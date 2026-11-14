#pragma once
#include <openxr/openxr.h>
#include <cmath>
#include <utility>
#include <vector>

namespace gk3hd::standalone::openxr {
struct DisplayRates {
  // Optional diagnostics must not turn a working core runtime into a failure.
  XrResult result = XR_ERROR_EXTENSION_NOT_PRESENT;
  std::vector<float> supported;
  float current = 0;
};

inline DisplayRates displayRates(PFN_xrGetInstanceProcAddr resolve,
                                 XrInstance instance, XrSession session,
                                 bool enabled) {
  DisplayRates out;
  if (!enabled) return out;
  PFN_xrVoidFunction enumerate = nullptr, get = nullptr;
  out.result = resolve(instance, "xrEnumerateDisplayRefreshRatesFB", &enumerate);
  if (XR_FAILED(out.result)) return out;
  out.result = resolve(instance, "xrGetDisplayRefreshRateFB", &get);
  if (XR_FAILED(out.result)) return out;
  if (!enumerate || !get) {
    out.result = XR_ERROR_FUNCTION_UNSUPPORTED;
    return out;
  }
  const auto rates = reinterpret_cast<PFN_xrEnumerateDisplayRefreshRatesFB>(enumerate);
  uint32_t count = 0;
  out.result = rates(session, 0, &count, nullptr);
  if (XR_FAILED(out.result)) return out;
  if (!count || count > 32) {
    out.result = XR_ERROR_VALIDATION_FAILURE;
    return out;
  }
  std::vector<float> values(count);
  const auto capacity = count;
  out.result = rates(session, capacity, &count, values.data());
  if (XR_FAILED(out.result)) return out;
  if (count != capacity) {
    out.result = XR_ERROR_VALIDATION_FAILURE;
    return out;
  }
  float previous = 0;
  for (const auto rate : values) {
    if (!std::isfinite(rate) || rate <= previous) {
      out.result = XR_ERROR_VALIDATION_FAILURE;
      return out;
    }
    previous = rate;
  }
  float current = 0;
  out.result = reinterpret_cast<PFN_xrGetDisplayRefreshRateFB>(get)(session, &current);
  if (XR_FAILED(out.result)) return out;
  if (!std::isfinite(current) || current <= 0) {
    out.result = XR_ERROR_VALIDATION_FAILURE;
    return out;
  }
  out.supported = std::move(values);
  out.current = current;
  return out;
}

struct DisplayPreference {
  bool attempted = false;
  DisplayRates rates;
  float requested = 0;
  XrResult result = XR_ERROR_EXTENSION_NOT_PRESENT;

  // Apply once when the app can present a focused frame. A mode inherited
  // from the launch transition is not this session's display preference.
  bool apply(PFN_xrGetInstanceProcAddr resolve, XrInstance instance,
             XrSession session, bool enabled, bool ready, float preferred = 120) {
    if (attempted || !ready) return false;
    attempted = true;
    rates = displayRates(resolve, instance, session, enabled);
    result = rates.result;
    if (XR_FAILED(result)) return true;
    if (!std::isfinite(preferred) || preferred <= 0) {
      result = XR_ERROR_VALIDATION_FAILURE;
      return true;
    }
    float selected = 0;
    for (const auto rate : rates.supported)
      if (rate <= preferred) selected = rate;
    if (!selected) return true;
    PFN_xrVoidFunction request = nullptr;
    result = resolve(instance, "xrRequestDisplayRefreshRateFB", &request);
    if (XR_FAILED(result)) return true;
    if (!request) {
      result = XR_ERROR_FUNCTION_UNSUPPORTED;
      return true;
    }
    requested = selected;
    result = reinterpret_cast<PFN_xrRequestDisplayRefreshRateFB>(request)(session, selected);
    return true;
  }
};
} // namespace gk3hd::standalone::openxr
