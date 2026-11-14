#pragma once

#include <cstddef>
#include <cstdint>
#include <vulkan/vulkan_core.h>

namespace gk3hd::vr {
// Vulkan counts attachment locations, not populated entries. Preserve holes
// before the last used location, including depth-only passes with no colors.
// The render subpass and its blend state must use this same count.
template<typename Attachment, std::size_t N>
constexpr uint32_t colorAttachmentCount(const Attachment (&colors)[N]) {
  auto count = uint32_t(N);
  while (count && colors[count - 1].format == VK_FORMAT_UNDEFINED) --count;
  return count;
}
}
