#pragma once
#include <atomic>
#include <cstdint>
#include <limits>

namespace gk3hd::vr {

// The synchronous XR render owner grants one permission on this device only.
// A pending, cancelled or panel-only frame never substitutes for its desktop.
class DesktopOutput {
public:
  explicit DesktopOutput(bool stereoOnly = false) : stereoOnly_(stereoOnly) { }
  uint64_t begin() {
    const auto ticket = epoch_.fetch_add(1, std::memory_order_acq_rel) + 1;
    withdraw();
    return ticket;
  }
  void invalidate() { begin(); }
  void withdraw() { ready_.store(0, std::memory_order_release); }
  void acceptedWorld(uint64_t ticket, uint32_t thread, bool accepted) {
    if (!stereoOnly_ || !accepted || !thread || !ticket ||
        ticket > std::numeric_limits<uint32_t>::max() || epoch_.load(std::memory_order_acquire) != ticket)
      return;
    ready_.store((ticket << 32) | thread, std::memory_order_release);
  }
  bool consume(uint32_t thread, bool ordinaryPresent) {
    if (!ordinaryPresent) { invalidate(); return false; }
    if (!thread) return false;
    auto ready = ready_.load(std::memory_order_acquire);
    const auto ticket = ready >> 32;
    if (uint32_t(ready) != thread || !ticket || epoch_.load(std::memory_order_acquire) != ticket)
      return false;
    return ready_.compare_exchange_strong(ready, 0, std::memory_order_acq_rel) &&
           epoch_.load(std::memory_order_acquire) == ticket;
  }
private:
  const bool stereoOnly_;
  std::atomic<uint64_t> epoch_{0}, ready_{0};
};

} // namespace gk3hd::vr
