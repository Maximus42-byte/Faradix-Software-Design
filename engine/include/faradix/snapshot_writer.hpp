#pragma once

#include "faradix/engine.hpp"

#include <chrono>
#include <filesystem>
#include <string>

namespace faradix {

// Development transport adapter; deliberately outside the engine core.
class SnapshotWriter {
public:
    SnapshotWriter(std::filesystem::path path, std::string run_id);
    void write(const DeviceState& state, std::chrono::system_clock::time_point measured_at);

private:
    std::filesystem::path path_;
    std::string run_id_;
    std::chrono::system_clock::time_point last_measurement_time_{};
};

} // namespace faradix
