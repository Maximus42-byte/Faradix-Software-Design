#include "faradix/engine.hpp"
#include "faradix/simulated_device.hpp"

#include <cassert>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace {

bool near(double left, double right) { return std::abs(left - right) < 1e-9; }

class RecordingDevice final : public faradix::Device {
public:
    faradix::Measurements measure() const override { return {40.0, applied_drive_ * 20.0, 25.0}; }
    void advance(double seconds, faradix::AdmittedCommand command) override {
        assert(near(seconds, 0.25));
        applied_drive_ = command.drive_fraction;
        ++calls;
    }
    int calls = 0;
private:
    double applied_drive_ = 0.0;
};

void deterministic_simulation() {
    faradix::SimulatedDevice first;
    faradix::SimulatedDevice second;
    faradix::Engine a(first, {1.0, 0.5});
    faradix::Engine b(second, {1.0, 0.5});
    for (int index = 1; index <= 5; ++index) {
        const auto left = a.step().state;
        const auto right = b.step().state;
        assert(left.sample_sequence == static_cast<unsigned>(index));
        assert(near(left.simulation_time_s, index));
        assert(near(left.measurements.stack_voltage_v, right.measurements.stack_voltage_v));
        assert(near(left.measurements.stack_current_a, right.measurements.stack_current_a));
        assert(near(left.measurements.electrolyte_temperature_c, right.measurements.electrolyte_temperature_c));
        assert(near(left.measurements.stack_current_a, 10.0));
        if (index == 1) {
            assert(near(left.measurements.electrolyte_temperature_c, 25.2));
            assert(near(left.measurements.stack_voltage_v, 45.002));
        }
    }
}

void command_admission_and_device_boundary() {
    RecordingDevice device;
    faradix::Engine engine(device, {0.25, 0.3});
    const auto accepted = engine.step(faradix::RequestedCommand{0.7});
    assert(accepted.admitted && device.calls == 1);
    assert(near(accepted.state.measurements.stack_current_a, 14.0));
    const auto rejected = engine.step(faradix::RequestedCommand{std::numeric_limits<double>::quiet_NaN()});
    assert(!rejected.admitted && device.calls == 1 && rejected.state.sample_sequence == 1);
    assert(!engine.step(faradix::RequestedCommand{1.1}).admitted);
    assert(device.calls == 1);
}

void bounded_steps() {
    faradix::SimulatedDevice device;
    faradix::Engine engine(device, {0.5, 0.2});
    int callbacks = 0;
    assert(engine.run_steps(4, [&](const faradix::StepResult& result) {
        assert(result.admitted);
        ++callbacks;
        assert(result.state.sample_sequence == static_cast<unsigned>(callbacks));
    }) == 4);
    assert(callbacks == 4);
    assert(near(engine.current().simulation_time_s, 2.0));
    assert(engine.run_steps(0, [&](const faradix::StepResult&) { assert(false); }) == 0);
    assert(engine.current().sample_sequence == 4);
    bool rejected_config = false;
    try { faradix::Engine invalid(device, {0.0, 0.5}); }
    catch (const std::invalid_argument&) { rejected_config = true; }
    assert(rejected_config);
}

} // namespace

int main() {
    deterministic_simulation();
    command_admission_and_device_boundary();
    bounded_steps();
}
