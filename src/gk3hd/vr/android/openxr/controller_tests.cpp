#include "controller_actions.h"
#include <cmath>
#include <cstring>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

using gk3hd::standalone::openxr::ControllerActions;
namespace {
void require(bool value, const char *text) {
  if (!value)
    throw std::runtime_error(text);
}
template <class T> T handle(uintptr_t value) { return (T)value; }
struct Fake {
  static Fake *active;
  std::map<std::string, XrPath> paths;
  std::map<XrPath, std::string> strings;
  std::map<XrAction, std::string> actions;
  struct Space {
    unsigned hand;
    bool grip;
  };
  std::map<XrSpace, Space> spaces;
  std::map<std::string, std::vector<std::pair<std::string, std::string>>>
      suggestions;
  unsigned syncs = 0, destroyedSpaces = 0, destroyedSets = 0, createdSpaces = 0;
  bool controls = true, analog = true, aimActive = true, gripActive = true,
       badAim = false, failSuggestion = false;
  unsigned failSpace = 0;
  XrResult syncResult = XR_SUCCESS;
  Fake() { active = this; }
  XrPath intern(const char *text) {
    const auto found = paths.find(text);
    if (found != paths.end())
      return found->second;
    const XrPath value = paths.size() + 1;
    paths[text] = value;
    strings[value] = text;
    return value;
  }
  unsigned hand(XrPath path) {
    const auto &text = strings.at(path);
    require(text == "/user/hand/left" || text == "/user/hand/right",
            "Wrong native hand path");
    return text == "/user/hand/right" ? 1 : 0;
  }
  static XrResult XRAPI_CALL path(XrInstance, const char *text, XrPath *out) {
    *out = active->intern(text);
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL createSet(XrInstance,
                                       const XrActionSetCreateInfo *,
                                       XrActionSet *out) {
    *out = handle<XrActionSet>(1);
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL destroySet(XrActionSet) {
    ++active->destroyedSets;
    require(active->spaces.empty(),
            "Input set destroyed before its hand spaces");
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL createAction(XrActionSet,
                                          const XrActionCreateInfo *info,
                                          XrAction *out) {
    require(info->countSubactionPaths == 2 &&
                active->hand(info->subactionPaths[0]) == 0 &&
                active->hand(info->subactionPaths[1]) == 1,
            "Input action did not preserve both hand paths");
    *out = handle<XrAction>(active->actions.size() + 100);
    active->actions[*out] = info->actionName;
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL
  suggest(XrInstance, const XrInteractionProfileSuggestedBinding *info) {
    if (active->failSuggestion)
      return XR_ERROR_PATH_UNSUPPORTED;
    auto &values =
        active->suggestions[active->strings.at(info->interactionProfile)];
    for (unsigned i = 0; i < info->countSuggestedBindings; ++i) {
      const auto &item = info->suggestedBindings[i];
      values.emplace_back(active->actions.at(item.action),
                          active->strings.at(item.binding));
    }
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL attach(XrSession,
                                    const XrSessionActionSetsAttachInfo *info) {
    require(info->countActionSets == 1 &&
                info->actionSets[0] == handle<XrActionSet>(1),
            "Wrong input set attachment");
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL createSpace(XrSession,
                                         const XrActionSpaceCreateInfo *info,
                                         XrSpace *out) {
    ++active->createdSpaces;
    if (active->createdSpaces == active->failSpace)
      return XR_ERROR_RUNTIME_FAILURE;
    require(info->poseInActionSpace.orientation.w == 1 &&
                info->poseInActionSpace.position.x == 0,
            "Invented hand-space calibration");
    const auto &name = active->actions.at(info->action);
    require(name == "aim" || name == "grip", "Unknown native pose action");
    *out = handle<XrSpace>(700 + active->createdSpaces);
    active->spaces[*out] = {active->hand(info->subactionPath), name == "grip"};
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL destroySpace(XrSpace value) {
    require(active->spaces.erase(value) == 1, "Hand space retired twice");
    ++active->destroyedSpaces;
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL sync(XrSession, const XrActionsSyncInfo *info) {
    ++active->syncs;
    require(info->countActiveActionSets == 1 &&
                info->activeActionSets[0].actionSet == handle<XrActionSet>(1),
            "Wrong synced action set");
    return active->syncResult;
  }
  static XrResult XRAPI_CALL boolean(XrSession,
                                     const XrActionStateGetInfo *info,
                                     XrActionStateBoolean *out) {
    const auto &name = active->actions.at(info->action);
    active->hand(info->subactionPath);
    out->isActive = active->controls;
    out->currentState = name == "primary" || name == "select";
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL scalar(XrSession, const XrActionStateGetInfo *info,
                                    XrActionStateFloat *out) {
    const auto &name = active->actions.at(info->action);
    const auto hand = active->hand(info->subactionPath);
    out->isActive = active->controls && active->analog;
    out->currentState =
        name == "trigger" ? (hand ? .2f : .75f) : (hand ? .1f : .9f);
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL vector(XrSession, const XrActionStateGetInfo *info,
                                    XrActionStateVector2f *out) {
    require(active->actions.at(info->action) == "stick",
            "Wrong thumbstick action");
    const auto hand = active->hand(info->subactionPath);
    out->isActive = active->controls;
    out->currentState = {hand ? .25f : -.25f, .5f};
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL pose(XrSession, const XrActionStateGetInfo *info,
                                  XrActionStatePose *out) {
    const auto &name = active->actions.at(info->action);
    active->hand(info->subactionPath);
    out->isActive = name == "aim" ? active->aimActive : active->gripActive;
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL locate(XrSpace space, XrSpace base, XrTime time,
                                    XrSpaceLocation *out) {
    require(base == handle<XrSpace>(500) && time == 1'000'000'000,
            "Controller did not use actual frame time/reference");
    const auto value = active->spaces.at(space);
    out->locationFlags = value.grip ? 3 : 15;
    out->pose.position = {float(value.hand * 10 + (value.grip ? 2 : 1)), 1, -2};
    out->pose.orientation.w = active->badAim && !value.grip ? 0.f : 1.f;
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL resolve(XrInstance, const char *name,
                                     PFN_xrVoidFunction *out) {
#define BIND(api, fn)                                                          \
  do {                                                                         \
    if (std::strcmp(name, api) == 0) {                                         \
      *out = reinterpret_cast<PFN_xrVoidFunction>(fn);                         \
      return XR_SUCCESS;                                                       \
    }                                                                          \
  } while (false)
    BIND("xrStringToPath", path);
    BIND("xrCreateActionSet", createSet);
    BIND("xrDestroyActionSet", destroySet);
    BIND("xrCreateAction", createAction);
    BIND("xrSuggestInteractionProfileBindings", suggest);
    BIND("xrAttachSessionActionSets", attach);
    BIND("xrCreateActionSpace", createSpace);
    BIND("xrDestroySpace", destroySpace);
    BIND("xrSyncActions", sync);
    BIND("xrGetActionStateBoolean", boolean);
    BIND("xrGetActionStateFloat", scalar);
    BIND("xrGetActionStateVector2f", vector);
    BIND("xrGetActionStatePose", pose);
    BIND("xrLocateSpace", locate);
#undef BIND
    *out = nullptr;
    return XR_ERROR_FUNCTION_UNSUPPORTED;
  }
};
Fake *Fake::active = nullptr;
template <class F> void rejects(F call) {
  bool failed = false;
  try {
    call();
  } catch (const std::exception &) {
    failed = true;
  }
  require(failed, "Invalid input operation was accepted");
}
} // namespace
int main() {
  try {
    {
      Fake fake;
      ControllerActions actions(Fake::resolve, handle<XrInstance>(10));
      require(fake.suggestions.size() == 2, "Missing core controller profile");
      for (const auto &profile : fake.suggestions)
        for (const auto &binding : profile.second)
          require(binding.second.find("system/") == std::string::npos &&
                      (profile.first !=
                           "/interaction_profiles/oculus/touch_controller" ||
                       binding.second != "/user/hand/right/input/menu/click"),
                  "Reserved system control bound");
      const auto bound = [&](const char *profile, const char *action,
                             const char *path) {
        for (const auto &binding : fake.suggestions.at(profile))
          if (binding.first == action && binding.second == path)
            return true;
        return false;
      };
      const char *touch = "/interaction_profiles/oculus/touch_controller";
      const char *simple = "/interaction_profiles/khr/simple_controller";
      require(bound(touch, "aim", "/user/hand/left/input/aim/pose") &&
                  bound(touch, "grip", "/user/hand/left/input/grip/pose") &&
                  bound(touch, "aim", "/user/hand/right/input/aim/pose") &&
                  bound(touch, "grip", "/user/hand/right/input/grip/pose"),
              "Aim/grip profiles conflated");
      require(
          bound(simple, "select", "/user/hand/left/input/select/click") &&
              bound(simple, "select", "/user/hand/right/input/select/click"),
          "Simple controller cannot select");
      require(bound(touch, "primary", "/user/hand/left/input/x/click") &&
                  bound(touch, "primary", "/user/hand/right/input/a/click"),
              "Primary buttons bound incorrectly");
      rejects(
          [&] { actions.sample(handle<XrSpace>(500), 1'000'000'000, true); });
      actions.attach(handle<XrSession>(20));
      auto hands = actions.sample(handle<XrSpace>(500), 1'000'000'000, true);
      require(hands[0].aim.pose.position.x == 1 &&
                  hands[0].grip.pose.position.x == 2 &&
                  hands[1].aim.pose.position.x == 11 &&
                  hands[1].grip.pose.position.x == 12,
              "Runtime hand poses conflated");
      require(hands[0].aim.locationFlags == 15 &&
                  hands[0].grip.locationFlags == 3,
              "Actual pose flags changed");
      require(hands[0].stick.x == -.25f && hands[1].stick.x == .25f &&
                  hands[0].trigger == .75f && hands[1].trigger == .2f,
              "Raw analog input changed");
      require(hands[0].buttons ==
                      (ControllerActions::Primary | ControllerActions::Trigger |
                       ControllerActions::Grip) &&
                  hands[1].buttons == ControllerActions::Primary,
              "Wrong physical button bits");
      hands = actions.sample(handle<XrSpace>(500), 1'000'000'000, false);
      require(fake.syncs == 1 && hands[0].aim.locationFlags == 0 &&
                  hands[0].buttons == 0,
              "Unfocused controls retained");
      fake.syncResult = XR_SESSION_NOT_FOCUSED;
      hands = actions.sample(handle<XrSpace>(500), 1'000'000'000, true);
      require(hands[0].buttons == 0 && hands[0].stick.x == 0,
              "Focus race retained controls");
      fake.syncResult = XR_SUCCESS;
      fake.controls = false;
      hands = actions.sample(handle<XrSpace>(500), 1'000'000'000, true);
      require(hands[0].trigger == 0 && hands[0].squeeze == 0 &&
                  hands[0].buttons == 0,
              "Inactive actions retained stale values");
      fake.controls = true;
      fake.analog = false;
      hands = actions.sample(handle<XrSpace>(500), 1'000'000'000, true);
      require(hands[0].trigger == 1 && hands[0].squeeze == 0,
              "Simple-controller select fallback failed");
      fake.gripActive = false;
      hands = actions.sample(handle<XrSpace>(500), 1'000'000'000, true);
      require(hands[0].aim.locationFlags == 15 &&
                  hands[0].grip.locationFlags == 0,
              "Grip loss hid or borrowed aim");
      fake.gripActive = true;
      fake.badAim = true;
      hands = actions.sample(handle<XrSpace>(500), 1'000'000'000, true);
      require(hands[0].aim.locationFlags == 0 &&
                  hands[0].grip.locationFlags == 3,
              "Bad aim became tracked or invalidated grip");
      actions.detach();
      require(fake.destroyedSpaces == 4 && fake.spaces.empty(),
              "Session hand spaces not retired");
      actions.attach(handle<XrSession>(21));
      actions.close();
      require(fake.destroyedSpaces == 8 && fake.destroyedSets == 1,
              "Resume/close leaked controller handles");
    }
    {
      Fake fake;
      fake.failSuggestion = true;
      rejects([&] {
        ControllerActions actions(Fake::resolve, handle<XrInstance>(10));
      });
      require(fake.destroyedSets == 1,
              "Failed binding initialization leaked its set");
    }
    {
      Fake fake;
      ControllerActions actions(Fake::resolve, handle<XrInstance>(10));
      fake.failSpace = 3;
      rejects([&] { actions.attach(handle<XrSession>(20)); });
      require(fake.destroyedSpaces == 2 && fake.spaces.empty(),
              "Failed partial attachment leaked hand spaces");
    }
    std::cout << "Native controllers: standard profiles, independent "
                 "poses/flags, raw actions, focus/inactivity withdrawal, "
                 "simple selection and lifecycle passed\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
