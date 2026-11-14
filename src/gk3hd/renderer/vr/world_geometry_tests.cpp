#ifdef _WIN32
#include <windows.h>
#endif
#include "world_geometry.h"
#include <cstdio>
#include <stdexcept>
#include <map>

namespace {
using namespace gk3hd::vr;
unsigned checks = 0;
void require(bool ok, const char* why) {
  if (!ok) throw std::runtime_error(why);
  ++checks;
}
struct Memory {
  std::map<uint32_t, std::vector<uint8_t>> blocks;
  size_t reads = 0;
  bool operator()(uint32_t address, void* output, size_t size) {
    ++reads;
    auto found = blocks.upper_bound(address);
    if (found == blocks.begin()) return false;
    --found;
    const uint64_t offset = uint64_t(address) - found->first;
    if (offset > found->second.size() || size > found->second.size() - offset) return false;
    std::memcpy(output, found->second.data() + offset, size);
    return true;
  }
  template<class T, size_t N> void put(uint32_t at, const std::array<T, N>& values) {
    auto& bytes = blocks[at]; bytes.resize(sizeof(values));
    std::memcpy(bytes.data(), values.data(), bytes.size());
  }
};
struct Fixture {
  Memory memory;
  WorldGeometryIdentity identity;
  Fixture() {
    std::array<uint8_t, 0x150> header{};
    auto word = [&](size_t off, uint32_t value) { std::memcpy(header.data() + off, &value, 4); };
    word(0, 0x123456); word(0xe8, 0x10000); word(0xf0, 0x20000);
    word(0x120, 4); word(0x130, 1); word(0x144, 0x30000);
    identity = WorldGeometryIdentity::native(0x40000, 1, header);
    memory.put<float,12>(0x10000, {0,0,0, 1,0,0, 1,1,0, 0,1,0});
    memory.put<float,8>(0x20000, {0,0, 1,0, 1,1, 0,1});
    memory.put<uint32_t,1>(0x30000, {0x50000});
    std::array<uint8_t,40> primitive{};
    const uint32_t n = 4, triangles = 2;
    std::memcpy(primitive.data()+32, &n, 4); std::memcpy(primitive.data()+36, &triangles, 4);
    memory.put(0x50000, primitive);
    // Native local-to-global map followed by triangle-local indices.
    memory.put<uint16_t,10>(0x50028, {3,2,1,0, 0,1,2, 0,2,3});
  }
};
void run() {
  Fixture f; WorldGeometryCache cache;
  auto read = [&](auto a, auto b, auto c) { return f.memory(a,b,c); };
  require(cache.prepare(f.identity, read) == WorldPreparation::Rebuilt, "first source not prepared");
  auto first = cache.snapshot(); const uint64_t firstKey = cache.key();
  require(first && first->vertices.size()==4 && first->vertices[2].xyz[1]==1, "vertex decode");
  require(first->vertices[2].uv[0]==1 && first->indices==std::vector<uint16_t>({3,2,1,3,1,0}), "UV/index mapping");
  require(first->primitives[0]==std::array<uint32_t,2>{0,6}, "primitive range");
  auto reads = f.memory.reads;
  require(cache.prepare(f.identity, read)==WorldPreparation::Reused && f.memory.reads==reads && cache.key()==firstKey,
          "unchanged source rebuilt");
  // Same address/shape after a resource retirement must not reuse old data.
  f.identity.lifetime++;
  f.memory.put<float,12>(0x10000, {0,0,0, 2,0,0, 2,2,0, 0,2,0});
  require(cache.prepare(f.identity, read)==WorldPreparation::Rebuilt && cache.key()>firstKey, "ABA reload reused key");
  require(cache.snapshot()->vertices[2].xyz[1]==2 && first->vertices[2].xyz[1]==1, "old retained source mutated");
  const uint64_t secondKey=cache.key();
  // An incomplete new scene must not publish partial geometry or select old data.
  f.identity.root++;
  f.memory.blocks.erase(0x50028);
  require(cache.prepare(f.identity,read)==WorldPreparation::Unsupported && !cache.snapshot() && !cache.key(),
          "failed preparation exposed stale/partial data");
  require(first->indices==std::vector<uint16_t>({3,2,1,3,1,0}), "failure invalidated retained frame source");
  f.memory.put<uint16_t,10>(0x50028, {3,2,1,0, 0,1,2, 0,2,3});
  require(cache.prepare(f.identity,read)==WorldPreparation::Rebuilt && cache.key()>secondKey, "recovery reused old generation");
  cache.invalidate(); require(!cache.key()&&!cache.snapshot(), "explicit invalidate remained ready");
  const auto valid=f.identity;
  for (uint32_t count : {0u, 2u, 65536u, UINT32_MAX}) {
    auto bad=valid; bad.shape[5]=count;
    require(cache.prepare(bad,read)==WorldPreparation::Unsupported && !cache.key(), "unsupported vertex count");
  }
  for (uint32_t count : {0u, 65536u, UINT32_MAX}) {
    auto bad=valid; bad.shape[6]=count;
    require(cache.prepare(bad,read)==WorldPreparation::Unsupported, "unsupported primitive count");
  }
  auto bad=valid; bad.shape[1]=UINT32_MAX-4;
  require(cache.prepare(bad,read)==WorldPreparation::Unsupported, "wrapped native address");
  for (auto indices : {std::array<uint16_t,10>{3,2,1,0,4,1,2,0,2,3},
                       std::array<uint16_t,10>{9,2,1,0,0,1,2,0,2,3}}) {
    f.memory.put(0x50028, indices); f.identity.lifetime++;
    require(cache.prepare(f.identity,read)==WorldPreparation::Unsupported && !cache.snapshot(), "invalid native index");
  }
}
}
int main() {
  try { run(); std::printf("world geometry: %u behavior checks passed\n",checks); return 0; }
  catch(const std::exception& e) { std::fprintf(stderr,"FAIL: %s\n",e.what()); return 1; }
}
