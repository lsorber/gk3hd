#define NOMINMAX
#include <windows.h>
#include <ddraw.h>
#include <d3d.h>
#include <wrl/client.h>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;
static unsigned failures=0;

void check(const char* step,HRESULT result) {
  if (FAILED(result)) {
    std::cerr << step << " failed: 0x" << std::hex << uint32_t(result) << std::dec << '\n';
    throw std::runtime_error(step);
  }
}
template<typename T> ComPtr<T> query(IUnknown* object,REFIID iid) {
  ComPtr<T> result;
  check("QueryInterface",object->QueryInterface(iid,reinterpret_cast<void**>(result.GetAddressOf())));
  return result;
}
template<typename T,typename D> void expectPixels(const char* label,T* surface,uint16_t expected,RECT region={8,8,24,24}) {
  D logical{}; logical.dwSize=sizeof(logical);
  check("GetSurfaceDesc",surface->GetSurfaceDesc(&logical));
  D desc{}; desc.dwSize=sizeof(desc);
  check("read Lock",surface->Lock(&region,&desc,DDLOCK_READONLY|DDLOCK_WAIT,nullptr));
  unsigned wrong=0;
  for (int y=0;y<region.bottom-region.top;++y) {
    auto row=reinterpret_cast<uint16_t*>(static_cast<char*>(desc.lpSurface)+y*desc.lPitch);
    for (int x=0;x<region.right-region.left;++x) wrong+=row[x]!=expected;
  }
  const DWORD caps=desc.ddsCaps.dwCaps;
  check("read Unlock",surface->Unlock(nullptr));
  std::cout << label << ": " << wrong << " incorrect pixels; Lock caps 0x" << std::hex << caps << std::dec << '\n';
  if (wrong) ++failures;
  if (caps!=logical.ddsCaps.dwCaps) {
    std::cout << "Lock/GetSurfaceDesc caps mismatch\n";
    ++failures;
  }
}
template<typename T,typename D> void writePixels(T* surface,uint16_t color) {
  RECT region{8,8,24,24};
  D desc{}; desc.dwSize=sizeof(desc);
  check("write Lock",surface->Lock(&region,&desc,DDLOCK_WRITEONLY|DDLOCK_WAIT,nullptr));
  for (int y=0;y<16;++y) {
    auto row=reinterpret_cast<uint16_t*>(static_cast<char*>(desc.lpSurface)+y*desc.lPitch);
    for (int x=0;x<16;++x) row[x]=color;
  }
  check("write Unlock",surface->Unlock(nullptr));
}

#include "check_surface_failures.h"

template<typename T> void checkKeys(T* setter,IDirectDrawSurface4* source,IDirectDrawSurface4* destination) {
  DDBLTFX fill{}; fill.dwSize=sizeof(fill); fill.dwFillColor=0x001f;
  DDCOLORKEY key{0xf800,0xf800};
  check("set red source key",setter->SetColorKey(DDCKEY_SRCBLT,&key));
  check("initialize key destination",destination->Blt(nullptr,nullptr,nullptr,DDBLT_COLORFILL|DDBLT_WAIT,&fill));
  check("copy keyed red source",destination->Blt(nullptr,source,nullptr,DDBLT_KEYSRC|DDBLT_WAIT,nullptr));
  expectPixels<IDirectDrawSurface4,DDSURFACEDESC2>("key preserves red background",destination,0x001f,{32,8,48,24});
  expectPixels<IDirectDrawSurface4,DDSURFACEDESC2>("key copies green foreground",destination,0x07e0);
  key={0x07e0,0x07e0};
  check("change source key to green",setter->SetColorKey(DDCKEY_SRCBLT,&key));
  check("reinitialize key destination",destination->Blt(nullptr,nullptr,nullptr,DDBLT_COLORFILL|DDBLT_WAIT,&fill));
  check("copy keyed green source",destination->Blt(nullptr,source,nullptr,DDBLT_KEYSRC|DDBLT_WAIT,nullptr));
  expectPixels<IDirectDrawSurface4,DDSURFACEDESC2>("changed key copies red background",destination,0xf800,{32,8,48,24});
  expectPixels<IDirectDrawSurface4,DDSURFACEDESC2>("changed key preserves green foreground",destination,0x001f);
  check("remove source key",setter->SetColorKey(DDCKEY_SRCBLT,nullptr));
  const HRESULT missing=destination->Blt(nullptr,source,nullptr,DDBLT_KEYSRC|DDBLT_WAIT,nullptr);
  if (SUCCEEDED(missing)) {
    std::cout << "Removed source key: keyed copy unexpectedly succeeded\n";
    ++failures;
  }
  check("unkeyed copy after removing key",destination->Blt(nullptr,source,nullptr,DDBLT_WAIT,nullptr));
  expectPixels<IDirectDrawSurface4,DDSURFACEDESC2>("removed key unkeyed foreground",destination,0x07e0);
}

template<typename T> void checkClipper(T* setter,IDirectDrawClipper* clipper,IDirectDrawSurface4* target,IDirect3DViewport3* viewport) {
  D3DRECT full{0,0,96,64};
  DDBLTFX prime{}; prime.dwSize=sizeof(prime); prime.dwFillColor=0x001f;
  check("prime different CPU pixels",target->Blt(nullptr,nullptr,nullptr,DDBLT_COLORFILL|DDBLT_WAIT,&prime));
  check("clear before clip test",viewport->Clear2(1,&full,D3DCLEAR_TARGET,0xffff0000,1.f,0));
  check("SetClipper",setter->SetClipper(clipper));
  DDBLTFX fill{}; fill.dwSize=sizeof(fill); fill.dwFillColor=0x001f;
  check("clipped color fill",setter->Blt(nullptr,nullptr,nullptr,DDBLT_COLORFILL|DDBLT_WAIT,&fill));
  expectPixels<IDirectDrawSurface4,DDSURFACEDESC2>("clip preserves outside pixels",target,0xf800);
  expectPixels<IDirectDrawSurface4,DDSURFACEDESC2>("clip draws inside pixels",target,0x001f,{32,8,48,24});
  check("detach clipper",setter->SetClipper(nullptr));
}

#include "check_key_scaling.h"
#include "check_texture_lifetime.h"

int wmain(int argc,wchar_t** argv) {
  try {
    if (argc!=2) throw std::runtime_error("provide one D7VK DLL path");
    HMODULE module=LoadLibraryW(argv[1]);
    if (!module) throw std::runtime_error("LoadLibraryW");
    auto create=reinterpret_cast<HRESULT(WINAPI*)(GUID*,IDirectDraw**,IUnknown*)>(GetProcAddress(module,"DirectDrawCreate"));
    if (!create) throw std::runtime_error("DirectDrawCreate export");
    auto historyDepth=reinterpret_cast<DWORD(WINAPI*)(IDirectDrawSurface*)>(GetProcAddress(module,"Gk3hdSurfaceHistoryDepth"));
    if (!historyDepth || historyDepth(nullptr)!=0)
      throw std::runtime_error("surface history capability export/null fallback");
    HWND window=CreateWindowExW(0,L"STATIC",L"gk3hd renderer surface test",WS_OVERLAPPEDWINDOW,0,0,128,128,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
    if (!window) throw std::runtime_error("CreateWindowExW");
    {
      ComPtr<IDirectDraw> dd;
      check("DirectDrawCreate",create(nullptr,dd.GetAddressOf(),nullptr));
      auto dd4=query<IDirectDraw4>(dd.Get(),IID_IDirectDraw4);
      check("SetCooperativeLevel",dd4->SetCooperativeLevel(window,DDSCL_NORMAL));
      DDSURFACEDESC2 desc{};
      desc.dwSize=sizeof(desc);
      desc.dwFlags=DDSD_WIDTH|DDSD_HEIGHT|DDSD_CAPS|DDSD_PIXELFORMAT;
      desc.dwWidth=96; desc.dwHeight=64;
      desc.ddsCaps.dwCaps=DDSCAPS_OFFSCREENPLAIN|DDSCAPS_3DDEVICE|DDSCAPS_VIDEOMEMORY;
      desc.ddpfPixelFormat={sizeof(DDPIXELFORMAT),DDPF_RGB,0,16,0xf800,0x7e0,0x1f,0};
      ComPtr<IDirectDrawSurface4> surface4;
      check("CreateSurface",dd4->CreateSurface(&desc,surface4.GetAddressOf(),nullptr));
      auto historySurface=query<IDirectDrawSurface>(surface4.Get(),IID_IDirectDrawSurface);
      if (historyDepth(historySurface.Get())!=0 || historyDepth(reinterpret_cast<IDirectDrawSurface*>(dd.Get()))!=0)
        throw std::runtime_error("history query must not create backing or accept a non-surface");
      auto d3d=query<IDirect3D3>(dd4.Get(),IID_IDirect3D3);
      ComPtr<IDirect3DDevice3> device;
      check("CreateDevice",d3d->CreateDevice(IID_IDirect3DHALDevice,surface4.Get(),device.GetAddressOf(),nullptr));
      ComPtr<IDirect3DViewport3> viewport;
      check("CreateViewport",d3d->CreateViewport(viewport.GetAddressOf(),nullptr));
      check("AddViewport",device->AddViewport(viewport.Get()));
      D3DVIEWPORT2 view{sizeof(view),0,0,96,64,-1.f,1.f,2.f,2.f,0.f,1.f};
      check("SetViewport2",viewport->SetViewport2(&view));
      check("SetCurrentViewport",device->SetCurrentViewport(viewport.Get()));
      D3DRECT rectangle{0,0,96,64};
      check("Clear2",viewport->Clear2(1,&rectangle,D3DCLEAR_TARGET,0xffff0000,1.f,0));
      auto surface1=query<IDirectDrawSurface>(surface4.Get(),IID_IDirectDrawSurface);
      auto surface2=query<IDirectDrawSurface2>(surface4.Get(),IID_IDirectDrawSurface2);
      auto surface3=query<IDirectDrawSurface3>(surface4.Get(),IID_IDirectDrawSurface3);
      auto surface7=query<IDirectDrawSurface7>(surface4.Get(),IID_IDirectDrawSurface7);
      expectPixels<IDirectDrawSurface4,DDSURFACEDESC2>("GPU -> Surface4",surface4.Get(),0xf800);
      expectPixels<IDirectDrawSurface,DDSURFACEDESC>("GPU -> Surface1",surface1.Get(),0xf800);
      expectPixels<IDirectDrawSurface2,DDSURFACEDESC>("GPU -> Surface2",surface2.Get(),0xf800);
      expectPixels<IDirectDrawSurface3,DDSURFACEDESC>("GPU -> Surface3",surface3.Get(),0xf800);
      expectPixels<IDirectDrawSurface7,DDSURFACEDESC2>("GPU -> Surface7",surface7.Get(),0xf800);
      if (historyDepth(surface1.Get())!=1)
        throw std::runtime_error("CPU-backed render target must report one retained history");
      writePixels<IDirectDrawSurface2,DDSURFACEDESC>(surface2.Get(),0x07e0);
      expectPixels<IDirectDrawSurface4,DDSURFACEDESC2>("Surface2 -> Surface4",surface4.Get(),0x07e0);
      writePixels<IDirectDrawSurface7,DDSURFACEDESC2>(surface7.Get(),0x001f);
      expectPixels<IDirectDrawSurface,DDSURFACEDESC>("Surface7 -> Surface1",surface1.Get(),0x001f);
      check("Clear2 before multiple locks",viewport->Clear2(1,&rectangle,D3DCLEAR_TARGET,0xffff0000,1.f,0));
      RECT writable{8,8,24,24},readOnly{32,8,48,24};
      DDSURFACEDESC2 writeDesc{}; writeDesc.dwSize=sizeof(writeDesc);
      DDSURFACEDESC readDesc{}; readDesc.dwSize=sizeof(readDesc);
      check("first region Lock",surface4->Lock(&writable,&writeDesc,DDLOCK_WRITEONLY|DDLOCK_WAIT,nullptr));
      check("second region Lock",surface1->Lock(&readOnly,&readDesc,DDLOCK_READONLY|DDLOCK_WAIT,nullptr));
      for(int y=0;y<16;++y) {
        auto row=reinterpret_cast<uint16_t*>(static_cast<char*>(writeDesc.lpSurface)+y*writeDesc.lPitch);
        for(int x=0;x<16;++x) row[x]=0x07e0;
      }
      check("first region Unlock",surface4->Unlock(&writable));
      check("second region Unlock",surface1->Unlock(readDesc.lpSurface));
      // GPU work outside either lock requires a preceding correct upload and
      // invalidates the CPU cache, so a later read cannot mask a missing upload.
      D3DRECT other{64,48,96,64};
      check("Clear2 after locks",viewport->Clear2(1,&other,D3DCLEAR_TARGET,0xff0000ff,1.f,0));
      expectPixels<IDirectDrawSurface,DDSURFACEDESC>("two locks -> GPU -> Surface1",surface1.Get(),0x07e0);
      check("clear before clip test",viewport->Clear2(1,&rectangle,D3DCLEAR_TARGET,0xffff0000,1.f,0));
      ComPtr<IDirectDrawClipper> clipper;
      check("CreateClipper",dd->CreateClipper(0,clipper.GetAddressOf(),nullptr));
      struct { RGNDATAHEADER header; RECT region; } clipData{};
      clipData.region={32,8,48,24};
      clipData.header={sizeof(RGNDATAHEADER),RDH_RECTANGLES,1,sizeof(RECT),clipData.region};
      check("SetClipList",clipper->SetClipList(reinterpret_cast<RGNDATA*>(&clipData),0));
      checkClipper(surface1.Get(),clipper.Get(),surface4.Get(),viewport.Get());
      checkClipper(surface2.Get(),clipper.Get(),surface4.Get(),viewport.Get());
      checkClipper(surface3.Get(),clipper.Get(),surface4.Get(),viewport.Get());
      checkClipper(surface4.Get(),clipper.Get(),surface4.Get(),viewport.Get());
      checkClipper(surface7.Get(),clipper.Get(),surface4.Get(),viewport.Get());
      check("clear before key test",viewport->Clear2(1,&rectangle,D3DCLEAR_TARGET,0xffff0000,1.f,0));
      writePixels<IDirectDrawSurface,DDSURFACEDESC>(surface1.Get(),0x07e0);
      ComPtr<IDirectDrawSurface4> destination;
      desc.ddsCaps.dwCaps=DDSCAPS_OFFSCREENPLAIN|DDSCAPS_SYSTEMMEMORY;
      check("create color-key destination",dd4->CreateSurface(&desc,destination.GetAddressOf(),nullptr));
      checkKeys(surface1.Get(),surface4.Get(),destination.Get());
      checkKeys(surface2.Get(),surface4.Get(),destination.Get());
      checkKeys(surface3.Get(),surface4.Get(),destination.Get());
      checkKeys(surface4.Get(),surface4.Get(),destination.Get());
      checkKeys(surface7.Get(),surface4.Get(),destination.Get());
      // Exercise the opposite direction too: native RGB565 sprite -> GPU target.
      // Color-key draws use CPU-backed pixels and must upload correctly without
      // changing the application's render state.
      auto sprite1=query<IDirectDrawSurface>(destination.Get(),IID_IDirectDrawSurface);
      if (historyDepth(sprite1.Get())!=0)
        throw std::runtime_error("native offscreen sprite must retain default history semantics");
      auto sprite7=query<IDirectDrawSurface7>(destination.Get(),IID_IDirectDrawSurface7);
      DDCOLORKEY spriteKey{0xf800,0xf800};
      for(unsigned keyPass=0;keyPass<3;++keyPass) {
        if(keyPass==1) spriteKey={0x07e0,0x07e0};
        if(keyPass<2) check("set sprite key via Surface7",sprite7->SetColorKey(DDCKEY_SRCBLT,&spriteKey));
        if(keyPass==2) writePixels<IDirectDrawSurface,DDSURFACEDESC>(sprite1.Get(),0x001f);
        check("begin keyed-copy frame",device->BeginScene());
        check("end keyed-copy frame",device->EndScene());
        check("blue GPU key background",viewport->Clear2(1,&rectangle,D3DCLEAR_TARGET,0xff0000ff,1.f,0));
        const D3DRENDERSTATETYPE watched[]={D3DRENDERSTATE_FOGENABLE,D3DRENDERSTATE_FOGCOLOR,
          D3DRENDERSTATE_CULLMODE,D3DRENDERSTATE_ALPHAREF,D3DRENDERSTATE_ALPHATESTENABLE,D3DRENDERSTATE_FILLMODE};
        const DWORD values[]={TRUE,0xff765432,D3DCULL_CW,73,TRUE,D3DFILL_WIREFRAME};
        DWORD saved[6]{};
        for (unsigned i=0;i<6;++i) {
          check("save render state",device->GetRenderState(watched[i],&saved[i]));
          check("set sentinel render state",device->SetRenderState(watched[i],values[i]));
        }
        check("CPU-backed key blit",surface1->Blt(nullptr,sprite1.Get(),nullptr,DDBLT_KEYSRC|DDBLT_WAIT,nullptr));
        for (unsigned i=0;i<6;++i) {
          DWORD actual=0;check("read sentinel render state",device->GetRenderState(watched[i],&actual));
          if (actual!=values[i]) {std::cout<<"key blit changed render state\n";++failures;}
          check("restore sentinel render state",device->SetRenderState(watched[i],saved[i]));
        }
        check("keyed copy GPU roundtrip",viewport->Clear2(1,&other,D3DCLEAR_TARGET,0xff0000ff,1.f,0));
        expectPixels<IDirectDrawSurface4,DDSURFACEDESC2>("GPU keyed background",surface4.Get(),keyPass==0?0x001f:0xf800,{32,8,48,24});
        expectPixels<IDirectDrawSurface4,DDSURFACEDESC2>("GPU keyed foreground",surface4.Get(),keyPass==0?0x07e0:0x001f);
      }
      checkKeyScaling(dd4.Get(),device.Get(),viewport.Get(),surface1.Get(),surface4.Get());
      checkBoundTextureLifetime(dd4.Get(),device.Get());
      check("clear before GDI test",viewport->Clear2(1,&rectangle,D3DCLEAR_TARGET,0xffff0000,1.f,0));
      HDC dc=nullptr;
      check("Surface2 GetDC",surface2->GetDC(&dc));
      HBRUSH brush=CreateSolidBrush(RGB(0,255,0));
      if (!brush || !FillRect(dc,&writable,brush)) throw std::runtime_error("GDI FillRect");
      DeleteObject(brush);
      check("Surface7 ReleaseDC",surface7->ReleaseDC(dc));
      check("GPU after GDI",viewport->Clear2(1,&other,D3DCLEAR_TARGET,0xff0000ff,1.f,0));
      expectPixels<IDirectDrawSurface2,DDSURFACEDESC>("cross-interface GDI -> GPU -> CPU",surface2.Get(),0x07e0);
      check("DeleteViewport",device->DeleteViewport(viewport.Get()));
      viewport.Reset();
      device.Reset();
      for(unsigned generation=0;generation<5;++generation) {
        check("recreate device",d3d->CreateDevice(IID_IDirect3DHALDevice,surface4.Get(),device.GetAddressOf(),nullptr));
        check("recreate viewport",d3d->CreateViewport(viewport.GetAddressOf(),nullptr));
        check("re-add viewport",device->AddViewport(viewport.Get()));
        check("reset viewport",viewport->SetViewport2(&view));
        check("reset current viewport",device->SetCurrentViewport(viewport.Get()));
        check("recreated GPU clear",viewport->Clear2(1,&rectangle,D3DCLEAR_TARGET,0xffff0000,1.f,0));
        check("begin recreated keyed frame",device->BeginScene());
        check("end recreated keyed frame",device->EndScene());
        check("recreated keyed copy",surface1->Blt(nullptr,sprite1.Get(),nullptr,DDBLT_KEYSRC|DDBLT_WAIT,nullptr));
        check("recreated keyed copy upload",viewport->Clear2(1,&other,D3DCLEAR_TARGET,0xff0000ff,1.f,0));
        expectPixels<IDirectDrawSurface4,DDSURFACEDESC2>("recreated keyed copy GPU/CPU roundtrip",surface4.Get(),0x001f);
        writePixels<IDirectDrawSurface3,DDSURFACEDESC>(surface3.Get(),0x07e0);
        check("recreated partial GPU clear",viewport->Clear2(1,&other,D3DCLEAR_TARGET,0xff0000ff,1.f,0));
        expectPixels<IDirectDrawSurface7,DDSURFACEDESC2>("recreated device CPU/GPU roundtrip",surface7.Get(),0x07e0);
        check("detach recreated viewport",device->DeleteViewport(viewport.Get()));
        viewport.Reset(); device.Reset();
      }
    }
    checkTransferFailures(create,window);
    DestroyWindow(window);
    std::cout << "Failures: " << failures << '\n';
    // D7VK owns process-lifetime worker state; process teardown unloads it.
    return failures ? 1 : 0;
  } catch(const std::exception& error) {
    std::cerr << "Error: " << error.what() << '\n';
    return 2;
  }
}
