#pragma once

#include "panel_bridge.h"
#include "overlay_pixels.h"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <vector>

namespace gk3hd::vr {

// Explicit isolated CPU-authored RGB565 content. The source key is supplied
// by its producer, never inferred from black, magenta or a desktop difference.
// Source coordinates remain in the original complete interface canvas.
struct CaptionPanelFrame {
  PanelFrame panel{};
  uint32_t surface = 0, key = 0;
  int32_t left = 0, top = 0, right = 0, bottom = 0;
};
static_assert(sizeof(CaptionPanelFrame) == 212, "caption bridge uses a fixed x86 ABI");

constexpr uint32_t OverlayKeyed = 1u;
constexpr uint32_t OverlayInteractive = 2u;
// A label follows menu placement without becoming a controller target.
constexpr uint32_t OverlayMenuCompanion = 4u;
// Dialogue has its own readable physical scale, never a menu hit target.
constexpr uint32_t OverlaySubtitle = 8u;
constexpr uint32_t MaxOverlayParts = 16;
// Sources are isolated CPU-authored surfaces, not pieces of the desktop page.
// A local source rectangle is placed 1:1 at (x, y) in physical canvas pixels.
// Keyed holes retain earlier parts. Black is content, never inferred alpha.
// The producer supplies opacity before blending against any desktop page.
struct OverlayPart {
  uint32_t surface = 0, flags = 0, key = 0;
  int32_t left = 0, top = 0, right = 0, bottom = 0, x = 0, y = 0;
  float opacity = 1.f;
};
struct OverlayPanelFrame {
  PanelFrame panel{};
  uint32_t count = 0;
  OverlayPart parts[MaxOverlayParts]{};
};
static_assert(sizeof(OverlayPart) == 40 && sizeof(OverlayPanelFrame) == 832,
              "composed overlay bridge uses a fixed x86 ABI");

struct OverlayRegion {
  uint32_t left = 0, top = 0, right = 0, bottom = 0;
  bool empty() const { return left == right || top == bottom; }
  uint32_t width() const { return right-left; }
  uint32_t height() const { return bottom-top; }
};

struct OverlayImage {
  uint32_t width = 0, height = 0;
  // Little-endian BGRA bytes, premultiplied, including producer-owned fades.
  std::vector<uint32_t> pixels;
  // Explicit producer-owned picking, independent of visual alpha. Labels
  // never become controls simply because their glyph/chrome pixels are opaque.
  // Display-only batches keep this empty rather than allocate another canvas.
  std::vector<uint8_t> coverage;
  // Clipped union of authored parts, not a scan/inference from pixel colors.
  // Canvas coordinates and picking retain the complete original dimensions.
  OverlayRegion bounds;
  OverlayRegion interactiveBounds;

  bool hit(float x, float y) const {
    if (!std::isfinite(x) || !std::isfinite(y) || x < 0 || y < 0 ||
        x >= float(width) || y >= float(height) || uint64_t(width)*height != pixels.size() ||
        coverage.size() != pixels.size() ||
        coverage.empty()) return false;
    return coverage[size_t(y)*width+size_t(x)] != 0;
  }
};

inline OverlayImage overlayCanvas(uint32_t width, uint32_t height) {
  if (!width || !height || width > 16384 || height > 16384 ||
      uint64_t(width)*height > 16u*1024*1024)
    throw std::invalid_argument("invalid isolated overlay canvas");
  return {width, height, std::vector<uint32_t>(size_t(width)*height), {}};
}

inline void compositeOverlay(OverlayImage& image, const OverlayPart& part, const void* source,
                             int32_t pitch, uint32_t width, uint32_t height) {
  // Bound the x86 allocation to 64 MiB and prove all source row arithmetic
  // before allocating or reading. Caller owns a locked system-memory surface.
  if (!source || !image.width || !image.height ||
      uint64_t(image.width)*image.height != image.pixels.size() ||
      (!image.coverage.empty() && image.coverage.size() != image.pixels.size()) ||
      !width || !height || width > 16384 || height > 16384 ||
      uint64_t(width)*height > 16u*1024*1024 || pitch <= 0 ||
      uint64_t(pitch) < uint64_t(width)*2 || (part.flags & ~(OverlayKeyed | OverlayInteractive | OverlayMenuCompanion | OverlaySubtitle)) ||
      ((part.flags & OverlaySubtitle) && (part.flags & (OverlayInteractive | OverlayMenuCompanion))) ||
      !std::isfinite(part.opacity) || part.opacity < 0.f || part.opacity > 1.f ||
      ((part.flags & OverlayKeyed) ? part.key > UINT16_MAX : part.key != 0) ||
      part.left < 0 || part.top < 0 || part.right <= part.left ||
      part.bottom <= part.top || uint32_t(part.right) > width ||
      uint32_t(part.bottom) > height)
    throw std::invalid_argument("invalid isolated overlay source");
  const uint64_t span = uint64_t(height-1)*uint32_t(pitch) + uint64_t(width)*2;
  if (span > SIZE_MAX || uintptr_t(source) > UINTPTR_MAX - span)
    throw std::invalid_argument("overlay source span overflows");
  // Quantize only at the final BGRA8 transport boundary. An invisible part
  // neither occludes existing content nor takes an underlying control's hit.
  const auto alpha = uint8_t(std::lround(double(part.opacity)*255));
  if (!alpha) return;
  // Intersect in 64-bit arithmetic, including wholly off-screen producers.
  // Clipping changes neither the local source origin nor texture scale.
  const int64_t left = std::max<int64_t>(part.x, 0), top = std::max<int64_t>(part.y, 0);
  const int64_t right = std::min<int64_t>(int64_t(part.x)+part.right-part.left, image.width);
  const int64_t bottom = std::min<int64_t>(int64_t(part.y)+part.bottom-part.top, image.height);
  if (left >= right || top >= bottom) return;
  if (left < right && top < bottom && (part.flags & OverlayInteractive) && image.coverage.empty())
    image.coverage.resize(image.pixels.size());
  if (left < right && top < bottom) {
    const OverlayRegion added{uint32_t(left), uint32_t(top), uint32_t(right), uint32_t(bottom)};
    if (image.bounds.empty()) image.bounds = added;
    else {
      image.bounds.left = std::min(image.bounds.left, added.left);
      image.bounds.top = std::min(image.bounds.top, added.top);
      image.bounds.right = std::max(image.bounds.right, added.right);
      image.bounds.bottom = std::max(image.bounds.bottom, added.bottom);
    }
    if (part.flags & OverlayInteractive) {
      auto& controls = image.interactiveBounds;
      if (controls.empty()) controls = added;
      else {
        controls.left = std::min(controls.left, added.left);
        controls.top = std::min(controls.top, added.top);
        controls.right = std::max(controls.right, added.right);
        controls.bottom = std::max(controls.bottom, added.bottom);
      }
    }
  }
  for (int64_t y = top; y < bottom; ++y) {
    const auto* row = static_cast<const uint8_t*>(source) +
      size_t(y-part.y+part.top)*uint32_t(pitch) + size_t(left-part.x+part.left)*2;
    const size_t offset = size_t(y)*image.width+size_t(left);
    auto* pixels = image.pixels.data()+offset;
    auto* coverage = image.coverage.empty() ? nullptr : image.coverage.data()+offset;
    const bool interactive = (part.flags & OverlayInteractive) != 0;
    if (alpha != 255)
      overlay_detail::fadedRow(pixels, coverage, row, size_t(right-left), uint16_t(part.key),
                              interactive, (part.flags & OverlayKeyed) != 0, alpha);
    else if (part.flags & OverlayKeyed)
      overlay_detail::row<true>(pixels, coverage, row, size_t(right-left), uint16_t(part.key), interactive);
    else overlay_detail::row<false>(pixels, coverage, row, size_t(right-left), 0, interactive);
  }
}

inline OverlayImage keyedOverlay(const CaptionPanelFrame& request, const void* source,
                                 int32_t pitch, uint32_t width, uint32_t height) {
  if (request.panel.canvasWidth != width || request.panel.canvasHeight != height)
    throw std::invalid_argument("caption source must match the complete canvas");
  auto image = overlayCanvas(width, height);
  const OverlayPart part{request.surface, OverlayKeyed, request.key, request.left, request.top,
    request.right, request.bottom, request.left, request.top};
  compositeOverlay(image, part, source, pitch, width, height);
  return image;
}

inline OverlayRegion overlayUploadRegion(const OverlayImage& image) {
  const auto& bounds = image.bounds;
  if (!image.width || !image.height || uint64_t(image.width)*image.height != image.pixels.size() ||
      bounds.left > bounds.right || bounds.top > bounds.bottom ||
      bounds.right > image.width || bounds.bottom > image.height)
    throw std::invalid_argument("invalid overlay upload footprint");
  // An entirely clipped batch still submits an explicitly transparent panel.
  // Never pass an empty rect to a blitter that interprets it as full-image.
  return bounds.empty() ? OverlayRegion{0, 0, 1, 1} : bounds;
}

inline uint32_t overlayTextureExtent(uint32_t needed, uint32_t canvas) {
  if (!needed || needed > canvas || canvas > 16384)
    throw std::invalid_argument("invalid overlay upload capacity");
  uint32_t extent = 1;
  while (extent < needed) extent *= 2;
  return std::min(extent, canvas);
}

// One buffer per legacy device, used under that device's existing bridge lock.
// Keep allocations across frames without retaining old visible pixels or hits.
// This is CPU-authored content, never a cache of a desktop/video-memory page.
class OverlayBuffer {
public:
  void begin(uint32_t width, uint32_t height) {
    if (width != image_.width || height != image_.height || image_.pixels.empty()) {
      // Validate and allocate before replacing the old state. An invalid or
      // failed resize must not leave a partially initialized canvas.
      image_ = overlayCanvas(width, height);
    } else {
      const auto prior = image_.bounds;
      for (uint32_t y = prior.top; y < prior.bottom; ++y) {
        const size_t start = size_t(y)*width + prior.left, end = size_t(y)*width + prior.right;
        std::fill(image_.pixels.begin()+start, image_.pixels.begin()+end, 0);
        if (!image_.coverage.empty())
          std::fill(image_.coverage.begin()+start, image_.coverage.begin()+end, uint8_t(0));
      }
    }
    image_.bounds = {};
    image_.interactiveBounds = {};
  }

  void composite(const OverlayPart& part, const void* source, int32_t pitch,
                 uint32_t width, uint32_t height) {
    compositeOverlay(image_, part, source, pitch, width, height);
  }

  void blackBackdrop() {
    // Explicit subtitle rectangle, not color-inferred alpha or a page readback.
    // Premultiplied glyph colors keep their native blend against black.
    const auto bounds=image_.bounds;
    for(uint32_t y=bounds.top;y<bounds.bottom;++y)
      for(uint32_t x=bounds.left;x<bounds.right;++x)
        image_.pixels[size_t(y)*image_.width+x] |= 0xff000000u;
  }

  const OverlayImage& image() const { return image_; }

private:
  OverlayImage image_;
};

// Menu-linked content can be enlarged independently of captions/status text.
// Keep native part order within each plane. Allocate the display-only buffer
// lazily; absent/retired producers must not submit yesterday's auxiliary quad.
class OverlayLayers {
public:
  void begin(uint32_t width, uint32_t height, bool menu) {
    primary_.begin(width, height);
    width_ = width; height_ = height; menu_ = menu; displayStarted_ = subtitleStarted_ = false;
  }
  void composite(const OverlayPart& part, const void* source, int32_t pitch,
                 uint32_t width, uint32_t height) {
    if (part.flags & OverlaySubtitle) {
      if (!subtitleStarted_) {
        subtitle_.begin(width_, height_);
        subtitleStarted_ = true;
      }
      subtitle_.composite(part, source, pitch, width, height);
    } else if (!menu_ || (part.flags & (OverlayInteractive | OverlayMenuCompanion)))
      primary_.composite(part, source, pitch, width, height);
    else {
      if (!displayStarted_) {
        display_.begin(width_, height_);
        displayStarted_ = true;
      }
      display_.composite(part, source, pitch, width, height);
    }
  }
  const OverlayImage& image() const { return primary_.image(); }
  void subtitleBackdrop() { if(subtitleStarted_) subtitle_.blackBackdrop(); }
  const OverlayImage* displayImage() const {
    return displayStarted_ && !display_.image().bounds.empty() ? &display_.image() : nullptr;
  }
  const OverlayImage* subtitleImage() const {
    return subtitleStarted_ && !subtitle_.image().bounds.empty() ? &subtitle_.image() : nullptr;
  }
private:
  OverlayBuffer primary_, display_, subtitle_;
  uint32_t width_ = 0, height_ = 0;
  bool menu_ = false, displayStarted_ = false, subtitleStarted_ = false;
};

} // namespace gk3hd::vr
