#include "faradix/recording_writer.hpp"
#include "faradix/development_json.hpp"

#include <algorithm>
#include <cerrno>
#include <iomanip>
#include <limits>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <system_error>
#include <utility>

#ifdef _WIN32
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <fcntl.h>
#include <unistd.h>
#endif

namespace faradix {
namespace {

bool safe_run_id(const std::string& value) {
    if (value.empty()) return false;
    for (const unsigned char character : value) {
        if ((character >= 'a' && character <= 'z') ||
            (character >= 'A' && character <= 'Z') ||
            (character >= '0' && character <= '9') ||
            character == '-' || character == '_') continue;
        return false;
    }
    return true;
}

#ifdef _WIN32
std::system_error file_error(DWORD code, const char* operation) {
    return {static_cast<int>(code), std::system_category(), operation};
}

void truncate_footer(HANDLE descriptor, LARGE_INTEGER offset) noexcept {
    if (SetFilePointerEx(descriptor, offset, nullptr, FILE_BEGIN) && SetEndOfFile(descriptor)) {
        FlushFileBuffers(descriptor);
    }
}
#endif

} // namespace

RecordingWriter::RecordingWriter(std::filesystem::path path, std::string run_id)
    : path_(std::move(path)), run_id_(std::move(run_id)) {
    if (path_.empty() || !safe_run_id(run_id_)) {
        throw std::invalid_argument("Development recording requires a path and safe run ID");
    }
    if (!path_.parent_path().empty()) {
        std::filesystem::create_directories(path_.parent_path());
    }
#ifdef _WIN32
    const HANDLE descriptor = CreateFileW(path_.c_str(), GENERIC_WRITE,
                                           FILE_SHARE_READ | FILE_SHARE_DELETE, nullptr,
                                           CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (descriptor == INVALID_HANDLE_VALUE) {
        throw file_error(GetLastError(), "Cannot create development recording without overwriting");
    }
    descriptor_ = descriptor;
#else
    descriptor_ = ::open(path_.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (descriptor_ < 0) {
        throw std::system_error(errno, std::generic_category(),
                                "Cannot create development recording without overwriting " + path_.string());
    }
#endif
}

RecordingWriter::~RecordingWriter() noexcept {
#ifdef _WIN32
    if (descriptor_ != nullptr) CloseHandle(static_cast<HANDLE>(descriptor_));
#else
    if (descriptor_ >= 0) ::close(descriptor_);
#endif
}

void RecordingWriter::write_line(const std::string& line) {
    std::size_t offset = 0;
    while (offset < line.size()) {
#ifdef _WIN32
        const auto remaining = std::min(line.size() - offset,
                                        static_cast<std::size_t>(std::numeric_limits<DWORD>::max()));
        DWORD written = 0;
        if (!WriteFile(static_cast<HANDLE>(descriptor_), line.data() + offset,
                       static_cast<DWORD>(remaining), &written, nullptr)) {
            throw file_error(GetLastError(), "Cannot write development recording");
        }
        if (written == 0) throw std::runtime_error("Cannot write development recording: zero bytes written");
        offset += written;
#else
        const auto written = ::write(descriptor_, line.data() + offset, line.size() - offset);
        if (written < 0 && errno == EINTR) continue;
        if (written <= 0) {
            const int error = written == 0 ? EIO : errno;
            throw std::system_error(error, std::generic_category(),
                                    "Cannot write development recording " + path_.string());
        }
        offset += static_cast<std::size_t>(written);
#endif
    }
#ifdef _WIN32
    if (!FlushFileBuffers(static_cast<HANDLE>(descriptor_))) {
        throw file_error(GetLastError(), "Cannot flush development recording");
    }
#else
    if (::fdatasync(descriptor_) != 0) {
        throw std::system_error(errno, std::generic_category(),
                                "Cannot flush development recording " + path_.string());
    }
#endif
}

void RecordingWriter::write(const DeviceState& state, std::chrono::system_clock::time_point measured_at) {
#ifdef _WIN32
    if (finished_ || descriptor_ == nullptr) throw std::logic_error("Development recording is closed");
#else
    if (finished_ || descriptor_ < 0) throw std::logic_error("Development recording is closed");
#endif
    validate_output_sample(state);
    if (state.sample_sequence != last_sequence_ + 1) {
        throw std::invalid_argument("Development recording sample sequence must be contiguous and increasing");
    }
    std::ostringstream json;
    json.imbue(std::locale::classic());
    json << std::setprecision(17)
         << "{\"record_version\":\"1\",\"record_type\":\"sample\",\"run_id\":\"" << run_id_
         << "\",\"sample_sequence\":" << state.sample_sequence
         << ",\"simulation_time_s\":" << state.simulation_time_s
         << ",\"measured_at\":\"" << utc_timestamp(measured_at)
         << "\",\"source\":\"simulated\",\"provenance\":\"development_simulation\",\"measurements\":{";
    write_measurements_json(json, state.measurements);
    json << "}}\n";
    write_line(json.str());
    ++sample_count_;
    last_sequence_ = state.sample_sequence;
}

void RecordingWriter::finish() {
#ifdef _WIN32
    if (finished_ || descriptor_ == nullptr) throw std::logic_error("Development recording is closed");
    LARGE_INTEGER zero{};
    LARGE_INTEGER footer_offset{};
    if (!SetFilePointerEx(static_cast<HANDLE>(descriptor_), zero, &footer_offset, FILE_CURRENT)) {
        throw file_error(GetLastError(), "Cannot position development recording");
    }
#else
    if (finished_ || descriptor_ < 0) throw std::logic_error("Development recording is closed");
    const auto footer_offset = ::lseek(descriptor_, 0, SEEK_CUR);
    if (footer_offset < 0) {
        throw std::system_error(errno, std::generic_category(),
                                "Cannot position development recording " + path_.string());
    }
#endif
    std::ostringstream json;
    json << "{\"record_version\":\"1\",\"record_type\":\"completion\",\"run_id\":\"" << run_id_
         << "\",\"sample_count\":" << sample_count_
         << ",\"last_sample_sequence\":" << last_sequence_
         << ",\"status\":\"cleanly_stopped\"}\n";
    try {
        write_line(json.str());
    } catch (...) {
        // Keep valid sample lines available if appending the footer fails.
#ifdef _WIN32
        truncate_footer(static_cast<HANDLE>(descriptor_), footer_offset);
#else
        if (::ftruncate(descriptor_, footer_offset) != 0) {
            // The original write/flush error still propagates; inspection will flag any fragment.
        }
#endif
        throw;
    }
#ifdef _WIN32
    const HANDLE descriptor = static_cast<HANDLE>(std::exchange(descriptor_, nullptr));
    if (!CloseHandle(descriptor)) {
        const DWORD close_error = GetLastError();
        // A failed close cannot certify a complete file. Best effort removes the footer.
        const HANDLE retry = CreateFileW(path_.c_str(), GENERIC_WRITE,
                                         FILE_SHARE_READ | FILE_SHARE_DELETE, nullptr,
                                         OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (retry != INVALID_HANDLE_VALUE) {
            truncate_footer(retry, footer_offset);
            CloseHandle(retry);
        }
        throw file_error(close_error, "Cannot close development recording");
    }
#else
    const int descriptor = std::exchange(descriptor_, -1);
    if (::close(descriptor) != 0) {
        const int close_error = errno;
        // A failed close cannot certify a complete file. Best effort removes the footer.
        const int retry = ::open(path_.c_str(), O_WRONLY | O_CLOEXEC | O_NOFOLLOW);
        if (retry >= 0) {
            if (::ftruncate(retry, footer_offset) != 0) {
                // The close error still propagates; inspection will flag any fragment.
            }
            ::close(retry);
        }
        throw std::system_error(close_error, std::generic_category(),
                                "Cannot close development recording " + path_.string());
    }
#endif
    finished_ = true;
}

} // namespace faradix
