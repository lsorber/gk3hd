#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <stdexcept>

namespace gk3hd::standalone {
struct HostInputLifetime {
    uint64_t source=0,poseEpoch=0,generation=0;
    bool present=false,focused=false,views=false,withdrawal=false;
};
inline HostInputLifetime readInputLifetime(const char* bytes,size_t length) {
    if(length<32)throw std::invalid_argument("Truncated input lifetime");
    uint32_t magic=0,flags=0;HostInputLifetime result;
    std::memcpy(&magic,bytes,4);std::memcpy(&flags,bytes+4,4);
    std::memcpy(&result.source,bytes+8,8);std::memcpy(&result.poseEpoch,bytes+16,8);
    std::memcpy(&result.generation,bytes+24,8);
    if(magic!=0x3146494cu||(flags&~7u)||!result.source||!result.poseEpoch||!result.generation||
       ((flags&4u)&&(flags&1u))||length!=32+((flags&2u)?88u:0u))
        throw std::invalid_argument("Invalid input lifetime");
    result.present=true;result.focused=(flags&1u)!=0;result.views=(flags&2u)!=0;
    result.withdrawal=(flags&4u)!=0;return result;
}

// One receiver belongs to one runtime instance and one explicitly bound host.
// Focus generations never grant permission to roll its rendering pose back.
class InputSourceOrder {
public:
    bool accept(const HostInputLifetime& value,uint32_t frame) {
        if(!value.present)return !source_;
        if(!value.source||!value.poseEpoch||!value.generation)return false;
        if(!source_) {
            if(value.withdrawal)return false;
            source_=value.source;epoch_=value.poseEpoch;generation_=value.generation;frame_=frame;
            focused_=value.focused;return true;
        }
        if(value.source!=source_||value.poseEpoch<epoch_||value.generation<generation_)return false;
        if(value.generation==generation_&&value.focused!=focused_)return false;
        if(value.withdrawal) {
            if(value.focused||value.poseEpoch!=epoch_||value.generation==generation_)return false;
            generation_=value.generation;focused_=false;return true; // No new pose or frame.
        }
        const auto delta=uint32_t(frame-frame_);
        if(value.poseEpoch==epoch_&&(!delta||delta>=0x80000000u))return false;
        epoch_=value.poseEpoch;generation_=value.generation;frame_=frame;focused_=value.focused;return true;
    }
private:
    uint64_t source_=0,epoch_=0,generation_=0;
    uint32_t frame_=0;
    bool focused_=false;
};
template<class State> void withdrawControls(State& state) {
    for(unsigned i=0;i<8;++i)state.floats[i]=0;
    for(unsigned i=0;i<19;++i)state.buttons[i]=false;
}
}
