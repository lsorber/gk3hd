#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#if !defined(GK3HD_STATUS_FORCE_SCALAR) && (defined(__SSE2__) || defined(_M_X64) || (defined(_M_IX86_FP) && _M_IX86_FP >= 2))
#include <emmintrin.h>
#define GK3HD_STATUS_SSE2 1
#endif
namespace gk3hd::vr::status_detail {
#ifdef GK3HD_STATUS_SSE2
inline __m128i channels(uint32_t pixel) {
  const auto zero=_mm_setzero_si128();
  return _mm_unpacklo_epi16(_mm_unpacklo_epi8(_mm_cvtsi32_si128(int(pixel)),zero),zero);
}
inline __m128i rounded(__m128d value) {
  const auto whole=_mm_cvttpd_epi32(value);
  const auto fraction=_mm_sub_pd(value,_mm_cvtepi32_pd(whole));
  const auto up=_mm_castpd_si128(_mm_cmpge_pd(fraction,_mm_set1_pd(.5)));
  return _mm_sub_epi32(whole,_mm_shuffle_epi32(up,_MM_SHUFFLE(2,0,2,0)));
}
inline __m128i filteredPair(__m128i a,__m128i b,__m128i c,__m128i d,double u,double v) {
  const auto wu=_mm_set1_pd(u),nu=_mm_set1_pd(1-u);
  const auto wv=_mm_set1_pd(v),nv=_mm_set1_pd(1-v);
  const auto top=_mm_add_pd(_mm_mul_pd(nu,_mm_cvtepi32_pd(a)),_mm_mul_pd(wu,_mm_cvtepi32_pd(b)));
  const auto bottom=_mm_add_pd(_mm_mul_pd(nu,_mm_cvtepi32_pd(c)),_mm_mul_pd(wu,_mm_cvtepi32_pd(d)));
  return rounded(_mm_add_pd(_mm_mul_pd(nv,top),_mm_mul_pd(wv,bottom)));
}
#endif
inline uint32_t sample(uint32_t a,uint32_t b,uint32_t c,uint32_t d,double u,double v) {
  // A uniform footprint interpolates to the same byte values. This also
  // covers fully keyed areas between and around the glyphs.
  if (a==b && a==c && a==d) return a;
#ifdef GK3HD_STATUS_SSE2
  const auto av=channels(a),bv=channels(b),cv=channels(c),dv=channels(d);
  const auto low=filteredPair(av,bv,cv,dv,u,v);
  const auto high=filteredPair(_mm_srli_si128(av,8),_mm_srli_si128(bv,8),_mm_srli_si128(cv,8),_mm_srli_si128(dv,8),u,v);
  const auto words=_mm_packs_epi32(_mm_unpacklo_epi64(low,high),_mm_setzero_si128());
  return uint32_t(_mm_cvtsi128_si32(_mm_packus_epi16(words,_mm_setzero_si128())));
#else
  uint32_t result=0;
  for(unsigned shift=0;shift<32;shift+=8) {
    const auto ch=[&](uint32_t p){return (p>>shift)&255;};
    result|=uint32_t(std::lround((1-v)*((1-u)*ch(a)+u*ch(b))+v*((1-u)*ch(c)+u*ch(d))))<<shift;
  }
  return result;
#endif
}
inline uint32_t over(uint32_t source,uint32_t destination) {
  if (!source) return destination;
  if (!destination) return source;
#ifdef GK3HD_STATUS_SSE2
  const auto zero=_mm_setzero_si128();
  const auto src=_mm_unpacklo_epi8(_mm_cvtsi32_si128(int(source)),zero);
  const auto dst=_mm_unpacklo_epi8(_mm_cvtsi32_si128(int(destination)),zero);
  auto n=_mm_add_epi16(_mm_mullo_epi16(dst,_mm_set1_epi16(short(255-(source>>24)))),_mm_set1_epi16(127));
  // Exact floor(n/255) for the entire possible 0..65152 range, no saturation
  // before division. The correction cannot overflow an unsigned 16-bit lane.
  n=_mm_srli_epi16(_mm_add_epi16(n,_mm_add_epi16(_mm_set1_epi16(1),_mm_srli_epi16(n,8))),8);
  return uint32_t(_mm_cvtsi128_si32(_mm_packus_epi16(_mm_add_epi16(src,n),zero)));
#else
  uint32_t result=0;const auto alpha=source>>24;
  for(unsigned shift=0;shift<32;shift+=8)
    result|=std::min(255u,((source>>shift)&255)+(((destination>>shift)&255)*(255-alpha)+127)/255)<<shift;
  return result;
#endif
}
}
#ifdef GK3HD_STATUS_SSE2
#undef GK3HD_STATUS_SSE2
#endif
