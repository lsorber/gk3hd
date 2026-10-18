#pragma once

#include "input_bridge.h"

namespace gk3hd::vr {

enum class PanelOperation : uint32_t { Present, Close, World, Caption, Overlay, ModalSubtitles, Blank, Loading };
// Loading clears outgoing content and temporarily pumps empty XR frames. The
// next normal rendering entry must join that owner before accessing XR state.
// Blank clears every submitted layer before native blocking scene teardown.
// Unlike Close it may begin an idle frame, and never submits a pending world.
// ModalSubtitles uses an opaque native page plus a separately sized subtitle
// source batch. Picking belongs solely to the original complete page. Its
// baked glyph region is matted in the private XR copy, never in the game page.
// Present finalizes a deferred world and this panel in ONE XR frame. Close
// finalizes a pending world without a panel; it never begins a new XR frame.
// World does the same but exports that completed world's controller snapshot.
// It cannot begin a fresh frame, resurrect old input or manufacture a panel hit.
constexpr uint32_t PanelRecenter = 1u;
constexpr uint32_t PanelTransparent = 2u;
// Explicit native-menu presentation, independent of desktop and eye extents.
constexpr uint32_t PanelReadableMenu = 4u;
constexpr uint32_t PointerHit = 1u;
struct PanelGeometry {
  float orientation[4]{};
  float position[3]{};
  float size[2]{};
};
struct PanelPointer {
  uint32_t flags = 0, hand = 0;
  float x = 0, y = 0;
  uint32_t held = 0, pressed = 0;
};
// Private bridge for an explicitly selected 2D engine canvas, not automatic
// conversion of the whole game to a cinema screen. Present copies the current
// D3D target into an independent quad image, once per frame, GPU-only. The
// engine must apply the returned logical pointer before its next UI update.
struct PanelFrame {
  uint32_t size = sizeof(PanelFrame), flags = 0;
  uint32_t canvasWidth = 0, canvasHeight = 0, hand = 1;
  float widthMeters = 1.6f, distanceMeters = 1.6f;
  PanelGeometry geometry{};
  InputSnapshot input{};
  PanelPointer pointer{};
};
static_assert(sizeof(PanelFrame) == 188, "panel bridge must use fixed-width values");

} // namespace gk3hd::vr
