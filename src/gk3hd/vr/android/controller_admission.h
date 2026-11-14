#pragma once
#include "controller_history.h"
#include <algorithm>
#include <cstdint>
#include <limits>
#include <vector>

namespace gk3hd::standalone {

// Controller event admission, independent of tracking. The caller serializes this object with
// receiver admission and owner changes. Neither querying nor acknowledging an
// event modifies tracking or OpenXR's current action state. An owner is supplied
// by the native consumer, never inferred from a frame number or hand pose.
template<class State, size_t Capacity=32>
class ControllerFrameAdmission {
public:
  using History=ControllerHistory<State,Capacity>;
  using Event=typename History::Event;
  using Batch=typename History::Batch;
  struct Frame {
    uint64_t admission=0,owner=0,generation=0,overflows=0;
    uint32_t poseFrame=0;
    std::vector<Event> events;
  };
  bool setOwner(uint64_t owner) {
    if(owner_==owner)return false;
    owner_=owner;pending_.clear();generation_=0;
    return true;
  }
  void admit(const State& latest,Batch batch,int64_t now) {
    if(admission_==(std::numeric_limits<uint64_t>::max)())
      throw std::overflow_error("controller admission identity exhausted");
    ++admission_;poseFrame_=uint32_t(latest.frameId);
    if(batch.generation!=generation_)pending_.clear();
    generation_=batch.generation;overflows_=batch.overflows;
    const auto& life=latest.inputLifetime;
    if(!owner_||now<0||!life.present||!life.focused||life.withdrawal||
       !life.source||!life.poseEpoch||!life.generation) {
      pending_.clear();return;
    }
    // A new cut never renews an old event's original timestamp. Expiry drops
    // the pending batch, rather than extending a historical held level.
    if(!pending_.empty()&&(now<pending_.back().received||
                          now-pending_.front().received>=250000000))pending_.clear();
    if(pending_.size()+batch.events.size()>Capacity) {
      if(admissionOverflows_==(std::numeric_limits<uint64_t>::max)())
        throw std::overflow_error("controller overflow identity exhausted");
      ++admissionOverflows_;pending_.clear();return;
    }
    uint64_t sequence=lastSequence_;
    int64_t stamp=pending_.empty()?-1:pending_.back().received;
    for(const auto& event:batch.events) {
      const auto& source=event.state.inputLifetime;
      if(event.sequence<=sequence||event.generation!=generation_||
         event.sourceEpoch!=life.poseEpoch||uint32_t(event.state.frameId)!=event.frame||
         uint32_t(poseFrame_-event.frame)>=0x80000000u||event.received<stamp||
         event.received<0||event.received>now||now-event.received>=250000000||
         !source.present||!source.focused||source.withdrawal||
         source.source!=life.source||source.poseEpoch!=life.poseEpoch||
         source.generation!=life.generation) {
        pending_.clear();return;
      }
      sequence=event.sequence;stamp=event.received;
    }
    for(auto& event:batch.events)pending_.push_back(std::move(event));
    lastSequence_=sequence;
  }
  Frame info()const {
    if(overflows_>(std::numeric_limits<uint64_t>::max)()-admissionOverflows_)
      throw std::overflow_error("controller overflow count exhausted");
    return {admission_,owner_,generation_,overflows_+admissionOverflows_,poseFrame_,{}};
  }
  const std::vector<Event>& events()const {return pending_;}
  Frame read()const {auto result=info();result.events=pending_;return result;}
  bool acknowledge(uint64_t owner,uint64_t admission,uint64_t sequence) {
    if(!owner||owner!=owner_||!admission||admission!=admission_)return false;
    const auto found=std::find_if(pending_.begin(),pending_.end(),
      [sequence](const Event& event){return event.sequence==sequence;});
    if(found==pending_.end())return false;
    pending_.erase(pending_.begin(),found+1);return true;
  }
private:
  uint64_t admission_=0,owner_=0,generation_=0,overflows_=0,lastSequence_=0;
  uint64_t admissionOverflows_=0;
  uint32_t poseFrame_=0;
  std::vector<Event> pending_;
};
}
