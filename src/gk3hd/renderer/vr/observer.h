#pragma once

#include "scene.h"

namespace gk3hd::vr {

// Original GAB.MOD face UV eye centres, adjusted by CHARACTERS.TXT's shoe
// references/thickness: 69.484 units above the bind-pose floor. Rounded to 0.5
// units (<0.4 mm at 40 units/metre), not an arbitrary real-world eye height.
constexpr float GabrielEyeHeightUnits = 69.5f;

// Rendering/aiming snapshot only: the protagonist, native camera, simulation
// and original walker/camera boundaries are never moved by this adjustment.
inline EngineCamera observerCamera(const SceneV1& scene) {
  auto camera = scene.camera;
  if (!scene.floor) return camera;
  auto from = camera.position, to = camera.position;
  from.y += .25f * scene.unitsPerMeter;
  to.y -= 4.f * scene.unitsPerMeter;
  XrVector3f hit{};
  const auto result = scene.floor(scene.context, &from, &to, &hit);
  if (result == 0) return camera;
  if (result == 1) {
    const EngineAimRay segment{from, from, to};
    if (!validRayHit(segment, hit, scene.unitsPerMeter))
      throw std::runtime_error("engine observer floor query returned an invalid hit");
    camera.position.y = hit.y + GabrielEyeHeightUnits;
  } else if (result != 2) {
    throw std::runtime_error("engine observer floor query returned an invalid hit");
  }
  if (!std::isfinite(camera.position.y))
    throw std::runtime_error("engine observer height overflow");

  // Stand upright. Authored camera pitch/roll must not rotate physical up/down
  // movement or bank the viewer; scripts retain their authored camera above.
  auto& m = camera.worldToCamera;
  const float scales[]{std::sqrt(m[0]*m[0]+m[3]*m[3]+m[6]*m[6]),
                       std::sqrt(m[1]*m[1]+m[4]*m[4]+m[7]*m[7]),
                       std::sqrt(m[2]*m[2]+m[5]*m[5]+m[8]*m[8])};
  for (float scale : scales)
    if (!std::isfinite(scale) || scale < 1e-6f)
      throw std::invalid_argument("invalid observer camera axis");
  float x = m[2], z = m[8], length = std::sqrt(x*x+z*z);
  if (length < 1e-6f) {
    x = -m[6]; z = m[0]; length = std::sqrt(x*x+z*z);
  }
  if (!std::isfinite(length) || length < 1e-6f)
    throw std::invalid_argument("invalid observer camera heading");
  x /= length; z /= length;
  m[0] = z*scales[0]; m[3] = 0; m[6] = -x*scales[0];
  m[1] = 0; m[4] = scales[1]; m[7] = 0;
  m[2] = x*scales[2]; m[5] = 0; m[8] = z*scales[2];
  m[9] = -(z*camera.position.x-x*camera.position.z)*scales[0];
  m[10] = -camera.position.y*scales[1];
  m[11] = -(x*camera.position.x+z*camera.position.z)*scales[2];
  camera.pitch = 0;
  return camera;
}

} // namespace gk3hd::vr
