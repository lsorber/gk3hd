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
