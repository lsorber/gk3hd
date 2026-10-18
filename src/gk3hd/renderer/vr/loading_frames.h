#pragma once

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <exception>
#include <functional>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <utility>

namespace gk3hd::vr {

// Exclusive temporary ownership of XR submission while the game thread loads.
// The callback must serialize the bound Vulkan queue and must not call the game
// or render world geometry. Normal rendering must stop/join this owner first.
class LoadingFrames {
public:
  using Step = std::function<bool()>;
  using Report = std::function<void(const std::exception_ptr&)>;
  ~LoadingFrames() { stopNoThrow(); }
  LoadingFrames() = default;
  LoadingFrames(const LoadingFrames&) = delete;
  LoadingFrames& operator=(const LoadingFrames&) = delete;

  void start(Step step, Report report) {
    if (!step) throw std::invalid_argument("loading requires a frame callback");
    // Start/stop belong to the sole renderer thread. The worker only reads the
    // stop flag under this mutex and records its failure after releasing XR.
    if (thread_.joinable()) {
      if (active_) return;
      stop();
    }
    if (failure_) std::rethrow_exception(failure_);
    {
      std::lock_guard<std::mutex> lock(mutex_);
      stopping_ = false;
    }
    active_ = true;
    try {
      thread_ = std::thread([this, step=std::move(step), report=std::move(report)] {
        try {
          for (;;) {
            {
              std::lock_guard<std::mutex> lock(mutex_);
              if (stopping_) break;
            }
            const bool submitted = step();
            if (submitted) ++frames_;
            // Give asset uploads access to their shared queue, and avoid a
            // busy loop when an invisible/stopping runtime has no frame.
            std::unique_lock<std::mutex> lock(mutex_);
            if (wake_.wait_for(lock, std::chrono::milliseconds(submitted ? 1 : 5),
                               [this] { return stopping_; })) break;
          }
        } catch (...) {
          failure_ = std::current_exception();
          if (report) {
            try { report(failure_); } catch (...) { }
          }
        }
        active_ = false;
      });
    } catch (...) {
      active_ = false;
      throw;
    }
  }

  void stop() {
    if (thread_.joinable()) {
      {
        std::lock_guard<std::mutex> lock(mutex_);
        stopping_ = true;
      }
      wake_.notify_all();
      thread_.join();
    }
    if (failure_) std::rethrow_exception(failure_);
  }
  void stopNoThrow() noexcept { try { stop(); } catch (...) { } }
  bool active() const { return active_; }
  uint64_t frames() const { return frames_; }
private:
  std::thread thread_;
  std::mutex mutex_;
  std::condition_variable wake_;
  bool stopping_ = false;
  std::atomic<bool> active_{false};
  std::atomic<uint64_t> frames_{0};
  std::exception_ptr failure_;
};

} // namespace gk3hd::vr
