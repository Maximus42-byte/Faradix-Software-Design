#include "faradix/recording_writer.hpp"
#include "faradix/development_json.hpp"

#include <cerrno>
#include <fcntl.h>
#include <iomanip>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <system_error>
#include <unistd.h>
#include <utility>

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

} // namespace

RecordingWriter::RecordingWriter(std::filesystem::path path, std::string run_id)
    : path_(std::move(path)), run_id_(std::move(run_id)) {
    if (path_.empty() || !safe_run_id(run_id_)) {
        throw std::invalid_argument("Development recording requires a path and safe run ID");
    }
    if (!path_.parent_path().empty()) {
        std::filesystem::create_directories(path_.parent_path());
    }
    descriptor_ = ::open(path_.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (descriptor_ < 0) {
        throw std::system_error(errno, std::generic_category(),
                                "Cannot create development recording without overwriting " + path_.string());
    }
}

RecordingWriter::~RecordingWriter() noexcept {
    if (descriptor_ >= 0) ::close(descriptor_);
}

void RecordingWriter::write_line(const std::string& line) {
    std::size_t offset = 0;
    while (offset < line.size()) {
        const auto written = ::write(descriptor_, line.data() + offset, line.size() - offset);
        if (written < 0 && errno == EINTR) continue;
        if (written <= 0) {
            const int error = written == 0 ? EIO : errno;
            throw std::system_error(error, std::generic_category(),
                                    "Cannot write development recording " + path_.string());
        }
        offset += static_cast<std::size_t>(written);
    }
    if (::fdatasync(descriptor_) != 0) {
        throw std::system_error(errno, std::generic_category(),
                                "Cannot flush development recording " + path_.string());
    }
}

void RecordingWriter::write(const DeviceState& state, std::chrono::system_clock::time_point measured_at) {
    if (finished_ || descriptor_ < 0) throw std::logic_error("Development recording is closed");
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
    if (finished_ || descriptor_ < 0) throw std::logic_error("Development recording is closed");
    const auto footer_offset = ::lseek(descriptor_, 0, SEEK_CUR);
    if (footer_offset < 0) {
        throw std::system_error(errno, std::generic_category(),
                                "Cannot position development recording " + path_.string());
    }
    std::ostringstream json;
    json << "{\"record_version\":\"1\",\"record_type\":\"completion\",\"run_id\":\"" << run_id_
         << "\",\"sample_count\":" << sample_count_
         << ",\"last_sample_sequence\":" << last_sequence_
         << ",\"status\":\"cleanly_stopped\"}\n";
    try {
        write_line(json.str());
    } catch (...) {
        // Keep valid sample lines available if appending the footer fails.
        ::ftruncate(descriptor_, footer_offset);
        throw;
    }
    const int descriptor = std::exchange(descriptor_, -1);
    if (::close(descriptor) != 0) {
        const int close_error = errno;
        // A failed close cannot certify a complete file. Best effort removes the footer.
        const int retry = ::open(path_.c_str(), O_WRONLY | O_CLOEXEC | O_NOFOLLOW);
        if (retry >= 0) {
            ::ftruncate(retry, footer_offset);
            ::close(retry);
        }
        throw std::system_error(close_error, std::generic_category(),
                                "Cannot close development recording " + path_.string());
    }
    finished_ = true;
}

} // namespace faradix
