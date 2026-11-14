#include "conservative_camera.h"
#include "shared_projection.h"
#include <iostream>
#include <limits>

using namespace gk3hd::vr;
namespace {
void require(bool condition, const char* message) { if (!condition) throw std::runtime_error(message); }
using Vector = std::array<double,4>;
Vector multiply(Vector point, const shared_projection::Matrix& matrix) {
  Vector result{};
  for (unsigned i=0; i<4; ++i) for (unsigned j=0; j<4; ++j) result[j] += point[i]*matrix[i][j];
  return result;
}
void projectionEquivalence() {
  EngineCamera base{};
  base.position = {123, 61, -200};
  base.worldToCamera = {1,0,0,0,1,0,0,0,1,-123,-61,200};
  unsigned comparisons = 0;
  for (float cant : {-.2f,0.f,.2f}) for (float separation : {0.f,.064f}) {
    std::array<EyeCamera,2> eyes{};
    for (unsigned eye=0; eye<2; ++eye) {
      const float yaw = eye ? cant : -cant;
      eyes[eye] = engineEyeCamera(base, {{0,std::sin(yaw/2),0,std::cos(yaw/2)},
                                      {eye ? separation/2 : -separation/2,.05f,-.1f}},
        eye ? XrFovf{-.7f,.85f,.8f,-.65f} : XrFovf{-.9f,.7f,.75f,-.8f},
        2060, 2160, 40, .05f, 600.f);
    }
    const auto source = conservativeStereoCamera(eyes);
    require(bool(source), "stereo camera could not be enclosed");
    for (double center : {0.,.5}) for (bool rotationOnly : {false,true}) for (unsigned eye=0; eye<2; ++eye) {
      const auto transform = shared_projection::transform(*source, eyes[eye], 4120, 2160, eye*2060, center, rotationOnly);
      for (double depth : {4.,40.,400.,4000.}) for (double x : {-10.,0.,10.}) for (double y : {-3.,0.,3.}) {
        const Vector world = rotationOnly ? Vector{x,y,depth,1} : Vector{base.position.x+x,base.position.y+y,base.position.z+depth,1};
        const auto local = multiply(world, shared_projection::view(*source, rotationOnly));
        // Independent scalar legacy TL conversion, including packed-canvas
        // normalization performed before the extra shader transform.
        const auto& p = source->projection;
        const Vector legacy{2*(p.focalX*local[0]+(p.centerX-center)*local[2])/4120-local[2],
                            2*(p.focalY*local[1]-(p.centerY-center)*local[2])/2160+local[2],
                            local[2],1};
        const auto actual = multiply(legacy, transform);
        const auto target = multiply(world, shared_projection::view(eyes[eye], rotationOnly));
        const auto& q = eyes[eye].projection;
        const Vector expected{2*(q.focalX*target[0]+(q.centerX+eye*2060-center)*target[2])/4120-target[2],
                              2*(q.focalY*target[1]-(q.centerY-center)*target[2])/2160+target[2],
                              q.depthA*target[2]+q.depthB,target[2]};
        for (unsigned i=0; i<4; ++i) {
          require(std::isfinite(actual[i]) && std::abs(actual[i]-expected[i]) < 1e-7*std::max(1.,std::abs(expected[i])),
                  "shared transform differs from independent native per-eye projection");
          ++comparisons;
        }
      }
    }
  }
  require(comparisons == 6912, "stereo projection coverage unexpectedly changed");
}
void invalidInputs() {
  EngineCamera base{}; base.worldToCamera = {1,0,0,0,1,0,0,0,1,0,0,0};
  const auto eye = engineEyeCamera(base, {{0,0,0,1},{0,0,0}}, {-.7f,.7f,.7f,-.7f}, 2000, 2000, 40, .05f, 600.f);
  for (unsigned variant=0; variant<6; ++variant) {
    auto source = eye;
    uint32_t width=4000, height=2000, offset=2000;
    double center=0;
    if (variant==0) width=0;
    if (variant==1) height=0;
    if (variant==2) offset=2001;
    if (variant==3) source.camera.worldToCamera={};
    if (variant==4) source.projection.depthB=std::numeric_limits<float>::quiet_NaN();
    if (variant==5) center=std::numeric_limits<double>::infinity();
    bool failed=false;
    try { shared_projection::transform(source,eye,width,height,offset,center,false); }
    catch (const std::invalid_argument&) { failed=true; }
    require(failed,"invalid stereo input did not fail before drawing");
  }
}
}
int main() {
  try {
    projectionEquivalence(); invalidInputs();
    std::cout << "Shared projection: canted/asymmetric eyes, IPD, depth, sky and pixel centers passed\n";
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
