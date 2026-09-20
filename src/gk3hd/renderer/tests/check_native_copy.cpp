#define NOMINMAX
#include <windows.h>
#include <ddraw.h>
#include <chrono>
#include <iostream>
#include <stdexcept>
#include <cstring>
#include <vector>
#include "private_native_copy.h"

void check(HRESULT result) { if (FAILED(result)) throw std::runtime_error("native operation failed"); }

void testSharedAndPaddedStorage(IDirectDraw* dd) {
  constexpr DWORD width=36,height=41,pitch=80;
  std::vector<uint8_t> input(pitch*height+16,0x39),output(pitch*height,0xcd);
  auto create=[&](void* storage) {
    DDSURFACEDESC desc{};
    desc.dwSize=sizeof(desc);
    desc.dwFlags=DDSD_WIDTH|DDSD_HEIGHT|DDSD_CAPS|DDSD_PIXELFORMAT;
    desc.dwWidth=width; desc.dwHeight=height;
    desc.ddsCaps.dwCaps=DDSCAPS_SYSTEMMEMORY|DDSCAPS_OFFSCREENPLAIN;
    desc.ddpfPixelFormat={sizeof(DDPIXELFORMAT),DDPF_RGB,0,16,0xf800,0x7e0,0x1f,0};
    IDirectDrawSurface* surface=nullptr;
    check(dd->CreateSurface(&desc,&surface,nullptr));
    IDirectDrawSurface4* view=nullptr;
    check(surface->QueryInterface(IID_IDirectDrawSurface4,reinterpret_cast<void**>(&view)));
    DDSURFACEDESC2 provided{};
    provided.dwSize=sizeof(provided);
    provided.dwFlags=DDSD_LPSURFACE|DDSD_PITCH|DDSD_WIDTH|DDSD_HEIGHT;
    provided.dwWidth=width; provided.dwHeight=height;
    provided.lPitch=pitch; provided.lpSurface=storage;
    check(view->SetSurfaceDesc(&provided,0));
    view->Release();
    return surface;
  };
  auto source=create(input.data());
  auto overlap=create(input.data()+4);
  auto target=create(output.data());
  const auto untouched=input;
  HRESULT result;
  if (dxvk::CopyLargeRGB565Surface(overlap,source,result)) throw std::runtime_error("overlapping storage accepted");
  if (input!=untouched) throw std::runtime_error("overlap rejection modified pixels");
  if (!dxvk::CopyLargeRGB565Surface(target,source,result)) throw std::runtime_error("padded copy rejected");
  check(result);
  for (DWORD y=0;y<height;++y) for (DWORD x=0;x<pitch;++x)
    if (output[y*pitch+x]!=(x<width*2 ? 0x39 : 0xcd)) throw std::runtime_error("padded copy altered padding or pixels");
  if (!dxvk::FillLargeRGB565Surface(target,0,result)) throw std::runtime_error("padded clear rejected");
  check(result);
  for (DWORD y=0;y<height;++y) for (DWORD x=0;x<pitch;++x)
    if (output[y*pitch+x]!=(x<width*2 ? 0 : 0xcd)) throw std::runtime_error("padded clear altered padding or pixels");
  target->Release(); overlap->Release(); source->Release();
  std::cout << "PASS: distinct COM objects with overlapping storage rejected; padded rows copied/cleared without touching padding\n";
}

int main() {
  constexpr int width=3840,height=2160;
  IDirectDraw* dd=nullptr;
  check(DirectDrawCreate(nullptr,&dd,nullptr));
  check(dd->SetCooperativeLevel(nullptr,DDSCL_NORMAL));
  testSharedAndPaddedStorage(dd);
  DDSURFACEDESC desc{};
  desc.dwSize=sizeof(desc);
  desc.dwFlags=DDSD_WIDTH|DDSD_HEIGHT|DDSD_CAPS|DDSD_PIXELFORMAT;
  desc.dwWidth=width; desc.dwHeight=height;
  desc.ddsCaps.dwCaps=DDSCAPS_SYSTEMMEMORY|DDSCAPS_OFFSCREENPLAIN;
  desc.ddpfPixelFormat={sizeof(DDPIXELFORMAT),DDPF_RGB,0,16,0xf800,0x7e0,0x1f,0};
  IDirectDrawSurface *source=nullptr,*target=nullptr;
  check(dd->CreateSurface(&desc,&source,nullptr));
  check(dd->CreateSurface(&desc,&target,nullptr));
  DDBLTFX fx{}; fx.dwSize=sizeof(fx); fx.dwFillColor=0x1234;
  check(source->Blt(nullptr,nullptr,nullptr,DDBLT_COLORFILL|DDBLT_WAIT,&fx));
  fx.dwFillColor=0;
  auto nativeCopy=[&] {check(target->Blt(nullptr,source,nullptr,DDBLT_WAIT|DDBLT_ASYNC,nullptr));};
  auto nativeClear=[&] {check(target->Blt(nullptr,nullptr,nullptr,DDBLT_COLORFILL|DDBLT_WAIT,&fx));};
  auto copy=[&] {
    DDSURFACEDESC in{},out{}; in.dwSize=out.dwSize=sizeof(desc);
    check(source->Lock(nullptr,&in,DDLOCK_READONLY|DDLOCK_WAIT,nullptr));
    check(target->Lock(nullptr,&out,DDLOCK_WRITEONLY|DDLOCK_WAIT,nullptr));
    for (int y=0;y<height;++y)
      memcpy(static_cast<char*>(out.lpSurface)+y*out.lPitch,static_cast<char*>(in.lpSurface)+y*in.lPitch,width*2);
    check(target->Unlock(nullptr)); check(source->Unlock(nullptr));
  };
  auto clear=[&] {
    DDSURFACEDESC out{}; out.dwSize=sizeof(desc);
    check(target->Lock(nullptr,&out,DDLOCK_WRITEONLY|DDLOCK_WAIT,nullptr));
    for (int y=0;y<height;++y) memset(static_cast<char*>(out.lpSurface)+y*out.lPitch,0,width*2);
    check(target->Unlock(nullptr));
  };
  auto checkedCopy=[&] {
    HRESULT result;
    if (!dxvk::CopyLargeRGB565Surface(target,source,result)) throw std::runtime_error("copy was not eligible");
    check(result);
  };
  // Check the retained implementation, not only a separately written benchmark.
  DDSURFACEDESC pixels{}; pixels.dwSize=sizeof(pixels);
  check(source->Lock(nullptr,&pixels,DDLOCK_WRITEONLY|DDLOCK_WAIT,nullptr));
  for (int y=0;y<height;++y) {
    auto row=reinterpret_cast<uint16_t*>(static_cast<char*>(pixels.lpSurface)+y*pixels.lPitch);
    for (int x=0;x<width;++x) row[x]=uint16_t((x*17)^(y*19));
  }
  check(source->Unlock(nullptr));
  auto capture=[&] {
    DDSURFACEDESC pixels{}; pixels.dwSize=sizeof(pixels);
    check(target->Lock(nullptr,&pixels,DDLOCK_READONLY|DDLOCK_WAIT,nullptr));
    std::vector<uint16_t> result(width*height);
    for (int y=0;y<height;++y) memcpy(result.data()+y*width,static_cast<char*>(pixels.lpSurface)+y*pixels.lPitch,width*2);
    check(target->Unlock(nullptr));
    return result;
  };
  nativeCopy(); const auto expected=capture(); clear(); checkedCopy();
  if (capture()!=expected) throw std::runtime_error("copy differs from native RGB565 pixels");
  IDirectDrawSurface* mismatch=nullptr;
  desc.dwWidth=width-1;
  check(dd->CreateSurface(&desc,&mismatch,nullptr));
  HRESULT result;
  if (dxvk::CopyLargeRGB565Surface(target,mismatch,result)) throw std::runtime_error("different sizes accepted");
  mismatch->Release();
  desc.dwWidth=width;
  desc.ddpfPixelFormat.dwRBitMask=0x7c00; desc.ddpfPixelFormat.dwGBitMask=0x3e0;
  check(dd->CreateSurface(&desc,&mismatch,nullptr));
  if (dxvk::CopyLargeRGB565Surface(target,mismatch,result)) throw std::runtime_error("different formats accepted");
  mismatch->Release();
  if (capture()!=expected) throw std::runtime_error("rejected copy changed destination");
  if (!dxvk::FillLargeRGB565Surface(target,0,result)) throw std::runtime_error("clear rejected");
  check(result);
  if (capture()!=std::vector<uint16_t>(width*height,0)) throw std::runtime_error("zero fill differs from native");
  auto checkedClear=[&] {
    HRESULT result;
    if (!dxvk::FillLargeRGB565Surface(target,0,result)) throw std::runtime_error("clear rejected");
    check(result);
  };
  auto checkedColorFill=[&] {
    HRESULT result;
    if (!dxvk::FillLargeRGB565Surface(target,0x0822,result)) throw std::runtime_error("color fill rejected");
    check(result);
  };
  checkedColorFill();
  if (capture()!=std::vector<uint16_t>(width*height,0x0822)) throw std::runtime_error("color fill differs from expected pixels");
  std::cout << "PASS: 8,294,400 exact pixels; dimension/format rejection leaves destination unchanged\n";
  target->Release(); source->Release(); dd->Release();
}
