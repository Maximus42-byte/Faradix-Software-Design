#include "faradix/engine.hpp"

#include <cmath>
#include <limits>
#include <stdexcept>

namespace faradix {
namespace {

bool admit(RequestedCommand request, AdmittedCommand& admitted) {
    // A toy software admission range, not a validated physical operating envelope.
    if (!std::isfinite(request.drive_fraction) || request.drive_fraction < 0.0 || request.drive_fraction > 1.0) {
        return false;
    }
    admitted = AdmittedCommand{request.drive_fraction};
    return true;
}

} // namespace

Engine::Engine(Device& device, EngineConfig config) : device_(device), config_(config) {
    if (!std::isfinite(config.step_seconds) || config.step_seconds <= 0.0 ||
        !std::isfinite(config.baseline_drive_fraction) || config.baseline_drive_fraction < 0.0 ||
        config.baseline_drive_fraction > 1.0) {
        throw std::invalid_argument("Invalid development engine configuration");
    }
}

StepResult Engine::step() {
    return step(RequestedCommand{config_.baseline_drive_fraction});
}

StepResult Engine::step(RequestedCommand request) {
    AdmittedCommand command{};
    if (!admit(request, command)) {
        return StepResult{false, current()};
    }
    if (sequence_ == std::numeric_limits<std::uint64_t>::max()) {
        throw std::overflow_error("Simulation sequence exhausted");
    }
    device_.advance(config_.step_seconds, command);
    simulation_time_s_ += config_.step_seconds;
    ++sequence_;
    return StepResult{true, current()};
}

std::size_t Engine::run_steps(std::size_t count, const std::function<void(const StepResult&)>& on_step) {
    for (std::size_t index = 0; index < count; ++index) {
        on_step(step());
    }
    return count;
}

DeviceState Engine::current() const {
    return DeviceState{device_.measure(), simulation_time_s_, sequence_};
}

} // namespace faradix
