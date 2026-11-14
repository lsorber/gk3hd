#include "color_attachments.h"

#include <array>
#include <iostream>
#include <stdexcept>

namespace {
struct Color { VkFormat format; uint32_t untouched; };
constexpr Color empty[]{{VK_FORMAT_UNDEFINED, 0}};
static_assert(gk3hd::vr::colorAttachmentCount(empty) == 0);
void expect(bool condition, const char* reason) {
  if (!condition) throw std::runtime_error(reason);
}
}

int main() {
  try {
    // All eight-location occupancy patterns, including interior holes, high
    // numbered outputs and no colors. Never compact or reorder locations.
    for (uint32_t mask = 0; mask != 256; ++mask) {
      Color colors[8]{};
      uint32_t expected = 0;
      for (uint32_t index = 0; index != 8; ++index) {
        colors[index] = {mask & (1u << index) ? VK_FORMAT_R8G8B8A8_UNORM : VK_FORMAT_UNDEFINED,
                         index + 1};
        if (mask & (1u << index)) expected = index + 1;
      }
      const auto before = std::array<Color, 8>{colors[0], colors[1], colors[2], colors[3],
                                               colors[4], colors[5], colors[6], colors[7]};
      expect(gk3hd::vr::colorAttachmentCount(colors) == expected, "Attachment location count changed");
      for (uint32_t index = 0; index != 8; ++index) {
        expect(colors[index].format == before[index].format, "Attachment format was mutated");
        expect(colors[index].untouched == before[index].untouched, "Attachment state was mutated");
      }
    }
    std::cout << "256 sparse color-attachment layouts preserve locations and state\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
