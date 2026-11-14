#include "runtime.h"
#include <exception>
#include <iostream>

int main() {
  static_assert(sizeof(void*) == 4, "GK3's XR component must be built for x86");
  try {
    gk3hd::vr::Runtime runtime;
    runtime.initialize();
    std::cout << "OpenXR runtime: " << runtime.name() << '\n';
    for (const auto& view : runtime.configuration())
      std::cout << "Eye target: " << view.recommendedImageRectWidth << 'x'
                << view.recommendedImageRectHeight << '\n';
    std::cout << "Runtime and headset discovery passed; graphics/session rendering not tested.\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "OpenXR unavailable: " << error.what() << '\n';
    return 1;
  }
}
