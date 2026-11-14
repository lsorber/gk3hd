#pragma once
#include <array>
#include <deque>
#include <functional>
#include <openxr/openxr.h>
#include <optional>
#include <thread>

namespace gk3hd::standalone::openxr {
struct EyeExtent {
  uint32_t width = 0, height = 0;
};
EyeExtent selectEyeExtent(const std::array<XrViewConfigurationView, 2> &,
                          EyeExtent requested);

// Native host session, separate from the guest application's OpenXR runtime.
// The platform adapter checks graphics requirements and provides the actual
// binding/format and graphics limits. It enumerates API-typed image objects.
class PackedSession {
public:
  struct Graphics {
    const void *binding = nullptr;
    int64_t format = 0;
    uint32_t maxWidth = 0, maxHeight = 0;
    std::function<void()> flush, finish;
  };
  struct Sample {
    uint64_t epoch = 0, serial = 0;
    XrTime time = 0;
    XrDuration period = 0;
    XrViewStateFlags flags = 0;
    bool shouldRender = false, focused = false;
    std::array<XrView, 2> eyes{};
  };
  PackedSession(PFN_xrGetInstanceProcAddr, XrInstance, XrSystemId, Graphics,
                EyeExtent requested = {});
  ~PackedSession();
  PackedSession(const PackedSession &) = delete;
  PackedSession &operator=(const PackedSession &) = delete;
  void poll();
  void resumed(bool);
  std::optional<Sample> begin();
  // Retain an independently located sample on the display owner. anchorSerial
  // is the original native frame used to predict it, not a guest/query ID.
  // Stale/withdrawn samples return null; no frame, graphics or location API runs.
  std::optional<Sample> retainLocated(uint64_t anchorSerial, const Sample &located);
  // A timeout retains the original acquired image for a later successful
  // wait. It does not grant permission to draw, release or acquire another.
  std::optional<uint32_t> acquire(XrDuration timeout = 5'000'000'000);
  void release();
  // rendered is the immutable sample that actually produced the pixels,
  // which may precede the current display frame. Null submits no layer.
  void end(const Sample *rendered, bool repeatReleased = false);
  // True only when xrEndFrame accepted a stereo layer, rather than retiring it.
  bool endRendered(uint64_t serial, bool repeatReleased = false);
  void close();
  uint32_t eyeWidth() const { return width_; }
  uint32_t eyeHeight() const { return height_; }
  uint32_t imageCount() const { return images_; }
  XrSwapchain swapchain() const { return chain_; }
  XrSpace space() const { return space_; }
  XrSession session() const { return session_; }
  enum class EndReason { None = 0, Exit = -1, SessionLost = -2, InstanceLost = -3 };
  EndReason endReason() const { return endReason_; }
  uint64_t reusableSerial() const;
  uint64_t inputGeneration() const { owner(); return inputGeneration_; }
  std::optional<XrTime> referenceDeadline() const {
    owner(); return referenceChanges_.empty() ? std::nullopt : std::optional{referenceChanges_.front()};
  }

private:
  template <class T> void load(const char *, T &);
  void owner() const;
  void startIfReady();
  bool frameSessionLost(XrResult);
  void invalidateHistory();
  void withdrawImages();
  const Sample *ownedSample(uint64_t serial) const;
  void closeImpl();
  PFN_xrGetInstanceProcAddr resolve_;
  XrInstance instance_;
  XrSystemId system_;
  Graphics graphics_;
  const std::thread::id owner_ = std::this_thread::get_id();
  uint64_t epoch_ = 0, nextSerial_ = 1, inputGeneration_ = 1;
  XrSession session_ = XR_NULL_HANDLE;
  XrSwapchain chain_ = XR_NULL_HANDLE;
  XrSpace space_ = XR_NULL_HANDLE;
  uint32_t width_ = 0, height_ = 0, images_ = 0, index_ = 0;
  bool running_ = false, resumed_ = true, open_ = false, acquired_ = false,
       waited_ = false, released_ = false;
  EndReason endReason_ = EndReason::None;
  bool reusableContent_ = false;
  XrSessionState state_ = XR_SESSION_STATE_UNKNOWN;
  Sample current_{};
  std::deque<Sample> history_;
  std::optional<Sample> presented_;
  std::deque<XrTime> referenceChanges_;
  PFN_xrGetSystemProperties systemProperties_ = nullptr;
  PFN_xrEnumerateViewConfigurationViews configurations_ = nullptr;
  PFN_xrCreateSession createSession_ = nullptr;
  PFN_xrDestroySession destroySession_ = nullptr;
  PFN_xrBeginSession beginSession_ = nullptr;
  PFN_xrEndSession endSession_ = nullptr;
  PFN_xrPollEvent events_ = nullptr;
  PFN_xrCreateReferenceSpace createSpace_ = nullptr;
  PFN_xrDestroySpace destroySpace_ = nullptr;
  PFN_xrEnumerateSwapchainFormats formats_ = nullptr;
  PFN_xrCreateSwapchain createChain_ = nullptr;
  PFN_xrDestroySwapchain destroyChain_ = nullptr;
  PFN_xrEnumerateSwapchainImages enumerateImages_ = nullptr;
  PFN_xrAcquireSwapchainImage acquire_ = nullptr;
  PFN_xrWaitSwapchainImage waitImage_ = nullptr;
  PFN_xrReleaseSwapchainImage release_ = nullptr;
  PFN_xrWaitFrame waitFrame_ = nullptr;
  PFN_xrBeginFrame beginFrame_ = nullptr;
  PFN_xrLocateViews locate_ = nullptr;
  PFN_xrEndFrame endFrame_ = nullptr;
};
} // namespace gk3hd::standalone::openxr
