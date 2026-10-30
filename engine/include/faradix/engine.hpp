#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>

namespace faradix {

// Development-domain quantities; field names carry units. No equipment limits are inferred.
struct Measurements {
    double stack_voltage_v;
    double stack_current_a;
    double electrolyte_temperature_c;
};

struct DeviceState {
    Measurements measurements;
    double simulation_time_s;
    std::uint64_t sample_sequence;
};

struct RequestedCommand {
    double drive_fraction; // Dimensionless toy input, nominally 0..1.
};

struct AdmittedCommand {
    double drive_fraction;
};

class Device {
public:
    virtual ~Device() = default;
    virtual Measurements measure() const = 0;
    virtual void advance(double step_seconds, AdmittedCommand command) = 0;
};

struct EngineConfig {
    double step_seconds = 1.0;
    double baseline_drive_fraction = 0.5;
};

struct StepResult {
    bool admitted;
    DeviceState state;
};

class Engine {
public:
    Engine(Device& device, EngineConfig config);
    StepResult step();
    StepResult step(RequestedCommand request);
    std::size_t run_steps(std::size_t count, const std::function<void(const StepResult&)>& on_step);
    DeviceState current() const;

private:
    Device& device_;
    EngineConfig config_;
    double simulation_time_s_ = 0.0;
    std::uint64_t sequence_ = 0;
};

} // namespace faradix
