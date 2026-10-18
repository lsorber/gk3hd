#pragma once

#include "camera.h"
#include <cstddef>
#include <cstdint>
#include <vector>

namespace gk3hd::vr {

struct ClipPlane {
  float x, y, z, distance;
};

// Verified camera layout for the normalized GK3 engine. The host resolves the
// object through a verified build profile, not a guessed process address.
// These are 32-bit engine fields even when math tests run on a 64-bit host.
struct EngineCamera {
  uint32_t vtable;
  XrVector3f target;
  float yaw, pitch, orbitDistance;
  XrVector3f position;
  std::array<float, 12> worldToCamera;
  int32_t width, height;
  float fieldOfView;
  std::array<ClipPlane, 6> planes;
  float aspect, depthScale, inverseDepthScale;
};
static_assert(offsetof(EngineCamera, position) == 0x1c);
static_assert(offsetof(EngineCamera, worldToCamera) == 0x28);
static_assert(offsetof(EngineCamera, planes) == 0x64);
static_assert(sizeof(EngineCamera) == 0xd0);

// Same ordering as the six floats used by GK3's CPU projection routine.
// +Z is forward in the engine, screen Y goes down, depth lies in [0, 1].
struct ScreenProjection {
  float depthA, depthB, centerX, centerY, focalX, focalY;
};

struct EyeCamera {
  EngineCamera camera;
  ScreenProjection projection;
};

// GK3's geometry and actor pickers consume world-space segment endpoints,
// not a direction vector. The origin is also needed when comparing hits.
struct EngineAimRay {
  XrVector3f origin, nearPoint, farPoint;
};
static_assert(sizeof(EngineAimRay) == 36);

// Use the SAME authored basis, recentered tracking origin and physical scale
// as the eyes. This is independent of desktop pixels and either eye's FOV.
EngineAimRay engineAimRay(const EngineCamera& base, XrPosef relativeAim,
                         float unitsPerMeter, float nearMeters, float farMeters);

// relativeEye is expressed in recentered OpenXR space, including the runtime's
// actual eye separation. Only this rendering snapshot changes: the authored
// camera/target and simulation must be restored before updates or game picking.
// GK3's original matrix has different scales on its three rows. Strip those
// scales before applying tracking, then use one coherent per-eye frustum for
// clipping AND projection. GK3's hardcoded polygon outcodes expect |X,Y|<=Z,
// so the eye matrix incorporates frustum scale/shear, not just a rigid pose.
// ScreenProjection then maps this canonical clip space into the eye image.
EyeCamera engineEyeCamera(const EngineCamera& base, XrPosef relativeEye,
                          XrFovf fov, uint32_t width, uint32_t height,
                          float unitsPerMeter, float nearMeters, float farMeters);

XrVector3f engineCameraPoint(const EngineCamera& camera, XrVector3f world);
// Input must already have passed the clipping stage, as in the engine.
std::array<float, 4> engineScreenPoint(const ScreenProjection& projection,
                                     XrVector3f point);

bool validRayHit(const EngineAimRay& ray, XrVector3f hit, float unitsPerMeter);
struct ReticleVertex {
  float x, y, z, rhw;
  uint32_t color;
};
static_assert(sizeof(ReticleVertex) == 20);
// One controller-facing world ring, independently projected for each eye.
// Its depth is the native scene depth, not an always-on-top desktop cursor.
std::vector<ReticleVertex> engineReticle(const EyeCamera& eye, const EngineAimRay& ray,
                                       XrVector3f hit, float unitsPerMeter);
// A thin stereo beam, clipped to the native eye frustum and depth-tested by the
// host. A null hit ends at 1.5 metres, not the scene's potentially huge far plane.
// An ineligible ray is never passed here. This does not invent a selectable hit.
std::vector<ReticleVertex> engineBeam(const EyeCamera& eye, const EngineAimRay& ray,
                                    const XrVector3f* hit, float unitsPerMeter);

} // namespace gk3hd::vr
