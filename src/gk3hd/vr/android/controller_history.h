#pragma once
#include "host_input_lifetime.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <type_traits>
#include <vector>

namespace gk3hd::standalone {

// Bounded observed-input journal. State is a parsed WXR snapshot; this class
// neither publishes a render pose nor authorizes an action in a game scene.
template<class State,size_t Capacity=32>
class ControllerHistory {
  static_assert(Capacity>0 && Capacity<=64);
  static_assert(std::is_nothrow_move_assignable_v<State>);
public:
  enum class Result { Baseline, Unchanged, Queued, Barrier, Overflow, Rejected, Invalid };
  struct Event {
    uint64_t sourceEpoch=0,generation=0,sequence=0;
    uint32_t frame=0,pressed=0,released=0;
    int64_t received=0;
    State state{};
  };
  struct Batch {
    uint64_t generation=0,overflows=0;
    std::vector<Event> events;
  };
  Result observe(const HostInputLifetime& lifetime,const State& state,int64_t now) {
    const auto frame=uint32_t(state.frameId);
    if(now<0) {retire();return Result::Invalid;}
    // The current host's explicit lifecycle is authoritative. Legacy packets,
    // foreign hosts and delayed generations cannot retire or append input.
    if(!lifetime.present||!lifetime.source||!lifetime.poseEpoch||!lifetime.generation||
       !sourceOrder_.accept(lifetime,frame))
      return Result::Rejected;
    const bool newEpoch=lifetime.poseEpoch!=epoch_;
    const bool newLifetime=newEpoch||lifetime.generation!=inputGeneration_;
    if(newLifetime) {
      retire();epoch_=lifetime.poseEpoch;inputGeneration_=lifetime.generation;
      if(newEpoch) {haveFrame_=false;lastTime_=-1;}
    }
    // A control-only withdrawal has no new tracking sample. Never renew pose
    // age or create a release event from it; retire the old action batch.
    if(!lifetime.focused)return newLifetime?Result::Barrier:Result::Unchanged;
    Key next{};
    if(!key(state,next)) {
      accept(frame,now);retire();haveKey_=false;return Result::Invalid;
    }
    const bool discontinuity=haveFrame_&&now<lastTime_;
    const bool barrier=haveKey_&&(next.recenter!=previous_.recenter||
      next.poses!=previous_.poses||!std::equal(next.validity.begin(),next.validity.begin()+next.poses,
                                             previous_.validity.begin()));
    if(!haveKey_||barrier||discontinuity) {
      const bool initial=!haveKey_&&!discontinuity;
      if(barrier||discontinuity)retire();
      previous_=next;haveKey_=true;accept(frame,now);
      return initial?Result::Baseline:Result::Barrier;
    }
    if(next.buttons==previous_.buttons&&next.analogs==previous_.analogs) {
      accept(frame,now);return Result::Unchanged;
    }
    if(count_==Capacity) {
      retire();++overflows_;previous_=next;accept(frame,now);return Result::Overflow;
    }
    if(sequence_==(std::numeric_limits<uint64_t>::max)())throw std::overflow_error("input sequence exhausted");
    uint32_t pressed=0,released=0;
    for(unsigned bit=0;bit<next.buttons.size();++bit) {
      if(next.buttons[bit]&&!previous_.buttons[bit])pressed|=1u<<bit;
      if(!next.buttons[bit]&&previous_.buttons[bit])released|=1u<<bit;
    }
    State copy=state;
    pending_[count_++]={epoch_,generation_,++sequence_,frame,pressed,released,now,std::move(copy)};
    previous_=next;accept(frame,now);return Result::Queued;
  }
  Batch drain(int64_t now) {
    if(now<0||(haveFrame_&&now<lastTime_)||
       (count_&&now-pending_[0].received>=250000000)) {
      retire();haveKey_=false;
    }
    Batch result{generation_,overflows_,{}};
    result.events.reserve(count_);
    for(size_t i=0;i<count_;++i)result.events.push_back(std::move(pending_[i]));
    count_=0;
    return result;
  }
  void retire() {
    if(generation_==(std::numeric_limits<uint64_t>::max)())throw std::overflow_error("input generation exhausted");
    for(size_t i=0;i<count_;++i)pending_[i]={};
    count_=0;++generation_;haveKey_=false;
  }
  void retirePending() {
    // A native UI handoff retires actions, not the already observed controls.
    // Preserve that baseline so the first genuinely new tap is not swallowed.
    const bool baseline=haveKey_;retire();haveKey_=baseline;
  }
private:
  struct Key {
    int32_t recenter;
    size_t poses;
    std::array<bool,19> buttons;
    std::array<float,4> analogs;
    std::array<std::array<uint32_t,3>,256> validity;
  };
  static bool key(const State& state,Key& result) {
    if(state.poses.size()>result.validity.size())return false;
    result.recenter=state.recenterId;result.poses=state.poses.size();
    for(size_t i=0;i<19;++i)result.buttons[i]=state.buttons[i];
    for(size_t i=0;i<4;++i) {
      float value=state.floats[4+i];
      if(!std::isfinite(value)||value<0||value>1)return false;
      result.analogs[i]=value;
    }
    for(size_t i=0;i<result.poses;++i) {
      const auto& pose=state.poses[i];
      if(pose.locationFlags&~15u)return false;
      result.validity[i]={uint32_t(pose.space),uint32_t(pose.baseSpace),pose.locationFlags&3u};
    }
    std::sort(result.validity.begin(),result.validity.begin()+result.poses);
    for(size_t i=1;i<result.poses;++i)
      if(result.validity[i][0]==result.validity[i-1][0]&&
         result.validity[i][1]==result.validity[i-1][1])return false;
    return true;
  }
  void accept(uint32_t frame,int64_t now) {lastFrame_=frame;lastTime_=now;haveFrame_=true;}
  std::array<Event,Capacity> pending_{};
  InputSourceOrder sourceOrder_;
  Key previous_{};
  uint64_t epoch_=0,inputGeneration_=0,generation_=1,sequence_=0,overflows_=0;
  uint32_t lastFrame_=0;
  int64_t lastTime_=-1;
  size_t count_=0;
  bool haveFrame_=false,haveKey_=false;
};
}
