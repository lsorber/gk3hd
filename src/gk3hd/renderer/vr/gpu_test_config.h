#pragma once

#include <array>
#include <cstdint>
#include <string_view>

namespace gk3hd::vr {

// Development fixture only. Default pixel tests stay small and deterministic,
// while no-readback profiling can exercise realistic stereo pixel workloads.
constexpr std::array<uint32_t, 2> testEyeSize(std::string_view value) {
  if (value.empty()) return {256, 256};
  std::array<uint32_t, 2> result{};
  size_t cursor = 0;
  for (unsigned dimension = 0; dimension < 2; ++dimension) {
    const size_t first = cursor;
    while (cursor < value.size() && value[cursor] >= '0' && value[cursor] <= '9') {
      result[dimension] = result[dimension]*10 + uint32_t(value[cursor++]-'0');
      if (result[dimension] > 4096) return {};
    }
    if (cursor == first || result[dimension] < 64) return {};
    if (!dimension && (cursor == value.size() || value[cursor++] != 'x')) return {};
  }
  return cursor == value.size() ? result : std::array<uint32_t, 2>{};
}

} // namespace gk3hd::vr
