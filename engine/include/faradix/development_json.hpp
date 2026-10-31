#pragma once

#include "faradix/engine.hpp"

#include <chrono>
#include <iosfwd>
#include <string>

namespace faradix {

// Shared development-output formatting, outside the reusable engine core.
void validate_output_sample(const DeviceState& state);
std::string utc_timestamp(std::chrono::system_clock::time_point point);
void write_measurements_json(std::ostream& output, const Measurements& measurements);

} // namespace faradix
