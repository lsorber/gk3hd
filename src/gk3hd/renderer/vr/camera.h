#pragma once

#include "runtime.h"
#include <cmath>
#include <stdexcept>

namespace gk3hd::vr {

inline XrQuaternionf normalized(XrQuaternionf q) {
  const float length = std::sqrt(q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w);
  if (!std::isfinite(length) || length < 1e-6f)
    throw std::invalid_argument("invalid tracking quaternion");
  return {q.x/length, q.y/length, q.z/length, q.w/length};
}

inline XrQuaternionf multiply(XrQuaternionf a, XrQuaternionf b) {
  return {a.w*b.x + a.x*b.w + a.y*b.z - a.z*b.y,
          a.w*b.y - a.x*b.z + a.y*b.w + a.z*b.x,
          a.w*b.z + a.x*b.y - a.y*b.x + a.z*b.w,
          a.w*b.w - a.x*b.x - a.y*b.y - a.z*b.z};
}

inline XrVector3f rotate(XrQuaternionf orientation, XrVector3f v) {
  const auto q = normalized(orientation);
  const auto result = multiply(multiply(q, {v.x, v.y, v.z, 0}), {-q.x, -q.y, -q.z, q.w});
  return {result.x, result.y, result.z};
}

// Right-handed OpenXR coordinates: +Y up, -Z forward, positions in meters.
// The engine adapter must explicitly convert GK3's basis and world units.
inline XrPosef compose(XrPosef base, XrPosef local) {
  const auto offset = rotate(base.orientation, local.position);
  return {normalized(multiply(normalized(base.orientation), normalized(local.orientation))),
          {base.position.x + offset.x, base.position.y + offset.y, base.position.z + offset.z}};
}

inline XrPosef inverse(XrPosef pose) {
  const auto q = normalized(pose.orientation);
  const XrQuaternionf inverted{-q.x, -q.y, -q.z, q.w};
  return {inverted, rotate(inverted, {-pose.position.x, -pose.position.y, -pose.position.z})};
}

// Column-major right-handed Vulkan projection: depth [0,1], framebuffer Y down.
inline std::array<float, 16> projection(XrFovf fov, float nearPlane, float farPlane) {
  constexpr float halfPi = 1.57079632679489661923f;
  for (float angle : {fov.angleLeft, fov.angleRight, fov.angleDown, fov.angleUp}) {
    if (!std::isfinite(angle) || !(angle > -halfPi && angle < halfPi))
      throw std::invalid_argument("invalid stereo field of view");
  }
  const float left = std::tan(fov.angleLeft), right = std::tan(fov.angleRight);
  const float down = std::tan(fov.angleDown), up = std::tan(fov.angleUp);
  const float width = right - left, height = up - down;
  if (!(width > 0 && height > 0 && nearPlane > 0 && farPlane > nearPlane) ||
      !std::isfinite(width) || !std::isfinite(height) || !std::isfinite(farPlane))
    throw std::invalid_argument("invalid stereo frustum");
  std::array<float, 16> result{};
  result[0] = 2 / width;
  result[5] = -2 / height;
  result[8] = (right + left) / width;
  result[9] = -(up + down) / height;
  result[10] = -farPlane / (farPlane - nearPlane);
  result[11] = -1;
  result[14] = -(farPlane * nearPlane) / (farPlane - nearPlane);
  return result;
}

struct PanelPoint { float x, y; };

// Drawing and picking share this exact panel pose, extent, and logical canvas.
inline bool panelPoint(XrPosef panel, float widthMeters, float heightMeters,
                       XrPosef aim, float canvasWidth, float canvasHeight,
                       PanelPoint& output) {
  if (!(widthMeters > 0 && heightMeters > 0 && canvasWidth > 0 && canvasHeight > 0) ||
      !std::isfinite(widthMeters) || !std::isfinite(heightMeters) ||
      !std::isfinite(canvasWidth) || !std::isfinite(canvasHeight))
    throw std::invalid_argument("invalid interface panel size");
  const auto local = compose(inverse(panel), aim);
  const auto direction = rotate(local.orientation, {0, 0, -1});
  if (direction.z >= -1e-6f || local.position.z <= 0) return false;
  const float distance = -local.position.z / direction.z;
  if (!(distance > 0)) return false;
  const float u = (local.position.x + direction.x * distance) / widthMeters + 0.5f;
  const float v = 0.5f - (local.position.y + direction.y * distance) / heightMeters;
  if (!(u >= 0 && u < 1 && v >= 0 && v < 1)) return false;
  output = {u * canvasWidth, v * canvasHeight};
  return true;
}

} // namespace gk3hd::vr
