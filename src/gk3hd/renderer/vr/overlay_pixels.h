#pragma once

#include <algorithm>
#include <cstdint>
#include <cstring>

#if defined(__SSE2__) || defined(_M_X64) || (defined(_M_IX86_FP) && _M_IX86_FP >= 2)
#include <emmintrin.h>
#define GK3HD_OVERLAY_SSE2 1
#endif

namespace gk3hd::vr::overlay_detail {

inline uint32_t color(uint16_t pixel) {
  const uint32_t r = pixel >> 11, g = (pixel >> 5) & 63, b = pixel & 31;
  return 0xff000000u | (((r << 3) | (r >> 2)) << 16) |
    (((g << 2) | (g >> 4)) << 8) | (b << 3) | (b >> 2);
}

inline uint32_t sourceOver(uint32_t source, uint32_t destination, uint8_t alpha) {
  // The source is opaque RGB565 expanded to BGRA8. Destination is already
  // premultiplied. Round each source-over channel once, including alpha, so
  // black fades remain real darkening and transparent pixels stay zero RGB.
  uint32_t result = 0;
  for (unsigned shift = 0; shift < 32; shift += 8) {
    const auto src = (source >> shift) & 255, dst = (destination >> shift) & 255;
    result |= ((src*alpha + dst*(255-alpha) + 127)/255) << shift;
  }
  return result;
}

inline void fadedRow(uint32_t* destination, uint8_t* coverage, const uint8_t* source,
                     size_t count, uint16_t key, bool interactive, bool keyed, uint8_t alpha) {
  for (size_t x = 0; x < count; ++x) {
    uint16_t pixel;
    std::memcpy(&pixel, source+x*2, sizeof(pixel));
    if (keyed && pixel == key) continue;
    destination[x] = sourceOver(color(pixel), destination[x], alpha);
    // Picking remains explicit producer ownership, not an alpha threshold.
    if (coverage) coverage[x] = uint8_t(interactive);
  }
}

// Called only after complete source/destination span validation. Decode eight
// RGB565 pixels at once on the x86 renderer's SSE2 baseline, with a scalar
// fallback elsewhere. Exact bit replication, not color resampling/correction.
// Key holes preserve earlier pixels AND their independently authored hit mask.
template<bool Keyed>
inline void row(uint32_t* destination, uint8_t* coverage, const uint8_t* source,
                size_t count, uint16_t key, bool interactive) {
  size_t x = 0;
#ifdef GK3HD_OVERLAY_SSE2
  const auto zero = _mm_setzero_si128(), alpha = _mm_set1_epi16(-256);
  const auto five = _mm_set1_epi16(31), six = _mm_set1_epi16(63);
  const auto keys = _mm_set1_epi16(short(key));
  const auto hits = _mm_set1_epi8(char(interactive));
  for (; count-x >= 8; x += 8) {
    const auto pixel = _mm_loadu_si128(reinterpret_cast<const __m128i*>(source+x*2));
    const auto r = _mm_srli_epi16(pixel, 11);
    const auto g = _mm_and_si128(_mm_srli_epi16(pixel, 5), six);
    const auto b = _mm_and_si128(pixel, five);
    const auto red = _mm_or_si128(_mm_slli_epi16(r, 3), _mm_srli_epi16(r, 2));
    const auto green = _mm_or_si128(_mm_slli_epi16(g, 2), _mm_srli_epi16(g, 4));
    const auto blue = _mm_or_si128(_mm_slli_epi16(b, 3), _mm_srli_epi16(b, 2));
    const auto bg = _mm_or_si128(blue, _mm_slli_epi16(green, 8));
    const auto ra = _mm_or_si128(red, alpha);
    auto low = _mm_unpacklo_epi16(bg, ra), high = _mm_unpackhi_epi16(bg, ra);
    if constexpr (Keyed) {
      const auto holes = _mm_cmpeq_epi16(pixel, keys);
      const auto lowHoles = _mm_unpacklo_epi16(holes, holes), highHoles = _mm_unpackhi_epi16(holes, holes);
      low = _mm_or_si128(_mm_andnot_si128(lowHoles, low), _mm_and_si128(lowHoles,
        _mm_loadu_si128(reinterpret_cast<const __m128i*>(destination+x))));
      high = _mm_or_si128(_mm_andnot_si128(highHoles, high), _mm_and_si128(highHoles,
        _mm_loadu_si128(reinterpret_cast<const __m128i*>(destination+x+4))));
      if (coverage) {
        const auto mask = _mm_packs_epi16(holes, zero);
        const auto prior = _mm_loadl_epi64(reinterpret_cast<const __m128i*>(coverage+x));
        const auto merged = _mm_or_si128(_mm_andnot_si128(mask, hits), _mm_and_si128(mask, prior));
        _mm_storel_epi64(reinterpret_cast<__m128i*>(coverage+x), merged);
      }
    }
    _mm_storeu_si128(reinterpret_cast<__m128i*>(destination+x), low);
    _mm_storeu_si128(reinterpret_cast<__m128i*>(destination+x+4), high);
  }
#endif
  for (; x < count; ++x) {
    uint16_t pixel;
    std::memcpy(&pixel, source+x*2, sizeof(pixel));
    if constexpr (Keyed) { if (pixel == key) continue; }
    destination[x] = color(pixel);
    if constexpr (Keyed) { if (coverage) coverage[x] = uint8_t(interactive); }
  }
  if constexpr (!Keyed) { if (coverage) std::fill(coverage, coverage+count, uint8_t(interactive)); }
}

} // namespace gk3hd::vr::overlay_detail

#ifdef GK3HD_OVERLAY_SSE2
#undef GK3HD_OVERLAY_SSE2
#endif
