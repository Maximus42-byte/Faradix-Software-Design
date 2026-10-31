#include "faradix/snapshot_writer.hpp"
#include "faradix/development_json.hpp"

#include <chrono>
#include <fstream>
#include <iomanip>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <system_error>
#include <thread>
#ifdef _WIN32
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

namespace faradix {
namespace {

void replace_snapshot(const std::filesystem::path& temporary, const std::filesystem::path& destination) {
#ifdef _WIN32
    // A bridge reader can briefly hold the previous file without delete sharing.
    // Retry that transient case; never delete the old snapshot before replacement.
    for (int attempt = 0; attempt < 10; ++attempt) {
        if (MoveFileExW(temporary.c_str(), destination.c_str(),
                        MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) return;
        const DWORD error = GetLastError();
        if ((error != ERROR_SHARING_VIOLATION && error != ERROR_LOCK_VIOLATION &&
             error != ERROR_ACCESS_DENIED) || attempt == 9) {
            throw std::system_error(static_cast<int>(error), std::system_category(),
                                    "Cannot replace development snapshot");
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
#else
    std::filesystem::rename(temporary, destination);
#endif
}

} // namespace

SnapshotWriter::SnapshotWriter(std::filesystem::path path, std::string run_id)
    : path_(std::move(path)), run_id_(std::move(run_id)) {
    if (path_.empty() || run_id_.empty()) {
        throw std::invalid_argument("Snapshot path and run ID are required");
    }
}

void SnapshotWriter::write(const DeviceState& state, std::chrono::system_clock::time_point measured_at) {
    validate_output_sample(state);
    // Preserve strictly increasing UTC times for fast bounded runs with identical clock ticks.
    if (measured_at <= last_measurement_time_) {
        measured_at = last_measurement_time_ + std::chrono::microseconds(1);
    }
    if (!path_.parent_path().empty()) {
        std::filesystem::create_directories(path_.parent_path());
    }
    auto temporary = path_;
    temporary += ".tmp." + run_id_;
    std::ostringstream json;
    json.imbue(std::locale::classic());
    json << std::setprecision(17)
         << "{\"snapshot_version\":\"1\",\"run_id\":\"" << run_id_
         << "\",\"sample_sequence\":" << state.sample_sequence
         << ",\"simulation_time_s\":" << state.simulation_time_s
         << ",\"measured_at\":\"" << utc_timestamp(measured_at)
         << "\",\"source\":\"simulated\",\"measurements\":{";
    write_measurements_json(json, state.measurements);
    json << "}}\n";
    try {
        std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
        output.exceptions(std::ios::failbit | std::ios::badbit);
        output << json.str();
        output.close();
        replace_snapshot(temporary, path_);
        last_measurement_time_ = measured_at;
    } catch (...) {
        std::error_code ignored;
        std::filesystem::remove(temporary, ignored);
        throw;
    }
}

} // namespace faradix
