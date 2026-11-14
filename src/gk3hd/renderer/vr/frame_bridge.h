#pragma once

#include <cstdint>
#include "input_bridge.h"

namespace gk3hd::vr {

// Private, versioned renderer ABI for the verified engine draw-only hook.
// Gk3hdXrFrameV1 takes an IDirect3DDevice3 owned by this renderer, an operation,
// and (for Begin only) FrameViews*. Call on the engine thread, retain the device
// throughout the transaction, and finish each successful Begin with Submit or
// Cancel. S_OK means render, S_FALSE means skip (already closed), HRESULT errors
// must not be treated as usable tracking. No game update occurs in this bridge.
enum class FrameOperation : uint32_t { Begin, Left, Right, Submit, Cancel };

struct EyeView {
  uint32_t width, height;
  float orientation[4]; // OpenXR quaternion x, y, z, w
  float position[3];    // metres in local tracking space
  float fov[4];         // left, right, up, down angles in radians
};

struct FrameViews {
  uint32_t size = sizeof(FrameViews);
  EyeView eyes[2]{};
  InputSnapshot input{};
};

static_assert(sizeof(FrameViews) == 208, "frame bridge ABI must be fixed-width");

} // namespace gk3hd::vr
