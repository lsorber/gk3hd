#include "tracking_freshness.h"
#include <array>
#include <cstdint>
#include <cstdio>

struct Pose {
    uint32_t locationFlags=15;
    float pose[7]{1,2,3,0,0,0,1},velocity[7]{63,1,2,3,4,5,6};
};
struct State {
    float floats[12]{1,1,1,1,1,1,1,1,.06352f,90,90,90};
    bool buttons[19]{true,true,true};
    std::array<Pose,3> poses;
    int frameId=123,recenterId=7;
};
#define REQUIRE(test) do {if(!(test)){std::fprintf(stderr,"Failed: %s\n",#test);return 1;}} while(0)
int main() {
    State state;
    REQUIRE(!gk3hd::standalone::expireTracking(state,std::chrono::milliseconds(249)));
    REQUIRE(state.floats[1]==1&&state.buttons[0]&&state.poses[1].locationFlags==15);
    REQUIRE(gk3hd::standalone::expireTracking(state,std::chrono::milliseconds(250)));
    for(unsigned i=0;i<8;i++) REQUIRE(state.floats[i]==0);
    for(bool held:state.buttons) REQUIRE(!held);
    for(const auto& pose:state.poses) {
        REQUIRE(pose.locationFlags==0);
        for(float value:pose.pose) REQUIRE(value==0);
        for(float value:pose.velocity) REQUIRE(value==0);
    }
    REQUIRE(state.floats[8]==.06352f&&state.floats[11]==90&&state.frameId==123&&state.recenterId==7);
    state=State{};
    REQUIRE(gk3hd::standalone::expireTracking(state,-std::chrono::milliseconds(1)));
    REQUIRE(!state.buttons[0]&&state.poses[0].locationFlags==0);
    std::puts("Tracking expiry: fresh data retained; stalled/backward-time input and poses retired; optics preserved");
}
