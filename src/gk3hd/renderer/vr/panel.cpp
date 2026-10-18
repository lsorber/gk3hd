#include "panel.h"
#include "camera.h"
#include "overlay.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace gk3hd::vr {
namespace {
XrPosef head(const FrameViews& views) {
  const auto& left = views.eyes[0];
  const auto& right = views.eyes[1];
  const auto a = normalized({left.orientation[0], left.orientation[1], left.orientation[2], left.orientation[3]});
  const auto b = normalized({right.orientation[0], right.orientation[1], right.orientation[2], right.orientation[3]});
  const float sign = a.x*b.x+a.y*b.y+a.z*b.z+a.w*b.w < 0 ? -1.f : 1.f;
  XrPosef result{normalized({a.x+sign*b.x, a.y+sign*b.y, a.z+sign*b.z, a.w+sign*b.w}),
    {(left.position[0]+right.position[0])/2, (left.position[1]+right.position[1])/2,
     (left.position[2]+right.position[2])/2}};
  if (!std::isfinite(result.position.x) || !std::isfinite(result.position.y) ||
      !std::isfinite(result.position.z)) throw std::invalid_argument("invalid panel head position");
  return result;
}
void pointerButtons(PanelPointer& pointer, const InputSnapshot& input, unsigned selected) {
  const auto& pointing = input.hands[selected];
  pointer.held = pointing.held; pointer.pressed = pointing.pressed;
  // Back, Menu and Inventory do not select at a ray position. Accept their
  // already release-armed actions from either tracked hand without changing
  // pointer ownership or borrowing the other hand's trigger. The native route
  // still arbitrates simultaneous shortcuts and retires held UI selections.
  constexpr uint32_t shortcuts = Cancel | Menu | Inventory;
  const auto& other = input.hands[selected ^ 1];
  if (other.flags & AimValid) {
    pointer.held |= other.held & shortcuts;
    pointer.pressed |= other.pressed & shortcuts;
  }
}
} // namespace
void PanelState::validate(const PanelFrame& request) {
  if (request.size != sizeof(request) || (request.flags & ~(PanelRecenter | PanelTransparent | PanelReadableMenu)) ||
      ((request.flags & PanelReadableMenu) && !(request.flags & PanelTransparent)) ||
      request.hand > 1 || !request.canvasWidth || !request.canvasHeight ||
      request.canvasWidth > uint32_t(INT32_MAX) || request.canvasHeight > uint32_t(INT32_MAX) ||
      !std::isfinite(request.widthMeters) || request.widthMeters <= 0 ||
      !std::isfinite(request.distanceMeters) || request.distanceMeters <= 0)
    throw std::invalid_argument("invalid interface panel request");
  const float height = request.widthMeters * (float(request.canvasHeight)/float(request.canvasWidth));
  if (!std::isfinite(height) || height <= 0) throw std::invalid_argument("invalid panel aspect ratio");
  if ((request.flags & PanelReadableMenu) &&
      (!std::isfinite(request.widthMeters*1.8f) || !std::isfinite(height*1.8f)))
    throw std::invalid_argument("invalid readable menu size");
}
PanelGeometry PanelState::subtitleGeometry(uint32_t canvasWidth, uint32_t canvasHeight) const {
  if (!visible_ || !canvasWidth || !canvasHeight)
    throw std::logic_error("subtitle geometry requires a prepared panel");
  auto result = canvas_;
  // Keep a stable bottom-center anchor below the view, independent of native
  // line length/count and menu placement. About 2 degrees of glyph height for
  // the native 17-pixel line in an 800-pixel canvas at 1.6 m viewing distance.
  // This changes angular size, not eye resolution, font metrics or picking.
  // SteamVR can depth-test coplanar quad layers against each other despite
  // their submission order. Put captions just in front of their native page
  // and scale about the anchor viewer to preserve their angular footprint.
  // The stable separation also prevents head-motion-dependent text breakup.
  constexpr float front = .99f;
  const float height = distance_ * 1.6f * front;
  result.size[0] = height * float(canvasWidth)/float(canvasHeight);
  result.size[1] = height;
  const auto offset = rotate(pose_.orientation,
                            {0, height*.5f-distance_*.3125f*front, distance_*(1-front)});
  result.position[0] += offset.x;
  result.position[1] += offset.y;
  result.position[2] += offset.z;
  if (!std::isfinite(result.size[0]) || !std::isfinite(result.size[1]) ||
      !std::isfinite(result.position[0]) || !std::isfinite(result.position[1]) ||
      !std::isfinite(result.position[2]))
    throw std::invalid_argument("invalid subtitle geometry");
  return result;
}
void PanelState::world(PanelFrame& request, const FrameViews& frame) {
  validate(request);
  request.geometry = {}; request.pointer = {}; request.input = frame.input;
  request.pointer.hand = request.hand;
  if (!(frame.input.flags & InputFocused)) return;
  unsigned selected = request.hand;
  if (!(frame.input.hands[selected].flags & AimValid)) selected ^= 1;
  request.pointer.hand = selected;
  const auto& hand = frame.input.hands[selected];
  if (!(hand.flags & AimValid)) return;
  pointerButtons(request.pointer, frame.input, selected);
}
void PanelState::prepare(PanelFrame& request, const FrameViews& frame, const OverlayImage* overlay) {
  validate(request);
  if ((request.flags & PanelReadableMenu) && !overlay)
    throw std::invalid_argument("readable menu requires isolated overlay sources");
  if (overlay && (!(request.flags & PanelTransparent) || overlay->width != request.canvasWidth ||
      overlay->height != request.canvasHeight ||
      uint64_t(overlay->width)*overlay->height != overlay->pixels.size() ||
      (!overlay->coverage.empty() && overlay->coverage.size() != overlay->pixels.size())))
    throw std::invalid_argument("invalid interactive overlay canvas");
  const auto viewer = head(frame);
  bool recenter = (request.flags & PanelRecenter) != 0;
  if (frame.input.flags & InputFocused)
    for (const auto& hand : frame.input.hands)
      recenter = recenter || ((hand.flags & AimValid) && (hand.pressed & Recenter));
  if (!visible_ || recenter || distance_ != request.distanceMeters) {
    const auto forward = rotate(viewer.orientation, {0, 0, -1});
    XrQuaternionf yaw = visible_ ? pose_.orientation : XrQuaternionf{0, 0, 0, 1};
    if (forward.x*forward.x + forward.z*forward.z > 1e-8f) {
      const float angle = std::atan2(-forward.x, -forward.z);
      yaw = {0, std::sin(angle/2), 0, std::cos(angle/2)};
    }
    const auto offset = rotate(yaw, {0, 0, -request.distanceMeters});
    const XrPosef next{yaw, {viewer.position.x+offset.x, viewer.position.y, viewer.position.z+offset.z}};
    if (!std::isfinite(next.position.x) || !std::isfinite(next.position.z))
      throw std::invalid_argument("invalid panel anchor position");
    pose_ = next;
    distance_ = request.distanceMeters;
    visible_ = true;
    menuVisible_ = false;
  }
  const auto& q = pose_.orientation;
  const float orientation[]{q.x, q.y, q.z, q.w};
  std::copy_n(orientation, 4, request.geometry.orientation);
  const auto& p = pose_.position;
  request.geometry.position[0] = p.x; request.geometry.position[1] = p.y; request.geometry.position[2] = p.z;
  request.geometry.size[0] = request.widthMeters;
  request.geometry.size[1] = request.widthMeters * (float(request.canvasHeight)/float(request.canvasWidth));
  canvas_ = request.geometry;
  const bool menu = (request.flags & PanelReadableMenu) && overlay && !overlay->interactiveBounds.empty();
  if (menu) {
    const auto& bounds = overlay->interactiveBounds;
    if (bounds.left > bounds.right || bounds.top > bounds.bottom ||
        bounds.right > request.canvasWidth || bounds.bottom > request.canvasHeight)
      throw std::invalid_argument("invalid menu anchor footprint");
    if (!menuVisible_ || menuWidth_ != request.canvasWidth || menuHeight_ != request.canvasHeight) {
      menuX_ = (float(bounds.left)+float(bounds.right))*.5f/float(request.canvasWidth);
      menuY_ = float(bounds.top)/float(request.canvasHeight);
      menuTargetX_ = menuTargetY_ = 0;
      // Open near the pointing direction, not at an unrelated fixed spot above
      // the viewer. Hold that anchor while exploring the menu/submenus. Keep
      // distant object menus comfortably sized instead of shrinking with depth.
      unsigned pointing = request.hand;
      if (!(frame.input.hands[pointing].flags & AimValid)) pointing ^= 1;
      const auto& controller = frame.input.hands[pointing];
      if ((frame.input.flags & InputFocused) && (controller.flags & AimValid)) {
        PanelPoint point{};
        const XrPosef aim{{controller.orientation[0],controller.orientation[1],
                          controller.orientation[2],controller.orientation[3]},
                         {controller.position[0],controller.position[1],controller.position[2]}};
        if (panelPoint(pose_,request.widthMeters,canvas_.size[1],aim,
                       float(request.canvasWidth),float(request.canvasHeight),point)) {
          menuTargetX_ = std::clamp(point.x/float(request.canvasWidth)-.5f,-.35f,.35f)*request.widthMeters;
          menuTargetY_ = std::clamp(.5f-point.y/float(request.canvasHeight),-.3f,.3f)*canvas_.size[1];
        }
      }
      menuWidth_ = request.canvasWidth; menuHeight_ = request.canvasHeight;
      menuVisible_ = true;
    }
    // A stable canvas-to-meters scale, not a fit recalculated for every popup.
    // Anchor the initial menu's top center near the pointed direction. Expanding a
    // submenu/tooltip changes neither existing glyph size nor button position.
    constexpr float magnification = 1.8f;
    request.geometry.size[0] *= magnification;
    request.geometry.size[1] *= magnification;
    const auto offset = rotate(pose_.orientation,
      {(.5f-menuX_)*request.geometry.size[0]+menuTargetX_,
       (menuY_-.5f)*request.geometry.size[1]+menuTargetY_+request.distanceMeters*.025f, 0});
    request.geometry.position[0] += offset.x;
    request.geometry.position[1] += offset.y;
    request.geometry.position[2] += offset.z;
    if (!std::isfinite(request.geometry.position[0]) || !std::isfinite(request.geometry.position[1]) ||
        !std::isfinite(request.geometry.position[2]))
      throw std::invalid_argument("invalid readable menu anchor position");
  } else menuVisible_ = false;
  request.input = frame.input;
  transparent_ = (request.flags & PanelTransparent) != 0;
  request.pointer = {};
  request.pointer.hand = request.hand;
  // Captions/tooltips are noninteractive. Only an explicit menu producer's
  // current coverage may intercept a ray, never the full transparent canvas.
  if (transparent_ && (!overlay || overlay->coverage.empty())) {
    const auto geometry = request.geometry;
    world(request, frame);
    request.geometry = geometry;
    return;
  }
  if (!(frame.input.flags & InputFocused)) return;
  unsigned selected = request.hand;
  if (!(frame.input.hands[selected].flags & AimValid)) selected ^= 1;
  const auto& hand = frame.input.hands[selected];
  if (!(hand.flags & AimValid)) return;
  const XrPosef aim{{hand.orientation[0], hand.orientation[1], hand.orientation[2], hand.orientation[3]},
                   {hand.position[0], hand.position[1], hand.position[2]}};
  PanelPoint point{};
  request.pointer.hand = selected;
  // Back/menu shortcuts need not point at the panel. Selection is valid only
  // when PointerHit is set; never clamp an outside ray to the nearest button.
  pointerButtons(request.pointer, frame.input, selected);
  const XrPosef displayed{{request.geometry.orientation[0], request.geometry.orientation[1],
                         request.geometry.orientation[2], request.geometry.orientation[3]},
                        {request.geometry.position[0], request.geometry.position[1], request.geometry.position[2]}};
  if (panelPoint(displayed, request.geometry.size[0], request.geometry.size[1], aim,
                 float(request.canvasWidth), float(request.canvasHeight), point) &&
      (!transparent_ || overlay->hit(point.x, point.y))) {
    request.pointer.flags = PointerHit;
    request.pointer.x = point.x; request.pointer.y = point.y;
  }
}
} // namespace gk3hd::vr
