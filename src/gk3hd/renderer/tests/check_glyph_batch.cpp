#define NOMINMAX
#include <windows.h>
#include <ddraw.h>
#include <wrl/client.h>

#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>

using Microsoft::WRL::ComPtr;

namespace {
constexpr unsigned extent=64;
constexpr uint16_t key=0xf81f, background=1;
constexpr DWORD blitFlags=DDBLT_WAIT|DDBLT_ASYNC|DDBLT_KEYSRC;
using Batch=HRESULT(WINAPI*)(IDirectDrawSurface*,uint32_t,const uint32_t*);
using Reuse=HRESULT(WINAPI*)(IDirectDrawSurface*,IDirectDrawSurface*,const uint32_t*,
                             uint32_t,uint32_t,uint32_t,uint32_t);

void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}
void check(HRESULT result) { require(SUCCEEDED(result),"DirectDraw operation failed"); }

ComPtr<IDirectDrawSurface> makeSurface(IDirectDraw& draw) {
  DDSURFACEDESC desc{};
  desc.dwSize=sizeof(desc);
  desc.dwFlags=DDSD_WIDTH|DDSD_HEIGHT|DDSD_CAPS|DDSD_PIXELFORMAT;
  desc.dwWidth=desc.dwHeight=extent;
  desc.ddsCaps.dwCaps=DDSCAPS_OFFSCREENPLAIN|DDSCAPS_SYSTEMMEMORY;
  desc.ddpfPixelFormat={sizeof(DDPIXELFORMAT),DDPF_RGB,0,16,0xf800,0x7e0,0x1f,0};
  ComPtr<IDirectDrawSurface> result;
  check(draw.CreateSurface(&desc,result.GetAddressOf(),nullptr));
  return result;
}

void fill(IDirectDrawSurface& surface, bool glyphs) {
  DDSURFACEDESC desc{};
  desc.dwSize=sizeof(desc);
  check(surface.Lock(nullptr,&desc,DDLOCK_WRITEONLY|DDLOCK_WAIT,nullptr));
  for (unsigned y=0;y<extent;++y) {
    auto* row=reinterpret_cast<uint16_t*>(static_cast<char*>(desc.lpSurface)+y*desc.lPitch);
    for (unsigned x=0;x<extent;++x)
      row[x]=glyphs ? ((x+2*y)%5==0 ? key : uint16_t(x*281+y*199)) : background;
  }
  check(surface.Unlock(desc.lpSurface));
}

std::vector<uint16_t> read(IDirectDrawSurface& surface) {
  DDSURFACEDESC desc{};
  desc.dwSize=sizeof(desc);
  check(surface.Lock(nullptr,&desc,DDLOCK_READONLY|DDLOCK_WAIT,nullptr));
  std::vector<uint16_t> pixels;
  for (unsigned y=0;y<extent;++y) {
    const auto* row=reinterpret_cast<const uint16_t*>(static_cast<char*>(desc.lpSurface)+y*desc.lPitch);
    pixels.insert(pixels.end(),row,row+extent);
  }
  check(surface.Unlock(desc.lpSurface));
  return pixels;
}

void exercise(IDirectDraw& draw, Batch batch) {
  const auto atlas=makeSurface(draw), target=makeSurface(draw), native=makeSurface(draw);
  fill(*atlas.Get(),true);
  DDCOLORKEY color{key,key};
  check(atlas->SetColorKey(DDCKEY_SRCBLT,&color));
  RECT from{1,2,36,39}, first{3,5,19,25}, second{14,16,43,40};
  const auto blit=[&](IDirectDrawSurface& into, RECT& dest) {
    check(into.Blt(&dest,atlas.Get(),&from,blitFlags,nullptr));
  };
  fill(*native.Get(),false);
  blit(*native.Get(),first);
  const auto firstOnly=read(*native.Get());
  blit(*native.Get(),second);
  const auto reference=read(*native.Get());
  require(firstOnly!=reference,"reference glyphs must change the target");

  uint32_t busy=1;
  fill(*target.Get(),false);
  require(batch(target.Get(),0,&busy)==DD_OK,"capture did not begin");
  blit(*target.Get(),first);
  blit(*target.Get(),second);
  check(batch(target.Get(),1,&busy));
  require(read(*target.Get())==reference,"batch pixels differ from ordered native blits");

  fill(*target.Get(),false);
  check(batch(target.Get(),0,&busy));
  require(read(*target.Get())==std::vector<uint16_t>(extent*extent,background),
          "capture must allow inspection before the first transfer");
  blit(*target.Get(),first);
  busy=0;
  require(FAILED(batch(target.Get(),1,&busy)),"abandoned capture must fail completion");
  require(read(*target.Get())==std::vector<uint16_t>(extent*extent,background),
          "abandoned glyphs were written");

  busy=1;
  check(batch(target.Get(),0,&busy));
  blit(*target.Get(),first);
  DDCOLORKEY changed{0,0};
  check(atlas->SetColorKey(DDCKEY_SRCBLT,&changed));
  check(batch(target.Get(),1,&busy));
  require(read(*target.Get())==firstOnly,"queued glyphs used the changed source key");
}

void exerciseReuse(IDirectDraw& draw, Batch batch, Reuse reuse) {
  const auto atlas=makeSurface(draw), target=makeSurface(draw), other=makeSurface(draw);
  fill(*atlas.Get(),true);
  fill(*other.Get(),true);
  DDCOLORKEY color{key,key};
  check(atlas->SetColorKey(DDCKEY_SRCBLT,&color));
  check(other->SetColorKey(DDCKEY_SRCBLT,&color));
  uint32_t busy=0, publication=0, creations=1, releases=0;
  const auto prepare=[&](bool sameLayout=true) {
    return reuse(target.Get(),atlas.Get(),&busy,publication,creations,releases,sameLayout);
  };
  const auto fresh=[&](IDirectDrawSurface& source) {
    fill(*target.Get(),false);
    busy=1;
    require(batch(target.Get(),0,&busy)==DD_OK,"reusable capture did not begin");
    RECT from{1,2,36,39}, to{3,5,19,25};
    check(target->Blt(&to,&source,&from,blitFlags,nullptr));
    require(batch(target.Get(),1,&busy)==DD_OK,"reusable capture did not finish");
    busy=0;
    ++publication;
  };

  require(prepare()==S_FALSE,"unpublished pixels were reused");
  fresh(*atlas.Get());
  const auto reference=read(*target.Get());
  require(prepare()==S_OK,"unchanged atlas did not reuse");
  require(read(*target.Get())==reference,"reuse changed the destination");
  ++publication;
  require(prepare()==S_OK,"successive publication did not reuse");
  require(prepare()==S_FALSE,"missing publication did not invalidate reuse");
  fresh(*other.Get());
  require(prepare()==S_FALSE,"unverified source populated the reuse cache");
  fresh(*atlas.Get());
  require(prepare(false)==S_FALSE,"changed native layout reused pixels");
  fresh(*atlas.Get());
  ++creations;
  ++releases;
  require(prepare()==S_FALSE,"recreated destination reused pixels");
  fresh(*atlas.Get());
  DDSURFACEDESC desc{};
  desc.dwSize=sizeof(desc);
  check(atlas->Lock(nullptr,&desc,DDLOCK_WRITEONLY|DDLOCK_WAIT,nullptr));
  auto* last=reinterpret_cast<uint16_t*>(static_cast<char*>(desc.lpSurface)+(extent-1)*desc.lPitch);
  last[extent-1]^=1;
  check(atlas->Unlock(desc.lpSurface));
  require(prepare()==S_FALSE,"an in-place atlas edit passed exact validation");
  fresh(*atlas.Get());
  DDCOLORKEY changed{0,0};
  check(atlas->SetColorKey(DDCKEY_SRCBLT,&changed));
  require(prepare()==S_FALSE,"changed source key reused pixels");
  check(atlas->SetColorKey(DDCKEY_SRCBLT,&color));
  fill(*target.Get(),false);
  busy=1;
  require(batch(target.Get(),0,&busy)==DD_OK,"second reusable capture did not begin");
  require(!read(*target.Get()).empty(),"read before the first glyph failed");
  RECT from{1,2,36,39}, to{3,5,19,25};
  check(target->Blt(&to,atlas.Get(),&from,blitFlags,nullptr));
  require(batch(target.Get(),1,&busy)==DD_OK,"fresh drawing failed after a read");
  busy=0;
  ++publication;
  require(read(*target.Get())==reference,"fresh drawing changed after a read");
  require(prepare()==S_FALSE,"interrupted capture established a reuse proof");
}
}

int main(int argc,char** argv) {
  try {
    require(argc==2,"pass the OpenXR renderer DLL path");
    const auto dll=LoadLibraryA(argv[1]);
    require(dll!=nullptr,"could not load renderer");
    const auto create=reinterpret_cast<HRESULT(WINAPI*)(GUID*,IDirectDraw**,IUnknown*)>(
      GetProcAddress(dll,"DirectDrawCreate"));
    const auto batch=reinterpret_cast<Batch>(GetProcAddress(dll,"Gk3hdXrGlyphBatchV1"));
    const auto reuse=reinterpret_cast<Reuse>(GetProcAddress(dll,"Gk3hdXrGlyphReuseV1"));
    require(create && batch && reuse,"required renderer exports are missing");
    const auto window=CreateWindowExW(0,L"STATIC",L"GK3HD glyph batch test",WS_OVERLAPPEDWINDOW,
      0,0,128,128,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
    require(window!=nullptr,"could not create the test window");
    {
      ComPtr<IDirectDraw> draw;
      check(create(nullptr,draw.GetAddressOf(),nullptr));
      check(draw->SetCooperativeLevel(window,DDSCL_NORMAL));
      exercise(*draw.Get(),batch);
      exerciseReuse(*draw.Get(),batch,reuse);
    }
    DestroyWindow(window);
    std::cout << "Grouped glyphs, abandonment and exact atlas reuse verified\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
