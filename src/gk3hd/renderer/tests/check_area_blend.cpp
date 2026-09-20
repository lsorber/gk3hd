// Execute the exact area filter against an independent integer reference.
#define NOMINMAX
#include <windows.h>
#include "private_area_blend.h"
#include <cassert>
#include <cstring>
#include <iostream>
#include <random>
#include <vector>

using dxvk::AreaBlend565Args;
using Export = DWORD(WINAPI*)(const AreaBlend565Args*);
static Export exported = nullptr;

static uint16_t reference(const AreaBlend565Args& a, int x, int y, uint16_t old) {
  const int left=(a.tileX+x)*a.sourceWidth, right=left+a.sourceWidth;
  const int top=(a.tileY+y)*a.sourceHeight, bottom=top+a.sourceHeight;
  uint64_t coverage=0,channels[3]={};
  for(int sy=top/a.destinationHeight;sy<(bottom+a.destinationHeight-1)/a.destinationHeight;++sy) {
    const auto color=reinterpret_cast<const uint16_t*>(reinterpret_cast<const uint8_t*>(a.source)+sy*a.sourcePitch);
    for(int sx=left/a.destinationWidth;sx<(right+a.destinationWidth-1)/a.destinationWidth;++sx) {
      uint32_t p=color[sx]; if(p==a.sourceKey)continue;
      uint32_t wx=std::min(right,(sx+1)*a.destinationWidth)-std::max(left,sx*a.destinationWidth);
      uint32_t wy=std::min(bottom,(sy+1)*a.destinationHeight)-std::max(top,sy*a.destinationHeight);
      uint32_t alpha=a.alpha[sy*a.alphaPitch+sx];
      uint64_t weight=uint64_t(wx)*wy*((alpha*a.opacity)>>8);
      coverage+=weight;channels[0]+=(p>>11)*weight;
      channels[1]+=((p>>5)&63)*weight;channels[2]+=(p&31)*weight;
    }
  }
  const uint64_t total=uint64_t(a.sourceWidth)*a.sourceHeight*65536;
  return uint16_t((((channels[0]+(old>>11)*(total-coverage))/total)<<11) |
    (((channels[1]+((old>>5)&63)*(total-coverage))/total)<<5) |
    ((channels[2]+(old&31)*(total-coverage))/total));
}

static void exercise(int sw,int sh,int dw,int dh,int x,int y,int tw,int th,uint32_t opacity,
                     uint32_t seed=20260914,uint32_t key=0xf81f,int uniform=-1) {
  const int cp=sw*2+14,ap=sw+7,dp=tw*2+10;
  std::vector<uint16_t> source(cp*sh/2,0x5a5a),dest(dp*th/2,0xa5a5);
  std::vector<uint8_t> alpha(ap*sh,0x5a);
  std::mt19937 rng(seed);
  for(int row=0;row<sh;row++)for(int col=0;col<sw;col++) {
    source[row*cp/2+col]=uint16_t(rng());alpha[row*ap+col]=uint8_t(rng());
    if(row%3==0&&col%5==0)source[row*cp/2+col]=0xf81f;
    if(row%7==0&&col%2==0)alpha[row*ap+col]=0;
    if(row%2==0&&col%7==0)alpha[row*ap+col]=255;
    if(uniform>=0){source[row*cp/2+col]=uint16_t(uniform);alpha[row*ap+col]=255;}
  }
  for(int row=0;row<th;row++)for(int col=0;col<tw;col++)dest[row*dp/2+col]=uint16_t(rng());
  auto original=dest,expected=dest,originalSource=source;auto originalAlpha=alpha;
  AreaBlend565Args a={sizeof(a),source.data(),alpha.data(),dest.data(),cp,ap,dp,
    sw,sh,dw,dh,x,y,tw,th,key,opacity};
  bool shrink=sw>dw||sh>dh;
  if(shrink)for(int row=0;row<th;row++)for(int col=0;col<tw;col++)
    expected[row*dp/2+col]=reference(a,col,row,original[row*dp/2+col]);
  assert(dxvk::AreaBlend565(a)==shrink);assert(dest==expected);
  if(exported){dest=original;assert(bool(exported(&a))==shrink);assert(dest==expected);}
  assert(source==originalSource&&alpha==originalAlpha);
  // Each invalid request must decline before any write (including padding).
  for(int fault=0;fault<13;fault++) {
    auto bad=a;dest=original;
    switch(fault) {
      case 0:bad.size--;break;case 1:bad.source=nullptr;break;
      case 2:bad.alpha=nullptr;break;case 3:bad.sourceWidth=0;break;
      case 4:bad.sourceHeight=377;break;case 5:bad.sourcePitch--;break;
      case 6:bad.alphaPitch=sw-1;break;case 7:bad.tileX=dw;break;
      case 8:bad.tileY=-1;break;case 9:bad.destinationPitch=tw*2-1;break;
      case 10:bad.opacity=65795;break;case 11:bad.destination=source.data();break;
      case 12:bad.destination=reinterpret_cast<uint16_t*>(alpha.data());break;
    }
    assert(!dxvk::AreaBlend565(bad));assert(dest==original);
    if(exported){assert(!exported(&bad));assert(dest==original);}
    assert(source==originalSource&&alpha==originalAlpha);
  }
}

int main(int argc,char** argv) {
  HMODULE module=nullptr;
  if(argc==2){module=LoadLibraryA(argv[1]);assert(module);exported=reinterpret_cast<Export>(GetProcAddress(module,"Gk3hdAreaBlend565"));assert(exported);assert(!exported(nullptr));}
  static_assert(sizeof(void*)!=4 || sizeof(AreaBlend565Args)==68,"x86 export ABI drift");
  int cases=0;
  for(uint32_t alpha:{0u,1u,32768u,65535u,65536u,65794u}) {
    exercise(8,8,2,2,0,0,2,2,alpha);
    exercise(376,376,94,94,83,86,11,8,alpha);
    exercise(376,376,265,265,128,128,13,9,alpha);
    exercise(94,94,265,265,128,128,4,3,alpha);
    exercise(376,376,470,470,256,256,4,3,alpha);
    exercise(376,5,100,10,50,2,3,5,alpha);cases+=6;
  }
  exercise(376,376,1,1,0,0,1,1,65794);cases++;
  // Full opaque sums reach the channel bounds; disabled keys must not remove
  // genuine black/magenta pixels. Wide tiles exercise the bounded-cache fallback.
  for(int color:{0,0xffff,0xf81f}) {
    exercise(376,376,1,1,0,0,1,1,65794,7,0xffffffff,color);cases++;
    exercise(376,8,32768,3,0,1,1024,1,65794,7,0xffffffff,color);cases++;
  }
  std::mt19937 dimensions(20260915);
  for(int i=0;i<400;i++) {
    int sw=1+dimensions()%376,sh=1+dimensions()%376;
    int dw=1+dimensions()%500,dh=1+dimensions()%500;
    int x=dimensions()%dw,y=dimensions()%dh;
    int tw=std::min(dw-x,1+int(dimensions()%9));
    int th=std::min(dh-y,1+int(dimensions()%9));
    exercise(sw,sh,dw,dh,x,y,tw,th,dimensions()%65795,dimensions(),
      i%2 ? 0xffffffff : 0xf81f);cases++;
  }
  // Exhaust channel boundaries over integer/noninteger area denominators.
  for(uint64_t area:{1ull,16ull,2209ull,141376ull})for(uint64_t q=0;q<=63;q++) {
    const uint64_t d=area<<16;const double inverse=1.0/d;
    for(uint64_t remainder:{0ull,1ull,d/2,d-1}) {
      uint64_t value=q*d+remainder;if(value>63*d)continue;
      assert(dxvk::AreaBlendChannel(value,d,inverse)==value/d);
    }
  }
  std::cout<<cases<<" area-blend reference cases, "<<cases*13<<" refusal cases and exact quotient boundaries passed\n";
  if(module){std::cout<<"Actual x86 DLL export passed the same tests\n";FreeLibrary(module);}
}
