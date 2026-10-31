#include "faradix/engine.hpp"
#include "faradix/recording_writer.hpp"
#include "faradix/simulated_device.hpp"
#include "faradix/snapshot_writer.hpp"

#include <chrono>
#include <filesystem>
#include <system_error>
#ifdef _WIN32
#include <atomic>
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif
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

#ifdef _WIN32
std::atomic_bool stop_requested{false};
BOOL WINAPI stop_handler(DWORD event) {
    if (event == CTRL_C_EVENT || event == CTRL_BREAK_EVENT) {
        stop_requested.store(true, std::memory_order_relaxed);
        return TRUE;
    }
    // Console close and forced process termination do not certify a clean stop.
    return FALSE;
}
bool should_stop() { return stop_requested.load(std::memory_order_relaxed); }
#else
volatile std::sig_atomic_t stop_requested = 0;
void stop_handler(int) { stop_requested = 1; }
bool should_stop() { return stop_requested != 0; }
#endif

bool stop_file_requested(const std::string& path) {
    if (path.empty()) return false;
    std::error_code error;
    const bool exists = std::filesystem::exists(path, error);
    if (error) throw std::system_error(error, "Cannot check development stop request");
    return exists;
}

struct Options {
    std::size_t steps = 0; // Zero means continuous.
    int period_ms = 1000;
    double step_seconds = 1.0;
    double baseline_drive = 0.5;
    std::string snapshot_path;
    std::string recording_path;
    std::string stop_file_path;
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
                         "[--baseline-drive 0..1] [--period-ms 0..60000] [--snapshot path] "
                         "[--record-jsonl path] [--stop-file path]\n"
                         "Default: continuous, 1 simulation second per step, 1 wall second between steps.\n"
                         "--stop-file requests a clean stop when the path appears.\n";
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
        } else if (option == "--record-jsonl") {
            options.recording_path = value_for(index, argc, argv);
            if (options.recording_path.empty()) throw std::invalid_argument("Invalid --record-jsonl path");
        } else if (option == "--stop-file") {
            options.stop_file_path = value_for(index, argc, argv);
            if (options.stop_file_path.empty()) throw std::invalid_argument("Invalid --stop-file path");
        } else {
            throw std::invalid_argument("Unknown option: " + option);
        }
    }
    if (options.steps == 0 && options.period_ms == 0) {
        throw std::invalid_argument("Continuous mode requires a positive wall period");
    }
    if (!options.stop_file_path.empty() &&
        (options.stop_file_path == options.snapshot_path ||
         options.stop_file_path == options.recording_path)) {
        throw std::invalid_argument("--stop-file must differ from output paths");
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
        std::unique_ptr<faradix::RecordingWriter> recorder;
        if (!options.recording_path.empty()) {
            try {
                recorder = std::make_unique<faradix::RecordingWriter>(options.recording_path, run_id);
            } catch (const std::exception& error) {
                std::cerr << "Development recording failed: " << error.what() << '\n';
                return 3;
            }
        }
#ifdef _WIN32
        if (!SetConsoleCtrlHandler(stop_handler, TRUE)) {
            // Headless runners can still request a clean stop through --stop-file.
            std::cerr << "Windows console stop handler unavailable; use --stop-file for graceful stop.\n";
        }
#else
        std::signal(SIGINT, stop_handler);
        std::signal(SIGTERM, stop_handler);
#endif
        std::cout << "Uncalibrated development simulation; no physical operating limits or hard real-time guarantee.\n"
                  << "run_id=" << run_id << " dt_s=" << options.step_seconds
                  << " baseline_drive=" << options.baseline_drive << '\n';
        auto next_wall_tick = std::chrono::steady_clock::now();
        std::size_t executed = 0;
        while (!should_stop() && !stop_file_requested(options.stop_file_path) &&
               (options.steps == 0 || executed < options.steps)) {
            const auto result = engine.step();
            const auto measured_at = std::chrono::system_clock::now();
            if (recorder) {
                try {
                    recorder->write(result.state, measured_at);
                } catch (const std::exception& error) {
                    std::cerr << "Development recording failed: " << error.what() << '\n';
                    return 3;
                }
            }
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
                // Check stop requests during the wait so a long wall period does not delay shutdown.
                while (!should_stop() && !stop_file_requested(options.stop_file_path)) {
                    const auto now = std::chrono::steady_clock::now();
                    if (now >= next_wall_tick) break;
                    const auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(next_wall_tick - now);
                    std::this_thread::sleep_for(remaining > std::chrono::milliseconds(50)
                        ? std::chrono::milliseconds(50) : remaining);
                }
            }
        }
        if (recorder) {
            try {
                recorder->finish();
            } catch (const std::exception& error) {
                std::cerr << "Development recording failed: " << error.what() << '\n';
                return 3;
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
