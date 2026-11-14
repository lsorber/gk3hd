// Exercise the test runtime's real layer validation without creating a GPU.
// This does not qualify a renderer, device, tracking source or compositor FPS.
#include "gpu_test_runtime.cpp"

#include <iostream>
#include <stdexcept>

namespace {
void requireContract(bool value) {
  if (!value) throw std::runtime_error("projection subimage contract failed");
}
void projectionContracts() {
  Session owner, other;
  owner.skipPixelReadback = true; owner.frameSequence = 1;
  Chain left, right;
  for (auto* target : {&left, &right}) {
    target->session = &owner; target->releasedFrame = 1;
    target->width = 512; target->height = 256;
  }
  XrCompositionLayerProjectionView views[2]{{XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW},
                                          {XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW}};
  views[0].subImage = {reinterpret_cast<XrSwapchain>(&left), {{0,0},{256,256}}, 0};
  views[1].subImage = {reinterpret_cast<XrSwapchain>(&left), {{256,0},{256,256}}, 0};
  XrCompositionLayerProjection layer{XR_TYPE_COMPOSITION_LAYER_PROJECTION};
  layer.viewCount = 2; layer.views = views;
  const auto* base = reinterpret_cast<const XrCompositionLayerBaseHeader*>(&layer);
  XrFrameEndInfo info{XR_TYPE_FRAME_END_INFO}; info.layerCount = 1; info.layers = &base;
  auto submit = [&] {
    owner.frame = true;
    return endFrame(reinterpret_cast<XrSession>(&owner), &info);
  };
  requireContract(submit() == XR_SUCCESS); // One acquire/release, two distinct view rectangles.
  views[1].subImage.swapchain = reinterpret_cast<XrSwapchain>(&right);
  requireContract(submit() == XR_SUCCESS); // Independent allocations still work.
  const auto valid = views[1].subImage;
  for (const auto rect : {XrRect2Di{{-1,0},{256,256}}, {{0,-1},{256,256}},
                         {{256,0},{257,256}}, {{0,0},{0,256}}, {{0,0},{256,-1}},
                         {{INT32_MAX,0},{256,256}}, {{0,1},{256,256}}}) {
    views[1].subImage.imageRect = rect;
    requireContract(submit() != XR_SUCCESS);
  }
  views[1].subImage = valid;
  views[1].subImage.imageArrayIndex = 1; requireContract(submit() != XR_SUCCESS);
  views[1].subImage = valid;
  right.acquired = true; requireContract(submit() != XR_SUCCESS); right.acquired = false;
  right.releasedFrame = 0; requireContract(submit() != XR_SUCCESS); right.releasedFrame = 1;
  right.session = &other; requireContract(submit() != XR_SUCCESS); right.session = &owner;

  std::vector<uint8_t> full(8 * 4 * 4);
  for (size_t i = 0; i < full.size(); ++i) full[i] = uint8_t(i);
  for (const auto rect : {XrRect2Di{{0,0},{8,4}}, {{0,0},{4,4}}, {{4,0},{4,4}}, {{2,1},{3,2}}}) {
    auto pixels = full; cropProjectionPixels(pixels, 8, rect);
    requireContract(pixels.size() == size_t(rect.extent.width) * rect.extent.height * 4);
    for (int32_t y = 0; y < rect.extent.height; ++y)
      for (int32_t x = 0; x < rect.extent.width; ++x)
        for (unsigned channel = 0; channel < 4; ++channel)
          requireContract(pixels[(size_t(y)*rect.extent.width+x)*4+channel] ==
              full[(size_t(y+rect.offset.y)*8+size_t(x+rect.offset.x))*4+channel]);
  }
}
}
int main() {
  try {
    projectionContracts();
    std::cout << "Projection contract passed: packed/independent views, crop pixels, ownership and invalid bounds\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n'; return 1;
  }
}
