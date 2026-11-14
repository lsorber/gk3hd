#include "gamma.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>
#include <stdexcept>

namespace {
using Channel = std::array<uint16_t, 256>;
struct Ramp { Channel red{}, green{}, blue{}; };
unsigned checks = 0;
void require(bool value, const char* message) {
  ++checks;
  if (!value) throw std::runtime_error(message);
}
bool neutral(const Ramp& ramp, bool immersive = true, bool legacy = true) {
  return gk3hd::vr::isNeutralLegacyXrRamp(immersive, legacy, ramp.red.data(),
      ramp.green.data(), ramp.blue.data(), ramp.red.size());
}
Ramp classic() {
  Ramp ramp;
  for (size_t i = 0; i < ramp.red.size(); ++i)
    ramp.red[i] = ramp.green[i] = ramp.blue[i] = static_cast<uint16_t>(i * 256);
  return ramp;
}
void defaultsAndScope() {
  const auto ramp = classic();
  const auto original = ramp;
  require(neutral(ramp), "classic default still incurs a gamma lookup");
  require(!neutral(ramp, false), "flat rendering policy changed");
  require(!neutral(ramp, true, false), "non-legacy gamma policy changed");
  require(!neutral(ramp, false, false), "dormant VR changed gamma policy");
  require(ramp.red == original.red && ramp.green == original.green && ramp.blue == original.blue,
          "requested ramp was modified");
  require(!gk3hd::vr::isNeutralLegacyXrRamp(true, true, nullptr, ramp.green.data(), ramp.blue.data(), 256),
          "missing red channel accepted");
  require(!gk3hd::vr::isNeutralLegacyXrRamp(true, true, ramp.red.data(), nullptr, ramp.blue.data(), 256),
          "missing green channel accepted");
  require(!gk3hd::vr::isNeutralLegacyXrRamp(true, true, ramp.red.data(), ramp.green.data(), nullptr, 256),
          "missing blue channel accepted");
  for (size_t count : {size_t(0), size_t(1), size_t(255), size_t(257)})
    require(!gk3hd::vr::isNeutralLegacyXrRamp(true, true, ramp.red.data(), ramp.green.data(), ramp.blue.data(), count),
            "nonstandard ramp extent accepted");
}
void everySampleMatters() {
  auto ramp = classic();
  for (auto* channel : {&ramp.red, &ramp.green, &ramp.blue}) {
    for (size_t i = 0; i < channel->size(); ++i) {
      const auto original = (*channel)[i];
      (*channel)[i] = static_cast<uint16_t>(original + 1);
      require(!neutral(ramp), "one-sample brightness change was ignored");
      if (original) {
        (*channel)[i] = static_cast<uint16_t>(original - 1);
        require(!neutral(ramp), "one-sample darkening was ignored");
      }
      (*channel)[i] = original;
      require(neutral(ramp), "neutral reset did not restore fast path");
    }
  }
}
void adjustmentsAndReset() {
  const auto defaultRamp = classic();
  // Synthetic inputs exercise preservation of nonlinear curves. This is not
  // a substitute for an actual native-game brightness-slider acceptance run.
  for (double gamma : {.5, .75, 1.25, 1.5, 2., 3.}) {
    auto changed = defaultRamp;
    for (size_t i = 0; i < changed.red.size(); ++i) {
      const double value = std::pow(double(i) / 256., 1. / gamma) * 65536.;
      changed.red[i] = changed.green[i] = changed.blue[i] =
          static_cast<uint16_t>(std::clamp(std::round(value), 0., 65535.));
    }
    const auto saved = changed;
    require(!neutral(changed), "user brightness adjustment was suppressed");
    require(neutral(defaultRamp), "reset after adjustment did not become neutral");
    require(!neutral(changed), "later brightness adjustment reused stale neutral state");
    require(changed.red == saved.red && changed.green == saved.green && changed.blue == saved.blue,
            "nonlinear input data changed");
  }
  Ramp other{};
  require(!neutral(other), "black ramp incorrectly neutral");
  other.red.fill(65535); other.green.fill(65535); other.blue.fill(65535);
  require(!neutral(other), "white ramp incorrectly neutral");
  for (size_t i = 0; i < other.red.size(); ++i)
    other.red[i] = other.green[i] = other.blue[i] = static_cast<uint16_t>(i * 257);
  require(!neutral(other), "normalized full-range ramp incorrectly classified as classic");
}
}

int main() {
  try {
    defaultsAndScope(); everySampleMatters(); adjustmentsAndReset();
    std::cout << "XR neutral-gamma behavior passed: " << checks << " checks\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n'; return 1;
  }
}
