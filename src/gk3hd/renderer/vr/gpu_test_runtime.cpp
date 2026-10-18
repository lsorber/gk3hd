// Test-only OpenXR runtime. Real Vulkan objects, synthetic tracking, no headset
// compositor. Never installed with the renderer or registered persistently.
#define XR_USE_GRAPHICS_API_VULKAN
#define XR_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <openxr/openxr.h>
#include <openxr/openxr_platform.h>
#include <openxr/openxr_loader_negotiation.h>
#include <windows.h>
#include "input_test_runtime.h"
#include "gpu_test_config.h"
#include "test_input_feed.h"

#include <array>
#include <atomic>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <deque>
#include <functional>
#include <memory>
#include <vector>

namespace {
// Optional cross-process controller fixture for private live-engine tests.
// No production code uses this channel. An even sequence commits a complete
// packet; acknowledged is written only after that packet has been sampled.
using gk3hd::vr::testinput::TestInputPacket;
struct TestFeed {
  HANDLE mapping = nullptr;
  TestInputPacket* packet = nullptr;
  bool requested = false;
  gk3hd::vr::testinput::TestInputSampler sampler;
  void open() {
    char name[256]{};
    const auto size = GetEnvironmentVariableA("GK3HD_XR_TEST_INPUT_MAPPING", name, sizeof(name));
    requested = size != 0;
    if (!size || size >= sizeof(name)) return;
    mapping = OpenFileMappingA(FILE_MAP_READ | FILE_MAP_WRITE, FALSE, name);
    if (mapping) packet = static_cast<TestInputPacket*>(MapViewOfFile(
      mapping, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, sizeof(TestInputPacket)));
  }
  ~TestFeed() {
    if (packet) UnmapViewOfFile(packet);
    if (mapping) CloseHandle(mapping);
  }
  void sample() {
    if (!requested) return;
    auto& model = gk3hd::vr::testinput::model;
    auto neutral = [&] { model.hands = {}; model.syncResult = XR_SESSION_NOT_FOCUSED; };
    const auto sampled = sampler.sample(packet, GetTickCount());
    if (!sampled.packet) { neutral(); return; }
    const auto& copy = *sampled.packet;
    for (unsigned index = 0; index < 2; ++index) {
      const auto& input = copy.hands[index];
      auto& hand = model.hands[index];
      hand.active = (input.flags & 1) != 0;
      hand.valid = (input.flags & 2) != 0;
      hand.buttons = input.buttons; hand.pose = input.pose; hand.stick = input.stick;
    }
    model.syncResult = copy.focused ? XR_SUCCESS : XR_SESSION_NOT_FOCUSED;
    if (sampled.committed)
      InterlockedExchange(reinterpret_cast<volatile LONG*>(&packet->acknowledged), copy.sequence);
  }
};
TestFeed* inputFeed = nullptr;
// Render-thread-only private experiment fixture, never a production tracking
// source. Lets the running original engine qualify wall approach/retreat.
XrVector3f headOffset{};
struct Session {
  const DWORD ownerThread = GetCurrentThreadId();
  std::atomic<uint32_t> mainWaits{0};
  PFN_vkGetInstanceProcAddr instanceResolve = nullptr;
  XrGraphicsBindingVulkanKHR graphics{};
  PFN_vkGetDeviceProcAddr resolve = nullptr;
  bool running = false;
  bool frame = false;
  XrTime time = 0;
  std::deque<XrSessionState> events;
  std::array<std::vector<uint8_t>, 2> submitted;
  uint32_t submittedFrames = 0;
  std::vector<uint8_t> panelPixels;
  std::array<float, 9> panelGeometry{};
  uint32_t panelFrames = 0;
  uint64_t panelFlags = 0;
  uint32_t syncCalls = 0, lastLayerCount = 0;
  uint32_t panelWidth = 0, panelHeight = 0;
  std::vector<uint8_t> keyboardPixels;
  std::array<float, 9> keyboardGeometry{};
  uint32_t keyboardFrames = 0;
  bool keyboardVisible = false;
  std::vector<uint8_t> subtitlePixels;
  std::array<float, 9> subtitleGeometry{};
  bool subtitleVisible = false;
  uint64_t frameSequence = 0;
  bool captureWritten = false;
  bool panelCaptureWritten = false;
  bool skipPixelReadback = false;
};
Session* eventSession = nullptr;
struct Chain {
  Session* session = nullptr;
  std::array<VkImage, 2> images{};
  std::array<VkDeviceMemory, 2> memory{};
  uint32_t next = 0;
  bool acquired = false;
  bool waited = false;
  uint64_t releasedFrame = 0;
  uint32_t width = 0, height = 0;
  VkFormat format = VK_FORMAT_UNDEFINED;
};
struct Instance {
  std::array<uint32_t, 2> eyeSize{256, 256};
  TestFeed feed;
  PFN_vkGetInstanceProcAddr resolve = nullptr;
  VkInstance vulkan = VK_NULL_HANDLE;
  VkPhysicalDevice physical = VK_NULL_HANDLE;
};
Instance* instance(XrInstance value) { return reinterpret_cast<Instance*>(value); }
Session* session(XrSession value) { return reinterpret_cast<Session*>(value); }
Chain* chain(XrSwapchain value) { return reinterpret_cast<Chain*>(value); }
template<typename T> T deviceFunction(Session* state, const char* name) {
  return reinterpret_cast<T>(state->resolve(state->graphics.device, name));
}
template<typename T> XrResult enumerate(uint32_t capacity, uint32_t* count,
                                      T* output, const std::vector<T>& values) {
  if (!count) return XR_ERROR_VALIDATION_FAILURE;
  *count = static_cast<uint32_t>(values.size());
  if (!capacity) return XR_SUCCESS;
  if (capacity < values.size()) return XR_ERROR_SIZE_INSUFFICIENT;
  if (!output) return XR_ERROR_VALIDATION_FAILURE;
  for (size_t i = 0; i < values.size(); ++i) output[i] = values[i];
  return XR_SUCCESS;
}
XrResult XRAPI_CALL extensions(const char*, uint32_t capacity, uint32_t* count,
                              XrExtensionProperties* output) {
  XrExtensionProperties value{XR_TYPE_EXTENSION_PROPERTIES};
  constexpr char extension[] = XR_KHR_VULKAN_ENABLE2_EXTENSION_NAME;
  std::memcpy(value.extensionName, extension, sizeof(extension));
  value.extensionVersion = XR_KHR_vulkan_enable2_SPEC_VERSION;
  return enumerate(capacity, count, output, std::vector<XrExtensionProperties>{value});
}
XrResult XRAPI_CALL createInstance(const XrInstanceCreateInfo*, XrInstance* output) {
  char size[32]{};
  const auto length = GetEnvironmentVariableA("GK3HD_XR_TEST_EYE_SIZE", size, sizeof(size));
  if (length >= sizeof(size)) return XR_ERROR_INITIALIZATION_FAILED;
  const auto extent = gk3hd::vr::testEyeSize(size);
  if (!extent[0]) return XR_ERROR_INITIALIZATION_FAILED;
  auto* state = new Instance;
  state->eyeSize = extent;
  state->feed.open(); inputFeed = &state->feed;
  *output = reinterpret_cast<XrInstance>(state); return XR_SUCCESS;
}
XrResult XRAPI_CALL destroyInstance(XrInstance value) {
  inputFeed = nullptr; delete instance(value); return XR_SUCCESS;
}
XrResult XRAPI_CALL properties(XrInstance, XrInstanceProperties* output) {
  constexpr char name[] = "GK3HD GPU test runtime (NOT a headset)";
  std::memcpy(output->runtimeName, name, sizeof(name));
  output->runtimeVersion = XR_MAKE_VERSION(1, 0, 0); return XR_SUCCESS;
}
XrResult XRAPI_CALL getSystem(XrInstance, const XrSystemGetInfo*, XrSystemId* output) {
  *output = 1; return XR_SUCCESS;
}
XrResult XRAPI_CALL requirements(XrInstance, XrSystemId, XrGraphicsRequirementsVulkanKHR* output) {
  output->minApiVersionSupported = XR_MAKE_VERSION(1, 0, 0);
  output->maxApiVersionSupported = XR_MAKE_VERSION(1, 3, 0); return XR_SUCCESS;
}
XrResult XRAPI_CALL views(XrInstance value, XrSystemId, XrViewConfigurationType type,
                         uint32_t capacity, uint32_t* count, XrViewConfigurationView* output) {
  if (type != XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO) return XR_ERROR_VIEW_CONFIGURATION_TYPE_UNSUPPORTED;
  XrViewConfigurationView view{XR_TYPE_VIEW_CONFIGURATION_VIEW};
  view.recommendedImageRectWidth = view.maxImageRectWidth = instance(value)->eyeSize[0];
  view.recommendedImageRectHeight = view.maxImageRectHeight = instance(value)->eyeSize[1];
  view.recommendedSwapchainSampleCount = view.maxSwapchainSampleCount = 1;
  return enumerate(capacity, count, output, std::vector<XrViewConfigurationView>{view, view});
}
XrResult XRAPI_CALL blends(XrInstance, XrSystemId, XrViewConfigurationType,
                          uint32_t capacity, uint32_t* count, XrEnvironmentBlendMode* output) {
  return enumerate(capacity, count, output, std::vector<XrEnvironmentBlendMode>{XR_ENVIRONMENT_BLEND_MODE_OPAQUE});
}
XrResult XRAPI_CALL createVkInstance(XrInstance value, const XrVulkanInstanceCreateInfoKHR* info,
                                    VkInstance* output, VkResult* result) {
  auto* state = instance(value);
  state->resolve = info->pfnGetInstanceProcAddr;
  auto create = reinterpret_cast<PFN_vkCreateInstance>(state->resolve(VK_NULL_HANDLE, "vkCreateInstance"));
  if (!create) return XR_ERROR_RUNTIME_FAILURE;
  *result = create(info->vulkanCreateInfo, info->vulkanAllocator, output);
  if (*result == VK_SUCCESS) state->vulkan = *output;
  return XR_SUCCESS;
}
XrResult XRAPI_CALL getVkDevice(XrInstance value, const XrVulkanGraphicsDeviceGetInfoKHR* info,
                               VkPhysicalDevice* output) {
  auto* state = instance(value);
  if (state->vulkan != info->vulkanInstance) return XR_ERROR_GRAPHICS_DEVICE_INVALID;
  auto list = reinterpret_cast<PFN_vkEnumeratePhysicalDevices>(state->resolve(state->vulkan, "vkEnumeratePhysicalDevices"));
  auto props = reinterpret_cast<PFN_vkGetPhysicalDeviceProperties>(state->resolve(state->vulkan, "vkGetPhysicalDeviceProperties"));
  uint32_t count = 0;
  if (list(state->vulkan, &count, nullptr) != VK_SUCCESS || !count) return XR_ERROR_RUNTIME_FAILURE;
  std::vector<VkPhysicalDevice> devices(count);
  if (list(state->vulkan, &count, devices.data()) != VK_SUCCESS) return XR_ERROR_RUNTIME_FAILURE;
  state->physical = devices[0];
  for (auto device : devices) {
    VkPhysicalDeviceProperties properties{}; props(device, &properties);
    if (properties.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU) { state->physical = device; break; }
  }
  *output = state->physical; return XR_SUCCESS;
}
XrResult XRAPI_CALL createVkDevice(XrInstance value, const XrVulkanDeviceCreateInfoKHR* info,
                                  VkDevice* output, VkResult* result) {
  auto* state = instance(value);
  if (info->vulkanPhysicalDevice != state->physical) return XR_ERROR_GRAPHICS_DEVICE_INVALID;
  auto create = reinterpret_cast<PFN_vkCreateDevice>(state->resolve(state->vulkan, "vkCreateDevice"));
  *result = create(state->physical, info->vulkanCreateInfo, info->vulkanAllocator, output);
  return XR_SUCCESS;
}
XrResult XRAPI_CALL createSession(XrInstance value, const XrSessionCreateInfo* info, XrSession* output) {
  const auto* binding = static_cast<const XrGraphicsBindingVulkanKHR*>(info->next);
  if (!binding || binding->type != XR_TYPE_GRAPHICS_BINDING_VULKAN_KHR ||
      binding->instance != instance(value)->vulkan || binding->physicalDevice != instance(value)->physical)
    return XR_ERROR_GRAPHICS_DEVICE_INVALID;
  auto state = std::make_unique<Session>(); state->graphics = *binding;
  char skip[2]{};
  state->skipPixelReadback =
    GetEnvironmentVariableA("GK3HD_XR_TEST_SKIP_PIXEL_READBACK", skip, sizeof(skip)) == 1 && skip[0] == '1';
  // Explicit lower-bound transport timing, never pixel or headset acceptance.
  // Do not silently produce empty evidence if a capture was requested too.
  if (state->skipPixelReadback &&
      (GetEnvironmentVariableA("GK3HD_XR_TEST_CAPTURE", nullptr, 0) ||
       GetEnvironmentVariableA("GK3HD_XR_TEST_PANEL_CAPTURE", nullptr, 0)))
    return XR_ERROR_VALIDATION_FAILURE;
  state->instanceResolve = instance(value)->resolve;
  state->resolve = reinterpret_cast<PFN_vkGetDeviceProcAddr>(instance(value)->resolve(binding->instance, "vkGetDeviceProcAddr"));
  state->events = {XR_SESSION_STATE_READY, XR_SESSION_STATE_VISIBLE, XR_SESSION_STATE_FOCUSED};
  *output = reinterpret_cast<XrSession>(state.release()); return XR_SUCCESS;
}
XrResult XRAPI_CALL destroySession(XrSession value) {
  if (eventSession == session(value)) eventSession = nullptr;
  gk3hd::vr::testinput::detachSession(value);
  delete session(value); return XR_SUCCESS;
}
XrResult XRAPI_CALL createSpace(XrSession, const XrReferenceSpaceCreateInfo*, XrSpace* output) {
  *output = reinterpret_cast<XrSpace>(new int(0)); return XR_SUCCESS;
}
XrResult XRAPI_CALL destroySpace(XrSpace value) {
  if (gk3hd::vr::testinput::ownsSpace(value)) return gk3hd::vr::testinput::destroySpace(value);
  delete reinterpret_cast<int*>(value); return XR_SUCCESS;
}
// The test host polls through its session directly. Kept in a single-process
// fixture, never used as a general multi-session runtime.
XrResult XRAPI_CALL poll(XrInstance, XrEventDataBuffer* output) {
  if (!eventSession || eventSession->events.empty()) return XR_EVENT_UNAVAILABLE;
  XrEventDataSessionStateChanged event{XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED};
  event.session = reinterpret_cast<XrSession>(eventSession);
  event.state = eventSession->events.front(); eventSession->events.pop_front();
  std::memcpy(output, &event, sizeof(event)); return XR_SUCCESS;
}
XrResult XRAPI_CALL beginSession(XrSession value, const XrSessionBeginInfo*) {
  session(value)->running = true; return XR_SUCCESS;
}
XrResult XRAPI_CALL endSession(XrSession value) { session(value)->running = false; return XR_SUCCESS; }
XrResult XRAPI_CALL formats(XrSession, uint32_t capacity, uint32_t* count, int64_t* output) {
  char selected[2]{};
  const bool bgra = GetEnvironmentVariableA("GK3HD_XR_TEST_BGRA", selected, sizeof(selected)) == 1 && selected[0] == '1';
  return enumerate(capacity, count, output,
    std::vector<int64_t>{bgra ? VK_FORMAT_B8G8R8A8_SRGB : VK_FORMAT_R8G8B8A8_SRGB});
}
void freeChain(Chain* state) {
  auto destroy = deviceFunction<PFN_vkDestroyImage>(state->session, "vkDestroyImage");
  auto free = deviceFunction<PFN_vkFreeMemory>(state->session, "vkFreeMemory");
  for (unsigned i = 0; i < 2; ++i) {
    if (state->images[i]) destroy(state->session->graphics.device, state->images[i], nullptr);
    if (state->memory[i]) free(state->session->graphics.device, state->memory[i], nullptr);
  }
}
// OpenXR promises COLOR_ATTACHMENT_OPTIMAL on image acquisition. Establish it
// on the runtime's bound queue before exposing these real GPU images.
VkResult submitGpu(Session* host, const std::function<void(VkCommandBuffer)>& record) {
  const auto device = host->graphics.device;
  auto createPool = deviceFunction<PFN_vkCreateCommandPool>(host, "vkCreateCommandPool");
  auto destroyPool = deviceFunction<PFN_vkDestroyCommandPool>(host, "vkDestroyCommandPool");
  auto allocate = deviceFunction<PFN_vkAllocateCommandBuffers>(host, "vkAllocateCommandBuffers");
  auto begin = deviceFunction<PFN_vkBeginCommandBuffer>(host, "vkBeginCommandBuffer");
  auto end = deviceFunction<PFN_vkEndCommandBuffer>(host, "vkEndCommandBuffer");
  auto getQueue = deviceFunction<PFN_vkGetDeviceQueue>(host, "vkGetDeviceQueue");
  auto submit = deviceFunction<PFN_vkQueueSubmit>(host, "vkQueueSubmit");
  auto createFence = deviceFunction<PFN_vkCreateFence>(host, "vkCreateFence");
  auto destroyFence = deviceFunction<PFN_vkDestroyFence>(host, "vkDestroyFence");
  auto wait = deviceFunction<PFN_vkWaitForFences>(host, "vkWaitForFences");
  VkCommandPoolCreateInfo poolInfo{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
  poolInfo.queueFamilyIndex = host->graphics.queueFamilyIndex;
  VkCommandPool pool = VK_NULL_HANDLE;
  VkResult result = createPool(device, &poolInfo, nullptr, &pool);
  if (result != VK_SUCCESS) return result;
  VkCommandBufferAllocateInfo allocation{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
  allocation.commandPool = pool; allocation.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
  allocation.commandBufferCount = 1;
  VkCommandBuffer commands = VK_NULL_HANDLE;
  VkFence fence = VK_NULL_HANDLE;
  result = allocate(device, &allocation, &commands);
  if (result == VK_SUCCESS) {
    VkCommandBufferBeginInfo info{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    result = begin(commands, &info);
  }
  if (result == VK_SUCCESS) {
    record(commands);
    result = end(commands);
  }
  if (result == VK_SUCCESS) {
    VkFenceCreateInfo info{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO}; result = createFence(device, &info, nullptr, &fence);
  }
  if (result == VK_SUCCESS) {
    VkQueue queue = VK_NULL_HANDLE;
    getQueue(device, host->graphics.queueFamilyIndex, host->graphics.queueIndex, &queue);
    VkSubmitInfo info{VK_STRUCTURE_TYPE_SUBMIT_INFO}; info.commandBufferCount = 1; info.pCommandBuffers = &commands;
    result = submit(queue, 1, &info, fence);
    if (result == VK_SUCCESS) result = wait(device, 1, &fence, VK_TRUE, UINT64_MAX);
  }
  if (fence) destroyFence(device, fence, nullptr);
  destroyPool(device, pool, nullptr); return result;
}
VkResult initializeImages(Chain* state) {
  auto barrier = deviceFunction<PFN_vkCmdPipelineBarrier>(state->session, "vkCmdPipelineBarrier");
  return submitGpu(state->session, [state, barrier](VkCommandBuffer commands) {
    std::array<VkImageMemoryBarrier, 2> transitions{};
    for (unsigned i = 0; i < 2; ++i) {
      auto& image = transitions[i]; image.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
      image.oldLayout = VK_IMAGE_LAYOUT_UNDEFINED; image.newLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
      image.dstAccessMask = VK_ACCESS_COLOR_ATTACHMENT_READ_BIT | VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
      image.srcQueueFamilyIndex = image.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
      image.image = state->images[i]; image.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    }
    barrier(commands, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
            0, 0, nullptr, 0, nullptr, 2, transitions.data());
  });
}

// Diagnostic readback exists only in this test runtime, never the player DLL.
// A fence is intentionally used here so tests can verify actual eye pixels,
// including encoded mid-tones and separate left/right content.
bool snapshot(Chain* state, std::vector<uint8_t>& output) {
  auto* host = state->session;
  const auto device = host->graphics.device;
  auto create = deviceFunction<PFN_vkCreateBuffer>(host, "vkCreateBuffer");
  auto destroy = deviceFunction<PFN_vkDestroyBuffer>(host, "vkDestroyBuffer");
  auto requirements = deviceFunction<PFN_vkGetBufferMemoryRequirements>(host, "vkGetBufferMemoryRequirements");
  auto allocate = deviceFunction<PFN_vkAllocateMemory>(host, "vkAllocateMemory");
  auto free = deviceFunction<PFN_vkFreeMemory>(host, "vkFreeMemory");
  auto bind = deviceFunction<PFN_vkBindBufferMemory>(host, "vkBindBufferMemory");
  auto map = deviceFunction<PFN_vkMapMemory>(host, "vkMapMemory");
  auto unmap = deviceFunction<PFN_vkUnmapMemory>(host, "vkUnmapMemory");
  auto barrier = deviceFunction<PFN_vkCmdPipelineBarrier>(host, "vkCmdPipelineBarrier");
  auto copy = deviceFunction<PFN_vkCmdCopyImageToBuffer>(host, "vkCmdCopyImageToBuffer");
  auto props = reinterpret_cast<PFN_vkGetPhysicalDeviceMemoryProperties>(host->instanceResolve(host->graphics.instance, "vkGetPhysicalDeviceMemoryProperties"));
  VkPhysicalDeviceMemoryProperties properties{}; props(host->graphics.physicalDevice, &properties);
  const VkDeviceSize size = VkDeviceSize(state->width) * state->height * 4;
  VkBufferCreateInfo info{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO}; info.size = size;
  info.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT;
  VkBuffer buffer = VK_NULL_HANDLE;
  if (create(device, &info, nullptr, &buffer) != VK_SUCCESS) return false;
  VkMemoryRequirements required{}; requirements(device, buffer, &required);
  VkMemoryAllocateInfo allocation{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO}; allocation.allocationSize = required.size;
  bool found = false;
  const auto flags = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
  for (uint32_t i = 0; i < properties.memoryTypeCount; ++i)
    if ((required.memoryTypeBits & (1u << i)) && (properties.memoryTypes[i].propertyFlags & flags) == flags) {
      allocation.memoryTypeIndex = i; found = true; break;
    }
  VkDeviceMemory memory = VK_NULL_HANDLE;
  bool okay = found && allocate(device, &allocation, nullptr, &memory) == VK_SUCCESS &&
    bind(device, buffer, memory, 0) == VK_SUCCESS;
  if (okay) okay = submitGpu(host, [=](VkCommandBuffer commands) {
    VkImageMemoryBarrier transition{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER};
    transition.srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT | VK_ACCESS_TRANSFER_WRITE_BIT;
    transition.dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
    transition.oldLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
    transition.newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    transition.srcQueueFamilyIndex = transition.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    transition.image = state->images[state->next ^ 1];
    transition.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    barrier(commands, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT | VK_PIPELINE_STAGE_TRANSFER_BIT,
      VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 0, nullptr, 1, &transition);
    VkBufferImageCopy region{}; region.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
    region.imageExtent = {state->width, state->height, 1};
    copy(commands, transition.image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, buffer, 1, &region);
    transition.srcAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
    transition.dstAccessMask = VK_ACCESS_COLOR_ATTACHMENT_READ_BIT | VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
    transition.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    transition.newLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
    barrier(commands, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
      0, 0, nullptr, 0, nullptr, 1, &transition);
    VkBufferMemoryBarrier visibility{VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER};
    visibility.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT; visibility.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
    visibility.srcQueueFamilyIndex = visibility.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    visibility.buffer = buffer; visibility.size = size;
    barrier(commands, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT,
      0, 0, nullptr, 1, &visibility, 0, nullptr);
  }) == VK_SUCCESS;
  void* mapped = nullptr;
  if (okay) okay = map(device, memory, 0, size, 0, &mapped) == VK_SUCCESS;
  if (okay) {
    output.resize(static_cast<size_t>(size));
    std::memcpy(output.data(), mapped, output.size());
    unmap(device, memory);
    // Keep the diagnostic API in RGBA byte order for either tested runtime.
    if (state->format == VK_FORMAT_B8G8R8A8_SRGB)
      for (size_t i = 0; i < output.size(); i += 4) std::swap(output[i], output[i + 2]);
  }
  destroy(device, buffer, nullptr);
  if (memory) free(device, memory, nullptr);
  return okay;
}
XrResult XRAPI_CALL createChain(XrSession value, const XrSwapchainCreateInfo* info, XrSwapchain* output) {
  auto* host = session(value); eventSession = host;
  if (info->sampleCount != 1 || info->arraySize != 1 || info->mipCount != 1 ||
      (info->format != VK_FORMAT_R8G8B8A8_SRGB && info->format != VK_FORMAT_B8G8R8A8_SRGB))
    return XR_ERROR_SWAPCHAIN_FORMAT_UNSUPPORTED;
  auto state = std::make_unique<Chain>(); state->session = host;
  state->width = info->width; state->height = info->height;
  state->format = static_cast<VkFormat>(info->format);
  auto create = deviceFunction<PFN_vkCreateImage>(host, "vkCreateImage");
  auto requirements = deviceFunction<PFN_vkGetImageMemoryRequirements>(host, "vkGetImageMemoryRequirements");
  auto allocate = deviceFunction<PFN_vkAllocateMemory>(host, "vkAllocateMemory");
  auto bind = deviceFunction<PFN_vkBindImageMemory>(host, "vkBindImageMemory");
  auto memoryProperties = reinterpret_cast<PFN_vkGetPhysicalDeviceMemoryProperties>(host->instanceResolve(host->graphics.instance, "vkGetPhysicalDeviceMemoryProperties"));
  VkPhysicalDeviceMemoryProperties memory{}; memoryProperties(host->graphics.physicalDevice, &memory);
  for (unsigned i = 0; i < 2; ++i) {
    VkImageCreateInfo image{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
    image.imageType = VK_IMAGE_TYPE_2D; image.format = static_cast<VkFormat>(info->format);
    image.extent = {info->width, info->height, 1}; image.mipLevels = image.arrayLayers = 1;
    image.samples = VK_SAMPLE_COUNT_1_BIT; image.tiling = VK_IMAGE_TILING_OPTIMAL;
    image.usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
    if (create(host->graphics.device, &image, nullptr, &state->images[i]) != VK_SUCCESS) {
      freeChain(state.get()); return XR_ERROR_RUNTIME_FAILURE;
    }
    VkMemoryRequirements required{}; requirements(host->graphics.device, state->images[i], &required);
    VkMemoryAllocateInfo allocation{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO}; allocation.allocationSize = required.size;
    bool found = false;
    for (unsigned index = 0; index < memory.memoryTypeCount; ++index)
      if (required.memoryTypeBits & (1u << index)) { allocation.memoryTypeIndex = index; found = true; break; }
    if (!found || allocate(host->graphics.device, &allocation, nullptr, &state->memory[i]) != VK_SUCCESS ||
        bind(host->graphics.device, state->images[i], state->memory[i], 0) != VK_SUCCESS) {
      freeChain(state.get()); return XR_ERROR_RUNTIME_FAILURE;
    }
  }
  if (initializeImages(state.get()) != VK_SUCCESS) {
    freeChain(state.get()); return XR_ERROR_RUNTIME_FAILURE;
  }
  *output = reinterpret_cast<XrSwapchain>(state.release()); return XR_SUCCESS;
}
XrResult XRAPI_CALL destroyChain(XrSwapchain value) { freeChain(chain(value)); delete chain(value); return XR_SUCCESS; }
XrResult XRAPI_CALL images(XrSwapchain value, uint32_t capacity, uint32_t* count, XrSwapchainImageBaseHeader* output) {
  *count = 2;
  if (!capacity) return XR_SUCCESS;
  if (capacity < 2) return XR_ERROR_SIZE_INSUFFICIENT;
  auto* typed = reinterpret_cast<XrSwapchainImageVulkanKHR*>(output);
  for (unsigned i = 0; i < 2; ++i) typed[i].image = chain(value)->images[i];
  return XR_SUCCESS;
}
XrResult XRAPI_CALL waitFrame(XrSession value, const XrFrameWaitInfo*, XrFrameState* output) {
  auto* state = session(value);
  if (GetCurrentThreadId() == state->ownerThread) ++state->mainWaits;
  output->predictedDisplayTime = state->time += 11111111;
  output->predictedDisplayPeriod = 11111111; output->shouldRender = XR_TRUE; return XR_SUCCESS;
}
XrResult XRAPI_CALL beginFrame(XrSession value, const XrFrameBeginInfo*) {
  if (session(value)->frame) return XR_ERROR_CALL_ORDER_INVALID;
  session(value)->frame = true; ++session(value)->frameSequence; return XR_SUCCESS;
}
XrResult XRAPI_CALL locate(XrSession value, const XrViewLocateInfo*, XrViewState* state,
                          uint32_t capacity, uint32_t* count, XrView* output) {
  *count = 2;
  if (capacity < 2) return XR_ERROR_SIZE_INSUFFICIENT;
  state->viewStateFlags = XR_VIEW_STATE_POSITION_VALID_BIT | XR_VIEW_STATE_ORIENTATION_VALID_BIT |
                         XR_VIEW_STATE_POSITION_TRACKED_BIT | XR_VIEW_STATE_ORIENTATION_TRACKED_BIT;
  // Deterministic motion is an opt-in development fixture, not tracking
  // synthesized by the player renderer. The default remains a fixed pose.
  char motion[2]{};
  const bool moving = GetEnvironmentVariableA("GK3HD_XR_TEST_MOTION", motion, sizeof(motion)) == 1 &&
                      motion[0] == '1';
  const float phase = moving ? float(session(value)->frameSequence - 1) * .12f : 0.f;
  const float yaw = .3f * std::sin(phase);
  const XrVector3f center{headOffset.x + .15f * std::sin(phase),
                        headOffset.y + .05f * std::sin(phase * .7f), headOffset.z};
  for (unsigned i = 0; i < 2; ++i) {
    const float eye = i ? .032f : -.032f;
    output[i].pose = {{0, std::sin(yaw / 2), 0, std::cos(yaw / 2)},
      {center.x + eye * std::cos(yaw), center.y, center.z - eye * std::sin(yaw)}};
    output[i].fov = {-0.8f, 0.8f, 0.8f, -0.8f};
  }
  return XR_SUCCESS;
}
XrResult XRAPI_CALL acquire(XrSwapchain value, const XrSwapchainImageAcquireInfo*, uint32_t* output) {
  auto* state = chain(value);
  if (state->acquired || !state->session->running || !state->session->frame)
    return XR_ERROR_CALL_ORDER_INVALID;
  state->acquired = true; state->waited = false; *output = state->next; return XR_SUCCESS;
}
XrResult XRAPI_CALL wait(XrSwapchain value, const XrSwapchainImageWaitInfo*) {
  if (!chain(value)->acquired) return XR_ERROR_CALL_ORDER_INVALID;
  chain(value)->waited = true; return XR_SUCCESS;
}
XrResult XRAPI_CALL release(XrSwapchain value, const XrSwapchainImageReleaseInfo*) {
  auto* state = chain(value);
  if (!state->acquired || !state->waited) return XR_ERROR_CALL_ORDER_INVALID;
  state->acquired = state->waited = false;
  state->releasedFrame = state->session->frameSequence; state->next ^= 1; return XR_SUCCESS;
}
// Optional one-shot evidence capture for live engine tests. All readback and
// file IO remain in this test runtime, never in the distributed renderer.
bool captureSubmitted(Session* state) {
  if (state->captureWritten) return true;
  wchar_t path[32768]{};
  const DWORD length = GetEnvironmentVariableW(L"GK3HD_XR_TEST_CAPTURE", path, 32768);
  if (!length) return true;
  if (length >= 32768 || state->submittedFrames < 32) return length < 32768;
  const HANDLE file = CreateFileW(path, GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS,
                                FILE_ATTRIBUTE_NORMAL, nullptr);
  if (file == INVALID_HANDLE_VALUE) return false;
  const std::array<uint32_t, 5> header{0x58334B47, 1, state->submittedFrames,
    static_cast<uint32_t>(state->submitted[0].size()),
    static_cast<uint32_t>(state->submitted[1].size())};
  auto write = [&](const void* data, DWORD size) {
    DWORD written = 0;
    return WriteFile(file, data, size, &written, nullptr) && written == size;
  };
  const bool okay = write(header.data(), static_cast<DWORD>(sizeof(header))) &&
    write(state->submitted[0].data(), header[3]) && write(state->submitted[1].data(), header[4]);
  CloseHandle(file);
  state->captureWritten = okay;
  return okay;
}
bool capturePanel(Session* state) {
  if (state->panelCaptureWritten) return true;
  wchar_t path[32768]{};
  const DWORD length = GetEnvironmentVariableW(L"GK3HD_XR_TEST_PANEL_CAPTURE", path, 32768);
  if (!length) return true;
  if (length >= 32768 || state->panelFrames < 32) return length < 32768;
  const HANDLE file = CreateFileW(path, GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS,
                                FILE_ATTRIBUTE_NORMAL, nullptr);
  if (file == INVALID_HANDLE_VALUE) return false;
  const std::array<uint32_t, 5> header{0x50334B47, 1, state->panelFrames,
                                     state->panelWidth, state->panelHeight};
  auto write = [&](const void* data, DWORD size) {
    DWORD written = 0;
    return WriteFile(file, data, size, &written, nullptr) && written == size;
  };
  const bool okay = write(header.data(), static_cast<DWORD>(sizeof(header))) &&
    write(state->panelPixels.data(), static_cast<DWORD>(state->panelPixels.size()));
  CloseHandle(file);
  state->panelCaptureWritten = okay;
  return okay;
}
XrResult XRAPI_CALL endFrame(XrSession value, const XrFrameEndInfo* info) {
  auto* state = session(value);
  if (!state->frame) return XR_ERROR_CALL_ORDER_INVALID;
  state->frame = false;
  state->lastLayerCount = info->layerCount;
  state->keyboardVisible = false;
  state->subtitleVisible = false;
  if (!info->layerCount) return XR_SUCCESS;
  if (info->layerCount > 4 || !info->layers) return XR_ERROR_LAYER_INVALID;
  bool world = false, panel = false;
  std::vector<XrSwapchain> quads;
  auto validImage = [&](const XrSwapchainSubImage& sub) {
    if (!sub.swapchain) return false;
    const auto* image = chain(sub.swapchain);
    return image->session == state && !image->acquired && image->releasedFrame == state->frameSequence &&
      !sub.imageArrayIndex && !sub.imageRect.offset.x && !sub.imageRect.offset.y &&
      sub.imageRect.extent.width == int32_t(image->width) && sub.imageRect.extent.height == int32_t(image->height);
  };
  for (uint32_t index = 0; index < info->layerCount; ++index) {
    if (!info->layers[index]) return XR_ERROR_LAYER_INVALID;
    if (info->layers[index]->type == XR_TYPE_COMPOSITION_LAYER_PROJECTION) {
      const auto* layer = reinterpret_cast<const XrCompositionLayerProjection*>(info->layers[index]);
      if (world || panel || layer->viewCount != 2 || !layer->views ||
          layer->views[0].subImage.swapchain == layer->views[1].subImage.swapchain)
        return XR_ERROR_LAYER_INVALID;
      for (unsigned eye = 0; eye < 2; ++eye) {
        if (!validImage(layer->views[eye].subImage) ||
            (!state->skipPixelReadback &&
             !snapshot(chain(layer->views[eye].subImage.swapchain), state->submitted[eye])))
          return XR_ERROR_RUNTIME_FAILURE;
      }
      world = true;
    } else if (info->layers[index]->type == XR_TYPE_COMPOSITION_LAYER_QUAD) {
      const auto* layer = reinterpret_cast<const XrCompositionLayerQuad*>(info->layers[index]);
      if (state->subtitleVisible || (layer->layerFlags & ~XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT) || layer->eyeVisibility != XR_EYE_VISIBILITY_BOTH ||
          !layer->space || !validImage(layer->subImage)) return XR_ERROR_LAYER_INVALID;
      const auto& q = layer->pose.orientation;
      const auto& p = layer->pose.position;
      const std::array<float, 9> geometry{q.x, q.y, q.z, q.w, p.x, p.y, p.z, layer->size.width, layer->size.height};
      for (float coordinate : geometry) if (!std::isfinite(coordinate)) return XR_ERROR_POSE_INVALID;
      if (std::abs(q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w-1.f) > .0001f ||
          layer->size.width <= 0 || layer->size.height <= 0) return XR_ERROR_POSE_INVALID;
      const auto* image = chain(layer->subImage.swapchain);
      // A second quad may be an opaque keyboard or transparent HUD/captions.
      // OpenXR imposes no keyboard-specific extent or opacity. Keep the actual
      // image lifecycle/pose checks and require independent swapchain content.
      if (std::find(quads.begin(),quads.end(),layer->subImage.swapchain)!=quads.end())
        return XR_ERROR_LAYER_INVALID;
      const bool third = state->keyboardVisible;
      auto& pixels = third ? state->subtitlePixels : panel ? state->keyboardPixels : state->panelPixels;
      if (!state->skipPixelReadback && !snapshot(chain(layer->subImage.swapchain), pixels))
        return XR_ERROR_RUNTIME_FAILURE;
      if (third) {
        state->subtitleVisible = true;
        state->subtitleGeometry = geometry;
      } else if (panel) {
        state->keyboardVisible = true;
        state->keyboardGeometry = geometry;
        ++state->keyboardFrames;
      } else {
        state->panelFlags = layer->layerFlags;
        state->panelWidth = image->width; state->panelHeight = image->height;
        state->panelGeometry = geometry;
      }
      panel = true;
      quads.push_back(layer->subImage.swapchain);
    } else return XR_ERROR_LAYER_INVALID;
  }
  if (panel) ++state->panelFrames;
  if (world) ++state->submittedFrames;
  return state->skipPixelReadback || ((!world || captureSubmitted(state)) && (!panel || capturePanel(state)))
    ? XR_SUCCESS : XR_ERROR_RUNTIME_FAILURE;
}
XrResult XRAPI_CALL syncActions(XrSession value, const XrActionsSyncInfo* info) {
  ++session(value)->syncCalls;
  if (inputFeed) inputFeed->sample();
  return gk3hd::vr::testinput::sync(value, info);
}
XrResult XRAPI_CALL resolve(XrInstance, const char* name, PFN_xrVoidFunction* output) {
  *output = nullptr;
#define BIND(api, implementation) if (!std::strcmp(name, #api)) { \
  *output = reinterpret_cast<PFN_xrVoidFunction>(static_cast<PFN_##api>(implementation)); return XR_SUCCESS; }
  BIND(xrGetInstanceProcAddr, resolve)
  BIND(xrEnumerateInstanceExtensionProperties, extensions)
  BIND(xrCreateInstance, createInstance)
  BIND(xrDestroyInstance, destroyInstance)
  BIND(xrGetInstanceProperties, properties)
  BIND(xrGetSystem, getSystem)
  BIND(xrEnumerateViewConfigurationViews, views)
  BIND(xrEnumerateEnvironmentBlendModes, blends)
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
  BIND(xrSyncActions, syncActions)
#undef BIND
  return gk3hd::vr::testinput::resolve(XR_NULL_HANDLE, name, output);
}
} // namespace

extern "C" __declspec(dllexport) uint32_t XRAPI_CALL Gk3hdXrTestInput(
    uint32_t hand, uint32_t flags, uint32_t buttons, float x, float y) {
  if (hand >= 2 || (flags & ~3u) || (buttons & ~31u)) return 0;
  auto& state = gk3hd::vr::testinput::model.hands[hand];
  state.active = (flags & 1) != 0; state.valid = (flags & 2) != 0;
  state.buttons = buttons; state.stick = {x, y};
  state.pose.position.x = hand ? .3f : -.3f;
  return 1;
}

extern "C" __declspec(dllexport) XrResult XRAPI_CALL xrNegotiateLoaderRuntimeInterface(
    const XrNegotiateLoaderInfo* loader, XrNegotiateRuntimeRequest* request) {
  if (loader->minInterfaceVersion > 1 || loader->maxInterfaceVersion < 1) return XR_ERROR_INITIALIZATION_FAILED;
  request->runtimeInterfaceVersion = 1;
  request->runtimeApiVersion = XR_MAKE_VERSION(1, 0, 0);
  request->getInstanceProcAddr = resolve; return XR_SUCCESS;
}

extern "C" __declspec(dllexport) uint32_t __stdcall Gk3hdXrTestAim(
    uint32_t hand, float x, float y, float z) {
  if (hand >= 2 || !std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) return 0;
  gk3hd::vr::testinput::model.hands[hand].pose = {{0, 0, 0, 1}, {x, y, z}};
  return 1;
}

extern "C" __declspec(dllexport) uint32_t __stdcall Gk3hdXrTestHead(float x, float y, float z) {
  if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z) ||
      std::abs(x) > 10 || std::abs(y) > 10 || std::abs(z) > 10) return 0;
  headOffset = {x, y, z};
  return 1;
}

extern "C" __declspec(dllexport) uint32_t __stdcall Gk3hdXrTestPixels(
    unsigned eye, uint8_t* output, uint32_t bytes) {
  if (!eventSession || eventSession->skipPixelReadback || eye >= 2 || !output ||
      bytes != eventSession->submitted[eye].size()) return 0;
  std::memcpy(output, eventSession->submitted[eye].data(), bytes);
  return eventSession->submittedFrames;
}

extern "C" __declspec(dllexport) uint32_t __stdcall Gk3hdXrTestPanel(
    uint8_t* output, uint32_t bytes, float* geometry) {
  if (!eventSession || eventSession->skipPixelReadback || !output || !geometry ||
      bytes != eventSession->panelPixels.size()) return 0;
  std::memcpy(output, eventSession->panelPixels.data(), bytes);
  std::memcpy(geometry, eventSession->panelGeometry.data(), sizeof(eventSession->panelGeometry));
  return eventSession->panelFrames;
}
extern "C" __declspec(dllexport) uint32_t __stdcall Gk3hdXrTestKeyboard(
    uint8_t* output, uint32_t bytes, float* geometry) {
  if (!eventSession || !eventSession->keyboardVisible || eventSession->skipPixelReadback || !output || !geometry ||
      bytes != eventSession->keyboardPixels.size()) return 0;
  std::memcpy(output, eventSession->keyboardPixels.data(), bytes);
  std::memcpy(geometry, eventSession->keyboardGeometry.data(), sizeof(eventSession->keyboardGeometry));
  return eventSession->keyboardFrames;
}
extern "C" __declspec(dllexport) uint32_t __stdcall Gk3hdXrTestSubtitle(
    uint8_t* output, uint32_t bytes, float* geometry) {
  if (!eventSession || !eventSession->subtitleVisible || eventSession->skipPixelReadback || !output || !geometry ||
      bytes != eventSession->subtitlePixels.size()) return 0;
  std::memcpy(output,eventSession->subtitlePixels.data(),bytes);
  std::memcpy(geometry,eventSession->subtitleGeometry.data(),sizeof(eventSession->subtitleGeometry));
  return 1;
}
extern "C" __declspec(dllexport) uint32_t WINAPI Gk3hdXrTestFrameStats(uint64_t* output, uint32_t count) {
  if (!eventSession || !output || (count != 5 && count != 6)) return 0;
  const uint64_t values[]{eventSession->frameSequence, eventSession->syncCalls,
    eventSession->submittedFrames, eventSession->panelFrames, eventSession->lastLayerCount, eventSession->panelFlags};
  std::memcpy(output, values, count*sizeof(uint64_t));
  return 1;
}
// Safe to read while the exclusive loading helper is submitting frames. Other
// test counters/pixels are deliberately observed only after its final join.
extern "C" __declspec(dllexport) uint32_t WINAPI Gk3hdXrTestMainWaits() {
  return eventSession ? eventSession->mainWaits.load() : 0;
}
