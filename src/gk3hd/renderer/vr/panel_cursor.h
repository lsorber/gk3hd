#pragma once

#include "panel_bridge.h"
#include <algorithm>
#include <cmath>
#include <vector>

namespace gk3hd::vr {

struct CursorRectangle {
  int32_t left, top, right, bottom;
  bool white;
};

// A high-contrast aiming cross in the private XR image, not the game's cursor
// visibility state. It survives held Select and native action-menu cursor hides.
// Exact same canvas coordinates as picking; no pixel readback or extra XR layer.
inline std::vector<CursorRectangle> panelCursor(const PanelPointer* pointer,
                                               uint32_t width, uint32_t height) {
  if (!pointer || pointer->flags != PointerHit || !width || !height ||
      width > INT32_MAX || height > INT32_MAX || !std::isfinite(pointer->x) ||
      !std::isfinite(pointer->y) || pointer->x < 0 || pointer->y < 0 ||
      pointer->x >= float(width) || pointer->y >= float(height)) return {};
  const auto x = int32_t(pointer->x), y = int32_t(pointer->y);
  const auto radius = std::max(3, int32_t(height/200));
  std::vector<CursorRectangle> result;
  const auto add = [&](int32_t left, int32_t top, int32_t right, int32_t bottom, bool white) {
    left = std::max(0, left); top = std::max(0, top);
    right = std::min(int32_t(width), right); bottom = std::min(int32_t(height), bottom);
    if (left < right && top < bottom) result.push_back({left, top, right, bottom, white});
  };
  add(x-radius-1,y-1,x+radius+2,y+2,false);
  add(x-1,y-radius-1,x+2,y+radius+2,false);
  add(x-radius,y,x+radius+1,y+1,true);
  add(x,y-radius,x+1,y+radius+1,true);
  return result;
}

} // namespace gk3hd::vr
