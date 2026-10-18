#pragma once

#include "frame_bridge.h"
#include "panel_bridge.h"
#include <openxr/openxr.h>

namespace gk3hd::vr {

struct OverlayImage;

class PanelState {
public:
  static void validate(const PanelFrame& request);
  static void world(PanelFrame& request, const FrameViews& frame);
  void prepare(PanelFrame& request, const FrameViews& frame, const OverlayImage* overlay = nullptr);
  bool transparent() const { return transparent_; }
  const PanelGeometry& canvasGeometry() const { return canvas_; }
  PanelGeometry subtitleGeometry(uint32_t canvasWidth, uint32_t canvasHeight) const;
  void close() noexcept { visible_ = transparent_ = menuVisible_ = false; }
private:
  XrPosef pose_{{0, 0, 0, 1}, {0, 0, 0}};
  float distance_ = 0;
  bool visible_ = false;
  bool transparent_ = false;
  PanelGeometry canvas_{};
  float menuX_ = 0, menuY_ = 0;
  float menuTargetX_ = 0, menuTargetY_ = 0;
  uint32_t menuWidth_ = 0, menuHeight_ = 0;
  bool menuVisible_ = false;
};

} // namespace gk3hd::vr
