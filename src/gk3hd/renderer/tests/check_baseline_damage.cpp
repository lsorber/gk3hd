#define NOMINMAX
#include "private_regions.h"
#include <array>
#include <random>
#include <iostream>
#include <stdexcept>

int main() {
  constexpr LONG width=64,height=257;
  const RECT whole{0,0,width,height};
  using Pixels=std::array<uint32_t,width*height>;
  Pixels cpu{},gpu{},background[2]{};
  uint64_t versions[2]={1,1};
  std::mt19937 random(20260906);
  dxvk::BaselineDamage tracking;
  std::vector<RECT> dirty;
  unsigned uploads=0;
  auto fill = [&](Pixels& pixels,RECT rect,uint32_t color) {
    for (LONG y=rect.top;y<rect.bottom;++y)
      for (LONG x=rect.left;x<rect.right;++x) pixels[y*width+x]=color;
  };
  auto upload = [&] {
    for (const RECT& rect : dirty)
      for (LONG y=rect.top;y<rect.bottom;++y)
        for (LONG x=rect.left;x<rect.right;++x) gpu[y*width+x]=cpu[y*width+x];
    if (!dirty.empty()) tracking.uploaded();
    dirty.clear();
    if (gpu!=cpu) throw std::runtime_error("GPU differs after tracked upload");
    ++uploads;
  };
  for (unsigned operation=0;operation<100000;++operation) {
    LONG x0=random()%width,x1=random()%width,y0=random()%height,y1=random()%height;
    RECT rect{std::min(x0,x1),std::min(y0,y1),std::max(x0,x1)+1,std::max(y0,y1)+1};
    unsigned source=random()%2;
    switch (random()%7) {
      case 0: // Normal CPU write, including a full clear before a later copy.
      case 1:
        if (operation%7==0) rect=whole;
        fill(cpu,rect,random());
        tracking.write(rect,height);
        dxvk::AddRegion(dirty,rect);
        break;
      case 2:
      case 3: // Repeated full copies can cancel pending CPU clears and edits.
        cpu=background[source];
        dirty=tracking.copy(source+1,versions[source],whole);
        break;
      case 4: // A source changes without changing its surface identity.
        fill(background[source],rect,random());
        ++versions[source];
        break;
      case 5: upload(); break;
      case 6: // GPU drawing invalidates any stable CPU-copy baseline.
        upload();
        fill(gpu,rect,random());
        cpu=gpu; // Model the subsequent readback before another CPU edit.
        tracking.invalidate();
        break;
    }
  }
  upload();
  std::cout << "PASS: 100,000 operations, " << uploads << " exact pixel uploads; CPU clear/copy cancellation, source versions/identities and GPU invalidation\n";
}
