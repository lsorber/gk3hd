#include "runtime_discovery.h"
#include <iostream>
using namespace gk3hd::standalone::openxr;
namespace {
XrResult result = XR_SUCCESS;
bool android = true, gles = true, refresh = false, performance = false, overflow = false, changed = false;
XrResult XRAPI_PTR enumerate(const char *, uint32_t capacity, uint32_t *count,
                            XrExtensionProperties *properties) {
  if (XR_FAILED(result)) return result;
  *count = overflow ? 1025 : uint32_t(android) + uint32_t(gles) + uint32_t(refresh) + uint32_t(performance);
  if (!capacity) return XR_SUCCESS;
  if (changed) { *count = capacity + 1; return XR_ERROR_SIZE_INSUFFICIENT; }
  uint32_t index = 0;
  constexpr char androidName[] = "XR_KHR_android_create_instance";
  constexpr char glesName[] = "XR_KHR_opengl_es_enable";
  constexpr char refreshName[] = XR_FB_DISPLAY_REFRESH_RATE_EXTENSION_NAME;
  constexpr char performanceName[] = XR_EXT_PERFORMANCE_SETTINGS_EXTENSION_NAME;
  if (android) std::memcpy(properties[index++].extensionName, androidName, sizeof(androidName));
  if (gles) std::memcpy(properties[index++].extensionName, glesName, sizeof(glesName));
  if (refresh) std::memcpy(properties[index++].extensionName, refreshName, sizeof(refreshName));
  if (performance) std::memcpy(properties[index++].extensionName, performanceName, sizeof(performanceName));
  return XR_SUCCESS;
}
void check(bool value) { if (!value) throw std::runtime_error("Runtime discovery mismatch"); }
void rejects() {
  bool rejected = false;
  try { discoverRuntime(enumerate); } catch (const std::runtime_error &) { rejected = true; }
  check(rejected);
}
}
int main() {
  try {
    result = XR_ERROR_RUNTIME_UNAVAILABLE;
    check(discoverRuntime(enumerate).support == RuntimeSupport::Absent);
    result = XR_ERROR_INITIALIZATION_FAILED; rejects();
    result = XR_ERROR_RUNTIME_FAILURE; rejects();
    result = XR_SUCCESS;
    for (bool a : {false, true}) for (bool g : {false, true})
        for (bool r : {false, true}) for (bool p : {false, true}) {
      android = a; gles = g; refresh = r; performance = p;
      const auto found = discoverRuntime(enumerate);
      check(found.support == (a && g ? RuntimeSupport::Supported : RuntimeSupport::Unsupported));
      check(found.displayRefreshRate == r);
      check(found.performanceSettings == p);
    }
    overflow = true; rejects(); overflow = false;
    changed = true; rejects();
    std::cout << "Native discovery: absence, required/optional capabilities, service failures and bounded enumeration passed\n";
    return 0;
  } catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
}
