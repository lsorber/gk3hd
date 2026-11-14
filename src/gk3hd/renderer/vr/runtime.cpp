#include "runtime.h"

#include <algorithm>
#include <cstring>
#include <cmath>
#include <stdexcept>
#include <utility>

namespace gk3hd::vr {

Runtime::Runtime(PFN_xrGetInstanceProcAddr resolve, std::function<void(std::optional<bool>)> trackingNotice)
  : resolve_(resolve), trackingNotice_(std::move(trackingNotice)), actions_(resolve) {
  if (!resolve_) throw std::invalid_argument("OpenXR resolver is missing");
}

Runtime::~Runtime() { shutdown(); }

void Runtime::reportTracking(std::optional<bool> tracked) noexcept {
  if (tracked_ == tracked) return;
  tracked_ = tracked;
  // Feedback is diagnostic only. An unavailable log/status sink must never
  // interrupt legal presentation, bypass tracking guards or change input.
  try { if (trackingNotice_) trackingNotice_(tracked); } catch (...) { }
}

template<typename T> void Runtime::load(const char* name, T& target) {
  PFN_xrVoidFunction address = nullptr;
  check(resolve_(instance_, name, &address), name);
  if (!address) throw std::runtime_error(std::string("OpenXR function missing: ") + name);
  target = reinterpret_cast<T>(address);
}

void Runtime::check(XrResult result, const char* operation) const {
  if (result == XR_ERROR_INSTANCE_LOST || result == XR_ERROR_SESSION_LOST ||
      result == XR_SESSION_LOSS_PENDING) {
    throw std::runtime_error(std::string("GK3HD OpenXR session ended: ") + operation
                             + " (OpenXR " + std::to_string(result) + ")");
  }
  if (XR_FAILED(result)) {
    throw std::runtime_error(std::string(operation) + " failed (OpenXR "
                             + std::to_string(result) + ")");
  }
}

void Runtime::initialize() {
  if (initialized()) throw std::logic_error("OpenXR already initialized");
  try {
    load("xrEnumerateInstanceExtensionProperties", enumerateExtensions_);
    load("xrCreateInstance", createInstance_);
    uint32_t count = 0;
    check(enumerateExtensions_(nullptr, 0, &count, nullptr), "enumerate extensions");
    std::vector<XrExtensionProperties> extensions(count, {XR_TYPE_EXTENSION_PROPERTIES});
    check(enumerateExtensions_(nullptr, count, &count, extensions.data()), "enumerate extensions");
    if (std::none_of(extensions.begin(), extensions.end(), [](const auto& extension) {
      return std::strcmp(extension.extensionName, XR_KHR_VULKAN_ENABLE2_EXTENSION_NAME) == 0;
    })) throw std::runtime_error("OpenXR runtime lacks XR_KHR_vulkan_enable2");
    const char* extension = XR_KHR_VULKAN_ENABLE2_EXTENSION_NAME;
    XrInstanceCreateInfo info{XR_TYPE_INSTANCE_CREATE_INFO};
    std::copy_n("GK3HD", 6, info.applicationInfo.applicationName);
    std::copy_n("GK3", 4, info.applicationInfo.engineName);
    info.applicationInfo.apiVersion = XR_MAKE_VERSION(1, 0, 0);
    info.enabledExtensionCount = 1;
    info.enabledExtensionNames = &extension;
    check(createInstance_(&info, &instance_), "create instance");
    // Resolve destroy first so every subsequent initialization failure unwinds.
    load("xrDestroyInstance", destroyInstance_);
    load("xrGetInstanceProperties", getProperties_);
    load("xrGetSystem", getSystem_);
    load("xrEnumerateViewConfigurationViews", enumerateViews_);
    load("xrEnumerateEnvironmentBlendModes", enumerateBlendModes_);
    load("xrGetVulkanGraphicsRequirements2KHR", getRequirements_);
    load("xrCreateVulkanInstanceKHR", createVkInstance_);
    load("xrGetVulkanGraphicsDevice2KHR", getVkDevice_);
    load("xrCreateVulkanDeviceKHR", createVkDevice_);
    load("xrCreateSession", createSession_);
    load("xrDestroySession", destroySession_);
    load("xrCreateReferenceSpace", createSpace_);
    load("xrDestroySpace", destroySpace_);
    load("xrPollEvent", pollEvent_);
    load("xrBeginSession", beginSession_);
    load("xrEndSession", endSession_);
    load("xrEnumerateSwapchainFormats", enumerateFormats_);
    load("xrCreateSwapchain", createSwapchain_);
    load("xrDestroySwapchain", destroySwapchain_);
    load("xrEnumerateSwapchainImages", enumerateImages_);
    load("xrWaitFrame", waitFrame_);
    load("xrBeginFrame", beginFrame_);
    load("xrLocateViews", locateViews_);
    load("xrAcquireSwapchainImage", acquireImage_);
    load("xrWaitSwapchainImage", waitImage_);
    load("xrReleaseSwapchainImage", releaseImage_);
    load("xrEndFrame", endFrame_);
    XrInstanceProperties properties{XR_TYPE_INSTANCE_PROPERTIES};
    check(getProperties_(instance_, &properties), "runtime properties");
    name_ = properties.runtimeName;
    // Our standalone runtime's event/session polling and xrBeginFrame are
    // CPU-only while no frame is open. Never infer this from its name, an
    // environment variable, or the presence of some other runtime feature.
    PFN_xrVoidFunction capability = nullptr;
    const XrResult queried = resolve_(instance_, "xrGk3hdGetCpuFrameBeginSupportV1", &capability);
    if (queried != XR_ERROR_FUNCTION_UNSUPPORTED) {
      check(queried, "CPU frame-begin capability");
      if (!capability) throw std::runtime_error("missing CPU frame-begin capability function");
      using CpuFrameBegin = XrResult(XRAPI_PTR*)(XrInstance, XrBool32*);
      XrBool32 supported = XR_FALSE;
      check(reinterpret_cast<CpuFrameBegin>(capability)(instance_, &supported), "CPU frame-begin support");
      if (supported != XR_FALSE && supported != XR_TRUE)
        throw std::runtime_error("invalid CPU frame-begin capability");
      cpuFrameBegin_ = supported == XR_TRUE;
    }
    XrSystemGetInfo systemInfo{XR_TYPE_SYSTEM_GET_INFO};
    systemInfo.formFactor = XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;
    check(getSystem_(instance_, &systemInfo, &system_), "find headset");
    check(enumerateBlendModes_(instance_, system_, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO,
                              0, &count, nullptr), "environment blend modes");
    std::vector<XrEnvironmentBlendMode> blendModes(count);
    check(enumerateBlendModes_(instance_, system_, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO,
                              count, &count, blendModes.data()), "environment blend modes");
    if (std::find(blendModes.begin(), blendModes.end(), XR_ENVIRONMENT_BLEND_MODE_OPAQUE)
        == blendModes.end())
      throw std::runtime_error("GK3 requires an opaque OpenXR presentation mode");
    check(getRequirements_(instance_, system_, &requirements_), "Vulkan requirements");
    check(enumerateViews_(instance_, system_, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO,
                          0, &count, nullptr), "stereo views");
    if (count != 2) throw std::runtime_error("OpenXR runtime must expose two stereo views");
    for (auto& view : configuration_) view = {XR_TYPE_VIEW_CONFIGURATION_VIEW};
    check(enumerateViews_(instance_, system_, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO,
                          2, &count, configuration_.data()), "stereo views");
    if (count != 2) throw std::runtime_error("OpenXR view count changed during initialization");
    for (const auto& view : configuration_)
      if (!view.recommendedImageRectWidth || !view.recommendedImageRectHeight ||
          view.recommendedImageRectWidth > static_cast<uint32_t>(INT32_MAX) ||
          view.recommendedImageRectHeight > static_cast<uint32_t>(INT32_MAX))
        throw std::runtime_error("invalid OpenXR eye dimensions");
    actions_.initialize(instance_);
  } catch (...) {
    shutdown();
    throw;
  }
}

VkInstance Runtime::createVulkanInstance(PFN_vkGetInstanceProcAddr resolve,
                                        const VkInstanceCreateInfo& createInfo) {
  if (!initialized() || vkInstance_) throw std::logic_error("invalid Vulkan initialization order");
  if (!resolve) throw std::invalid_argument("Vulkan resolver is missing");
  const uint32_t api = createInfo.pApplicationInfo && createInfo.pApplicationInfo->apiVersion ?
    createInfo.pApplicationInfo->apiVersion : VK_API_VERSION_1_0;
  const XrVersion version = XR_MAKE_VERSION(VK_API_VERSION_MAJOR(api),
                                           VK_API_VERSION_MINOR(api), VK_API_VERSION_PATCH(api));
  if (version < requirements_.minApiVersionSupported || version > requirements_.maxApiVersionSupported)
    throw std::invalid_argument("Vulkan API version is outside the XR runtime's supported range");
  XrVulkanInstanceCreateInfoKHR info{XR_TYPE_VULKAN_INSTANCE_CREATE_INFO_KHR};
  info.systemId = system_;
  info.pfnGetInstanceProcAddr = resolve;
  info.vulkanCreateInfo = &createInfo;
  VkResult result = VK_SUCCESS;
  VkInstance created = VK_NULL_HANDLE;
  check(createVkInstance_(instance_, &info, &created, &result), "create Vulkan instance");
  if (result != VK_SUCCESS) throw std::runtime_error("runtime Vulkan instance creation failed");
  if (!created) throw std::runtime_error("runtime returned a null Vulkan instance");
  vkInstance_ = created;
  return vkInstance_;
}

VkPhysicalDevice Runtime::graphicsDevice(VkInstance instance) {
  if (!initialized() || !vkInstance_ || instance != vkInstance_)
    throw std::logic_error("XR graphics device requires the compatible Vulkan instance");
  XrVulkanGraphicsDeviceGetInfoKHR info{XR_TYPE_VULKAN_GRAPHICS_DEVICE_GET_INFO_KHR};
  info.systemId = system_;
  info.vulkanInstance = instance;
  check(getVkDevice_(instance_, &info, &vkPhysical_), "select Vulkan GPU");
  vkInstance_ = instance;
  return vkPhysical_;
}

VkDevice Runtime::createVulkanDevice(PFN_vkGetInstanceProcAddr resolve,
                                    const VkDeviceCreateInfo& createInfo) {
  if (!vkPhysical_ || vkDevice_) throw std::logic_error("select XR graphics device first");
  if (!resolve) throw std::invalid_argument("Vulkan resolver is missing");
  XrVulkanDeviceCreateInfoKHR info{XR_TYPE_VULKAN_DEVICE_CREATE_INFO_KHR};
  info.systemId = system_;
  info.pfnGetInstanceProcAddr = resolve;
  info.vulkanPhysicalDevice = vkPhysical_;
  info.vulkanCreateInfo = &createInfo;
  VkResult result = VK_SUCCESS;
  VkDevice created = VK_NULL_HANDLE;
  check(createVkDevice_(instance_, &info, &created, &result), "create Vulkan device");
  if (result != VK_SUCCESS) throw std::runtime_error("runtime Vulkan device creation failed");
  if (!created) throw std::runtime_error("runtime returned a null Vulkan device");
  vkDevice_ = created;
  return vkDevice_;
}

void Runtime::createSession(const XrGraphicsBindingVulkanKHR& graphics) {
  if (!vkDevice_ || session_ || graphics.instance != vkInstance_ ||
      graphics.physicalDevice != vkPhysical_ || graphics.device != vkDevice_)
    throw std::logic_error("XR session graphics must match the runtime-selected device");
  XrSessionCreateInfo info{XR_TYPE_SESSION_CREATE_INFO};
  info.next = &graphics;
  info.systemId = system_;
  check(createSession_(instance_, &info, &session_), "create session");
  try {
    XrReferenceSpaceCreateInfo space{XR_TYPE_REFERENCE_SPACE_CREATE_INFO};
    space.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_LOCAL;
    space.poseInReferenceSpace.orientation.w = 1.0f;
    check(createSpace_(session_, &space, &space_), "create seated space");
    actions_.attach(session_);
  } catch (...) {
    actions_.closeSession();
    if (space_) destroySpace_(space_);
    space_ = XR_NULL_HANDLE;
    destroySession_(session_);
    session_ = XR_NULL_HANDLE;
    throw;
  }
}

void Runtime::requireSession() const {
  if (!session_) throw std::logic_error("OpenXR session has not been created");
}

void Runtime::pollEvents() {
  if (!initialized()) throw std::logic_error("OpenXR is not initialized");
  for (;;) {
    XrEventDataBuffer event{XR_TYPE_EVENT_DATA_BUFFER};
    const XrResult result = pollEvent_(instance_, &event);
    if (result == XR_EVENT_UNAVAILABLE) return;
    check(result, "poll events");
    if (event.type == XR_TYPE_EVENT_DATA_INSTANCE_LOSS_PENDING) {
      exitRequested_ = true; input_ = {}; actions_.reset();
      reportTracking(std::nullopt);
    }
    if (event.type == XR_TYPE_EVENT_DATA_INTERACTION_PROFILE_CHANGED &&
        reinterpret_cast<const XrEventDataInteractionProfileChanged&>(event).session == session_) {
      input_ = {}; actions_.reset();
    }
    if (event.type != XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED) continue;
    const auto& change = reinterpret_cast<const XrEventDataSessionStateChanged&>(event);
    if (change.session != session_) continue;
    state_ = change.state;
    if (!focused()) { input_ = {}; actions_.reset(); reportTracking(std::nullopt); }
    if (state_ == XR_SESSION_STATE_READY && !running_) {
      XrSessionBeginInfo begin{XR_TYPE_SESSION_BEGIN_INFO};
      begin.primaryViewConfigurationType = XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
      check(beginSession_(session_, &begin), "begin session");
      running_ = true;
    } else if (state_ == XR_SESSION_STATE_STOPPING && running_) {
      if (frameOpen_) endFrame(false);
      check(endSession_(session_), "end session");
      running_ = false;
    } else if (state_ == XR_SESSION_STATE_EXITING || state_ == XR_SESSION_STATE_LOSS_PENDING) {
      running_ = false;
      exitRequested_ = true;
    }
  }
}

bool Runtime::readyForFrame() {
  pollEvents();
  if (exitRequested_)
    throw std::runtime_error("GK3HD OpenXR session ended: runtime requested exit or session loss");
  return running_;
}

std::vector<int64_t> Runtime::formats() const {
  requireSession();
  uint32_t count = 0;
  check(enumerateFormats_(session_, 0, &count, nullptr), "swapchain formats");
  std::vector<int64_t> result(count);
  check(enumerateFormats_(session_, count, &count, result.data()), "swapchain formats");
  result.resize(count);
  return result;
}

bool Runtime::mutableEyeFormat(unsigned index) const {
  if (index >= eyes_.size()) throw std::out_of_range("invalid XR eye index");
  const auto& target = packedEyeTargets_ ? packed_ : eyes_[index];
  return target.chain && target.mutableFormat;
}

bool Runtime::directAttachment(unsigned index) const {
  if (index >= eyes_.size()) throw std::out_of_range("invalid XR eye index");
  const auto& target = packedEyeTargets_ ? packed_ : eyes_[index];
  return target.chain && target.directAttachment;
}

VkExtent2D Runtime::eyeStorageExtent(unsigned index) const {
  if (index >= eyes_.size()) throw std::out_of_range("invalid XR eye index");
  return (packedEyeTargets_ ? packed_ : eyes_[index]).storageExtent;
}

void Runtime::createSwapchains(int64_t format, bool preferMutable, bool preferPacked, bool preferDirect) {
  requireSession();
  const auto supported = formats();
  if (std::find(supported.begin(), supported.end(), format) == supported.end())
    throw std::invalid_argument("unsupported XR swapchain format");
  if (eyes_[0].chain || eyes_[1].chain || packed_.chain)
    throw std::logic_error("XR swapchains already created");
  if (preferPacked && configuration_[0].recommendedImageRectWidth == configuration_[1].recommendedImageRectWidth &&
      configuration_[0].recommendedImageRectHeight == configuration_[1].recommendedImageRectHeight &&
      configuration_[0].recommendedImageRectWidth <= uint32_t(INT32_MAX) / 2) {
    // Query only when packing was explicitly requested. Ordinary PC-VR keeps
    // its existing creation path. Never infer this limit from the HMD name.
    PFN_xrGetSystemProperties getSystemProperties = nullptr;
    load("xrGetSystemProperties", getSystemProperties);
    XrSystemProperties properties{XR_TYPE_SYSTEM_PROPERTIES};
    check(getSystemProperties(instance_, system_, &properties), "XR image limits");
    packedEyeTargets_ = configuration_[0].recommendedImageRectWidth * 2 <= properties.graphicsProperties.maxSwapchainImageWidth &&
      configuration_[0].recommendedImageRectHeight <= properties.graphicsProperties.maxSwapchainImageHeight;
  }
  try {
    if (packedEyeTargets_) {
      createTarget(packed_, format, configuration_[0].recommendedImageRectWidth * 2,
                   configuration_[0].recommendedImageRectHeight, preferMutable, preferDirect);
      if (packed_.directAttachment) {
        // Only the paired standalone runtime can report extra transport rows.
        PFN_xrVoidFunction address = nullptr;
        const auto result = resolve_(instance_, "xrGk3hdGetSwapchainStorageExtentV1", &address);
        if (result != XR_ERROR_FUNCTION_UNSUPPORTED) {
          check(result, "packed eye storage capability");
          if (!address) throw std::runtime_error("missing packed eye storage function");
          using StorageExtent = XrResult(XRAPI_PTR*)(XrSwapchain, XrExtent2Di*);
          XrExtent2Di extent{};
          check(reinterpret_cast<StorageExtent>(address)(packed_.chain, &extent), "packed eye storage extent");
          const auto width = static_cast<int32_t>(packed_.storageExtent.width);
          const auto height = static_cast<int32_t>(packed_.storageExtent.height);
          constexpr int32_t maximumTransportRows = 4;
          if (extent.width != width || extent.height < height || extent.height - height > maximumTransportRows)
            throw std::runtime_error("invalid packed eye storage extent");
          packed_.storageExtent.height = static_cast<uint32_t>(extent.height);
        }
      }
    } else {
      for (unsigned i = 0; i < 2; ++i)
        createTarget(eyes_[i], format, configuration_[i].recommendedImageRectWidth,
                     configuration_[i].recommendedImageRectHeight, preferMutable, preferDirect);
    }
  } catch (...) {
    for (auto& target : eyes_) {
      destroyTarget(target);
    }
    destroyTarget(packed_);
    packedEyeTargets_ = false;
    throw;
  }
}

void Runtime::createTarget(Eye& target, int64_t format, uint32_t width, uint32_t height,
                           bool preferMutable, bool preferDirect) {
  if (target.chain || !width || !height || width > uint32_t(INT32_MAX) || height > uint32_t(INT32_MAX))
    throw std::invalid_argument("invalid XR swapchain dimensions or existing target");
  try {
    XrSwapchainCreateInfo info{XR_TYPE_SWAPCHAIN_CREATE_INFO};
    info.usageFlags = XR_SWAPCHAIN_USAGE_COLOR_ATTACHMENT_BIT | XR_SWAPCHAIN_USAGE_TRANSFER_DST_BIT;
    info.format = format; info.sampleCount = 1;
    info.width = width; info.height = height;
    info.faceCount = info.arraySize = info.mipCount = 1;
    if (preferMutable) info.usageFlags |= XR_SWAPCHAIN_USAGE_MUTABLE_FORMAT_BIT;
    const bool directRequested = preferDirect && preferMutable;
    constexpr XrSwapchainUsageFlags readable = XR_SWAPCHAIN_USAGE_SAMPLED_BIT | XR_SWAPCHAIN_USAGE_TRANSFER_SRC_BIT;
    if (directRequested) info.usageFlags |= readable;
    auto result = createSwapchain_(session_, &info, &target.chain);
    if (directRequested && result == XR_ERROR_FEATURE_UNSUPPORTED) {
      target.chain = XR_NULL_HANDLE;
      info.usageFlags &= ~readable;
      result = createSwapchain_(session_, &info, &target.chain);
    }
    if (preferMutable && result == XR_ERROR_FEATURE_UNSUPPORTED) {
      // Only unsupported usage permits fallback. Never hide device/session
      // failure or allocation errors by retrying a different presentation path.
      target.chain = XR_NULL_HANDLE;
      info.usageFlags &= ~XR_SWAPCHAIN_USAGE_MUTABLE_FORMAT_BIT;
      result = createSwapchain_(session_, &info, &target.chain);
    }
    check(result, "create XR swapchain");
    target.storageExtent = {width, height};
    target.mutableFormat = (info.usageFlags & XR_SWAPCHAIN_USAGE_MUTABLE_FORMAT_BIT) != 0;
    target.directAttachment = directRequested && target.mutableFormat && (info.usageFlags & readable) == readable;
    uint32_t count = 0;
    check(enumerateImages_(target.chain, 0, &count, nullptr), "XR images");
    if (!count) throw std::runtime_error("XR swapchain has no images");
    target.images.assign(count, {XR_TYPE_SWAPCHAIN_IMAGE_VULKAN_KHR});
    const auto capacity = count;
    check(enumerateImages_(target.chain, capacity, &count,
          reinterpret_cast<XrSwapchainImageBaseHeader*>(target.images.data())), "XR images");
    if (count != capacity) throw std::runtime_error("XR image count changed during creation");
  } catch (...) { destroyTarget(target); throw; }
}
void Runtime::destroyTarget(Eye& target) noexcept {
  if (target.chain && destroySwapchain_) destroySwapchain_(target.chain);
  target = {};
}
void Runtime::createPanelSwapchain(int64_t format, uint32_t width, uint32_t height) {
  requireSession();
  const auto supported = formats();
  if (std::find(supported.begin(), supported.end(), format) == supported.end())
    throw std::invalid_argument("unsupported XR panel format");
  createTarget(panel_, format, width, height);
  panelExtent_ = {int32_t(width), int32_t(height)};
}
void Runtime::destroyPanelSwapchain() {
  if (panel_.acquired || (frameOpen_ && panel_.submitted))
    throw std::logic_error("cannot resize an active XR panel image");
  destroyTarget(panel_); panelExtent_ = {};
}
void Runtime::createKeyboardSwapchain(int64_t format, uint32_t width, uint32_t height) {
  requireSession();
  const auto supported = formats();
  if (std::find(supported.begin(), supported.end(), format) == supported.end())
    throw std::invalid_argument("unsupported XR keyboard format");
  createTarget(keyboard_, format, width, height);
  keyboardExtent_ = {int32_t(width), int32_t(height)};
}
void Runtime::destroyKeyboardSwapchain() {
  if (keyboard_.acquired || (frameOpen_ && keyboard_.submitted))
    throw std::logic_error("cannot resize an active XR keyboard image");
  destroyTarget(keyboard_); keyboardExtent_ = {};
}

Runtime::Eye& Runtime::eye(unsigned index) {
  if (index >= eyes_.size()) throw std::out_of_range("invalid XR eye");
  return eyes_[index];
}

const std::vector<XrSwapchainImageVulkanKHR>& Runtime::images(unsigned index) const {
  const auto& target = eyes_.at(index);
  return packedEyeTargets_ ? packed_.images : target.images;
}

void Runtime::createSubtitleSwapchain(int64_t format, uint32_t width, uint32_t height) {
  requireSession();
  const auto supported = formats();
  if (std::find(supported.begin(), supported.end(), format) == supported.end())
    throw std::invalid_argument("unsupported XR subtitle format");
  createTarget(subtitle_, format, width, height);
  subtitleExtent_ = {int32_t(width), int32_t(height)};
}
void Runtime::destroySubtitleSwapchain() {
  if (subtitle_.acquired || (frameOpen_ && subtitle_.submitted))
    throw std::logic_error("cannot resize an active XR subtitle image");
  destroyTarget(subtitle_); subtitleExtent_ = {};
}
void Runtime::createPointerSwapchain(int64_t format) {
  requireSession();
  const auto supported = formats();
  if (std::find(supported.begin(), supported.end(), format) == supported.end())
    throw std::invalid_argument("unsupported XR pointer format");
  createTarget(pointer_, format, 1, 1);
}
void Runtime::destroyPointerSwapchain() {
  if (pointer_.acquired || (frameOpen_ && pointer_.submitted))
    throw std::logic_error("cannot resize an active XR pointer image");
  destroyTarget(pointer_);
}
bool Runtime::beginFrame(const std::function<void()>& enterQueue,
                         const std::function<void()>& leaveQueue) {
  if (bool(enterQueue) != bool(leaveQueue))
    throw std::invalid_argument("XR queue callbacks must be balanced");
  struct QueueScope {
    const std::function<void()>& leave;
    QueueScope(const std::function<void()>& enter, const std::function<void()>& exit) : leave(exit) {
      if (enter) enter();
    }
    ~QueueScope() { if (leave) leave(); }
  };
  requireSession();
  if (!running_ || frameOpen_) throw std::logic_error("invalid XR frame begin");
  input_ = {};
  try {
    XrFrameWaitInfo wait{XR_TYPE_FRAME_WAIT_INFO};
    frame_ = {XR_TYPE_FRAME_STATE};
    check(waitFrame_(session_, &wait, &frame_), "wait frame");
    predictedTime_ = frame_.predictedDisplayTime;
    XrFrameBeginInfo begin{XR_TYPE_FRAME_BEGIN_INFO};
    XrResult started;
    if (cpuFrameBegin_) {
      started = beginFrame_(session_, &begin);
    } else {
      QueueScope queue(enterQueue, leaveQueue);
      started = beginFrame_(session_, &begin);
    }
    check(started, "begin frame");
    frameOpen_ = true;
    sharedProjection_ = false;
    viewsValid_ = false;
    for (auto& target : eyes_) target.submitted = false;
    packed_.submitted = false;
    panel_.submitted = false;
    keyboard_.submitted = false;
    subtitle_.submitted = false;
    pointer_.submitted = false;
    // XR_FRAME_DISCARDED describes the prior frame, not this newly begun one.
    input_ = actions_.sample(space_, frame_.predictedDisplayTime, focused() && frame_.shouldRender);
    if (!frame_.shouldRender) { reportTracking(std::nullopt); return false; }
    XrViewLocateInfo locate{XR_TYPE_VIEW_LOCATE_INFO};
    locate.viewConfigurationType = XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
    locate.displayTime = frame_.predictedDisplayTime;
    locate.space = space_;
    XrViewState state{XR_TYPE_VIEW_STATE};
    uint32_t count = 0;
    for (auto& view : views_) view = {XR_TYPE_VIEW};
    check(locateViews_(session_, &locate, &state, 2, &count, views_.data()), "locate eyes");
    const auto valid = XR_VIEW_STATE_ORIENTATION_VALID_BIT | XR_VIEW_STATE_POSITION_VALID_BIT;
    viewsValid_ = count == 2 && (state.viewStateFlags & valid) == valid;
    const auto tracked = XR_VIEW_STATE_ORIENTATION_TRACKED_BIT | XR_VIEW_STATE_POSITION_TRACKED_BIT;
    // A runtime can preserve a valid last-known pose through tracking loss.
    // Continue legal presentation, but never interact from that stale viewer
    // location. Reset latches so recovery requires release/neutral input.
    const bool headTracked = viewsValid_ && (state.viewStateFlags & tracked) == tracked;
    if (!headTracked) {
      input_ = {}; actions_.reset();
    }
    reportTracking(headTracked);
    return viewsValid_;
  } catch (...) {
    reportTracking(std::nullopt);
    input_ = {}; actions_.reset();
    if (frameOpen_) {
      QueueScope queue(enterQueue, leaveQueue);
      endFrame(false);
    }
    throw;
  }
}

uint32_t Runtime::acquireEye(unsigned index) {
  auto& target = eye(index);
  if (!packedEyeTargets_) return acquireTarget(target);
  if (!frameOpen_ || !viewsValid_ || target.acquired || target.submitted)
    throw std::logic_error("invalid packed XR eye acquisition");
  if (!packed_.acquired) packedIndex_ = acquireTarget(packed_);
  if (!packed_.waited) throw std::logic_error("packed XR image has not been waited");
  target.acquired = target.waited = true;
  target.releasedContent = false;
  return packedIndex_;
}
uint32_t Runtime::acquirePanel() { return acquireTarget(panel_); }
uint32_t Runtime::acquireTarget(Eye& target) {
  if (!frameOpen_ || !viewsValid_ || !target.chain || target.acquired || target.submitted)
    throw std::logic_error("invalid XR eye acquisition");
  XrSwapchainImageAcquireInfo acquire{XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO};
  uint32_t image = 0;
  check(acquireImage_(target.chain, &acquire, &image), "acquire eye");
  target.acquired = true;
  target.releasedContent = false;
  XrSwapchainImageWaitInfo wait{XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO};
  wait.timeout = XR_INFINITE_DURATION;
  const XrResult result = waitImage_(target.chain, &wait);
  check(result, "wait eye");
  if (result == XR_TIMEOUT_EXPIRED)
    throw std::runtime_error("XR image wait timed out without transferring ownership");
  target.waited = true;
  if (image >= target.images.size()) throw std::runtime_error("invalid XR swapchain image index");
  return image;
}

void Runtime::releaseEye(unsigned index) {
  auto& target = eye(index);
  if (!packedEyeTargets_) { releaseTarget(target); return; }
  if (!frameOpen_ || !target.acquired || !target.waited || !packed_.acquired || !packed_.waited)
    throw std::logic_error("packed XR eye must be acquired and waited before release");
  // Both eye writes use this physical image. Keep it acquired until the last
  // write is queued, even when the first logical eye has already completed.
  if (eyes_[1-index].submitted) releaseTarget(packed_);
  target.acquired = target.waited = false;
  target.submitted = target.releasedContent = true;
}
void Runtime::releasePanel() { releaseTarget(panel_); }
uint32_t Runtime::acquireKeyboard() { return acquireTarget(keyboard_); }
void Runtime::releaseKeyboard() { releaseTarget(keyboard_); }
uint32_t Runtime::acquireSubtitle() { return acquireTarget(subtitle_); }
void Runtime::releaseSubtitle() { releaseTarget(subtitle_); }
bool Runtime::reuseSubtitle() {
  if (!frameOpen_ || !viewsValid_ || !subtitle_.chain || subtitle_.acquired || subtitle_.submitted)
    throw std::logic_error("invalid unchanged XR subtitle composition");
  if (!subtitle_.releasedContent) return false;
  subtitle_.submitted = true;
  return true;
}
uint32_t Runtime::acquirePointer() { return acquireTarget(pointer_); }
void Runtime::releasePointer() { releaseTarget(pointer_); }
void Runtime::releaseTarget(Eye& target) {
  if (!frameOpen_ || !target.acquired || !target.waited)
    throw std::logic_error("XR eye must be acquired and waited before release");
  XrSwapchainImageReleaseInfo release{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};
  check(releaseImage_(target.chain, &release), "release eye");
  target.acquired = target.waited = false;
  target.submitted = true;
  target.releasedContent = true;
}

void Runtime::sharePackedProjection() {
  if (!packedEyeTargets_ || !frameOpen_ || !viewsValid_ || !eyes_[0].acquired || !eyes_[0].waited ||
      eyes_[1].acquired || eyes_[0].submitted || eyes_[1].submitted || sharedProjection_)
    throw std::logic_error("invalid shared packed projection ownership");
  sharedProjection_ = true;
  eyes_[1].submitted = true;
}

bool Runtime::endFrame(bool rendered, const PanelLayer* panel, const PanelLayer* keyboard,
                       const PanelLayer* subtitle, const PanelLayer* pointer) {
  if (!frameOpen_) throw std::logic_error("no XR frame to end");
  for (const auto& target : eyes_) {
    if (target.acquired) throw std::logic_error("release XR eye before ending frame");
    if (rendered && !target.submitted) throw std::logic_error("both XR eyes must be rendered");
  }
  if (panel_.acquired) throw std::logic_error("release XR panel before ending frame");
  if (keyboard_.acquired) throw std::logic_error("release XR keyboard before ending frame");
  if (subtitle_.acquired) throw std::logic_error("release XR subtitle before ending frame");
  if (pointer_.acquired) throw std::logic_error("release XR pointer before ending frame");
  if (panel && (!panel_.submitted || !panel_.chain)) throw std::logic_error("XR panel image was not written");
  if (keyboard && (!panel || !keyboard_.submitted || !keyboard_.chain))
    throw std::logic_error("XR keyboard requires a written image and editor panel");
  if (subtitle && ((!rendered && !panel) || !subtitle_.submitted || !subtitle_.chain || !subtitle->transparent))
    throw std::logic_error("XR subtitles require a written transparent image and world or native screen");
  if (pointer && (!panel || !pointer_.submitted || !pointer_.chain || !pointer->transparent))
    throw std::logic_error("XR pointer requires a written transparent image and interface panel");
  if ((rendered || panel) && (!viewsValid_ || !frame_.shouldRender))
    throw std::logic_error("cannot submit invalid XR views");
  for (const auto* target : {panel, keyboard, subtitle, pointer}) {
    if (!target) continue;
    const auto& p = target->pose.position;
    const auto& q = target->pose.orientation;
    const float norm = q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w;
    if (!std::isfinite(p.x) || !std::isfinite(p.y) || !std::isfinite(p.z) ||
        !std::isfinite(norm) || std::abs(norm-1.f) > .001f ||
        !std::isfinite(target->size.width) || !std::isfinite(target->size.height) ||
        target->size.width <= 0 || target->size.height <= 0)
      throw std::invalid_argument("invalid XR panel geometry");
  }
  if (packed_.acquired) {
    if (rendered) throw std::logic_error("packed XR image is not complete");
    // Cancelled partial frames publish no world projection, but still retire
    // their successfully waited physical lease before ending the frame.
    releaseTarget(packed_);
  }
  std::array<XrCompositionLayerProjectionView, 2> projection{};
  for (unsigned i = 0; i < 2; ++i) {
    projection[i] = {XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW};
    projection[i].pose = views_[i].pose;
    projection[i].fov = views_[i].fov;
    projection[i].subImage.swapchain = packedEyeTargets_ ? packed_.chain : eyes_[i].chain;
    if (packedEyeTargets_) projection[i].subImage.imageRect.offset.x =
      int32_t(i * configuration_[i].recommendedImageRectWidth);
    projection[i].subImage.imageRect.extent = {
      static_cast<int32_t>(configuration_[i].recommendedImageRectWidth),
      static_cast<int32_t>(configuration_[i].recommendedImageRectHeight)};
  }
  XrCompositionLayerProjection layer{XR_TYPE_COMPOSITION_LAYER_PROJECTION};
  layer.space = space_;
  layer.viewCount = 2;
  layer.views = projection.data();
  XrCompositionLayerQuad quad{XR_TYPE_COMPOSITION_LAYER_QUAD};
  quad.space = space_; quad.eyeVisibility = XR_EYE_VISIBILITY_BOTH;
  quad.subImage.swapchain = panel_.chain;
  quad.subImage.imageRect.extent = panelExtent_;
  if (panel) {
    quad.pose = panel->pose; quad.size = panel->size;
    if (panel->transparent) quad.layerFlags = XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT;
  }
  XrCompositionLayerQuad keys{XR_TYPE_COMPOSITION_LAYER_QUAD};
  keys.space = space_; keys.eyeVisibility = XR_EYE_VISIBILITY_BOTH;
  keys.subImage.swapchain = keyboard_.chain;
  keys.subImage.imageRect.extent = keyboardExtent_;
  if (keyboard) {
    keys.pose = keyboard->pose; keys.size = keyboard->size;
    if (keyboard->transparent) keys.layerFlags = XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT;
  }
  XrCompositionLayerQuad captions{XR_TYPE_COMPOSITION_LAYER_QUAD};
  captions.space = space_; captions.eyeVisibility = XR_EYE_VISIBILITY_BOTH;
  captions.subImage.swapchain = subtitle_.chain;
  captions.subImage.imageRect.extent = subtitleExtent_;
  captions.layerFlags = XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT;
  if (subtitle) { captions.pose = subtitle->pose; captions.size = subtitle->size; }
  XrCompositionLayerQuad aim{XR_TYPE_COMPOSITION_LAYER_QUAD};
  aim.space = space_; aim.eyeVisibility = XR_EYE_VISIBILITY_BOTH;
  aim.subImage.swapchain = pointer_.chain;
  aim.subImage.imageRect.extent = {1, 1};
  aim.layerFlags = XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT;
  if (pointer) { aim.pose = pointer->pose; aim.size = pointer->size; }
  std::array<const XrCompositionLayerBaseHeader*, 5> layers{};
  uint32_t count = 0;
  if (rendered) layers[count++] = reinterpret_cast<const XrCompositionLayerBaseHeader*>(&layer);
  if (panel) layers[count++] = reinterpret_cast<const XrCompositionLayerBaseHeader*>(&quad);
  if (keyboard) layers[count++] = reinterpret_cast<const XrCompositionLayerBaseHeader*>(&keys);
  if (subtitle) layers[count++] = reinterpret_cast<const XrCompositionLayerBaseHeader*>(&captions);
  if (pointer) layers[count++] = reinterpret_cast<const XrCompositionLayerBaseHeader*>(&aim);
  XrFrameEndInfo end{XR_TYPE_FRAME_END_INFO};
  end.displayTime = frame_.predictedDisplayTime;
  end.environmentBlendMode = XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
  end.layerCount = count;
  end.layers = count ? layers.data() : nullptr;
  const XrResult result = endFrame_(session_, &end);
  frameOpen_ = false;
  check(result, "end frame");
  return rendered && result == XR_SUCCESS;
}

void Runtime::closeSession() noexcept {
  // Teardown is also valid after runtime/session loss. Never throw in a destructor.
  if (frameOpen_ && session_) {
    XrFrameEndInfo end{XR_TYPE_FRAME_END_INFO};
    end.displayTime = frame_.predictedDisplayTime;
    end.environmentBlendMode = XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
    bool canEnd = true;
    for (auto* item : std::array<Eye*, 7>{&packed_, packedEyeTargets_ ? nullptr : &eyes_[0],
         packedEyeTargets_ ? nullptr : &eyes_[1], &panel_, &keyboard_, &subtitle_, &pointer_}) {
      if (!item) continue;
      auto& target = *item;
      // An acquired-but-not-waited image cannot legally be released. Attempt
      // a nonblocking wait on teardown, then abandon the session if it is not
      // available. Never hang shutdown or end a frame with an outstanding eye.
      if (target.acquired && !target.waited && waitImage_) {
        XrSwapchainImageWaitInfo wait{XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO};
        const XrResult result = waitImage_(target.chain, &wait);
        target.waited = XR_SUCCEEDED(result) && result != XR_TIMEOUT_EXPIRED;
      }
      if (target.acquired && target.waited && releaseImage_) {
        XrSwapchainImageReleaseInfo release{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};
        if (XR_SUCCEEDED(releaseImage_(target.chain, &release))) target.acquired = false;
      }
      canEnd = canEnd && !target.acquired;
    }
    if (canEnd && endFrame_) endFrame_(session_, &end);
  }
  for (auto& target : eyes_) {
    destroyTarget(target);
  }
  destroyTarget(packed_); packedIndex_ = 0;
  destroyTarget(panel_); panelExtent_ = {};
  destroyTarget(keyboard_); keyboardExtent_ = {};
  destroyTarget(subtitle_); subtitleExtent_ = {};
  destroyTarget(pointer_);
  actions_.closeSession();
  input_ = {};
  if (space_ && destroySpace_) destroySpace_(space_);
  if (session_ && destroySession_) destroySession_(session_);
  session_ = XR_NULL_HANDLE;
  space_ = XR_NULL_HANDLE;
  vkDevice_ = VK_NULL_HANDLE;
  running_ = exitRequested_ = frameOpen_ = viewsValid_ = false;
  packedEyeTargets_ = sharedProjection_ = false;
  reportTracking(std::nullopt);
  predictedTime_ = 0;
  state_ = XR_SESSION_STATE_UNKNOWN;
}

void Runtime::shutdown() noexcept {
  closeSession();
  actions_.shutdown();
  if (instance_ && destroyInstance_) destroyInstance_(instance_);
  instance_ = XR_NULL_HANDLE;
  system_ = XR_NULL_SYSTEM_ID;
  vkInstance_ = VK_NULL_HANDLE;
  vkPhysical_ = VK_NULL_HANDLE;
  name_.clear();
  cpuFrameBegin_ = false;
}

} // namespace gk3hd::vr
