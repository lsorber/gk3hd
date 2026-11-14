#pragma once
#include <cstdint>

namespace gk3hd::vr::world_bridge {
// S_FALSE rejects a known unsupported operation before a row is appended.
// Other failures cancel the frame rather than replaying over submitted work.
enum class Operation : uint32_t { Begin, Append, Submit, Cancel, AppendPrepared };
struct Request {
  uint32_t bytes, version, flags, reserved;
  uint64_t geometryKey;
  uint32_t vertexCount, indexCount, materialCount, drawCount, textureCount;
  const void* vertices;
  const uint16_t* indices;
  const void* materials;
  const float* matrices;
  const void* draws;
  void* const* textures;
};
struct Draw {
  uint32_t bytes, first, count, diffuse;
  float uv[4];
  uint32_t uniform;
};
struct Result { uint32_t bytes, draws, batches, maxTextures; };
} // namespace gk3hd::vr::world_bridge
