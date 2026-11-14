#pragma once

#include <vulkan/vulkan.h>
#define XR_USE_GRAPHICS_API_VULKAN
#include <openxr/openxr.h>
#include <openxr/openxr_platform.h>
#include "input.h"

#include <array>
#include <atomic>
#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace gk3hd::vr {

struct PanelLayer { XrPosef pose; XrExtent2Df size; bool transparent = false; };

// XR transactions have one exclusive owner: the engine/render thread normally,
// or a joined-at-handoff loading worker. Never call these from DllMain.
// The host owns Vulkan objects. This object owns XR handles only and must be
// destroyed before the host destroys the graphics device. The host must drain
// GPU work referencing XR images before shutdown; this class cannot wait on a
// graphics queue it does not own.
class Runtime {
public:
  // Optional diagnostic sink: true/false describe observed headset tracking;
  // nullopt withdraws that observation on hidden/failed frames or teardown.
  // Runs on the exclusive XR owner, never grants input or changes frame order.
  explicit Runtime(PFN_xrGetInstanceProcAddr resolve = xrGetInstanceProcAddr,
                   std::function<void(std::optional<bool>)> trackingNotice = {});
  ~Runtime();
  Runtime(const Runtime&) = delete;
  Runtime& operator=(const Runtime&) = delete;

  void initialize();
  // Drain all GPU work using XR images before calling. Keeps the XR instance
  // and selected Vulkan instance/GPU alive for a renderer device recreation.
  void closeSession() noexcept;
  void shutdown() noexcept;
  bool initialized() const { return instance_ != XR_NULL_HANDLE; }
  bool running() const { return running_; }
  bool focused() const { return state_ == XR_SESSION_STATE_FOCUSED; }
  bool exitRequested() const { return exitRequested_; }
  const std::string& name() const { return name_; }
  const std::array<XrViewConfigurationView, 2>& configuration() const { return configuration_; }
  const XrGraphicsRequirementsVulkanKHR& requirements() const { return requirements_; }

  VkInstance createVulkanInstance(PFN_vkGetInstanceProcAddr resolve,
                                const VkInstanceCreateInfo& createInfo);
  VkPhysicalDevice graphicsDevice(VkInstance instance);
  VkDevice createVulkanDevice(PFN_vkGetInstanceProcAddr resolve,
                            const VkDeviceCreateInfo& createInfo);
  void createSession(const XrGraphicsBindingVulkanKHR& graphics);
  void pollEvents();
  // Temporary hidden/stopping states may resume. Terminal loss/exit must not
  // silently fall back to desktop play in the supervised, VR-only player.
  bool readyForFrame();
  // Only an explicitly negotiated runtime contract permits the renderer to
  // skip its early queue drain. Open-frame cleanup always needs protection.
  bool queueFreeFrameBegin() const { return cpuFrameBegin_ && !frameOpen_; }

  // Select one common runtime format. There is no desktop swapchain present
  // or retained-page rotation here. Packing is an explicit renderer request,
  // accepted only for matching eye dimensions within the runtime's limits.
  // Optional mutable world images avoid a final encoded-color copy. A runtime
  // rejecting that usage falls back to ordinary targets; UI is unchanged.
    void createSwapchains(int64_t format, bool preferMutable = false, bool preferPacked = false,
                          bool preferDirect = false);
  bool mutableEyeFormat(unsigned index) const;
  bool directAttachment(unsigned index) const;
  // The physical Vulkan allocation can include rows outside the eye views.
  // A direct image may clear these rows after waiting and before releasing it.
  // The standalone runtime writes transport metadata after release.
  VkExtent2D eyeStorageExtent(unsigned index) const;
  bool packedEyeTargets() const { return packedEyeTargets_; }
  // Both eye subrectangles have been rendered into the acquired left image.
  // The second view shares that image but never acquires/releases it twice.
  void sharePackedProjection();
  void createPanelSwapchain(int64_t format, uint32_t width, uint32_t height);
  // Host must discard borrowed wrappers and drain image work before resizing.
  void destroyPanelSwapchain();
  const std::vector<XrSwapchainImageVulkanKHR>& panelImages() const { return panel_.images; }
  // Independent keyboard target, composed below the qualified native editor
  // panel in the same predicted frame. Never a second wait/begin/frame loop.
  void createKeyboardSwapchain(int64_t format, uint32_t width, uint32_t height);
  void destroyKeyboardSwapchain();
  const std::vector<XrSwapchainImageVulkanKHR>& keyboardImages() const { return keyboard_.images; }
  void createSubtitleSwapchain(int64_t format, uint32_t width, uint32_t height);
  void destroySubtitleSwapchain();
  const std::vector<XrSwapchainImageVulkanKHR>& subtitleImages() const { return subtitle_.images; }
  // Independent one-pixel source for the controller's 3D interface aiming line.
  void createPointerSwapchain(int64_t format);
  void destroyPointerSwapchain();
  const std::vector<XrSwapchainImageVulkanKHR>& pointerImages() const { return pointer_.images; }
  std::vector<int64_t> formats() const;
  const std::vector<XrSwapchainImageVulkanKHR>& images(unsigned eye) const;
  const std::array<XrView, 2>& views() const { return views_; }
  const InputSnapshot& input() const { return input_; }
  XrTime predictedDisplayTime() const { return predictedTime_.load(); }
  // Frame waits can leave the renderer/uploader's Vulkan queue available. The
  // optional balanced callbacks protect only queue-accessing begin/cleanup.
  bool beginFrame(const std::function<void()>& enterQueue = {},
                  const std::function<void()>& leaveQueue = {});
  uint32_t acquireEye(unsigned eye);
  void releaseEye(unsigned eye);
  uint32_t acquirePanel();
  void releasePanel();
  uint32_t acquireKeyboard();
  void releaseKeyboard();
  uint32_t acquireSubtitle();
  void releaseSubtitle();
  // Explicit unchanged-content composition, without acquiring or modifying an image.
  bool reuseSubtitle();
  uint32_t acquirePointer();
  void releasePointer();
  // True only for an accepted world projection, not GPU/display completion.
  bool endFrame(bool rendered, const PanelLayer* panel = nullptr, const PanelLayer* keyboard = nullptr,
                const PanelLayer* subtitle = nullptr, const PanelLayer* pointer = nullptr);

private:
  struct Eye {
    XrSwapchain chain = XR_NULL_HANDLE;
    std::vector<XrSwapchainImageVulkanKHR> images;
    VkExtent2D storageExtent{};
    bool acquired = false;
    bool waited = false;
    bool submitted = false;
    bool releasedContent = false;
    bool mutableFormat = false;
    bool directAttachment = false;
  };

  template<typename T> void load(const char* name, T& target);
  void check(XrResult result, const char* operation) const;
  void requireSession() const;
  void reportTracking(std::optional<bool> tracked) noexcept;
  Eye& eye(unsigned index);
  void createTarget(Eye& target, int64_t format, uint32_t width, uint32_t height,
                    bool preferMutable = false, bool preferDirect = false);
  void destroyTarget(Eye& target) noexcept;
  uint32_t acquireTarget(Eye& target);
  void releaseTarget(Eye& target);

  PFN_xrGetInstanceProcAddr resolve_;
  std::function<void(std::optional<bool>)> trackingNotice_;
  bool cpuFrameBegin_ = false;
  std::optional<bool> tracked_;
  Actions actions_;
  InputSnapshot input_{};
  PFN_xrCreateInstance createInstance_ = nullptr;
  PFN_xrEnumerateInstanceExtensionProperties enumerateExtensions_ = nullptr;
  PFN_xrDestroyInstance destroyInstance_ = nullptr;
  PFN_xrGetInstanceProperties getProperties_ = nullptr;
  PFN_xrGetSystem getSystem_ = nullptr;
  PFN_xrEnumerateViewConfigurationViews enumerateViews_ = nullptr;
  PFN_xrEnumerateEnvironmentBlendModes enumerateBlendModes_ = nullptr;
  PFN_xrGetVulkanGraphicsRequirements2KHR getRequirements_ = nullptr;
  PFN_xrCreateVulkanInstanceKHR createVkInstance_ = nullptr;
  PFN_xrGetVulkanGraphicsDevice2KHR getVkDevice_ = nullptr;
  PFN_xrCreateVulkanDeviceKHR createVkDevice_ = nullptr;
  PFN_xrCreateSession createSession_ = nullptr;
  PFN_xrDestroySession destroySession_ = nullptr;
  PFN_xrCreateReferenceSpace createSpace_ = nullptr;
  PFN_xrDestroySpace destroySpace_ = nullptr;
  PFN_xrPollEvent pollEvent_ = nullptr;
  PFN_xrBeginSession beginSession_ = nullptr;
  PFN_xrEndSession endSession_ = nullptr;
  PFN_xrEnumerateSwapchainFormats enumerateFormats_ = nullptr;
  PFN_xrCreateSwapchain createSwapchain_ = nullptr;
  PFN_xrDestroySwapchain destroySwapchain_ = nullptr;
  PFN_xrEnumerateSwapchainImages enumerateImages_ = nullptr;
  PFN_xrWaitFrame waitFrame_ = nullptr;
  PFN_xrBeginFrame beginFrame_ = nullptr;
  PFN_xrLocateViews locateViews_ = nullptr;
  PFN_xrAcquireSwapchainImage acquireImage_ = nullptr;
  PFN_xrWaitSwapchainImage waitImage_ = nullptr;
  PFN_xrReleaseSwapchainImage releaseImage_ = nullptr;
  PFN_xrEndFrame endFrame_ = nullptr;

  XrInstance instance_ = XR_NULL_HANDLE;
  XrSystemId system_ = XR_NULL_SYSTEM_ID;
  VkInstance vkInstance_ = VK_NULL_HANDLE;
  VkPhysicalDevice vkPhysical_ = VK_NULL_HANDLE;
  VkDevice vkDevice_ = VK_NULL_HANDLE;
  XrSession session_ = XR_NULL_HANDLE;
  XrSpace space_ = XR_NULL_HANDLE;
  XrSessionState state_ = XR_SESSION_STATE_UNKNOWN;
  XrGraphicsRequirementsVulkanKHR requirements_{XR_TYPE_GRAPHICS_REQUIREMENTS_VULKAN_KHR};
  std::array<XrViewConfigurationView, 2> configuration_{};
  std::array<XrView, 2> views_{};
  std::array<Eye, 2> eyes_{};
  // Physical packed ownership is separate from logical per-eye readiness.
  Eye packed_{};
  uint32_t packedIndex_ = 0;
  Eye panel_{};
  XrExtent2Di panelExtent_{};
  Eye keyboard_{};
  XrExtent2Di keyboardExtent_{};
  Eye subtitle_{};
  XrExtent2Di subtitleExtent_{};
  Eye pointer_{};
  XrFrameState frame_{XR_TYPE_FRAME_STATE};
  std::atomic<XrTime> predictedTime_{0};
  std::string name_;
  bool running_ = false;
  bool exitRequested_ = false;
  bool frameOpen_ = false;
  bool packedEyeTargets_ = false, sharedProjection_ = false;
  bool viewsValid_ = false;
};

} // namespace gk3hd::vr
