#pragma once
#include <array>
#include <openxr/openxr.h>

namespace gk3hd::standalone::openxr {
// Physical input only. Game actions/edges/locomotion remain in the shared game
// input layer, so the host does not interpret the same controls a second time.
class ControllerActions {
public:
  enum Button : uint32_t {
    Primary = 1,
    Secondary = 2,
    Menu = 4,
    Stick = 8,
    Trigger = 16,
    Grip = 32
  };
  struct Hand {
    XrSpaceLocation aim{}, grip{};
    XrVector2f stick{};
    float trigger = 0, squeeze = 0;
    uint32_t buttons = 0;
  };
  ControllerActions(PFN_xrGetInstanceProcAddr, XrInstance);
  ~ControllerActions();
  ControllerActions(const ControllerActions &) = delete;
  ControllerActions &operator=(const ControllerActions &) = delete;
  void attach(XrSession);
  void detach();
  std::array<Hand, 2> sample(XrSpace, XrTime, bool focused);
  void close();

private:
  template <class T> void load(const char *, T &);
  XrPath path(const char *);
  XrAction action(const char *, const char *, XrActionType);
  void bindings();
  XrSpaceLocation locate(XrAction, XrSpace, XrPath, XrSpace, XrTime);
  bool button(XrAction, XrPath);
  float scalar(XrAction, XrPath, bool &active);
  PFN_xrGetInstanceProcAddr resolve_;
  XrInstance instance_;
  XrActionSet set_ = XR_NULL_HANDLE;
  XrSession session_ = XR_NULL_HANDLE;
  std::array<XrPath, 2> hands_{};
  std::array<std::array<XrSpace, 2>, 2> spaces_{};
  XrAction aim_ = XR_NULL_HANDLE, grip_ = XR_NULL_HANDLE,
           stick_ = XR_NULL_HANDLE, trigger_ = XR_NULL_HANDLE,
           squeeze_ = XR_NULL_HANDLE, select_ = XR_NULL_HANDLE;
  std::array<XrAction, 4> buttons_{};
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
  PFN_xrGetActionStateFloat float_ = nullptr;
  PFN_xrGetActionStateVector2f vector_ = nullptr;
  PFN_xrGetActionStatePose pose_ = nullptr;
  PFN_xrLocateSpace locate_ = nullptr;
};
} // namespace gk3hd::standalone::openxr
