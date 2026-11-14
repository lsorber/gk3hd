#pragma once

#include "input_bridge.h"
#include <openxr/openxr.h>
#include <array>

namespace gk3hd::vr {

// Called only on the render thread. The action set outlives device/session
// recreation; aim spaces are session children and must close before a session.
class Actions {
public:
  explicit Actions(PFN_xrGetInstanceProcAddr resolve);
  ~Actions();
  Actions(const Actions&) = delete;
  Actions& operator=(const Actions&) = delete;
  void initialize(XrInstance instance);
  void attach(XrSession session);
  InputSnapshot sample(XrSpace base, XrTime displayTime, bool focused);
  void reset() noexcept;
  void closeSession() noexcept;
  void shutdown() noexcept;

private:
  template<typename T> void load(const char* name, T& target);
  XrPath path(const char* value);
  XrAction action(const char* name, const char* title, XrActionType type);
  void bindings();
  struct Latch {
    uint32_t previous = 0, blocked = 0, active = 0;
    bool valid = false, stickArmed = false;
  };
  PFN_xrGetInstanceProcAddr resolve_;
  PFN_xrStringToPath stringToPath_ = nullptr;
  PFN_xrCreateActionSet createSet_ = nullptr;
  PFN_xrDestroyActionSet destroySet_ = nullptr;
  PFN_xrCreateAction createAction_ = nullptr;
  PFN_xrSuggestInteractionProfileBindings suggest_ = nullptr;
  PFN_xrAttachSessionActionSets attach_ = nullptr;
  PFN_xrCreateActionSpace createSpace_ = nullptr;
  PFN_xrDestroySpace destroySpace_ = nullptr;
  PFN_xrSyncActions sync_ = nullptr;
  PFN_xrGetActionStateBoolean boolean_ = nullptr;
  PFN_xrGetActionStatePose pose_ = nullptr;
  PFN_xrGetActionStateVector2f vector_ = nullptr;
  PFN_xrLocateSpace locate_ = nullptr;
  XrInstance instance_ = XR_NULL_HANDLE;
  XrSession session_ = XR_NULL_HANDLE;
  XrActionSet set_ = XR_NULL_HANDLE;
  XrAction aim_ = XR_NULL_HANDLE, stick_ = XR_NULL_HANDLE;
  std::array<XrAction, 5> buttons_{};
  std::array<XrPath, 2> hands_{};
  std::array<XrSpace, 2> spaces_{};
  std::array<Latch, 2> latches_{};
};

} // namespace gk3hd::vr
