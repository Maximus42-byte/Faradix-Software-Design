#include "faradix/engine.hpp"
#include "faradix/recording_writer.hpp"
#include "faradix/simulated_device.hpp"

#include <cassert>
#include <cerrno>
#include <chrono>
#include <csignal>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <string>
#include <system_error>
#include <vector>
#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>

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

void bounded_recording_and_incomplete_prefix() {
    const auto unique = std::to_string(std::chrono::steady_clock::now().time_since_epoch().count());
    const auto path = std::filesystem::temp_directory_path() / ("faradix-recording-" + unique + ".jsonl");
    faradix::SimulatedDevice device;
    faradix::Engine engine(device, {0.5, 0.2});
    const auto epoch = std::chrono::system_clock::time_point{std::chrono::seconds(1700000000)};
    {
        faradix::RecordingWriter recorder(path, "test-run");
        engine.run_steps(4, [&](const faradix::StepResult& result) {
            recorder.write(result.state, epoch + std::chrono::seconds(result.state.sample_sequence));
        });
        recorder.finish();
    }
    std::ifstream input(path);
    std::vector<std::string> lines;
    for (std::string line; std::getline(input, line); ) lines.push_back(line);
    assert(lines.size() == 5);
    for (std::size_t index = 0; index < 4; ++index) {
        const auto& line = lines[index];
        assert(line.find("\"record_version\":\"1\",\"record_type\":\"sample\",\"run_id\":\"test-run\"") != std::string::npos);
        assert(line.find("\"sample_sequence\":" + std::to_string(index + 1)) != std::string::npos);
        assert(line.find("\"source\":\"simulated\",\"provenance\":\"development_simulation\"") != std::string::npos);
        assert(line.find("\"stack_voltage_v\":") != std::string::npos);
        assert(line.find("\"stack_current_a\":") != std::string::npos);
        assert(line.find("\"electrolyte_temperature_c\":") != std::string::npos);
        assert(line.find("Z\",\"source\"") != std::string::npos);
    }
    assert(lines.back() ==
        "{\"record_version\":\"1\",\"record_type\":\"completion\",\"run_id\":\"test-run\","
        "\"sample_count\":4,\"last_sample_sequence\":4,\"status\":\"cleanly_stopped\"}");
    bool exclusive_open_rejected = false;
    try { faradix::RecordingWriter duplicate(path, "test-run"); }
    catch (const std::system_error&) { exclusive_open_rejected = true; }
    assert(exclusive_open_rejected);
    std::filesystem::remove(path);

    const auto partial_path = std::filesystem::temp_directory_path() / ("faradix-partial-" + unique + ".jsonl");
    {
        faradix::RecordingWriter recorder(partial_path, "test-run");
        faradix::SimulatedDevice partial_device;
        faradix::Engine partial_engine(partial_device, {0.5, 0.2});
        recorder.write(partial_engine.step().state, epoch);
        // An interrupted experiment has no completion line.
    }
    std::ifstream partial_input(partial_path);
    std::string partial_line;
    assert(static_cast<bool>(std::getline(partial_input, partial_line)));
    assert(partial_line.find("\"record_type\":\"sample\"") != std::string::npos);
    assert(!static_cast<bool>(std::getline(partial_input, partial_line)));
    std::filesystem::remove(partial_path);
}

void recording_write_error_preserves_valid_prefix() {
    const auto unique = std::to_string(std::chrono::steady_clock::now().time_since_epoch().count());
    const auto path = std::filesystem::temp_directory_path() / ("faradix-write-error-" + unique + ".jsonl");
    const auto child = ::fork();
    assert(child >= 0);
    if (child == 0) {
        std::signal(SIGXFSZ, SIG_IGN);
        try {
            faradix::SimulatedDevice device;
            faradix::Engine engine(device, {0.5, 0.2});
            faradix::RecordingWriter recorder(path, "write-error-test");
            const auto now = std::chrono::system_clock::now();
            recorder.write(engine.step().state, now);
            struct rlimit limit{};
            if (::getrlimit(RLIMIT_FSIZE, &limit) != 0) ::_exit(2);
            limit.rlim_cur = static_cast<rlim_t>(std::filesystem::file_size(path));
            if (::setrlimit(RLIMIT_FSIZE, &limit) != 0) ::_exit(3);
            try {
                recorder.write(engine.step().state, now + std::chrono::seconds(1));
            } catch (const std::system_error& error) {
                ::_exit(error.code().value() == EFBIG ? 0 : 5);
            }
            ::_exit(4);
        } catch (...) {
            ::_exit(6);
        }
    }
    int status = 0;
    assert(::waitpid(child, &status, 0) == child);
    assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);
    std::ifstream input(path);
    std::string line;
    assert(static_cast<bool>(std::getline(input, line)));
    assert(line.find("\"record_type\":\"sample\"") != std::string::npos);
    assert(!static_cast<bool>(std::getline(input, line)));
    std::filesystem::remove(path);
}

} // namespace

int main() {
    deterministic_simulation();
    command_admission_and_device_boundary();
    bounded_steps();
    bounded_recording_and_incomplete_prefix();
    recording_write_error_preserves_valid_prefix();
}
