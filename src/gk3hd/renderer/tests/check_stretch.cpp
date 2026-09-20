#define NOMINMAX
#include <iostream>
#include <stdexcept>
#include <array>
#include <climits>
#include "private_stretch.h"

// In-memory surface double: controls errors and malformed mappings without
// driver-dependent failures. Real COM interfaces are tested by the main suite.
struct Surface {
  std::array<uint16_t,40*40> storage{};
  DDSURFACEDESC desc{};
  HRESULT description=DD_OK,keyResult=DD_OK,lockResult=DD_OK,unlockResult=DD_OK;
  DDCOLORKEY key{0xf81f,0xf81f};
  unsigned locks=0,unlocks=0;
  bool locked=false;
  void* mapped=nullptr;
  LONG mapPitch=80;
  Surface() {
    desc.dwSize=sizeof(desc);desc.dwWidth=desc.dwHeight=32;
    desc.ddpfPixelFormat={sizeof(DDPIXELFORMAT),DDPF_RGB,0,16,0xf800,0x7e0,0x1f,0};
    mapped=storage.data();
  }
  HRESULT GetSurfaceDesc(DDSURFACEDESC* out) { *out=desc;return description; }
  HRESULT GetColorKey(DWORD,DDCOLORKEY* out) { *out=key;return keyResult; }
  HRESULT Lock(RECT*,DDSURFACEDESC* out,DWORD,HANDLE) {
    ++locks;
    if (FAILED(lockResult)) return lockResult;
    if (locked) throw std::runtime_error("double Lock");
    locked=true;*out=desc;out->lpSurface=mapped;out->lPitch=mapPitch;return DD_OK;
  }
  HRESULT Unlock(void* pointer) {
    ++unlocks;
    if (!locked || pointer!=mapped) throw std::runtime_error("unpaired Unlock");
    locked=false;return unlockResult;
  }
};

void require(bool condition) { if (!condition) throw std::runtime_error("stretch assertion"); }
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
    std::cout<<"PASS: "<<tests<<" rejection/failure checks, inclusive keys, and untouched padding\n";
  } catch (const std::exception& error) { std::cerr<<error.what()<<'\n';return 2; }
}
