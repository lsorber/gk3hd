#include "performance.h"
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <type_traits>
#include <vector>

using namespace gk3hd::standalone::openxr;
namespace {
unsigned checks = 0, resolves = 0;
bool nullFunction = false;
XrResult resolveResult = XR_SUCCESS;
std::array<XrResult, 2> requestResults{XR_SUCCESS, XR_SUCCESS};
std::vector<XrPerfSettingsDomainEXT> requests;
template<class T> T handle(std::uintptr_t value) {
  if constexpr (std::is_pointer_v<T>) return reinterpret_cast<T>(value);
  else return static_cast<T>(value);
}
const auto instance = handle<XrInstance>(1);
const auto session = handle<XrSession>(2);
void check(bool value) {
  ++checks;
  if (!value) throw std::runtime_error("Native performance preference mismatch");
}
XrResult XRAPI_CALL request(XrSession owner, XrPerfSettingsDomainEXT domain,
                            XrPerfSettingsLevelEXT level) {
  check(owner == session);
  check(level == XR_PERF_SETTINGS_LEVEL_SUSTAINED_HIGH_EXT);
  check(domain == XR_PERF_SETTINGS_DOMAIN_CPU_EXT || domain == XR_PERF_SETTINGS_DOMAIN_GPU_EXT);
  requests.push_back(domain);
  return requestResults[domain == XR_PERF_SETTINGS_DOMAIN_CPU_EXT ? 0 : 1];
}
XrResult XRAPI_CALL resolve(XrInstance owner, const char* name, PFN_xrVoidFunction* output) {
  check(owner == instance);
  check(std::strcmp(name, "xrPerfSettingsSetPerformanceLevelEXT") == 0);
  ++resolves;
  *output = nullFunction ? nullptr : reinterpret_cast<PFN_xrVoidFunction>(request);
  return resolveResult;
}
void reset() {
  requests.clear(); resolves = 0; nullFunction = false;
  resolveResult = XR_SUCCESS; requestResults.fill(XR_SUCCESS);
}
}
int main() {
  try {
    PerformancePreference absent;
    check(absent.apply(resolve, instance, session, false));
    check(resolves == 0 && requests.empty());
    check(absent.results[0] == XR_ERROR_EXTENSION_NOT_PRESENT);

    reset(); PerformancePreference normal;
    check(normal.apply(resolve, instance, session, true));
    check(requests == std::vector<XrPerfSettingsDomainEXT>{XR_PERF_SETTINGS_DOMAIN_CPU_EXT,
                                                        XR_PERF_SETTINGS_DOMAIN_GPU_EXT});
    check(normal.results == requestResults);
    // A later thermal/runtime reduction is authoritative. Repeated frames or
    // caller retries cannot reassert the original hint in this session.
    requestResults.fill(XR_ERROR_RUNTIME_FAILURE);
    for (unsigned i = 0; i < 20; ++i) check(!normal.apply(resolve, instance, session, true));
    check(resolves == 1 && requests.size() == 2);

    reset(); requestResults = {XR_ERROR_RUNTIME_FAILURE, XR_SUCCESS};
    PerformancePreference partial;
    check(partial.apply(resolve, instance, session, true));
    check(partial.results == requestResults && requests.size() == 2);

    reset(); resolveResult = XR_ERROR_FUNCTION_UNSUPPORTED;
    PerformancePreference unavailable;
    check(unavailable.apply(resolve, instance, session, true));
    check(unavailable.results[0] == resolveResult && requests.empty());
    check(!unavailable.apply(resolve, instance, session, true));

    reset(); nullFunction = true; PerformancePreference missing;
    check(missing.apply(resolve, instance, session, true));
    check(missing.results[0] == XR_ERROR_FUNCTION_UNSUPPORTED && requests.empty());

    reset(); PerformancePreference invalid;
    check(invalid.apply(resolve, instance, XR_NULL_HANDLE, true));
    check(invalid.results[0] == XR_ERROR_HANDLE_INVALID && resolves == 0 && requests.empty());
    std::cout << checks << " native performance capability, fallback, error and one-shot checks passed\n";
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
