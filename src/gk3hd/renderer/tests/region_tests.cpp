#define NOMINMAX
#include "private_regions.h"
#include <array>
#include <random>
#include <stdexcept>
#include <iostream>

std::array<int,1024> raster(const std::vector<RECT>& regions) {
  std::array<int,1024> result{};
  for (auto r : regions)
    for (LONG y=r.top;y<r.bottom;++y)
      for (LONG x=r.left;x<r.right;++x) ++result[y*32+x];
  return result;
}
int main() {
  const RECT canvas{0,0,3840,2160}, sourceWhole{0,0,64,64}, crop{2,3,61,62};
  const RECT expectedFast{1912,1736,1971,1795};
  auto fast = dxvk::FastBltRegion(1912,1736,&crop,&sourceWhole,&canvas);
  if (!fast || !EqualRect(&*fast,&expectedFast))
    throw std::runtime_error("fast blit crop is not translated exactly");
  const RECT lastPixel{63,63,64,64}, empty{3,3,3,4}, negative{-1,0,2,2}, large{0,0,65,64};
  fast=dxvk::FastBltRegion(3839,2159,&lastPixel,&sourceWhole,&canvas);
  const RECT expectedEdge{3839,2159,3840,2160};
  if (!fast || !EqualRect(&*fast,&expectedEdge))
    throw std::runtime_error("fast blit at last pixel lost its extent");
  for (auto invalid : {&empty,&negative,&large})
    if (dxvk::FastBltRegion(0,0,invalid,&sourceWhole,&canvas))
      throw std::runtime_error("invalid source accepted as bounded fast blit");
  for (DWORD x : {DWORD(3840),DWORD(0x7fffffff),DWORD(0xffffffff)})
    if (dxvk::FastBltRegion(x,0,&lastPixel,&sourceWhole,&canvas))
      throw std::runtime_error("out-of-bounds/overflowing fast blit accepted");
  if (dxvk::FastBltRegion(0,2160,&lastPixel,&sourceWhole,&canvas) ||
      dxvk::FastBltRegion(0,0,nullptr,&sourceWhole,&canvas) ||
      dxvk::FastBltRegion(0,0,&crop,nullptr,&canvas) ||
      dxvk::FastBltRegion(0,0,&crop,&sourceWhole,nullptr))
    throw std::runtime_error("unknown fast blit extent accepted");
  std::mt19937 random(20260906);
  for (unsigned trial=0;trial<1000;++trial) {
    std::vector<RECT> unioned;
    std::array<int,1024> expected{};
    for (unsigned operation=0;operation<20;++operation) {
      LONG x0=random()%33,x1=random()%33,y0=random()%33,y1=random()%33;
      RECT next{std::min(x0,x1),std::min(y0,y1),std::max(x0,x1),std::max(y0,y1)};
      dxvk::AddRegion(unioned,next);
      for (LONG y=next.top;y<next.bottom;++y)
        for (LONG x=next.left;x<next.right;++x) expected[y*32+x]=1;
      if (raster(unioned)!=expected) throw std::runtime_error("union coverage or overlap");
      auto missing=raster(dxvk::SubtractRegions({RECT{0,0,32,32}},unioned));
      for (unsigned i=0;i<1024;++i)
        if (missing[i]!=1-expected[i]) throw std::runtime_error("subtraction coverage or overlap");
    }
  }
  for (unsigned trial=0;trial<10000;++trial) {
    std::vector<RECT> dirty, valid;
    for (unsigned i=0;i<10;++i) {
      LONG x0=random()%33,x1=random()%33,y0=random()%33,y1=random()%33;
      RECT next{std::min(x0,x1),std::min(y0,y1),std::max(x0,x1),std::max(y0,y1)};
      dxvk::AddRegion(valid,next);
      if (i%2) dxvk::AddRegion(dirty,next);
    }
    auto before=raster(dirty), readable=raster(valid);
    dxvk::CoalesceCovered(dirty,valid);
    auto after=raster(dirty);
    for (unsigned i=0;i<1024;++i)
      if (after[i]>1 || (before[i] && !after[i]) || (after[i] && !readable[i]))
        throw std::runtime_error("coalescing loses edits or copies stale pixels");
  }
  std::vector<RECT> distant{{0,0,2,2},{30,30,32,32}};
  dxvk::CoalesceCovered(distant,distant);
  if (distant.size()!=2) throw std::runtime_error("unknown gap merged");
  dxvk::CoalesceCovered(distant,{RECT{0,0,32,32}});
  if (distant.size()!=2) throw std::runtime_error("excessive known gap merged");
  std::vector<RECT> nearby{{0,0,10,10},{12,0,22,10}};
  dxvk::CoalesceCovered(nearby,{RECT{0,0,32,32}});
  RECT merged{0,0,22,10};
  if (nearby.size()!=1 || !EqualRect(&nearby[0],&merged))
    throw std::runtime_error("small known gap not merged");
  std::cout << "PASS: 20,000 rectangle unions/subtractions, exact coverage and no overlapping output\n";
  std::cout << "PASS: 10,000 safe coalescing cases plus explicit known/unknown gap cases\n";
}
