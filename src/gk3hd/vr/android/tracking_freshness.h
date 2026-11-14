#pragma once

#include <algorithm>
#include <chrono>

namespace gk3hd::standalone {

// A stalled or paused Android host must not keep the observer walking on an
// indefinitely cached packet. Keep optical metadata/frame identity, but retire
// every pose, velocity and control. Normal action latches require release on
// recovery. This does not manufacture tracking or select a newer render pose.
template<class HostState>
bool expireTracking(HostState& state,std::chrono::steady_clock::duration age) {
    if(age>=decltype(age)::zero()&&age<std::chrono::milliseconds(250)) return false;
    std::fill_n(state.floats,8,0.f);
    std::fill_n(state.buttons,19,false);
    for(auto& pose:state.poses) {
        pose.locationFlags=0;
        std::fill_n(pose.pose,7,0.f);
        std::fill_n(pose.velocity,7,0.f);
    }
    return true;
}

}
