#pragma once

#include "frame_bridge.h"
#include "panel_bridge.h"
#include <stdexcept>

namespace gk3hd::vr {

// Shared by the draw-only world hook and completed-page hook. A hidden frame
// is already closed by begin but remains sampled until finish, so the panel
// cannot wait for a second frame or advance controller edge detection twice.
class FrameTransport {
public:
  virtual ~FrameTransport() = default;
  virtual bool begin(FrameViews& views) = 0;
  // Consumes the frame even when submission reports an error.
  virtual void end(bool world, const PanelGeometry* panel) = 0;
};

class FrameScheduler {
public:
  const FrameViews* begin(FrameTransport& transport) {
    if (!sampled_) {
      views_ = {};
      open_ = transport.begin(views_);
      sampled_ = true;
    }
    return open_ ? &views_ : nullptr;
  }
  const FrameViews* beginWorld(FrameTransport& transport) {
    if (worldAttempted_) throw std::logic_error("second world draw before XR frame completion");
    const auto* views = begin(transport);
    worldAttempted_ = true;
    return views;
  }
  void completeWorld() {
    if (!open_ || !worldAttempted_ || worldReady_)
      throw std::logic_error("world completion outside its XR transaction");
    worldReady_ = true;
  }
  bool finish(FrameTransport& transport, const PanelGeometry* panel = nullptr) {
    if (open_ && worldAttempted_ && !worldReady_) {
      cancel(transport);
      throw std::logic_error("cannot submit an incomplete world draw");
    }
    const bool open = open_, world = worldReady_;
    reset(); // Never double-end after a runtime submission error.
    if (open) transport.end(world, panel);
    return open;
  }
  void cancel(FrameTransport& transport) {
    const bool open = open_;
    reset();
    if (open) transport.end(false, nullptr);
  }
  bool pending() const { return sampled_; }
  // Retire visible content before the original engine blocks on scene I/O.
  // Reuse a pending frame, or begin one when idle; never submit its world/UI.
  bool blank(FrameTransport& transport) {
    if (!sampled_) begin(transport);
    const bool open = open_;
    cancel(transport);
    return open;
  }
  bool worldReady() const { return worldReady_; }
private:
  void reset() { sampled_ = open_ = worldAttempted_ = worldReady_ = false; views_ = {}; }
  FrameViews views_{};
  bool sampled_ = false, open_ = false, worldAttempted_ = false, worldReady_ = false;
};

} // namespace gk3hd::vr
