#pragma once
#include <array>
#include <cmath>
#include <cstddef>
#include <cstring>
#include <stdexcept>
#include <openxr/openxr.h>

namespace gk3hd::standalone {
struct HostEye {
    std::array<float,7> pose{}; // xyz, quaternion xyzw relative to head
    std::array<float,4> fov{};  // left, right, up, down radians
};
static_assert(sizeof(HostEye)==44&&sizeof(float)==4);
struct HostStereoViews {
    bool present=false;
    std::array<HostEye,2> eyes{};
};
inline HostStereoViews readStereoViews(const char* bytes,size_t length) {
    if(length!=88) throw std::invalid_argument("Exact stereo view extent");
    HostStereoViews result;
    std::memcpy(result.eyes.data(),bytes,88);
    for(const auto& eye:result.eyes) {
        for(float value:eye.pose) if(!std::isfinite(value)) throw std::invalid_argument("Non-finite eye pose");
        float norm=0;for(unsigned i=3;i<7;++i)norm+=eye.pose[i]*eye.pose[i];
        if(std::abs(norm-1)>.001f) throw std::invalid_argument("Invalid eye orientation");
        for(float value:eye.fov)
            if(!std::isfinite(value)||std::abs(value)>=1.5707963267948966f)
                throw std::invalid_argument("Unsupported eye FOV");
        if(eye.fov[0]>=eye.fov[1]||eye.fov[3]>=eye.fov[2]) throw std::invalid_argument("Inverted eye FOV");
    }
    result.present=true;return result;
}
inline XrView hostEyeInSpace(const XrPosef& head,const HostEye& eye) {
    const auto& a=head.orientation;const auto& b=eye.pose;
    XrView result{};result.type=XR_TYPE_VIEW;
    result.pose.orientation={a.w*b[3]+a.x*b[6]+a.y*b[5]-a.z*b[4],
        a.w*b[4]-a.x*b[5]+a.y*b[6]+a.z*b[3],
        a.w*b[5]+a.x*b[4]-a.y*b[3]+a.z*b[6],a.w*b[6]-a.x*b[3]-a.y*b[4]-a.z*b[5]};
    const float tx=2*(a.y*b[2]-a.z*b[1]),ty=2*(a.z*b[0]-a.x*b[2]),tz=2*(a.x*b[1]-a.y*b[0]);
    result.pose.position={head.position.x+b[0]+a.w*tx+a.y*tz-a.z*ty,
        head.position.y+b[1]+a.w*ty+a.z*tx-a.x*tz,
        head.position.z+b[2]+a.w*tz+a.x*ty-a.y*tx};
    result.fov={eye.fov[0],eye.fov[1],eye.fov[2],eye.fov[3]};
    return result;
}
}
