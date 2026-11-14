#pragma once

#include <algorithm>
#include <limits>
#include <stdexcept>
#include <vulkan/vulkan_core.h>

namespace gk3hd::standalone {
// Preserve the visible eyes; the last row carries metadata and spare rows
// satisfy the pinned standalone linear-image import's four-row allocation.
inline uint32_t transportImageHeight(uint32_t visibleHeight) {
  if (!visibleHeight || visibleHeight > std::numeric_limits<uint32_t>::max() - 4)
    throw std::invalid_argument("Standalone eye height overflows its transport");
  return (visibleHeight + 4) & ~3u;
}
// World images are renderable, and their transport includes metadata/padding.
// Never advertise more than either the selected GPU's image or framebuffer
// limit. No HMD model, driver name or assumed desktop GPU limit is involved.
inline VkExtent2D worldImageLimits(const VkPhysicalDeviceLimits& limits) {
  const auto width = std::min(limits.maxImageDimension2D, limits.maxFramebufferWidth);
  const auto height = std::min(limits.maxImageDimension2D, limits.maxFramebufferHeight);
  return {width, height >= 4 ? (height & ~3u) - 1 : 0};
}
}
