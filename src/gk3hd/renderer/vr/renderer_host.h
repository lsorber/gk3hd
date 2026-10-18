#pragma once

#include "runtime.h"

namespace gk3hd::vr {

// Renderer-owned bridge, constructed before Vulkan initialization and never in
// DllMain. The renderer retains ownership of Vulkan objects and queues. A host
// must drain all image work before stop(), then destroy its graphics device.
class RendererHost {
public:
  explicit RendererHost(PFN_xrGetInstanceProcAddr resolve = xrGetInstanceProcAddr,
                        std::function<void(std::optional<bool>)> trackingNotice = {});
  ~RendererHost();
  RendererHost(const RendererHost&) = delete;
  RendererHost& operator=(const RendererHost&) = delete;

  VkInstance createInstance(PFN_vkGetInstanceProcAddr resolve,
                            const VkInstanceCreateInfo& info);
  VkPhysicalDevice selectDevice(VkInstance instance);
  VkDevice createDevice(PFN_vkGetInstanceProcAddr resolve, VkPhysicalDevice device,
                        const VkDeviceCreateInfo& info);
  void start(const XrGraphicsBindingVulkanKHR& graphics);
  void stopDevice() noexcept;
  void stop() noexcept;
  Runtime& runtime() { return runtime_; }
  VkPhysicalDevice physicalDevice() const { return physical_; }
  VkFormat format() const { return format_; }

private:
  Runtime runtime_;
  VkInstance instance_ = VK_NULL_HANDLE;
  VkPhysicalDevice physical_ = VK_NULL_HANDLE;
  VkDevice device_ = VK_NULL_HANDLE;
  VkFormat format_ = VK_FORMAT_UNDEFINED;
};

} // namespace gk3hd::vr
