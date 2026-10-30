#include "faradix/engine.hpp"
#include "faradix/simulated_device.hpp"
#include "faradix/snapshot_writer.hpp"

#include <chrono>
#include <csignal>
#include <cstdlib>
#include <exception>
#include <iomanip>
#include <iostream>
#include <memory>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>

namespace {

volatile std::sig_atomic_t stop_requested = 0;
void stop_handler(int) { stop_requested = 1; }

struct Options {
    std::size_t steps = 0; // Zero means continuous.
    int period_ms = 1000;
    double step_seconds = 1.0;
    double baseline_drive = 0.5;
    std::string snapshot_path;
};

std::string value_for(int& index, int argc, char** argv) {
    if (++index >= argc) throw std::invalid_argument("Missing option value");
    return argv[index];
}

Options parse_options(int argc, char** argv) {
    Options options;
    for (int index = 1; index < argc; ++index) {
        const std::string option = argv[index];
        if (option == "--help") {
            std::cout << "Usage: faradix_engine [--steps 1..1000000] [--dt-s seconds] "
                         "[--baseline-drive 0..1] [--period-ms 0..60000] [--snapshot path]\n"
                         "Default: continuous, 1 simulation second per step, 1 wall second between steps.\n";
            std::exit(0);
        }
        if (option == "--steps") {
            const auto value = value_for(index, argc, argv);
            std::size_t parsed = 0;
            const auto count = std::stoull(value, &parsed);
            if (parsed != value.size() || count == 0 || count > 1000000) throw std::invalid_argument("Invalid --steps");
            options.steps = static_cast<std::size_t>(count);
        } else if (option == "--period-ms") {
            const auto value = value_for(index, argc, argv);
            std::size_t parsed = 0;
            const auto period = std::stoi(value, &parsed);
            if (parsed != value.size() || period < 0 || period > 60000) throw std::invalid_argument("Invalid --period-ms");
            options.period_ms = period;
        } else if (option == "--dt-s" || option == "--baseline-drive") {
            const auto value = value_for(index, argc, argv);
            std::size_t parsed = 0;
            const auto number = std::stod(value, &parsed);
            if (parsed != value.size()) throw std::invalid_argument("Invalid numeric option");
            if (option == "--dt-s") options.step_seconds = number;
            else options.baseline_drive = number;
        } else if (option == "--snapshot") {
            options.snapshot_path = value_for(index, argc, argv);
        } else {
            throw std::invalid_argument("Unknown option: " + option);
        }
    }
    if (options.steps == 0 && options.period_ms == 0) {
        throw std::invalid_argument("Continuous mode requires a positive wall period");
    }
    return options;
}

std::string make_run_id() {
    const auto now = std::chrono::system_clock::now().time_since_epoch().count();
    std::random_device random;
    std::ostringstream value;
    value << std::hex << now << '-' << random() << random();
    return value.str();
}

} // namespace

int main(int argc, char** argv) {
    try {
        const auto options = parse_options(argc, argv);
        faradix::SimulatedDevice device;
        faradix::Engine engine(device, {options.step_seconds, options.baseline_drive});
        const auto run_id = make_run_id();
        std::unique_ptr<faradix::SnapshotWriter> writer;
        if (!options.snapshot_path.empty()) {
            writer = std::make_unique<faradix::SnapshotWriter>(options.snapshot_path, run_id);
        }
        std::signal(SIGINT, stop_handler);
        std::signal(SIGTERM, stop_handler);
        std::cout << "Uncalibrated development simulation; no physical operating limits or hard real-time guarantee.\n"
                  << "run_id=" << run_id << " dt_s=" << options.step_seconds
                  << " baseline_drive=" << options.baseline_drive << '\n';
        auto next_wall_tick = std::chrono::steady_clock::now();
        std::size_t executed = 0;
        while (!stop_requested && (options.steps == 0 || executed < options.steps)) {
            const auto result = engine.step();
            const auto measured_at = std::chrono::system_clock::now();
            if (writer) {
                try {
                    writer->write(result.state, measured_at);
                } catch (const std::exception& error) {
                    std::cerr << "Snapshot export failed: " << error.what() << '\n';
                }
            }
            const auto& state = result.state;
            std::cout << std::fixed << std::setprecision(3)
                      << "sample=" << state.sample_sequence
                      << " simulation_time_s=" << state.simulation_time_s
                      << " drive=" << options.baseline_drive
                      << " voltage_v=" << state.measurements.stack_voltage_v
                      << " current_a=" << state.measurements.stack_current_a
                      << " temperature_c=" << state.measurements.electrolyte_temperature_c << std::endl;
            ++executed;
            if (options.period_ms > 0 && (options.steps == 0 || executed < options.steps)) {
                next_wall_tick += std::chrono::milliseconds(options.period_ms);
                // Check signals during the wait so a long wall period does not delay shutdown.
                while (!stop_requested) {
                    const auto now = std::chrono::steady_clock::now();
                    if (now >= next_wall_tick) break;
                    const auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(next_wall_tick - now);
                    std::this_thread::sleep_for(remaining > std::chrono::milliseconds(50)
                        ? std::chrono::milliseconds(50) : remaining);
                }
            }
        }
        std::cout << "Stopped after " << executed << " steps (simulation_time_s="
                  << engine.current().simulation_time_s << ").\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Engine error: " << error.what() << '\n';
        return 2;
    }
}
