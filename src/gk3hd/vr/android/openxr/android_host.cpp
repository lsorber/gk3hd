#include <jni.h>
#define XR_USE_PLATFORM_ANDROID
#define XR_USE_GRAPHICS_API_OPENGL_ES
#include "controller_actions.h"
#include "display_rates.h"
#include "performance.h"
#include "packed_session.h"
#include "relative_views.h"
#include "runtime_discovery.h"
#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <algorithm>
#include <android/log.h>
#include <cmath>
#include <cstring>
#include <memory>
#include <mutex>
#include <openxr/openxr_platform.h>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

namespace {
using gk3hd::standalone::openxr::EyeExtent;
using gk3hd::standalone::openxr::PackedSession;
using gk3hd::standalone::openxr::selectEyeExtent;
template <class T> T typed(XrStructureType type) {
  T value{};
  value.type = type;
  return value;
}
void require(bool value, const char *text) {
  if (!value)
    throw std::runtime_error(text);
}
void checked(XrResult result, const char *text) {
  if (XR_FAILED(result))
    throw std::runtime_error(std::string(text) + " (OpenXR " +
                             std::to_string(result) + ")");
}
template <class T> T function(XrInstance instance, const char *name) {
  PFN_xrVoidFunction out = nullptr;
  checked(xrGetInstanceProcAddr(instance, name, &out), name);
  require(out != nullptr, "Missing OpenXR function");
  return reinterpret_cast<T>(out);
}
void putPose(float *out, const XrPosef &pose) {
  out[0] = pose.position.x;
  out[1] = pose.position.y;
  out[2] = pose.position.z;
  out[3] = pose.orientation.x;
  out[4] = pose.orientation.y;
  out[5] = pose.orientation.z;
  out[6] = pose.orientation.w;
}
void initializeLoader(JNIEnv *env, jobject context) {
  // The loader is process-wide. Retain the Application, never a retired launch
  // Activity, across discovery and subsequent native presenter creation.
  static std::once_flag initialized;
  static jobject application = nullptr;
  std::call_once(initialized, [&] {
    const jclass type = env->GetObjectClass(context);
    require(type != nullptr, "Missing Android Context class");
    const auto method = env->GetMethodID(type, "getApplicationContext", "()Landroid/content/Context;");
    env->DeleteLocalRef(type);
    require(method != nullptr, "Missing Android Application context method");
    const auto local = env->CallObjectMethod(context, method);
    require(!env->ExceptionCheck() && local, "Cannot obtain Android Application context");
    const auto retained = env->NewGlobalRef(local);
    env->DeleteLocalRef(local);
    require(retained != nullptr, "Cannot retain Android Application context");
    try {
      JavaVM *vm = nullptr;
      require(env->GetJavaVM(&vm) == JNI_OK, "Cannot obtain Android VM");
      auto init = typed<XrLoaderInitInfoAndroidKHR>(XR_TYPE_LOADER_INIT_INFO_ANDROID_KHR);
      init.applicationVM = vm;
      init.applicationContext = retained;
      checked(function<PFN_xrInitializeLoaderKHR>(XR_NULL_HANDLE, "xrInitializeLoaderKHR")(
                  reinterpret_cast<const XrLoaderInitInfoBaseHeaderKHR *>(&init)),
              "Initialize Android OpenXR loader");
      application = retained;
    } catch (...) { env->DeleteGlobalRef(retained); throw; }
  });
  require(application != nullptr, "Android OpenXR loader is not initialized");
}
struct Host {
  jobject activity = nullptr;
  XrInstance instance = XR_NULL_HANDLE;
  XrSystemId system = XR_NULL_SYSTEM_ID;
  std::unique_ptr<PackedSession> session;
  std::unique_ptr<gk3hd::standalone::openxr::ControllerActions> input;
  XrSpace head = XR_NULL_HANDLE;
  std::vector<GLuint> buffers;
  std::optional<PackedSession::Sample> current;
  bool headValid = false;
  bool displayRefreshRate = false;
  bool performanceSettings = false;
  gk3hd::standalone::openxr::DisplayPreference displayPreference;
  XrDuration observedPeriod = 0;
  uint32_t width = 0, height = 0;
  EyeExtent requested;
  std::thread::id owner;
  void initialize(JNIEnv *env, jobject object, EyeExtent extentOverride) {
    requested = extentOverride;
    activity = env->NewGlobalRef(object);
    require(activity != nullptr, "Cannot retain OpenXR Activity");
    JavaVM *vm = nullptr;
    require(env->GetJavaVM(&vm) == JNI_OK, "Cannot obtain Android VM");
    initializeLoader(env, object);
    const auto capabilities = gk3hd::standalone::openxr::discoverRuntime(xrEnumerateInstanceExtensionProperties);
    require(capabilities.support ==
                gk3hd::standalone::openxr::RuntimeSupport::Supported,
            "Required Android OpenXR/GLES runtime unavailable");
    displayRefreshRate = capabilities.displayRefreshRate;
    performanceSettings = capabilities.performanceSettings;
    std::vector<const char *> enabled{XR_KHR_ANDROID_CREATE_INSTANCE_EXTENSION_NAME,
                                     XR_KHR_OPENGL_ES_ENABLE_EXTENSION_NAME};
    if (displayRefreshRate) enabled.push_back(XR_FB_DISPLAY_REFRESH_RATE_EXTENSION_NAME);
    if (performanceSettings) enabled.push_back(XR_EXT_PERFORMANCE_SETTINGS_EXTENSION_NAME);
    auto android = typed<XrInstanceCreateInfoAndroidKHR>(
        XR_TYPE_INSTANCE_CREATE_INFO_ANDROID_KHR);
    android.applicationVM = vm;
    android.applicationActivity = activity;
    auto create = typed<XrInstanceCreateInfo>(XR_TYPE_INSTANCE_CREATE_INFO);
    create.next = &android;
    std::strcpy(create.applicationInfo.applicationName, "GK3HD standalone VR");
    create.applicationInfo.apiVersion = XR_MAKE_VERSION(1, 0, 0);
    create.enabledExtensionCount = uint32_t(enabled.size());
    create.enabledExtensionNames = enabled.data();
    checked(xrCreateInstance(&create, &instance),
            "Create native OpenXR instance");
    auto get = typed<XrSystemGetInfo>(XR_TYPE_SYSTEM_GET_INFO);
    get.formFactor = XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;
    checked(xrGetSystem(instance, &get, &system), "Find native headset system");
    uint32_t total = 0;
    std::array<XrViewConfigurationView, 2> views{};
    for (auto &view : views)
      view.type = XR_TYPE_VIEW_CONFIGURATION_VIEW;
    checked(xrEnumerateViewConfigurationViews(
                instance, system, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO, 2,
                &total, views.data()),
            "Query native eye recommendations");
    require(total == 2, "Native runtime does not expose two stereo eyes");
    const auto extent = selectEyeExtent(views, requested);
    width = extent.width;
    height = extent.height;
    require(width <= 4096 && height <= 4096,
            "Native eye dimensions exceed current source budget");
    auto properties = typed<XrInstanceProperties>(XR_TYPE_INSTANCE_PROPERTIES);
    checked(xrGetInstanceProperties(instance, &properties),
            "Read native runtime identity");
    __android_log_print(ANDROID_LOG_INFO, "GK3HDOpenXR",
                        "Runtime %s, %s eyes %ux%u",
                        properties.runtimeName,
                        requested.width ? "fixture" : "recommended", width, height);
    input = std::make_unique<gk3hd::standalone::openxr::ControllerActions>(
        xrGetInstanceProcAddr, instance);
  }
  void owned() const {
    require(owner == std::this_thread::get_id(),
            "OpenXR host requires its graphics thread");
  }
  void attach() {
    require(!session, "Native graphics already attached");
    owner = std::this_thread::get_id();
    const EGLDisplay display = eglGetCurrentDisplay();
    const EGLContext context = eglGetCurrentContext();
    require(display != EGL_NO_DISPLAY && context != EGL_NO_CONTEXT,
            "Native OpenXR requires a current EGL context");
    EGLint id = 0;
    require(eglQueryContext(display, context, EGL_CONFIG_ID, &id) == EGL_TRUE,
            "Cannot query actual EGL config");
    EGLConfig config = nullptr;
    EGLint count = 0;
    const EGLint attributes[] = {EGL_CONFIG_ID, id, EGL_NONE};
    require(eglChooseConfig(display, attributes, &config, 1, &count) ==
                    EGL_TRUE &&
                count == 1,
            "Cannot resolve actual EGL config");
    auto requirements = typed<XrGraphicsRequirementsOpenGLESKHR>(
        XR_TYPE_GRAPHICS_REQUIREMENTS_OPENGL_ES_KHR);
    checked(function<PFN_xrGetOpenGLESGraphicsRequirementsKHR>(
                instance, "xrGetOpenGLESGraphicsRequirementsKHR")(
                instance, system, &requirements),
            "Native GLES requirements");
    GLint major = 0, minor = 0, limit = 0, viewport[2] = {};
    glGetIntegerv(GL_MAJOR_VERSION, &major);
    glGetIntegerv(GL_MINOR_VERSION, &minor);
    glGetIntegerv(GL_MAX_TEXTURE_SIZE, &limit);
    glGetIntegerv(GL_MAX_VIEWPORT_DIMS, viewport);
    const XrVersion version = XR_MAKE_VERSION(major, minor, 0);
    require(version >= requirements.minApiVersionSupported &&
                version <= requirements.maxApiVersionSupported && limit > 0 &&
                viewport[0] > 0 && viewport[1] > 0,
            "Current GLES context does not meet runtime requirements");
    auto binding = typed<XrGraphicsBindingOpenGLESAndroidKHR>(
        XR_TYPE_GRAPHICS_BINDING_OPENGL_ES_ANDROID_KHR);
    binding.display = display;
    binding.config = config;
    binding.context = context;
    session = std::make_unique<PackedSession>(
        xrGetInstanceProcAddr, instance, system,
        PackedSession::Graphics{&binding, GL_SRGB8_ALPHA8,
                                uint32_t(std::min(limit, viewport[0])),
                                uint32_t(std::min(limit, viewport[1])),
                                [] { glFlush(); }, [] { glFinish(); }},
        requested);
    try {
      displayPreference = {};
      observedPeriod = 0;
      input->attach(session->session());
      gk3hd::standalone::openxr::PerformancePreference performance;
      performance.apply(xrGetInstanceProcAddr, instance, session->session(), performanceSettings);
      __android_log_print(ANDROID_LOG_INFO, "GK3HDOpenXR",
                          "Sustained performance hint available=%d CPU result=%d GPU result=%d; runtime controls clocks",
                          int(performanceSettings), int(performance.results[0]), int(performance.results[1]));
      require(session->eyeWidth() == width && session->eyeHeight() == height,
              "Native eye dimensions changed while attaching graphics");
      auto space = typed<XrReferenceSpaceCreateInfo>(
          XR_TYPE_REFERENCE_SPACE_CREATE_INFO);
      space.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_VIEW;
      space.poseInReferenceSpace.orientation.w = 1;
      checked(xrCreateReferenceSpace(session->session(), &space, &head),
              "Create native head space");
      uint32_t imagesCount = 0;
      std::vector<XrSwapchainImageOpenGLESKHR> images(
          session->imageCount(), typed<XrSwapchainImageOpenGLESKHR>(
                                     XR_TYPE_SWAPCHAIN_IMAGE_OPENGL_ES_KHR));
      checked(
          xrEnumerateSwapchainImages(
              session->swapchain(), uint32_t(images.size()), &imagesCount,
              reinterpret_cast<XrSwapchainImageBaseHeader *>(images.data())),
          "Read actual native GLES images");
      require(imagesCount == images.size(), "Native image count changed");
      buffers.resize(imagesCount);
      glGenFramebuffers(GLsizei(buffers.size()), buffers.data());
      GLint previous = 0;
      glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &previous);
      for (size_t i = 0; i < images.size(); ++i) {
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, buffers[i]);
        glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, images[i].image, 0);
        require(glCheckFramebufferStatus(GL_DRAW_FRAMEBUFFER) ==
                    GL_FRAMEBUFFER_COMPLETE,
                "Native GLES image is not renderable");
      }
      glBindFramebuffer(GL_DRAW_FRAMEBUFFER, GLuint(previous));
      require(glGetError() == GL_NO_ERROR, "Native graphics setup error");
    } catch (...) {
      try {
        detach();
      } catch (...) {
      }
      throw;
    }
  }
  void detach() {
    owned();
    current.reset();
    headValid = false;
    if (session) {
      // Finish the open frame while its images still exist, then retire
      // our FBO references before destroying the runtime image objects.
      glFinish();
      if (!buffers.empty())
        glDeleteFramebuffers(GLsizei(buffers.size()), buffers.data());
      buffers.clear();
      if (head) {
        checked(xrDestroySpace(head), "Destroy native head space");
        head = XR_NULL_HANDLE;
      }
      input->detach();
      session->close();
      session.reset();
    }
  }
  bool next(float *poses, jlong *state) {
    owned();
    require(bool(session), "Native graphics not attached");
    current = session->begin();
    headValid = false;
    if (!current) {
      state[0] = static_cast<jlong>(session->endReason());
      return false;
    }
    const auto &sample = *current;
    if (displayPreference.apply(xrGetInstanceProcAddr, instance,
                                session->session(), displayRefreshRate,
                                sample.focused && sample.shouldRender)) {
      std::string supported;
      for (const auto rate : displayPreference.rates.supported) {
        if (!supported.empty()) supported += ",";
        supported += std::to_string(rate);
      }
      __android_log_print(ANDROID_LOG_INFO, "GK3HDOpenXR",
                          "Display preference current=%.3f Hz supported=[%s] requested=%.3f Hz result=%d; follow actual predicted period",
                          double(displayPreference.rates.current), supported.c_str(),
                          double(displayPreference.requested), int(displayPreference.result));
    }
    // Actual predicted periods are useful even without the optional extension.
    // Suppress integer-nanosecond jitter and keep diagnostics out of steady frames.
    if (sample.period > 0 &&
        (!observedPeriod || std::abs(double(sample.period) / double(observedPeriod) - 1) > .01)) {
      observedPeriod = sample.period;
      __android_log_print(ANDROID_LOG_INFO, "GK3HDOpenXR",
                          "Native predicted display cadence=%.3f Hz period=%lld ns",
                          1e9 / double(sample.period), static_cast<long long>(sample.period));
    }
    state[0] = jlong(sample.serial);
    state[1] = sample.time;
    state[2] = sample.period;
    state[3] = 0;
    state[4] = sample.shouldRender;
    state[5] = sample.focused;
    state[6] = jlong(sample.epoch);
    auto location = typed<XrSpaceLocation>(XR_TYPE_SPACE_LOCATION);
    checked(xrLocateSpace(head, session->space(), sample.time, &location),
            "Locate actual native head");
    headValid = gk3hd::standalone::openxr::locatedPose(location) &&
                (sample.flags & 3) == 3;
    if (!headValid)
      return true;
    state[3] = jlong(location.locationFlags & sample.flags);
    state[7] = jlong(session->reusableSerial());
    putPose(poses, location.pose);
    for (unsigned eye = 0; eye < 2; ++eye) {
      auto *out = poses + 7 + eye * 11;
      putPose(out, gk3hd::standalone::openxr::relativeView(
                       location.pose, sample.eyes[eye].pose));
      const auto &f = sample.eyes[eye].fov;
      out[7] = f.angleLeft;
      out[8] = f.angleRight;
      out[9] = f.angleUp;
      out[10] = f.angleDown;
    }
    return true;
  }
  GLuint acquire() {
    owned();
    require(current && headValid && bool(session),
            "No tracked native frame available");
    // A zero-timeout poll can drop a layer while the image is merely busy.
    // Keep waiting in this frame, with a finite budget for a stalled runtime.
    // Zero indicates the runtime timed out. An unwaited image stays owned
    // by the session and is never released or exposed for drawing.
    const auto index = session->acquire();
    return index ? buffers.at(*index) : 0;
  }
  std::array<gk3hd::standalone::openxr::ControllerActions::Hand, 2>
  controllers() {
    owned();
    require(current && session && input,
            "No native frame for controller sampling");
    return input->sample(session->space(), current->time,
                         headValid && current->focused &&
                             current->shouldRender);
  }
  bool end(uint64_t serial, bool repeatReleased = false) {
    owned();
    require(current && session, "No native frame to submit");
    require(!serial || headValid,
            "Cannot submit images after native tracking withdrawal");
    if (serial && !repeatReleased)
      session->release();
    const bool submitted = session->endRendered(serial, repeatReleased);
    current.reset();
    return submitted;
  }
  void close(JNIEnv *env) {
    if (session)
      detach();
    if (input) {
      input->close();
      input.reset();
    }
    if (instance) {
      checked(xrDestroyInstance(instance), "Destroy native instance");
      instance = XR_NULL_HANDLE;
    }
    if (activity) {
      env->DeleteGlobalRef(activity);
      activity = nullptr;
    }
  }
};
template <class F>
auto invoke(JNIEnv *env, F call) noexcept -> decltype(call()) {
  using Result = decltype(call());
  try {
    return call();
  } catch (const std::exception &error) {
    jclass type = env->FindClass("java/lang/IllegalStateException");
    if (type)
      env->ThrowNew(type, error.what());
    if constexpr (!std::is_void_v<Result>)
      return Result{};
  }
}
Host &host(jlong pointer) {
  require(pointer != 0, "Closed native OpenXR host");
  return *reinterpret_cast<Host *>(pointer);
}
} // namespace
extern "C" JNIEXPORT jint JNICALL
Java_org_gk3hd_standalone_NativeOpenXr_capabilities(JNIEnv *env, jclass, jobject context) {
  return invoke(env, [&]() -> jint {
    initializeLoader(env, context);
    return jint(gk3hd::standalone::openxr::discoverRuntime(xrEnumerateInstanceExtensionProperties).support);
  });
}
extern "C" JNIEXPORT jlong JNICALL
Java_org_gk3hd_standalone_NativeOpenXr_create(JNIEnv *env, jclass,
                                              jobject activity, jint width,
                                              jint height) {
  return invoke(env, [&]() -> jlong {
    require(width >= 0 && height >= 0, "Negative requested native eye dimensions");
    auto value = std::make_unique<Host>();
    try {
      value->initialize(env, activity, {uint32_t(width), uint32_t(height)});
    } catch (...) {
      try {
        value->close(env);
      } catch (...) {
      }
      throw;
    }
    return reinterpret_cast<jlong>(value.release());
  });
}
extern "C" JNIEXPORT void JNICALL
Java_org_gk3hd_standalone_NativeOpenXr_dimensions(JNIEnv *env, jclass,
                                                  jlong pointer,
                                                  jintArray output) {
  invoke(env, [&] {
    require(output && env->GetArrayLength(output) == 2,
            "Expected native eye dimensions");
    auto &value = host(pointer);
    const jint sizes[] = {jint(value.width), jint(value.height)};
    env->SetIntArrayRegion(output, 0, 2, sizes);
  });
}
extern "C" JNIEXPORT void JNICALL Java_org_gk3hd_standalone_NativeOpenXr_attach(
    JNIEnv *env, jclass, jlong pointer) {
  invoke(env, [&] { host(pointer).attach(); });
}
extern "C" JNIEXPORT void JNICALL Java_org_gk3hd_standalone_NativeOpenXr_detach(
    JNIEnv *env, jclass, jlong pointer) {
  invoke(env, [&] { host(pointer).detach(); });
}
extern "C" JNIEXPORT jboolean JNICALL
Java_org_gk3hd_standalone_NativeOpenXr_next(JNIEnv *env, jclass, jlong pointer,
                                            jfloatArray poses,
                                            jlongArray state) {
  return invoke(env, [&]() -> jboolean {
    require(poses && state && env->GetArrayLength(poses) == 29 &&
                env->GetArrayLength(state) == 8,
            "Expected native frame arrays");
    float values[29]{};
    jlong metadata[8]{};
    const bool present = host(pointer).next(values, metadata);
    env->SetFloatArrayRegion(poses, 0, 29, values);
    env->SetLongArrayRegion(state, 0, 8, metadata);
    return present ? JNI_TRUE : JNI_FALSE;
  });
}
extern "C" JNIEXPORT jint JNICALL
Java_org_gk3hd_standalone_NativeOpenXr_acquire(JNIEnv *env, jclass,
                                               jlong pointer) {
  return invoke(env, [&]() -> jint { return jint(host(pointer).acquire()); });
}
extern "C" JNIEXPORT void JNICALL
Java_org_gk3hd_standalone_NativeOpenXr_controllers(JNIEnv *env, jclass,
                                                   jlong pointer,
                                                   jfloatArray values,
                                                   jintArray metadata) {
  invoke(env, [&] {
    require(values && metadata && env->GetArrayLength(values) == 36 &&
                env->GetArrayLength(metadata) == 6,
            "Expected native controller arrays");
    const auto hands = host(pointer).controllers();
    float poses[36]{};
    jint state[6]{};
    for (unsigned hand = 0; hand < 2; ++hand) {
      const auto &input = hands[hand];
      auto *out = poses + hand * 18;
      auto *flags = state + hand * 3;
      putPose(out, input.aim.pose);
      putPose(out + 7, input.grip.pose);
      out[14] = input.stick.x;
      out[15] = input.stick.y;
      out[16] = input.trigger;
      out[17] = input.squeeze;
      flags[0] = jint(input.aim.locationFlags);
      flags[1] = jint(input.grip.locationFlags);
      flags[2] = jint(input.buttons);
    }
    env->SetFloatArrayRegion(values, 0, 36, poses);
    env->SetIntArrayRegion(metadata, 0, 6, state);
  });
}
extern "C" JNIEXPORT jboolean JNICALL Java_org_gk3hd_standalone_NativeOpenXr_end(
    JNIEnv *env, jclass, jlong pointer, jlong serial) {
  return invoke(env, [&]() -> jboolean {
    require(serial >= 0, "Invalid native frame serial");
    return host(pointer).end(uint64_t(serial)) ? JNI_TRUE : JNI_FALSE;
  });
}
extern "C" JNIEXPORT jboolean JNICALL Java_org_gk3hd_standalone_NativeOpenXr_repeat(
    JNIEnv *env, jclass, jlong pointer, jlong serial) {
  return invoke(env, [&]() -> jboolean {
    require(serial > 0, "Invalid repeated native frame serial");
    return host(pointer).end(uint64_t(serial), true) ? JNI_TRUE : JNI_FALSE;
  });
}
extern "C" JNIEXPORT void JNICALL Java_org_gk3hd_standalone_NativeOpenXr_close(
    JNIEnv *env, jclass, jlong pointer) {
  invoke(env, [&] {
    auto *value = &host(pointer);
    value->close(env);
    delete value;
  });
}
