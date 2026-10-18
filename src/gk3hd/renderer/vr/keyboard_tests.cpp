#include "keyboard.h"
#include "camera.h"
#include <algorithm>
#include <array>
#include <fstream>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>

using namespace gk3hd::vr;
namespace {
void require(bool condition, const char* message) { if (!condition) throw std::runtime_error(message); }
void rejects(const std::function<void()>& action) {
  try { action(); } catch (const std::exception&) { return; }
  throw std::runtime_error("invalid keyboard state was accepted");
}
PanelGeometry panel() { return {{0, 0, 0, 1}, {0, 1.5f, -1.6f}, {1.6f, 1.2f}}; }
InputSnapshot controllers() {
  InputSnapshot input{}; input.flags = InputFocused;
  for (auto& hand : input.hands) {
    hand.flags = AimValid; hand.orientation[3] = 1; hand.position[1] = 1.5f;
  }
  return input;
}
void aim(InputSnapshot& input, const KeyboardFrame& view, float x, float y) {
  const XrQuaternionf q{view.geometry.orientation[0], view.geometry.orientation[1],
                        view.geometry.orientation[2], view.geometry.orientation[3]};
  const auto offset = rotate(q, {(x/float(KeyboardState::Width)-.5f)*view.geometry.size[0],
                         (.5f-y/float(KeyboardState::Height))*view.geometry.size[1], 1.f});
  auto& hand = input.hands[view.hand];
  for (unsigned i = 0; i < 4; ++i) hand.orientation[i] = view.geometry.orientation[i];
  hand.position[0] = view.geometry.position[0]+offset.x;
  hand.position[1] = view.geometry.position[1]+offset.y;
  hand.position[2] = view.geometry.position[2]+offset.z;
}
size_t find(const KeyboardState& state, KeyboardCommand command, uint32_t character = 0) {
  for (size_t i = 0; i < state.keys().size(); ++i)
    if (state.keys()[i].command == command && state.keys()[i].character == character) return i;
  throw std::runtime_error("expected keyboard key is absent");
}
KeyboardFrame click(KeyboardState& state, InputSnapshot& input, const PanelGeometry& parent,
                    uint32_t epoch, unsigned hand, KeyboardCommand command, uint32_t character = 0,
                    bool available = true) {
  input.hands[hand].held = input.hands[hand].pressed = 0;
  const auto view = state.prepare(epoch, parent, input, hand, available);
  const auto& rect = state.keys()[find(state, command, character)].bounds;
  aim(input, view, (float(rect.left)+float(rect.right))*.5f, (float(rect.top)+float(rect.bottom))*.5f);
  state.prepare(epoch, parent, input, hand, available);
  input.hands[hand].held = input.hands[hand].pressed = Select;
  return state.prepare(epoch, parent, input, hand, available);
}
void charactersAndEditing() {
  KeyboardState state; auto input = controllers(); const auto parent = panel();
  std::array<bool, 127> covered{};
  for (unsigned mode = 0; mode < 2; ++mode) {
    for (unsigned caps = 0; caps < 2; ++caps) {
      state.prepare(7, parent, input, 1, true);
      const auto keys = state.keys();
      for (const auto& key : keys) {
        if (key.command != KeyboardCommand::Character) continue;
        const auto event = click(state, input, parent, 7, 1, key.command, key.character);
        require(event.visible && event.consumesSelect && event.action.epoch == 7 &&
                event.action.kind == 1 && event.action.value == key.character,
                "displayed character and dispatched character disagree");
        covered[key.character] = true;
        const auto held = state.prepare(7, parent, input, 1, true);
        require(!held.action.kind, "held key repeated or duplicated a click");
      }
      const auto toggle = click(state, input, parent, 7, 1, KeyboardCommand::Caps);
      require(!toggle.action.kind && state.caps() == !caps, "caps changed the editor or failed to toggle");
    }
    const auto toggle = click(state, input, parent, 7, 1, KeyboardCommand::Symbols);
    require(!toggle.action.kind && state.symbols() == !mode, "symbols changed the editor or failed to toggle");
  }
  for (unsigned c = 32; c <= 126; ++c) require(covered[c], "printable ASCII cannot be entered");
  const KeyboardCommand commands[]{KeyboardCommand::Backspace, KeyboardCommand::Delete,
    KeyboardCommand::Left, KeyboardCommand::Right, KeyboardCommand::Home, KeyboardCommand::End};
  const uint32_t values[]{8, 46, 37, 39, 36, 35};
  for (unsigned i = 0; i < 6; ++i) {
    const auto event = click(state, input, parent, 7, 1, commands[i]);
    require(event.action.kind == 2 && event.action.value == values[i], "native editing key is wrong");
  }
  for (unsigned hand = 0; hand < 2; ++hand) {
    const auto event = click(state, input, parent, 7, hand, KeyboardCommand::Enter);
    require(event.action.epoch == 7 && event.action.kind == 3 && event.action.value == 13 &&
            event.consumesSelect, "explicit confirmation was not isolated from editing/native Select");
    require(!state.prepare(7, parent, input, hand, true).action.kind,
            "held confirmation repeated");
    require(!state.prepare(8, parent, input, hand, true).action.kind,
            "held confirmation crossed editor epochs");
    require(!click(state, input, parent, 8, hand, KeyboardCommand::Enter, 0, false).action.kind,
            "confirmation overwrote a busy mailbox");
    require(!state.prepare(8, parent, input, hand, true).action.kind,
            "suppressed confirmation replayed when mailbox became free");
  }
}
void ownership() {
  KeyboardState state; auto input = controllers(); const auto parent = panel();
  input.hands[1].held = input.hands[1].pressed = Select;
  auto view = state.prepare(1, parent, input, 1, true);
  const auto rect = state.keys().front().bounds;
  aim(input, view, float(rect.left+10), float(rect.top+10));
  require(!state.prepare(1, parent, input, 1, true).action.kind, "opening while held typed a character");
  auto event = click(state, input, parent, 1, 1, KeyboardCommand::Character, 'q');
  require(event.action.value == 'q', "release did not arm keyboard");
  // An editor change, a hand change and a lost session each require a fresh
  // release. There is no queued replay when the mailbox becomes free later.
  require(!state.prepare(2, parent, input, 1, true).action.kind, "old held input crossed an editor epoch");
  event = click(state, input, parent, 2, 1, KeyboardCommand::Caps);
  require(state.caps(), "caps setup failed");
  input.hands[0] = input.hands[1];
  require(!state.prepare(2, parent, input, 0, true).action.kind && !state.caps(),
          "controller handover retained input or keyboard modifiers");
  input.flags = 0;
  require(!state.prepare(2, parent, input, 0, true).visible && state.keys().empty(), "focus loss kept keyboard active");
  input.flags = InputFocused;
  require(!state.prepare(2, parent, input, 0, true).action.kind, "focus return replayed held input");
  input.hands[0].flags = 0;
  require(!state.prepare(2, parent, input, 0, true).visible, "lost tracked hand was replaced by unqualified hand");
  input.hands[0].flags = AimValid;
  event = click(state, input, parent, 3, 0, KeyboardCommand::Character, 'x', false);
  require(!event.action.kind && event.consumesSelect, "occupied mailbox overwrote pending native text");
  require(!state.prepare(3, parent, input, 0, true).action.kind, "mailbox release replayed a suppressed click");
  require(!state.prepare(0, parent, input, 0, true).visible, "closed editor retained keyboard");
  require(!state.prepare(3, parent, input, 2, true).visible, "invalid hand activated keyboard");
  input = controllers();
  const auto old = state.prepare(9, parent, input, 1, true);
  const auto current = state.prepare(10, parent, input, 1, true);
  rejects([&] { state.image(old); });
  require(!state.image(current).pixels.empty(), "stale view damaged the current keyboard");
}
void picking() {
  for (unsigned hand = 0; hand < 2; ++hand) {
    KeyboardState state; auto input = controllers(); auto parent = panel();
    // Rotate and translate the editor panel. Keyboard draw and picking must
    // move together, not assume a centered, forward-facing screen.
    parent.orientation[1] = .5f; parent.orientation[3] = std::sqrt(.75f);
    parent.position[0] = .8f;
    auto view = state.prepare(2, parent, input, hand, true);
    require(view.geometry.size[0] == 1.2f && std::abs(view.geometry.size[1]-.456f) < 1e-6f,
            "keyboard was stretched or oversized");
    for (size_t i = 0; i < state.keys().size(); ++i) {
      const auto rect = state.keys()[i].bounds;
      for (const float x : {float(rect.left)+.1f, float(rect.right)-.1f})
        for (const float y : {float(rect.top)+.1f, float(rect.bottom)-.1f}) {
          aim(input, view, x, y);
          const auto result = state.prepare(2, parent, input, hand, true);
          require(result.hovered == int(i) && result.consumesSelect, "keyboard ray misses a visible key edge");
        }
      require(state.keyAt(float(rect.right), float(rect.top)) == -1,
              "key gap or right boundary became a neighbouring control");
    }
    aim(input, view, -1, 20);
    require(!state.prepare(2, parent, input, hand, true).consumesSelect, "outside keyboard ray clamped to a key");
    aim(input, view, 4, 4);
    input.hands[hand].held = input.hands[hand].pressed = Select;
    auto result = state.prepare(2, parent, input, hand, true);
    require(result.consumesSelect && result.hovered == -1 && !result.action.kind,
            "keyboard background clicked through into game controls");
    input.hands[hand].position[2] = view.geometry.position[2]-10;
    require(!state.prepare(2, parent, input, hand, true).consumesSelect, "back of keyboard accepted a ray");
    require(state.keyAt(std::numeric_limits<float>::quiet_NaN(), 50) == -1, "NaN picked a key");
  }
}
void painting(const char* preview) {
  KeyboardState state; auto input = controllers(); auto parent = panel();
  auto view = state.prepare(4, parent, input, 1, true);
  const auto& first = state.image(view);
  require(first.width == 1200 && first.height == 456 && first.bounds.right == 1200 &&
          first.bounds.bottom == 456 && first.coverage.empty(), "invalid keyboard image footprint");
  const auto* allocation = first.pixels.data();
  const auto pixels = first.pixels;
  require(state.image(view).pixels.data() == allocation && state.image(view).pixels == pixels,
          "unchanged keyboard reallocated or changed pixels");
  for (const auto& key : state.keys()) {
    bool text = false;
    for (uint32_t y = key.bounds.top; y < key.bounds.bottom; ++y)
      for (uint32_t x = key.bounds.left; x < key.bounds.right; ++x)
        text = text || (pixels[size_t(y)*1200+x] & 255) > 170;
    require(text, "keyboard key has no visible label");
  }
  for (auto pixel : pixels) require(pixel >> 24 == 255, "GDI text destroyed keyboard opacity");
  view = click(state, input, parent, 4, 1, KeyboardCommand::Character, 'q');
  require(state.image(view).pixels != pixels && state.image(view).pixels.data() == allocation,
          "hover is invisible or reallocates the keyboard canvas");
  if (preview) {
    std::ofstream file(preview, std::ios::binary);
    file << "P6\n1200 456\n255\n";
    for (const auto color : state.image(view).pixels) {
      const char rgb[]{char(color >> 16), char(color >> 8), char(color)};
      file.write(rgb, 3);
    }
    require(bool(file), "keyboard preview could not be written");
  }
  state.close();
  require(state.image({}).pixels.empty(), "closed keyboard retained a visible image");
}
void invalid() {
  KeyboardState state; auto input = controllers(); const auto good = panel();
  for (unsigned kind = 0; kind < 5; ++kind) {
    auto bad = good;
    switch (kind) {
      case 0: bad.size[0] = 0; break;
      case 1: bad.size[1] = -1; break;
      case 2: bad.position[1] = std::numeric_limits<float>::infinity(); break;
      case 3: bad.orientation[3] = 0; break;
      case 4: bad.size[1] = std::numeric_limits<float>::quiet_NaN(); break;
    }
    rejects([&] { state.prepare(1, bad, input, 1, true); });
    require(state.keys().empty(), "invalid parent retained a keyboard owner");
  }
  auto scaled = good; scaled.orientation[3] = 2;
  const auto view = state.prepare(1, scaled, input, 1, true);
  require(view.geometry.orientation[3] == 1, "keyboard drawing and picking use different quaternion normalization");
  input.hands[1].orientation[3] = 0;
  rejects([&] { state.prepare(1, good, input, 1, true); });
  require(state.keys().empty(), "invalid aim retained a keyboard owner");
}
void bridge() {
  TextKeyboard keyboard;
  TextFrame request{}; request.epoch = 11; request.available = 1;
  keyboard.configure(request);
  PanelFrame parent{}; parent.geometry = panel(); parent.input = controllers(); parent.pointer.hand = 1;
  const auto opened = keyboard.prepare(parent);
  aim(parent.input, opened, 45, 45);
  parent.input.hands[1].held = parent.input.hands[1].pressed = Select | Cancel | Menu;
  parent.pointer.flags = PointerHit;
  parent.pointer.held = parent.pointer.pressed = Select | Cancel | Menu;
  const auto selected = keyboard.prepare(parent);
  require(selected.action.kind == 1 && selected.action.value == '1' && !parent.pointer.flags &&
          parent.pointer.held == (Cancel | Menu) && parent.pointer.pressed == (Cancel | Menu) &&
          parent.input.hands[1].held == (Cancel | Menu) && parent.input.hands[1].pressed == (Cancel | Menu),
          "keyboard selection reached native UI or swallowed Back/Menu");
  keyboard.configure(request);
  require(request.action.epoch == 11 && request.action.kind == 1 && request.action.value == '1',
          "keyboard action did not reach matching native epoch");
  keyboard.configure(request);
  require(!request.action.kind, "keyboard bridge duplicated a delivered character");
  // Native selection snapshots are not mutated by callers after consumption;
  // the renderer supplies a fresh sampled input on the next frame.
  parent.input.hands[1].held = parent.input.hands[1].pressed = Select;
  require(!keyboard.prepare(parent).action.kind, "held selection repeated after bridge delivery");
  parent.input.hands[1].held = parent.input.hands[1].pressed = 0;
  keyboard.prepare(parent);
  parent.input.hands[1].held = parent.input.hands[1].pressed = Select;
  keyboard.prepare(parent);
  request.epoch = 12;
  keyboard.configure(request);
  require(!request.action.kind, "action from old native epoch reached a new editor");
  request.available = 0;
  keyboard.configure(request);
  parent.input.hands[1].held = parent.input.hands[1].pressed = 0; keyboard.prepare(parent);
  parent.input.hands[1].held = parent.input.hands[1].pressed = Select;
  require(!keyboard.prepare(parent).action.kind, "occupied native mailbox accepted a new character");
  request.available = 1; keyboard.configure(request);
  parent.input.hands[1].held = parent.input.hands[1].pressed = Select;
  require(!keyboard.prepare(parent).action.kind, "suppressed input replayed after mailbox became available");
  request.available = 2;
  rejects([&] { keyboard.configure(request); });
  request.available = 1; request.epoch = 0; keyboard.configure(request);
  require(!keyboard.prepare(parent).visible && !request.action.kind, "native editor closure retained keyboard");
}
}
int main(int argc, char** argv) {
  try {
    charactersAndEditing(); ownership(); picking(); invalid(); bridge(); painting(argc > 1 ? argv[1] : nullptr);
    std::cout << "Keyboard passed: all printable ASCII, native editing, labels, both-hand edge rays, epoch/focus/tracking release guards and no queued replay\n";
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
