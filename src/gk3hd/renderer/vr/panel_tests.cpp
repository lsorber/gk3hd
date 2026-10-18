#include "panel.h"
#include "panel_cursor.h"
#include "camera.h"
#include "overlay.h"
#include "gpu_test_config.h"

#include <cstring>
#include <algorithm>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>

using namespace gk3hd::vr;
static_assert(testEyeSize("")[0] == 256 && testEyeSize("")[1] == 256);
static_assert(testEyeSize("1440x1600")[0] == 1440 && testEyeSize("1440x1600")[1] == 1600);
static_assert(testEyeSize("64x4096")[0] == 64 && testEyeSize("4096x64")[1] == 64);
static_assert(!testEyeSize("63x64")[0] && !testEyeSize("64x4097")[0]);
static_assert(!testEyeSize("4294967296x64")[0] && !testEyeSize("1e3x64")[0]);
static_assert(!testEyeSize("64x")[0] && !testEyeSize("x64")[0]);
static_assert(!testEyeSize("64X64")[0] && !testEyeSize("64x64extra")[0]);
static_assert(!testEyeSize(" 64x64")[0] && !testEyeSize("64x64 ")[0]);
namespace {
void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
bool close(float a, float b) { return std::abs(a-b) < .0001f; }
void rejects(const std::function<void()>& call) {
  try { call(); } catch (const std::exception&) { return; }
  throw std::runtime_error("invalid panel configuration accepted");
}
FrameViews frame() {
  FrameViews views{};
  for (unsigned eye = 0; eye < 2; ++eye) {
    views.eyes[eye].orientation[3] = eye ? -1.f : 1.f;
    views.eyes[eye].position[0] = eye ? .03f : -.03f;
    views.eyes[eye].position[1] = 1.5f;
  }
  views.input.flags = InputFocused;
  for (auto& hand : views.input.hands) {
    hand.flags = AimValid; hand.orientation[3] = 1.f; hand.position[1] = 1.5f;
  }
  return views;
}
PanelFrame request() {
  PanelFrame value{};
  value.canvasWidth = 1024; value.canvasHeight = 768;
  return value;
}
void placement() {
  auto views = frame(); auto value = request();
  PanelState panel;
  panel.prepare(value, views);
  require(close(value.geometry.position[2], -value.distanceMeters) &&
          close(value.geometry.position[1], 1.5f) && close(value.geometry.size[1], 1.2f),
          "panel placement or aspect ratio is wrong");
  require(value.pointer.flags == PointerHit && close(value.pointer.x, 512) &&
          close(value.pointer.y, 384), "panel pointer does not match its visible center");
  const auto placed = value.geometry;
  for (auto& eye : views.eyes) { eye.position[0] += .5f; eye.position[1] += .2f; }
  panel.prepare(value, views);
  require(std::memcmp(&placed, &value.geometry, sizeof(placed)) == 0, "panel follows head movement");
  value.flags = PanelRecenter; panel.prepare(value, views);
  require(close(value.geometry.position[0], .5f) && close(value.geometry.position[1], 1.7f),
          "explicit panel recenter did not follow current head");
  value.flags = 0; views.input.hands[0].pressed = Recenter;
  for (auto& eye : views.eyes) eye.position[0] += .1f;
  panel.prepare(value, views);
  require(close(value.geometry.position[0], .6f), "controller recenter did not reposition panel");
  views.input.flags = 0;
  for (auto& eye : views.eyes) eye.position[0] += .1f;
  panel.prepare(value, views);
  require(close(value.geometry.position[0], .6f) && !value.pointer.flags && !value.pointer.pressed,
          "dashboard input altered panel or pointer");
  panel.close(); panel.prepare(value, views);
  require(close(value.geometry.position[0], .7f), "reopening panel did not anchor it anew");
  value.canvasWidth = 1920; value.canvasHeight = 1080;
  panel.prepare(value, views);
  require(close(value.geometry.size[1], .9f), "widescreen canvas was stretched to 4:3");
}
void hitTesting() {
  auto views = frame(); auto value = request(); PanelState panel;
  for (const unsigned hand : {0u, 1u}) {
    value.hand = hand;
    for (const float x : {- .99f, -.5f, 0.f, .5f, .99f})
      for (const float y : {-.99f, 0.f, .99f}) {
        views.input.hands[hand].position[0] = x * .8f;
        views.input.hands[hand].position[1] = 1.5f + y * .6f;
        views.input.hands[hand].pressed = Select;
        panel.prepare(value, views);
        require(value.pointer.flags == PointerHit && value.pointer.hand == hand &&
                close(value.pointer.x, (x*.5f+.5f)*1024) &&
                close(value.pointer.y, (.5f-y*.5f)*768) && value.pointer.pressed == Select,
                "panel edge pointer drifts from the displayed canvas");
      }
  }
  views.input.hands[1].position[0] = 2.f;
  panel.prepare(value, views);
  require(!value.pointer.flags, "outside pointer clamped to a button");
  std::fill_n(views.input.hands[1].position, 3, 0.f);
  views.input.hands[1].position[1] = 1.5f;
  views.input.hands[1].position[2] = -2.f;
  views.input.hands[1].orientation[1] = 1.f; views.input.hands[1].orientation[3] = 0;
  panel.prepare(value, views);
  require(!value.pointer.flags, "invisible back of quad accepts clicks");
  views.input.hands[1].flags = 0;
  views.input.hands[0].position[0] = 0; views.input.hands[0].position[1] = 1.5f;
  panel.prepare(value, views);
  require(value.pointer.flags == PointerHit && !value.pointer.hand, "available alternate hand ignored");
  views.input.hands[0].flags = 0;
  panel.prepare(value, views);
  require(!value.pointer.flags && !value.pointer.held && !value.pointer.pressed, "lost pointers remain active");
}
void modalSizeTransitions() {
  auto views = frame(); auto value = request(); PanelState panel;
  for (const auto extent : {std::array<uint32_t,2>{1280,800}, {3840,2160}}) {
    value.canvasWidth = extent[0]; value.canvasHeight = extent[1];
    for (const float width : {1.6f, 2.4f, 1.6f, 2.4f}) {
      value.widthMeters = width;
      const float height = width*float(extent[1])/float(extent[0]);
      for (const unsigned hand : {0u, 1u}) {
        value.hand = hand;
        for (const float x : {.005f, .25f, .5f, .75f, .995f})
          for (const float y : {.005f, .5f, .995f}) {
            auto& aim = views.input.hands[hand];
            aim.position[0] = (x-.5f)*width;
            aim.position[1] = 1.5f+(.5f-y)*height;
            aim.pressed = Select;
            panel.prepare(value, views);
            require(close(value.geometry.size[0],width) && close(value.geometry.size[1],height) &&
                    close(value.geometry.position[2],-value.distanceMeters),
                    "modal resize altered aspect ratio, distance or visible geometry");
            require(value.pointer.flags == PointerHit && value.pointer.hand == hand &&
                    std::abs(value.pointer.x-x*extent[0]) < .001f &&
                    std::abs(value.pointer.y-y*extent[1]) < .001f && value.pointer.pressed == Select,
                    "modal resize left controller picking on the previous canvas transform");
          }
        views.input.hands[hand].position[0] = width*.501f;
        panel.prepare(value, views);
        require(!value.pointer.flags, "modal resize clamped an outside ray onto a control");
      }
    }
  }
}
void upright() {
  auto views = frame(); auto value = request(); PanelState panel;
  // Pitch plus roll should not tilt a readable interface screen.
  const XrQuaternionf orientation = multiply({0, .5f, 0, std::sqrt(.75f)},
                                           multiply({.3f, 0, 0, std::sqrt(.91f)}, {0, 0, .2f, std::sqrt(.96f)}));
  for (auto& eye : views.eyes) {
    eye.orientation[0] = orientation.x; eye.orientation[1] = orientation.y;
    eye.orientation[2] = orientation.z; eye.orientation[3] = orientation.w;
  }
  panel.prepare(value, views);
  require(value.geometry.orientation[0] == 0 && value.geometry.orientation[2] == 0 &&
          close(value.geometry.position[1], 1.5f), "panel inherits headset roll/pitch");
  const auto forward = rotate(orientation, {0, 0, -1});
  const auto panelForward = rotate({value.geometry.orientation[0], value.geometry.orientation[1],
    value.geometry.orientation[2], value.geometry.orientation[3]}, {0, 0, -1});
  const auto length = std::sqrt(forward.x*forward.x+forward.z*forward.z);
  require(close(panelForward.x, forward.x/length) && close(panelForward.z, forward.z/length),
          "panel yaw is not aligned with viewer");
}
void worldInput() {
  auto value = request(); auto views = frame();
  views.input.hands[1].held = Select;
  views.input.hands[1].pressed = Menu;
  PanelState::world(value, views);
  require(!value.pointer.flags && !value.geometry.size[0] && value.pointer.hand == 1 &&
          value.pointer.held == Select && value.pointer.pressed == Menu &&
          std::memcmp(&value.input, &views.input, sizeof(value.input)) == 0,
          "world-only input created a panel or lost its completed snapshot");
  views.input.hands[1].flags = 0; views.input.hands[0].held = Inventory;
  PanelState::world(value, views);
  require(value.pointer.hand == 0 && value.pointer.held == Inventory,
          "world-only input failed tracked-hand fallback");
  views.input.flags = 0;
  PanelState::world(value, views);
  require(!value.pointer.flags && !value.pointer.held && !value.pointer.pressed,
          "unfocused world-only frame retained actions");
}
void sharedShortcuts() {
  for (const unsigned pointing : {0u, 1u}) {
    for (const bool world : {false, true}) {
      auto views = frame(); auto value = request(); PanelState panel;
      value.hand = pointing;
      auto& owner = views.input.hands[pointing];
      auto& other = views.input.hands[pointing ^ 1];
      owner.held = Select;
      other.held = other.pressed = Select | Cancel | Menu | Inventory | Recenter;
      const auto update = [&] {
        if (world) PanelState::world(value, views);
        else panel.prepare(value, views);
      };
      update();
      require(value.pointer.hand == pointing && value.pointer.held == (Select | Cancel | Menu | Inventory) &&
              value.pointer.pressed == (Cancel | Menu | Inventory) &&
              std::memcmp(&value.input, &views.input, sizeof(value.input)) == 0,
              "other-hand shortcuts changed pointing, borrowed a trigger or altered the native snapshot");
      if (!world) require(value.pointer.flags == PointerHit && close(value.pointer.x,512) &&
                          close(value.pointer.y,384), "other-hand shortcut shifted the displayed pointer");
      other.held = other.pressed = Select;
      update();
      require(value.pointer.held == Select && !value.pointer.pressed,
              "non-pointing trigger selected through the pointing hand");
      owner.held = 0; other.held = Menu; other.pressed = 0;
      update();
      require(value.pointer.held == Menu && !value.pointer.pressed,
              "held other-hand shortcut was regenerated as a press");
      other.flags = 0; other.pressed = Menu;
      update();
      require(!value.pointer.held && !value.pointer.pressed,
              "untracked other hand retained a shortcut");
      views.input.flags = 0; other.flags = AimValid;
      update();
      require(!value.pointer.flags && !value.pointer.held && !value.pointer.pressed,
              "unfocused frame accepted another hand's shortcut");
    }
  }
}
void invalid() {
  auto views = frame(); const auto baseline = request(); PanelState panel;
  for (unsigned kind = 0; kind < 7; ++kind) {
    auto value = baseline;
    switch (kind) {
      case 0: value.canvasWidth = 0; break;
      case 1: value.size = 0; break;
      case 2: value.flags = 8; break;
      case 3: value.hand = 2; break;
      case 4: value.distanceMeters = -1; break;
      case 5: value.widthMeters = std::numeric_limits<float>::infinity(); break;
      case 6: value.widthMeters = std::numeric_limits<float>::quiet_NaN(); break;
    }
    rejects([&] { panel.prepare(value, views); });
  }
  auto value = baseline;
  views.eyes[0].position[0] = std::numeric_limits<float>::infinity();
  rejects([&] { panel.prepare(value, views); });
  views = frame();
  for (auto& eye : views.eyes) {
    eye.position[2] = std::numeric_limits<float>::max()/4;
    eye.orientation[1] = 1; eye.orientation[3] = 0;
  }
  value.distanceMeters = std::numeric_limits<float>::max();
  rejects([&] { panel.prepare(value, views); });
  views = frame(); value = baseline;
  panel.prepare(value, views);
  require(std::isfinite(value.geometry.position[2]), "failed placement poisoned panel anchor");
}
} // namespace
void transparentCaptions() {
  auto views = frame(); auto value = request(); PanelState panel;
  value.flags = PanelTransparent;
  views.input.hands[1].held = Select;
  panel.prepare(value, views);
  require(panel.transparent() && !value.pointer.flags && value.pointer.held == Select &&
          value.geometry.size[0] == 1.6f, "caption overlay swallowed world input");
  value.flags = 0;
  panel.prepare(value, views);
  require(!panel.transparent() && value.pointer.flags == PointerHit, "opaque panel inherited caption alpha");
  CaptionPanelFrame caption{};
  caption.panel.canvasWidth = 4; caption.panel.canvasHeight = 3;
  caption.key = 1; caption.left = 1; caption.top = 1; caption.right = 4; caption.bottom = 3;
  const uint16_t pixels[15]{0xffff, 0xffff, 0xffff, 0xffff, 0xaaaa,
                           0xffff, 0, 1, 0xf800, 0xbbbb,
                           0xffff, 0x7e0, 0x1f, 0xffff, 0xcccc};
  const auto image = keyedOverlay(caption, pixels, 10, 4, 3);
  require(image.pixels == std::vector<uint32_t>{0, 0, 0, 0, 0, 0xff000000, 0, 0xffff0000,
          0, 0xff00ff00, 0xff0000ff, 0xffffffff}, "keyed caption altered black, key, bounds, pitch or RGB565 colors");
  for (unsigned kind = 0; kind < 8; ++kind) {
    auto bad = caption;
    switch (kind) {
      case 0: bad.left = -1; break;
      case 1: bad.right = 5; break;
      case 2: bad.bottom = 1; break;
      case 3: bad.key = 65536; break;
      case 4: bad.panel.canvasWidth = 3; break;
      case 5: bad.panel.canvasHeight = 4; break;
      case 6: bad.top = -1; break;
      case 7: bad.right = bad.left; break;
    }
    rejects([&] { keyedOverlay(bad, pixels, 10, 4, 3); });
  }
  rejects([&] { keyedOverlay(caption, nullptr, 10, 4, 3); });
  rejects([&] { keyedOverlay(caption, pixels, 6, 4, 3); });
  rejects([&] { keyedOverlay(caption, pixels, -10, 4, 3); });
  auto huge = caption; huge.panel.canvasWidth = huge.panel.canvasHeight = 8192;
  rejects([&] { keyedOverlay(huge, pixels, 16384, 8192, 8192); });
  rejects([&] { keyedOverlay(caption, reinterpret_cast<void*>(UINTPTR_MAX-4), 10, 4, 3); });
}
void composedOverlays() {
  auto image = overlayCanvas(6, 4);
  const uint16_t base[4]{0, 0xf800, 0x7e0, 0x1f};
  OverlayPart opaque{0, 0, 0, 0, 0, 2, 2, 2, 1};
  compositeOverlay(image, opaque, base, 4, 2, 2);
  const uint16_t keyed[8]{1, 0, 0xffff, 0xaaaa, 0xf800, 1, 0x1f, 0xbbbb};
  OverlayPart detail{0, OverlayKeyed, 1, 0, 0, 3, 2, 1, 1};
  compositeOverlay(image, detail, keyed, 8, 3, 2);
  require(image.pixels == std::vector<uint32_t>{0, 0, 0, 0, 0, 0,
          0, 0, 0xff000000, 0xffffffff, 0, 0,
          0, 0xffff0000, 0xff00ff00, 0xff0000ff, 0, 0,
          0, 0, 0, 0, 0, 0},
          "composed overlay lost local placement, layer order, key holes, opaque black or padding");
  detail.left = 1; detail.x = -1; detail.y = 3;
  compositeOverlay(image, detail, keyed, 8, 3, 2);
  require(image.pixels[18] == 0xffffffff && image.pixels[19] == 0,
          "source cropping and destination clipping shifted or scaled an overlay");
  const auto unchanged = image.pixels;
  for (const auto coordinate : {INT32_MIN, INT32_MAX}) {
    detail.x = detail.y = coordinate;
    compositeOverlay(image, detail, keyed, 8, 3, 2);
    require(image.pixels == unchanged, "off-screen overlay overflowed or clamped to an edge");
  }
  for (unsigned kind = 0; kind < 9; ++kind) {
    auto bad = opaque;
    switch (kind) {
      case 0: bad.flags = 16; break;
      case 1: bad.key = 1; break;
      case 2: bad.flags = OverlayKeyed; bad.key = 65536; break;
      case 3: bad.left = -1; break;
      case 4: bad.top = -1; break;
      case 5: bad.right = 3; break;
      case 6: bad.bottom = 3; break;
      case 7: bad.right = bad.left; break;
      case 8: bad.bottom = bad.top; break;
    }
    rejects([&] { compositeOverlay(image, bad, base, 4, 2, 2); });
    require(image.pixels == unchanged, "invalid overlay mutated an already composed canvas");
  }
  rejects([&] { compositeOverlay(image, opaque, nullptr, 4, 2, 2); });
  rejects([&] { compositeOverlay(image, opaque, base, 3, 2, 2); });
  rejects([&] { compositeOverlay(image, opaque, base, -4, 2, 2); });
  rejects([&] { compositeOverlay(image, opaque, reinterpret_cast<void*>(UINTPTR_MAX-4), 4, 2, 2); });
  rejects([&] { overlayCanvas(0, 4); });
  rejects([&] { overlayCanvas(8192, 8192); });
  rejects([&] { overlayCanvas(UINT32_MAX, 2); });
}
void interactiveOverlays() {
  const uint16_t controls[8]{1, 0, 0xffff, 0xaaaa, 0xf800, 1, 0x1f, 0xbbbb};
  auto image = overlayCanvas(6, 4);
  OverlayPart icon{0, OverlayKeyed | OverlayInteractive, 1, 0, 0, 3, 2, 1, 1};
  compositeOverlay(image, icon, controls, 8, 3, 2);
  require(!image.hit(1.5f, 1.5f) && image.hit(2.5f, 1.5f) && image.hit(3.5f, 1.5f) &&
          image.hit(1.5f, 2.5f) && !image.hit(2.5f, 2.5f) && image.hit(3.5f, 2.5f),
          "interactive key holes, opaque black or source pitch disagree with displayed pixels");
  for (const float x : {-1.f, 6.f, std::numeric_limits<float>::infinity(),
                        std::numeric_limits<float>::quiet_NaN()})
    require(!image.hit(x, 1), "outside or invalid overlay point accepted");
  require(!image.hit(2, -1) && !image.hit(2, 4) &&
          image.hit(2.999f, 1.999f) && !image.hit(1.999f, 1.999f),
          "coverage changed half-open pixel boundaries");
  // An opaque noninteractive label occludes a control without becoming one.
  // Its keyed holes still expose the preceding native interactive producer.
  auto label = icon; label.flags = OverlayKeyed; label.x = 2;
  compositeOverlay(image, label, controls, 8, 3, 2);
  require(image.hit(2.5f, 1.5f) && !image.hit(3.5f, 1.5f) && !image.hit(4.5f, 1.5f) &&
          !image.hit(2.5f, 2.5f) && image.hit(3.5f, 2.5f),
          "display-only label captured input or key holes erased underlying controls");
  auto clipped = overlayCanvas(3, 3); icon.x = -1; icon.y = 2; icon.left = 1;
  compositeOverlay(clipped, icon, controls, 8, 3, 2);
  require(clipped.hit(.5f, 2.5f) && !clipped.hit(1.5f, 2.5f) && !clipped.hit(.5f, 1.5f),
          "clipping shifted coverage relative to the visible crop");
  auto invalid = image; invalid.coverage.pop_back();
  rejects([&] { compositeOverlay(invalid, icon, controls, 8, 3, 2); });
  require(!invalid.hit(2, 1), "malformed coverage allowed an unchecked pixel lookup");

  for (const auto extent : {std::array<uint32_t, 2>{1024, 768}, {1280, 800}, {3840, 2160}}) {
    auto views = frame(); auto value = request(); PanelState panel;
    value.flags = PanelTransparent;
    value.canvasWidth = extent[0]; value.canvasHeight = extent[1];
    auto canvas = overlayCanvas(extent[0], extent[1]);
    // Place native controls near all edges and at the center. Each source
    // contains an explicit transparent pixel adjacent to an opaque black one.
    for (const auto origin : {std::array<int32_t, 2>{2, 2}, {int32_t(extent[0])-5, 2},
                              {2, int32_t(extent[1])-4},
                              {int32_t(extent[0])-5, int32_t(extent[1])-4},
                              {int32_t(extent[0]/2), int32_t(extent[1]/2)}}) {
      icon.left = 0; icon.x = origin[0]; icon.y = origin[1];
      compositeOverlay(canvas, icon, controls, 8, 3, 2);
      for (const unsigned hand : {0u, 1u}) {
        value.hand = hand;
        views.input.hands[hand].held = Select; views.input.hands[hand].pressed = Menu;
        for (const bool covered : {false, true}) {
          const float x = float(origin[0]) + (covered ? 1.5f : .5f);
          const float y = float(origin[1]) + .5f;
          views.input.hands[hand].position[0] = (x/extent[0]-.5f)*value.widthMeters;
          views.input.hands[hand].position[1] = 1.5f + (.5f-y/extent[1]) *
            (value.widthMeters*float(extent[1])/float(extent[0]));
          panel.prepare(value, views, &canvas);
          require(bool(value.pointer.flags & PointerHit) == covered && value.pointer.hand == hand &&
                  value.pointer.held == Select && value.pointer.pressed == Menu &&
                  std::memcmp(&views.input, &value.input, sizeof(value.input)) == 0,
                  "menu coverage picking drifted, resampled or lost controller actions");
          if (covered) require(std::abs(value.pointer.x-x) < .002f && std::abs(value.pointer.y-y) < .002f,
                               "covered pointer lost physical canvas coordinates");
          else require(value.pointer.x == 0 && value.pointer.y == 0, "uncovered pixel retained stale pointer");
        }
      }
    }
    views.input.flags = 0;
    panel.prepare(value, views, &canvas);
    require(!value.pointer.flags && !value.pointer.held && !value.pointer.pressed,
            "unfocused interactive overlay retained selection");
    views.input.flags = InputFocused; views.input.hands[1].flags = 0;
    value.hand = 1;
    panel.prepare(value, views, &canvas);
    require(value.pointer.flags == PointerHit && value.pointer.hand == 0,
            "interactive overlay lost tracked-hand fallback");
    auto empty = overlayCanvas(extent[0], extent[1]);
    panel.prepare(value, views, &empty);
    require(!value.pointer.flags && value.pointer.held == Select,
            "next frame's empty overlay inherited previous menu coverage");
    value.flags = 0;
    rejects([&] { panel.prepare(value, views, &canvas); });
    panel.prepare(value, views);
    require(value.pointer.flags == PointerHit, "flat interface inherited last overlay's holes");
    value.flags = PanelTransparent;
    for (unsigned kind = 0; kind < 3; ++kind) {
      auto bad = canvas;
      if (kind == 0) --bad.width;
      if (kind == 1) bad.pixels.pop_back();
      if (kind == 2) bad.coverage.pop_back();
      rejects([&] { panel.prepare(value, views, &bad); });
    }
  }
}
void readableMenus() {
  const uint16_t source[]{0xf800,0x07e0,0x001f,0xffff};
  for (const auto extent : {std::array<uint32_t,2>{1024,768}, {1280,800}, {3840,2160}}) {
    auto views=frame(); auto value=request(); PanelState panel;
    value.flags=PanelTransparent|PanelReadableMenu;
    value.canvasWidth=extent[0]; value.canvasHeight=extent[1];
    auto image=overlayCanvas(extent[0],extent[1]);
    OverlayPart button{0,OverlayInteractive,0,0,0,2,2,int32_t(extent[0])-20,13};
    compositeOverlay(image,button,source,4,2,2);
    panel.prepare(value,views,&image);
    const auto displayed=value.geometry, ordinary=panel.canvasGeometry();
    require(close(displayed.size[0]/ordinary.size[0],1.8f) &&
            close(displayed.size[1]/ordinary.size[1],1.8f),"readable menu stretched or failed to enlarge");
    // The first menu's top center is above the anchor. Its original native
    // coordinates remain unchanged, even when it was at a desktop edge.
    const float anchorX=float(button.x)+1.f, anchorY=float(button.y);
    require(close(displayed.position[0]+(anchorX/float(extent[0])-.5f)*displayed.size[0],0) &&
            close(displayed.position[1]+(.5f-anchorY/float(extent[1]))*displayed.size[1],1.54f),
            "menu edge placement did not anchor its visible controls");
    for (unsigned hand : {0u,1u}) for (const auto delta : {std::array<float,2>{.5f,.5f},
          {1.5f,1.5f},{-.5f,.5f},{2.5f,.5f},{.5f,-.5f},{.5f,2.5f}}) {
      const float x=float(button.x)+delta[0], y=float(button.y)+delta[1];
      value.hand=hand;
      views.input.hands[hand].position[0]=displayed.position[0]+(x/float(extent[0])-.5f)*displayed.size[0];
      views.input.hands[hand].position[1]=displayed.position[1]+(.5f-y/float(extent[1]))*displayed.size[1];
      panel.prepare(value,views,&image);
      const bool inside=delta[0]>0 && delta[0]<2 && delta[1]>0 && delta[1]<2;
      require(bool(value.pointer.flags&PointerHit)==inside,"readable menu ray differs from its visible button");
      if (inside) require(std::abs(value.pointer.x-x)<.002f && std::abs(value.pointer.y-y)<.002f,
                          "readable menu changed native picking coordinates");
    }
    // Expanding a submenu or adding an off-center tooltip must not refit the
    // existing menu. The display-only canvas geometry must never move with it.
    button.x-=40; button.y+=40;
    compositeOverlay(image,button,source,4,2,2);
    auto tooltip=button; tooltip.flags=OverlayMenuCompanion; tooltip.x=0;
    compositeOverlay(image,tooltip,source,4,2,2);
    panel.prepare(value,views,&image);
    require(std::memcmp(&displayed,&value.geometry,sizeof(displayed))==0 &&
            std::memcmp(&ordinary,&panel.canvasGeometry(),sizeof(ordinary))==0,
            "popup refit moved menu buttons or display-only labels");
    value.flags=PanelTransparent;
    panel.prepare(value,views,&image);
    require(std::memcmp(&ordinary,&value.geometry,sizeof(ordinary))==0,"closing readable menu retained enlarged placement");
  }
  OverlayLayers layers;
  layers.begin(128,128,true);
  const OverlayPart menu{0,OverlayInteractive,0,0,0,2,2,61,43};
  auto tooltip=menu; tooltip.flags=OverlayMenuCompanion; tooltip.x=70;
  auto caption=menu; caption.flags=0; caption.x=3; caption.y=110;
  layers.composite(menu,source,4,2,2);
  layers.composite(tooltip,source,4,2,2);
  layers.composite(caption,source,4,2,2);
  require(layers.image().pixels[43*128+61] && layers.image().pixels[43*128+70] &&
          !layers.image().pixels[110*128+3] && !layers.image().hit(70.5f,43.5f),
          "menu-linked labels were lost or became interactive");
  const auto* display=layers.displayImage();
  require(display && display->pixels[110*128+3] && !display->pixels[43*128+61] && display->coverage.empty(),
          "caption/status content inherited the menu plane or input");
  layers.begin(128,128,true); layers.composite(menu,source,4,2,2);
  require(!layers.displayImage(),"retired caption resubmitted its old auxiliary quad");
  layers.begin(128,128,false); layers.composite(tooltip,source,4,2,2);
  require(!layers.displayImage() && layers.image().pixels[43*128+70] && !layers.image().hit(70.5f,43.5f),
          "ordinary world tooltip acquired menu placement or picking");
}
void reusedOverlays() {
  OverlayBuffer buffer, independent;
  const uint16_t source[8]{1, 0, 0xffff, 0xaaaa, 0xf800, 1, 0x1f, 0xbbbb};
  rejects([&] { buffer.begin(0, 0); });
  for (const auto extent : {std::array<uint32_t, 2>{6, 4}, {1280, 800}, {3840, 2160}, {6, 4}}) {
    for (unsigned frame = 0; frame < 10; ++frame) {
      buffer.begin(extent[0], extent[1]);
      auto fresh = overlayCanvas(extent[0], extent[1]);
      auto add = [&](OverlayPart part) {
        buffer.composite(part, source, 8, 3, 2);
        compositeOverlay(fresh, part, source, 8, 3, 2);
      };
      // Moving/shrinking controls, opaque black, keyed holes, edge clipping,
      // display-only occlusion, empty frames and labels following controls.
      if (frame < 8) {
        OverlayPart part{0, OverlayKeyed | OverlayInteractive, 1, 0, 0, 3, 2,
                         frame & 1 ? int32_t(extent[0])-2 : -1,
                         frame & 2 ? int32_t(extent[1])-1 : 0};
        if (frame >= 4) { part.flags = 0; part.key = 0; }
        add(part);
        if (frame & 1) { part.flags = OverlayKeyed; part.key = 1; --part.x; add(part); }
      }
      const auto& reused = buffer.image();
      require(reused.pixels == fresh.pixels, "reused overlay retained pixels or changed composition");
      const auto crop = overlayUploadRegion(reused), expectedCrop = overlayUploadRegion(fresh);
      require(crop.left == expectedCrop.left && crop.top == expectedCrop.top &&
              crop.right == expectedCrop.right && crop.bottom == expectedCrop.bottom,
              "reused overlay retained or shifted its upload footprint");
      for (size_t i = 0; i < fresh.pixels.size(); ++i)
        require((reused.coverage.empty() ? 0 : reused.coverage[i]) ==
                (fresh.coverage.empty() ? 0 : fresh.coverage[i]),
                "reused overlay retained hits or changed input coverage");
    }
  }
  buffer.begin(6, 4);
  OverlayPart part{0, OverlayInteractive, 0, 0, 0, 3, 2, 1, 1};
  buffer.composite(part, source, 8, 3, 2);
  const auto prior = buffer.image().pixels;
  rejects([&] { buffer.begin(8192, 8192); });
  rejects([&] { buffer.begin(0, 4); });
  require(buffer.image().pixels == prior, "failed resize corrupted the reusable canvas");
  independent.begin(6, 4);
  require(independent.image().pixels == std::vector<uint32_t>(24), "another device inherited overlay content");
  // A valid earlier part followed by a rejected later part is not submitted
  // by the caller. The next batch must clear that abandoned partial content.
  auto bad = part; bad.flags = 16;
  rejects([&] { buffer.composite(bad, source, 8, 3, 2); });
  buffer.begin(6, 4);
  require(buffer.image().pixels == independent.image().pixels && !buffer.image().hit(1, 1),
          "abandoned overlay batch leaked pixels or hits into the next frame");
}
void uploadFootprints() {
  const uint16_t source[8]{1, 0, 0xffff, 0xaaaa, 0xf800, 1, 0x1f, 0xbbbb};
  auto image = overlayCanvas(1280, 800);
  auto crop = overlayUploadRegion(image);
  require(crop.left == 0 && crop.top == 0 && crop.width() == 1 && crop.height() == 1 &&
          image.pixels[0] == 0, "empty upload is not explicitly transparent");
  OverlayPart part{0, OverlayKeyed | OverlayInteractive, 1, 0, 0, 3, 2, 101, 77};
  compositeOverlay(image, part, source, 8, 3, 2);
  crop = overlayUploadRegion(image);
  require(crop.left == 101 && crop.top == 77 && crop.right == 104 && crop.bottom == 79 &&
          image.hit(102.5f, 77.5f) && !image.hit(1.5f, .5f),
          "upload crop changed complete-canvas coordinates or inferred keyed holes");
  part.x = -1; part.y = 799;
  compositeOverlay(image, part, source, 8, 3, 2);
  crop = overlayUploadRegion(image);
  require(crop.left == 0 && crop.top == 77 && crop.right == 104 && crop.bottom == 800,
          "upload footprint failed to union clipped producer rectangles");
  part.x = INT32_MAX; part.y = INT32_MIN;
  compositeOverlay(image, part, source, 8, 3, 2);
  const auto clipped = overlayUploadRegion(image);
  require(clipped.left == crop.left && clipped.top == crop.top && clipped.right == crop.right &&
          clipped.bottom == crop.bottom, "offscreen producer expanded upload bounds");
  for (unsigned kind = 0; kind < 5; ++kind) {
    auto invalid = image;
    if (kind == 0) invalid.bounds.left = invalid.bounds.right+1;
    if (kind == 1) invalid.bounds.top = invalid.bounds.bottom+1;
    if (kind == 2) invalid.bounds.right = invalid.width+1;
    if (kind == 3) invalid.bounds.bottom = invalid.height+1;
    if (kind == 4) invalid.pixels.pop_back();
    rejects([&] { overlayUploadRegion(invalid); });
  }
  for (const uint32_t canvas : {1u, 96u, 800u, 1280u, 3840u, 16384u})
    for (uint32_t needed = 1; needed <= canvas; ++needed) {
      const auto capacity = overlayTextureExtent(needed, canvas);
      require(capacity >= needed && capacity <= canvas,
              "upload allocation cannot contain the crop or exceeds its canvas");
    }
  rejects([&] { overlayTextureExtent(0, 800); });
  rejects([&] { overlayTextureExtent(801, 800); });
  rejects([&] { overlayTextureExtent(1, 16385); });
}
void pixelRows() {
  auto expected = [](uint16_t pixel) {
    const uint32_t red = (pixel >> 11) & 31, green = (pixel >> 5) & 63, blue = pixel & 31;
    const uint32_t r = red*8+red/4, g = green*4+green/16, b = blue*8+blue/4;
    return 0xff000000u | (r*65536+g*256+b);
  };
  std::vector<uint8_t> input(65536*2+1);
  for (uint32_t i = 0; i < 65536; ++i) {
    const uint16_t pixel = uint16_t(i);
    std::memcpy(input.data()+1+i*2, &pixel, 2);
  }
  std::vector<uint32_t> output(65536+2, 0x12345678);
  std::vector<uint8_t> coverage(65536+2, 7);
  // Unaligned source/destination, every possible RGB565 value, opaque black,
  // and exact output/picking bounds. The oracle does not share the SIMD code.
  overlay_detail::row<false>(output.data()+1, coverage.data()+1, input.data()+1, 65536, 0, true);
  require(output.front() == 0x12345678 && output.back() == 0x12345678 &&
          coverage.front() == 7 && coverage.back() == 7, "pixel row wrote beyond its span");
  for (uint32_t i = 0; i < 65536; ++i)
    require(output[i+1] == expected(uint16_t(i)) && coverage[i+1] == 1,
            "opaque conversion changed RGB565 bit replication or hit coverage");
  for (const uint16_t key : {uint16_t(0), uint16_t(1), uint16_t(0xffff), uint16_t(0x7e0)}) {
    std::fill(output.begin(), output.end(), 0x12345678);
    std::fill(coverage.begin(), coverage.end(), uint8_t(7));
    overlay_detail::row<true>(output.data()+1, coverage.data()+1, input.data()+1, 65536, key, false);
    for (uint32_t i = 0; i < 65536; ++i)
      require(output[i+1] == (i == key ? 0x12345678 : expected(uint16_t(i))) &&
              coverage[i+1] == (i == key ? 7 : 0),
              "keyed row lost underlying pixels/coverage or made a display-only part interactive");
  }
  // Mixed holes at every SIMD lane and scalar tail; source can end exactly at
  // a row boundary. Vary offsets/counts through multiple complete batches.
  for (size_t start = 0; start < 8; ++start) for (size_t count = 0; count < 33; ++count) {
    std::vector<uint8_t> source(count*2+start);
    output.assign(count+2, 0x12345678); coverage.assign(count+2, 7);
    for (size_t i = 0; i < count; ++i) {
      const uint16_t pixel = i % 3 == 0 ? uint16_t(1) : uint16_t((i*977)&0xffff);
      std::memcpy(source.data()+start+i*2, &pixel, 2);
    }
    for (const bool interactive : {false, true}) {
      std::fill(output.begin(), output.end(), 0x12345678);
      std::fill(coverage.begin(), coverage.end(), uint8_t(7));
      overlay_detail::row<true>(output.data()+1, coverage.data()+1,
        count ? source.data()+start : nullptr, count, 1, interactive);
      for (size_t i = 0; i < count; ++i) {
        uint16_t pixel; std::memcpy(&pixel, source.data()+start+i*2, 2);
        require(output[i+1] == (pixel == 1 ? 0x12345678 : expected(pixel)) &&
                coverage[i+1] == (pixel == 1 ? 7 : uint8_t(interactive)),
                "mixed key lanes, tail or alignment changed row composition");
      }
      require(output.front() == 0x12345678 && output.back() == 0x12345678 &&
              coverage.front() == 7 && coverage.back() == 7, "mixed row wrote beyond its span");
    }
    std::fill(output.begin(), output.end(), 0x12345678);
    overlay_detail::row<false>(output.data()+1, nullptr,
      count ? source.data()+start : nullptr, count, 0, false);
    require(output.front() == 0x12345678 && output.back() == 0x12345678,
            "display-only row without coverage wrote beyond its span");
    for (size_t i = 0; i < count; ++i) {
      uint16_t pixel; std::memcpy(&pixel, source.data()+start+i*2, 2);
      require(output[i+1] == expected(pixel), "display-only row without coverage changed colors");
    }
  }
}
void fadedOverlays() {
  const uint16_t source[4]{0, 0xffff, 1, 0xf800};
  OverlayPart part{0, OverlayKeyed, 1, 0, 0, 4, 1, 0, 0};
  // Test every transport fade level with an independent double-precision
  // source-over oracle. RGB565 source black remains visible with nonzero
  // alpha. The key, not black or an image difference, defines the holes.
  for (unsigned fade = 0; fade <= 255; ++fade) {
    auto image = overlayCanvas(4, 1);
    image.pixels.assign(4, 0x80402010);
    image.coverage.assign(4, 1);
    part.opacity = float(fade)/255;
    compositeOverlay(image, part, source, 8, 4, 1);
    for (unsigned x = 0; x < 4; ++x) {
      uint32_t expected = 0;
      const uint32_t colors[]{0xff000000, 0xffffffff, 0, 0xffff0000};
      for (unsigned shift = 0; shift < 32; shift += 8) {
        const double src = double((colors[x] >> shift) & 255);
        const double prior = double((0x80402010u >> shift) & 255);
        expected |= uint32_t(std::lround((src*fade + prior*(255-fade))/255)) << shift;
      }
      if (x == 2 || fade == 0) expected = 0x80402010;
      require(image.pixels[x] == expected, "fade changed source-over color, alpha or key holes");
      require(image.coverage[x] == (x == 2 || !fade ? 1 : 0),
              "fading label became a control or invisible pixels occluded input");
      for (unsigned shift = 0; shift < 24; shift += 8)
        require(((image.pixels[x] >> shift) & 255) <= (image.pixels[x] >> 24),
                "fade produced invalid premultiplied colors");
    }
    require((image.bounds.empty()) == (fade == 0), "invisible fade retained an upload footprint");
  }
  for (const float invalid : {-1.f, 1.001f, std::numeric_limits<float>::infinity(),
                              -std::numeric_limits<float>::infinity(),
                              std::numeric_limits<float>::quiet_NaN()}) {
    auto image = overlayCanvas(4, 1); part.opacity = invalid;
    rejects([&] { compositeOverlay(image, part, source, 8, 4, 1); });
    require(image.pixels == std::vector<uint32_t>(4) && image.bounds.empty(),
            "invalid producer opacity mutated the canvas");
  }
  // Actual layer order: translucent black backing then independently faded
  // white glyphs. A later frame withdrawing both must not retain either.
  OverlayBuffer buffer;
  buffer.begin(4, 1); part.key = 0; part.flags = 0; part.opacity = .5f;
  const uint16_t black[4]{};
  buffer.composite(part, black, 8, 4, 1);
  part.flags = OverlayKeyed; part.key = 1;
  buffer.composite(part, source, 8, 4, 1);
  require(buffer.image().pixels[1] == 0xc0808080 && buffer.image().pixels[2] == 0x80000000,
          "independent glyph/background fades lost authored order or opaque black");
  buffer.begin(4, 1); part.opacity = 0;
  buffer.composite(part, source, 8, 4, 1);
  require(buffer.image().pixels == std::vector<uint32_t>(4) && buffer.image().bounds.empty(),
          "completed fade retained pixels from the previous frame");
}
void readableSubtitles() {
  const uint16_t source[4]{0xffff, 1, 0, 0xffff};
  OverlayLayers layers;
  const OverlayPart subtitle{0,OverlayKeyed|OverlaySubtitle,1,0,0,2,2,61,120};
  const OverlayPart menu{0,OverlayInteractive,0,0,0,2,2,61,43};
  const OverlayPart status{0,0,0,0,0,2,2,3,4};
  layers.begin(128,128,true);
  layers.composite(menu,source,4,2,2);
  layers.composite(status,source,4,2,2);
  layers.composite(subtitle,source,4,2,2);
  require(layers.subtitleImage() && layers.subtitleImage()->pixels[120*128+61] &&
          !layers.image().pixels[120*128+61] && !layers.displayImage()->pixels[120*128+61] &&
          layers.subtitleImage()->coverage.empty(),"subtitles inherited menu/HUD pixels or picking");
  layers.subtitleBackdrop();
  require(layers.subtitleImage()->pixels[120*128+61]==0xffffffff &&
          layers.subtitleImage()->pixels[120*128+62]==0xff000000 &&
          layers.subtitleImage()->pixels[121*128+61]==0xff000000 &&
          !layers.subtitleImage()->pixels[119*128+61] &&
          layers.subtitleImage()->coverage.empty(),
          "cinematic subtitle backing changed colors, exceeded native bounds or became interactive");
  layers.begin(128,128,false); layers.composite(status,source,4,2,2);
  require(!layers.subtitleImage(),"retired subtitle retained its quad");
  layers.composite(subtitle,source,4,2,2);
  require(layers.subtitleImage() && !layers.subtitleImage()->pixels[4*128+3],"reopened subtitle retained old HUD content");
  auto bad=subtitle; bad.flags|=OverlayInteractive;
  rejects([&] { layers.composite(bad,source,4,2,2); });
  bad=subtitle; bad.flags|=OverlayMenuCompanion;
  rejects([&] { layers.composite(bad,source,4,2,2); });
  PanelState panel; rejects([&] { panel.subtitleGeometry(1280,800); });
  auto value=request(); value.canvasWidth=1280; value.canvasHeight=800;
  auto views=frame(); panel.prepare(value,views);
  const auto ordinary=panel.canvasGeometry();
  const auto caption=panel.subtitleGeometry(1280,800);
  const auto normal=rotate({ordinary.orientation[0],ordinary.orientation[1],ordinary.orientation[2],ordinary.orientation[3]},
                           {0,0,1});
  const float forward=(caption.position[0]-ordinary.position[0])*normal.x+
                      (caption.position[1]-ordinary.position[1])*normal.y+
                      (caption.position[2]-ordinary.position[2])*normal.z;
  const float captionDistance=value.distanceMeters-forward;
  require(caption.size[1]>ordinary.size[1]*2 && close(caption.size[0]/caption.size[1],1.6f) &&
          forward>0 && captionDistance>0 &&
          close(caption.size[1]/captionDistance,1.6f) &&
          close((caption.position[1]-.5f*caption.size[1]-ordinary.position[1])/captionDistance,-.3125f) &&
          std::memcmp(&ordinary,&panel.canvasGeometry(),sizeof(ordinary))==0,
          "subtitle physical scale/bottom anchor changed ordinary UI geometry");
  value.flags=PanelTransparent|PanelReadableMenu;
  auto menuCanvas=overlayCanvas(1280,800);
  compositeOverlay(menuCanvas,menu,source,4,2,2);
  panel.prepare(value,views,&menuCanvas);
  const auto withMenu=panel.subtitleGeometry(1280,800);
  require(std::memcmp(&caption,&withMenu,sizeof(caption))==0,"menu opening shifted dialogue");
  for (auto& eye : views.eyes) {
    eye.position[0]+=.08f; eye.position[1]+=.04f; eye.position[2]-=.05f;
    const float angle=.2f; eye.orientation[1]=std::sin(angle/2); eye.orientation[3]=std::cos(angle/2);
  }
  panel.prepare(value,views,&menuCanvas);
  const auto moved=panel.subtitleGeometry(1280,800);
  require(std::memcmp(&caption,&moved,sizeof(caption))==0,"head motion moved separated subtitles");
}
void visiblePointer() {
  PanelPointer pointer{};
  require(panelCursor(&pointer,1280,800).empty(),"invalid pointer was displayed");
  pointer.flags=PointerHit; pointer.x=640.5f; pointer.y=400.5f;
  for (uint32_t held : {0u, uint32_t(Select)}) {
    pointer.held=held;
    const auto rects=panelCursor(&pointer,1280,800);
    require(rects.size()==4 && rects.back().white && rects.back().left==640 &&
            rects.back().top<400 && rects.back().bottom>400,
            "held or idle pointer lost its visible picking coordinate");
  }
  for (float x : {0.f,1279.9f}) for(float y : {0.f,799.9f}) {
    pointer.x=x; pointer.y=y;
    for(const auto& rect:panelCursor(&pointer,1280,800))
      require(rect.left>=0 && rect.top>=0 && rect.right<=1280 && rect.bottom<=800 &&
              rect.left<rect.right && rect.top<rect.bottom,"edge cursor escaped its canvas");
  }
  pointer.x=std::numeric_limits<float>::quiet_NaN();
  require(panelCursor(&pointer,1280,800).empty(),"NaN pointer reached drawing");
  pointer.x=1280;
  require(panelCursor(&pointer,1280,800).empty(),"outside pointer clamped to an edge");
}
int main() {
  try {
    visiblePointer(); placement(); hitTesting(); modalSizeTransitions(); upright(); invalid(); worldInput(); sharedShortcuts(); transparentCaptions(); composedOverlays();
    interactiveOverlays(); readableMenus(); readableSubtitles(); reusedOverlays(); uploadFootprints(); pixelRows(); fadedOverlays();
    std::cout << "Panels passed: anchored upright placement, aspect ratio, recenter, both-hand edge picking, focus/tracking loss, back-face rejection\n";
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
