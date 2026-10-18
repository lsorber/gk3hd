#pragma once

#include "engine_camera.h"
#include "frame_bridge.h"
#include "camera_transition.h"
#include <algorithm>
#include <climits>
#include <stdexcept>

#ifdef _WIN32
#define GK3HD_XR_CALL __stdcall
#else
#define GK3HD_XR_CALL
#endif

namespace gk3hd::vr {

// Gk3hdXrSceneV1 receives an IDirect3DDevice3 from this renderer and SceneV1*.
// Draw is a verified engine draw-only adapter. It must clear color/depth, apply
// the supplied rendering snapshot, draw static geometry and actors, and restore
// authored camera/projection/render state before returning. It must not tick the
// game, process input, present the desktop, or invoke this coordinator again.
using SceneDraw = int32_t (GK3HD_XR_CALL*)(void* context, unsigned eye, const EyeCamera* camera);
// Read-only native selection before either eye draws. Return 0 for unavailable
// world ownership, 1/2 for actor/scenery, 3 for an eligible world miss, or a
// negative error. A miss permits a beam, not a target or action. Never dispatch.
using ScenePick = int32_t (GK3HD_XR_CALL*)(void* context, unsigned hand,
                                        const EngineAimRay* ray, XrVector3f* hit);
// Native finite geometry segment, independent of selectable objects/screens.
// Cast from the authored interior towards the tracked eye. Return 0 for clear,
// 1 for a first surface hit, negative for unavailable; never move the camera.
using SceneGeometry = int32_t (GK3HD_XR_CALL*)(void* context, const XrVector3f* from,
                                            const XrVector3f* to, XrVector3f* hit);
constexpr int32_t SceneWorldMiss = 3;
constexpr uint32_t SceneRecenter = 1u;
// The completed-page presenter must finish this frame, with or without a panel.
constexpr uint32_t SceneDeferred = 2u;
// Opt-in GPU mirror primitive. The engine adapter must separately retain its
// page/camera bookkeeping; this flag alone does not skip a native world draw.
constexpr uint32_t SceneMirror = 4u;

struct MirrorCrop { int32_t left, top, right, bottom; };
// Fill the independent desktop canvas without stretching the eye's aspect.
// Integer products avoid overflow/rounding differences for large eye targets.
inline MirrorCrop mirrorCrop(uint32_t width, uint32_t height, uint32_t canvasWidth, uint32_t canvasHeight) {
  if (!width || !height || !canvasWidth || !canvasHeight ||
      width > INT32_MAX || height > INT32_MAX || canvasWidth > INT32_MAX || canvasHeight > INT32_MAX)
    throw std::invalid_argument("invalid XR mirror dimensions");
  uint32_t cropWidth = width, cropHeight = height;
  if (uint64_t(width)*canvasHeight > uint64_t(height)*canvasWidth)
    cropWidth = std::max(1u, uint32_t(uint64_t(height)*canvasWidth/canvasHeight));
  else
    cropHeight = std::max(1u, uint32_t(uint64_t(width)*canvasHeight/canvasWidth));
  const int32_t left = int32_t((width-cropWidth)/2), top = int32_t((height-cropHeight)/2);
  return {left, top, left+int32_t(cropWidth), top+int32_t(cropHeight)};
}
// Output from the same predicted frame and seated origin used for the eyes.
// Bits 0/1 identify valid left/right world rays. A zero mask means NO world
// selection. A focused input snapshot without rays permits navigation away
// from a wall fade; cuts and lost tracking/focus clear that snapshot too.
// No XR handles cross ABI.
struct WorldInputV1 {
  uint32_t size = sizeof(WorldInputV1), rayMask = 0;
  InputSnapshot input{};
  EngineAimRay rays[2]{};
};
static_assert(sizeof(WorldInputV1) == 180);
struct WorldTargetV1 {
  uint32_t size = sizeof(WorldTargetV1), hand = UINT32_MAX, kind = 0;
  XrVector3f point{};
};
static_assert(sizeof(WorldTargetV1) == 24);
struct SceneV1 {
  uint32_t size = sizeof(SceneV1);
  uint32_t flags = 0; // SceneRecenter | SceneDeferred | SceneMirror.
  float unitsPerMeter = 0; // Explicit game-world calibration, never guessed IPD.
  EngineCamera camera{};  // Authored camera snapshot, not mutated by tracking.
  uint32_t width = 0, height = 0; // Desktop dimensions, never the VR eye size.
  SceneDraw draw = nullptr;
  void* context = nullptr;
  WorldInputV1* worldInput = nullptr; // Optional, render-thread-owned output.
  ScenePick pick = nullptr;
  WorldTargetV1* target = nullptr; // Completed-frame diagnostic, not early input.
  SceneGeometry geometry = nullptr;
  // Designated native floor, only while the ordinary camera is user-owned.
  // 0: retain authored/scripted camera; 1: floor hit; 2: user-owned camera with
  // no floor reference (retain height but stand upright). Other results fail.
  SceneGeometry floor = nullptr;
};
#ifdef _WIN32
static_assert(sizeof(SceneV1) == 256, "scene bridge requires the x86 engine ABI");
#endif

// Frame transport owns queue synchronization and XR image lifecycle. The scene
// coordinator owns recenter, camera comfort and original-engine eye math.
class SceneTransport {
public:
  virtual ~SceneTransport() = default;
  virtual bool begin(FrameViews& views) = 0; // False means no frame remains open.
  virtual XrTime displayTime() const = 0;
  // Bind a private target at the recommended eye dimensions. Every successful
  // beginEye has one endEye, including failed draws/copies. The desktop target,
  // depth and rendering state must be restored before finishing the XR frame.
  virtual void beginEye(unsigned eye, const EyeCamera& camera) = 0;
  virtual void endEye() = 0;
  virtual void write(unsigned eye, float visibility) = 0;
  virtual void overlay(const EyeCamera& camera, const WorldTargetV1& target,
                       const EngineAimRay& ray, float unitsPerMeter) = 0;
  virtual void end(bool rendered) = 0;
};

class StereoScene {
public:
  bool render(const SceneV1& scene, SceneTransport& transport);
private:
  XrPosef origin_{{0, 0, 0, 1}, {0, 0, 0}};
  bool centered_ = false;
  bool rendering_ = false;
  CameraTransition transition_;
};

} // namespace gk3hd::vr
