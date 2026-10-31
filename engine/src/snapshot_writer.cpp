#include "faradix/snapshot_writer.hpp"
#include "faradix/development_json.hpp"

#include <chrono>
#include <fstream>
#include <iomanip>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <system_error>

namespace faradix {

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
    const auto temporary = std::filesystem::path(path_.string() + ".tmp." + run_id_);
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
        std::filesystem::rename(temporary, path_);
        last_measurement_time_ = measured_at;
    } catch (...) {
        std::error_code ignored;
        std::filesystem::remove(temporary, ignored);
        throw;
    }
}

} // namespace faradix
