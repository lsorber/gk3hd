#include "engine_camera.h"

#include <algorithm>

namespace gk3hd::vr {
namespace {
float dot(XrVector3f a, XrVector3f b) {
  return a.x*b.x + a.y*b.y + a.z*b.z;
}
XrVector3f cross(XrVector3f a, XrVector3f b) {
  return {a.y*b.z - a.z*b.y, a.z*b.x - a.x*b.z, a.x*b.y - a.y*b.x};
}
XrVector3f unit(XrVector3f v) {
  const float length = std::sqrt(dot(v, v));
  if (!std::isfinite(length) || length < 1e-6f)
    throw std::invalid_argument("invalid engine camera axis");
  return {v.x/length, v.y/length, v.z/length};
}
bool finite(XrVector3f v) {
  return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z);
}
struct EngineBasis {
  XrVector3f right, up, forward;
  XrVector3f world(XrVector3f local) const {
    // This reflection cannot be represented by a tracking quaternion.
    return {right.x*local.x + up.x*local.y - forward.x*local.z,
            right.y*local.x + up.y*local.y - forward.y*local.z,
            right.z*local.x + up.z*local.y - forward.z*local.z};
  }
};
EngineBasis basis(const EngineCamera& camera) {
  const auto& m = camera.worldToCamera;
  const EngineBasis result{unit({m[0], m[3], m[6]}), unit({m[1], m[4], m[7]}),
                           unit({m[2], m[5], m[8]})};
  if (std::abs(dot(result.right, result.up)) > 1e-3f ||
      std::abs(dot(result.right, result.forward)) > 1e-3f ||
      std::abs(dot(result.up, result.forward)) > 1e-3f ||
      dot(cross(result.right, result.up), result.forward) < 0.999f)
    throw std::invalid_argument("engine camera basis is not orthogonal");
  return result;
}
XrVector3f trackedPosition(const EngineCamera& base, const EngineBasis& axes,
                          XrVector3f position, float unitsPerMeter) {
  const auto offset = axes.world(position);
  const XrVector3f result{base.position.x + unitsPerMeter*offset.x,
                         base.position.y + unitsPerMeter*offset.y,
                         base.position.z + unitsPerMeter*offset.z};
  if (!finite(result)) throw std::invalid_argument("tracked engine position overflow");
  return result;
}
ClipPlane plane(XrVector3f normal, float distance) {
  const auto n = unit(normal);
  const float length = std::sqrt(dot(normal, normal));
  return {n.x, n.y, n.z, distance/length};
}
} // namespace

EyeCamera engineEyeCamera(const EngineCamera& base, XrPosef relativeEye,
                          XrFovf fov, uint32_t width, uint32_t height,
                          float unitsPerMeter, float nearMeters, float farMeters) {
  if (!width || !height || width > static_cast<uint32_t>(INT32_MAX) ||
      height > static_cast<uint32_t>(INT32_MAX) || !finite(base.position) ||
      !finite(relativeEye.position) || !std::isfinite(unitsPerMeter) || unitsPerMeter <= 0)
    throw std::invalid_argument("invalid engine eye dimensions or world scale");
  // Share OpenXR projection validation with the native graphics path.
  const auto xrProjection = projection(fov, nearMeters, farMeters);
  const float nearPlane = nearMeters * unitsPerMeter, farPlane = farMeters * unitsPerMeter;
  if (!std::isfinite(nearPlane) || !std::isfinite(farPlane) ||
      !(nearPlane > 0 && farPlane > nearPlane))
    throw std::invalid_argument("engine clipping distance overflow");
  const auto axes = basis(base);
  // GK3's camera space has +Z forward. OpenXR has -Z forward. Converting
  // vectors explicitly avoids treating this reflection as a quaternion.
  const auto orientation = normalized(relativeEye.orientation);
  const auto eyeRight = axes.world(rotate(orientation, {1, 0, 0}));
  const auto eyeUp = axes.world(rotate(orientation, {0, 1, 0}));
  const auto eyeForward = axes.world(rotate(orientation, {0, 0, -1}));
  EyeCamera result{base, {}};
  auto& camera = result.camera;
  camera.position = trackedPosition(base, axes, relativeEye.position, unitsPerMeter);
  const float left = std::tan(fov.angleLeft), rightSlope = std::tan(fov.angleRight);
  const float down = std::tan(fov.angleDown), top = std::tan(fov.angleUp);
  // GK3's polygon outcodes and BSP sphere tests assume -Z <= X,Y <= Z.
  // Put the asymmetric frustum into that canonical space, including its
  // off-axis shear. Updating plane equations alone leaves those fast paths
  // testing a different frustum from the one eventually projected.
  const float sx = 2/(rightSlope-left), tx = -(rightSlope+left)/(rightSlope-left);
  const float sy = 2/(top-down), ty = -(top+down)/(top-down);
  const XrVector3f clipRight{sx*eyeRight.x + tx*eyeForward.x,
                           sx*eyeRight.y + tx*eyeForward.y,
                           sx*eyeRight.z + tx*eyeForward.z};
  const XrVector3f clipUp{sy*eyeUp.x + ty*eyeForward.x,
                        sy*eyeUp.y + ty*eyeForward.y,
                        sy*eyeUp.z + ty*eyeForward.z};
  if (!finite(clipRight) || !finite(clipUp))
    throw std::invalid_argument("engine frustum transform overflow");
  camera.worldToCamera = {clipRight.x, clipUp.x, eyeForward.x,
                         clipRight.y, clipUp.y, eyeForward.y,
                         clipRight.z, clipUp.z, eyeForward.z,
                         -dot(clipRight, camera.position), -dot(clipUp, camera.position),
                         -dot(eyeForward, camera.position)};
  for (const float coefficient : camera.worldToCamera)
    if (!std::isfinite(coefficient))
      throw std::invalid_argument("engine view translation overflow");
  // Plane order is the engine's near, far, left, right, top, bottom order.
  camera.planes = {plane({0, 0, 1}, -nearPlane), plane({0, 0, -1}, farPlane),
                   plane({1, 0, 1}, 0), plane({-1, 0, 1}, 0),
                   plane({0, -1, 1}, 0), plane({0, 1, 1}, 0)};
  camera.width = static_cast<int32_t>(width);
  camera.height = static_cast<int32_t>(height);
  // The BSP sphere test pads X by r*(1+depthScale), Y by
  // r*(aspect+depthScale), and Z by r*depthScale. These values describe
  // culling-space radius bounds, not the headset image's aspect ratio.
  // Bound every sheared side-plane normal conservatively in world space.
  camera.aspect = 1;
  camera.fieldOfView = fov.angleUp - fov.angleDown;
  camera.depthScale = std::max({1.f, std::hypot(sx, tx+1)-1,
      std::hypot(sx, tx-1)-1, std::hypot(sy, ty+1)-1, std::hypot(sy, ty-1)-1});
  if (!std::isfinite(camera.depthScale))
    throw std::invalid_argument("engine culling radius overflow");
  camera.inverseDepthScale = 1/camera.depthScale;
  const float w = static_cast<float>(width), h = static_cast<float>(height);
  result.projection = {-xrProjection[10], xrProjection[14]*unitsPerMeter,
                       w/2, h/2, w/2, h/2};
  return result;
}

EngineAimRay engineAimRay(const EngineCamera& base, XrPosef relativeAim,
                         float unitsPerMeter, float nearMeters, float farMeters) {
  const float nearDistance = nearMeters*unitsPerMeter, farDistance = farMeters*unitsPerMeter;
  if (!finite(base.position) || !finite(relativeAim.position) ||
      !std::isfinite(unitsPerMeter) || unitsPerMeter <= 0 ||
      !std::isfinite(nearDistance) || !std::isfinite(farDistance) ||
      !(nearDistance >= 0 && farDistance > nearDistance))
    throw std::invalid_argument("invalid controller ray scale or range");
  const auto axes = basis(base);
  const auto origin = trackedPosition(base, axes, relativeAim.position, unitsPerMeter);
  const auto direction = unit(axes.world(rotate(relativeAim.orientation, {0, 0, -1})));
  const auto endpoint = [&](float distance) -> XrVector3f {
    const XrVector3f value{origin.x + direction.x*distance,
                           origin.y + direction.y*distance,
                           origin.z + direction.z*distance};
    if (!finite(value)) throw std::invalid_argument("controller ray endpoint overflow");
    return value;
  };
  return {origin, endpoint(nearDistance), endpoint(farDistance)};
}

XrVector3f engineCameraPoint(const EngineCamera& camera, XrVector3f world) {
  const auto& m = camera.worldToCamera;
  return {world.x*m[0] + world.y*m[3] + world.z*m[6] + m[9],
          world.x*m[1] + world.y*m[4] + world.z*m[7] + m[10],
          world.x*m[2] + world.y*m[5] + world.z*m[8] + m[11]};
}

std::array<float, 4> engineScreenPoint(const ScreenProjection& p, XrVector3f v) {
  if (!finite(v) || v.z <= 0)
    throw std::invalid_argument("cannot project an unclipped engine vertex");
  const float reciprocal = 1/v.z;
  return {v.x*p.focalX*reciprocal + p.centerX,
          p.centerY - v.y*p.focalY*reciprocal,
          p.depthA + p.depthB*reciprocal, reciprocal};
}

bool validRayHit(const EngineAimRay& ray, XrVector3f hit, float scale) {
  if (!finite(ray.origin) || !finite(ray.nearPoint) || !finite(ray.farPoint) ||
      !finite(hit) || !std::isfinite(scale) || scale <= 0) return false;
  const XrVector3f d{ray.farPoint.x-ray.nearPoint.x, ray.farPoint.y-ray.nearPoint.y,
                    ray.farPoint.z-ray.nearPoint.z};
  const XrVector3f h{hit.x-ray.nearPoint.x, hit.y-ray.nearPoint.y, hit.z-ray.nearPoint.z};
  const float length2 = dot(d, d);
  if (!std::isfinite(length2) || length2 <= 0) return false;
  const float along = dot(h, d)/length2;
  if (!std::isfinite(along) || along < 0 || along > 1)
    return false;
  const XrVector3f error{h.x-along*d.x, h.y-along*d.y, h.z-along*d.z};
  return dot(error, error) <= scale*scale*.0004f; // 2 cm native hit tolerance.
}

std::vector<ReticleVertex> engineReticle(const EyeCamera& eye, const EngineAimRay& ray,
                                       XrVector3f hit, float scale) {
  if (!validRayHit(ray, hit, scale)) throw std::invalid_argument("invalid reticle hit");
  const auto direction = unit({ray.farPoint.x-ray.nearPoint.x,
                               ray.farPoint.y-ray.nearPoint.y,
                               ray.farPoint.z-ray.nearPoint.z});
  const auto right = unit(cross(direction, std::abs(direction.y) < .9f ?
                               XrVector3f{0, 1, 0} : XrVector3f{1, 0, 0}));
  const auto up = cross(right, direction);
  const XrVector3f distance{hit.x-ray.origin.x, hit.y-ray.origin.y, hit.z-ray.origin.z};
  // Keep a distant selectable target visible without changing its hit point
  // or depth. Close targets use a 14 mm outer radius, distant ones about 0.9
  // degrees full angular diameter. Both eyes still see the same world ring.
  const float outerRadius = std::max(scale*.014f, std::sqrt(dot(distance, distance))*.008f);
  // Bias 1 mm towards the controller to avoid a coplanar surface flicker.
  hit = {hit.x-direction.x*scale*.001f, hit.y-direction.y*scale*.001f,
         hit.z-direction.z*scale*.001f};
  constexpr unsigned segments = 24;
  std::vector<ReticleVertex> result;
  result.reserve(segments*6);
  for (unsigned segment = 0; segment < segments; ++segment) {
    std::array<ReticleVertex, 4> points{};
    for (unsigned corner = 0; corner < 4; ++corner) {
      const float angle = 6.28318530718f*float(segment + corner/2)/float(segments);
      const float radius = outerRadius*(corner%2 ? 1.f : 10.f/14.f);
      const auto point = engineCameraPoint(eye.camera,
        {hit.x+radius*(std::cos(angle)*right.x+std::sin(angle)*up.x),
         hit.y+radius*(std::cos(angle)*right.y+std::sin(angle)*up.y),
         hit.z+radius*(std::cos(angle)*right.z+std::sin(angle)*up.z)});
      if (point.z <= -eye.camera.planes[0].distance ||
          point.z >= eye.camera.planes[1].distance) return {};
      const auto projected = engineScreenPoint(eye.projection, point);
      points[corner] = {projected[0], projected[1], projected[2], projected[3], 0xffffc040u};
    }
    for (unsigned index : {0u, 1u, 2u, 2u, 1u, 3u}) result.push_back(points[index]);
  }
  return result;
}
std::vector<ReticleVertex> engineBeam(const EyeCamera& eye, const EngineAimRay& ray,
                                    const XrVector3f* hit, float scale) {
  if (!validRayHit(ray, hit ? *hit : ray.farPoint, scale))
    throw std::invalid_argument("invalid beam ray or hit");
  const auto direction = unit({ray.farPoint.x-ray.nearPoint.x,
                               ray.farPoint.y-ray.nearPoint.y,
                               ray.farPoint.z-ray.nearPoint.z});
  const XrVector3f end = hit ? *hit : ray.farPoint;
  const XrVector3f offset{end.x-ray.origin.x, end.y-ray.origin.y, end.z-ray.origin.z};
  const float distance = dot(offset, direction);
  const float length = hit ? distance : std::min(distance, 1.5f*scale);
  const float start = .03f*scale; // Do not put a glowing beam inside the hand.
  if (!(length > start)) return {};
  auto a = engineCameraPoint(eye.camera,
    {ray.origin.x+direction.x*start, ray.origin.y+direction.y*start,
     ray.origin.z+direction.z*start});
  auto b = engineCameraPoint(eye.camera,
    {ray.origin.x+direction.x*length, ray.origin.y+direction.y*length,
     ray.origin.z+direction.z*length});
  if (!finite(a) || !finite(b)) throw std::invalid_argument("beam projection overflow");
  const XrVector3f delta{b.x-a.x, b.y-a.y, b.z-a.z};
  float first = 0, last = 1;
  for (const auto& p : eye.camera.planes) {
    const float origin = p.x*a.x+p.y*a.y+p.z*a.z+p.distance;
    const float slope = p.x*delta.x+p.y*delta.y+p.z*delta.z;
    if (!std::isfinite(origin) || !std::isfinite(slope))
      throw std::invalid_argument("invalid beam clipping plane");
    if (slope == 0) { if (origin < 0) return {}; continue; }
    const float boundary = -origin/slope;
    if (slope > 0) first = std::max(first, boundary);
    else last = std::min(last, boundary);
    if (first >= last) return {};
  }
  const auto point = [&](float t) -> XrVector3f {
    return {a.x+delta.x*t, a.y+delta.y*t, a.z+delta.z*t};
  };
  const auto from = engineScreenPoint(eye.projection, point(first));
  const auto to = engineScreenPoint(eye.projection, point(last));
  const float dx = to[0]-from[0], dy = to[1]-from[1], span = std::hypot(dx, dy);
  // A beam viewed exactly along its axis has no screen-space length. Its hit
  // ring remains visible; never divide by zero or synthesize a desktop dot.
  if (!std::isfinite(span) || span < .001f) return {};
  const float nx = -dy/span, ny = dx/span;
  std::array<ReticleVertex, 4> corners{};
  for (unsigned corner = 0; corner < 4; ++corner) {
    const auto& v = corner/2 ? to : from;
    // About 1.5 mm in world space, bounded for readability in each eye target.
    const float radius = std::clamp(scale*.0015f*eye.projection.focalY*v[3], .75f, 3.f);
    const float sign = corner%2 ? 1.f : -1.f;
    corners[corner] = {v[0]+sign*nx*radius, v[1]+sign*ny*radius, v[2], v[3],
                       corner/2 ? 0xb038b8ffu : 0x7038b8ffu};
  }
  std::vector<ReticleVertex> result;
  result.reserve(6);
  for (unsigned index : {0u, 1u, 2u, 2u, 1u, 3u}) result.push_back(corners[index]);
  return result;
}
} // namespace gk3hd::vr
