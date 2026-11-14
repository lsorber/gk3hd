#include "input.h"

#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <string>

int main() {
  XrInstance instance = XR_NULL_HANDLE;
  int exitCode = 1;
  try {
    XrInstanceCreateInfo info{XR_TYPE_INSTANCE_CREATE_INFO};
    std::copy_n("GK3HD input probe", 18, info.applicationInfo.applicationName);
    info.applicationInfo.apiVersion = XR_MAKE_VERSION(1, 0, 0);
    const auto result = xrCreateInstance(&info, &instance);
    if (result != XR_SUCCESS)
      throw std::runtime_error("create input probe instance failed (OpenXR " + std::to_string(result) + ")");
    {
      gk3hd::vr::Actions actions(xrGetInstanceProcAddr);
      actions.initialize(instance);
    }
    std::cout << "Runtime accepts core controller action types, hand paths, and suggested bindings. No headset input or gameplay tested.\n";
    exitCode = 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; }
  if (instance) xrDestroyInstance(instance);
  return exitCode;
}
