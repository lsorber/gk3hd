#pragma once
#include <array>
#include <openxr/openxr.h>

namespace gk3hd::standalone::openxr {
struct PerformancePreference {
  bool attempted = false;
  std::array<XrResult, 2> results{
      XR_ERROR_EXTENSION_NOT_PRESENT, XR_ERROR_EXTENSION_NOT_PRESENT};

  // A session-scoped hint, not a forced clock or a per-frame boost. Never
  // reassert it over later runtime/thermal decisions in the same session.
  bool apply(PFN_xrGetInstanceProcAddr resolve, XrInstance instance,
             XrSession session, bool enabled) {
    if (attempted) return false;
    attempted = true;
    if (!enabled) return true;
    if (instance == XR_NULL_HANDLE || session == XR_NULL_HANDLE) {
      results.fill(XR_ERROR_HANDLE_INVALID);
      return true;
    }
    PFN_xrVoidFunction function = nullptr;
    const auto found = resolve(instance, "xrPerfSettingsSetPerformanceLevelEXT", &function);
    if (XR_FAILED(found) || !function) {
      results.fill(XR_FAILED(found) ? found : XR_ERROR_FUNCTION_UNSUPPORTED);
      return true;
    }
    const auto request = reinterpret_cast<PFN_xrPerfSettingsSetPerformanceLevelEXT>(function);
    results[0] = request(session, XR_PERF_SETTINGS_DOMAIN_CPU_EXT,
                         XR_PERF_SETTINGS_LEVEL_SUSTAINED_HIGH_EXT);
    results[1] = request(session, XR_PERF_SETTINGS_DOMAIN_GPU_EXT,
                         XR_PERF_SETTINGS_LEVEL_SUSTAINED_HIGH_EXT);
    return true;
  }
};
} // namespace gk3hd::standalone::openxr
