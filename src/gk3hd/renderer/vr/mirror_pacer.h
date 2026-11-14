#pragma once

#include <cstdint>
#include <limits>

namespace gk3hd::vr {

// Only the optional desktop preview is paced here. Tracking, world/interface
// rendering and XR submission retain the runtime's full recommended cadence.
class MirrorPacer {
public:
  bool due(int64_t time) {
    if (time <= 0) { reset(); return true; } // No XR prediction: ordinary present.
    if (time < observed_) reset();
    observed_ = time;
    if (time == presented_ || time < next_) return false;
    presented_ = time;
    const auto maximum = std::numeric_limits<int64_t>::max();
    if (time > maximum - interval_) next_ = maximum;
    else if (!next_ || time - next_ >= interval_) next_ = time + interval_;
    else next_ += interval_;
    return true;
  }
  void reset() { observed_ = presented_ = next_ = 0; }

private:
  static constexpr int64_t interval_ = 1'000'000'000 / 30;
  int64_t observed_ = 0, presented_ = 0, next_ = 0;
};

} // namespace gk3hd::vr
