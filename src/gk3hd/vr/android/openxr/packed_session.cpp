#include "packed_session.h"
#include <algorithm>
#include <atomic>
#include <climits>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace gk3hd::standalone::openxr {
namespace {
std::atomic<uint64_t> nextEpoch{1};
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
void require(bool value, const char *message) {
  if (!value)
    throw std::logic_error(message);
}
bool valid(const PackedSession::Sample &sample) {
  constexpr auto required =
      XR_VIEW_STATE_ORIENTATION_VALID_BIT | XR_VIEW_STATE_POSITION_VALID_BIT;
  if ((sample.flags & required) != required)
    return false;
  for (const auto &eye : sample.eyes) {
    const auto &p = eye.pose.position;
    const auto &q = eye.pose.orientation;
    const auto &f = eye.fov;
    const float norm = q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w;
    if (!std::isfinite(p.x) || !std::isfinite(p.y) || !std::isfinite(p.z) ||
        !std::isfinite(norm) || std::abs(norm - 1) > .001f ||
        !std::isfinite(f.angleLeft) || !std::isfinite(f.angleRight) ||
        !std::isfinite(f.angleUp) || !std::isfinite(f.angleDown) ||
        f.angleLeft >= f.angleRight || f.angleDown >= f.angleUp ||
        std::abs(f.angleLeft) >= 1.57079633f ||
        std::abs(f.angleRight) >= 1.57079633f ||
        std::abs(f.angleDown) >= 1.57079633f ||
        std::abs(f.angleUp) >= 1.57079633f)
      return false;
  }
  return true;
}
} // namespace
EyeExtent selectEyeExtent(const std::array<XrViewConfigurationView, 2> &views,
                          EyeExtent requested) {
  if (!requested.width && !requested.height) {
    for (const auto &view : views) {
      requested.width = std::max(requested.width, view.recommendedImageRectWidth);
      requested.height = std::max(requested.height, view.recommendedImageRectHeight);
    }
  }
  require(requested.width && requested.height, "Incomplete native eye dimensions");
  for (const auto &view : views)
    require(requested.width <= view.maxImageRectWidth &&
                requested.height <= view.maxImageRectHeight,
            "Native eye dimensions exceed runtime view bounds");
  return requested;
}

template <class T> void PackedSession::load(const char *name, T &target) {
  PFN_xrVoidFunction function = nullptr;
  check(resolve_(instance_, name, &function), name);
  require(function != nullptr, "Missing native OpenXR function");
  target = reinterpret_cast<T>(function);
}
void PackedSession::owner() const {
  require(std::this_thread::get_id() == owner_,
          "Native XR session requires its owning graphics thread");
}
PackedSession::PackedSession(PFN_xrGetInstanceProcAddr resolve,
                             XrInstance instance, XrSystemId system,
                             Graphics graphics, EyeExtent requested)
    : resolve_(resolve), instance_(instance), system_(system),
      graphics_(std::move(graphics)) {
  require(resolve_ && instance_ && system_ && graphics_.binding &&
              graphics_.format && graphics_.maxWidth && graphics_.maxHeight &&
              graphics_.flush && graphics_.finish,
          "Incomplete native XR graphics contract");
  epoch_ = nextEpoch.fetch_add(1);
#define LOAD(name, member) load(name, member)
  LOAD("xrGetSystemProperties", systemProperties_);
  LOAD("xrEnumerateViewConfigurationViews", configurations_);
  LOAD("xrCreateSession", createSession_);
  LOAD("xrDestroySession", destroySession_);
  LOAD("xrBeginSession", beginSession_);
  LOAD("xrEndSession", endSession_);
  LOAD("xrPollEvent", events_);
  LOAD("xrCreateReferenceSpace", createSpace_);
  LOAD("xrDestroySpace", destroySpace_);
  LOAD("xrEnumerateSwapchainFormats", formats_);
  LOAD("xrCreateSwapchain", createChain_);
  LOAD("xrDestroySwapchain", destroyChain_);
  LOAD("xrEnumerateSwapchainImages", enumerateImages_);
  LOAD("xrAcquireSwapchainImage", acquire_);
  LOAD("xrWaitSwapchainImage", waitImage_);
  LOAD("xrReleaseSwapchainImage", release_);
  LOAD("xrWaitFrame", waitFrame_);
  LOAD("xrBeginFrame", beginFrame_);
  LOAD("xrLocateViews", locate_);
  LOAD("xrEndFrame", endFrame_);
#undef LOAD
  try {
    auto props = typed<XrSystemProperties>(XR_TYPE_SYSTEM_PROPERTIES);
    check(systemProperties_(instance_, system_, &props),
          "Native system properties");
    std::array<XrViewConfigurationView, 2> views{};
    for (auto &view : views)
      view.type = XR_TYPE_VIEW_CONFIGURATION_VIEW;
    uint32_t count = 0;
    check(configurations_(instance_, system_,
                          XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO, 2, &count,
                          views.data()),
          "Native stereo configuration");
    require(count == 2, "Native presenter requires two actual stereo views");
    const auto extent = selectEyeExtent(views, requested);
    width_ = extent.width;
    height_ = extent.height;
    require(width_ <= INT32_MAX / 2 &&
                height_ <= INT32_MAX &&
                uint64_t(width_) * 2 <=
                    std::min(props.graphicsProperties.maxSwapchainImageWidth,
                             graphics_.maxWidth) &&
                height_ <=
                    std::min(props.graphicsProperties.maxSwapchainImageHeight,
                             graphics_.maxHeight),
            "Native packed stereo exceeds runtime/graphics bounds");
    auto create = typed<XrSessionCreateInfo>(XR_TYPE_SESSION_CREATE_INFO);
    create.next = graphics_.binding;
    create.systemId = system_;
    check(createSession_(instance_, &create, &session_),
          "Create native session");
    auto local =
        typed<XrReferenceSpaceCreateInfo>(XR_TYPE_REFERENCE_SPACE_CREATE_INFO);
    local.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_LOCAL;
    local.poseInReferenceSpace.orientation.w = 1;
    check(createSpace_(session_, &local, &space_), "Create native local space");
    count = 0;
    check(formats_(session_, 0, &count, nullptr), "Count native formats");
    require(count && count <= 256, "Native format count out of bounds");
    std::vector<int64_t> formats(count);
    check(formats_(session_, count, &count, formats.data()),
          "Read native formats");
    require(std::find(formats.begin(), formats.end(), graphics_.format) !=
                formats.end(),
            "Required native color format unavailable");
    auto chain = typed<XrSwapchainCreateInfo>(XR_TYPE_SWAPCHAIN_CREATE_INFO);
    chain.usageFlags = XR_SWAPCHAIN_USAGE_COLOR_ATTACHMENT_BIT;
    chain.format = graphics_.format;
    chain.sampleCount = 1;
    chain.width = width_ * 2;
    chain.height = height_;
    chain.faceCount = chain.arraySize = chain.mipCount = 1;
    check(createChain_(session_, &chain, &chain_),
          "Create native packed swapchain");
    check(enumerateImages_(chain_, 0, &images_, nullptr),
          "Count native images");
    require(images_ && images_ <= 16, "Native image count out of bounds");
  } catch (...) {
    try {
      closeImpl();
    } catch (...) {
    }
    throw;
  }
}
PackedSession::~PackedSession() {
  if (std::this_thread::get_id() == owner_)
    try {
      closeImpl();
    } catch (...) {
    }
}
void PackedSession::startIfReady() {
  if (session_ && state_ == XR_SESSION_STATE_READY && !running_ && resumed_ &&
      endReason_ == EndReason::None) {
    auto begin = typed<XrSessionBeginInfo>(XR_TYPE_SESSION_BEGIN_INFO);
    begin.primaryViewConfigurationType =
        XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
    check(beginSession_(session_, &begin), "Begin native session");
    running_ = true;
  }
}
void PackedSession::resumed(bool value) {
  owner();
  resumed_ = value;
  if (!value)
    invalidateHistory();
  startIfReady();
}
void PackedSession::invalidateHistory() {
  withdrawImages();
  epoch_ = nextEpoch.fetch_add(1);
}
void PackedSession::withdrawImages() {
  require(inputGeneration_ != std::numeric_limits<uint64_t>::max(),
          "Native input generation exhausted");
  ++inputGeneration_;
  history_.clear();
  presented_.reset();
  reusableContent_ = false;
}
const PackedSession::Sample *PackedSession::ownedSample(uint64_t serial) const {
  const auto found = std::find_if(history_.begin(), history_.end(),
                                [&](const Sample &value) { return value.serial == serial; });
  // Supplemental samples can be retained after a newer frame. Enforce expiry
  // by the sample's own target even when it is not at the front of the deque.
  if (found != history_.end() &&
      (current_.time < found->time || current_.time - found->time <= 250'000'000))
    return &*found;
  return presented_ && presented_->serial == serial ? &*presented_ : nullptr;
}
void PackedSession::poll() {
  owner();
  require(session_ != XR_NULL_HANDLE, "Closed native session");
  for (unsigned i = 0; i < 64; ++i) {
    auto event = typed<XrEventDataBuffer>(XR_TYPE_EVENT_DATA_BUFFER);
    const auto result = events_(instance_, &event);
    if (result == XR_EVENT_UNAVAILABLE)
      return;
    check(result, "Poll native events");
    if (event.type == XR_TYPE_EVENT_DATA_INSTANCE_LOSS_PENDING) {
      endReason_ = EndReason::InstanceLost;
      return;
    }
    if (event.type == XR_TYPE_EVENT_DATA_EVENTS_LOST) {
      // A lost event may have changed the coordinate basis. Keep known future
      // boundaries, but never assume existing images still describe this space.
      invalidateHistory();
      continue;
    }
    if (event.type == XR_TYPE_EVENT_DATA_REFERENCE_SPACE_CHANGE_PENDING) {
      const auto &changed =
          *reinterpret_cast<const XrEventDataReferenceSpaceChangePending *>(&event);
      if (changed.session == session_ &&
          changed.referenceSpaceType == XR_REFERENCE_SPACE_TYPE_LOCAL) {
        require(changed.changeTime > 0 && referenceChanges_.size() < 64,
                "Native reference-space change is invalid or unbounded");
        referenceChanges_.insert(
            std::upper_bound(referenceChanges_.begin(), referenceChanges_.end(), changed.changeTime),
            changed.changeTime);
      }
      continue;
    }
    if (event.type != XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED)
      continue;
    const auto &changed =
        *reinterpret_cast<const XrEventDataSessionStateChanged *>(&event);
    if (changed.session != session_)
      continue;
    if ((state_ == XR_SESSION_STATE_FOCUSED) != (changed.state == XR_SESSION_STATE_FOCUSED)) {
      withdrawImages();
    }
    state_ = changed.state;
    if (state_ == XR_SESSION_STATE_READY)
      startIfReady();
    else if (state_ == XR_SESSION_STATE_STOPPING && running_) {
      if (open_)
        end(nullptr);
      invalidateHistory();
      running_ = false;
      check(endSession_(session_), "End native session");
    } else if (state_ == XR_SESSION_STATE_EXITING) {
      endReason_ = EndReason::Exit;
      return;
    } else if (state_ == XR_SESSION_STATE_LOSS_PENDING) {
      endReason_ = EndReason::SessionLost;
      return;
    }
  }
  throw std::runtime_error("Native event stream exceeded its servicing bound");
}
bool PackedSession::frameSessionLost(XrResult result) {
  if (result == XR_SESSION_LOSS_PENDING || result == XR_ERROR_SESSION_LOST)
    endReason_ = EndReason::SessionLost;
  else if (result == XR_ERROR_INSTANCE_LOST)
    endReason_ = EndReason::InstanceLost;
  else
    return false;
  return true;
}

std::optional<PackedSession::Sample> PackedSession::begin() {
  owner();
  require(!open_, "Native frame already open");
  if (endReason_ != EndReason::None)
    return std::nullopt;
  poll();
  if (!running_ || !resumed_ || endReason_ != EndReason::None)
    return std::nullopt;
  auto wait = typed<XrFrameWaitInfo>(XR_TYPE_FRAME_WAIT_INFO);
  auto frame = typed<XrFrameState>(XR_TYPE_FRAME_STATE);
  const auto waited = waitFrame_(session_, &wait, &frame);
  if (frameSessionLost(waited))
    return std::nullopt;
  check(waited, "Wait native frame");
  auto begin = typed<XrFrameBeginInfo>(XR_TYPE_FRAME_BEGIN_INFO);
  const auto begun = beginFrame_(session_, &begin);
  const bool lostAtBegin = frameSessionLost(begun);
  if (lostAtBegin && XR_FAILED(begun))
    return std::nullopt;
  check(begun, "Begin native frame");
  open_ = true;
  released_ = false;
  current_ = {};
  current_.epoch = epoch_;
  current_.serial = nextSerial_++;
  current_.time = frame.predictedDisplayTime;
  current_.period = frame.predictedDisplayPeriod;
  current_.shouldRender = frame.shouldRender != 0;
  current_.focused = state_ == XR_SESSION_STATE_FOCUSED;
  try {
    require(current_.time > 0 && current_.period > 0,
            "Invalid native display timing");
    if (lostAtBegin) {
      end(nullptr);
      return std::nullopt;
    }
    while (!referenceChanges_.empty() && referenceChanges_.front() <= current_.time) {
      invalidateHistory();
      referenceChanges_.pop_front();
    }
    current_.epoch = epoch_;
    auto locate = typed<XrViewLocateInfo>(XR_TYPE_VIEW_LOCATE_INFO);
    locate.viewConfigurationType = XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
    locate.displayTime = current_.time;
    locate.space = space_;
    auto state = typed<XrViewState>(XR_TYPE_VIEW_STATE);
    uint32_t count = 0;
    for (auto &view : current_.eyes)
      view.type = XR_TYPE_VIEW;
    const auto located = locate_(session_, &locate, &state, 2, &count, current_.eyes.data());
    if (frameSessionLost(located)) {
      if (XR_SUCCEEDED(located))
        end(nullptr);
      else
        open_ = false;
      return std::nullopt;
    }
    check(located, "Locate native eyes");
    current_.flags = count == 2 ? state.viewStateFlags : 0;
    if (!valid(current_)) {
      current_.flags = 0;
      withdrawImages();
    }
    if (!current_.shouldRender) withdrawImages();
    if (current_.shouldRender && valid(current_))
      history_.push_back(current_);
    while (!history_.empty() &&
           (history_.size() > 256 ||
            current_.time - history_.front().time > 250'000'000))
      history_.pop_front();
    return current_;
  } catch (...) {
    try {
      end(nullptr);
    } catch (...) {
    }
    throw;
  }
}
std::optional<PackedSession::Sample> PackedSession::retainLocated(
    uint64_t anchorSerial, const Sample &located) {
  owner();
  require(open_, "Supplemental location requires an open native display frame");
  require(anchorSerial && anchorSerial < nextSerial_ && !located.serial,
          "Supplemental location confused native frame/query identities");
  const auto *anchor = ownedSample(anchorSerial);
  if (!anchor || !current_.focused || !current_.shouldRender || !valid(current_) ||
      !anchor->focused || !anchor->shouldRender || !valid(*anchor) ||
      !located.focused || !located.shouldRender || !valid(located) ||
      located.epoch != epoch_ || anchor->epoch != epoch_ ||
      located.period != anchor->period || located.period <= 0 ||
      located.period > 50'000'000 || located.time < anchor->time ||
      located.time - anchor->time > std::min<XrDuration>(2 * located.period, 50'000'000) ||
      located.time > current_.time || current_.time - located.time > 250'000'000)
    return std::nullopt;
  require(nextSerial_ != std::numeric_limits<uint64_t>::max(),
          "Native retained sample identity exhausted");
  Sample retained = located;
  retained.serial = nextSerial_++;
  history_.push_back(retained);
  while (history_.size() > 256)
    history_.pop_front();
  return retained;
}
std::optional<uint32_t> PackedSession::acquire(XrDuration timeout) {
  owner();
  require(open_ && current_.shouldRender && valid(current_) && !released_ &&
              timeout >= 0,
          "Native image acquisition unavailable");
  if (!acquired_) {
    auto acquire = typed<XrSwapchainImageAcquireInfo>(
        XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO);
    check(acquire_(chain_, &acquire, &index_), "Acquire native image");
    acquired_ = true;
    reusableContent_ = false;
    waited_ = false;
    require(index_ < images_, "Native image index out of bounds");
  }
  if (!waited_) {
    auto wait =
        typed<XrSwapchainImageWaitInfo>(XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO);
    wait.timeout = timeout;
    const auto result = waitImage_(chain_, &wait);
    if (result == XR_TIMEOUT_EXPIRED)
      return std::nullopt;
    check(result, "Wait native image");
    waited_ = true;
  }
  return index_;
}
void PackedSession::release() {
  owner();
  require(acquired_ && waited_, "Native image not writable/releasable");
  graphics_.flush();
  auto release =
      typed<XrSwapchainImageReleaseInfo>(XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO);
  check(release_(chain_, &release), "Release native image");
  acquired_ = waited_ = false;
  released_ = true;
}
uint64_t PackedSession::reusableSerial() const {
  owner();
  if (!open_ || !current_.focused || !reusableContent_ || !presented_ ||
      released_ || acquired_)
    return 0;
  return presented_->serial;
}
void PackedSession::end(const Sample *rendered, bool repeatReleased) {
  owner();
  require(open_, "No native frame to finish");
  if (repeatReleased)
    require(rendered && reusableSerial() == rendered->serial,
            "No unchanged released native image to repeat");
  if (rendered) {
    require((released_ || repeatReleased) && !acquired_ && current_.shouldRender &&
                valid(current_) && rendered->epoch == epoch_ &&
                valid(*rendered) && rendered->time > 0 &&
                rendered->time <= current_.time,
            "Unowned, invalid or mismatched native render sample");
    const auto *found = ownedSample(rendered->serial);
    require(found && found->time == rendered->time &&
                found->flags == rendered->flags,
            "Unknown/stale native render sample");
    for (unsigned i = 0; i < 2; ++i) {
      const auto &a = found->eyes[i];
      const auto &b = rendered->eyes[i];
      require(a.pose.position.x == b.pose.position.x &&
                  a.pose.position.y == b.pose.position.y &&
                  a.pose.position.z == b.pose.position.z &&
                  a.pose.orientation.x == b.pose.orientation.x &&
                  a.pose.orientation.y == b.pose.orientation.y &&
                  a.pose.orientation.z == b.pose.orientation.z &&
                  a.pose.orientation.w == b.pose.orientation.w &&
                  a.fov.angleLeft == b.fov.angleLeft &&
                  a.fov.angleRight == b.fov.angleRight &&
                  a.fov.angleUp == b.fov.angleUp &&
                  a.fov.angleDown == b.fov.angleDown,
              "Relabelled native render views");
    }
  }
  if (acquired_ && waited_)
    release();
  std::array<XrCompositionLayerProjectionView, 2> eyes{};
  auto projection =
      typed<XrCompositionLayerProjection>(XR_TYPE_COMPOSITION_LAYER_PROJECTION);
  projection.space = space_;
  if (rendered) {
    for (unsigned i = 0; i < 2; ++i) {
      eyes[i].type = XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW;
      eyes[i].pose = rendered->eyes[i].pose;
      eyes[i].fov = rendered->eyes[i].fov;
      eyes[i].subImage.swapchain = chain_;
      eyes[i].subImage.imageRect = {{int32_t(i * width_), 0},
                                    {int32_t(width_), int32_t(height_)}};
    }
    projection.viewCount = 2;
    projection.views = eyes.data();
  }
  const auto *layer =
      reinterpret_cast<const XrCompositionLayerBaseHeader *>(&projection);
  auto end = typed<XrFrameEndInfo>(XR_TYPE_FRAME_END_INFO);
  end.displayTime = current_.time;
  end.environmentBlendMode = XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
  end.layerCount = rendered ? 1 : 0;
  end.layers = rendered ? &layer : nullptr;
  open_ = false;
  reusableContent_ = false;
  const auto result = endFrame_(session_, &end);
  if (frameSessionLost(result))
    return;
  check(result, "End native frame");
  if (rendered) {
    presented_ = *rendered;
    reusableContent_ = true;
  }
}
bool PackedSession::endRendered(uint64_t serial, bool repeatReleased) {
  owner();
  if (!serial) {
    end(nullptr);
    return false;
  }
  const auto *found = ownedSample(serial);
  if (!found) {
    // Delayed pixels can outlive their retained pose after a tracking reset or
    // an age limit. Drop that layer; never relabel it with the current eyes or
    // terminate an otherwise live headset session. Future/unissued serials
    // still identify a caller error.
    require(serial < nextSerial_, "Unissued native rendered frame serial");
    end(nullptr);
    return false;
  }
  end(found, repeatReleased);
  return endReason_ == EndReason::None;
}
void PackedSession::closeImpl() {
  if (!session_)
    return;
  if (open_)
    end(nullptr);
  graphics_.finish();
  if (chain_) {
    check(destroyChain_(chain_), "Destroy native images");
    chain_ = XR_NULL_HANDLE;
  }
  acquired_ = waited_ = reusableContent_ = false;
  if (space_) {
    check(destroySpace_(space_), "Destroy native local space");
    space_ = XR_NULL_HANDLE;
  }
  check(destroySession_(session_), "Destroy native session");
  session_ = XR_NULL_HANDLE;
  running_ = false;
}
void PackedSession::close() {
  owner();
  closeImpl();
}
} // namespace gk3hd::standalone::openxr
