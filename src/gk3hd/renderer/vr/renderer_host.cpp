#include "renderer_host.h"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace gk3hd::vr {

RendererHost::RendererHost(PFN_xrGetInstanceProcAddr resolve, std::function<void(std::optional<bool>)> trackingNotice,
                           bool preferMutableWorld)
  : runtime_(resolve, std::move(trackingNotice)), preferMutableWorld_(preferMutableWorld) {
  runtime_.initialize();
}

RendererHost::~RendererHost() { stop(); }

VkInstance RendererHost::createInstance(PFN_vkGetInstanceProcAddr resolve,
                                        const VkInstanceCreateInfo& info) {
  instance_ = runtime_.createVulkanInstance(resolve, info);
  return instance_;
}

VkPhysicalDevice RendererHost::selectDevice(VkInstance instance) {
  physical_ = runtime_.graphicsDevice(instance);
  return physical_;
}

VkDevice RendererHost::createDevice(PFN_vkGetInstanceProcAddr resolve,
                                    VkPhysicalDevice device, const VkDeviceCreateInfo& info) {
  if (device == VK_NULL_HANDLE || device != physical_)
    throw std::invalid_argument("renderer GPU does not match the OpenXR runtime GPU");
  device_ = runtime_.createVulkanDevice(resolve, info);
  return device_;
}

void RendererHost::start(const XrGraphicsBindingVulkanKHR& graphics) {
  if (graphics.instance != instance_ || graphics.physicalDevice != physical_ ||
      graphics.device != device_)
    throw std::invalid_argument("renderer graphics binding does not match its XR device");
  runtime_.createSession(graphics);
  const auto formats = runtime_.formats();
  // Preserve encoded game pixels via an UNORM view (mutable world output) or
  // staging and a bitwise sRGB copy. Linear-only formats need a different color
  // conversion, so fail explicitly rather than silently darkening the image.
  // Standalone's BGRA transport can copy matching encoded pixels verbatim.
  // Keep the ordinary PC-VR preference and use shader conversion if needed.
  const std::array<VkFormat,2> preferred = preferMutableWorld_
    ? std::array<VkFormat,2>{VK_FORMAT_B8G8R8A8_SRGB,VK_FORMAT_R8G8B8A8_SRGB}
    : std::array<VkFormat,2>{VK_FORMAT_R8G8B8A8_SRGB,VK_FORMAT_B8G8R8A8_SRGB};
  for (const auto format : preferred) {
    if (std::find(formats.begin(), formats.end(), format) != formats.end()) {
      runtime_.createSwapchains(format, preferMutableWorld_, preferMutableWorld_, preferMutableWorld_);
      format_ = format;
      return;
    }
  }
  throw std::runtime_error("OpenXR runtime exposes no supported sRGB eye format");
}

void RendererHost::stopDevice() noexcept {
  runtime_.closeSession();
  device_ = VK_NULL_HANDLE;
  format_ = VK_FORMAT_UNDEFINED;
}

void RendererHost::stop() noexcept {
  runtime_.shutdown();
  instance_ = VK_NULL_HANDLE;
  physical_ = VK_NULL_HANDLE;
  device_ = VK_NULL_HANDLE;
  format_ = VK_FORMAT_UNDEFINED;
}

} // namespace gk3hd::vr
