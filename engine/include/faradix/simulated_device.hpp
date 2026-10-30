#pragma once

#include "faradix/engine.hpp"

namespace faradix {

// Uncalibrated toy plant. Hidden temperature and applied input stay inside the adapter.
class SimulatedDevice final : public Device {
public:
    Measurements measure() const override;
    void advance(double step_seconds, AdmittedCommand command) override;

private:
    double temperature_c_ = 25.0;
    double drive_fraction_ = 0.0;
};

} // namespace faradix
