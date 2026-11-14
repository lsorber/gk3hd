#pragma once

#include <cstdint>
#include <vector>

namespace gk3hd::vr::world_batches {
struct Run { uint32_t first, count; bool opaque; };

// Color key and alpha test require discard-capable shading. Light mapping
// alone does not. Only consecutive draws may be combined, preserving depth
// and transparency order across the ordinary-draw fallback boundary.
inline bool eligible(uint32_t flags) { return (flags & 5u) == 0; }

template<typename Draw, typename Material>
std::vector<Run> partition(const Draw* draws, uint32_t count,
                           const Material* materials, bool enabled) {
  std::vector<Run> runs;
  runs.reserve(count);
  for (uint32_t i = 0; i < count; ++i) {
    const bool opaque = enabled && eligible(materials[draws[i].firstInstance >> 1].texturesFlags[2]);
    if (runs.empty() || runs.back().opaque != opaque) runs.push_back({i, 1, opaque});
    else ++runs.back().count;
  }
  return runs;
}
}
