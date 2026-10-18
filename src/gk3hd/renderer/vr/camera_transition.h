#pragma once

#include "engine_camera.h"

namespace gk3hd::vr {

// Only authored camera changes cause a blink. HMD motion never enters this
// detector, and projection/FOV changes do not masquerade as camera rotation.
// Predicted OpenXR display time, not frame count or sleeps, controls recovery.
class CameraTransition {
public:
  float sample(const EngineCamera& camera, float unitsPerMeter, XrTime time) {
    if (time <= 0) throw std::invalid_argument("invalid predicted display time");
    if (previousTime_ && (time < previousTime_ || cut(camera, unitsPerMeter)))
      started_ = time;
    previous_ = camera;
    previousTime_ = time;
    if (!started_) return 1.f;
    const double elapsed = double(time) - double(started_);
    if (elapsed >= Duration) { started_ = 0; return 1.f; }
    const float progress = static_cast<float>(elapsed / Duration);
    return progress * progress * (3.f - 2.f * progress);
  }

private:
  static constexpr double Duration = 200000000.; // 200 ms black-to-visible.
  EngineCamera previous_{};
  XrTime previousTime_ = 0, started_ = 0;

  bool cut(const EngineCamera& camera, float unitsPerMeter) const {
    const double x = double(camera.position.x) - previous_.position.x;
    const double y = double(camera.position.y) - previous_.position.y;
    const double z = double(camera.position.z) - previous_.position.z;
    const double distance = .5 * unitsPerMeter;
    if (x*x + y*y + z*z > distance*distance) return true;
    const auto& a = previous_.worldToCamera;
    const auto& b = camera.worldToCamera;
    for (unsigned axis = 0; axis < 3; ++axis) {
      double dot = 0, aa = 0, bb = 0;
      for (unsigned row = 0; row < 3; ++row) {
        const double av = a[axis + 3*row], bv = b[axis + 3*row];
        dot += av*bv; aa += av*av; bb += bv*bv;
      }
      if (dot < .9659258263 * std::sqrt(aa*bb)) return true; // 15 degrees.
    }
    return false;
  }
};

} // namespace gk3hd::vr
