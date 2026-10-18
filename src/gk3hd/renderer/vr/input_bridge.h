#pragma once

#include <cstdint>

namespace gk3hd::vr {

// Native snapshot, sampled once at the predicted eye display time. No runtime
// handles cross the bridge. Hands are left, right; poses use LOCAL metres.
enum InputButton : uint32_t {
  Select = 1u, Cancel = 2u, Menu = 4u, Inventory = 8u, Recenter = 16u
};
constexpr uint32_t InputFocused = 1u;
constexpr uint32_t AimValid = 1u;
struct HandInput {
  uint32_t flags = 0, held = 0, pressed = 0;
  float orientation[4]{};
  float position[3]{};
  float stick[2]{};
};
struct InputSnapshot {
  uint32_t flags = 0;
  HandInput hands[2]{};
};
static_assert(sizeof(HandInput) == 48 && sizeof(InputSnapshot) == 100,
              "input bridge must use fixed-width values");

} // namespace gk3hd::vr
