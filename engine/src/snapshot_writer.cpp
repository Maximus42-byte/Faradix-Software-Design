#include "faradix/snapshot_writer.hpp"

#include <chrono>
#include <cmath>
#include <ctime>
#include <fstream>
#include <iomanip>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <system_error>

namespace faradix {
namespace {

std::string utc_timestamp(std::chrono::system_clock::time_point point) {
    using namespace std::chrono;
    const auto whole_seconds = floor<seconds>(point);
    const auto micros = duration_cast<microseconds>(point - whole_seconds).count();
    const std::time_t epoch_seconds = system_clock::to_time_t(whole_seconds);
    std::tm utc{};
    if (gmtime_r(&epoch_seconds, &utc) == nullptr) {
        throw std::runtime_error("Cannot format UTC measurement time");
    }
    std::ostringstream output;
    output << std::put_time(&utc, "%Y-%m-%dT%H:%M:%S") << '.'
           << std::setw(6) << std::setfill('0') << micros << 'Z';
    return output.str();
}

} // namespace

SnapshotWriter::SnapshotWriter(std::filesystem::path path, std::string run_id)
    : path_(std::move(path)), run_id_(std::move(run_id)) {
    if (path_.empty() || run_id_.empty()) {
        throw std::invalid_argument("Snapshot path and run ID are required");
    }
}

void SnapshotWriter::write(const DeviceState& state, std::chrono::system_clock::time_point measured_at) {
    const auto& m = state.measurements;
    if (state.sample_sequence == 0 || !std::isfinite(state.simulation_time_s) ||
        !std::isfinite(m.stack_voltage_v) || !std::isfinite(m.stack_current_a) ||
        !std::isfinite(m.electrolyte_temperature_c)) {
        throw std::invalid_argument("Cannot snapshot non-finite or unstepped state");
    }
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
         << "\",\"source\":\"simulated\",\"measurements\":{"
         << "\"stack_voltage_v\":" << m.stack_voltage_v
         << ",\"stack_current_a\":" << m.stack_current_a
         << ",\"electrolyte_temperature_c\":" << m.electrolyte_temperature_c
         << "}}\n";
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
