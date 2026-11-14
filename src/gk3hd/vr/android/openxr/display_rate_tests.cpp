#include "display_rates.h"
#include <algorithm>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>

using namespace gk3hd::standalone::openxr;
namespace {
unsigned resolves = 0, queries = 0, reads = 0, checks = 0;
unsigned requests = 0;
std::vector<float> supported{72, 80, 90, 120};
float current = 72;
bool nullFunction = false, changed = false;
bool nullRequest = false;
XrResult enumerationResult = XR_SUCCESS, readResult = XR_SUCCESS;
XrResult requestResult = XR_SUCCESS;
float requested = 0;
void check(bool value) {
  ++checks;
  if (!value) throw std::runtime_error("Display refresh behavior mismatch");
}
XrResult XRAPI_CALL rates(XrSession session, uint32_t capacity,
                          uint32_t *count, float *values) {
  check(session != XR_NULL_HANDLE);
  ++queries;
  if (XR_FAILED(enumerationResult)) return enumerationResult;
  *count = uint32_t(supported.size());
  if (!capacity) return XR_SUCCESS;
  check(capacity == supported.size());
  if (changed) { ++*count; return XR_SUCCESS; }
  std::copy(supported.begin(), supported.end(), values);
  return XR_SUCCESS;
}
XrResult XRAPI_CALL get(XrSession session, float *value) {
  check(session != XR_NULL_HANDLE);
  ++reads;
  *value = current;
  return readResult;
}
XrResult XRAPI_CALL request(XrSession session, float value) {
  check(session != XR_NULL_HANDLE);
  check(std::find(supported.begin(), supported.end(), value) != supported.end());
  ++requests;
  requested = value;
  return requestResult;
}
XrResult XRAPI_CALL resolve(XrInstance, const char *name, PFN_xrVoidFunction *out) {
  ++resolves;
  *out = nullptr;
  if (nullFunction) return XR_SUCCESS;
  if (!std::strcmp(name, "xrEnumerateDisplayRefreshRatesFB"))
    *out = reinterpret_cast<PFN_xrVoidFunction>(rates);
  else if (!std::strcmp(name, "xrGetDisplayRefreshRateFB"))
    *out = reinterpret_cast<PFN_xrVoidFunction>(get);
  else if (!std::strcmp(name, "xrRequestDisplayRefreshRateFB")) {
    if (!nullRequest) *out = reinterpret_cast<PFN_xrVoidFunction>(request);
  } else throw std::runtime_error("Unexpected refresh function");
  return XR_SUCCESS;
}
DisplayRates query(bool enabled = true) {
  return displayRates(resolve, (XrInstance)uintptr_t(1), (XrSession)uintptr_t(2), enabled);
}
void invalid() {
  const auto value = query();
  check(XR_FAILED(value.result) && value.supported.empty() && value.current == 0);
}
bool apply(DisplayPreference &preference, bool enabled = true, float preferred = 120, bool ready = true) {
  return preference.apply(resolve, (XrInstance)uintptr_t(1),
                           (XrSession)uintptr_t(2), enabled, ready, preferred);
}
}
int main() {
  try {
    check(query(false).result == XR_ERROR_EXTENSION_NOT_PRESENT);
    check(resolves == 0 && queries == 0 && reads == 0);
    const auto available = query();
    check(available.result == XR_SUCCESS && available.supported == supported);
    check(available.current == 72 && current == 72 && requests == 0);
    nullFunction = true; invalid(); nullFunction = false;
    enumerationResult = XR_ERROR_RUNTIME_FAILURE; invalid(); enumerationResult = XR_SUCCESS;
    readResult = XR_ERROR_SESSION_LOST; invalid(); readResult = XR_SUCCESS;
    changed = true; invalid(); changed = false;
    for (const auto &values : {std::vector<float>{}, std::vector<float>(33, 90),
                              std::vector<float>{90, 72}, std::vector<float>{90, 90},
                              std::vector<float>{0}, std::vector<float>{-90},
                              std::vector<float>{std::numeric_limits<float>::quiet_NaN()},
                              std::vector<float>{std::numeric_limits<float>::infinity()}}) {
      supported = values; invalid();
    }
    supported = {90};
    for (float value : {0.f, -1.f, std::numeric_limits<float>::quiet_NaN(),
                        std::numeric_limits<float>::infinity()}) {
      current = value; invalid();
    }
    current = 90;
    check(query().current == 90);
    supported = {72, 80, 90, 120, 144};
    DisplayPreference preference;
    const auto beforeFocus = resolves;
    check(!apply(preference, true, 120, false) && !preference.attempted && resolves == beforeFocus);
    check(apply(preference) && requested == 120 && requests == 1);
    check(preference.result == XR_SUCCESS && preference.requested == 120);
    // A runtime thermal reduction must remain in force on subsequent frames.
    current = 72;
    const auto previousResolves = resolves;
    check(!apply(preference) && requests == 1 && resolves == previousResolves);
    preference = {};
    supported = {72, 90};
    check(apply(preference) && requested == 90 && requests == 2);
    preference = {};
    current = 90;
    check(apply(preference) && preference.requested == 90 && requests == 3);
    current = 72;
    check(!apply(preference) && requests == 3);
    preference = {};
    check(apply(preference, false) && preference.result == XR_ERROR_EXTENSION_NOT_PRESENT);
    check(requests == 3);
    preference = {};
    current = 72;
    nullRequest = true;
    check(apply(preference) && preference.result == XR_ERROR_FUNCTION_UNSUPPORTED);
    check(requests == 3);
    nullRequest = false;
    preference = {};
    requestResult = XR_ERROR_DISPLAY_REFRESH_RATE_UNSUPPORTED_FB;
    check(apply(preference) && preference.result == requestResult && requests == 4);
    check(!apply(preference) && requests == 4);
    requestResult = XR_SUCCESS;
    preference = {};
    supported = {144};
    check(apply(preference) && preference.requested == 0 && requests == 4);
    preference = {};
    enumerationResult = XR_ERROR_RUNTIME_FAILURE;
    check(apply(preference) && preference.result == enumerationResult && requests == 4);
    enumerationResult = XR_SUCCESS;
    for (float value : {0.f, -1.f, std::numeric_limits<float>::quiet_NaN(),
                        std::numeric_limits<float>::infinity()}) {
      preference = {};
      check(apply(preference, true, value) && preference.result == XR_ERROR_VALIDATION_FAILURE);
      check(requests == 4);
    }
    std::cout << "Display refresh: " << checks
              << " capability, preference, fallback and thermal-yield checks passed\n";
    return 0;
  } catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
}
