#pragma once
#include "packed_session.h"
#include "relative_views.h"
#include <cmath>
#include <cstring>
#include <deque>
#include <stdexcept>
#include <string>
#include <vector>

// Controlled dispatch only. No loader, hardware tracking or real XR runtime.
namespace gk3hd::standalone::openxr::testing {
inline void require(bool value, const char *text) {
  if (!value)
    throw std::runtime_error(text);
}
template <class T> T handle(uintptr_t value) { return (T)value; }
struct Fake {
  inline static Fake *active=nullptr;
  std::deque<XrSessionState> events;
  std::deque<XrEventDataReferenceSpaceChangePending> referenceEvents;
  unsigned creates = 0, begins = 0, ends = 0, acquires = 0, waits = 0,
           releases = 0, frames = 0, flushes = 0, finishes = 0, destroys = 0,
           layers = 0;
  bool timeout = false, render = true, loss = false, eventsLost = false;
  bool failEnd = false;
  XrViewStateFlags flags = 15;
  XrResult waitFrameResult = XR_SUCCESS, beginFrameResult = XR_SUCCESS,
           locateResult = XR_SUCCESS, endResult = XR_SUCCESS;
  XrTime time = 1'000'000'000, lastDisplay = 0;
  XrDuration lastImageTimeout = -1;
  float renderedX = 0;
  std::array<XrView, 2> projected{};
  uint32_t limit = 4096;
  uint32_t graphicsLimit = 4096;
  EyeExtent expectedExtent{120, 120};
  std::vector<int> retirement;
  XrBaseInStructure binding{XR_TYPE_GRAPHICS_BINDING_OPENGL_ES_ANDROID_KHR,
                            nullptr};
  Fake() { active = this; }
  PackedSession::Graphics graphics() {
    return {&binding,
            0x8c43,
            graphicsLimit,
            graphicsLimit,
            [this] { ++flushes; },
            [this] {
              ++finishes;
              retirement.push_back(1);
            }};
  }
  PackedSession make(EyeExtent requested = {}) {
    return PackedSession(resolve, handle<XrInstance>(1), 1, graphics(), requested);
  }
  static XrResult XRAPI_CALL system(XrInstance, XrSystemId,
                                    XrSystemProperties *p) {
    p->graphicsProperties.maxSwapchainImageWidth = active->limit;
    p->graphicsProperties.maxSwapchainImageHeight = 4096;
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL config(XrInstance, XrSystemId,
                                    XrViewConfigurationType, uint32_t cap,
                                    uint32_t *count,
                                    XrViewConfigurationView *views) {
    *count = 2;
    require(cap == 2, "Configuration capacity changed");
    views[0].recommendedImageRectWidth = 100;
    views[0].recommendedImageRectHeight = 120;
    views[1].recommendedImageRectWidth = 120;
    views[1].recommendedImageRectHeight = 110;
    views[0].maxImageRectWidth = 3200;
    views[0].maxImageRectHeight = 3600;
    views[1].maxImageRectWidth = 3600;
    views[1].maxImageRectHeight = 3500;
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL create(XrInstance, const XrSessionCreateInfo *q,
                                    XrSession *out) {
    require(q->next == &active->binding, "Graphics binding was not retained");
    ++active->creates;
    *out = handle<XrSession>(2);
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL destroy(XrSession) {
    ++active->destroys;
    active->retirement.push_back(4);
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL beginSession(XrSession,
                                          const XrSessionBeginInfo *) {
    ++active->begins;
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL endSession(XrSession) {
    ++active->ends;
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL event(XrInstance, XrEventDataBuffer *out) {
    if (active->eventsLost) {
      active->eventsLost = false;
      XrEventDataEventsLost lost{};
      lost.type = XR_TYPE_EVENT_DATA_EVENTS_LOST;lost.lostEventCount = 1;
      std::memcpy(out, &lost, sizeof(lost));return XR_SUCCESS;
    }
    if (!active->referenceEvents.empty()) {
      const auto changed = active->referenceEvents.front();
      active->referenceEvents.pop_front();
      std::memcpy(out, &changed, sizeof(changed));return XR_SUCCESS;
    }
    if (active->loss) {
      active->loss = false;
      out->type = XR_TYPE_EVENT_DATA_INSTANCE_LOSS_PENDING;
      return XR_SUCCESS;
    }
    if (active->events.empty())
      return XR_EVENT_UNAVAILABLE;
    XrEventDataSessionStateChanged state{};
    state.type = XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED;
    state.session = handle<XrSession>(2);
    state.state = active->events.front();
    active->events.pop_front();
    std::memcpy(out, &state, sizeof(state));
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL createSpace(XrSession,
                                         const XrReferenceSpaceCreateInfo *q,
                                         XrSpace *out) {
    require(q->referenceSpaceType == XR_REFERENCE_SPACE_TYPE_LOCAL &&
                q->poseInReferenceSpace.orientation.w == 1,
            "Reference origin changed");
    *out = handle<XrSpace>(3);
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL destroySpace(XrSpace) {
    active->retirement.push_back(3);
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL formats(XrSession, uint32_t cap, uint32_t *count,
                                     int64_t *out) {
    *count = 2;
    if (cap) {
      out[0] = 0x8058;
      out[1] = 0x8c43;
    }
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL createChain(XrSession,
                                         const XrSwapchainCreateInfo *q,
                                         XrSwapchain *out) {
    require(q->width == active->expectedExtent.width * 2 &&
                q->height == active->expectedExtent.height && q->arraySize == 1 &&
                q->sampleCount == 1 && q->format == 0x8c43,
            "Packed native extent/format changed");
    *out = handle<XrSwapchain>(4);
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL destroyChain(XrSwapchain) {
    require(active->finishes > 0, "GPU images destroyed before completion");
    active->retirement.push_back(2);
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL images(XrSwapchain, uint32_t, uint32_t *count,
                                    XrSwapchainImageBaseHeader *) {
    *count = 3;
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL acquire(XrSwapchain,
                                     const XrSwapchainImageAcquireInfo *,
                                     uint32_t *index) {
    ++active->acquires;
    *index = 1;
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL waitImage(XrSwapchain,
                                       const XrSwapchainImageWaitInfo *info) {
    active->lastImageTimeout = info->timeout;
    ++active->waits;
    return active->timeout ? XR_TIMEOUT_EXPIRED : XR_SUCCESS;
  }
  static XrResult XRAPI_CALL release(XrSwapchain,
                                     const XrSwapchainImageReleaseInfo *) {
    require(active->flushes == active->releases + 1,
            "Release did not submit graphics work exactly once");
    ++active->releases;
    return XR_SUCCESS;
  }
  static XrResult XRAPI_CALL waitFrame(XrSession, const XrFrameWaitInfo *,
                                       XrFrameState *out) {
    active->time += 11'111'111;
    out->predictedDisplayTime = active->time;
    out->predictedDisplayPeriod = 11'111'111;
    out->shouldRender = active->render ? XR_TRUE : XR_FALSE;
    return active->waitFrameResult;
  }
  static XrResult XRAPI_CALL beginFrame(XrSession, const XrFrameBeginInfo *) {
    return active->beginFrameResult;
  }
  static XrResult XRAPI_CALL locate(XrSession, const XrViewLocateInfo *q,
                                    XrViewState *state, uint32_t,
                                    uint32_t *count, XrView *eyes) {
    require(q->space == handle<XrSpace>(3) && q->displayTime == active->time,
            "Eye sampling did not use the predicted native frame");
    *count = 2;
    state->viewStateFlags = active->flags;
    for (unsigned i = 0; i < 2; ++i) {
      eyes[i].pose.orientation.w = 1;
      eyes[i].pose.position = {float(active->time - 1'000'000'000) / 1e9f +
                                   float(i) * .064f,
                               1.7f, 0};
      eyes[i].fov = {-.8f, .7f, .9f, -.6f};
    }
    return active->locateResult;
  }
  static XrResult XRAPI_CALL endFrame(XrSession, const XrFrameEndInfo *info) {
    ++active->frames;
    if (active->failEnd) return XR_ERROR_RUNTIME_FAILURE;
    active->layers = info->layerCount;
    active->lastDisplay = info->displayTime;
    if (info->layerCount) {
      require(info->layerCount == 1, "Unexpected native layers");
      const auto &projection =
          *reinterpret_cast<const XrCompositionLayerProjection *>(
              info->layers[0]);
      require(projection.space == handle<XrSpace>(3) &&
                  projection.viewCount == 2,
              "Projection space/eye count changed");
      active->renderedX = projection.views[0].pose.position.x;
      for (unsigned i = 0; i < 2; ++i) {
        active->projected[i].pose=projection.views[i].pose;
        active->projected[i].fov=projection.views[i].fov;
        const auto &image = projection.views[i].subImage;
        require(image.swapchain == handle<XrSwapchain>(4) &&
                    image.imageRect.offset.x == int(i * active->expectedExtent.width) &&
                    image.imageRect.extent.width == int(active->expectedExtent.width) &&
                    image.imageRect.extent.height == int(active->expectedExtent.height) &&
                    image.imageArrayIndex == 0,
                "Eye rectangle escaped owned packed image");
      }
    }
    return active->endResult;
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
    BIND("xrGetSystemProperties", system);
    BIND("xrEnumerateViewConfigurationViews", config);
    BIND("xrCreateSession", create);
    BIND("xrDestroySession", destroy);
    BIND("xrBeginSession", beginSession);
    BIND("xrEndSession", endSession);
    BIND("xrPollEvent", event);
    BIND("xrCreateReferenceSpace", createSpace);
    BIND("xrDestroySpace", destroySpace);
    BIND("xrEnumerateSwapchainFormats", formats);
    BIND("xrCreateSwapchain", createChain);
    BIND("xrDestroySwapchain", destroyChain);
    BIND("xrEnumerateSwapchainImages", images);
    BIND("xrAcquireSwapchainImage", acquire);
    BIND("xrWaitSwapchainImage", waitImage);
    BIND("xrReleaseSwapchainImage", release);
    BIND("xrWaitFrame", waitFrame);
    BIND("xrBeginFrame", beginFrame);
    BIND("xrLocateViews", locate);
    BIND("xrEndFrame", endFrame);
#undef BIND
    *out = nullptr;
    return XR_ERROR_FUNCTION_UNSUPPORTED;
  }
};
template <class F> void rejects(F call) {
  bool rejected = false;
  try {
    {
      const float half = std::sqrt(.5f);
      XrPosef head{{0, half, 0, half}, {1, 2, 3}};
      XrPosef eye{{0, std::sin(3.14159265f / 4 + .05f), 0,
                   std::cos(3.14159265f / 4 + .05f)},
                  {1.004f, 2.002f, 3.032f}};
      const auto relative = gk3hd::standalone::openxr::relativeView(head, eye);
      require(std::abs(relative.position.x + .032f) < 1e-6f &&
                  std::abs(relative.position.y - .002f) < 1e-6f &&
                  std::abs(relative.position.z - .004f) < 1e-6f &&
                  std::abs(relative.orientation.y - std::sin(.05f)) < 1e-6f &&
                  std::abs(relative.orientation.w - std::cos(.05f)) < 1e-6f,
              "Independent head-to-eye transform changed");
      XrSpaceLocation location{};
      location.pose = head;
      require(!gk3hd::standalone::openxr::locatedPose(location),
              "Unavailable head promoted");
      location.locationFlags = 3;
      require(gk3hd::standalone::openxr::locatedPose(location),
              "Actual head validity lost");
      location.pose.orientation.w = 0;
      require(!gk3hd::standalone::openxr::locatedPose(location),
              "Invalid native head quaternion accepted");
    }
    call();
  } catch (const std::logic_error &) {
    rejected = true;
  }
  require(rejected, "Invalid ownership/state was accepted");
}
inline void ready(Fake &fake) {
  fake.events = {XR_SESSION_STATE_READY, XR_SESSION_STATE_FOCUSED};
}
inline void recenter(Fake &fake, XrTime when, XrReferenceSpaceType type = XR_REFERENCE_SPACE_TYPE_LOCAL,
              XrSession session = handle<XrSession>(2)) {
  XrEventDataReferenceSpaceChangePending changed{};
  changed.type = XR_TYPE_EVENT_DATA_REFERENCE_SPACE_CHANGE_PENDING;
  changed.session = session;changed.referenceSpaceType = type;changed.changeTime = when;
  // The runtime may not know the old/new transform. We never invent one or
  // relabel old pixels; a fresh native sample recovers submission instead.
  changed.poseValid = XR_FALSE;
  fake.referenceEvents.push_back(changed);
}
} // namespace gk3hd::standalone::openxr::testing
