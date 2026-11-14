#pragma once

#include "panel_bridge.h"
#include "overlay.h"
#include <string>
#include <stdexcept>
#include <vector>

namespace gk3hd::vr {

// Values match the native mailbox: printable, editing, explicit confirmation.
// No Escape, host key events or native editor pointers cross this boundary.
struct TextAction { uint32_t epoch = 0, kind = 0, value = 0; };
// Gk3hdXrTextV1: configure the next qualified epoch and retrieve at most one
// action produced by the just-completed panel frame. No process pointers.
struct TextFrame {
  uint32_t size = sizeof(TextFrame), epoch = 0, available = 0;
  TextAction action{};
};
static_assert(sizeof(TextFrame) == 24, "text bridge must use fixed-width values");
enum class KeyboardCommand { Character, Caps, Symbols, Backspace, Delete, Left, Right, Home, End, Enter };
struct KeyboardKey {
  KeyboardCommand command;
  uint32_t character = 0;
  std::string label;
  OverlayRegion bounds;
};
struct KeyboardFrame {
  bool visible = false, consumesSelect = false;
  int hovered = -1;
  uint32_t epoch = 0, hand = 0;
  PanelGeometry geometry{};
  TextAction action{};
};

// Renderer-owned keyboard, anchored below the native editor's panel. The
// caller supplies a currently qualified editor epoch, not an inferred window
// title or pointer. The native consumer must revalidate that epoch on receipt.
// This model emits only intent. Native code revalidates confirmation ownership;
// it never sends OS keys, repeats held input or moves the OS mouse.
class KeyboardState {
public:
  static constexpr uint32_t Width = 1200, Height = 456;
  KeyboardFrame prepare(uint32_t epoch, const PanelGeometry& parent,
                        const InputSnapshot& input, uint32_t hand, bool mailboxAvailable);
  void close() noexcept;
  const std::vector<KeyboardKey>& keys() const { return keys_; }
  int keyAt(float x, float y) const;
  bool caps() const { return caps_; }
  bool symbols() const { return symbols_; }
  // Windows labels are generated with a system font, never shipped font data.
  // Reuses its pixel allocation and redraws only when the view changes.
  const OverlayImage& image(const KeyboardFrame& frame);
private:
  void layout();
  uint32_t epoch_ = 0, hand_ = 0;
  bool caps_ = false, symbols_ = false, blocked_ = true, down_ = false;
  bool dirty_ = true;
  int paintedHover_ = -2;
  std::vector<KeyboardKey> keys_;
  OverlayImage image_{};
};

class TextKeyboard {
public:
  void configure(TextFrame& request) {
    if (request.size != sizeof(request) || request.available > 1)
      throw std::invalid_argument("invalid keyboard text request");
    const auto result = pending_;
    pending_ = {};
    if (request.epoch != epoch_) state_.close();
    epoch_ = request.epoch; available_ = request.available != 0;
    request.action = epoch_ && result.epoch == epoch_ && available_ ? result : TextAction{};
    if (!epoch_) close();
  }
  KeyboardFrame prepare(PanelFrame& panel) {
    auto result = state_.prepare(epoch_, panel.geometry, panel.input, panel.pointer.hand,
                                 available_ && !pending_.kind);
    if (result.consumesSelect) {
      // Preserve Back/Menu, tracking and the shared sampling epoch. Only this
      // keyboard's Select is removed before native UI/world input consumes it.
      panel.pointer.held &= ~Select; panel.pointer.pressed &= ~Select;
      panel.pointer.flags &= ~PointerHit;
      auto& hand = panel.input.hands[result.hand];
      hand.held &= ~Select; hand.pressed &= ~Select;
    }
    if (result.action.kind) pending_ = result.action;
    return result;
  }
  const OverlayImage& image(const KeyboardFrame& frame) { return state_.image(frame); }
  void close() noexcept { epoch_ = 0; available_ = false; pending_ = {}; state_.close(); }
private:
  KeyboardState state_;
  uint32_t epoch_ = 0;
  bool available_ = false;
  TextAction pending_{};
};

} // namespace gk3hd::vr
