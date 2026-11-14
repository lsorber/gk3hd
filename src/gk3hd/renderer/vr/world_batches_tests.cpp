#include "world_batches.h"
#include <array>
#include <cstdio>
#include <stdexcept>

namespace {
unsigned checks = 0;
void require(bool value, const char* why) {
  if (!value) throw std::runtime_error(why);
  ++checks;
}
struct Material { uint32_t texturesFlags[4]; };
struct Draw { uint32_t firstInstance; };
void run() {
  using namespace gk3hd::vr::world_batches;
  const std::array<Material, 6> materials = {{{0,0,0,0}, {0,0,2,0}, {0,0,1,0},
                                            {0,0,4,0}, {0,0,5,0}, {0,0,6,0}}};
  // Material indices deliberately differ from draw order. Both eye instances
  // select one material. Do not sort separated opaque runs across cutouts.
  const std::array<Draw, 10> draws = {{{2}, {0}, {4}, {6}, {0}, {2}, {8}, {10}, {0}, {0}}};
  const auto runs = partition(draws.data(), uint32_t(draws.size()), materials.data(), true);
  require(runs.size() == 5, "separated drawing classes were regrouped");
  const std::array<uint32_t,5> starts = {0,2,4,6,8}, lengths = {2,2,2,2,2};
  for (size_t i = 0; i < runs.size(); ++i) {
    require(runs[i].first == starts[i] && runs[i].count == lengths[i], "draw coverage/order changed");
    require(runs[i].opaque == (i%2 == 0), "keyed/alpha draw used opaque shader");
  }
  const auto general = partition(draws.data(), uint32_t(draws.size()), materials.data(), false);
  require(general.size()==1 && general[0].first==0 && general[0].count==draws.size() && !general[0].opaque,
          "general-shader fallback changed draw order or count");
  require(partition(draws.data(), 0, materials.data(), true).empty(), "empty pass emitted work");
  for (uint32_t flags = 0; flags < 16; ++flags)
    require(eligible(flags) == (!(flags&1u) && !(flags&4u)), "color-key/alpha classification");
}
}
int main() {
  try { run(); std::printf("world batches: %u behavior checks passed\n", checks); return 0; }
  catch (const std::exception& e) { std::fprintf(stderr,"FAIL: %s\n",e.what()); return 1; }
}
