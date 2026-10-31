#include "faradix/development_json.hpp"

#include <chrono>
#include <cmath>
#include <ctime>
#include <iomanip>
#include <ostream>
#include <sstream>
#include <stdexcept>

namespace faradix {

void validate_output_sample(const DeviceState& state) {
    const auto& measurements = state.measurements;
    if (state.sample_sequence == 0 || !std::isfinite(state.simulation_time_s) ||
        !std::isfinite(measurements.stack_voltage_v) ||
        !std::isfinite(measurements.stack_current_a) ||
        !std::isfinite(measurements.electrolyte_temperature_c)) {
        throw std::invalid_argument("Cannot serialize non-finite or unstepped development sample");
    }
}

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

void write_measurements_json(std::ostream& output, const Measurements& measurements) {
    output << "\"stack_voltage_v\":" << measurements.stack_voltage_v
           << ",\"stack_current_a\":" << measurements.stack_current_a
           << ",\"electrolyte_temperature_c\":" << measurements.electrolyte_temperature_c;
}

} // namespace faradix
