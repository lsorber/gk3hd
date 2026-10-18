#include "runtime.h"
#include "camera.h"
#include "engine_camera.h"
#include "renderer_host.h"
#include "mirror_pacer.h"
#include "input_test_runtime.h"

#include <cstring>
#include <deque>
#include <functional>
#include <iostream>
#include <map>
#include <stdexcept>
#include <type_traits>

namespace {
template<typename T> T handle(uintptr_t value) {
  if constexpr (std::is_pointer_v<T>) return reinterpret_cast<T>(value);
  else return static_cast<T>(value);
}
void expect(bool value, const char* message) {
  if (!value) throw std::runtime_error(message);
}
void rejects(const std::function<void()>& operation) {
  try { operation(); } catch (const std::exception&) { return; }
  throw std::runtime_error("invalid operation was accepted");
}
struct Fixture {
  bool extensions = true;
  bool headset = true;
  bool validPose = true;
  XrViewStateFlags trackingFlags = XR_VIEW_STATE_ORIENTATION_TRACKED_BIT | XR_VIEW_STATE_POSITION_TRACKED_BIT;
  bool shouldRender = true;
  bool timeout = false;
  bool opaque = true;
  bool verifyQueue = false;
  bool queueHeld = false;
  bool failLocate = false;
  unsigned destroyed = 0;
  unsigned released = 0;
  unsigned ended = 0;
  unsigned layers = 0;
  unsigned chains = 0;
  unsigned panelLayers = 0;
  std::array<XrExtent2Di, 2> eyeExtents{{{1024, 1200}, {1024, 1200}}};
  std::vector<XrExtent2Di> projectionExtents;
  XrCompositionLayerFlags panelFlags = 0;
  bool failPanelImages = false;
  XrExtent2Di panelExtent{};
  std::vector<XrSwapchain> quadChains;
  std::vector<XrPosef> quadPoses;
  std::map<XrSwapchain, XrExtent2Di> extents;
  XrResult beginResult = XR_SUCCESS;
  XrResult waitResult = XR_SUCCESS;
  bool profileChanged = false;
  VkResult deviceResult = VK_SUCCESS;
  VkFormat eyeFormat = VK_FORMAT_R8G8B8A8_SRGB;
  std::deque<XrSessionState> events;
} fixture;

XrResult XRAPI_CALL extensions(const char*, uint32_t capacity, uint32_t* count,
                              XrExtensionProperties* output) {
  *count = fixture.extensions ? 1 : 0;
  if (capacity && fixture.extensions)
    std::strcpy(output[0].extensionName, XR_KHR_VULKAN_ENABLE2_EXTENSION_NAME);
  return XR_SUCCESS;
}
XrResult XRAPI_CALL createInstance(const XrInstanceCreateInfo* info, XrInstance* output) {
  expect(info->enabledExtensionCount == 1, "Vulkan extension not requested");
  *output = handle<XrInstance>(1);
  return XR_SUCCESS;
}
XrResult XRAPI_CALL destroyInstance(XrInstance) { ++fixture.destroyed; return XR_SUCCESS; }
XrResult XRAPI_CALL properties(XrInstance, XrInstanceProperties* output) {
  std::strcpy(output->runtimeName, "Test runtime");
  return XR_SUCCESS;
}
XrResult XRAPI_CALL getSystem(XrInstance, const XrSystemGetInfo*, XrSystemId* output) {
  *output = 1;
  return fixture.headset ? XR_SUCCESS : XR_ERROR_FORM_FACTOR_UNAVAILABLE;
}
XrResult XRAPI_CALL configuration(XrInstance, XrSystemId, XrViewConfigurationType,
                                 uint32_t capacity, uint32_t* count, XrViewConfigurationView* output) {
  *count = 2;
  for (unsigned i = 0; i < capacity; ++i) {
    output[i].recommendedImageRectWidth = uint32_t(fixture.eyeExtents[i].width);
    output[i].recommendedImageRectHeight = uint32_t(fixture.eyeExtents[i].height);
    output[i].maxImageRectWidth = output[i].maxImageRectHeight = 8192;
    output[i].recommendedSwapchainSampleCount = 1;
  }
  return XR_SUCCESS;
}
XrResult XRAPI_CALL requirements(XrInstance, XrSystemId, XrGraphicsRequirementsVulkanKHR* output) {
  output->minApiVersionSupported = XR_MAKE_VERSION(1, 0, 0);
  output->maxApiVersionSupported = XR_MAKE_VERSION(1, 3, 0);
  return XR_SUCCESS;
}
XrResult XRAPI_CALL blendModes(XrInstance, XrSystemId, XrViewConfigurationType,
                              uint32_t capacity, uint32_t* count, XrEnvironmentBlendMode* output) {
  *count = 1;
  if (capacity) *output = fixture.opaque ? XR_ENVIRONMENT_BLEND_MODE_OPAQUE
                                       : XR_ENVIRONMENT_BLEND_MODE_ADDITIVE;
  return XR_SUCCESS;
}
XrResult XRAPI_CALL createVkInstance(XrInstance, const XrVulkanInstanceCreateInfoKHR*,
                                    VkInstance* output, VkResult* result) {
  *output = handle<VkInstance>(1); *result = VK_SUCCESS; return XR_SUCCESS;
}
XrResult XRAPI_CALL getVkDevice(XrInstance, const XrVulkanGraphicsDeviceGetInfoKHR*, VkPhysicalDevice* output) {
  *output = handle<VkPhysicalDevice>(2); return XR_SUCCESS;
}
XrResult XRAPI_CALL createVkDevice(XrInstance, const XrVulkanDeviceCreateInfoKHR*,
                                  VkDevice* output, VkResult* result) {
  *output = handle<VkDevice>(3); *result = fixture.deviceResult; return XR_SUCCESS;
}
XrResult XRAPI_CALL createSession(XrInstance, const XrSessionCreateInfo*, XrSession* output) {
  *output = handle<XrSession>(4); return XR_SUCCESS;
}
XrResult XRAPI_CALL destroySession(XrSession value) {
  gk3hd::vr::testinput::detachSession(value); return XR_SUCCESS;
}
XrResult XRAPI_CALL createSpace(XrSession, const XrReferenceSpaceCreateInfo* info, XrSpace* output) {
  expect(info->referenceSpaceType == XR_REFERENCE_SPACE_TYPE_LOCAL, "seated space is not LOCAL");
  expect(info->poseInReferenceSpace.orientation.w == 1, "reference orientation is not identity");
  *output = handle<XrSpace>(5); return XR_SUCCESS;
}
XrResult XRAPI_CALL destroySpace(XrSpace value) {
  if (gk3hd::vr::testinput::ownsSpace(value)) return gk3hd::vr::testinput::destroySpace(value);
  return XR_SUCCESS;
}
XrResult XRAPI_CALL poll(XrInstance, XrEventDataBuffer* output) {
  if (fixture.profileChanged) {
    fixture.profileChanged = false;
    XrEventDataInteractionProfileChanged event{XR_TYPE_EVENT_DATA_INTERACTION_PROFILE_CHANGED};
    event.session = handle<XrSession>(4);
    std::memcpy(output, &event, sizeof(event)); return XR_SUCCESS;
  }
  if (fixture.events.empty()) return XR_EVENT_UNAVAILABLE;
  XrEventDataSessionStateChanged change{XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED};
  change.session = handle<XrSession>(4);
  change.state = fixture.events.front(); fixture.events.pop_front();
  std::memcpy(output, &change, sizeof(change)); return XR_SUCCESS;
}
XrResult XRAPI_CALL beginSession(XrSession, const XrSessionBeginInfo*) { return XR_SUCCESS; }
XrResult XRAPI_CALL endSession(XrSession) { return XR_SUCCESS; }
XrResult XRAPI_CALL formats(XrSession, uint32_t capacity, uint32_t* count, int64_t* output) {
  *count = 1;
  if (capacity) *output = fixture.eyeFormat;
  return XR_SUCCESS;
}
XrResult XRAPI_CALL createChain(XrSession, const XrSwapchainCreateInfo* info, XrSwapchain* output) {
  expect(info->width && info->height, "empty XR target dimensions");
  *output = handle<XrSwapchain>(10 + fixture.chains++);
  fixture.extents[*output] = {int32_t(info->width), int32_t(info->height)};
  return XR_SUCCESS;
}
XrResult XRAPI_CALL destroyChain(XrSwapchain value) { fixture.extents.erase(value); return XR_SUCCESS; }
XrResult XRAPI_CALL images(XrSwapchain value, uint32_t capacity, uint32_t* count, XrSwapchainImageBaseHeader* output) {
  if (fixture.failPanelImages && fixture.extents.at(value).height != 1200) return XR_ERROR_RUNTIME_FAILURE;
  *count = 2;
  if (capacity) {
    auto* typed = reinterpret_cast<XrSwapchainImageVulkanKHR*>(output);
    typed[0].image = handle<VkImage>(100); typed[1].image = handle<VkImage>(101);
  }
  return XR_SUCCESS;
}
XrResult XRAPI_CALL waitFrame(XrSession, const XrFrameWaitInfo*, XrFrameState* output) {
  expect(!fixture.verifyQueue || !fixture.queueHeld, "frame wait blocked the graphics queue");
  if (fixture.waitResult != XR_SUCCESS) return fixture.waitResult;
  output->predictedDisplayTime = 123456;
  output->shouldRender = fixture.shouldRender; return XR_SUCCESS;
}
XrResult XRAPI_CALL beginFrame(XrSession, const XrFrameBeginInfo*) {
  expect(!fixture.verifyQueue || fixture.queueHeld, "frame begin accessed an unprotected queue");
  return fixture.beginResult;
}
XrResult XRAPI_CALL locate(XrSession, const XrViewLocateInfo* info, XrViewState* state,
                          uint32_t, uint32_t* count, XrView* output) {
  expect(!fixture.verifyQueue || !fixture.queueHeld, "view sampling retained the graphics queue");
  if (fixture.failLocate) return XR_ERROR_RUNTIME_FAILURE;
  expect(info->displayTime == 123456, "views not located at predicted display time");
  *count = 2;
  state->viewStateFlags = fixture.validPose ?
    XR_VIEW_STATE_POSITION_VALID_BIT | XR_VIEW_STATE_ORIENTATION_VALID_BIT | fixture.trackingFlags : 0;
  for (unsigned i = 0; i < 2; ++i) {
    output[i].pose.orientation.w = 1;
    output[i].pose.position.x = i == 0 ? -0.032f : 0.032f;
    output[i].fov = {-0.8f, 0.8f, 0.7f, -0.7f};
  }
  return XR_SUCCESS;
}
XrResult XRAPI_CALL acquire(XrSwapchain, const XrSwapchainImageAcquireInfo*, uint32_t* index) {
  *index = 1; return XR_SUCCESS;
}
XrResult XRAPI_CALL wait(XrSwapchain, const XrSwapchainImageWaitInfo*) {
  return fixture.timeout ? XR_TIMEOUT_EXPIRED : XR_SUCCESS;
}
XrResult XRAPI_CALL release(XrSwapchain, const XrSwapchainImageReleaseInfo*) {
  ++fixture.released; return XR_SUCCESS;
}
XrResult XRAPI_CALL endFrame(XrSession, const XrFrameEndInfo* info) {
  expect(!fixture.verifyQueue || fixture.queueHeld, "frame end accessed an unprotected queue");
  ++fixture.ended; fixture.layers = info->layerCount;
  fixture.panelLayers = 0;
  fixture.quadChains.clear(); fixture.quadPoses.clear();
  fixture.projectionExtents.clear();
  for (uint32_t i = 0; i < info->layerCount; ++i) {
    const auto* base = info->layers[i];
    if (base->type == XR_TYPE_COMPOSITION_LAYER_PROJECTION) {
      const auto* layer = reinterpret_cast<const XrCompositionLayerProjection*>(base);
      expect(i == 0 && layer->viewCount == 2, "not a background stereo projection layer");
      expect(layer->views[0].pose.position.x != layer->views[1].pose.position.x, "eye poses collapsed");
      expect(layer->views[0].subImage.swapchain != layer->views[1].subImage.swapchain, "eyes share target");
      for (const auto& view : std::array{layer->views[0], layer->views[1]}) {
        const auto extent = fixture.extents.at(view.subImage.swapchain);
        expect(view.subImage.imageRect.extent.width == extent.width &&
               view.subImage.imageRect.extent.height == extent.height,
               "projection does not cover its recommended eye target");
        fixture.projectionExtents.push_back(extent);
      }
    } else if (base->type == XR_TYPE_COMPOSITION_LAYER_QUAD) {
      const auto* quad = reinterpret_cast<const XrCompositionLayerQuad*>(base);
      expect(quad->eyeVisibility == XR_EYE_VISIBILITY_BOTH && quad->space == handle<XrSpace>(5) &&
             !(quad->layerFlags & ~XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT) &&
             !quad->subImage.imageArrayIndex, "wrong panel configuration");
      fixture.panelFlags = quad->layerFlags;
      const auto extent = fixture.extents.at(quad->subImage.swapchain);
      expect(quad->subImage.imageRect.extent.width == extent.width &&
             quad->subImage.imageRect.extent.height == extent.height, "panel canvas was cropped/stretched");
      fixture.panelExtent = extent;
      fixture.quadChains.push_back(quad->subImage.swapchain);
      fixture.quadPoses.push_back(quad->pose);
      ++fixture.panelLayers;
    } else throw std::runtime_error("unexpected XR layer");
  }
  return XR_SUCCESS;
}

XrResult XRAPI_CALL resolve(XrInstance, const char* name, PFN_xrVoidFunction* output) {
#define BIND(api, implementation) if (!std::strcmp(name, #api)) { \
  *output = reinterpret_cast<PFN_xrVoidFunction>(static_cast<PFN_##api>(implementation)); return XR_SUCCESS; }
  BIND(xrEnumerateInstanceExtensionProperties, extensions)
  BIND(xrCreateInstance, createInstance)
  BIND(xrDestroyInstance, destroyInstance)
  BIND(xrGetInstanceProperties, properties)
  BIND(xrGetSystem, getSystem)
  BIND(xrEnumerateViewConfigurationViews, configuration)
  BIND(xrEnumerateEnvironmentBlendModes, blendModes)
  BIND(xrGetVulkanGraphicsRequirements2KHR, requirements)
  BIND(xrCreateVulkanInstanceKHR, createVkInstance)
  BIND(xrGetVulkanGraphicsDevice2KHR, getVkDevice)
  BIND(xrCreateVulkanDeviceKHR, createVkDevice)
  BIND(xrCreateSession, createSession)
  BIND(xrDestroySession, destroySession)
  BIND(xrCreateReferenceSpace, createSpace)
  BIND(xrDestroySpace, destroySpace)
  BIND(xrPollEvent, poll)
  BIND(xrBeginSession, beginSession)
  BIND(xrEndSession, endSession)
  BIND(xrEnumerateSwapchainFormats, formats)
  BIND(xrCreateSwapchain, createChain)
  BIND(xrDestroySwapchain, destroyChain)
  BIND(xrEnumerateSwapchainImages, images)
  BIND(xrWaitFrame, waitFrame)
  BIND(xrBeginFrame, beginFrame)
  BIND(xrLocateViews, locate)
  BIND(xrAcquireSwapchainImage, acquire)
  BIND(xrWaitSwapchainImage, wait)
  BIND(xrReleaseSwapchainImage, release)
  BIND(xrEndFrame, endFrame)
#undef BIND
  return gk3hd::vr::testinput::resolve(XR_NULL_HANDLE, name, output);
}

void prepare(gk3hd::vr::Runtime& runtime) {
  runtime.initialize();
  VkInstanceCreateInfo instance{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
  const PFN_vkGetInstanceProcAddr vulkan = [](VkInstance, const char*) -> PFN_vkVoidFunction {
    return nullptr;
  };
  runtime.createVulkanInstance(vulkan, instance);
  runtime.graphicsDevice(handle<VkInstance>(1));
  VkDeviceCreateInfo device{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
  runtime.createVulkanDevice(vulkan, device);
  XrGraphicsBindingVulkanKHR graphics{XR_TYPE_GRAPHICS_BINDING_VULKAN_KHR};
  graphics.instance = handle<VkInstance>(1);
  graphics.physicalDevice = handle<VkPhysicalDevice>(2);
  graphics.device = handle<VkDevice>(3);
  runtime.createSession(graphics);
  runtime.createSwapchains(VK_FORMAT_R8G8B8A8_SRGB);
  fixture.events = {XR_SESSION_STATE_READY, XR_SESSION_STATE_FOCUSED};
  runtime.pollEvents();
}

void lifecycle() {
  fixture = {};
  {
    gk3hd::vr::Runtime runtime(resolve);
    prepare(runtime);
    expect(runtime.focused() && runtime.running(), "session did not start");
    rejects([&] { runtime.initialize(); });
    rejects([&] { runtime.acquireEye(0); });
    expect(runtime.beginFrame(), "valid frame was skipped");
    rejects([&] { runtime.beginFrame(); });
    rejects([&] { runtime.endFrame(true); });
    for (unsigned eye = 0; eye < 2; ++eye) {
      expect(runtime.acquireEye(eye) == 1, "incorrect acquired image");
      rejects([&] { runtime.acquireEye(eye); });
      rejects([&] { runtime.endFrame(false); });
      runtime.releaseEye(eye);
      rejects([&] { runtime.releaseEye(eye); });
    }
    runtime.endFrame(true);
    expect(fixture.layers == 1 && fixture.released == 2, "stereo layer was not submitted");
    fixture.shouldRender = false;
    expect(!runtime.beginFrame(), "hidden frame rendered");
    runtime.endFrame(false);
    expect(fixture.layers == 0, "hidden frame has layers");
    fixture.shouldRender = true;
    fixture.validPose = false;
    expect(!runtime.beginFrame(), "invalid tracked pose rendered");
    runtime.endFrame(false);
    fixture.validPose = true;
    fixture.beginResult = XR_FRAME_DISCARDED;
    expect(runtime.beginFrame(), "discarded previous frame skipped the current frame");
    runtime.endFrame(false);
    fixture.events = {XR_SESSION_STATE_STOPPING};
    runtime.pollEvents();
    expect(!runtime.running(), "stopping session remains active");
  }
  expect(fixture.destroyed == 1, "instance cleanup was not exactly once");
}
void frameQueueOwnership() {
  for (unsigned mode = 0; mode < 6; ++mode) {
    fixture = {};
    gk3hd::vr::Runtime runtime(resolve);
    prepare(runtime);
    fixture.verifyQueue = true;
    fixture.shouldRender = mode != 1;
    fixture.validPose = mode != 2;
    if (mode == 3) fixture.beginResult = XR_ERROR_RUNTIME_FAILURE;
    if (mode == 4) fixture.waitResult = XR_ERROR_RUNTIME_FAILURE;
    fixture.failLocate = mode == 5;
    unsigned entered = 0, left = 0;
    const auto enter = [&] {
      expect(!fixture.queueHeld, "recursive queue acquisition");
      fixture.queueHeld = true; ++entered;
    };
    const auto leave = [&] {
      expect(fixture.queueHeld, "unbalanced queue release");
      fixture.queueHeld = false; ++left;
    };
    rejects([&] { runtime.beginFrame(enter, {}); });
    rejects([&] { runtime.beginFrame({}, leave); });
    expect(!entered && !left, "invalid callbacks touched the queue");
    if (mode >= 3) {
      rejects([&] { runtime.beginFrame(enter, leave); });
      expect(fixture.ended == (mode == 5 ? 1u : 0u), "failed frame had wrong cleanup");
    } else {
      expect(runtime.beginFrame(enter, leave) == (mode == 0), "visible/hidden frame changed");
      expect(entered == 1 && left == 1 && !fixture.queueHeld,
             "frame begin did not release its queue");
      enter(); runtime.endFrame(false); leave();
      expect(fixture.ended == 1 && !fixture.layers, "empty frame did not retire");
    }
    expect(entered == left && !fixture.queueHeld, "frame failure leaked queue ownership");
  }
}

void terminalSessionLoss() {
  for (const auto state : {XR_SESSION_STATE_EXITING, XR_SESSION_STATE_LOSS_PENDING}) {
    fixture = {};
    {
      gk3hd::vr::Runtime runtime(resolve);
      prepare(runtime);
      expect(runtime.readyForFrame(), "focused session was not ready");
      fixture.events = {XR_SESSION_STATE_STOPPING};
      expect(!runtime.readyForFrame(), "stopping session still draws");
      fixture.events = {XR_SESSION_STATE_READY, XR_SESSION_STATE_FOCUSED};
      expect(runtime.readyForFrame(), "temporarily stopped session cannot resume");
      fixture.events = {state};
      try {
        runtime.readyForFrame();
        throw std::logic_error("terminal session silently skipped instead of failing");
      } catch (const std::runtime_error& error) {
        expect(std::string(error.what()).find("GK3HD OpenXR session ended:") == 0,
               "terminal session has no supervised failure message");
      }
    }
    expect(fixture.destroyed == 1 && fixture.extents.empty(), "lost session leaked targets");
  }
  for (const auto result : {XR_ERROR_SESSION_LOST, XR_ERROR_INSTANCE_LOST, XR_SESSION_LOSS_PENDING}) {
    fixture = {};
    gk3hd::vr::Runtime runtime(resolve);
    prepare(runtime);
    fixture.waitResult = result;
    try {
      runtime.beginFrame();
      throw std::logic_error("lost wait result was treated as usable tracking");
    } catch (const std::runtime_error& error) {
      expect(std::string(error.what()).find("GK3HD OpenXR session ended:") == 0,
             "lost frame wait has no supervised failure message");
    }
    expect(fixture.ended == 0, "lost wait opened a renderable frame");
  }
}

void recommendedEyeDimensions() {
  const std::array<std::array<XrExtent2Di, 2>, 2> cases{{
    {{{2016, 2240}, {2064, 2288}}}, {{{4316, 4316}, {4316, 4316}}}
  }};
  for (const auto& dimensions : cases) {
    fixture = {};
    fixture.eyeExtents = dimensions;
    {
      gk3hd::vr::Runtime runtime(resolve);
      prepare(runtime);
      expect(runtime.beginFrame(), "recommended-size frame did not begin");
      for (unsigned eye = 0; eye < 2; ++eye) {
        runtime.acquireEye(eye);
        runtime.releaseEye(eye);
      }
      runtime.endFrame(true);
      expect(fixture.projectionExtents.size() == 2, "recommended eye projections missing");
      for (unsigned eye = 0; eye < 2; ++eye)
        expect(fixture.projectionExtents[eye].width == dimensions[eye].width &&
               fixture.projectionExtents[eye].height == dimensions[eye].height,
               "eye target used desktop, maximum or other-eye dimensions");
    }
    expect(fixture.extents.empty(), "recommended eye targets leaked on shutdown");
  }
  for (const auto invalid : {XrExtent2Di{0, 2240}, XrExtent2Di{2016, 0},
                             XrExtent2Di{-1, 2240}}) {
    fixture = {};
    fixture.eyeExtents[1] = invalid;
    { gk3hd::vr::Runtime runtime(resolve); rejects([&] { runtime.initialize(); }); }
    expect(fixture.destroyed == 1 && fixture.extents.empty(),
           "invalid recommended eye dimensions retained runtime resources");
  }
}
void failures() {
  fixture = {};
  fixture.extensions = false;
  { gk3hd::vr::Runtime runtime(resolve); rejects([&] { runtime.initialize(); }); }
  expect(fixture.destroyed == 0, "destroyed nonexistent instance");
  fixture = {};
  fixture.headset = false;
  {
    gk3hd::vr::Runtime runtime(resolve);
    rejects([&] { runtime.initialize(); });
    expect(!runtime.initialized(), "partial initialization remains active");
    fixture.headset = true;
    runtime.initialize();
  }
  expect(fixture.destroyed == 2, "failed initialization or retry leaked");
  fixture = {};
  {
    gk3hd::vr::Runtime runtime(resolve);
    prepare(runtime);
    runtime.beginFrame();
    fixture.timeout = true;
    rejects([&] { runtime.acquireEye(0); });
    rejects([&] { runtime.releaseEye(0); });
  }
  expect(fixture.released == 0 && fixture.ended == 0,
         "timed-out image was released or its frame incorrectly ended");
  fixture = {};
  {
    gk3hd::vr::Runtime runtime(resolve);
    prepare(runtime);
    runtime.beginFrame();
    fixture.timeout = true;
    rejects([&] { runtime.acquireEye(0); });
    fixture.timeout = false;
  }
  expect(fixture.released == 1 && fixture.ended == 1,
         "available abandoned image did not unwind through wait and release");
  fixture = {};
  fixture.opaque = false;
  { gk3hd::vr::Runtime runtime(resolve); rejects([&] { runtime.initialize(); }); }
  expect(fixture.destroyed == 1, "unsupported presentation mode leaked its instance");
  fixture = {};
  {
    gk3hd::vr::Runtime runtime(resolve);
    prepare(runtime);
    runtime.beginFrame();
    runtime.acquireEye(0);
  }
  expect(fixture.released == 1 && fixture.layers == 0, "abandoned frame did not unwind");
}

void rendererIntegration() {
  fixture = {};
  {
    gk3hd::vr::RendererHost host(resolve);
    const PFN_vkGetInstanceProcAddr vulkan = [](VkInstance, const char*) -> PFN_vkVoidFunction {
      return nullptr;
    };
    VkInstanceCreateInfo instanceInfo{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    const auto instance = host.createInstance(vulkan, instanceInfo);
    const auto physical = host.selectDevice(instance);
    VkDeviceCreateInfo deviceInfo{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
    rejects([&] { host.createDevice(vulkan, handle<VkPhysicalDevice>(9), deviceInfo); });
    fixture.deviceResult = VK_ERROR_INITIALIZATION_FAILED;
    rejects([&] { host.createDevice(vulkan, physical, deviceInfo); });
    fixture.deviceResult = VK_SUCCESS;
    const auto device = host.createDevice(vulkan, physical, deviceInfo);
    XrGraphicsBindingVulkanKHR graphics{XR_TYPE_GRAPHICS_BINDING_VULKAN_KHR};
    graphics.instance = instance;
    graphics.physicalDevice = physical;
    graphics.device = device;
    host.start(graphics);
    expect(host.format() == VK_FORMAT_R8G8B8A8_SRGB && host.runtime().images(0).size() == 2 &&
           host.runtime().images(1).size() == 2, "renderer did not receive two eye image sets");
    host.stopDevice();
    expect(host.runtime().initialized() && host.runtime().images(0).empty(),
           "device teardown discarded the instance or retained dead eye images");
    graphics.device = host.createDevice(vulkan, physical, deviceInfo);
    host.start(graphics);
    fixture.events = {XR_SESSION_STATE_READY, XR_SESSION_STATE_FOCUSED};
    host.runtime().pollEvents();
    expect(host.runtime().beginFrame(), "recreated renderer session cannot begin a frame");
    host.runtime().endFrame(false);
    host.stopDevice();
    fixture.eyeFormat = VK_FORMAT_B8G8R8A8_SRGB;
    graphics.device = host.createDevice(vulkan, physical, deviceInfo);
    host.start(graphics);
    expect(host.format() == VK_FORMAT_B8G8R8A8_SRGB, "supported BGRA runtime rejected");
    host.stopDevice();
    fixture.eyeFormat = VK_FORMAT_R8G8B8A8_UNORM;
    graphics.device = host.createDevice(vulkan, physical, deviceInfo);
    rejects([&] { host.start(graphics); });
    expect(host.format() == VK_FORMAT_UNDEFINED, "linear-only format accepted without color conversion");
    host.stopDevice();
  }
  expect(fixture.destroyed == 1, "renderer device recreation leaked or replaced its XR instance");
}
void inputIntegration() {
  namespace input = gk3hd::vr::testinput;
  fixture = {}; input::model = {};
  {
    std::vector<std::optional<bool>> tracking;
    gk3hd::vr::Runtime runtime(resolve, [&](std::optional<bool> tracked) { tracking.push_back(tracked); });
    prepare(runtime);
    input::model.hands[0].active = true;
    expect(runtime.beginFrame(), "input baseline frame skipped");
    expect(tracking == std::vector<std::optional<bool>>{true}, "tracked headset was not reported");
    expect(runtime.input().hands[0].flags == gk3hd::vr::AimValid &&
           input::model.locatedTime == 123456, "runtime did not sample predicted input");
    runtime.endFrame(false);
    input::model.hands[0].buttons = gk3hd::vr::Select;
    runtime.beginFrame();
    expect(runtime.input().hands[0].pressed == gk3hd::vr::Select, "runtime lost selection edge");
    expect(tracking.size() == 1, "unchanged tracking spammed feedback");
    runtime.endFrame(false);
    fixture.profileChanged = true; runtime.pollEvents();
    expect(!runtime.input().flags, "profile change left stale input visible");
    runtime.beginFrame();
    expect(!runtime.input().hands[0].held, "profile change activated held selection");
    runtime.endFrame(false);
    fixture.events = {XR_SESSION_STATE_VISIBLE}; runtime.pollEvents();
    expect(!runtime.input().flags, "focus loss left stale input visible");
    runtime.beginFrame();
    expect(!runtime.input().flags, "unfocused frame exposes controls");
    runtime.endFrame(false);
    fixture.events = {XR_SESSION_STATE_FOCUSED}; runtime.pollEvents();
    runtime.beginFrame();
    expect(!runtime.input().hands[0].held, "focus recovery pressed held selection");
    runtime.endFrame(false);
    input::model.fail = "boolean";
    const auto ended = fixture.ended;
    rejects([&] { runtime.beginFrame(); });
    expect(!runtime.input().flags && fixture.ended == ended + 1 && !fixture.layers,
           "input failure leaked a frame or snapshot");
    input::model.fail.clear();
    runtime.beginFrame(); runtime.endFrame(false);
    expect(tracking.back() == true, "input recovery did not restore known tracking");
    for (const bool waitFailure : {true, false}) {
      fixture.waitResult = waitFailure ? XR_ERROR_RUNTIME_FAILURE : XR_SUCCESS;
      fixture.beginResult = waitFailure ? XR_SUCCESS : XR_ERROR_RUNTIME_FAILURE;
      const auto framesEnded = fixture.ended;
      rejects([&] { runtime.beginFrame(); });
      expect(!runtime.input().flags && framesEnded == fixture.ended,
             "failed frame begin exposes input or ends a nonexistent frame");
      fixture.waitResult = fixture.beginResult = XR_SUCCESS;
      runtime.beginFrame();
      expect(!runtime.input().hands[0].held, "failed frame recovery activates held selection");
      runtime.endFrame(false);
    }
    fixture.validPose = false;
    expect(!runtime.beginFrame() && !runtime.input().flags, "head tracking loss exposes controller input");
    expect(tracking.back() == false, "tracking loss was not reported");
    runtime.endFrame(false);
    fixture.validPose = true;
    for (const XrViewStateFlags remaining : {XrViewStateFlags(0),
        XrViewStateFlags(XR_VIEW_STATE_ORIENTATION_TRACKED_BIT),
        XrViewStateFlags(XR_VIEW_STATE_POSITION_TRACKED_BIT)}) {
      fixture.trackingFlags = remaining;
      // A valid last-known pose is still renderable, but it must not permit
      // world actions, keyboard entry, shortcuts or camera navigation.
      expect(runtime.beginFrame() && !runtime.input().flags,
             "valid but untracked head pose exposes controller interaction");
      expect(tracking.back() == false, "partial tracking was reported as recovered");
      for (unsigned eye = 0; eye < 2; ++eye) {
        runtime.acquireEye(eye); runtime.releaseEye(eye);
      }
      runtime.endFrame(true);
      expect(fixture.layers == 1, "last-known head pose lost legal stereo presentation");
      input::model.hands[0].buttons = gk3hd::vr::Select | gk3hd::vr::Inventory;
      input::model.hands[0].stick = {.8f, 0};
      fixture.trackingFlags = XR_VIEW_STATE_ORIENTATION_TRACKED_BIT | XR_VIEW_STATE_POSITION_TRACKED_BIT;
      expect(runtime.beginFrame() && runtime.input().flags &&
             !runtime.input().hands[0].held && !runtime.input().hands[0].pressed &&
             !runtime.input().hands[0].stick[0], "tracking recovery replayed held controls");
      expect(tracking.back() == true, "full tracking recovery was not reported");
      runtime.endFrame(false);
      input::model.hands[0].buttons = 0; input::model.hands[0].stick = {};
      runtime.beginFrame(); runtime.endFrame(false);
      input::model.hands[0].buttons = gk3hd::vr::Select | gk3hd::vr::Inventory;
      input::model.hands[0].stick = {.8f, 0};
      runtime.beginFrame();
      expect(runtime.input().hands[0].pressed == (gk3hd::vr::Select | gk3hd::vr::Inventory) &&
             runtime.input().hands[0].stick[0] == .8f, "fresh controls did not rearm after tracking recovery");
      runtime.endFrame(false);
    }
    fixture.events = {XR_SESSION_STATE_STOPPING};
    expect(!runtime.readyForFrame() && !tracking.back().has_value(),
           "stopped session retained a stale tracking observation");
    fixture.events = {XR_SESSION_STATE_READY, XR_SESSION_STATE_FOCUSED};
    expect(runtime.readyForFrame() && runtime.beginFrame(), "temporary stop did not resume");
    expect(tracking.back() == true, "resumed session lost tracking feedback");
    runtime.endFrame(false);
    fixture.validPose = true; fixture.shouldRender = false;
    const auto notices = tracking.size();
    expect(!runtime.beginFrame() && !runtime.input().flags, "hidden frame exposes controller input");
    expect(tracking.size() == notices + 1 && !tracking.back().has_value(),
           "hidden runtime retained stale tracking or diagnosed tracking failure");
    runtime.endFrame(false);
    runtime.shutdown();
    fixture.shouldRender = true;
    prepare(runtime);
    runtime.beginFrame(); runtime.endFrame(false);
    expect(tracking.size() == notices + 2 && tracking.back() == true, "new session reused stale tracking notice");
  }
  expect(input::model.sets.empty() && input::model.spaces.empty() && input::model.sessions.empty(),
         "runtime input cleanup leaked handles");
  fixture = {}; input::model = {};
  {
    gk3hd::vr::Runtime runtime(resolve, [](std::optional<bool>) { throw std::runtime_error("status sink unavailable"); });
    prepare(runtime);
    expect(runtime.beginFrame(), "diagnostic failure interrupted legal presentation");
    runtime.endFrame(false);
    fixture.trackingFlags = 0;
    expect(runtime.beginFrame() && !runtime.input().flags,
           "diagnostic failure bypassed the head-tracking input safeguard");
    runtime.endFrame(false);
  }
  fixture = {}; input::model = {}; input::model.failSpaceAt = 2;
  {
    gk3hd::vr::Runtime runtime(resolve);
    rejects([&] { prepare(runtime); });
    expect(input::model.spaces.empty() && input::model.sessions.empty(), "partial input session leaked");
    runtime.shutdown();
    input::model.failSpaceAt = 0;
    prepare(runtime);
    runtime.beginFrame(); runtime.endFrame(false);
  }
  expect(input::model.sets.empty() && input::model.spaces.empty(), "retry leaked input resources");
}
void panelIntegration() {
  fixture = {};
  {
    gk3hd::vr::Runtime runtime(resolve); prepare(runtime);
    rejects([&] { runtime.createPanelSwapchain(VK_FORMAT_UNDEFINED, 1024, 768); });
    rejects([&] { runtime.createPanelSwapchain(VK_FORMAT_R8G8B8A8_SRGB, 0, 768); });
    fixture.failPanelImages = true;
    rejects([&] { runtime.createPanelSwapchain(VK_FORMAT_R8G8B8A8_SRGB, 1024, 768); });
    expect(fixture.extents.size() == 2 && runtime.panelImages().empty(), "partial panel creation damaged eyes or leaked");
    fixture.failPanelImages = false;
    runtime.createPanelSwapchain(VK_FORMAT_R8G8B8A8_SRGB, 1024, 768);
    rejects([&] { runtime.createPanelSwapchain(VK_FORMAT_R8G8B8A8_SRGB, 1024, 768); });
    rejects([&] { runtime.acquirePanel(); });
    const gk3hd::vr::PanelLayer panel{{{0, 0, 0, 1}, {0, 1.5f, -1.6f}}, {1.6f, 1.2f}};
    runtime.beginFrame();
    rejects([&] { runtime.endFrame(false, &panel); });
    expect(runtime.acquirePanel() == 1, "wrong acquired panel image");
    rejects([&] { runtime.acquirePanel(); });
    rejects([&] { runtime.destroyPanelSwapchain(); });
    rejects([&] { runtime.endFrame(false); });
    runtime.releasePanel();
    rejects([&] { runtime.destroyPanelSwapchain(); });
    runtime.endFrame(false, &panel);
    expect(fixture.layers == 1 && fixture.panelLayers == 1 && fixture.panelExtent.width == 1024 &&
           fixture.panelExtent.height == 768, "panel-only frame submitted incorrect canvas");
    runtime.beginFrame();
    for (unsigned eye = 0; eye < 2; ++eye) { runtime.acquireEye(eye); runtime.releaseEye(eye); }
    runtime.acquirePanel(); runtime.releasePanel();
    runtime.endFrame(true, &panel);
    expect(fixture.layers == 2 && fixture.panelLayers == 1, "world and panel were not composed together");
    expect(!fixture.panelFlags, "opaque canvas enabled source alpha");
    runtime.beginFrame();
    for (unsigned eye = 0; eye < 2; ++eye) { runtime.acquireEye(eye); runtime.releaseEye(eye); }
    runtime.acquirePanel(); runtime.releasePanel();
    auto transparent = panel; transparent.transparent = true;
    runtime.endFrame(true, &transparent);
    expect(fixture.layers == 2 && fixture.panelFlags == XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT,
           "isolated captions did not request premultiplied source-alpha composition");
    runtime.destroyPanelSwapchain();
    expect(runtime.panelImages().empty() && fixture.extents.size() == 2, "panel resize damaged eyes");
    runtime.createPanelSwapchain(VK_FORMAT_R8G8B8A8_SRGB, 1280, 800);
    runtime.beginFrame(); runtime.acquirePanel(); runtime.releasePanel();
    auto invalid = panel; invalid.pose.orientation.w = 0;
    rejects([&] { runtime.endFrame(false, &invalid); });
    runtime.endFrame(false);
    runtime.beginFrame(); runtime.acquirePanel();
  }
  expect(fixture.extents.empty(), "panel/session teardown retained borrowed images");
}
void keyboardIntegration() {
  using namespace gk3hd::vr;
  fixture = {};
  {
    Runtime runtime(resolve); prepare(runtime);
    runtime.createPanelSwapchain(VK_FORMAT_R8G8B8A8_SRGB, 1024, 768);
    rejects([&] { runtime.createKeyboardSwapchain(VK_FORMAT_UNDEFINED, 1200, 456); });
    rejects([&] { runtime.createKeyboardSwapchain(VK_FORMAT_R8G8B8A8_SRGB, 1200, 0); });
    fixture.failPanelImages = true;
    rejects([&] { runtime.createKeyboardSwapchain(VK_FORMAT_R8G8B8A8_SRGB, 1200, 456); });
    expect(runtime.keyboardImages().empty() && fixture.extents.size() == 3,
           "partial keyboard target creation leaked or damaged existing targets");
    fixture.failPanelImages = false;
    runtime.createKeyboardSwapchain(VK_FORMAT_R8G8B8A8_SRGB, 1200, 456);
    const PanelLayer panel{{{0, 0, 0, 1}, {0, 1.5f, -1.6f}}, {1.6f, 1.2f}};
    const PanelLayer keyboard{{{0, 0, 0, 1}, {0, .612f, -1.58f}}, {1.2f, .456f}};
    rejects([&] { runtime.acquireKeyboard(); });
    rejects([&] { runtime.releaseKeyboard(); });
    runtime.beginFrame();
    runtime.acquirePanel(); runtime.releasePanel();
    rejects([&] { runtime.endFrame(false, &panel, &keyboard); });
    expect(runtime.acquireKeyboard() == 1, "wrong keyboard swapchain acquisition");
    rejects([&] { runtime.acquireKeyboard(); });
    rejects([&] { runtime.destroyKeyboardSwapchain(); });
    rejects([&] { runtime.endFrame(false); });
    runtime.releaseKeyboard();
    rejects([&] { runtime.destroyKeyboardSwapchain(); });
    rejects([&] { runtime.endFrame(false, nullptr, &keyboard); });
    auto bad = keyboard; bad.pose.orientation.w = 0;
    rejects([&] { runtime.endFrame(false, &panel, &bad); });
    runtime.endFrame(false, &panel, &keyboard);
    expect(fixture.layers == 2 && fixture.panelLayers == 2 && fixture.quadChains.size() == 2 &&
           fixture.quadChains[0] != fixture.quadChains[1] && fixture.panelExtent.width == 1200 &&
           fixture.panelExtent.height == 456 && fixture.quadPoses[1].position.y == .612f,
           "keyboard replaced/stretched editor or lost its independent layer pose");
    runtime.beginFrame();
    runtime.acquirePanel(); runtime.releasePanel();
    rejects([&] { runtime.endFrame(false, &panel, &keyboard); });
    runtime.acquireKeyboard(); runtime.releaseKeyboard();
    for (unsigned eye = 0; eye < 2; ++eye) { runtime.acquireEye(eye); runtime.releaseEye(eye); }
    runtime.endFrame(true, &panel, &keyboard);
    expect(fixture.layers == 3 && fixture.panelLayers == 2,
           "stereo world/editor/keyboard failed same-frame composition");
    runtime.beginFrame(); runtime.endFrame(false);
    expect(!fixture.layers, "cancelled frame retained keyboard or editor layers");
    runtime.destroyKeyboardSwapchain();
    expect(fixture.extents.size() == 3 && runtime.keyboardImages().empty(),
           "keyboard withdrawal damaged eye/editor targets");
    runtime.createKeyboardSwapchain(VK_FORMAT_R8G8B8A8_SRGB, 1200, 456);
    runtime.beginFrame(); runtime.acquireKeyboard();
  }
  expect(fixture.extents.empty(), "session teardown leaked acquired keyboard images");
  fixture = {};
  {
    Runtime runtime(resolve); prepare(runtime);
    runtime.createKeyboardSwapchain(VK_FORMAT_R8G8B8A8_SRGB, 1200, 456);
    runtime.beginFrame(); fixture.timeout = true;
    rejects([&] { runtime.acquireKeyboard(); });
    fixture.timeout = false;
    runtime.closeSession();
    expect(fixture.released == 1 && fixture.ended == 1 && fixture.extents.empty(),
           "keyboard wait failure did not recover ownership during teardown");
  }
}
void subtitleIntegration() {
  using namespace gk3hd::vr;
  fixture={};
  {
    Runtime runtime(resolve); prepare(runtime);
    runtime.createPanelSwapchain(VK_FORMAT_R8G8B8A8_SRGB,1280,800);
    runtime.createKeyboardSwapchain(VK_FORMAT_R8G8B8A8_SRGB,1280,800);
    rejects([&] { runtime.createSubtitleSwapchain(VK_FORMAT_UNDEFINED,1280,800); });
    runtime.createSubtitleSwapchain(VK_FORMAT_R8G8B8A8_SRGB,1280,800);
    const PanelLayer panel{{{0,0,0,1},{0,1.5f,-1.6f}},{1.6f,1.f},true};
    const PanelLayer subtitle{{{0,0,0,1},{0,2.28f,-1.6f}},{4.096f,2.56f},true};
    runtime.beginFrame();
    for (unsigned eye=0;eye<2;++eye) { runtime.acquireEye(eye); runtime.releaseEye(eye); }
    runtime.acquirePanel(); runtime.releasePanel();
    runtime.acquireKeyboard(); runtime.releaseKeyboard();
    rejects([&] { runtime.endFrame(true,&panel,&panel,&subtitle); });
    runtime.acquireSubtitle();
    rejects([&] { runtime.endFrame(true,&panel,&panel,&subtitle); });
    rejects([&] { runtime.destroySubtitleSwapchain(); });
    runtime.releaseSubtitle();
    auto opaque=subtitle; opaque.transparent=false;
    rejects([&] { runtime.endFrame(true,&panel,&panel,&opaque); });
    runtime.endFrame(true,&panel,&panel,&subtitle);
    expect(fixture.layers==4 && fixture.quadChains.size()==3 &&
           fixture.quadChains[0]!=fixture.quadChains[2] && fixture.quadChains[1]!=fixture.quadChains[2],
           "subtitles replaced menu/HUD or lost same-frame composition");
    runtime.beginFrame();
    for (unsigned eye=0;eye<2;++eye) { runtime.acquireEye(eye); runtime.releaseEye(eye); }
    rejects([&] { runtime.endFrame(true,nullptr,nullptr,&subtitle); });
    runtime.endFrame(true);
    expect(fixture.layers==1,"retired subtitles retained a layer");
    runtime.beginFrame();
    runtime.acquireSubtitle(); runtime.releaseSubtitle();
    rejects([&] { runtime.endFrame(false,nullptr,nullptr,&subtitle); });
    runtime.acquirePanel(); runtime.releasePanel();
    auto screen=panel; screen.transparent=false;
    runtime.endFrame(false,&screen,nullptr,&subtitle);
    expect(fixture.layers==2 && fixture.quadChains.size()==2 &&
           fixture.quadChains[0]!=fixture.quadChains[1],
           "cinematic subtitles required projection eyes or replaced the native screen");
    runtime.beginFrame(); runtime.acquirePanel(); runtime.releasePanel();
    rejects([&] { runtime.endFrame(false,&screen,nullptr,&subtitle); });
    runtime.endFrame(false,&screen);
    expect(fixture.layers==1,"retired cinematic subtitle retained an auxiliary layer");
    runtime.beginFrame(); runtime.acquireSubtitle();
  }
  expect(fixture.extents.empty(),"subtitle teardown leaked an acquired target");
}
void mirrorCadence() {
  using gk3hd::vr::MirrorPacer;
  for (const int64_t hz : {80, 90, 120, 144}) {
    MirrorPacer pacer;
    unsigned accepted = 0;
    for (int64_t frame = 1; frame <= hz * 3; ++frame) {
      const auto time = frame * 1'000'000'000 / hz;
      if (pacer.due(time)) ++accepted;
      expect(!pacer.due(time), "mirror repeated one headset frame");
    }
    expect(accepted >= 89 && accepted <= 91, "mirror rate depends on headset refresh or blocks XR frames");
  }
  MirrorPacer pacer;
  expect(pacer.due(1'000'000'000) && !pacer.due(1'001'000'000), "mirror did not pace successive predictions");
  expect(pacer.due(2'000'000'000) && !pacer.due(2'001'000'000), "mirror burst after a missed interval");
  expect(pacer.due(100) && !pacer.due(101), "mirror did not recover a restarted clock");
  expect(pacer.due(0) && pacer.due(0) && pacer.due(-1), "ordinary presentation was throttled without XR tracking");
  const auto maximum = std::numeric_limits<int64_t>::max();
  expect(pacer.due(maximum) && !pacer.due(maximum), "mirror overflow or duplicate near clock limit");
  pacer.reset(); expect(pacer.due(100), "mirror reset retained an old deadline");
}
void cameraMath() {
  using namespace gk3hd::vr;
  const auto close = [](float a, float b) { return std::abs(a - b) < 1e-4f; };
  const float sine = std::sqrt(0.5f);
  const XrPosef base{{0, sine, 0, sine}, {2, 3, 4}};
  const XrPosef eye{{0, 0, 0, 1}, {-0.032f, 0, 0}};
  const auto recovered = compose(inverse(base), compose(base, eye));
  expect(close(recovered.position.x, eye.position.x) && close(recovered.position.z, 0),
         "tracking recenter lost eye separation");
  const auto forward = rotate(base.orientation, {0, 0, -1});
  expect(close(forward.x, -1) && close(forward.z, 0), "wrong tracking rotation convention");
  const XrFovf fov{-0.7f, 0.9f, 0.8f, -0.6f};
  const auto matrix = projection(fov, 0.1f, 100);
  const auto x = [&](float value) { return matrix[0] * value - matrix[8]; };
  const auto y = [&](float value) { return matrix[5] * value - matrix[9]; };
  expect(close(x(std::tan(fov.angleLeft)), -1) && close(x(std::tan(fov.angleRight)), 1),
         "asymmetric horizontal projection is incorrect");
  expect(close(y(std::tan(fov.angleUp)), -1) && close(y(std::tan(fov.angleDown)), 1),
         "asymmetric vertical projection is incorrect");
  expect(close((-matrix[10] * 0.1f + matrix[14]) / 0.1f, 0), "near depth is not zero");
  expect(close((-matrix[10] * 100 + matrix[14]) / 100, 1), "far depth is not one");
  rejects([&] { projection(fov, 0, 100); });
  rejects([&] { projection({-2, 2, 1, -1}, 0.1f, 100); });
  rejects([&] { normalized({0, 0, 0, 0}); });
  PanelPoint point{};
  const XrPosef panel{{0, 0, 0, 1}, {0, 0, -2}};
  const XrPosef aim{{0, 0, 0, 1}, {0, 0, 0}};
  expect(panelPoint(panel, 2, 1.5f, aim, 1024, 768, point), "center ray missed panel");
  expect(close(point.x, 512) && close(point.y, 384), "panel center has an input offset");
  auto edge = aim; edge.position.x = 0.9f; edge.position.y = 0.6f;
  expect(panelPoint(panel, 2, 1.5f, edge, 1024, 768, point), "edge ray missed panel");
  expect(close(point.x, 972.8f) && close(point.y, 76.8f), "edge panel coordinates drift");
  edge.position.x = 1.1f;
  expect(!panelPoint(panel, 2, 1.5f, edge, 1024, 768, point), "outside panel ray was accepted");
  edge = aim; edge.position.z = -3;
  expect(!panelPoint(panel, 2, 1.5f, edge, 1024, 768, point), "backward panel ray was accepted");
}

void engineCameraMath() {
  using namespace gk3hd::vr;
  const auto close = [](float a, float b) { return std::abs(a-b) < 2e-4f; };
  EngineCamera base{};
  base.position = {10, 20, 30};
  base.target = {10, 20, 31};
  // Projection-scaled rows, as used by the original engine. Tracking must
  // preserve physical distances rather than inheriting these unequal scales.
  base.worldToCamera = {1, 0, 0, 0, 2, 0, 0, 0, 0.5f, -10, -40, -15};
  const XrFovf fov{-0.7f, 0.9f, 0.8f, -0.6f};
  const XrPosef identity{{0, 0, 0, 1}, {0, 0, 0}};
  const auto center = engineEyeCamera(base, identity, fov, 1400, 1200, 40, 0.05f, 600);
  const auto point = engineCameraPoint(center.camera, {10, 20, 110});
  expect(close(point.z, 80), "engine projection scale leaked into physical depth");
  const auto& p = center.projection;
  const auto screen = [&](float x, float y, float z) {
    return engineScreenPoint(p, engineCameraPoint(center.camera, {10+x, 20+y, 30+z}));
  };
  expect(close(screen(80*std::tan(fov.angleLeft), 0, 80)[0], 0) &&
         close(screen(80*std::tan(fov.angleRight), 0, 80)[0], 1400),
         "engine asymmetric horizontal FOV does not match the eye image");
  expect(close(screen(0, 80*std::tan(fov.angleUp), 80)[1], 0) &&
         close(screen(0, 80*std::tan(fov.angleDown), 80)[1], 1200),
         "engine asymmetric vertical FOV does not match the eye image");
  expect(close(screen(0, 0, 2)[2], 0) && close(screen(0, 0, 24000)[2], 1),
         "engine clip distances do not match submitted depth");
  const auto inside = [&](XrVector3f v) {
    v = engineCameraPoint(center.camera, {10+v.x, 20+v.y, 30+v.z});
    for (const auto& plane : center.camera.planes) {
      if (plane.x*v.x + plane.y*v.y + plane.z*v.z + plane.distance < -1e-4f)
        return false;
    }
    return true;
  };
  expect(inside({0, 0, 80}) && !inside({0, 0, 1}) && !inside({0, 0, 25000}),
         "near/far engine culling disagrees with projection");
  expect(inside({79*std::tan(fov.angleLeft), 0, 80}) &&
         !inside({81*std::tan(fov.angleLeft), 0, 80}),
         "engine side planes are inconsistent");
  expect(inside({0, 79*std::tan(fov.angleUp), 80}) &&
         !inside({0, 81*std::tan(fov.angleUp), 80}), "engine top plane clips wrong side");
  for (const auto& plane : center.camera.planes)
    expect(close(plane.x*plane.x + plane.y*plane.y + plane.z*plane.z, 1),
           "non-unit clipping plane would distort sphere culling");
  auto leftPose = identity, rightPose = identity;
  leftPose.position.x = -0.032f; rightPose.position.x = 0.032f;
  const auto left = engineEyeCamera(base, leftPose, fov, 1400, 1200, 40, 0.05f, 600);
  const auto right = engineEyeCamera(base, rightPose, fov, 1400, 1200, 40, 0.05f, 600);
  expect(close(right.camera.position.x-left.camera.position.x, 2.56f),
         "engine IPD is not expressed in calibrated world units");
  const auto leftPoint = engineScreenPoint(left.projection,
      engineCameraPoint(left.camera, {10, 20, 110}));
  const auto rightPoint = engineScreenPoint(right.projection,
      engineCameraPoint(right.camera, {10, 20, 110}));
  expect(leftPoint[0] > rightPoint[0], "stereo parallax has reversed eyes");
  auto moved = identity; moved.position = {0, 0.1f, -0.2f};
  const auto lean = engineEyeCamera(base, moved, fov, 1400, 1200, 40, 0.05f, 600);
  expect(close(lean.camera.position.y, 24) && close(lean.camera.position.z, 38),
         "tracked lean uses the wrong engine basis or world scale");
  const float sine = std::sqrt(0.5f);
  moved = identity; moved.orientation = {0, sine, 0, sine};
  const auto turn = engineEyeCamera(base, moved, fov, 1400, 1200, 40, 0.05f, 600);
  const auto facing = engineCameraPoint(turn.camera, {-70, 20, 30});
  expect(close(facing.x, point.x) && close(facing.y, point.y) && close(facing.z, 80),
         "OpenXR head rotation is reflected incorrectly in the engine");
  expect(base.worldToCamera[4] == 2 && center.camera.target.z == base.target.z,
         "eye rendering changed the authored simulation camera");
  rejects([&] { engineEyeCamera(base, identity, fov, 0, 1200, 40, 0.05f, 600); });
  rejects([&] { engineEyeCamera(base, identity, fov, 1400, 1200, -1, 0.05f, 600); });
  rejects([&] { engineScreenPoint(p, {0, 0, -1}); });
  base.worldToCamera[3] = 1;
  rejects([&] { engineEyeCamera(base, identity, fov, 1400, 1200, 40, 0.05f, 600); });
}

void engineFrustumBounds() {
  using namespace gk3hd::vr;
  EngineCamera base{};
  base.worldToCamera = {1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0};
  const XrPosef identity{{0, 0, 0, 1}, {0, 0, 0}};
  const std::array<XrFovf, 3> fields{{{-0.7f, 0.9f, 0.8f, -0.6f},
                                    {-1.05f, 0.78f, 0.92f, -0.82f},
                                    {-0.95f, 0.55f, 0.4f, -0.8f}}};
  for (const auto fov : fields) {
    const auto eye = engineEyeCamera(base, identity, fov, 1400, 1200, 40, 0.05f, 600);
    const float left = std::tan(fov.angleLeft), right = std::tan(fov.angleRight);
    const float down = std::tan(fov.angleDown), top = std::tan(fov.angleUp);
    const float middleX = (left+right)*50, middleY = (down+top)*50;
    const auto clip = [&](float x, float y) {
      return engineCameraPoint(eye.camera, {x, y, 100});
    };
    expect(std::abs(clip(left*100, middleY).x+100) < 0.001f &&
           std::abs(clip(right*100, middleY).x-100) < 0.001f &&
           std::abs(clip(middleX, top*100).y-100) < 0.001f &&
           std::abs(clip(middleX, down*100).y+100) < 0.001f,
           "fast canonical clipping disagrees with the runtime FOV boundaries");
    // A world-space unit sphere must fit inside GK3's conservative padding
    // even when asymmetric projection shears its camera-space shape.
    const auto& m = eye.camera.worldToCamera;
    for (const int sign : {-1, 1}) {
      const float xBound = std::sqrt(
          std::pow(m[0]+sign*m[2], 2) + std::pow(m[3]+sign*m[5], 2) +
          std::pow(m[6]+sign*m[8], 2));
      const float yBound = std::sqrt(
          std::pow(m[1]+sign*m[2], 2) + std::pow(m[4]+sign*m[5], 2) +
          std::pow(m[7]+sign*m[8], 2));
      expect(xBound <= 1+eye.camera.depthScale+1e-5f &&
             yBound <= eye.camera.aspect+eye.camera.depthScale+1e-5f,
             "BSP culling would reject a visible asymmetric-frustum sphere");
    }
  }
}
void engineRayMath() {
  using namespace gk3hd::vr;
  const auto close = [](float a, float b) { return std::abs(a-b) < .001f; };
  EngineCamera base{};
  base.position = {10, 20, 30};
  // Authored axes face +X, with unequal projection scales. Right is -Z.
  base.worldToCamera = {0, 0, .5f, 0, 2, 0, -3, 0, 0, 90, -40, -5};
  XrPosef aim{{0, 0, 0, 1}, {.1f, .2f, -.3f}};
  const auto saved = base;
  const auto ray = engineAimRay(base, aim, 40, .05f, 600);
  expect(close(ray.origin.x, 22) && close(ray.origin.y, 28) && close(ray.origin.z, 26) &&
         close(ray.nearPoint.x, 24) && close(ray.farPoint.x, 24022) &&
         close(ray.farPoint.z, 26), "ray inherited projection scale or wrong handedness");
  const auto eye = engineEyeCamera(base, aim, {-.7f, .9f, .8f, -.6f}, 1280, 800, 40, .05f, 600);
  expect(close(eye.camera.position.x, ray.origin.x) && close(eye.camera.position.y, ray.origin.y) &&
         close(eye.camera.position.z, ray.origin.z), "eyes and rays have different world origins");
  const float sine = std::sqrt(.5f);
  aim.orientation = {0, sine, 0, sine};
  const auto side = engineAimRay(base, aim, 40, 0, 10);
  expect(close(side.farPoint.z, 426) && close(side.farPoint.x, 22) &&
         close(side.nearPoint.x, side.origin.x), "controller can not point outside desktop FOV");
  expect(std::memcmp(&base, &saved, sizeof(base)) == 0, "ray generation mutated authored camera");
  rejects([&] { engineAimRay(base, aim, 0, 0, 10); });
  rejects([&] { engineAimRay(base, aim, 40, -1, 10); });
  rejects([&] { engineAimRay(base, aim, 40, 10, 10); });
  rejects([&] { engineAimRay(base, aim, 40, 0, INFINITY); });
  aim.position.x = NAN;
  rejects([&] { engineAimRay(base, aim, 40, 0, 10); });
  aim.position.x = .1f; aim.orientation = {};
  rejects([&] { engineAimRay(base, aim, 40, 0, 10); });
  aim.orientation.w = 1; base.worldToCamera[3] = 1;
  rejects([&] { engineAimRay(base, aim, 40, 0, 10); });
}
} // namespace

int main() {
  try {
    lifecycle(); frameQueueOwnership(); terminalSessionLoss(); recommendedEyeDimensions(); failures(); rendererIntegration(); inputIntegration(); panelIntegration(); keyboardIntegration(); subtitleIntegration(); mirrorCadence(); cameraMath(); engineCameraMath(); engineFrustumBounds(); engineRayMath();
    std::cout << "OpenXR lifecycle tests passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n'; return 1;
  }
}
