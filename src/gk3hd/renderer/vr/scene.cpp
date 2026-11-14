#include "scene.h"
#include "wall_visibility.h"
#include "observer.h"
#include "teleport.h"
#include "conservative_camera.h"

namespace gk3hd::vr {
namespace {
XrPosef pose(const EyeView& view) {
  return {{view.orientation[0], view.orientation[1], view.orientation[2], view.orientation[3]},
          {view.position[0], view.position[1], view.position[2]}};
}
XrPosef aimPose(const HandInput& hand) {
  return {{hand.orientation[0], hand.orientation[1], hand.orientation[2], hand.orientation[3]},
          {hand.position[0], hand.position[1], hand.position[2]}};
}
XrPosef midpoint(XrPosef left, XrPosef right) {
  left.orientation = normalized(left.orientation);
  right.orientation = normalized(right.orientation);
  const auto a = left.orientation, b = right.orientation;
  const float sign = a.x*b.x + a.y*b.y + a.z*b.z + a.w*b.w < 0 ? -1.f : 1.f;
  return {normalized({a.x+sign*b.x, a.y+sign*b.y, a.z+sign*b.z, a.w+sign*b.w}),
          {(left.position.x+right.position.x)/2, (left.position.y+right.position.y)/2,
           (left.position.z+right.position.z)/2}};
}
} // namespace

bool StereoScene::render(const SceneV1& scene, SceneTransport& transport) {
  listenerReady_=false;
  if (scene.size != sizeof(scene)) throw std::invalid_argument("invalid engine scene ABI");
  if (scene.worldInput) {
    if (scene.worldInput->size != sizeof(WorldInputV1))
      throw std::invalid_argument("invalid world input ABI");
    *scene.worldInput = {};
  }
  if (scene.target) {
    if (scene.target->size != sizeof(WorldTargetV1))
      throw std::invalid_argument("invalid world target ABI");
    *scene.target = {};
  }
  if (scene.teleport) {
    if (scene.teleport->size != sizeof(TeleportRequest))
      throw std::invalid_argument("invalid teleport output ABI");
    *scene.teleport = {};
  }
  if (scene.size != sizeof(scene) || (scene.flags & ~(SceneRecenter | SceneDeferred | SceneMirror | SceneRelocate)) || !scene.draw ||
      !scene.width || !scene.height || !std::isfinite(scene.unitsPerMeter) || scene.unitsPerMeter <= 0)
    throw std::invalid_argument("invalid engine scene bridge request");
  const bool requestedRelocation = (scene.flags & SceneRelocate) != 0;
  if (requestedRelocation && !scene.teleport)
    throw std::invalid_argument("observer relocation requires completion output");
  // The native producer retires flags after this call, including on failure.
  // Only successful two-eye completion below can acknowledge relocation.
  if (rendering_) throw std::logic_error("recursive XR scene rendering");
  struct RenderingGuard {
    bool& flag;
    ~RenderingGuard() { flag = false; }
  } guard{rendering_};
  rendering_ = true;
  FrameViews views{};
  if (!transport.begin(views)) {
    teleportArmed_=teleportHeld_=false; teleportHand_=2;
    return false;
  }
  bool frameOpen = true;
  bool eyeOpen = false;
  try {
    bool recenter = (scene.flags & SceneRecenter) != 0;
    if (views.input.flags & InputFocused)
      for (const auto& hand : views.input.hands)
        recenter = recenter || ((hand.flags & AimValid) && (hand.pressed & Recenter));
    if (!centered_ || recenter) {
      const auto viewer = midpoint(pose(views.eyes[0]), pose(views.eyes[1]));
      const auto forward = rotate(viewer.orientation, {0, 0, -1});
      // Center horizontal heading and position, not pitch/roll. Otherwise a
      // seated player centering while tilted permanently banks the world.
      // Looking vertically has no heading: preserve the last valid yaw.
      if (forward.x*forward.x + forward.z*forward.z > 1e-8f) {
        const float yaw = std::atan2(-forward.x, -forward.z);
        origin_.orientation = {0, std::sin(yaw/2), 0, std::cos(yaw/2)};
      }
      origin_.position = viewer.position;
      movementHeading_ = {0, 1};
      centered_ = true;
    }
    const auto camera = observerCamera(scene);
    // Retain the rigid head center, independently of either eye's IPD/FOV.
    // Do not publish it until the complete stereo transaction succeeds.
    const auto localHead = compose(inverse(origin_),midpoint(pose(views.eyes[0]),pose(views.eyes[1])));
    const auto listener = engineListenerPose(camera, localHead, scene.unitsPerMeter);
    const auto& m = camera.worldToCamera;
    const float depthScale = std::sqrt(m[2]*m[2]+m[5]*m[5]+m[8]*m[8]);
    if (!std::isfinite(depthScale) || depthScale <= 0)
      throw std::invalid_argument("invalid authored camera depth scale");
    const float authoredNear = -scene.camera.planes[0].distance/depthScale/scene.unitsPerMeter;
    if (!std::isfinite(authoredNear) || authoredNear <= 0)
      throw std::invalid_argument("invalid authored near clipping distance");
    // Authored desktop cameras can crop nearby characters long before the
    // wearer reaches them. Use a close VR near plane consistently for native
    // clipping, shared culling, projection and wall protection in both eyes.
    const float nearMeters = std::min(authoredNear, .02f);
    const float farMeters = scene.camera.planes[1].distance/depthScale/scene.unitsPerMeter;
    // Compute both snapshots before the first game draw, so invalid tracking or
    // projection cannot leave the first eye partially rendered.
    std::array<EyeCamera, 2> eyes{};
    WorldInputV1 worldInput{};
    WorldTargetV1 target{};
    WorldTargetV1 pointer{}; // Visual-only: a miss must not become an action hit.
    const auto pointing=scene.pointingHand ? *scene.pointingHand : 1u;
    const unsigned moveHand=pointing^1u;
    for (unsigned eye = 0; eye < 2; ++eye) {
      const auto& view = views.eyes[eye];
      const auto relative = compose(inverse(origin_), pose(view));
      const XrFovf fov{view.fov[0], view.fov[1], view.fov[2], view.fov[3]};
      eyes[eye] = engineEyeCamera(camera, relative, fov, view.width, view.height,
                                 scene.unitsPerMeter, nearMeters, farMeters);
    }
    // Both eyes retain their current predicted head poses even at black. Do
    // not aim/select world objects through an obscured transition frame.
    const auto displayTime = transport.displayTime();
    const float transition = transition_.sample(camera, scene.unitsPerMeter, displayTime);
    float visibility = std::min(wallVisibility(scene, eyes, nearMeters, camera), transition);
    if (transition == 1.f && (scene.worldInput || scene.pick) && (views.input.flags & InputFocused)) {
      // A wall fade withdraws object rays, not the ability to retreat with the
      // stick. Authored cuts, tracking/focus loss and failed frames still
      // withdraw every world control. Publish only after both eyes complete.
      worldInput.input = views.input;
      if (pointing < 2 && (worldInput.input.hands[moveHand].flags & AimValid)) {
        auto& control = worldInput.input.hands[moveHand];
        if (std::isfinite(control.stick[0]) && std::isfinite(control.stick[1]) &&
            std::abs(control.stick[0]) <= 1 && std::abs(control.stick[1]) <= 1) {
          const auto movement = headRelativeMotion({control.stick[0], control.stick[1]},
                                                   localHead.orientation, movementHeading_);
          control.stick[0] = movement.x; control.stick[1] = movement.y;
        }
      }
      for (unsigned hand = 0; visibility == 1.f && hand < 2; ++hand) {
        if (!(views.input.hands[hand].flags & AimValid)) continue;
        const auto relative = compose(inverse(origin_), aimPose(views.input.hands[hand]));
        worldInput.rays[hand] = engineAimRay(camera, relative, scene.unitsPerMeter,
                                           0, farMeters);
        worldInput.rayMask |= 1u << hand;
      }
    }
    // A query may consume only this local predicted snapshot. Completed input
    // remains invalid until both eyes and the frame transport have succeeded.
    if (scene.pick)
      for (unsigned hand = 0; hand < 2; ++hand) {
        if (!(worldInput.rayMask & (1u << hand))) continue;
        XrVector3f hit{};
        const auto kind = scene.pick(scene.context, hand, &worldInput.rays[hand], &hit);
        if (kind < 0 || kind > SceneWorldMiss) throw std::runtime_error("engine world query failed");
        if (!kind) continue;
        pointer.hand = hand;
        if (kind == SceneWorldMiss) break;
        if (!validRayHit(worldInput.rays[hand], hit, scene.unitsPerMeter))
          throw std::runtime_error("engine world query returned an invalid hit");
        target.hand = hand; target.kind = static_cast<uint32_t>(kind); target.point = hit;
        pointer = target;
        break; // The adapter selects the active pointing hand, not both hands.
      }
    TeleportRequest teleport{};
    TeleportPath relocation{};
    const bool relocating = requestedRelocation && (views.input.flags & InputFocused) &&
      ((views.input.hands[0].flags | views.input.hands[1].flags) & AimValid);
    if (relocating) {
      visibility = 0;
      teleport.ready = ObserverRelocationReady;
      pointer = {}; target = {}; worldInput.rayMask = 0;
      for (auto& control : worldInput.input.hands) {
        control.held = control.pressed = 0;
        control.stick[0] = control.stick[1] = 0;
      }
    }
    if (!relocating && scene.teleport && pointing<2 && visibility==1.f && pointer.hand<2 &&
        (worldInput.rayMask&(1u<<moveHand)) &&
        !(views.input.hands[pointing].held&(Menu|Inventory|Cancel)) &&
        (!(views.input.hands[pointing].held&Select) || teleportHeld_) &&
        !(views.input.hands[moveHand].held&(Menu|Inventory|Cancel))) {
      const auto& hand=views.input.hands[moveHand];
      if (teleportHand_!=moveHand) {
        teleportHand_=moveHand; teleportArmed_=teleportHeld_=false;
      }
      const bool held=(hand.held&Select)!=0;
      const bool released=!held && teleportHeld_ && teleportArmed_;
      if (!held) teleportArmed_=true;
      const auto relative=compose(inverse(origin_),aimPose(hand));
      if ((held || released) && teleportArmed_) {
        const auto aim=engineAimRay(camera,relative,scene.unitsPerMeter,0,TeleportMaximumRangeMeters);
        relocation=teleportPath(scene,camera,aim);
        if (released && relocation.valid) {
          teleport=teleportMovement(scene.camera,camera,relocation.points[relocation.count-1]);
          visibility=0; // Complete the black frame before native relocation.
        }
        if (!held) relocation={};
      }
      if ((held || released) && teleportArmed_) {
        // Teleport preview owns locomotion and selection, including a miss.
        // Keep the physical snapshot immutable; publish only neutral controls
        // to native movement/picking until this preview has ended.
        pointer = {}; target = {}; worldInput.rayMask = 0;
        for (auto& control : worldInput.input.hands) {
          control.held &= ~Select; control.pressed &= ~Select;
          control.stick[0] = control.stick[1] = 0;
        }
      }
      teleportHeld_=held && teleportArmed_;
    } else {
      teleportArmed_=teleportHeld_=false; teleportHand_=2;
    }
    transport.prepareVisibility(visibility);
    bool shared = false;
    if (scene.sharedDraw) {
      const auto source = conservativeStereoCamera(eyes);
      if (source && transport.beginShared(*source, eyes)) {
        eyeOpen = shared = true;
        if (scene.sharedDraw(scene.context, &*source, eyes.data()) != 0)
          throw std::runtime_error("engine shared world draw failed");
        transport.finishShared();
      }
    }
    for (unsigned eye = 0; eye < 2; ++eye) {
      if (shared) transport.selectSharedEye(eye);
      else {
        transport.beginEye(eye, eyes[eye]);
        eyeOpen = true;
        if (scene.draw(scene.context, eye, &eyes[eye]) != 0)
          throw std::runtime_error("engine eye draw failed");
      }
      if (pointer.hand < 2)
        transport.overlay(eyes[eye], pointer, worldInput.rays[pointer.hand], scene.unitsPerMeter);
      if (relocation.count > 1)
        transport.teleportOverlay(eyes[eye],relocation,scene.unitsPerMeter);
      transport.write(eye, visibility);
      if (!shared) {
        eyeOpen = false;
        transport.endEye();
      }
    }
    if (shared) {
      eyeOpen = false;
      transport.endEye();
    }
    // Transport consumes the frame even if the runtime reports a submission
    // error. Never attempt to end the same XR frame a second time.
    frameOpen = false;
    transport.end(true);
    if (teleport.ready) transition_.blink(displayTime);
    if (views.input.flags & InputFocused) {
      listener_=listener;listenerAt_=ListenerClock::now();listenerReady_=true;
    }
    if (scene.worldInput) *scene.worldInput = worldInput;
    if (scene.target) *scene.target = target;
    if (scene.teleport) *scene.teleport = teleport;
    return true;
  } catch (...) {
    teleportArmed_=teleportHeld_=false; teleportHand_=2;
    if (eyeOpen) {
      try { transport.endEye(); } catch (...) { }
    }
    if (frameOpen) {
      try { transport.end(false); } catch (...) { }
    }
    throw;
  }
}
} // namespace gk3hd::vr
