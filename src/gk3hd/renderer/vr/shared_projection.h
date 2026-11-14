#pragma once

#include "engine_camera.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <stdexcept>

namespace gk3hd::vr::shared_projection {
// Row-vector convention, matching the native engine and D3D9 constants.
using Matrix = std::array<std::array<double, 4>, 4>;
inline Matrix product(const Matrix& a, const Matrix& b) {
  Matrix result{};
  for (unsigned i=0; i<4; ++i) for (unsigned j=0; j<4; ++j)
    for (unsigned k=0; k<4; ++k) result[i][j] += a[i][k]*b[k][j];
  return result;
}
inline Matrix inverse(Matrix a) {
  Matrix result{};
  for (unsigned i=0; i<4; ++i) result[i][i] = 1;
  for (unsigned i=0; i<4; ++i) {
    unsigned pivot = i;
    for (unsigned j=i+1; j<4; ++j)
      if (std::abs(a[j][i]) > std::abs(a[pivot][i])) pivot = j;
    if (!std::isfinite(a[pivot][i]) || std::abs(a[pivot][i]) < 1e-12)
      throw std::invalid_argument("singular stereo projection");
    std::swap(a[i], a[pivot]); std::swap(result[i], result[pivot]);
    const double divisor = a[i][i];
    for (unsigned j=0; j<4; ++j) { a[i][j] /= divisor; result[i][j] /= divisor; }
    for (unsigned j=0; j<4; ++j) if (i != j) {
      const double scale = a[j][i];
      for (unsigned k=0; k<4; ++k) { a[j][k] -= scale*a[i][k]; result[j][k] -= scale*result[i][k]; }
    }
  }
  return result;
}
inline Matrix view(const EyeCamera& eye, bool rotationOnly) {
  Matrix result{};
  for (unsigned i=0; i<3; ++i) for (unsigned j=0; j<3; ++j)
    result[i][j] = eye.camera.worldToCamera[i*3+j];
  if (!rotationOnly) for (unsigned j=0; j<3; ++j) result[3][j] = eye.camera.worldToCamera[9+j];
  result[3][3] = 1;
  return result;
}
inline Matrix projection(const EyeCamera& eye, uint32_t width, uint32_t height,
                         uint32_t offset, double pixelCenter) {
  if (!width || !height || eye.camera.width <= 0 || eye.camera.height <= 0 ||
      offset > width || uint32_t(eye.camera.width) > width-offset ||
      uint32_t(eye.camera.height) > height || !std::isfinite(pixelCenter))
    throw std::invalid_argument("invalid stereo canvas");
  const auto& p = eye.projection;
  for (float value : {p.depthA,p.depthB,p.centerX,p.centerY,p.focalX,p.focalY})
    if (!std::isfinite(value)) throw std::invalid_argument("nonfinite stereo projection");
  return {{{2*p.focalX/width,0,0,0}, {0,2*p.focalY/height,0,0},
           {2*(p.centerX+offset-pixelCenter)/width-1,1-2*(p.centerY-pixelCenter)/height,p.depthA,1},
           {0,0,p.depthB,0}}};
}
// Convert a once-projected native vertex into either eye without changing UVs,
// color, draw order or the native simulation. The shader's input is native
// clip X/Y, reconstructed physical source Z and 1, not a sampled depth image.
// Sky polygons use rotation-only matrices and retain their authored depth.
inline Matrix transform(const EyeCamera& source, const EyeCamera& target,
                        uint32_t width, uint32_t height, uint32_t offset,
                        double pixelCenter, bool rotationOnly) {
  auto plane = projection(source, width, height, 0, pixelCenter);
  for (unsigned i=0; i<4; ++i) { plane[i][2] = i==2 ? 1. : 0.; plane[i][3] = i==3 ? 1. : 0.; }
  const auto result = product(inverse(product(view(source, rotationOnly), plane)),
                              product(view(target, rotationOnly), projection(target, width, height, offset, pixelCenter)));
  for (const auto& row : result) for (const double value : row)
    if (!std::isfinite(value)) throw std::invalid_argument("nonfinite stereo transform");
  return result;
}
} // namespace gk3hd::vr::shared_projection
