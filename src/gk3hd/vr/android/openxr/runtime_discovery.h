#pragma once
#include <openxr/openxr.h>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

namespace gk3hd::standalone::openxr {
enum class RuntimeSupport { Absent = 0, Supported = 1, Unsupported = 2 };
struct RuntimeCapabilities {
  RuntimeSupport support = RuntimeSupport::Unsupported;
  bool displayRefreshRate = false;
  bool performanceSettings = false;
};

// Discovery creates neither an instance nor a session. Only an absent runtime
// permits vendor fallback; service/loader failures must remain visible.
inline RuntimeCapabilities discoverRuntime(PFN_xrEnumerateInstanceExtensionProperties enumerate) {
  auto checked = [](XrResult result) {
    if (XR_FAILED(result))
      throw std::runtime_error("Discover native OpenXR runtime (OpenXR " +
                               std::to_string(result) + ")");
  };
  uint32_t count = 0;
  const auto result = enumerate(nullptr, 0, &count, nullptr);
  if (result == XR_ERROR_RUNTIME_UNAVAILABLE) return {RuntimeSupport::Absent, false};
  checked(result);
  if (count > 1024) throw std::runtime_error("Native extension count out of bounds");
  if (!count) return {};
  std::vector<XrExtensionProperties> properties(count);
  for (auto &property : properties) property.type = XR_TYPE_EXTENSION_PROPERTIES;
  const auto capacity = count;
  checked(enumerate(nullptr, capacity, &count, properties.data()));
  if (count > capacity) throw std::runtime_error("Native extension count changed unexpectedly");
  bool android = false, gles = false, refresh = false, performance = false;
  for (uint32_t i = 0; i < count; ++i) {
    android |= std::strncmp(properties[i].extensionName, "XR_KHR_android_create_instance",
                            XR_MAX_EXTENSION_NAME_SIZE) == 0;
    gles |= std::strncmp(properties[i].extensionName, "XR_KHR_opengl_es_enable",
                         XR_MAX_EXTENSION_NAME_SIZE) == 0;
    refresh |= std::strncmp(properties[i].extensionName, XR_FB_DISPLAY_REFRESH_RATE_EXTENSION_NAME,
                            XR_MAX_EXTENSION_NAME_SIZE) == 0;
    performance |= std::strncmp(properties[i].extensionName, XR_EXT_PERFORMANCE_SETTINGS_EXTENSION_NAME,
                                XR_MAX_EXTENSION_NAME_SIZE) == 0;
  }
  return {android && gles ? RuntimeSupport::Supported : RuntimeSupport::Unsupported, refresh, performance};
}
} // namespace gk3hd::standalone::openxr
