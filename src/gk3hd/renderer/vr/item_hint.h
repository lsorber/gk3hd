#pragma once

#include "panel.h"
#include "overlay.h"
#include <string>
#include <vector>

namespace gk3hd::vr {

// Original inventory enum is diagnostic only. Canonical names resolve artwork
// across the game's separate inventory, noun and verb namespaces.
struct ItemHintRequest {
  uint32_t size = sizeof(ItemHintRequest), item = 0;
  char name[96]{};
};
static_assert(sizeof(ItemHintRequest) == 104);

class ItemHint {
public:
  void configure(const ItemHintRequest& request, const void* catalog, uint32_t bytes);
  std::optional<PanelGeometry> prepare(const FrameViews& views, unsigned hand,
                                      const PanelFrame* panel = nullptr);
  const OverlayImage& image();
  void close() noexcept { selected_ = -1; }
private:
  struct Visual {
    std::string name;
    std::wstring label;
    uint32_t width = 0, height = 0;
    std::vector<uint32_t> pixels;
  };
  void load(const void* data, uint32_t bytes);
  const void* source_ = nullptr;
  uint32_t bytes_ = 0;
  std::vector<Visual> visuals_;
  int selected_ = -1, painted_ = -1;
  OverlayImage image_{};
};

} // namespace gk3hd::vr
