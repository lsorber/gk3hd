#include "test_input_feed.h"
#include <iostream>
#include <limits>
#include <stdexcept>
using namespace gk3hd::vr::testinput;
static void require(bool value, const char* message) {
  if (!value) throw std::runtime_error(message);
}
static TestInputPacket packet() {
  TestInputPacket result{};
  result.magic = 0x31494B47; result.sequence = 2; result.focused = 1;
  result.hands[1].flags = 3; result.hands[1].buttons = 1;
  result.hands[1].pose.orientation.w = 1;
  return result;
}
int main() {
  try {
    TestInputSampler sampler;
    auto input = packet();
    auto sampled = sampler.sample(&input, 10);
    require(sampled.committed && sampled.packet && sampled.packet->focused == 1, "valid publication");
    input.sequence = 3; input.focused = 0; input.hands[1].buttons = 31;
    sampled = sampler.sample(&input, 20);
    require(sampled.packet && !sampled.committed && sampled.packet->focused == 1 &&
      sampled.packet->hands[1].buttons == 1, "pending publication invented focus loss or used torn data");
    require(sampler.sample(&input, 120).packet != nullptr, "bounded pending sample");
    require(!sampler.sample(&input, 121).packet, "stalled publisher retained input");
    require(!sampler.sample(&input, 122).packet, "stalled publisher resurrected input");
    input.sequence = 4;
    sampled = sampler.sample(&input, 123);
    require(sampled.committed && sampled.packet && sampled.packet->focused == 0, "explicit focus loss ignored");
    input.sequence = 5; input.focused = 1;
    sampled = sampler.sample(&input, 124);
    require(sampled.packet && sampled.packet->focused == 0, "pending recovery invented focus");
    input.sequence = 6;
    require(sampler.sample(&input, 125).packet->focused == 1, "committed recovery");
    input.magic = 0;
    require(!sampler.sample(&input, 126).packet, "malformed packet retained input");
    input = packet(); input.focused = 2;
    require(!sampler.sample(&input, 127).packet, "invalid focus accepted");
    input = packet(); input.hands[0].pose.position.x = std::numeric_limits<float>::quiet_NaN();
    require(!sampler.sample(&input, 128).packet, "nonfinite pose accepted");
    input = packet(); input.hands[1].flags = 4;
    require(!sampler.sample(&input, 129).packet, "invalid hand accepted");
    input = packet(); input.hands[1].buttons = 32;
    require(!sampler.sample(&input, 130).packet, "invalid buttons accepted");
    input = packet();
    require(sampler.sample(&input, 0xfffffff0u).packet != nullptr, "clock-wrap seed");
    input.sequence = 3;
    require(sampler.sample(&input, 0xfffffff8u).packet != nullptr, "clock-wrap pending");
    require(sampler.sample(&input, 8).packet != nullptr, "clock-wrap lost input");
    require(!sampler.sample(&input, 93).packet, "clock-wrap stalled publisher");
    input = packet(); sampler.sample(&input, 200);
    input.sequence = 0;
    require(!sampler.sample(&input, 201).packet, "empty publisher retained input");
    require(!sampler.sample(nullptr, 202).packet, "missing publisher retained input");
    std::cout << "Test input publication, explicit focus loss and timeout guards passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n'; return 1;
  }
}
