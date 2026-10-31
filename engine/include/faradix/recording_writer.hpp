#pragma once

#include "faradix/engine.hpp"

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <string>

namespace faradix {

// Optional local JSON Lines output adapter for development experiments.
class RecordingWriter {
public:
    RecordingWriter(std::filesystem::path path, std::string run_id);
    ~RecordingWriter() noexcept;

    RecordingWriter(const RecordingWriter&) = delete;
    RecordingWriter& operator=(const RecordingWriter&) = delete;

    void write(const DeviceState& state, std::chrono::system_clock::time_point measured_at);
    void finish();

private:
    void write_line(const std::string& line);

    std::filesystem::path path_;
    std::string run_id_;
    int descriptor_ = -1;
    std::uint64_t sample_count_ = 0;
    std::uint64_t last_sequence_ = 0;
    bool finished_ = false;
};

} // namespace faradix
