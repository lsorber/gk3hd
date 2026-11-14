// Private automation protocol, never included in the production renderer.
#pragma once
#include <openxr/openxr.h>
#include <windows.h>
#include <array>
#include <cmath>
#include <cstring>

namespace gk3hd::vr::testinput {
struct TestHandPacket {
  uint32_t flags, buttons;
  XrPosef pose;
  XrVector2f stick;
};
struct TestInputPacket {
  uint32_t magic, sequence, focused, acknowledged;
  std::array<TestHandPacket, 2> hands;
};
static_assert(sizeof(TestInputPacket) == 104, "fixed private test packet");

class TestInputSampler {
public:
  struct Sample {
    const TestInputPacket* packet = nullptr;
    bool committed = false;
  };
  Sample sample(TestInputPacket* source, DWORD now) {
    if (!source) return unavailable();
    const auto first = sequence(source);
    if (!first) return unavailable();
    if (first & 1) return pending(now);
    TestInputPacket copy{};
    std::memcpy(&copy, source, sizeof(copy));
    MemoryBarrier();
    if (first != sequence(source)) return pending(now);
    if (copy.magic != 0x31494B47 || copy.focused > 1) return unavailable();
    for (const auto& hand : copy.hands) {
      if ((hand.flags & ~3u) || (hand.buttons & ~31u)) return unavailable();
      const float values[] = {hand.pose.orientation.x, hand.pose.orientation.y,
        hand.pose.orientation.z, hand.pose.orientation.w, hand.pose.position.x,
        hand.pose.position.y, hand.pose.position.z, hand.stick.x, hand.stick.y};
      for (float value : values) if (!std::isfinite(value)) return unavailable();
    }
    current_ = copy;
    complete_ = true;
    writing_ = false;
    return {&current_, true};
  }
private:
  static uint32_t sequence(TestInputPacket* source) {
    return static_cast<uint32_t>(InterlockedCompareExchange(
      reinterpret_cast<volatile LONG*>(&source->sequence), 0, 0));
  }
  Sample unavailable() {
    complete_ = false;
    writing_ = false;
    return {};
  }
  Sample pending(DWORD now) {
    if (!writing_) { writing_ = true; started_ = now; }
    // An in-progress publication is not runtime focus loss. Keep only the
    // last complete sample, never torn bytes, and never indefinitely if the
    // automation publisher dies while holding the sequence lock.
    if (!complete_ || static_cast<DWORD>(now - started_) > 100) return unavailable();
    return {&current_, false};
  }
  TestInputPacket current_{};
  bool complete_ = false, writing_ = false;
  DWORD started_ = 0;
};
} // namespace gk3hd::vr::testinput
