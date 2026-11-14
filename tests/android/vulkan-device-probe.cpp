// Bounded Android system-driver diagnostic. No game, surfaces or submissions.
#include <vulkan/vulkan.h>
#include <unistd.h>

#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

template <typename T> static T typed(VkStructureType type) {
  T value{};
  value.sType = type;
  return value;
}

static void check(bool value, const char* message) {
  if (!value) {
    std::fprintf(stderr, "%s\n", message);
    std::exit(2);
  }
}

struct Group {
  const char* name;
  VkBaseOutStructure* node;
  std::size_t offset;
  unsigned count;
  VkBool32 wanted[3];

  VkBool32* bits() const {
    return reinterpret_cast<VkBool32*>(reinterpret_cast<char*>(node) + offset);
  }
};

int main(int argc, char** argv) {
  check(argc == 2 && std::strlen(argv[1]) == 32 &&
            std::strspn(argv[1], "0123456789abcdef") == 32,
        "Explicit observation token required");
  auto app = typed<VkApplicationInfo>(VK_STRUCTURE_TYPE_APPLICATION_INFO);
  app.pApplicationName = "GK3HD native device diagnostic";
  app.apiVersion = VK_API_VERSION_1_1;
  auto instanceInfo = typed<VkInstanceCreateInfo>(VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO);
  instanceInfo.pApplicationInfo = &app;
  VkInstance instance = VK_NULL_HANDLE;
  check(vkCreateInstance(&instanceInfo, nullptr, &instance) == VK_SUCCESS, "Create instance failed");
  uint32_t count = 0;
  check(vkEnumeratePhysicalDevices(instance, &count, nullptr) == VK_SUCCESS && count == 1,
        "One physical GPU required for this diagnostic");
  VkPhysicalDevice physical = VK_NULL_HANDLE;
  check(vkEnumeratePhysicalDevices(instance, &count, &physical) == VK_SUCCESS, "Enumerate GPU failed");
  vkGetPhysicalDeviceQueueFamilyProperties(physical, &count, nullptr);
  check(count > 0 && count <= 32, "Queue-family bound exceeded");
  std::vector<VkQueueFamilyProperties> queues(count);
  vkGetPhysicalDeviceQueueFamilyProperties(physical, &count, queues.data());
  uint32_t family = 0;
  while (family < count && !(queues[family].queueFlags & VK_QUEUE_GRAPHICS_BIT)) ++family;
  check(family < count, "No graphics queue");

  const char* extensions[] = {
      "VK_EXT_4444_formats", "VK_EXT_conservative_rasterization", "VK_EXT_custom_border_color",
      "VK_EXT_depth_clip_enable", "VK_EXT_extended_dynamic_state", "VK_EXT_host_query_reset",
      "VK_EXT_robustness2", "VK_EXT_shader_demote_to_helper_invocation",
      "VK_EXT_shader_stencil_export", "VK_EXT_shader_viewport_index_layer",
      "VK_EXT_transform_feedback", "VK_EXT_vertex_attribute_divisor", "VK_KHR_create_renderpass2",
      "VK_KHR_depth_stencil_resolve", "VK_KHR_draw_indirect_count", "VK_KHR_driver_properties",
      "VK_KHR_image_format_list", "VK_KHR_sampler_mirror_clamp_to_edge", "VK_KHR_swapchain",
      "VK_KHR_timeline_semaphore"};
  auto formats = typed<VkPhysicalDevice4444FormatsFeaturesEXT>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_4444_FORMATS_FEATURES_EXT);
  auto border = typed<VkPhysicalDeviceCustomBorderColorFeaturesEXT>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_CUSTOM_BORDER_COLOR_FEATURES_EXT);
  auto clip = typed<VkPhysicalDeviceDepthClipEnableFeaturesEXT>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DEPTH_CLIP_ENABLE_FEATURES_EXT);
  auto dynamic = typed<VkPhysicalDeviceExtendedDynamicStateFeaturesEXT>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTENDED_DYNAMIC_STATE_FEATURES_EXT);
  auto query = typed<VkPhysicalDeviceHostQueryResetFeatures>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_HOST_QUERY_RESET_FEATURES);
  auto robust = typed<VkPhysicalDeviceRobustness2FeaturesEXT>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ROBUSTNESS_2_FEATURES_EXT);
  auto demote = typed<VkPhysicalDeviceShaderDemoteToHelperInvocationFeaturesEXT>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_DEMOTE_TO_HELPER_INVOCATION_FEATURES_EXT);
  auto feedback = typed<VkPhysicalDeviceTransformFeedbackFeaturesEXT>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_TRANSFORM_FEEDBACK_FEATURES_EXT);
  auto divisor = typed<VkPhysicalDeviceVertexAttributeDivisorFeaturesEXT>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VERTEX_ATTRIBUTE_DIVISOR_FEATURES_EXT);
  auto timeline = typed<VkPhysicalDeviceTimelineSemaphoreFeatures>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_TIMELINE_SEMAPHORE_FEATURES);
  // This captured client-emulated feature is newer than the pinned NDK headers.
  struct PlacedFeatures {
    VkStructureType sType;
    void* pNext;
    VkBool32 memoryMapPlaced, memoryMapRangePlaced, memoryUnmapReserve;
  };
  auto placed = typed<PlacedFeatures>(static_cast<VkStructureType>(1000272000));
#define GROUP(name, value, type, field, n, a, b, c) \
  {name, reinterpret_cast<VkBaseOutStructure*>(&value), offsetof(type, field), n, {a, b, c}}
  Group groups[] = {
      GROUP("4444", formats, VkPhysicalDevice4444FormatsFeaturesEXT, formatA4R4G4B4, 2, 1, 1, 0),
      GROUP("border", border, VkPhysicalDeviceCustomBorderColorFeaturesEXT, customBorderColors, 2, 1, 1, 0),
      GROUP("depth_clip", clip, VkPhysicalDeviceDepthClipEnableFeaturesEXT, depthClipEnable, 1, 1, 0, 0),
      GROUP("dynamic_state", dynamic, VkPhysicalDeviceExtendedDynamicStateFeaturesEXT, extendedDynamicState, 1, 1, 0, 0),
      GROUP("query_reset", query, VkPhysicalDeviceHostQueryResetFeatures, hostQueryReset, 1, 1, 0, 0),
      GROUP("robustness2", robust, VkPhysicalDeviceRobustness2FeaturesEXT, robustBufferAccess2, 3, 1, 0, 1),
      GROUP("demote", demote, VkPhysicalDeviceShaderDemoteToHelperInvocationFeaturesEXT, shaderDemoteToHelperInvocation, 1, 1, 0, 0),
      GROUP("feedback", feedback, VkPhysicalDeviceTransformFeedbackFeaturesEXT, transformFeedback, 2, 0, 0, 0),
      GROUP("divisor", divisor, VkPhysicalDeviceVertexAttributeDivisorFeaturesEXT, vertexAttributeInstanceRateDivisor, 2, 1, 1, 0),
      GROUP("timeline", timeline, VkPhysicalDeviceTimelineSemaphoreFeatures, timelineSemaphore, 1, 0, 0, 0),
      GROUP("client_emulated_placed", placed, PlacedFeatures, memoryMapPlaced, 3, 1, 0, 1)};
#undef GROUP
  auto features = typed<VkPhysicalDeviceFeatures2>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2);
  VkBaseOutStructure* head = nullptr;
  for (auto& group : groups) { group.node->pNext = head; head = group.node; }
  features.pNext = head;
  auto getFeatures = reinterpret_cast<PFN_vkGetPhysicalDeviceFeatures2>(
      vkGetInstanceProcAddr(instance, "vkGetPhysicalDeviceFeatures2"));
  check(getFeatures != nullptr, "Features2 unavailable");
  getFeatures(physical, &features);
  std::printf("{\"token\":\"%s\",\"pid\":%d,\"feature_groups\":[", argv[1], getpid());
  bool first = true;
  for (auto& group : groups) {
    std::printf("%s{\"name\":\"%s\",\"supported\":[", first ? "" : ",", group.name);
    for (unsigned i = 0; i < group.count; ++i) std::printf("%s%u", i ? "," : "", group.bits()[i]);
    std::printf("],\"requested\":[");
    for (unsigned i = 0; i < group.count; ++i) {
      std::printf("%s%u", i ? "," : "", group.wanted[i]);
      group.bits()[i] = group.wanted[i];
    }
    std::printf("]}"); first = false;
  }
  VkPhysicalDeviceFeatures required{};
#define REQUIRE(field) required.field = VK_TRUE
  REQUIRE(robustBufferAccess); REQUIRE(fullDrawIndexUint32); REQUIRE(imageCubeArray);
  REQUIRE(independentBlend); REQUIRE(geometryShader); REQUIRE(sampleRateShading);
  REQUIRE(multiDrawIndirect); REQUIRE(drawIndirectFirstInstance); REQUIRE(depthClamp);
  REQUIRE(depthBiasClamp); REQUIRE(fillModeNonSolid); REQUIRE(depthBounds);
  REQUIRE(multiViewport); REQUIRE(samplerAnisotropy); REQUIRE(textureCompressionBC);
  REQUIRE(occlusionQueryPrecise); REQUIRE(pipelineStatisticsQuery);
  REQUIRE(vertexPipelineStoresAndAtomics); REQUIRE(shaderStorageImageWriteWithoutFormat);
  REQUIRE(shaderClipDistance); REQUIRE(shaderCullDistance);
#undef REQUIRE
  float priority = 1;
  auto queue = typed<VkDeviceQueueCreateInfo>(VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO);
  queue.queueFamilyIndex = family; queue.queueCount = 1; queue.pQueuePriorities = &priority;
  auto create = typed<VkDeviceCreateInfo>(VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO);
  create.queueCreateInfoCount = 1; create.pQueueCreateInfos = &queue;
  create.pEnabledFeatures = &required;
  create.enabledExtensionCount = sizeof(extensions) / sizeof(extensions[0]);
  create.ppEnabledExtensionNames = extensions;
  std::printf("],\"device_cases\":[");
  auto attempt = [&](const char* name, const void* next) {
    create.pNext = next;
    VkDevice device = VK_NULL_HANDLE;
    VkResult result = vkCreateDevice(physical, &create, nullptr, &device);
    std::printf("%s{\"name\":\"%s\",\"result\":%d}", first ? "" : ",", name, result);
    std::fflush(stdout); first = false;
    if (result == VK_SUCCESS) vkDestroyDevice(device, nullptr);
  };
  first = true;
  attempt("core_and_extensions", nullptr);
  for (auto& group : groups) { group.node->pNext = nullptr; attempt(group.name, group.node); }
  head = nullptr;
  for (auto& group : groups) { group.node->pNext = head; head = group.node; }
  attempt("all_groups", head);
  head = nullptr;
  for (auto& group : groups) {
    if (group.node == reinterpret_cast<VkBaseOutStructure*>(&placed)) continue;
    group.node->pNext = head; head = group.node;
  }
  attempt("without_client_emulated_placed", head);
  vkDestroyInstance(instance, nullptr);
  std::printf("],\"instance_retired\":true}\n");
  return 0;
}
