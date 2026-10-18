#include "input.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

namespace gk3hd::vr {
namespace {
void check(XrResult result, const char* operation) {
  if (result != XR_SUCCESS)
    throw std::runtime_error(std::string(operation) + " failed (OpenXR "
                             + std::to_string(result) + ")");
}
template<size_t N> void copyName(char (&target)[N], const char* text) {
  const auto length = std::strlen(text);
  if (length >= N) throw std::invalid_argument("OpenXR action name is too long");
  std::copy_n(text, length + 1, target);
}
bool validPose(const XrSpaceLocation& location) {
  constexpr auto valid = XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_VALID_BIT;
  const auto& p = location.pose.position;
  const auto& q = location.pose.orientation;
  const float norm = q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w;
  return (location.locationFlags & valid) == valid && std::isfinite(p.x) &&
    std::isfinite(p.y) && std::isfinite(p.z) && std::isfinite(norm) && norm > 1e-12f;
}
} // namespace

Actions::Actions(PFN_xrGetInstanceProcAddr resolve) : resolve_(resolve) {
  if (!resolve_) throw std::invalid_argument("OpenXR input resolver is missing");
}
Actions::~Actions() { shutdown(); }
template<typename T> void Actions::load(const char* name, T& target) {
  PFN_xrVoidFunction value = nullptr;
  check(resolve_(instance_, name, &value), name);
  if (!value) throw std::runtime_error(std::string("OpenXR input function missing: ") + name);
  target = reinterpret_cast<T>(value);
}
XrPath Actions::path(const char* value) {
  XrPath result = XR_NULL_PATH;
  check(stringToPath_(instance_, value, &result), value);
  return result;
}
XrAction Actions::action(const char* name, const char* title, XrActionType type) {
  XrActionCreateInfo info{XR_TYPE_ACTION_CREATE_INFO};
  copyName(info.actionName, name);
  copyName(info.localizedActionName, title);
  info.actionType = type;
  info.countSubactionPaths = 2;
  info.subactionPaths = hands_.data();
  XrAction result = XR_NULL_HANDLE;
  check(createAction_(set_, &info, &result), "create input action");
  return result;
}
void Actions::initialize(XrInstance instance) {
  if (!instance || instance_) throw std::logic_error("invalid input initialization");
  instance_ = instance;
  try {
    load("xrDestroyActionSet", destroySet_);
    load("xrStringToPath", stringToPath_);
    load("xrCreateActionSet", createSet_);
    load("xrCreateAction", createAction_);
    load("xrSuggestInteractionProfileBindings", suggest_);
    load("xrAttachSessionActionSets", attach_);
    load("xrCreateActionSpace", createSpace_);
    load("xrDestroySpace", destroySpace_);
    load("xrSyncActions", sync_);
    load("xrGetActionStateBoolean", boolean_);
    load("xrGetActionStatePose", pose_);
    load("xrGetActionStateVector2f", vector_);
    load("xrLocateSpace", locate_);
    hands_ = {path("/user/hand/left"), path("/user/hand/right")};
    XrActionSetCreateInfo info{XR_TYPE_ACTION_SET_CREATE_INFO};
    copyName(info.actionSetName, "gk3hd");
    copyName(info.localizedActionSetName, "GK3HD");
    check(createSet_(instance_, &info, &set_), "create input action set");
    aim_ = action("aim", "Point", XR_ACTION_TYPE_POSE_INPUT);
    stick_ = action("stick", "Navigate camera", XR_ACTION_TYPE_VECTOR2F_INPUT);
    const char* names[]{"select", "cancel", "menu", "inventory", "recenter"};
    const char* titles[]{"Select", "Back", "Menu", "Inventory", "Recenter"};
    for (unsigned i = 0; i < buttons_.size(); ++i)
      buttons_[i] = action(names[i], titles[i], XR_ACTION_TYPE_BOOLEAN_INPUT);
    bindings();
  } catch (...) { shutdown(); throw; }
}
void Actions::bindings() {
  // Core 1.0 allowlisted components. Never bind reserved system/dashboard keys.
  struct Profile {
    const char* name;
    const char* select;
    const char* cancel[2];
    const char* menu[2];
    const char* inventory[2];
    const char* recenter;
    const char* stick;
  };
  const Profile profiles[]{
    {"khr/simple_controller", "select/click", {nullptr, "menu/click"},
     {"menu/click", nullptr}, {nullptr, nullptr}, nullptr, nullptr},
    {"oculus/touch_controller", "trigger/value", {"y/click", "b/click"},
     {"menu/click", nullptr}, {"x/click", "a/click"}, "thumbstick/click", "thumbstick"},
    {"valve/index_controller", "trigger/value", {nullptr, "b/click"},
     {"b/click", nullptr}, {"a/click", "a/click"}, "thumbstick/click", "thumbstick"},
    {"microsoft/motion_controller", "trigger/value", {"trackpad/click", "trackpad/click"},
     {"menu/click", "menu/click"}, {"squeeze/click", "squeeze/click"}, "thumbstick/click", "thumbstick"},
    {"htc/vive_controller", "trigger/click", {"squeeze/click", "squeeze/click"},
     {"menu/click", nullptr}, {nullptr, "menu/click"}, "trackpad/click", "trackpad"}
  };
  for (const auto& profile : profiles) {
    std::vector<XrActionSuggestedBinding> bindings;
    for (unsigned hand = 0; hand < 2; ++hand) {
      const std::string prefix = hand ? "/user/hand/right/input/" : "/user/hand/left/input/";
      const auto bind = [&](XrAction value, const char* component) {
        if (component) bindings.push_back({value, path((prefix + component).c_str())});
      };
      bind(aim_, "aim/pose"); bind(stick_, profile.stick);
      bind(buttons_[0], profile.select); bind(buttons_[1], profile.cancel[hand]);
      bind(buttons_[2], profile.menu[hand]); bind(buttons_[3], profile.inventory[hand]);
      bind(buttons_[4], profile.recenter);
    }
    XrInteractionProfileSuggestedBinding info{XR_TYPE_INTERACTION_PROFILE_SUGGESTED_BINDING};
    info.interactionProfile = path((std::string("/interaction_profiles/") + profile.name).c_str());
    info.countSuggestedBindings = static_cast<uint32_t>(bindings.size());
    info.suggestedBindings = bindings.data();
    // These are core allowlisted paths. A runtime must accept valid suggestions
    // even for absent hardware. Do not hide typos as an unsupported controller.
    check(suggest_(instance_, &info), "suggest input bindings");
  }
}
void Actions::attach(XrSession session) {
  if (!set_ || !session || session_) throw std::logic_error("invalid input session attachment");
  XrSessionActionSetsAttachInfo info{XR_TYPE_SESSION_ACTION_SETS_ATTACH_INFO};
  info.countActionSets = 1; info.actionSets = &set_;
  check(attach_(session, &info), "attach input action set");
  session_ = session;
  try {
    for (unsigned hand = 0; hand < 2; ++hand) {
      XrActionSpaceCreateInfo space{XR_TYPE_ACTION_SPACE_CREATE_INFO};
      space.action = aim_; space.subactionPath = hands_[hand];
      space.poseInActionSpace.orientation.w = 1.f;
      check(createSpace_(session_, &space, &spaces_[hand]), "create pointing space");
    }
  } catch (...) { closeSession(); throw; }
}
InputSnapshot Actions::sample(XrSpace base, XrTime displayTime, bool focused) {
  if (!session_ || !base || displayTime <= 0) throw std::logic_error("invalid input sample");
  InputSnapshot result{};
  if (!focused) { reset(); return result; }
  try {
    const XrActiveActionSet activeSet{set_, XR_NULL_PATH};
    XrActionsSyncInfo sync{XR_TYPE_ACTIONS_SYNC_INFO};
    sync.countActiveActionSets = 1; sync.activeActionSets = &activeSet;
    const auto synced = sync_(session_, &sync);
    if (synced == XR_SESSION_NOT_FOCUSED || synced == XR_SESSION_LOSS_PENDING) {
      reset(); return result;
    }
    check(synced, "sync input actions");
    result.flags = InputFocused;
    for (unsigned hand = 0; hand < 2; ++hand) {
      auto& latch = latches_[hand];
      auto& output = result.hands[hand];
      XrActionStateGetInfo get{XR_TYPE_ACTION_STATE_GET_INFO};
      get.subactionPath = hands_[hand]; get.action = aim_;
      XrActionStatePose pose{XR_TYPE_ACTION_STATE_POSE};
      check(pose_(session_, &get, &pose), "pointing action");
      XrSpaceLocation location{XR_TYPE_SPACE_LOCATION};
      if (pose.isActive) check(locate_(spaces_[hand], base, displayTime, &location), "locate pointer");
      if (!pose.isActive || !validPose(location)) { latch = {}; continue; }
      output.flags = AimValid;
      const auto& p = location.pose.position;
      const auto& q = location.pose.orientation;
      const float norm = std::sqrt(q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w);
      const float orientation[]{q.x/norm, q.y/norm, q.z/norm, q.w/norm};
      std::copy_n(orientation, 4, output.orientation);
      output.position[0] = p.x; output.position[1] = p.y; output.position[2] = p.z;
      uint32_t held = 0, active = 0;
      for (unsigned button = 0; button < buttons_.size(); ++button) {
        get.action = buttons_[button];
        XrActionStateBoolean state{XR_TYPE_ACTION_STATE_BOOLEAN};
        check(boolean_(session_, &get, &state), "button action");
        if (state.isActive) active |= 1u << button;
        if (state.isActive && state.currentState) held |= 1u << button;
      }
      if (!latch.valid) latch.blocked |= held;
      latch.blocked |= held & ~latch.active;
      latch.blocked &= held;
      output.held = held & ~latch.blocked;
      output.pressed = output.held & ~latch.previous;
      latch.previous = output.held; latch.active = active; latch.valid = true;
      get.action = stick_;
      XrActionStateVector2f stick{XR_TYPE_ACTION_STATE_VECTOR2F};
      check(vector_(session_, &get, &stick), "camera stick action");
      if (stick.isActive && std::isfinite(stick.currentState.x) && std::isfinite(stick.currentState.y)) {
        const float x = std::clamp(stick.currentState.x, -1.f, 1.f);
        const float y = std::clamp(stick.currentState.y, -1.f, 1.f);
        if (x*x + y*y <= .04f) latch.stickArmed = true;
        if (latch.stickArmed) { output.stick[0] = x; output.stick[1] = y; }
      } else { latch.stickArmed = false; }
    }
    return result;
  } catch (...) { reset(); throw; }
}
void Actions::reset() noexcept { latches_ = {}; }
void Actions::closeSession() noexcept {
  for (auto& space : spaces_) {
    if (space && destroySpace_) destroySpace_(space);
    space = XR_NULL_HANDLE;
  }
  session_ = XR_NULL_HANDLE;
  reset();
}
void Actions::shutdown() noexcept {
  closeSession();
  if (set_ && destroySet_) destroySet_(set_);
  set_ = XR_NULL_HANDLE; instance_ = XR_NULL_HANDLE;
  aim_ = stick_ = XR_NULL_HANDLE; buttons_ = {}; hands_ = {};
}

} // namespace gk3hd::vr
