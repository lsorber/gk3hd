#pragma once

#include <array>
#include <cstdint>
#include <cstring>
#include <limits>
#include <memory>
#include <vector>

namespace gk3hd::vr {

struct WorldVertex { float xyz[3], uv[2]; };
static_assert(sizeof(WorldVertex) == 20);

// The owner supplies a scene/resource lifetime, independently of address reuse.
// Shape words alone cannot distinguish a reloaded object at the same address.
struct WorldGeometryIdentity {
  uint32_t root = 0;
  uint64_t lifetime = 0;
  std::array<uint32_t, 9> shape{};

  static WorldGeometryIdentity native(uint32_t address, uint64_t epoch,
                                      const std::array<uint8_t, 0x150>& header) {
    WorldGeometryIdentity result;
    result.root = address; result.lifetime = epoch;
    constexpr std::array<unsigned, 9> offsets = {
      0, 0xe8, 0xec, 0xf0, 0xfc, 0x120, 0x130, 0x144, 0x148};
    for (size_t i = 0; i < offsets.size(); ++i)
      std::memcpy(&result.shape[i], header.data() + offsets[i], 4);
    return result;
  }
  bool operator==(const WorldGeometryIdentity& other) const {
    return root == other.root && lifetime == other.lifetime && shape == other.shape;
  }
};

struct WorldGeometry {
  std::vector<WorldVertex> vertices;
  std::vector<uint16_t> indices;
  std::vector<std::array<uint32_t, 2>> primitives;
};

enum class WorldPreparation { Reused, Rebuilt, Unsupported };

// CPU source preparation only. Rendering/queue ownership remains with the
// caller. Returned shared snapshots can outlive cache invalidation; no GPU
// idle or resource destruction is implied by preparing another generation.
class WorldGeometryCache {
public:
  static constexpr uint64_t keyBase = 0x47574b0000000000ull;

  void invalidate() { geometry_.reset(); key_ = 0; identity_ = {}; }
  uint64_t key() const { return key_; }
  std::shared_ptr<const WorldGeometry> snapshot() const { return geometry_; }

  template<class Read>
  WorldPreparation prepare(const WorldGeometryIdentity& identity, Read read) {
    if (geometry_ && identity == identity_) return WorldPreparation::Reused;
    // Never expose an old source as ready for a newly requested identity.
    // Build separately so failed reads cannot publish partially decoded data.
    invalidate();
    const uint32_t nv = identity.shape[5], ns = identity.shape[6];
    if (!identity.root || nv < 3 || nv > 65535 || !ns || ns > 65535 ||
        serial_ == (std::numeric_limits<uint64_t>::max)())
      return WorldPreparation::Unsupported;
    auto next = std::make_shared<WorldGeometry>();
    auto load = [&](uint32_t base, uint64_t offset, void* target, size_t size) {
      const uint64_t address = uint64_t(base) + offset;
      if (!base || !size || address > UINT32_MAX || size > UINT32_MAX - address)
        return false;
      return read(static_cast<uint32_t>(address), target, size);
    };
    std::vector<float> positions(size_t(nv) * 3), uv(size_t(nv) * 2);
    if (!load(identity.shape[1], 0, positions.data(), positions.size() * sizeof(float)) ||
        !load(identity.shape[3], 0, uv.data(), uv.size() * sizeof(float)))
      return WorldPreparation::Unsupported;
    next->vertices.resize(nv); next->primitives.resize(ns);
    for (uint32_t i = 0; i < nv; ++i) {
      std::memcpy(next->vertices[i].xyz, positions.data() + size_t(i) * 3, 12);
      std::memcpy(next->vertices[i].uv, uv.data() + size_t(i) * 2, 8);
    }
    std::vector<uint32_t> pointers(ns);
    if (!load(identity.shape[7], 0, pointers.data(), pointers.size() * sizeof(uint32_t)))
      return WorldPreparation::Unsupported;
    for (uint32_t sid = 0; sid < ns; ++sid) {
      std::array<uint8_t, 40> header{};
      if (!load(pointers[sid], 0, header.data(), header.size()))
        return WorldPreparation::Unsupported;
      uint32_t n = 0, triangles = 0;
      std::memcpy(&n, header.data() + 32, 4);
      std::memcpy(&triangles, header.data() + 36, 4);
      if (n < 3 || n > 4096 || !triangles || triangles > 8192 ||
          next->indices.size() + size_t(triangles) * 3 > 1000000)
        return WorldPreparation::Unsupported;
      std::vector<uint16_t> local(size_t(n) + size_t(triangles) * 3);
      if (!load(pointers[sid], 40, local.data(), local.size() * sizeof(uint16_t)))
        return WorldPreparation::Unsupported;
      next->primitives[sid] = {static_cast<uint32_t>(next->indices.size()), triangles * 3};
      for (uint32_t i = 0; i < triangles * 3; ++i) {
        const uint16_t index = local[n + i];
        if (index >= n || local[index] >= nv) return WorldPreparation::Unsupported;
        next->indices.push_back(local[index]);
      }
    }
    // Preserve the key namespace used by the renderer, but never reuse a key
    // after invalidation or a successful reload with identical counts.
    ++serial_;
    identity_ = identity; geometry_ = std::move(next); key_ = serial_;
    return WorldPreparation::Rebuilt;
  }
private:
  uint64_t serial_ = keyBase, key_ = 0;
  WorldGeometryIdentity identity_{};
  std::shared_ptr<const WorldGeometry> geometry_;
};
}
