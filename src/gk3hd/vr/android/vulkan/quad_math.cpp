#include "quad.h"
#include <cmath>
#include <stdexcept>

namespace gk3hd::standalone {
namespace {
void validPose(const XrPosef& pose) {
    const auto& p=pose.position;const auto& q=pose.orientation;
    float norm=q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w;
    if(!std::isfinite(p.x)||!std::isfinite(p.y)||!std::isfinite(p.z)||
       !std::isfinite(norm)||std::abs(norm-1)>0.001f)
        throw std::invalid_argument("Invalid quad/eye pose");
}
XrVector3f rotate(XrQuaternionf q,XrVector3f p) {
    XrVector3f t{2*(q.y*p.z-q.z*p.y),2*(q.z*p.x-q.x*p.z),2*(q.x*p.y-q.y*p.x)};
    return {p.x+q.w*t.x+q.y*t.z-q.z*t.y,
            p.y+q.w*t.y+q.z*t.x-q.x*t.z,
            p.z+q.w*t.z+q.x*t.y-q.y*t.x};
}
}
QuadVertices projectQuad(const XrPosef& eye,const XrFovf& fov,
                         const XrPosef& quad,XrExtent2Df size,
                         XrRect2Di crop,uint32_t width,uint32_t height) {
    validPose(eye);validPose(quad);
    if(!std::isfinite(size.width)||!std::isfinite(size.height)||size.width<=0||size.height<=0||
       !width||!height||crop.offset.x<0||crop.offset.y<0||crop.extent.width<=0||crop.extent.height<=0||
       uint64_t(crop.offset.x)+crop.extent.width>width||uint64_t(crop.offset.y)+crop.extent.height>height)
        throw std::invalid_argument("Invalid quad size/crop");
    constexpr float halfPi=1.5707963267948966f;
    const float angles[]={fov.angleLeft,fov.angleRight,fov.angleDown,fov.angleUp};
    for(float a:angles) if(!std::isfinite(a)||a<=-halfPi||a>=halfPi)
        throw std::invalid_argument("Invalid eye frustum");
    float l=std::tan(fov.angleLeft),r=std::tan(fov.angleRight),
          b=std::tan(fov.angleDown),t=std::tan(fov.angleUp);
    if(l>=r||b>=t) throw std::invalid_argument("Inverted eye frustum");
    QuadVertices out{};
    const auto& q=eye.orientation;
    for(int i=0;i<4;i++) {
        XrVector3f corner{((i&2)?1:-1)*size.width*.5f,((i&1)?-1:1)*size.height*.5f,0};
        auto world=rotate(quad.orientation,corner);
        world={world.x+quad.position.x-eye.position.x,world.y+quad.position.y-eye.position.y,
               world.z+quad.position.z-eye.position.z};
        auto p=rotate({-q.x,-q.y,-q.z,q.w},world);
        // Vulkan's viewport has downward Y and [0,w] clip depth. A 1 cm near
        // plane clips geometry properly, including quads crossing the eye plane.
        out.clip[i][0]=2*p.x/(r-l)+(r+l)*p.z/(r-l);
        out.clip[i][1]=-2*p.y/(t-b)-(t+b)*p.z/(t-b);
        out.clip[i][2]=-p.z-.01f;
        out.clip[i][3]=-p.z;
    }
    out.uv[0]=float(crop.offset.x)/width;out.uv[1]=float(crop.offset.y)/height;
    out.uv[2]=float(uint64_t(crop.offset.x)+crop.extent.width)/width;
    out.uv[3]=float(uint64_t(crop.offset.y)+crop.extent.height)/height;
    return out;
}
}
