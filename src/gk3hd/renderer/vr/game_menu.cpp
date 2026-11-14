#include "game_menu.h"
#include "camera.h"
#include "label_canvas.h"
#include "panel.h"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace gk3hd::vr {
void GameMenuState::close() noexcept {
  epoch_ = hand_ = allowed_ = 0;
  blocked_ = dirty_ = true; down_ = false;
  shortcutHeld_ = 0; shortcutBlocked_ = Cancel | Menu;
  page_ = GameMenuPage::Main; paintedHover_ = -2;
  buttons_.clear(); image_.pixels.clear(); image_.coverage.clear(); image_.bounds = {};
}
void GameMenuState::layout(uint32_t allowed) {
  buttons_.clear();
  auto add = [&](GameMenuCommand command, const char* label, unsigned row, bool enabled = true) {
    const uint32_t top = 150+row*104;
    buttons_.push_back({command, label, {72, top, Width-72, top+88}, enabled});
  };
  if (page_ == GameMenuPage::Main) {
    add(GameMenuCommand::Resume, "Resume", 0);
    add(GameMenuCommand::Save, "Save game", 1, (allowed & gameMenuBit(GameMenuCommand::Save)) != 0);
    add(GameMenuCommand::Load, "Load game", 2, (allowed & gameMenuBit(GameMenuCommand::Load)) != 0);
    add(GameMenuCommand::Settings, "Settings", 3, (allowed & gameMenuBit(GameMenuCommand::Settings)) != 0);
    add(GameMenuCommand::Controls, "Controls", 4);
    add(GameMenuCommand::ReturnToProtagonist, "Return to Gabriel / Grace", 5,
        (allowed & gameMenuBit(GameMenuCommand::ReturnToProtagonist)) != 0);
    add(GameMenuCommand::Quit, "Quit game...", 6);
  } else if (page_ == GameMenuPage::ConfirmQuit) {
    add(GameMenuCommand::Quit, "Quit game", 3);
    add(GameMenuCommand::None, "Keep playing", 4);
  } else {
    add(GameMenuCommand::None, "Back", 6);
  }
  dirty_ = true;
}
void GameMenuState::changePage(GameMenuPage page, uint32_t allowed) {
  page_ = page; layout(allowed);
  // Neither the opening press nor a completed tap can activate the new page.
  blocked_ = true; down_ = false; shortcutBlocked_ = Cancel | Menu;
}
GameMenuFrame GameMenuState::prepare(uint32_t epoch, uint32_t allowed, const PanelGeometry& parent,
                                     const InputSnapshot& input, unsigned hand, bool available) {
  if (!epoch) { close(); return {}; }
  if (hand > 1 || (allowed & ~GameMenuAllowed))
    throw std::invalid_argument("invalid game menu configuration");
  if (epoch != epoch_ || hand != hand_) {
    close(); epoch_ = epoch; hand_ = hand; allowed_ = allowed; layout(allowed);
  } else if (allowed != allowed_) { allowed_ = allowed; layout(allowed); blocked_ = true; }
  GameMenuFrame frame{};
  frame.visible = true; frame.epoch = epoch; frame.hand = hand; frame.page = page_;
  frame.geometry = parent;
  const auto q = normalized({parent.orientation[0], parent.orientation[1],
                              parent.orientation[2], parent.orientation[3]});
  const float orientation[]{q.x, q.y, q.z, q.w};
  std::copy_n(orientation, 4, frame.geometry.orientation);
  for (float value : parent.position)
    if (!std::isfinite(value)) throw std::invalid_argument("invalid game menu position");
  for (float value : parent.size)
    if (!std::isfinite(value) || value <= 0) throw std::invalid_argument("invalid game menu size");
  frame.geometry.size[0] = std::min(1.1f, parent.size[0]);
  frame.geometry.size[1] = frame.geometry.size[0]*float(Height)/float(Width);
  if (!(input.flags & InputFocused)) {
    blocked_ = true; down_ = false; shortcutHeld_ = 0; shortcutBlocked_ = Cancel | Menu;
    return frame;
  }
  uint32_t shortcuts = 0, pressed = 0;
  for (const auto& controller : input.hands) if (controller.flags & AimValid) {
    shortcuts |= controller.held & (Cancel | Menu);
    pressed |= controller.pressed & (Cancel | Menu);
  }
  shortcutBlocked_ &= shortcuts;
  const auto freshShortcut = (pressed | (shortcuts & ~shortcutHeld_)) & ~shortcutBlocked_;
  shortcutHeld_ = shortcuts;
  if (freshShortcut && available) {
    if (page_ == GameMenuPage::Main) frame.action = {epoch, uint32_t(GameMenuCommand::Resume)};
    else { changePage(GameMenuPage::Main, allowed); frame.page = page_; }
    return frame;
  }
  const auto& controller = input.hands[hand];
  if (!(controller.flags & AimValid)) { blocked_ = true; down_ = false; return frame; }
  const bool held = (controller.held & Select) != 0;
  const bool wasBlocked = blocked_;
  if (!held) blocked_ = false;
  const XrPosef pose{q, {parent.position[0], parent.position[1], parent.position[2]}};
  const XrPosef aim{{controller.orientation[0], controller.orientation[1],
                      controller.orientation[2], controller.orientation[3]},
                     {controller.position[0], controller.position[1], controller.position[2]}};
  PanelPoint point{};
  if (panelPoint(pose, frame.geometry.size[0], frame.geometry.size[1], aim,
                 float(Width), float(Height), point)) {
    frame.pointer = {PointerHit, hand, point.x, point.y, controller.held, controller.pressed};
    for (size_t i = 0; i < buttons_.size(); ++i) {
      const auto& button = buttons_[i]; const auto& r = button.bounds;
      if (point.x >= float(r.left) && point.x < float(r.right) &&
          point.y >= float(r.top) && point.y < float(r.bottom) && button.enabled) {
        frame.hovered = int(i); break;
      }
    }
  }
  if (frame.hovered >= 0 && !wasBlocked && !down_ && (controller.pressed & Select) && available) {
    const auto command = buttons_[size_t(frame.hovered)].command;
    if (page_ == GameMenuPage::Main && command == GameMenuCommand::Quit)
      changePage(GameMenuPage::ConfirmQuit, allowed);
    else if (command == GameMenuCommand::Controls) changePage(GameMenuPage::Controls, allowed);
    else if (command == GameMenuCommand::None) changePage(GameMenuPage::Main, allowed);
    else frame.action = {epoch, uint32_t(command)};
    if (frame.page != page_) { frame.page = page_; frame.hovered = -1; }
  }
  down_ = held;
  return frame;
}
const OverlayImage& GameMenuState::image(const GameMenuFrame& frame) {
  if (!frame.visible || !epoch_) { close(); return image_; }
  if (frame.epoch != epoch_ || frame.hand != hand_ || frame.page != page_ ||
      frame.hovered < -1 || frame.hovered >= int(buttons_.size()))
    throw std::invalid_argument("stale game menu image");
  if (!dirty_ && paintedHover_ == frame.hovered) return image_;
  LabelCanvas canvas(Width, Height, 38);
  if (!canvas.valid()) throw std::runtime_error("cannot create game menu labels");
  std::fill_n(canvas.pixels, size_t(Width)*Height, 0xff161b22u);
  if (!SetBkMode(canvas.dc, TRANSPARENT)) throw std::runtime_error("cannot configure game menu labels");
  auto text = [&](const std::string& label, RECT rect, bool enabled = true) {
    if (SetTextColor(canvas.dc, enabled ? RGB(245,247,250) : RGB(132,143,156)) == CLR_INVALID ||
        !DrawTextA(canvas.dc, label.c_str(), int(label.size()), &rect,
                   DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX))
      throw std::runtime_error("cannot draw game menu labels");
  };
  text(page_ == GameMenuPage::Main ? "GK3HD - Paused" :
       page_ == GameMenuPage::Controls ? "Controls" : "Quit the game?", {48,32,LONG(Width)-48,120});
  if (page_ == GameMenuPage::Controls) {
    const char* lines[]{"Point and trigger to select", "Off-hand stick: walk and strafe",
      "Pointing-hand stick: snap turn", "Hold the off-hand trigger to teleport",
      "Inventory: open or close your items", "Back: cancel or return one step"};
    for (unsigned i = 0; i < 6; ++i)
      text(lines[i], {24,LONG(164+i*82),LONG(Width)-24,LONG(230+i*82)});
  }
  if (page_ == GameMenuPage::ConfirmQuit)
    text("Unsaved progress will be lost.", {24,190,LONG(Width)-24,300});
  for (size_t i = 0; i < buttons_.size(); ++i) {
    const auto& button = buttons_[i]; const auto& r = button.bounds;
    const uint32_t color = frame.hovered == int(i) ? 0xff276fafu :
      button.enabled ? 0xff303944u : 0xff202630u;
    for (uint32_t y = r.top; y < r.bottom; ++y)
      std::fill(canvas.pixels+size_t(y)*Width+r.left, canvas.pixels+size_t(y)*Width+r.right, color);
    text(button.label, {LONG(r.left),LONG(r.top),LONG(r.right),LONG(r.bottom)}, button.enabled);
  }
  if (!GdiFlush()) throw std::runtime_error("cannot finish game menu labels");
  image_.width = Width; image_.height = Height; image_.pixels.resize(size_t(Width)*Height);
  for (size_t i = 0; i < image_.pixels.size(); ++i) image_.pixels[i] = canvas.pixels[i] | 0xff000000u;
  image_.bounds = {0,0,Width,Height}; image_.coverage.clear();
  dirty_ = false; paintedHover_ = frame.hovered;
  return image_;
}
void GameMenu::configure(GameMenuRequest& request) {
  if (request.size != sizeof(request) || (request.allowed & ~GameMenuAllowed))
    throw std::invalid_argument("invalid game menu bridge request");
  const auto action = pending_; pending_ = {};
  if (request.epoch != epoch_) state_.close();
  epoch_ = request.epoch; allowed_ = request.allowed;
  request.action = epoch_ && action.epoch == epoch_ ? action : GameMenuAction{};
  if (request.action.command && request.action.command != uint32_t(GameMenuCommand::Resume) &&
      request.action.command != uint32_t(GameMenuCommand::Quit) &&
      !(allowed_ & (1u << request.action.command))) request.action = {};
  if (!epoch_) close();
}
GameMenuFrame GameMenu::prepare(PanelFrame& panel) {
  auto frame = state_.prepare(epoch_, allowed_, panel.geometry, panel.input, panel.hand, !pending_.command);
  if (frame.visible) {
    // The whole menu is modal, including empty space and off-panel misses.
    // Preserve real focus/tracking for presentation, but no native shortcut,
    // click or locomotion may reach the covered screen.
    panel.pointer = {}; panel.pointer.hand = panel.hand;
    for (unsigned index = 0; index < 2; ++index) {
      auto& hand = panel.input.hands[index];
      if ((panel.input.flags & InputFocused) && (hand.flags & AimValid))
        consumed_[index] = hand.held;
      hand.held = hand.pressed = 0; hand.stick[0] = hand.stick[1] = 0;
    }
    panel.geometry = frame.geometry;
  } else filterInput(panel);
  if (frame.action.command) pending_ = frame.action;
  return frame;
}
void GameMenu::filterInput(PanelFrame& panel) {
  for (unsigned index = 0; index < 2; ++index) {
    auto& hand = panel.input.hands[index];
    // Missing tracking/focus is not an observed button release. Keep the
    // gesture retired until a real valid sample reports it released.
    if ((panel.input.flags & InputFocused) && (hand.flags & AimValid))
      consumed_[index] &= hand.held;
    hand.held &= ~consumed_[index]; hand.pressed &= ~consumed_[index];
  }
  panelPointerButtons(panel.pointer,panel.input,panel.hand);
}
// Closing visuals/epochs must not rearm the gesture which dismissed them.
// The next real input sample, including a world-only frame, owns release.
void GameMenu::close() noexcept { epoch_ = allowed_ = 0; pending_ = {}; state_.close(); }
} // namespace gk3hd::vr
