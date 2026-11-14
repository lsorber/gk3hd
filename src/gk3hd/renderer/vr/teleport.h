#pragma once

#include "scene.h"
#include "observer.h"

namespace gk3hd::vr {

constexpr float TeleportMaximumRangeMeters = 24.f;
constexpr float TeleportHorizontalSpeed = 20.f;
constexpr float TeleportVerticalSpeed = 10.f;
constexpr float TeleportFlightSeconds = 2.4f;

inline float distance(XrVector3f a, XrVector3f b) {
  const float x=a.x-b.x,y=a.y-b.y,z=a.z-b.z;
  return std::sqrt(x*x+y*y+z*z);
}

// One render-thread path shared by picking, both eye overlays and release.
// No process pointers or additional engine ABI are needed for the arc.
struct TeleportPath {
  // Retain short swept segments at the higher launch speed. Queries stop at
  // the first obstacle/floor, so ordinary horizontal throws use few segments.
  std::array<XrVector3f,65> points{};
  uint32_t count=0;
  bool valid=false;
};

// The native designated floor, not selectable props, roofs, desktop pixels or
// Gabriel's walker coordinates. The arc has already checked every segment.
inline bool teleportLanding(const SceneV1& scene, const EngineCamera& observer,
                            XrVector3f hit) {
  if (!scene.floor || !scene.geometry) return false;
  const float units=scene.unitsPerMeter;
  const float dx=hit.x-observer.position.x,dz=hit.z-observer.position.z;
  const float range=std::sqrt(dx*dx+dz*dz)/units;
  if (range<.25f || range>TeleportMaximumRangeMeters ||
      std::abs(hit.y+GabrielEyeHeightUnits-observer.position.y)>units)
    return false;
  const auto clear = [&](XrVector3f from,XrVector3f to) {
    XrVector3f obstacle{};
    const auto result=scene.geometry(scene.context,&from,&to,&obstacle);
    if (result!=0 && result!=1) throw std::runtime_error("teleport clearance query failed");
    if (!result) return true;
    const EngineAimRay segment{from,from,to};
    if (!validRayHit(segment,obstacle,units)) throw std::runtime_error("invalid teleport obstruction");
    return false;
  };
  // Neither a visible ground point behind a wall nor a floor under a table is
  // a valid destination. Do not move the head first and check collision later.
  XrVector3f eye{hit.x,hit.y+GabrielEyeHeightUnits,hit.z};
  XrVector3f feet{hit.x,hit.y+.15f*units,hit.z};
  if (!clear(observer.position,eye) || !clear(feet,eye)) return false;
  for (const auto offset : {std::array<float,2>{-.2f,0}, {.2f,0}, {0,-.2f}, {0,.2f}}) {
    const XrVector3f from{hit.x+offset[0]*units,hit.y+.25f*units,hit.z+offset[1]*units};
    const XrVector3f to{from.x,hit.y-.25f*units,from.z};
    XrVector3f support{};
    if (scene.floor(scene.context,&from,&to,&support)!=1) return false;
    const EngineAimRay segment{from,from,to};
    if (!validRayHit(segment,support,units)) throw std::runtime_error("invalid teleport floor support");
    if (std::abs(support.y-hit.y)>.15f*units) return false;
  }
  return true;
}

inline TeleportPath teleportPath(const SceneV1& scene, const EngineCamera& observer,
                                const EngineAimRay& aim) {
  const float units=scene.unitsPerMeter;
  if (!validRayHit(aim,aim.farPoint,units))
    throw std::invalid_argument("invalid teleport aim");
  TeleportPath path{};
  if (!scene.geometry) return path;
  const float length=distance(aim.nearPoint,aim.farPoint);
  const XrVector3f direction{(aim.farPoint.x-aim.nearPoint.x)/length,
                           (aim.farPoint.y-aim.nearPoint.y)/length,
                           (aim.farPoint.z-aim.nearPoint.z)/length};
  // A gentle, bounded throw in metres and seconds. Tracking/eye resolution and
  // game world scale do not change its trajectory. Begin beyond the hand.
  path.points[path.count++]={aim.origin.x+direction.x*.03f*units,
                            aim.origin.y+direction.y*.03f*units,
                            aim.origin.z+direction.z*.03f*units};
  for (unsigned i=1;i<path.points.size();++i) {
    const float t=TeleportFlightSeconds*float(i)/float(path.points.size()-1);
    // Extend horizontal reach without also doubling the upward lob. Otherwise
    // a normal upward aim overshoots the landing limit or hits a low ceiling,
    // despite a clear, reachable destination in front of the wearer.
    const XrVector3f next{aim.origin.x+direction.x*TeleportHorizontalSpeed*t*units,
                         aim.origin.y+(direction.y*TeleportVerticalSpeed*t-4.905f*t*t)*units,
                         aim.origin.z+direction.z*TeleportHorizontalSpeed*t*units};
    const auto previous=path.points[path.count-1];
    if (distance(previous,next)<1e-5f*units) continue;
    const EngineAimRay segment{previous,previous,next};
    XrVector3f obstacle{},floor{};
    const int32_t blocked=scene.geometry(scene.context,&previous,&next,&obstacle);
    if (blocked!=0 && blocked!=1) throw std::runtime_error("teleport arc geometry query failed");
    const int32_t grounded=scene.floor ? scene.floor(scene.context,&previous,&next,&floor) : 0;
    if (grounded<0 || grounded>2) throw std::runtime_error("teleport arc floor query failed");
    if (blocked && !validRayHit(segment,obstacle,units))
      throw std::runtime_error("invalid teleport arc obstruction");
    if (grounded==1 && !validRayHit(segment,floor,units))
      throw std::runtime_error("invalid teleport arc floor hit");
    // The geometry query includes the floor. Accept coincident hits, but never
    // ignore a wall/prop encountered before the floor within this segment.
    if (blocked && (grounded!=1 || distance(previous,obstacle)+.02f*units<distance(previous,floor))) {
      path.points[path.count++]=obstacle;
      return path;
    }
    if (grounded==1) {
      path.points[path.count++]=floor;
      path.valid=teleportLanding(scene,observer,floor);
      return path;
    }
    path.points[path.count++]=next;
  }
  return path;
}

inline std::vector<ReticleVertex> teleportVertices(const EyeCamera& eye,
                                                  const TeleportPath& path,float units) {
  if (path.count>path.points.size() || !std::isfinite(units) || units<=0)
    throw std::invalid_argument("invalid teleport overlay");
  std::vector<ReticleVertex> vertices;
  if (path.count<2) return vertices;
  const uint32_t color=path.valid ? 0xff40e080u : 0xffe06050u;
  const auto line=[&](XrVector3f from,XrVector3f to) {
    const auto part=engineLine(eye,from,to,units,color);
    vertices.insert(vertices.end(),part.begin(),part.end());
  };
  for (uint32_t i=1;i<path.count;++i) line(path.points[i-1],path.points[i]);
  auto center=path.points[path.count-1];
  if (path.valid) {
    // A 50 cm landing ring lies on the floor. It is deliberately unlike the
    // small controller-facing interaction reticle used for Gabriel's actions.
    center.y+=.01f*units;
    for (unsigned i=0;i<24;++i) {
      const float a=6.28318530718f*float(i)/24,b=6.28318530718f*float(i+1)/24;
      line({center.x+.25f*units*std::cos(a),center.y,center.z+.25f*units*std::sin(a)},
           {center.x+.25f*units*std::cos(b),center.y,center.z+.25f*units*std::sin(b)});
    }
  } else {
    const auto previous=path.points[path.count-2];
    const float length=distance(previous,center);
    if (length<1e-6f) return vertices;
    const XrVector3f d{(center.x-previous.x)/length,(center.y-previous.y)/length,
                      (center.z-previous.z)/length};
    const float horizontal=std::hypot(d.x,d.z);
    const XrVector3f right=horizontal>1e-5f ? XrVector3f{-d.z/horizontal,0,d.x/horizontal} : XrVector3f{1,0,0};
    const XrVector3f up{right.y*d.z-right.z*d.y,right.z*d.x-right.x*d.z,
                       right.x*d.y-right.y*d.x};
    center={center.x-d.x*.01f*units,center.y-d.y*.01f*units,center.z-d.z*.01f*units};
    const auto corner=[&](float x,float y)->XrVector3f {
      return {center.x+(right.x*x+up.x*y)*.08f*units,
              center.y+(right.y*x+up.y*y)*.08f*units,
              center.z+(right.z*x+up.z*y)*.08f*units};
    };
    // Shape as well as colour distinguishes an invalid destination.
    line(corner(-1,-1),corner(1,1));line(corner(-1,1),corner(1,-1));
  }
  return vertices;
}

inline TeleportRequest teleportMovement(const EngineCamera& camera,const EngineCamera& observer,
                                        XrVector3f floor) {
  const float x=floor.x-observer.position.x,z=floor.z-observer.position.z;
  const float sine=std::sin(camera.yaw),cosine=std::cos(camera.yaw);
  // Match native CameraManager::Translate(4/3), not a pitched or frustum-scaled
  // eye basis. Native movement/commit still owns camera collision and ground.
  return {sizeof(TeleportRequest),1,x*cosine-z*sine,x*sine+z*cosine,
          floor.y+GabrielEyeHeightUnits-observer.position.y};
}

} // namespace gk3hd::vr
