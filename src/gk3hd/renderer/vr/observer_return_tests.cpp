#include "observer_return.h"
#include "teleport.h"

#include <iostream>
#include <limits>
#include <vector>

using namespace gk3hd::vr;
namespace {
void require(bool condition,const char* message) {
  if (!condition) throw std::runtime_error(message);
}
bool close(float a,float b) { return std::abs(a-b)<.001f; }
struct Box { XrVector3f low,high; };
struct Room {
  float units=40,ground=0,slope=0;
  XrVector3f origin{};
  bool supported=true,hole=false,invalidHit=false;
  int floorOverride=1,geometryOverride=0;
  unsigned queries=0;
  std::vector<Box> obstacles;
  static int32_t GK3HD_XR_CALL floor(void* context,const XrVector3f* from,
                                    const XrVector3f* to,XrVector3f* hit) {
    auto& room=*static_cast<Room*>(context);++room.queries;
    require(close(from->x,to->x) && close(from->z,to->z) && from->y>to->y,
            "Return floor query was not a downward column");
    if (room.floorOverride!=1) return room.floorOverride;
    const float x=(from->x-room.origin.x)/room.units;
    const float z=(from->z-room.origin.z)/room.units;
    if (!room.supported || (room.hole && std::abs(x)<.35f && z>.6f)) return 0;
    const float y=room.ground+room.slope*(from->x-room.origin.x);
    if (y>from->y || y<to->y) return 0;
    *hit={from->x,y,from->z};
    if (room.invalidHit) hit->x+=room.units;
    return 1;
  }
  static int32_t GK3HD_XR_CALL geometry(void* context,const XrVector3f* from,
                                       const XrVector3f* to,XrVector3f* hit) {
    auto& room=*static_cast<Room*>(context);++room.queries;
    if (room.geometryOverride) return room.geometryOverride;
    float first=2;
    for (const auto& box : room.obstacles) {
      const float start[]{from->x,from->y,from->z},end[]{to->x,to->y,to->z};
      const float low[]{box.low.x,box.low.y,box.low.z},high[]{box.high.x,box.high.y,box.high.z};
      float enter=0,leave=1;
      for (unsigned axis=0;axis<3;++axis) {
        const float delta=end[axis]-start[axis];
        if (std::abs(delta)<1e-6f) {
          if (start[axis]<low[axis] || start[axis]>high[axis]) {enter=2;break;}
        } else {
          const float a=(low[axis]-start[axis])/delta,b=(high[axis]-start[axis])/delta;
          enter=std::max(enter,std::min(a,b));leave=std::min(leave,std::max(a,b));
        }
      }
      if (enter<=leave) first=std::min(first,enter);
    }
    if (first>1) return 0;
    *hit={from->x+first*(to->x-from->x),from->y+first*(to->y-from->y),
          from->z+first*(to->z-from->z)};
    return 1;
  }
  SceneV1 scene() {
    SceneV1 value{};value.unitsPerMeter=units;value.context=this;
    value.floor=floor;value.geometry=geometry;return value;
  }
  XrVector3f anchor() const {return {origin.x,ground+.85f*units,origin.z};}
  XrVector3f observer() const {return {origin.x,ground+GabrielEyeHeightUnits,origin.z+20*units};}
  void block(float left,float bottom,float back,float right,float top,float front) {
    obstacles.push_back({{origin.x+left*units,ground+bottom*units,origin.z+back*units},
                         {origin.x+right*units,ground+top*units,origin.z+front*units}});
  }
};
void destinations() {
  for (float units : {20.f,40.f,80.f}) {
    Room room;room.units=units;room.ground=123;room.origin={91,0,-273};
    auto scene=room.scene();const auto anchor=room.anchor(),observer=room.observer();
    XrVector3f result{1,2,3};
    require(observerReturnFloor(scene,anchor,observer,result),"open ground had no Return destination");
    require(close(result.x,anchor.x) && result.z>anchor.z && close(result.y,room.ground),
            "Return did not prefer the observer's side of the protagonist's floor");
    const float range=std::hypot(result.x-anchor.x,result.z-anchor.z)/units;
    require(range>.6f && range<1.4f,"Return overlapped the character or landed too far away");
    XrVector3f repeated{};
    require(observerReturnFloor(scene,anchor,observer,repeated) && close(result.x,repeated.x) &&
            close(result.y,repeated.y) && close(result.z,repeated.z),"Return search was nondeterministic");
    require(close(anchor.y,room.anchor().y) && close(observer.z,room.observer().z),
            "read-only Return search moved the protagonist or observer");
    // A wall halfway along a long route must not prevent a safe local Return.
    room.block(-10,-1,10,10,10,10.1f);
    require(observerReturnFloor(scene,anchor,observer,result),"Return incorrectly required a clear old-to-new path");
    EngineCamera oldCamera{};oldCamera.position=observer;
    require(!teleportLanding(scene,oldCamera,result),
            "Return search accidentally widened ordinary teleport range");
  }
}
void obstacles() {
  Room room;auto scene=room.scene();XrVector3f result{};
  room.block(-.4f,0,.4f,.4f,4,1.5f);
  require(observerReturnFloor(scene,room.anchor(),room.observer(),result) &&
          std::abs(result.x)>.4f*room.units,"Return ignored a nearby wall instead of trying another side");
  room.obstacles.clear();room.block(-2,1.2f,-2,2,1.3f,2);
  const XrVector3f prior{7,8,9};result=prior;
  require(!observerReturnFloor(scene,room.anchor(),room.observer(),result),
          "Return placed the observer under a low ceiling");
  require(close(result.x,prior.x) && close(result.y,prior.y) && close(result.z,prior.z),
          "failed Return search destroyed the previous destination");
  require(room.queries<500,"Return performed unbounded scene queries");
  room.obstacles.clear();room.hole=true;
  require(observerReturnFloor(scene,room.anchor(),room.observer(),result) &&
          std::abs(result.x)>.35f*room.units,"Return selected a partially unsupported footprint");
  room.hole=false;room.slope=.1f;
  require(observerReturnFloor(scene,room.anchor(),room.observer(),result),
          "a gentle supported floor slope unnecessarily disabled Return");
  room.slope=0;room.supported=false;result=prior;
  require(!observerReturnFloor(scene,room.anchor(),room.observer(),result),"Return invented missing ground");
}
void bodyClearance() {
  // The centre column is clear, but a thin obstruction crosses a footprint
  // corner. The alternative must be used rather than clipping the head/body.
  Room room;room.block(.19f,.4f,.59f,.21f,.8f,1.01f);
  auto scene=room.scene();XrVector3f result{};
  require(observerReturnFloor(scene,room.anchor(),room.observer(),result) &&
          std::abs(result.x)>.01f*room.units,"Return checked only its central head column");
  // A thin rail intersects the body between all five vertical columns.
  room.obstacles.clear();room.block(-.05f,0,.74f,.05f,4,.76f);
  require(observerReturnFloor(scene,room.anchor(),room.observer(),result) &&
          std::abs(result.x)>.01f*room.units,"Return missed an obstruction between its clearance columns");
}
void invalidInputs() {
  Room room;auto scene=room.scene();const XrVector3f prior{7,8,9};XrVector3f result=prior;
  for (int unavailable : {0,2}) {
    room.floorOverride=unavailable;
    require(!observerReturnFloor(scene,room.anchor(),room.observer(),result),
            "unavailable native floor produced a destination");
  }
  room.floorOverride=1;scene.geometry=nullptr;
  require(!observerReturnFloor(scene,room.anchor(),room.observer(),result),
          "Return accepted a destination without collision information");
  scene=room.scene();
  const auto fails=[&](const char* message) {
    bool caught=false;
    try {observerReturnFloor(scene,room.anchor(),room.observer(),result);}
    catch (const std::exception&) {caught=true;}
    require(caught,message);
    require(close(result.x,prior.x) && close(result.y,prior.y) && close(result.z,prior.z),
            "invalid query published a destination");
  };
  room.invalidHit=true;fails("off-segment native floor hit was trusted");room.invalidHit=false;
  room.floorOverride=-1;fails("native floor error was treated as clear ground");room.floorOverride=1;
  room.geometryOverride=-1;fails("native collision error was treated as clear space");room.geometryOverride=0;
  for (float invalid : {0.f,-1.f,std::numeric_limits<float>::infinity(),
                        std::numeric_limits<float>::quiet_NaN()}) {
    scene.unitsPerMeter=invalid;fails("invalid world calibration was accepted");
  }
  scene=room.scene();room.origin.x=std::numeric_limits<float>::quiet_NaN();
  fails("nonfinite protagonist anchor was accepted");
}
}
int main() {
  try {
    destinations();obstacles();bodyClearance();invalidInputs();
    std::cout<<"Observer Return floor, clearance, bounded search and failure checks passed\n";
    return 0;
  } catch (const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
