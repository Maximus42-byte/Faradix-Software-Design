#include "faradix/simulated_device.hpp"

#include <cmath>
#include <stdexcept>

namespace faradix {

Measurements SimulatedDevice::measure() const {
    const double current_a = 20.0 * drive_fraction_;
    const double voltage_v = 40.0 + 0.5 * current_a + 0.01 * (temperature_c_ - 25.0);
    return Measurements{voltage_v, current_a, temperature_c_};
}

void SimulatedDevice::advance(double step_seconds, AdmittedCommand command) {
    if (!std::isfinite(step_seconds) || step_seconds <= 0.0 ||
        !std::isfinite(command.drive_fraction) || command.drive_fraction < 0.0 || command.drive_fraction > 1.0) {
        throw std::invalid_argument("Invalid toy plant step");
    }
    const double current_a = 20.0 * command.drive_fraction;
    // Explicit Euler: heating from current squared, cooling toward 25 C.
    temperature_c_ += step_seconds * (0.002 * current_a * current_a - 0.08 * (temperature_c_ - 25.0));
    drive_fraction_ = command.drive_fraction;
}

} // namespace faradix
