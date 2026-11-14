#pragma once
#include "world_bridge.h"
#include "world_geometry.h"

namespace gk3hd::vr {

// Addresses come from the verified executable profile and compiled loading
// bridge. Device presentation and headset selection are outside this adapter.
struct WorldAdapterConfig {
  uint32_t bytes, version, manager, formats, lifetime;
};
enum class WorldAction : uint32_t { Native, Handled, Failed };

class WorldAdapter {
public:
  struct SourceRange { uint32_t address; const void* expected; size_t bytes; };
  using Equal = bool (*)(void*, const SourceRange*, size_t);
  using Read = bool (*)(void*, uint32_t, void*, size_t);
  using Submit = int32_t (*)(void*, uint32_t, world_bridge::Operation, const void*);
  WorldAdapter(void* context, Read read, Submit submit, Equal equal = nullptr)
    : context_(context), read_(read), submit_(submit), equal_(equal) {}
  WorldAction begin(const WorldAdapterConfig&, uint32_t root) noexcept;
  WorldAction end(uint32_t root) noexcept;
  WorldAction draw(const std::array<uint32_t,8>& arguments, uint32_t surface) noexcept;
  WorldAction prepared(uint32_t root, uint32_t surface) noexcept;
  void cancel() noexcept;
private:
  struct Resource {
    uint32_t resource=0, bitmapTable=0, textureTable=0, count=0, bitmap=0, texture=0;
    std::array<uint8_t,80> header{};
    std::array<uint8_t,64> format{};
  };
  struct Signature { std::array<uint8_t,32> material{}; Resource base{}, light{}; };
  struct Prepared {
    bool valid=false;
    uint64_t drawPass=0, fastPass=0;
    world_bridge::Draw draw{};
    Signature signature{};
    std::array<SourceRange,15> ranges{};
    size_t rangeCount=0;
  };
  bool load(uint64_t, void*, size_t) const;
  bool resource(uint32_t, uint32_t, Resource&) const;
  bool signature(uint32_t, Signature&) const;
  bool comparisons(uint32_t, Prepared&);
  bool unchanged(uint32_t, const Prepared&) const;
  bool collect();
  void finish();
  WorldAction fallback(uint32_t);
  WorldAction fail() noexcept;
  void* context_;
  Read read_;
  Submit submit_;
  Equal equal_;
  WorldAdapterConfig config_{};
  WorldGeometryCache geometry_;
  std::shared_ptr<const WorldGeometry> source_;
  std::vector<Prepared> prepared_;
  std::array<uint8_t,0x150> header_{};
  uint32_t root_=0, device_=0;
  uint64_t pass_=0;
  bool active_=false, collecting_=false, failed_=false;
};
} // namespace gk3hd::vr
