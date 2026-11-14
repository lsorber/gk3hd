#pragma once

#include "engine_camera.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <optional>

namespace gk3hd::vr {
namespace shared_camera {
struct Vector {
  double x, y, z;
  Vector operator+(Vector b) const { return {x+b.x, y+b.y, z+b.z}; }
  Vector operator-(Vector b) const { return {x-b.x, y-b.y, z-b.z}; }
  Vector operator*(double b) const { return {x*b, y*b, z*b}; }
};
inline double dot(Vector a, Vector b) { return a.x*b.x+a.y*b.y+a.z*b.z; }
inline Vector cross(Vector a, Vector b) {
  return {a.y*b.z-a.z*b.y, a.z*b.x-a.x*b.z, a.x*b.y-a.y*b.x};
}
inline Vector unit(Vector a) {
  const auto length = std::sqrt(dot(a, a));
  if (!std::isfinite(length) || length < 1e-9)
    throw std::invalid_argument("invalid shared-view axis");
  return a*(1/length);
}
inline Vector column(const EyeCamera& eye, unsigned index) {
  const auto& m = eye.camera.worldToCamera;
  return {m[index], m[index+3], m[index+6]};
}
// The engine's view matrix already includes the asymmetric frustum shear.
// Invert that full matrix, not a guessed rigid camera rotation.
inline Vector unproject(const EyeCamera& eye, Vector point) {
  const auto& m = eye.camera.worldToCamera;
  const auto a = column(eye, 0), b = column(eye, 1), c = column(eye, 2);
  const auto determinant = dot(a, cross(b, c));
  if (!std::isfinite(determinant) || std::abs(determinant) < 1e-9)
    throw std::invalid_argument("singular shared-view input");
  point = point-Vector{m[9], m[10], m[11]};
  return (cross(b, c)*point.x+cross(c, a)*point.y+cross(a, b)*point.z)*(1/determinant);
}
inline std::array<Vector, 8> corners(const EyeCamera& eye) {
  std::array<Vector, 8> result{};
  unsigned index = 0;
  const double nearDistance = -eye.camera.planes[0].distance;
  const double farDistance = eye.camera.planes[1].distance;
  if (!(nearDistance > 0 && farDistance > nearDistance))
    throw std::invalid_argument("invalid shared-view clipping range");
  for (double z : {nearDistance, farDistance})
    for (double x : {-1., 1.})
      for (double y : {-1., 1.}) result[index++] = unproject(eye, {x*z, y*z, z});
  return result;
}
} // namespace shared_camera

// One finite native culling/projection envelope containing both eye frusta.
// It does not replace either submitted eye camera. Unsupported geometry (for
// example a combined frustum extending behind its center) uses two native draws.
inline std::optional<EyeCamera> conservativeStereoCamera(const std::array<EyeCamera, 2>& eyes) {
  using namespace shared_camera;
  try {
    const auto forward = unit(unit(column(eyes[0], 2))+unit(column(eyes[1], 2)));
    const auto r0 = column(eyes[0], 0), r1 = column(eyes[1], 0);
    const auto tentative = unit(unit(r0-forward*dot(r0, forward))+
                                unit(r1-forward*dot(r1, forward)));
    const auto up = unit(cross(forward, tentative)), right = unit(cross(up, forward));
    const auto center = (unproject(eyes[0], {})+unproject(eyes[1], {}))*.5;
    double lowX = std::numeric_limits<double>::infinity(), lowY = lowX, nearDistance = lowX;
    double highX = -lowX, highY = -lowX, farDistance = 0;
    for (const auto& eye : eyes) for (const auto point : corners(eye)) {
      const auto offset = point-center;
      const double x = dot(offset, right), y = dot(offset, up), z = dot(offset, forward);
      if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z) || z <= 1e-6)
        return std::nullopt;
      lowX = std::min(lowX, x/z); highX = std::max(highX, x/z);
      lowY = std::min(lowY, y/z); highY = std::max(highY, y/z);
      nearDistance = std::min(nearDistance, z); farDistance = std::max(farDistance, z);
    }
    auto base = eyes[0].camera;
    base.position = {float(center.x), float(center.y), float(center.z)};
    base.worldToCamera = {float(right.x), float(up.x), float(forward.x),
                         float(right.y), float(up.y), float(forward.y),
                         float(right.z), float(up.z), float(forward.z),
                         float(-dot(center, right)), float(-dot(center, up)), float(-dot(center, forward))};
    const XrFovf fov{float(std::atan(lowX-1e-5)), float(std::atan(highX+1e-5)),
                     float(std::atan(highY+1e-5)), float(std::atan(lowY-1e-5))};
    return engineEyeCamera(base, {{0,0,0,1},{0,0,0}}, fov,
        uint32_t(std::max(eyes[0].camera.width, eyes[1].camera.width)),
        uint32_t(std::max(eyes[0].camera.height, eyes[1].camera.height)),
        1.f, float(nearDistance*(1-1e-5)), float(farDistance*(1+1e-5)));
  } catch (const std::invalid_argument&) { return std::nullopt; }
}
} // namespace gk3hd::vr
