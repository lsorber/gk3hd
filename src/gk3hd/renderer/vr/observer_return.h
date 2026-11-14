#pragma once

#include "observer.h"

namespace gk3hd::vr {

// Read-only, action-time search. The native owner must still validate scene,
// protagonist and camera ownership, complete a blackout, then revalidate before
// committing a move. Finding ground grants no relocation permission.
inline bool observerReturnFloor(const SceneV1& scene, XrVector3f anchor,
                                XrVector3f observer, XrVector3f& output) {
  const float units=scene.unitsPerMeter;
  const auto finite=[](XrVector3f value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
  };
  if (!std::isfinite(units) || units<=0 || !finite(anchor) || !finite(observer))
    throw std::invalid_argument("invalid observer Return coordinates");
  if (!scene.floor || !scene.geometry) return false;
  const auto floor=[&](XrVector3f from,XrVector3f to,XrVector3f& hit) {
    if (!finite(from) || !finite(to) || !(from.y>to.y))
      throw std::invalid_argument("invalid observer Return floor segment");
    const int32_t result=scene.floor(scene.context,&from,&to,&hit);
    if (result==0 || result==2) return false; // No floor or no user-owned reference.
    if (result!=1 || !validRayHit({from,from,to},hit,units))
      throw std::runtime_error("invalid observer Return floor result");
    return true;
  };
  const auto clear=[&](XrVector3f from,XrVector3f to) {
    if (!finite(from) || !finite(to))
      throw std::invalid_argument("invalid observer Return clearance segment");
    XrVector3f hit{};
    const int32_t result=scene.geometry(scene.context,&from,&to,&hit);
    if (result==0) return true;
    if (result!=1 || !validRayHit({from,from,to},hit,units))
      throw std::runtime_error("invalid observer Return clearance result");
    return false;
  };
  // The native model root is not a foot position. Establish the protagonist's
  // designated floor first, rather than mistaking a table/prop for ground.
  XrVector3f ground{};
  if (!floor({anchor.x,anchor.y+.25f*units,anchor.z},
             {anchor.x,anchor.y-4.f*units,anchor.z},ground)) return false;
  float x=(observer.x-anchor.x)/units,z=(observer.z-anchor.z)/units;
  const float length=std::hypot(x,z);
  if (!std::isfinite(length)) throw std::invalid_argument("observer Return direction overflow");
  if (length>.01f) { x/=length;z/=length; }
  else { x=0;z=1; } // No preferred side when already above the protagonist.

  // Try the near side first, then alternate left/right, keeping outside the
  // character's body. Sixteen candidates bound the work to one menu action.
  // Nothing depends on an eye's IPD, frustum, device name or render resolution.
  constexpr float diagonal=.70710678118f;
  constexpr std::array<std::array<float,2>,8> directions{{
    {1,0},{diagonal,diagonal},{diagonal,-diagonal},{0,1},{0,-1},
    {-diagonal,diagonal},{-diagonal,-diagonal},{-1,0}}};
  constexpr std::array<std::array<float,2>,5> footprint{{
    {0,0},{-.2f,-.2f},{-.2f,.2f},{.2f,-.2f},{.2f,.2f}}};
  for (float radius : {.8f,1.2f}) for (const auto& direction : directions) {
    XrVector3f center{anchor.x+(x*direction[0]-z*direction[1])*radius*units,
                     ground.y,anchor.z+(z*direction[0]+x*direction[1])*radius*units};
    XrVector3f hit{};
    // Do not select a lower storey or a balcony above the protagonist.
    if (!floor({center.x,ground.y+.35f*units,center.z},
               {center.x,ground.y-.35f*units,center.z},hit)) continue;
    center.y=hit.y;
    bool available=true;
    const float eye=center.y+GabrielEyeHeightUnits;
    // Floor support and standing clearance cover the centre and four corners.
    // A clear centre alone would allow the head/body to overlap a door frame.
    for (const auto& offset : footprint) {
      const float px=center.x+offset[0]*units,pz=center.z+offset[1]*units;
      if (!floor({px,center.y+.25f*units,pz},{px,center.y-.25f*units,pz},hit) ||
          std::abs(hit.y-center.y)>.15f*units ||
          !clear({px,center.y+.15f*units,pz},{px,eye+.1f*units,pz})) {
        available=false;break;
      }
    }
    if (!available) continue;
    // Reject furniture and walls crossing the standing volume between its
    // columns, including a waist-high obstacle that leaves the head clear.
    for (float height : {.15f*units,.5f*GabrielEyeHeightUnits,GabrielEyeHeightUnits}) {
      const float y=center.y+height;
      if (!clear({center.x-.2f*units,y,center.z},{center.x+.2f*units,y,center.z}) ||
          !clear({center.x,y,center.z-.2f*units},{center.x,y,center.z+.2f*units})) {
        available=false;break;
      }
    }
    if (!available) continue;
    // Return may cross an obstructed route or exceed ordinary teleport range.
    // Do not impose a ray from the OLD observer, or mutate heading/the actor.
    output=center;
    return true;
  }
  return false; // Failed searches leave the caller's previous position intact.
}

} // namespace gk3hd::vr
