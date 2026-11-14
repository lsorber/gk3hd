#include "controller_actions.h"
#include <cmath>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

namespace gk3hd::standalone::openxr {
namespace {
template <class T> T typed(XrStructureType type) {
  T value{};
  value.type = type;
  return value;
}
void check(XrResult value, const char *operation) {
  if (XR_FAILED(value))
    throw std::runtime_error(std::string(operation) + " (OpenXR " +
                             std::to_string(value) + ")");
}
void require(bool value, const char *text) {
  if (!value)
    throw std::logic_error(text);
}
template <size_t N> void name(char (&target)[N], const char *text) {
  const auto length = std::strlen(text);
  require(length < N, "Native action name too long");
  std::memcpy(target, text, length + 1);
}
} // namespace
template <class T> void ControllerActions::load(const char *name, T &target) {
  PFN_xrVoidFunction value = nullptr;
  check(resolve_(instance_, name, &value), name);
  require(value != nullptr, "Missing native input function");
  target = reinterpret_cast<T>(value);
}
XrPath ControllerActions::path(const char *text) {
  XrPath value = XR_NULL_PATH;
  check(stringToPath_(instance_, text, &value), text);
  return value;
}
XrAction ControllerActions::action(const char *id, const char *title,
                                   XrActionType type) {
  auto info = typed<XrActionCreateInfo>(XR_TYPE_ACTION_CREATE_INFO);
  name(info.actionName, id);
  name(info.localizedActionName, title);
  info.actionType = type;
  info.countSubactionPaths = 2;
  info.subactionPaths = hands_.data();
  XrAction value = XR_NULL_HANDLE;
  check(createAction_(set_, &info, &value), "Create native input action");
  return value;
}
ControllerActions::ControllerActions(PFN_xrGetInstanceProcAddr resolve,
                                     XrInstance instance)
    : resolve_(resolve), instance_(instance) {
  require(resolve && instance, "Missing native input instance/resolver");
#define LOAD(api, field) load(api, field)
  LOAD("xrStringToPath", stringToPath_);
  LOAD("xrCreateActionSet", createSet_);
  LOAD("xrDestroyActionSet", destroySet_);
  LOAD("xrCreateAction", createAction_);
  LOAD("xrSuggestInteractionProfileBindings", suggest_);
  LOAD("xrAttachSessionActionSets", attach_);
  LOAD("xrCreateActionSpace", createSpace_);
  LOAD("xrDestroySpace", destroySpace_);
  LOAD("xrSyncActions", sync_);
  LOAD("xrGetActionStateBoolean", boolean_);
  LOAD("xrGetActionStateFloat", float_);
  LOAD("xrGetActionStateVector2f", vector_);
  LOAD("xrGetActionStatePose", pose_);
  LOAD("xrLocateSpace", locate_);
#undef LOAD
  try {
    hands_ = {path("/user/hand/left"), path("/user/hand/right")};
    auto info = typed<XrActionSetCreateInfo>(XR_TYPE_ACTION_SET_CREATE_INFO);
    name(info.actionSetName, "gk3hd_host");
    name(info.localizedActionSetName, "GK3HD physical controllers");
    check(createSet_(instance_, &info, &set_), "Create native input set");
    aim_ = action("aim", "Pointing pose", XR_ACTION_TYPE_POSE_INPUT);
    grip_ = action("grip", "Holding pose", XR_ACTION_TYPE_POSE_INPUT);
    stick_ = action("stick", "Thumbstick", XR_ACTION_TYPE_VECTOR2F_INPUT);
    trigger_ = action("trigger", "Trigger value", XR_ACTION_TYPE_FLOAT_INPUT);
    squeeze_ = action("squeeze", "Grip value", XR_ACTION_TYPE_FLOAT_INPUT);
    select_ = action("select", "Select button", XR_ACTION_TYPE_BOOLEAN_INPUT);
    const char *ids[] = {"primary", "secondary", "menu", "stick_click"};
    const char *titles[] = {"Primary button", "Secondary button", "Menu button",
                            "Thumbstick click"};
    for (unsigned i = 0; i < 4; ++i)
      buttons_[i] = action(ids[i], titles[i], XR_ACTION_TYPE_BOOLEAN_INPUT);
    bindings();
  } catch (...) {
    try {
      close();
    } catch (...) {
    }
    throw;
  }
}
ControllerActions::~ControllerActions() {
  try {
    close();
  } catch (...) {
  }
}
void ControllerActions::bindings() {
  for (bool simple : {false, true}) {
    std::vector<XrActionSuggestedBinding> bindings;
    for (unsigned hand = 0; hand < 2; ++hand) {
      const std::string prefix =
          hand ? "/user/hand/right/input/" : "/user/hand/left/input/";
      const auto bind = [&](XrAction value, const char *component) {
        bindings.push_back({value, path((prefix + component).c_str())});
      };
      bind(aim_, "aim/pose");
      bind(grip_, "grip/pose");
      if (simple) {
        bind(select_, "select/click");
        bind(buttons_[hand ? 1 : 2], "menu/click");
      } else {
        bind(stick_, "thumbstick");
        bind(trigger_, "trigger/value");
        bind(squeeze_, "squeeze/value");
        bind(buttons_[0], hand ? "a/click" : "x/click");
        bind(buttons_[1], hand ? "b/click" : "y/click");
        bind(buttons_[3], "thumbstick/click");
        // The right system/dashboard button belongs to the runtime.
        if (!hand)
          bind(buttons_[2], "menu/click");
      }
    }
    auto info = typed<XrInteractionProfileSuggestedBinding>(
        XR_TYPE_INTERACTION_PROFILE_SUGGESTED_BINDING);
    info.interactionProfile =
        path(simple ? "/interaction_profiles/khr/simple_controller"
                    : "/interaction_profiles/oculus/touch_controller");
    info.countSuggestedBindings = uint32_t(bindings.size());
    info.suggestedBindings = bindings.data();
    check(suggest_(instance_, &info), "Suggest native controller bindings");
  }
}
void ControllerActions::attach(XrSession session) {
  require(set_ && session && !session_,
          "Invalid native input session attachment");
  auto info = typed<XrSessionActionSetsAttachInfo>(
      XR_TYPE_SESSION_ACTION_SETS_ATTACH_INFO);
  info.countActionSets = 1;
  info.actionSets = &set_;
  check(attach_(session, &info), "Attach native input set");
  session_ = session;
  try {
    for (unsigned hand = 0; hand < 2; ++hand)
      for (unsigned kind = 0; kind < 2; ++kind) {
        auto create =
            typed<XrActionSpaceCreateInfo>(XR_TYPE_ACTION_SPACE_CREATE_INFO);
        create.action = kind ? grip_ : aim_;
        create.subactionPath = hands_[hand];
        create.poseInActionSpace.orientation.w = 1;
        check(createSpace_(session_, &create, &spaces_[hand][kind]),
              "Create native hand space");
      }
  } catch (...) {
    try {
      detach();
    } catch (...) {
    }
    throw;
  }
}
void ControllerActions::detach() {
  for (auto &hand : spaces_)
    for (auto &space : hand)
      if (space) {
        check(destroySpace_(space), "Destroy native hand space");
        space = XR_NULL_HANDLE;
      }
  session_ = XR_NULL_HANDLE;
}
void ControllerActions::close() {
  detach();
  if (set_) {
    check(destroySet_(set_), "Destroy native input set");
    set_ = XR_NULL_HANDLE;
  }
}
XrSpaceLocation ControllerActions::locate(XrAction action, XrSpace space,
                                          XrPath hand, XrSpace base,
                                          XrTime time) {
  auto get = typed<XrActionStateGetInfo>(XR_TYPE_ACTION_STATE_GET_INFO);
  get.action = action;
  get.subactionPath = hand;
  auto active = typed<XrActionStatePose>(XR_TYPE_ACTION_STATE_POSE);
  check(pose_(session_, &get, &active), "Read native pose activity");
  auto out = typed<XrSpaceLocation>(XR_TYPE_SPACE_LOCATION);
  if (!active.isActive)
    return out;
  const auto result = locate_(space, base, time, &out);
  check(result, "Locate native controller");
  if (result != XR_SUCCESS)
    return typed<XrSpaceLocation>(XR_TYPE_SPACE_LOCATION);
  out.locationFlags &= 15;
  auto &p = out.pose.position;
  auto &q = out.pose.orientation;
  if (!(out.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT))
    q = {0, 0, 0, 1};
  if (!(out.locationFlags & XR_SPACE_LOCATION_POSITION_VALID_BIT))
    p = {0, 0, 0};
  const float norm = q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w;
  if (!std::isfinite(p.x) || !std::isfinite(p.y) || !std::isfinite(p.z) ||
      !std::isfinite(norm) || std::abs(norm - 1) > .001f)
    return typed<XrSpaceLocation>(XR_TYPE_SPACE_LOCATION);
  return out;
}
bool ControllerActions::button(XrAction action, XrPath hand) {
  auto get = typed<XrActionStateGetInfo>(XR_TYPE_ACTION_STATE_GET_INFO);
  get.action = action;
  get.subactionPath = hand;
  auto out = typed<XrActionStateBoolean>(XR_TYPE_ACTION_STATE_BOOLEAN);
  check(boolean_(session_, &get, &out), "Read native button");
  return out.isActive && out.currentState;
}
float ControllerActions::scalar(XrAction action, XrPath hand, bool &active) {
  auto get = typed<XrActionStateGetInfo>(XR_TYPE_ACTION_STATE_GET_INFO);
  get.action = action;
  get.subactionPath = hand;
  auto out = typed<XrActionStateFloat>(XR_TYPE_ACTION_STATE_FLOAT);
  check(float_(session_, &get, &out), "Read native scalar");
  active = out.isActive != 0;
  if (!active)
    return 0;
  require(std::isfinite(out.currentState) && out.currentState >= 0 &&
              out.currentState <= 1,
          "Invalid native trigger/grip value");
  return out.currentState;
}
std::array<ControllerActions::Hand, 2>
ControllerActions::sample(XrSpace base, XrTime time, bool focused) {
  require(session_ && base && time > 0, "Invalid native controller sample");
  std::array<Hand, 2> out{};
  if (!focused)
    return out;
  const XrActiveActionSet active{set_, XR_NULL_PATH};
  auto sync = typed<XrActionsSyncInfo>(XR_TYPE_ACTIONS_SYNC_INFO);
  sync.countActiveActionSets = 1;
  sync.activeActionSets = &active;
  const auto result = sync_(session_, &sync);
  if (result == XR_SESSION_NOT_FOCUSED || result == XR_SESSION_LOSS_PENDING)
    return out;
  check(result, "Sync native input actions");
  for (unsigned hand = 0; hand < 2; ++hand) {
    auto &value = out[hand];
    const auto user = hands_[hand];
    value.aim = locate(aim_, spaces_[hand][0], user, base, time);
    value.grip = locate(grip_, spaces_[hand][1], user, base, time);
    auto get = typed<XrActionStateGetInfo>(XR_TYPE_ACTION_STATE_GET_INFO);
    get.action = stick_;
    get.subactionPath = user;
    auto stick = typed<XrActionStateVector2f>(XR_TYPE_ACTION_STATE_VECTOR2F);
    check(vector_(session_, &get, &stick), "Read native thumbstick");
    if (stick.isActive) {
      require(std::isfinite(stick.currentState.x) &&
                  std::isfinite(stick.currentState.y) &&
                  std::abs(stick.currentState.x) <= 1 &&
                  std::abs(stick.currentState.y) <= 1,
              "Invalid native thumbstick");
      value.stick = stick.currentState;
    }
    bool analog = false;
    value.trigger = scalar(trigger_, user, analog);
    if (!analog)
      value.trigger = button(select_, user) ? 1.f : 0.f;
    bool squeezeActive = false;
    value.squeeze = scalar(squeeze_, user, squeezeActive);
    for (unsigned i = 0; i < 4; ++i)
      if (button(buttons_[i], user))
        value.buttons |= 1u << i;
    if (value.trigger > .7f)
      value.buttons |= Trigger;
    if (value.squeeze > .7f)
      value.buttons |= Grip;
  }
  return out;
}
} // namespace gk3hd::standalone::openxr
