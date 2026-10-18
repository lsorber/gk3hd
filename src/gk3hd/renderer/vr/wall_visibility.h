#pragma once

#include "scene.h"
#include <algorithm>

namespace gk3hd::vr {

// Distance-driven, binocular fade: do not reveal the other side of a wall or
// stop predicted head tracking. This is not navigation collision/room-scale
// walking. The upright observer, not the lower/pitched desktop camera, is the
// trusted interior segment origin. Navigation collision belongs to the engine;
// this guard covers physical head leaning, not furniture near a neutral eye.
inline float wallVisibility(const SceneV1& scene, const std::array<EyeCamera, 2>& eyes,
                            float nearMeters, const EngineCamera& observer) {
  if (!scene.geometry) return 1.f;
  const auto from = observer.position;
  const XrVector3f head{
    (eyes[0].camera.position.x+eyes[1].camera.position.x)*.5f-from.x,
    (eyes[0].camera.position.y+eyes[1].camera.position.y)*.5f-from.y,
    (eyes[0].camera.position.z+eyes[1].camera.position.z)*.5f-from.z};
  const float displacement = std::sqrt(head.x*head.x+head.y*head.y+head.z*head.z)/scene.unitsPerMeter;
  // IPD and an authored camera passing under a lamp must not black out the
  // whole display. Ease in protection only when the wearer actually leans.
  const float lean = std::clamp((displacement-.02f)/.05f, 0.f, 1.f);
  if (lean == 0) return 1.f;
  const float padding = (nearMeters + .1f) * scene.unitsPerMeter;
  float visibility = 1.f;
  for (const auto& eye : eyes) {
    const auto position = eye.camera.position;
    const XrVector3f delta{position.x-from.x, position.y-from.y, position.z-from.z};
    const float length = std::sqrt(delta.x*delta.x + delta.y*delta.y + delta.z*delta.z);
    if (length < .00001f * scene.unitsPerMeter) continue;
    const float scale = 1.f + padding/length;
    const XrVector3f to{from.x+delta.x*scale, from.y+delta.y*scale, from.z+delta.z*scale};
    XrVector3f hit{};
    const auto result = scene.geometry(scene.context, &from, &to, &hit);
    if (result != 0 && result != 1) throw std::runtime_error("engine head geometry query failed");
    if (!result) continue;
    const EngineAimRay segment{from, from, to};
    if (!validRayHit(segment, hit, scene.unitsPerMeter))
      throw std::runtime_error("engine head geometry query returned an invalid hit");
    const XrVector3f distance{hit.x-from.x, hit.y-from.y, hit.z-from.z};
    const float clearance = (std::sqrt(distance.x*distance.x + distance.y*distance.y +
                                     distance.z*distance.z) - length) / scene.unitsPerMeter;
    // Black before the near plane crosses the surface, fully visible another
    // 10 cm away. Retreat follows the same smooth curve, without a time latch.
    const float progress = std::clamp((clearance-nearMeters)/.1f, 0.f, 1.f);
    visibility = std::min(visibility, progress*progress*(3.f-2.f*progress));
  }
  return 1.f-lean*(1.f-visibility);
}

} // namespace gk3hd::vr
