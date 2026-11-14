#pragma once
#include <cmath>
#include <openxr/openxr.h>

namespace gk3hd::standalone::openxr {
// OpenXR poses are rigid transforms. Do not infer head orientation by averaging
// canted eyes: locate VIEW in LOCAL, then express each eye relative to that
// head.
inline XrPosef relativeView(const XrPosef &head, const XrPosef &eye) {
  const XrQuaternionf a = {-head.orientation.x, -head.orientation.y,
                           -head.orientation.z, head.orientation.w};
  const auto &b = eye.orientation;
  XrPosef out{};
  out.orientation = {a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
                     a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
                     a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w,
                     a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z};
  XrVector3f v = {eye.position.x - head.position.x,
                  eye.position.y - head.position.y,
                  eye.position.z - head.position.z};
  const XrVector3f t = {2 * (a.y * v.z - a.z * v.y),
                        2 * (a.z * v.x - a.x * v.z),
                        2 * (a.x * v.y - a.y * v.x)};
  out.position = {v.x + a.w * t.x + a.y * t.z - a.z * t.y,
                  v.y + a.w * t.y + a.z * t.x - a.x * t.z,
                  v.z + a.w * t.z + a.x * t.y - a.y * t.x};
  return out;
}
inline bool locatedPose(const XrSpaceLocation &value) {
  constexpr auto required = XR_SPACE_LOCATION_ORIENTATION_VALID_BIT |
                            XR_SPACE_LOCATION_POSITION_VALID_BIT;
  if ((value.locationFlags & required) != required)
    return false;
  const auto &p = value.pose.position;
  const auto &q = value.pose.orientation;
  const float norm = q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w;
  return std::isfinite(p.x) && std::isfinite(p.y) && std::isfinite(p.z) &&
         std::isfinite(norm) && std::abs(norm - 1) < .001f;
}
} // namespace gk3hd::standalone::openxr
