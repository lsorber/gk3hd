// Internal binary adapter probe for isolated live-engine experiments, not a
// player-facing command. Input: one EngineCamera. Output: one EyeCamera.
#include "engine_camera.h"
#include <iostream>
#include <string>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

int main(int argc, char** argv) {
  try {
    if (argc != 3 && argc != 7)
      throw std::invalid_argument("usage: camera-probe UNITS_PER_METER EYE_X_METERS [LEFT RIGHT UP DOWN]");
#ifdef _WIN32
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
#endif
    gk3hd::vr::EngineCamera base{};
    if (!std::cin.read(reinterpret_cast<char*>(&base), sizeof(base)))
      throw std::runtime_error("expected a complete engine camera snapshot");
    const auto& m = base.worldToCamera;
    const auto length = [](float x, float y, float z) { return std::sqrt(x*x+y*y+z*z); };
    const float sx = length(m[0], m[3], m[6]), sy = length(m[1], m[4], m[7]);
    const float sz = length(m[2], m[5], m[8]);
    // Reproduce the source game's FOV/clip distances for the offline stereo gate.
    // A live headset uses its runtime-provided per-eye FOV instead.
    const float horizontal = std::atan(sz/sx), vertical = std::atan(sz/sy);
    const float units = std::stof(argv[1]);
    const XrPosef eye{{0, 0, 0, 1}, {std::stof(argv[2]), 0, 0}};
    const XrFovf fov = argc == 7
        ? XrFovf{std::stof(argv[3]), std::stof(argv[4]), std::stof(argv[5]), std::stof(argv[6])}
        : XrFovf{-horizontal, horizontal, vertical, -vertical};
    const auto result = gk3hd::vr::engineEyeCamera(base, eye, fov,
        static_cast<uint32_t>(base.width), static_cast<uint32_t>(base.height), units,
        -base.planes[0].distance/sz/units, base.planes[1].distance/sz/units);
    std::cout.write(reinterpret_cast<const char*>(&result), sizeof(result));
    return std::cout ? 0 : 1;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n'; return 1;
  }
}
