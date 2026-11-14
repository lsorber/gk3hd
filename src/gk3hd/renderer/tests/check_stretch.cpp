#define NOMINMAX
#include <iostream>
#include <stdexcept>
#include <string>
#include <array>
#include <climits>
#include "private_stretch.h"

// In-memory surface double: controls errors and malformed mappings without
// driver-dependent failures. Real COM interfaces are tested by the main suite.
struct Surface {
  alignas(uint32_t) std::array<uint16_t,40*40> storage{};
  DDSURFACEDESC desc{};
  HRESULT description=DD_OK,keyResult=DD_OK,lockResult=DD_OK,unlockResult=DD_OK;
  DDCOLORKEY key{0xf81f,0xf81f};
  unsigned locks=0,unlocks=0;
  bool locked=false;
  void* mapped=nullptr;
  void* acquired=nullptr;
  LONG mapPitch=80;
  Surface() {
    desc.dwSize=sizeof(desc);desc.dwWidth=desc.dwHeight=32;
    desc.ddpfPixelFormat={sizeof(DDPIXELFORMAT),DDPF_RGB,0,16,0xf800,0x7e0,0x1f,0};
    mapped=storage.data();
  }
  HRESULT GetSurfaceDesc(DDSURFACEDESC* out) { *out=desc;return description; }
  HRESULT GetColorKey(DWORD,DDCOLORKEY* out) { *out=key;return keyResult; }
  HRESULT Lock(RECT* rect,DDSURFACEDESC* out,DWORD,HANDLE) {
    ++locks;
    if (FAILED(lockResult)) return lockResult;
    if (locked) throw std::runtime_error("double Lock");
    acquired=mapped;
    if(mapped&&rect) acquired=static_cast<char*>(mapped)+rect->top*mapPitch+
      rect->left*(desc.ddpfPixelFormat.dwRGBBitCount/8);
    locked=true;*out=desc;out->lpSurface=acquired;out->lPitch=mapPitch;return DD_OK;
  }
  HRESULT Unlock(void* pointer) {
    ++unlocks;
    if (!locked || pointer!=acquired) throw std::runtime_error("unpaired Unlock");
    locked=false;return unlockResult;
  }
};

void requireAt(bool condition,unsigned line) {
  if (!condition) throw std::runtime_error("stretch assertion at line "+std::to_string(line));
}
#define require(condition) requireAt((condition),__LINE__)
constexpr RECT src{0,0,12,17},dst{0,0,33,34};
dxvk::CPUStretchResult stretch(Surface& target,Surface& source,DWORD flags=DDBLT_WAIT) {
  return dxvk::StretchRGB565Surface(&target,&source,dst,src,flags,nullptr);
}

int main() {
  try {
    unsigned tests=0;
    // Out-of-bounds/negative/empty rectangles and unsupported flag contracts
    // must be rejected before native memory is locked or changed.
    const RECT bad[]={{-1,0,1,1},{0,0,0,1},{0,0,1,0},{5,5,4,6},
      {0,0,LONG_MAX,1},{LONG_MIN,0,LONG_MAX,1}};
    for (RECT rect:bad) {
      Surface source,target;target.desc.dwWidth=target.desc.dwHeight=40;
      auto result=dxvk::StretchRGB565Surface(&target,&source,dst,rect,DDBLT_WAIT,nullptr);
      require(!result.handled && !result.written && !source.locks && !target.locks);++tests;
    }
    for (DWORD flags:{DWORD(0),DWORD(DDBLT_WAIT|DDBLT_DDFX),DWORD(DDBLT_WAIT|DDBLT_KEYDEST),
        DWORD(DDBLT_WAIT|DDBLT_KEYSRCOVERRIDE),DWORD(DDBLT_WAIT|DDBLT_ROP)}) {
      Surface source,target;target.desc.dwWidth=target.desc.dwHeight=40;
      require(!stretch(target,source,flags).handled && !source.locks && !target.locks);++tests;
    }
    for (unsigned failure=0;failure<10;++failure) {
      Surface source,target;target.desc.dwWidth=target.desc.dwHeight=40;
      if (failure==0) source.desc.ddpfPixelFormat.dwRBitMask=0x7c00;
      if (failure==1) target.desc.ddpfPixelFormat.dwRGBBitCount=32;
      if (failure==2) source.description=DDERR_GENERIC;
      if (failure==3) target.description=DDERR_GENERIC;
      if (failure==4) source.keyResult=DDERR_NOCOLORKEY;
      if (failure==5) source.key={0xffff,0x10000};
      if (failure==6) source.key={0xff,0xfe};
      if (failure==7) target.desc.dwWidth=32;
      if (failure==8) source.desc.dwHeight=16;
      if (failure==9) source.desc.ddpfPixelFormat.dwFlags|=DDPF_ALPHAPIXELS;
      require(!stretch(target,source,DDBLT_WAIT|DDBLT_KEYSRC).handled && !source.locks && !target.locks);++tests;
    }
    for (unsigned invalid=0;invalid<6;++invalid) {
      Surface source,target;target.desc.dwWidth=target.desc.dwHeight=40;
      target.storage.fill(0x1234);const auto before=target.storage;
      if (invalid==0) target.mapped=source.storage.data()+2; // Distinct objects, overlapping bytes.
      if (invalid==1) source.mapped=nullptr;
      if (invalid==2) source.mapPitch=23;
      if (invalid==3) target.mapPitch=65;
      if (invalid==4) target.mapPitch=-80;
      if (invalid==5) source.mapped=reinterpret_cast<char*>(source.storage.data())+1;
      auto result=stretch(target,source);
      require(!result.handled && !result.written && target.storage==before &&
        source.unlocks==1 && target.unlocks==1 && !source.locked && !target.locked);++tests;
    }
    for (unsigned failure=0;failure<4;++failure) {
      Surface source,target;target.desc.dwWidth=target.desc.dwHeight=40;
      source.storage.fill(0x4567);target.storage.fill(0x1234);
      if (failure==0) source.lockResult=DDERR_SURFACEBUSY;
      if (failure==1) target.lockResult=DDERR_SURFACEBUSY;
      if (failure==2) source.unlockResult=DDERR_SURFACEBUSY;
      if (failure==3) target.unlockResult=DDERR_SURFACEBUSY;
      auto result=stretch(target,source);
      require(result.handled && result.result==DDERR_SURFACEBUSY && result.written==(failure>=2));
      require(!source.locked && !target.locked && target.storage[0]==(failure>=2?0x4567:0x1234));++tests;
    }
    Surface source,target;target.desc.dwWidth=target.desc.dwHeight=40;
    source.storage.fill(0xf81f);target.storage.fill(0x1234);
    auto result=stretch(target,source,DDBLT_WAIT|DDBLT_KEYSRC);
    require(result.handled && SUCCEEDED(result.result) && target.storage[0]==0x1234);
    // Inclusive color-key ranges, with opaque data outside the key range.
    source.key={0x2000,0x3000};source.storage.fill(0x2000);
    require(SUCCEEDED(stretch(target,source,DDBLT_WAIT|DDBLT_KEYSRC).result) && target.storage[0]==0x1234);
    source.storage.fill(0x3000);
    require(SUCCEEDED(stretch(target,source,DDBLT_WAIT|DDBLT_KEYSRC).result) && target.storage[0]==0x1234);
    source.storage.fill(0x3001);
    require(SUCCEEDED(stretch(target,source,DDBLT_WAIT|DDBLT_KEYSRC).result) && target.storage[0]==0x3001);
    // Only 33 pixels on each destination row, not its 40-pixel pitch, are owned.
    for (unsigned y=0;y<34;++y) for (unsigned x=33;x<40;++x) require(target.storage[y*40+x]==0x1234);
    // Movie samples are canonical RGB32, while the game's target is RGB565.
    // Preserve source-space color keys and row padding before quantization.
    Surface movie,screen;
    movie.desc.dwWidth=3;movie.desc.dwHeight=2;movie.mapPitch=16;
    movie.desc.ddpfPixelFormat={sizeof(DDPIXELFORMAT),DDPF_RGB,0,32,0xff0000,0xff00,0xff,0};
    auto pixels=reinterpret_cast<uint32_t*>(movie.storage.data());
    pixels[0]=0x80ff0000;pixels[1]=0x00ff00;pixels[2]=0x0000ff;pixels[3]=0xdeadbeef;
    pixels[4]=0xffffff;pixels[5]=0;pixels[6]=0xff00ff;pixels[7]=0xdeadbeef;
    screen.storage.fill(0x1234);
    auto convert=dxvk::StretchRGB565Surface(&screen,&movie,RECT{0,0,6,4},RECT{0,0,3,2},DDBLT_WAIT,nullptr);
    require(convert.handled&&convert.written&&convert.result==DD_OK);
    const uint16_t expected[2][3]={{0xf800,0x07e0,0x001f},{0xffff,0,0xf81f}};
    for(unsigned y=0;y<4;++y)for(unsigned x=0;x<40;++x)
      require(screen.storage[y*40+x]==(x<6 ? expected[y/2][x/2] : 0x1234));
    movie.key={0xff00ff,0xff00ff};screen.storage.fill(0x1234);
    convert=dxvk::StretchRGB565Surface(&screen,&movie,RECT{0,0,3,2},RECT{0,0,3,2},DDBLT_WAIT|DDBLT_KEYSRC,nullptr);
    require(convert.handled&&convert.written&&convert.result==DD_OK);
    for(unsigned y=0;y<2;++y)for(unsigned x=0;x<3;++x)
      require(screen.storage[y*40+x]==(y==1&&x==2 ? 0x1234 : expected[y][x]));
    // Conversion must not write through a partial overlap missed by 16-bit
    // source-span accounting. Both surfaces remain properly unlocked.
    movie.mapped=screen.storage.data();screen.mapped=screen.storage.data()+12;
    const auto untouched=screen.storage;
    convert=dxvk::StretchRGB565Surface(&screen,&movie,RECT{0,0,3,2},RECT{0,0,3,2},DDBLT_WAIT,nullptr);
    require(!convert.handled&&!convert.written&&screen.storage==untouched&&!movie.locked&&!screen.locked);
    // A cropped atlas glyph need not begin at the mapped surface's origin.
    // Check pixel centers independently, including color keys and untouched
    // surrounding destination pixels, for both sample formats and directions.
    const RECT crops[]={{2,1,7,6},{1,2,9,8}};
    const RECT destinations[]={{3,2,11,9},{4,3,7,6}};
    for(unsigned bytes:{2u,4u})for(unsigned route=0;route<2;route++) {
      Surface atlas,canvas;atlas.desc.dwWidth=9;atlas.desc.dwHeight=8;atlas.mapPitch=48;
      canvas.desc.dwWidth=13;canvas.desc.dwHeight=11;canvas.storage.fill(0x1234);
      if(bytes==4)atlas.desc.ddpfPixelFormat={sizeof(DDPIXELFORMAT),DDPF_RGB,0,32,0xff0000,0xff00,0xff,0};
      const auto pixel=[&](unsigned x,unsigned y) {
        if(x==4&&y==3)return bytes==2 ? 0xf81fu : 0xff00ffu;
        return bytes==2 ? 0x200u+64*y+x : ((23*x)<<16)|((29*y)<<8)|(7*(x+y));
      };
      for(unsigned y=0;y<8;y++)for(unsigned x=0;x<9;x++) {
        char* cell=static_cast<char*>(atlas.mapped)+y*atlas.mapPitch+x*bytes;
        if(bytes==2)*reinterpret_cast<uint16_t*>(cell)=uint16_t(pixel(x,y));
        else *reinterpret_cast<uint32_t*>(cell)=pixel(x,y)|0x80000000u;
      }
      const auto original=atlas.storage;atlas.key={bytes==2 ? 0xf81fu : 0xff00ffu,bytes==2 ? 0xf81fu : 0xff00ffu};
      const RECT from=crops[route],to=destinations[route];
      auto cropped=dxvk::StretchRGB565Surface(&canvas,&atlas,to,from,DDBLT_WAIT|DDBLT_KEYSRC,nullptr);
      require(cropped.handled&&cropped.written&&cropped.result==DD_OK&&atlas.storage==original);
      for(unsigned y=0;y<40;y++)for(unsigned x=0;x<40;x++) {
        uint16_t wanted=0x1234;
        if(x>=unsigned(to.left)&&x<unsigned(to.right)&&y>=unsigned(to.top)&&y<unsigned(to.bottom)) {
          unsigned sx=from.left+((2*(x-to.left)+1)*(from.right-from.left))/(2*(to.right-to.left));
          unsigned sy=from.top+((2*(y-to.top)+1)*(from.bottom-from.top))/(2*(to.bottom-to.top));
          uint32_t sample=pixel(sx,sy);
          if(sample!=atlas.key.dwColorSpaceLowValue)wanted=bytes==2 ? uint16_t(sample) :
            uint16_t(((sample>>8)&0xf800)|((sample>>5)&0x7e0)|((sample>>3)&0x1f));
        }
        if(canvas.storage[y*40+x]!=wanted)throw std::runtime_error(
          "cropped sample mismatch: bytes="+std::to_string(bytes)+" route="+std::to_string(route)+
          " at="+std::to_string(x)+","+std::to_string(y));
      }
      require(!atlas.locked&&!canvas.locked&&atlas.unlocks==1&&canvas.unlocks==1);
      ++tests;
    }
    // Exercise common fractional ratios through the copy itself, including
    // exact center ties such as 8 -> 3. An arithmetic oracle specifies the
    // expected pixels without duplicating the sampler's stepping algorithm.
    for(unsigned width=1;width<=32;width++)for(unsigned scaled=1;scaled<=40;scaled++) {
      Surface row,canvas;canvas.desc.dwWidth=canvas.desc.dwHeight=40;
      for(unsigned x=0;x<32;x++)row.storage[x]=uint16_t(0x300+x);
      canvas.storage.fill(0x1234);
      auto sampled=dxvk::StretchRGB565Surface(&canvas,&row,RECT{0,0,LONG(scaled),2},
        RECT{0,0,LONG(width),1},DDBLT_WAIT,nullptr);
      require(sampled.handled&&sampled.written&&sampled.result==DD_OK);
      for(unsigned y=0;y<2;y++)for(unsigned x=0;x<40;x++)
        require(canvas.storage[y*40+x]==(x<scaled ? 0x300+((2*x+1)*width)/(2*scaled) : 0x1234));
      ++tests;
    }
    std::cout<<"PASS: "<<tests<<" rejection/failure checks, inclusive keys, RGB32 conversion, overlap and padding\n";
  } catch (const std::exception& error) { std::cerr<<error.what()<<'\n';return 2; }
}
