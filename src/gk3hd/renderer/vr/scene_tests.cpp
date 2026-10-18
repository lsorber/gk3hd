#include "scene.h"
#include "frame_scheduler.h"
#include "loading_frames.h"
#include "wall_visibility.h"
#include "observer.h"

#include <cstring>
#include <future>
#include <iostream>
#include <stdexcept>
#include <vector>

using namespace gk3hd::vr;
namespace {
void require(bool test, const char* message) { if (!test) throw std::runtime_error(message); }
struct Frame final : SceneTransport {
  FrameViews views{};
  bool visible = true, open = false;
  unsigned submissions = 0, cancellations = 0;
  std::vector<unsigned> writes;
  std::vector<float> visibility;
  XrTime time = 1000000000;
  std::vector<EyeCamera> overlays;
  std::vector<WorldTargetV1> pointers;
  bool failOverlay = false;
  bool eyeOpen = false, failWrite = false;
  unsigned eyeRestores = 0;
  Frame() {
    for (unsigned eye = 0; eye < 2; ++eye)
      views.eyes[eye] = {256, 256, {0, 0, 0, eye ? -1.f : 1.f},
        {.5f + (eye ? .04f : -.04f), 1.6f, 2}, {-.7f, .9f, .8f, -.6f}};
  }
  bool begin(FrameViews& output) override {
    require(!open, "frame already open");
    output = views; writes.clear(); visibility.clear(); open = visible; return visible;
  }
  XrTime displayTime() const override { return time; }
  void beginEye(unsigned eye, const EyeCamera& camera) override {
    require(open && !eyeOpen, "nested eye target or target without frame");
    require(eye == writes.size(), "eye targets were reordered");
    const auto& view = views.eyes[eye];
    require(camera.camera.width == int(view.width) && camera.camera.height == int(view.height),
            "eye target uses desktop dimensions");
    eyeOpen = true;
  }
  void endEye() override {
    require(eyeOpen, "eye target restored twice");
    eyeOpen = false; ++eyeRestores;
  }
  void write(unsigned eye, float gain) override {
    require(open && eyeOpen, "copy without eye target");
    if (failWrite) throw std::runtime_error("copy failure");
    writes.push_back(eye); visibility.push_back(gain);
  }
  void overlay(const EyeCamera& camera, const WorldTargetV1& target, const EngineAimRay&, float) override {
    require(open && writes.size() == overlays.size(), "reticle drawn after eye copy");
    overlays.push_back(camera);
    pointers.push_back(target);
    if (failOverlay) throw std::runtime_error("reticle failure");
  }
  void end(bool rendered) override {
    require(open && !eyeOpen, "frame ended twice or eye target not restored"); open = false;
    if (rendered) ++submissions; else ++cancellations;
  }
};
struct Draws {
  std::vector<EyeCamera> cameras;
  int failEye = -1;
  int floorResult = 1;
  float floorY = 0, floorXError = 0;
  unsigned floorQueries = 0;
  static int32_t GK3HD_XR_CALL floor(void* context, const XrVector3f* from,
                                   const XrVector3f* to, XrVector3f* hit) {
    auto& state = *static_cast<Draws*>(context);
    ++state.floorQueries;
    require(from->x == to->x && from->z == to->z && from->y > to->y,
            "observer sampled a slanted/non-downward floor segment");
    if (state.floorResult == 1) *hit = {from->x+state.floorXError, state.floorY, from->z};
    return state.floorResult;
  }
  static int32_t GK3HD_XR_CALL draw(void* context, unsigned eye, const EyeCamera* camera) {
    auto& state = *static_cast<Draws*>(context);
    require(eye == state.cameras.size(), "eyes were reordered");
    state.cameras.push_back(*camera);
    return int(eye) == state.failEye ? -1 : 0;
  }
};
SceneV1 scene(Draws& draws) {
  SceneV1 value{};
  value.unitsPerMeter = 40;
  value.width = 1024; value.height = 768;
  value.camera.worldToCamera = {1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0};
  value.camera.planes[0].distance = -2;
  value.camera.planes[1].distance = 24000;
  value.draw = Draws::draw; value.context = &draws;
  return value;
}
void observerPlacement() {
  for (float units : {20.f, 40.f, 80.f}) {
    StereoScene coordinator;
    Frame frame;
    Draws draws;
    auto request = scene(draws);
    request.floor = Draws::floor;
    request.unitsPerMeter = units;
    request.camera.position = {20, 61, 30};
    // Authored yaw and pitch, with unequal camera-axis scales. The observer
    // retains heading but physical up/down must remain the world's vertical.
    const float yaw = .7f, pitch = .4f;
    const float cy = std::cos(yaw), sy = std::sin(yaw);
    const float cp = std::cos(pitch), sp = std::sin(pitch);
    request.camera.pitch = pitch;
    request.camera.worldToCamera = {cy*2, sy*sp*3, sy*cp*4,
      0, cp*3, -sp*4, -sy*2, cy*sp*3, cy*cp*4, 0, 0, 0};
    const auto authored = request.camera;
    WorldInputV1 input{};
    request.worldInput = &input;
    frame.views.input.flags = InputFocused;
    auto& hand = frame.views.input.hands[0];
    hand.flags = AimValid;
    hand.orientation[3] = 1;
    hand.position[0] = .5f; hand.position[1] = 1.6f; hand.position[2] = 2;
    const auto center = [&]() {
      const auto& left = draws.cameras[0].camera.position;
      const auto& right = draws.cameras[1].camera.position;
      return XrVector3f{(left.x+right.x)/2, (left.y+right.y)/2, (left.z+right.z)/2};
    };
    require(coordinator.render(request, frame), "observer scene skipped");
    const auto neutral = center();
    require(std::abs(neutral.y-GabrielEyeHeightUnits) < .001f &&
            std::abs(neutral.x-20) < .001f && std::abs(neutral.z-30) < .001f,
            "observer inherited authored height or shifted its horizontal anchor");
    require(input.rayMask == 1 && std::abs(input.rays[0].origin.y-neutral.y) < .001f,
            "controller ray used authored height instead of the observer anchor");
    const auto separation = [&]() {
      const auto& left = draws.cameras[0].camera.position;
      const auto& right = draws.cameras[1].camera.position;
      return std::sqrt((left.x-right.x)*(left.x-right.x)+(left.z-right.z)*(left.z-right.z));
    };
    require(std::abs(separation()-.08f*units) < .001f, "observer invented an eye separation");
    for (float displacement : {.25f, -.35f}) {
      draws.cameras.clear(); frame.time += 10000000;
      for (auto& eye : frame.views.eyes) eye.position[1] = 1.6f+displacement;
      require(coordinator.render(request, frame), "tracked observer scene skipped");
      const auto moved = center();
      require(std::abs(moved.y-neutral.y-displacement*units) < .001f &&
              std::abs(moved.x-neutral.x) < .001f && std::abs(moved.z-neutral.z) < .001f,
              "physical crouch/stand was scaled incorrectly or followed authored pitch");
    }
    draws.cameras.clear(); frame.time += 10000000;
    request.flags |= SceneRecenter;
    require(coordinator.render(request, frame), "observer recenter scene skipped");
    require(std::abs(center().y-GabrielEyeHeightUnits) < .001f &&
            std::abs(separation()-.08f*units) < .001f,
            "seated recenter changed virtual eye height or runtime IPD");
    draws.cameras.clear(); frame.time += 10000000;
    request.flags &= ~SceneRecenter;
    draws.floorY = 5;
    request.camera.position.y += 5;
    require(coordinator.render(request, frame), "observer floor transition skipped");
    require(std::abs(center().y-5-GabrielEyeHeightUnits) < .001f,
            "observer did not follow the changed floor");
    require(std::memcmp(&authored, &request.camera, offsetof(EngineCamera, position)) == 0 &&
            request.camera.position.y == authored.position.y+5,
            "observer altered original camera fields");
    request.camera = authored;
    draws.floorResult = 0;
    const auto unchanged = observerCamera(request);
    require(std::memcmp(&unchanged, &authored, sizeof(authored)) == 0,
            "scripted owner changed the authored camera");
    draws.floorResult = 2;
    const auto upright = observerCamera(request);
    require(upright.position.x == authored.position.x && upright.position.y == authored.position.y &&
            upright.position.z == authored.position.z && upright.pitch == 0 &&
            upright.worldToCamera[1] == 0 && upright.worldToCamera[3] == 0 &&
            upright.worldToCamera[5] == 0 && upright.worldToCamera[7] == 0,
            "missing floor invented an altitude or retained a tilted free-camera horizon");
    require(std::memcmp(&request.camera, &authored, sizeof(authored)) == 0,
            "upright fallback mutated the original camera");
    draws.floorResult = 1;
    draws.floorXError = units*.1f;
    draws.cameras.clear();
    bool rejected = false;
    try { coordinator.render(request, frame); } catch (const std::runtime_error&) { rejected = true; }
    require(rejected && draws.cameras.empty() && frame.cancellations == 1 && !frame.open,
            "invalid floor hit was rendered or left a frame open");
    require(std::memcmp(&authored, &request.camera, sizeof(authored)) == 0,
            "failed observer query mutated its authored camera");
  }
}
void lifecycle() {
  StereoScene coordinator;
  Frame frame;
  Draws draws;
  auto request = scene(draws);
  const auto saved = request;
  require(coordinator.render(request, frame), "visible scene skipped");
  require(draws.cameras[0].camera.width == 256 && draws.cameras[0].camera.height == 256,
          "desktop resolution dictated headset camera dimensions");
  require(frame.submissions == 1 && frame.writes == std::vector<unsigned>{0, 1}, "wrong frame transaction");
  require(std::memcmp(&saved.camera, &request.camera, sizeof(EngineCamera)) == 0, "authored camera was changed");
  const auto first = draws.cameras;
  require(std::abs(first[0].camera.position.x + 1.6f) < .0001f &&
          std::abs(first[1].camera.position.x - 1.6f) < .0001f &&
          std::abs(first[0].camera.position.y) < .0001f, "recenter did not preserve runtime IPD");
  draws.cameras.clear();
  for (auto& eye : frame.views.eyes) eye.position[1] += .1f;
  require(coordinator.render(request, frame), "tracked scene skipped");
  require(std::abs(draws.cameras[0].camera.position.y - 4.f) < .0001f, "head leaning was lost");
  draws.cameras.clear(); request.flags = 1;
  require(coordinator.render(request, frame), "recentered scene skipped");
  require(std::abs(draws.cameras[0].camera.position.y) < .0001f, "explicit recenter did not reset leaning");
  draws.cameras.clear(); request.flags = 0;
  for (auto& eye : frame.views.eyes) eye.position[1] += .1f;
  frame.views.input.flags = InputFocused;
  frame.views.input.hands[1].flags = AimValid;
  frame.views.input.hands[1].pressed = Recenter;
  require(coordinator.render(request, frame), "controller recenter skipped");
  require(std::abs(draws.cameras[0].camera.position.y) < .0001f, "controller recenter did not reset leaning");
  draws.cameras.clear(); frame.views.input.flags = 0;
  for (auto& eye : frame.views.eyes) eye.position[1] += .1f;
  require(coordinator.render(request, frame), "unfocused scene skipped");
  require(std::abs(draws.cameras[0].camera.position.y - 4.f) < .0001f,
          "dashboard input recentered the world");
  draws.cameras.clear(); request.flags = 0; frame.visible = false;
  require(!coordinator.render(request, frame) && draws.cameras.empty() && !frame.open, "hidden frame rendered");
}
void levelRecenter() {
  // Recenter position/heading, not gravity. A player who centers while looking
  // down or tilting sideways must see an upright world on sitting upright.
  const float yawAngle = .35f, tilt = .26f;
  const XrQuaternionf yaw{0, std::sin(yawAngle/2), 0, std::cos(yawAngle/2)};
  const XrQuaternionf pitch{std::sin(tilt/2), 0, 0, std::cos(tilt/2)};
  const XrQuaternionf roll{0, 0, std::sin(tilt/2), std::cos(tilt/2)};
  for (unsigned mode = 0; mode < 3; ++mode)
    for (const auto tilted : {pitch, roll, multiply(pitch, roll)}) {
      StereoScene coordinator; Frame frame; Draws draws;
      auto request = scene(draws);
      WorldInputV1 output; request.worldInput = &output;
      const auto original = request.camera;
      const XrVector3f center{.7f, 1.8f, 2.1f};
      const auto setHead = [&](XrQuaternionf orientation) {
        for (unsigned eye = 0; eye < 2; ++eye) {
          auto& view = frame.views.eyes[eye];
          const auto offset = rotate(orientation, {eye ? .04f : -.04f, 0, 0});
          const float sign = eye ? -1.f : 1.f;
          view.orientation[0] = sign*orientation.x; view.orientation[1] = sign*orientation.y;
          view.orientation[2] = sign*orientation.z; view.orientation[3] = sign*orientation.w;
          view.position[0] = center.x + offset.x; view.position[1] = center.y + offset.y;
          view.position[2] = center.z + offset.z;
        }
      };
      if (mode) {
        setHead({0,0,0,1});
        require(coordinator.render(request, frame), "neutral recenter setup failed");
        draws.cameras.clear();
      }
      setHead(multiply(yaw, tilted));
      request.flags = mode == 1 ? SceneRecenter : 0;
      frame.views.input.flags = InputFocused;
      auto& hand = frame.views.input.hands[0];
      hand.flags = AimValid; hand.pressed = mode == 2 ? Recenter : 0;
      hand.orientation[3] = 1;
      require(coordinator.render(request, frame), "tilted recenter failed");
      draws.cameras.clear(); request.flags = 0; hand.pressed = 0;
      setHead(yaw);
      const auto handOffset = rotate(yaw, {.2f, -.1f, -.3f});
      hand.position[0] = center.x+handOffset.x; hand.position[1] = center.y+handOffset.y;
      hand.position[2] = center.z+handOffset.z;
      hand.orientation[0] = yaw.x; hand.orientation[1] = yaw.y;
      hand.orientation[2] = yaw.z; hand.orientation[3] = yaw.w;
      require(coordinator.render(request, frame), "upright recenter recovery failed");
      for (unsigned eye = 0; eye < 2; ++eye) {
        const auto& camera = draws.cameras[eye].camera;
        const auto& matrix = camera.worldToCamera;
        require(std::abs(matrix[2]) < .0001f && std::abs(matrix[5]) < .0001f &&
                std::abs(matrix[8]-1) < .0001f, "recenter tilted the upright forward direction");
        // Remove the asymmetric projection's forward shear before comparing
        // the vertical basis. These tests deliberately use asymmetric FOVs.
        require(std::abs(matrix[1]) < .0001f && matrix[4] > 0,
                "recenter banked the upright horizon");
        require(std::abs(camera.position.x-(eye ? 1.6f : -1.6f)) < .0001f &&
                std::abs(camera.position.y) < .0001f && std::abs(camera.position.z) < .0001f,
                "level recenter lost its seated origin or binocular separation");
      }
      require(output.rayMask == 1 && std::abs(output.rays[0].origin.x-8) < .0001f &&
              std::abs(output.rays[0].origin.y+4) < .0001f &&
              std::abs(output.rays[0].origin.z-12) < .0001f,
              "level recenter gave controllers a different world origin");
      require(std::memcmp(&request.camera, &original, sizeof(original)) == 0,
              "level recenter changed the authored camera");
      // Straight up has no horizontal heading. Retain the previous heading,
      // rather than choosing arbitrary yaw from floating-point noise.
      draws.cameras.clear(); request.flags = SceneRecenter;
      setHead(multiply(yaw, {std::sqrt(.5f), 0, 0, std::sqrt(.5f)}));
      require(coordinator.render(request, frame), "vertical recenter failed");
      draws.cameras.clear(); request.flags = 0; setHead(yaw);
      require(coordinator.render(request, frame), "vertical recenter recovery failed");
      const auto& matrix = draws.cameras[0].camera.worldToCamera;
      require(std::abs(matrix[2]) < .0001f && std::abs(matrix[5]) < .0001f &&
              std::abs(matrix[8]-1) < .0001f, "vertical recenter discarded the previous heading");
    }
}
void mirrorRegions() {
  for (const auto& shape : std::vector<std::array<uint32_t,4>>{
      {1568,1568,1280,800}, {3524,3524,1280,800}, {2048,1600,800,1280},
      {1920,1080,1920,1080}, {3,5,7,11}, {2147483647u,2147483647u,1280,800}}) {
    const auto crop = mirrorCrop(shape[0],shape[1],shape[2],shape[3]);
    require(crop.left >= 0 && crop.top >= 0 && crop.right <= int32_t(shape[0]) &&
            crop.bottom <= int32_t(shape[1]) && crop.right > crop.left && crop.bottom > crop.top,
            "mirror crop escaped the source eye");
    require(std::abs(crop.left-(int32_t(shape[0])-crop.right)) <= 1 &&
            std::abs(crop.top-(int32_t(shape[1])-crop.bottom)) <= 1,
            "mirror crop was not centered");
    const auto width = crop.right-crop.left, height = crop.bottom-crop.top;
    require(std::abs(double(width)*shape[3]-double(height)*shape[2]) <= std::max(shape[2],shape[3]),
            "mirror aspect differed by more than one source pixel");
  }
  for (const auto& shape : std::vector<std::array<uint32_t,4>>{
      {0,256,128,128}, {256,0,128,128}, {256,256,0,128}, {256,256,128,0},
      {UINT32_MAX,256,128,128}, {256,UINT32_MAX,128,128}, {256,256,UINT32_MAX,128}}) {
    try { mirrorCrop(shape[0],shape[1],shape[2],shape[3]); throw 1; }
    catch (const std::invalid_argument&) { }
  }
  Frame frame; Draws draws; StereoScene coordinator;
  auto request = scene(draws); request.flags = SceneMirror;
  require(coordinator.render(request,frame),"mirror flag rejected a valid stereo scene");
  request.flags = 8;
  try { coordinator.render(request,frame); throw 1; } catch (const std::invalid_argument&) { }
  require(frame.submissions == 1 && !frame.open,"unknown scene flag opened a frame");
}
void failures() {
  StereoScene coordinator;
  Frame frame;
  Draws draws;
  auto request = scene(draws);
  request.unitsPerMeter = 0;
  try { coordinator.render(request, frame); throw 1; } catch (const std::invalid_argument&) { }
  require(!frame.open && !frame.cancellations, "invalid request opened a frame");
  request.unitsPerMeter = 40; request.camera.planes[0].distance = 2;
  try { coordinator.render(request, frame); throw 1; } catch (const std::invalid_argument&) { }
  require(!frame.open && frame.cancellations == 1 && draws.cameras.empty(), "invalid camera drew partial eyes");
  request.camera.planes[0].distance = -2; draws.failEye = 1;
  try { coordinator.render(request, frame); throw 1; } catch (const std::runtime_error&) { }
  require(!frame.open && frame.cancellations == 2 && !frame.submissions &&
          frame.writes == std::vector<unsigned>{0}, "failed engine draw submitted an incomplete stereo frame");
  draws.cameras.clear(); draws.failEye = -1;
  require(coordinator.render(request, frame), "coordinator cannot recover after draw failure");
  draws.cameras.clear(); frame.failWrite = true;
  const auto restored = frame.eyeRestores;
  try { coordinator.render(request, frame); throw 1; } catch (const std::runtime_error&) { }
  require(!frame.open && !frame.eyeOpen && frame.eyeRestores == restored + 1,
          "failed eye copy left its target bound");
  frame.failWrite = false; draws.cameras.clear();
  frame.views.eyes[0].width = 1920; frame.views.eyes[0].height = 1800;
  frame.views.eyes[1].width = 2048; frame.views.eyes[1].height = 2000;
  require(coordinator.render(request, frame) && draws.cameras[0].camera.width == 1920 &&
          draws.cameras[0].camera.height == 1800 && draws.cameras[1].camera.width == 2048 &&
          draws.cameras[1].camera.height == 2000, "different recommended eye sizes were ignored");
  draws.cameras.clear(); frame.views.eyes[1].width = 0;
  try { coordinator.render(request, frame); throw 1; } catch (const std::invalid_argument&) { }
  require(draws.cameras.empty() && !frame.eyeOpen && !frame.open,
          "invalid second-eye dimensions partially rendered the frame");
}
void worldInput() {
  StereoScene coordinator;
  Frame frame;
  Draws draws;
  auto request = scene(draws);
  WorldInputV1 output{};
  request.worldInput = &output;
  frame.views.input.flags = InputFocused;
  for (unsigned hand = 0; hand < 2; ++hand) {
    auto& input = frame.views.input.hands[hand];
    input.flags = AimValid;
    input.orientation[3] = 1;
    input.position[0] = .5f + (hand ? .2f : -.2f);
    input.position[1] = 1.4f;
    input.position[2] = 1.8f;
  }
  frame.views.input.hands[1].held = Select;
  require(coordinator.render(request, frame) && output.rayMask == 3,
          "focused tracked hands did not produce world rays");
  require(output.input.hands[1].held == Select &&
          std::abs(output.rays[0].origin.x + 8.f) < .0001f &&
          std::abs(output.rays[1].origin.x - 8.f) < .0001f &&
          std::abs(output.rays[1].origin.y + 8.f) < .0001f &&
          std::abs(output.rays[1].origin.z - 8.f) < .0001f,
          "hands and eyes did not share the recentered world basis");
  require(output.rays[1].nearPoint.z == output.rays[1].origin.z &&
          std::abs(output.rays[1].farPoint.z - output.rays[1].origin.z - 24000.f) < .001f,
          "world picker did not receive a controller-origin segment");
  // Head movement alone must not drag the controller or change its ray origin.
  draws.cameras.clear();
  for (auto& eye : frame.views.eyes) eye.position[0] += .1f;
  require(coordinator.render(request, frame) &&
          std::abs(output.rays[1].origin.x - 8.f) < .0001f,
          "ray used the moving eye rather than the fixed tracking origin");
  draws.cameras.clear(); request.flags = SceneRecenter;
  require(coordinator.render(request, frame) &&
          std::abs(output.rays[1].origin.x - 4.f) < .0001f &&
          std::abs(draws.cameras[1].camera.position.x - 1.6f) < .0001f,
          "eye recenter and controller recenter disagree");
  request.flags = 0; draws.cameras.clear();
  frame.views.input.hands[0].flags = 0;
  require(coordinator.render(request, frame) && output.rayMask == 2 &&
          output.rays[0].farPoint.z == 0, "untracked hand retained its previous ray");
  draws.cameras.clear(); frame.views.input.flags = 0;
  require(coordinator.render(request, frame) && !output.rayMask && !output.input.flags,
          "unfocused world exposed stale controller input");
  draws.cameras.clear(); frame.views.input.flags = InputFocused;
  require(coordinator.render(request, frame) && output.rayMask == 2, "input could not recover");
  draws.cameras.clear(); frame.visible = false;
  require(!coordinator.render(request, frame) && !output.rayMask && !output.input.flags,
          "hidden frame retained world selection");
  frame.visible = true; draws.failEye = 1;
  try { coordinator.render(request, frame); throw 1; } catch (const std::runtime_error&) { }
  require(!output.rayMask && !output.input.flags, "failed stereo frame published world input");
  draws.cameras.clear(); draws.failEye = -1;
  frame.views.input.hands[1].orientation[3] = 0;
  try { coordinator.render(request, frame); throw 1; } catch (const std::invalid_argument&) { }
  require(!output.rayMask && draws.cameras.empty() && !frame.open,
          "invalid aim published input or partially drew stereo");
  output.size = 1;
  try { coordinator.render(request, frame); throw 1; } catch (const std::invalid_argument&) { }
  require(!frame.open, "invalid output ABI opened an XR frame");
}

void transitions() {
  StereoScene coordinator;
  Frame frame;
  Draws draws;
  auto request = scene(draws);
  WorldInputV1 input{};
  request.worldInput = &input;
  frame.views.input.flags = InputFocused;
  frame.views.input.hands[0].flags = AimValid;
  frame.views.input.hands[0].orientation[3] = 1;
  auto render = [&] {
    draws.cameras.clear();
    require(coordinator.render(request, frame), "transition skipped a tracked frame");
    require(frame.visibility.size() == 2 && frame.visibility[0] == frame.visibility[1],
            "eyes have different transition opacity");
    return frame.visibility[0];
  };
  require(render() == 1.f && input.rayMask, "startup incorrectly fades or disables input");
  frame.time += 11000000;
  for (auto& eye : frame.views.eyes) eye.position[0] += 1.f;
  require(render() == 1.f, "head movement caused a camera blink");
  frame.time += 11000000;
  request.camera.position.x += 40.f;
  const auto saved = request.camera;
  require(render() == 0.f && !input.rayMask && !input.input.flags,
          "authored jump was visible or retained world selection");
  require(std::abs(draws.cameras[0].camera.position.x - 78.4f) < .001f,
          "black frame lost the predicted head pose");
  frame.time += 100000000;
  require(std::abs(render() - .5f) < .00001f && !input.rayMask,
          "transition does not use predicted time or permits obscured selection");
  frame.time += 100000000;
  require(render() == 1.f && input.rayMask, "completed fade did not restore world selection");
  require(std::memcmp(&saved, &request.camera, sizeof(saved)) == 0,
          "transition changed the authored camera");
  frame.time += 11000000;
  // 30 degree snap around Y. Do not depend on Euler-angle fields.
  request.camera.worldToCamera = {.8660254f, 0, .5f, 0, 1, 0, -.5f, 0, .8660254f, 0, 0, 0};
  require(render() == 0.f, "authored snap rotation did not blink");
  frame.time += 50000000;
  request.camera.position.z += 40.f;
  require(render() == 0.f, "second cut did not restart the fade");
  draws.failEye = 1;
  try { render(); throw 1; } catch (const std::runtime_error&) { }
  require(!frame.open && !input.rayMask, "failed transition published input or leaked a frame");
  draws.failEye = -1;
  frame.time += 200000000;
  require(render() == 1.f, "failed transition could not recover");

  // Frame-rate independence, normalized projection axes and gentle movement.
  for (const XrTime step : {5000000LL, 20000000LL, 50000000LL}) {
    CameraTransition transition;
    auto camera = scene(draws).camera;
    const XrTime start = 1000000000;
    require(transition.sample(camera, 40, start) == 1.f, "fresh transition is dark");
    camera.position.y += 40;
    for (XrTime offset = 0; offset <= 200000000; offset += step) {
      const float p = float(offset) / 200000000.f;
      require(std::abs(transition.sample(camera, 40, start+step+offset) - p*p*(3-2*p)) < .00001f,
              "camera fade depends on rendering frame rate");
    }
    camera.worldToCamera[0] = 2; camera.worldToCamera[4] = 3; camera.worldToCamera[8] = 4;
    camera.position.x += 4;
    require(transition.sample(camera, 40, start+500000000) == 1.f,
            "projection scale or gentle motion triggered a cut");
    require(transition.sample(camera, 40, start) == 0.f, "clock restart retained stale visibility");
  }
  frame.time = 0;
  try { render(); throw 1; } catch (const std::invalid_argument&) { }
  require(!frame.open && !input.rayMask, "invalid display time retained world ownership");
}

struct Picks {
  Draws draws;
  WorldInputV1 output{};
  WorldTargetV1 target{};
  EngineAimRay ray{};
  unsigned calls = 0;
  int32_t kind = 2;
  bool invalid = false;
  static int32_t GK3HD_XR_CALL draw(void* context, unsigned eye, const EyeCamera* camera) {
    auto& state = *static_cast<Picks*>(context);
    require(state.calls == 1 && !state.output.rayMask && !state.target.kind,
            "reticle pick lagged eyes or published uncompleted input");
    return Draws::draw(&state.draws, eye, camera);
  }
  static int32_t GK3HD_XR_CALL pick(void* context, unsigned hand, const EngineAimRay* ray,
                                   XrVector3f* hit) {
    auto& state = *static_cast<Picks*>(context);
    require(hand == 1 && state.draws.cameras.empty(), "query did not precede both eyes");
    ++state.calls; state.ray = *ray;
    *hit = {ray->origin.x, ray->origin.y, ray->origin.z + (state.invalid ? -40.f : 40.f)};
    return state.kind;
  }
};
void reticles() {
  StereoScene coordinator;
  Frame frame;
  Picks picks;
  auto request = scene(picks.draws);
  request.context = &picks; request.draw = Picks::draw; request.pick = Picks::pick;
  request.worldInput = &picks.output; request.target = &picks.target;
  frame.views.input.flags = InputFocused;
  auto& hand = frame.views.input.hands[1];
  hand.flags = AimValid; hand.orientation[3] = 1;
  hand.position[0] = .5f; hand.position[1] = 1.6f; hand.position[2] = 2;
  require(coordinator.render(request, frame) && picks.target.kind == 2 && picks.target.hand == 1,
          "same-frame target was not completed");
  require(frame.overlays.size() == 2 && picks.calls == 1, "eyes did not share one native hit");
  const auto left = engineReticle(frame.overlays[0], picks.ray, picks.target.point, 40);
  const auto right = engineReticle(frame.overlays[1], picks.ray, picks.target.point, 40);
  require(left.size() == 144 && right.size() == left.size() && left[0].x > right[0].x,
          "reticle used flat desktop coordinates rather than binocular projection");
  require(left[0].z > 0 && left[0].z < 1 && left[0].rhw > 0, "reticle lost scene depth");
  for (int32_t kind : {0, SceneWorldMiss, -1, 4, 2}) {
    picks.draws.cameras.clear(); picks.calls = 0; picks.kind = kind; picks.invalid = kind == 2;
    frame.overlays.clear(); frame.pointers.clear();
    if (kind == 0) {
      require(coordinator.render(request, frame) && !picks.target.kind && frame.overlays.empty(),
              "lost ownership retained previous pointer");
    } else if (kind == SceneWorldMiss) {
      require(coordinator.render(request, frame) && !picks.target.kind &&
              picks.target.hand == UINT32_MAX && frame.overlays.size() == 2 &&
              frame.pointers[0].hand == 1 && !frame.pointers[0].kind,
              "world miss lost its beam or published an invented action target");
    } else {
      try { coordinator.render(request, frame); throw 1; } catch (const std::runtime_error&) { }
      require(!picks.target.kind && !picks.output.rayMask && picks.draws.cameras.empty() && !frame.open,
              "bad native hit published input or rendered partial eyes");
    }
  }
  picks.draws.cameras.clear(); picks.calls = 0; picks.kind = 2; picks.invalid = false;
  frame.overlays.clear(); frame.failOverlay = true;
  try { coordinator.render(request, frame); throw 1; } catch (const std::runtime_error&) { }
  require(!picks.target.kind && !picks.output.rayMask && !frame.open,
          "failed overlay left input valid or frame open");
}
void beams() {
  EngineCamera base{};
  base.worldToCamera = {1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0};
  const XrFovf fov{-.7f, .9f, .8f, -.6f};
  const auto left = engineEyeCamera(base, {{0, 0, 0, 1}, {-.03f, 0, 0}}, fov,
                                    1024, 768, 40, .05f, 100);
  const auto right = engineEyeCamera(base, {{0, 0, 0, 1}, {.03f, 0, 0}}, fov,
                                     1024, 768, 40, .05f, 100);
  const EngineAimRay ray{{-8, -6, 0}, {-8, -6, 0}, {-8, -6, 4000}};
  const XrVector3f hit{-8, -6, 40};
  const auto a = engineBeam(left, ray, &hit, 40);
  const auto b = engineBeam(right, ray, &hit, 40);
  require(a.size() == 6 && b.size() == 6 && a[2].x > b[2].x,
          "beam missing or not independently projected for each eye");
  const auto miss = engineBeam(left, ray, nullptr, 40);
  require(miss.size() == 6 && std::abs(miss[2].rhw-1.f/60.f) < 1e-6f,
          "miss beam reached arbitrary scene far plane rather than 1.5 metres");
  for (const auto& v : miss)
    require(std::isfinite(v.x) && std::isfinite(v.y) && v.z >= -.00001f &&
            v.z <= 1.00001f && v.rhw > 0, "clipped beam produced invalid depth/coordinates");
  const EngineAimRay behind{{-8, -6, -40}, {-8, -6, -40}, {-8, -6, -100}};
  require(engineBeam(left, behind, nullptr, 40).empty(), "beam behind eye was projected");
  const EngineAimRay outside{{-4000, 0, 0}, {-4000, 0, 0}, {-4000, 0, 60}};
  require(engineBeam(left, outside, nullptr, 40).empty(), "beam outside eye frustum was projected");
  const EngineAimRay through{{-8, -6, -40}, {-8, -6, -40}, {-8, -6, 4000}};
  require(engineBeam(left, through, &hit, 40).size() == 6, "near-plane crossing lost visible beam");
  const XrVector3f close{-8, -6, .5f};
  require(engineBeam(left, ray, &close, 40).empty(), "beam inside hand was drawn");
  for (float bad : {0.f, -1.f, INFINITY, NAN}) {
    try { engineBeam(left, ray, &hit, bad); throw 1; }
    catch (const std::invalid_argument&) { }
  }
  const XrVector3f offRay{40, 20, 30};
  try { engineBeam(left, ray, &offRay, 40); throw 1; }
  catch (const std::invalid_argument&) { }
}
struct SharedTransport final : FrameTransport {
  FrameViews input{};
  bool visible = true, open = false, failEnd = false;
  unsigned begins = 0, ends = 0;
  std::vector<std::pair<bool, bool>> layers;
  bool begin(FrameViews& output) override {
    require(!open, "shared frame begun twice");
    ++begins; output = input; open = visible; return visible;
  }
  void end(bool world, const PanelGeometry* panel) override {
    require(open, "shared frame ended twice");
    open = false; ++ends; layers.emplace_back(world, panel != nullptr);
    if (failEnd) throw std::runtime_error("submission failed after consuming frame");
  }
};
void sharedFrames() {
  FrameScheduler frames;
  SharedTransport transport;
  PanelGeometry panel{};
  transport.input.input.hands[0].pressed = Select;
  auto* world = frames.beginWorld(transport);
  require(world && world->input.hands[0].pressed == Select, "world lost sampled input");
  frames.completeWorld();
  // A controller change between hooks belongs to the NEXT game update.
  transport.input.input.hands[0].pressed = Menu;
  require(frames.begin(transport) == world && world->input.hands[0].pressed == Select &&
          transport.begins == 1 && transport.ends == 0, "panel resampled the world frame");
  require(frames.finish(transport, &panel) && !frames.pending() &&
          transport.layers.back() == std::make_pair(true, true), "world and panel were not submitted together");
  require(!frames.finish(transport) && transport.ends == 1, "repeated completion resubmitted a frame");
  require(frames.begin(transport)->input.hands[0].pressed == Menu, "next update lost new input");
  frames.finish(transport, &panel);
  require(transport.layers.back() == std::make_pair(false, true), "panel-only update submitted stale world");
  frames.beginWorld(transport); frames.completeWorld(); frames.finish(transport);
  require(transport.layers.back() == std::make_pair(true, false), "closing panel lost current world");
  frames.beginWorld(transport);
  try { frames.finish(transport, &panel); throw 1; } catch (const std::logic_error&) { }
  require(!frames.pending() && transport.layers.back() == std::make_pair(false, false),
          "incomplete world was submitted");
  frames.beginWorld(transport); frames.completeWorld();
  try { frames.beginWorld(transport); throw 1; } catch (const std::logic_error&) { }
  frames.cancel(transport);
  require(!frames.pending() && !transport.open, "duplicate draw could not be cancelled");
  transport.visible = false;
  const auto before = transport.begins;
  require(!frames.beginWorld(transport) && !frames.begin(transport) && transport.begins == before+1,
          "hidden update waited/synced input twice");
  require(!frames.finish(transport) && !frames.pending(), "hidden update did not retire");
  transport.visible = true;
  frames.beginWorld(transport); frames.completeWorld(); transport.failEnd = true;
  try { frames.finish(transport); throw 1; } catch (const std::runtime_error&) { }
  const auto ended = transport.ends;
  frames.cancel(transport);
  require(!frames.pending() && !transport.open && transport.ends == ended,
          "failed submission was ended twice");
  transport.failEnd = false;
  frames.beginWorld(transport); frames.completeWorld(); frames.finish(transport);
  require(transport.layers.back() == std::make_pair(true, false), "shared scheduler could not recover");
  const auto idleBegins = transport.begins, idleEnds = transport.ends;
  require(frames.blank(transport) && !frames.pending() && !transport.open &&
          transport.begins == idleBegins+1 && transport.ends == idleEnds+1 &&
          transport.layers.back() == std::make_pair(false, false),
          "idle loading boundary did not clear the submitted world/UI");
  frames.beginWorld(transport); frames.completeWorld();
  const auto pendingBegins = transport.begins;
  require(frames.blank(transport) && transport.begins == pendingBegins &&
          transport.layers.back() == std::make_pair(false, false) && !frames.worldReady(),
          "loading resampled or submitted the outgoing pending world");
  frames.beginWorld(transport);
  require(frames.blank(transport) && !frames.pending(), "loading stranded an incomplete world");
  transport.visible = false;
  require(!frames.blank(transport) && !frames.pending(), "hidden loading boundary kept a frame open");
  transport.visible = true; transport.failEnd = true;
  try { frames.blank(transport); throw 1; } catch (const std::runtime_error&) { }
  const auto failedEnds = transport.ends;
  frames.cancel(transport);
  require(!frames.pending() && !transport.open && transport.ends == failedEnds,
          "failed loading clear ended its frame twice");
  transport.failEnd = false;
  frames.beginWorld(transport); frames.completeWorld(); frames.finish(transport);
  require(transport.layers.back() == std::make_pair(true, false), "world could not recover after loading");
}
void loadingOwnership() {
  LoadingFrames loading;
  std::promise<void> entered, release;
  auto enteredFuture = entered.get_future();
  auto releaseFuture = release.get_future().share();
  std::atomic<unsigned> calls{0};
  loading.start([&] {
    if (++calls == 1) entered.set_value();
    releaseFuture.wait(); return true;
  }, {});
  require(enteredFuture.wait_for(std::chrono::seconds(1)) == std::future_status::ready,
          "loading frame owner did not start");
  loading.start([]() -> bool { throw std::runtime_error("duplicate owner"); }, {});
  auto stopping = std::async(std::launch::async, [&] { loading.stop(); });
  require(stopping.wait_for(std::chrono::milliseconds(10)) == std::future_status::timeout,
          "normal rendering returned before the loading frame completed");
  release.set_value(); stopping.get();
  require(!loading.active() && loading.frames() >= 1 && loading.frames() == calls,
          "loading handoff retained an owner, duplicated callbacks or lost its frame");
  loading.stop();
  const auto beforeHidden = loading.frames();
  std::promise<void> second;
  auto secondFuture = second.get_future();
  std::atomic<bool> hiddenEntered{false};
  loading.start([&] { if (!hiddenEntered.exchange(true)) second.set_value(); return false; }, {});
  require(secondFuture.wait_for(std::chrono::seconds(1)) == std::future_status::ready,
          "loading could not restart after a completed handoff");
  loading.stop();
  require(loading.frames() == beforeHidden && !loading.active(), "invisible loading manufactured a submitted frame");

  LoadingFrames failed;
  std::promise<void> reported;
  auto reportedFuture = reported.get_future();
  failed.start([]() -> bool { throw std::runtime_error("runtime stopped"); },
               [&](const std::exception_ptr& error) { require(bool(error), "missing worker failure"); reported.set_value(); });
  require(reportedFuture.wait_for(std::chrono::seconds(1)) == std::future_status::ready,
          "loading runtime failure was not reported");
  try { failed.stop(); throw 1; } catch (const std::runtime_error&) { }
  require(!failed.active() && failed.frames() == 0, "failed loading remained active or fabricated progress");
  try { failed.start([] { return true; }, {}); throw 1; } catch (const std::runtime_error&) { }
  failed.stopNoThrow();
}
void wallLeaning() {
  struct Walls : Draws {
    int result = 1;
    float wall = 20.f;
    unsigned queries = 0;
    bool invalid = false;
    static int32_t GK3HD_XR_CALL query(void* context, const XrVector3f* from,
                                     const XrVector3f* to, XrVector3f* hit) {
      auto& state = *static_cast<Walls*>(context);
      ++state.queries;
      require(from->x == 0 && from->y == 0 && from->z == 0,
              "wall query did not start at the authored interior");
      if (state.result < 0) return state.result;
      if (!state.result || to->x < state.wall) return 0;
      const float t = state.wall/to->x;
      *hit = {state.wall, from->y+(to->y-from->y)*t, from->z+(to->z-from->z)*t};
      if (state.invalid) hit->y += 40;
      return 1;
    }
  } draws;
  StereoScene coordinator;
  Frame frame;
  auto request = scene(draws);
  request.geometry = Walls::query;
  WorldInputV1 input{};
  request.worldInput = &input;
  frame.views.input.flags = InputFocused;
  frame.views.input.hands[1].flags = AimValid;
  frame.views.input.hands[1].orientation[3] = 1;
  const auto saved = request.camera;
  const auto sample = [&](float lean) {
    draws.cameras.clear();
    for (unsigned eye = 0; eye < 2; ++eye)
      frame.views.eyes[eye].position[0] = .5f + (eye ? .04f : -.04f) + lean;
    frame.time += 11111111;
    require(coordinator.render(request, frame), "wall safety suppressed tracked frame submission");
    require(frame.visibility.size() == 2 && frame.visibility[0] == frame.visibility[1],
            "wall fade differed between eyes");
    require(std::memcmp(&saved, &request.camera, sizeof(saved)) == 0,
            "wall safety moved the authored camera");
    require(std::abs(draws.cameras[1].camera.position.x-(lean+.04f)*40) < .001f,
            "wall safety clamped predicted head translation");
    return frame.visibility[0];
  };
  require(sample(0) == 1 && input.rayMask == 2, "clear room hid the world");
  const auto first = sample(.36f); // nearer eye has 10 cm clearance: midpoint fade.
  require(std::abs(first-.5f) < .001f && input.rayMask == 0 && input.input.flags == InputFocused &&
          input.input.hands[1].flags == AimValid,
          "wall approach did not withdraw selection while retaining retreat controls");
  require(sample(.42f) == 0 && input.rayMask == 0 && input.input.flags == InputFocused,
          "near-plane wall crossing exposed the room or disabled retreat");
  require(sample(.8f) == 0 && input.rayMask == 0 && input.input.flags == InputFocused,
          "head through wall revealed the outside or disabled retreat");
  frame.views.input.flags = 0;
  require(sample(.8f) == 0 && !input.rayMask && !input.input.flags,
          "unfocused wall fade retained navigation controls");
  frame.views.input.flags = InputFocused;
  require(std::abs(sample(.36f)-first) < .001f && sample(0) == 1 && input.rayMask == 2,
          "wall retreat did not recover the same smooth curve and input");
  draws.result = 0;
  require(sample(.8f) == 1, "open space was treated as a wall");
  for (const bool invalid : {false, true}) {
    draws.cameras.clear(); draws.result = invalid ? 1 : -1; draws.invalid = invalid;
    const auto submissions = frame.submissions, cancellations = frame.cancellations;
    try { sample(.8f); throw 1; } catch (const std::runtime_error&) { }
    require(frame.submissions == submissions && frame.cancellations == cancellations+1 &&
            draws.cameras.empty() && input.rayMask == 0 && !frame.open,
            "invalid geometry query drew/published partial world input");
  }
  draws.result = 1; draws.invalid = false;
  require(sample(0) == 1 && input.rayMask == 2, "failed query left wall safety stuck");
  require(draws.queries > 10, "wall queries did not cover both eye positions");
}
void closeAuthoredCamera() {
  struct Surface {
    float x = 0;
    bool hole = false;
    static int32_t GK3HD_XR_CALL query(void* context, const XrVector3f* from,
                                     const XrVector3f* to, XrVector3f* hit) {
      const auto& surface = *static_cast<Surface*>(context);
      const float dx = to->x-from->x;
      if (surface.hole || dx <= 0) return 0;
      const float t = (surface.x-from->x)/dx;
      if (t < 0 || t > 1) return 0;
      *hit = {surface.x, from->y+(to->y-from->y)*t, from->z+(to->z-from->z)*t};
      return 1;
    }
  } surface;
  // A camera 25 cm from a surface must remain usable at neutral tracking.
  // Its nonzero world origin and world-unit calibration must not affect the
  // physical fade distance. Both eyes follow the nearer eye, not separate fades.
  for (const float units : {20.f, 40.f, 80.f}) {
    SceneV1 request{};
    request.unitsPerMeter = units;
    request.camera.position = {277.f, 62.f, -49.f};
    request.context = &surface;
    request.geometry = Surface::query;
    surface.x = request.camera.position.x + .25f*units;
    surface.hole = false;
    const auto saved = request.camera;
    std::array<EyeCamera, 2> eyes{};
    const auto sample = [&](float lean) {
      for (unsigned eye = 0; eye < 2; ++eye)
        eyes[eye].camera.position = {request.camera.position.x + (lean+(eye ? .032f : -.032f))*units,
                                    request.camera.position.y, request.camera.position.z};
      const auto visibility = wallVisibility(request, eyes, .05f, request.camera);
      require(std::memcmp(&request.camera, &saved, sizeof(saved)) == 0,
              "close-camera protection modified its authored origin");
      return visibility;
    };
    require(sample(0) == 1.f, "nearby authored surface hid the neutral camera");
    const auto approach = sample(.118f);
    require(std::abs(approach-.5f) < .001f, "close-camera fade changed with world calibration");
    require(sample(.17f) == 0.f && sample(.3f) == 0.f,
            "close-camera near-plane crossing exposed the surface's far side");
    require(std::abs(sample(.118f)-approach) < .001f && sample(0) == 1.f,
            "close-camera retreat retained an obsolete obstacle fade");
    surface.hole = true;
    require(sample(.3f) == 1.f, "native transparent-hole result still faded the world");
    surface.hole = false;
    require(sample(.3f) == 0.f, "restored opaque surface retained a transparent-hole result");
  }
}
} // namespace
int main() {
  try {
    lifecycle(); observerPlacement(); levelRecenter(); mirrorRegions(); failures(); worldInput(); transitions(); wallLeaning(); closeAuthoredCamera(); sharedFrames(); loadingOwnership(); reticles(); beams();
    std::cout << "Scene coordinator passed: tracked eyes, explicit/controller recentering, focus guards, hidden frames, draw failure, unchanged authored camera\n";
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
  catch (...) { std::cerr << "expected scene error was not reported\n"; return 1; }
}
