#pragma once

// Test-only action runtime. Never staged into the renderer or shipped as a
// player runtime. Independent state lets tests drive focus, tracking and input.
#include <openxr/openxr.h>
#include <array>
#include <cstring>
#include <map>
#include <string>
#include <type_traits>
#include <vector>

namespace gk3hd::vr::testinput {
template<typename T> T handle(uintptr_t value) {
  if constexpr (std::is_pointer_v<T>) return reinterpret_cast<T>(value);
  else return static_cast<T>(value);
}
struct Action {
  XrActionSet set;
  XrActionType type;
  std::string name;
  std::array<XrPath, 2> hands;
};
struct Space { XrSession session; unsigned hand; };
struct Hand {
  bool active = false, valid = true;
  uint32_t buttons = 0;
  uint32_t activeButtons = 31;
  XrVector2f stick{};
  XrPosef pose{{0, 0, 0, 1}, {0, 1, -1}};
};
struct Binding { std::string profile, path, action; XrActionType type; };
struct Model {
  uintptr_t next = 0x10000;
  std::map<std::string, XrPath> paths;
  std::map<XrActionSet, bool> sets;
  std::map<XrAction, Action> actions;
  std::map<XrSpace, Space> spaces;
  std::map<XrSession, XrActionSet> sessions;
  std::vector<Binding> bindings;
  std::array<Hand, 2> hands{};
  XrResult syncResult = XR_SUCCESS;
  std::string fail, unsupportedProfile;
  unsigned spaceCalls = 0, failSpaceAt = 0, syncs = 0;
  XrTime locatedTime = 0;
  template<typename T> T allocate() { return handle<T>(next++); }
  std::string path(XrPath value) const {
    for (const auto& pair : paths) if (pair.second == value) return pair.first;
    return {};
  }
  bool fails(const char* operation) const { return fail == operation; }
};
inline Model model;

inline XrResult XRAPI_CALL stringToPath(XrInstance, const char* text, XrPath* output) {
  if (!text || *text != '/') return XR_ERROR_PATH_FORMAT_INVALID;
  auto& path = model.paths[text];
  if (!path) path = static_cast<XrPath>(model.next++);
  *output = path; return XR_SUCCESS;
}
inline XrResult XRAPI_CALL createSet(XrInstance, const XrActionSetCreateInfo*, XrActionSet* output) {
  if (model.fails("createSet")) return XR_ERROR_RUNTIME_FAILURE;
  *output = model.allocate<XrActionSet>(); model.sets[*output] = false;
  return XR_SUCCESS;
}
inline XrResult XRAPI_CALL destroySet(XrActionSet value) {
  if (!model.sets.erase(value)) return XR_ERROR_HANDLE_INVALID;
  for (auto it = model.actions.begin(); it != model.actions.end();)
    if (it->second.set == value) it = model.actions.erase(it); else ++it;
  return XR_SUCCESS;
}
inline XrResult XRAPI_CALL createAction(XrActionSet set, const XrActionCreateInfo* info, XrAction* output) {
  if (!model.sets.count(set)) return XR_ERROR_HANDLE_INVALID;
  if (model.sets.at(set)) return XR_ERROR_ACTIONSETS_ALREADY_ATTACHED;
  if (model.fails("createAction")) return XR_ERROR_RUNTIME_FAILURE;
  if (info->countSubactionPaths != 2 ||
      model.path(info->subactionPaths[0]) != "/user/hand/left" ||
      model.path(info->subactionPaths[1]) != "/user/hand/right") return XR_ERROR_PATH_UNSUPPORTED;
  *output = model.allocate<XrAction>();
  model.actions.emplace(*output, Action{set, info->actionType, info->actionName,
    {info->subactionPaths[0], info->subactionPaths[1]}});
  return XR_SUCCESS;
}
inline XrResult XRAPI_CALL suggest(XrInstance, const XrInteractionProfileSuggestedBinding* info) {
  if (model.fails("suggest")) return XR_ERROR_RUNTIME_FAILURE;
  const auto profile = model.path(info->interactionProfile);
  if (profile == model.unsupportedProfile) return XR_ERROR_PATH_UNSUPPORTED;
  for (uint32_t i = 0; i < info->countSuggestedBindings; ++i) {
    const auto& binding = info->suggestedBindings[i];
    if (!model.actions.count(binding.action)) return XR_ERROR_HANDLE_INVALID;
    const auto& action = model.actions.at(binding.action);
    if (model.sets.at(action.set)) return XR_ERROR_ACTIONSETS_ALREADY_ATTACHED;
    const auto path = model.path(binding.binding);
    if (path.empty() || path.find("/input/system/") != std::string::npos) return XR_ERROR_PATH_UNSUPPORTED;
    model.bindings.push_back({profile, path, action.name, action.type});
  }
  return XR_SUCCESS;
}
inline XrResult XRAPI_CALL attach(XrSession session, const XrSessionActionSetsAttachInfo* info) {
  if (model.fails("attach")) return XR_ERROR_RUNTIME_FAILURE;
  if (model.sessions.count(session)) return XR_ERROR_ACTIONSETS_ALREADY_ATTACHED;
  if (info->countActionSets != 1 || !model.sets.count(info->actionSets[0])) return XR_ERROR_HANDLE_INVALID;
  model.sessions[session] = info->actionSets[0]; model.sets.at(info->actionSets[0]) = true;
  return XR_SUCCESS;
}
inline void detachSession(XrSession value) { model.sessions.erase(value); }
inline XrResult XRAPI_CALL createSpace(XrSession session, const XrActionSpaceCreateInfo* info, XrSpace* output) {
  ++model.spaceCalls;
  if (model.failSpaceAt == model.spaceCalls) return XR_ERROR_RUNTIME_FAILURE;
  if (!model.sessions.count(session) || !model.actions.count(info->action)) return XR_ERROR_HANDLE_INVALID;
  const auto& action = model.actions.at(info->action);
  if (action.type != XR_ACTION_TYPE_POSE_INPUT) return XR_ERROR_ACTION_TYPE_MISMATCH;
  if (model.sessions.at(session) != action.set) return XR_ERROR_ACTIONSET_NOT_ATTACHED;
  unsigned hand = info->subactionPath == action.hands[0] ? 0 : 1;
  if (info->subactionPath != action.hands[hand]) return XR_ERROR_PATH_UNSUPPORTED;
  if (info->poseInActionSpace.orientation.w != 1.f) return XR_ERROR_POSE_INVALID;
  *output = model.allocate<XrSpace>(); model.spaces.emplace(*output, Space{session, hand});
  return XR_SUCCESS;
}
inline bool ownsSpace(XrSpace value) { return model.spaces.count(value) != 0; }
inline XrResult XRAPI_CALL destroySpace(XrSpace value) {
  return model.spaces.erase(value) ? XR_SUCCESS : XR_ERROR_HANDLE_INVALID;
}
inline XrResult XRAPI_CALL sync(XrSession session, const XrActionsSyncInfo* info) {
  ++model.syncs;
  if (model.fails("sync")) return XR_ERROR_RUNTIME_FAILURE;
  if (!model.sessions.count(session) || info->countActiveActionSets != 1 ||
      info->activeActionSets[0].actionSet != model.sessions.at(session)) return XR_ERROR_ACTIONSET_NOT_ATTACHED;
  return model.syncResult;
}
inline XrResult query(XrSession session, const XrActionStateGetInfo* get, XrActionType type, unsigned& hand) {
  if (!model.sessions.count(session) || !model.actions.count(get->action)) return XR_ERROR_HANDLE_INVALID;
  const auto& action = model.actions.at(get->action);
  if (action.type != type) return XR_ERROR_ACTION_TYPE_MISMATCH;
  if (action.set != model.sessions.at(session)) return XR_ERROR_ACTIONSET_NOT_ATTACHED;
  hand = get->subactionPath == action.hands[0] ? 0 : 1;
  if (get->subactionPath != action.hands[hand]) return XR_ERROR_PATH_UNSUPPORTED;
  return XR_SUCCESS;
}
inline XrResult XRAPI_CALL boolean(XrSession session, const XrActionStateGetInfo* get, XrActionStateBoolean* output) {
  if (model.fails("boolean")) return XR_ERROR_RUNTIME_FAILURE;
  unsigned hand = 0;
  const auto result = query(session, get, XR_ACTION_TYPE_BOOLEAN_INPUT, hand);
  if (result != XR_SUCCESS) return result;
  const char* names[]{"select", "cancel", "menu", "inventory", "recenter"};
  for (unsigned i = 0; i < 5; ++i) if (model.actions.at(get->action).name == names[i]) {
    output->isActive = model.hands[hand].active && (model.hands[hand].activeButtons & (1u << i));
    output->currentState = (model.hands[hand].buttons & (1u << i)) != 0;
    // Deliberately false: the app must not rely on this after a focus change.
    output->changedSinceLastSync = XR_FALSE;
    return XR_SUCCESS;
  }
  return XR_ERROR_HANDLE_INVALID;
}
inline XrResult XRAPI_CALL pose(XrSession session, const XrActionStateGetInfo* get, XrActionStatePose* output) {
  unsigned hand = 0;
  const auto result = query(session, get, XR_ACTION_TYPE_POSE_INPUT, hand);
  if (result == XR_SUCCESS) output->isActive = model.hands[hand].active;
  return result;
}
inline XrResult XRAPI_CALL vector(XrSession session, const XrActionStateGetInfo* get, XrActionStateVector2f* output) {
  unsigned hand = 0;
  const auto result = query(session, get, XR_ACTION_TYPE_VECTOR2F_INPUT, hand);
  if (result == XR_SUCCESS) {
    output->isActive = model.hands[hand].active; output->currentState = model.hands[hand].stick;
  }
  return result;
}
inline XrResult XRAPI_CALL locate(XrSpace space, XrSpace base, XrTime time, XrSpaceLocation* output) {
  if (model.fails("locate")) return XR_ERROR_RUNTIME_FAILURE;
  if (!model.spaces.count(space) || !base) return XR_ERROR_HANDLE_INVALID;
  model.locatedTime = time;
  const auto& hand = model.hands[model.spaces.at(space).hand];
  output->locationFlags = hand.valid ? XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_VALID_BIT : 0;
  output->pose = hand.pose;
  return XR_SUCCESS;
}
inline XrResult XRAPI_CALL resolve(XrInstance, const char* name, PFN_xrVoidFunction* output) {
  *output = nullptr;
#define BIND(api, implementation) if (!std::strcmp(name, #api)) { \
  *output = reinterpret_cast<PFN_xrVoidFunction>(static_cast<PFN_##api>(implementation)); return XR_SUCCESS; }
  BIND(xrStringToPath, stringToPath)
  BIND(xrCreateActionSet, createSet)
  BIND(xrDestroyActionSet, destroySet)
  BIND(xrCreateAction, createAction)
  BIND(xrSuggestInteractionProfileBindings, suggest)
  BIND(xrAttachSessionActionSets, attach)
  BIND(xrCreateActionSpace, createSpace)
  BIND(xrDestroySpace, destroySpace)
  BIND(xrSyncActions, sync)
  BIND(xrGetActionStateBoolean, boolean)
  BIND(xrGetActionStatePose, pose)
  BIND(xrGetActionStateVector2f, vector)
  BIND(xrLocateSpace, locate)
#undef BIND
  return XR_ERROR_FUNCTION_UNSUPPORTED;
}
} // namespace gk3hd::vr::testinput
