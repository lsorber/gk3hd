#define NOMINMAX
#include <windows.h>
#include <ddraw.h>
#include <d3d.h>
#include <wrl/client.h>
#include <cstdint>
#include <iostream>
#include <stdexcept>

using Microsoft::WRL::ComPtr;

static void check(const char* label, HRESULT result) {
  if (FAILED(result)) {
    std::cerr << label << ": 0x" << std::hex << uint32_t(result) << '\n';
    throw std::runtime_error(label);
  }
}

template<class T> static ComPtr<T> query(IUnknown* object, REFIID iid) {
  ComPtr<T> result;
  check("QueryInterface", object->QueryInterface(iid, reinterpret_cast<void**>(result.GetAddressOf())));
  return result;
}

template<class Description, class Surface, class Clear>
static void check_windowed_copy(Surface* primary, Surface* target, Clear clear) {
  RECT whole{0, 0, 96, 64}, corner{80, 48, 96, 64};
  DDBLTFX copy{}; copy.dwSize = sizeof(copy); copy.dwROP = SRCCOPY;
  for (bool fast : {false, true}) {
    clear();
    // Present GPU-only frames repeatedly without priming the CPU cache.
    for (unsigned frame = 0; frame < 8; ++frame) {
      if (fast)
        check("windowed BltFast presentation", primary->BltFast(0, 0, target, &whole, DDBLTFAST_WAIT));
      else
        check("windowed ROP presentation", primary->Blt(&whole, target, &whole, DDBLT_WAIT | DDBLT_ROP, &copy));
    }
    Description mapped{}; mapped.dwSize = sizeof(mapped);
    check("write overlay after presentation", target->Lock(&corner, &mapped, DDLOCK_WRITEONLY | DDLOCK_WAIT, nullptr));
    for (int y = 0; y < 16; ++y) {
      auto row = reinterpret_cast<uint16_t*>(static_cast<char*>(mapped.lpSurface) + y * mapped.lPitch);
      for (int x = 0; x < 16; ++x) row[x] = 0x07e0;
    }
    check("unlock presentation overlay", target->Unlock(nullptr));
    check("present CPU-authored overlay", primary->Blt(&whole, target, &whole, DDBLT_WAIT | DDBLT_ROP, &copy));
    // CPU consumers must still see the retained scene and the new overlay.
    mapped = {}; mapped.dwSize = sizeof(mapped);
    check("read scene after windowed presentation", target->Lock(&whole, &mapped, DDLOCK_READONLY | DDLOCK_WAIT, nullptr));
    unsigned wrong = 0;
    for (int y = 0; y < 64; ++y) {
      auto row = reinterpret_cast<const uint16_t*>(static_cast<const char*>(mapped.lpSurface) + y * mapped.lPitch);
      for (int x = 0; x < 96; ++x) wrong += row[x] != (x >= 80 && y >= 48 ? 0x07e0 : 0xf800);
    }
    check("unlock presented scene", target->Unlock(nullptr));
    if (wrong) throw std::runtime_error("windowed presentation lost GPU pixels or CPU overlay");
  }
}

template<class Clear>
static void check_windowed_aliases(IDirectDrawSurface* primary, IDirectDrawSurface* target, Clear clear) {
  check_windowed_copy<DDSURFACEDESC>(primary, target, clear);
  auto primary2 = query<IDirectDrawSurface2>(primary, IID_IDirectDrawSurface2);
  auto target2 = query<IDirectDrawSurface2>(target, IID_IDirectDrawSurface2);
  check_windowed_copy<DDSURFACEDESC>(primary2.Get(), target2.Get(), clear);
  auto primary3 = query<IDirectDrawSurface3>(primary, IID_IDirectDrawSurface3);
  auto target3 = query<IDirectDrawSurface3>(target, IID_IDirectDrawSurface3);
  check_windowed_copy<DDSURFACEDESC>(primary3.Get(), target3.Get(), clear);
  auto primary4 = query<IDirectDrawSurface4>(primary, IID_IDirectDrawSurface4);
  auto target4 = query<IDirectDrawSurface4>(target, IID_IDirectDrawSurface4);
  check_windowed_copy<DDSURFACEDESC2>(primary4.Get(), target4.Get(), clear);
  auto primary7 = query<IDirectDrawSurface7>(primary, IID_IDirectDrawSurface7);
  auto target7 = query<IDirectDrawSurface7>(target, IID_IDirectDrawSurface7);
  check_windowed_copy<DDSURFACEDESC2>(primary7.Get(), target7.Get(), clear);
}

static void check_windowed_presentation(IDirectDraw* dd) {
  DDSURFACEDESC desc{}; desc.dwSize = sizeof(desc); desc.dwFlags = DDSD_CAPS;
  desc.ddsCaps.dwCaps = DDSCAPS_PRIMARYSURFACE;
  ComPtr<IDirectDrawSurface> primary, target;
  check("create windowed primary", dd->CreateSurface(&desc, primary.GetAddressOf(), nullptr));
  desc.dwFlags = DDSD_WIDTH | DDSD_HEIGHT | DDSD_CAPS | DDSD_PIXELFORMAT;
  desc.dwWidth = 96; desc.dwHeight = 64;
  desc.ddsCaps.dwCaps = DDSCAPS_OFFSCREENPLAIN | DDSCAPS_3DDEVICE | DDSCAPS_VIDEOMEMORY;
  desc.ddpfPixelFormat = {sizeof(DDPIXELFORMAT), DDPF_RGB, 0, 16, 0xf800, 0x7e0, 0x1f, 0};
  check("create windowed render target", dd->CreateSurface(&desc, target.GetAddressOf(), nullptr));
  auto d3d = query<IDirect3D2>(dd, IID_IDirect3D2);
  ComPtr<IDirect3DDevice2> device;
  check("create windowed legacy device", d3d->CreateDevice(IID_IDirect3DHALDevice, target.Get(), device.GetAddressOf()));
  ComPtr<IDirect3DViewport2> viewport;
  check("create windowed viewport", d3d->CreateViewport(viewport.GetAddressOf(), nullptr));
  check("attach windowed viewport", device->AddViewport(viewport.Get()));
  D3DVIEWPORT2 view{sizeof(view), 0, 0, 96, 64, -1.f, 1.f, 2.f, 2.f, 0.f, 1.f};
  check("configure windowed viewport", viewport->SetViewport2(&view));
  check("select windowed viewport", device->SetCurrentViewport(viewport.Get()));
  ComPtr<IDirect3DMaterial2> material;
  check("create background material", d3d->CreateMaterial(material.GetAddressOf(), nullptr));
  D3DMATERIAL red{}; red.dwSize = sizeof(red); red.diffuse.r = 1.f; red.diffuse.a = 1.f;
  check("set red background", material->SetMaterial(&red));
  D3DMATERIALHANDLE background;
  check("get background handle", material->GetHandle(device.Get(), &background));
  check("set viewport background", viewport->SetBackground(background));
  D3DRECT all{0, 0, 96, 64};
  check_windowed_aliases(primary.Get(), target.Get(), [&] {
    check("clear legacy windowed target", viewport->Clear(1, &all, D3DCLEAR_TARGET));
  });
  check("detach windowed viewport", device->DeleteViewport(viewport.Get()));
  material.Reset(); viewport.Reset(); device.Reset();
  // GK3 renders through Device3 but presents through Surface1. Presentation
  // must recognize aliases across those interface versions and recreation.
  auto d3d3 = query<IDirect3D3>(dd, IID_IDirect3D3);
  auto target4 = query<IDirectDrawSurface4>(target.Get(), IID_IDirectDrawSurface4);
  ComPtr<IDirect3DDevice3> device3;
  check("recreate windowed device through Device3", d3d3->CreateDevice(IID_IDirect3DHALDevice, target4.Get(), device3.GetAddressOf(), nullptr));
  ComPtr<IDirect3DViewport3> viewport3;
  check("create recreated viewport", d3d3->CreateViewport(viewport3.GetAddressOf(), nullptr));
  check("attach recreated viewport", device3->AddViewport(viewport3.Get()));
  check("configure recreated viewport", viewport3->SetViewport2(&view));
  check("select recreated viewport", device3->SetCurrentViewport(viewport3.Get()));
  check_windowed_aliases(primary.Get(), target.Get(), [&] {
    check("clear recreated windowed target", viewport3->Clear2(1, &all, D3DCLEAR_TARGET, 0xffff0000, 1.f, 0));
  });
  check("detach recreated viewport", device3->DeleteViewport(viewport3.Get()));
}

int wmain(int argc, wchar_t** argv) {
  try {
    if (argc != 2) throw std::runtime_error("provide one renderer DLL path");
    HMODULE module = LoadLibraryW(argv[1]);
    if (!module) throw std::runtime_error("LoadLibraryW");
    auto create = reinterpret_cast<HRESULT(WINAPI*)(GUID*, IDirectDraw**, IUnknown*)>(
      GetProcAddress(module, "DirectDrawCreate"));
    if (!create) throw std::runtime_error("DirectDrawCreate export");
    HWND window = CreateWindowExW(0, L"STATIC", L"gk3hd presentation test", WS_OVERLAPPEDWINDOW,
      0, 0, 128, 128, nullptr, nullptr, GetModuleHandleW(nullptr), nullptr);
    if (!window) throw std::runtime_error("CreateWindowExW");
    unsigned wrong = 0;
    {
      ComPtr<IDirectDraw> dd;
      check("create windowed DirectDraw", create(nullptr, dd.GetAddressOf(), nullptr));
      check("set windowed cooperative level", dd->SetCooperativeLevel(window, DDSCL_NORMAL));
      check_windowed_presentation(dd.Get());
    }
    {
      ComPtr<IDirectDraw> dd;
      check("DirectDrawCreate", create(nullptr, dd.GetAddressOf(), nullptr));
      auto dd4 = query<IDirectDraw4>(dd.Get(), IID_IDirectDraw4);
      check("SetCooperativeLevel", dd4->SetCooperativeLevel(window, DDSCL_NORMAL));
      DDSURFACEDESC2 desc{};
      desc.dwSize = sizeof(desc);
      desc.dwFlags = DDSD_WIDTH | DDSD_HEIGHT | DDSD_CAPS | DDSD_PIXELFORMAT | DDSD_BACKBUFFERCOUNT;
      desc.dwWidth = 96; desc.dwHeight = 64; desc.dwBackBufferCount = 1;
      desc.ddsCaps.dwCaps = DDSCAPS_OFFSCREENPLAIN | DDSCAPS_3DDEVICE | DDSCAPS_VIDEOMEMORY |
        DDSCAPS_FLIP | DDSCAPS_COMPLEX;
      desc.ddpfPixelFormat = {sizeof(DDPIXELFORMAT), DDPF_RGB, 0, 16, 0xf800, 0x7e0, 0x1f, 0};
      ComPtr<IDirectDrawSurface4> front, back;
      check("CreateSurface", dd4->CreateSurface(&desc, front.GetAddressOf(), nullptr));
      DDSCAPS2 caps{}; caps.dwCaps = DDSCAPS_BACKBUFFER;
      check("GetAttachedSurface", front->GetAttachedSurface(&caps, back.GetAddressOf()));
      auto d3d = query<IDirect3D3>(dd4.Get(), IID_IDirect3D3);
      ComPtr<IDirect3DDevice3> device;
      check("CreateDevice", d3d->CreateDevice(IID_IDirect3DHALDevice, back.Get(), device.GetAddressOf(), nullptr));
      ComPtr<IDirect3DViewport3> viewport;
      check("CreateViewport", d3d->CreateViewport(viewport.GetAddressOf(), nullptr));
      check("AddViewport", device->AddViewport(viewport.Get()));
      D3DVIEWPORT2 view{sizeof(view), 0, 0, 96, 64, -1.f, 1.f, 2.f, 2.f, 0.f, 1.f};
      check("SetViewport2", viewport->SetViewport2(&view));
      check("SetCurrentViewport", device->SetCurrentViewport(viewport.Get()));
      // The first NOVSYNC flip can reset the swapchain legitimately.
      check("prime presentation mode", front->Flip(nullptr, DDFLIP_WAIT | DDFLIP_NOVSYNC));
      D3DRECT full{0, 0, 96, 64}, corner{80, 48, 96, 64};
      check("initial GPU clear", viewport->Clear2(1, &full, D3DCLEAR_TARGET, 0xffff0000, 1.f, 0));
      // Exercise multiple in-flight presents without readbacks that would mask
      // premature acquire/present semaphore reuse by synchronizing every frame.
      for (unsigned frame = 0; frame < 64; ++frame) {
        check("burst BeginScene", device->BeginScene());
        check("burst EndScene", device->EndScene());
        check("burst Flip", front->Flip(nullptr, DDFLIP_WAIT | DDFLIP_NOVSYNC));
      }
      for (unsigned frame = 0; frame < 8; ++frame) {
        check("BeginScene", device->BeginScene());
        check("EndScene", device->EndScene());
        check("Flip", front->Flip(nullptr, DDFLIP_WAIT | DDFLIP_NOVSYNC));
        // GK3's incremental updates require retained pixels on this windowed
        // compatibility path. A GPU write invalidates the CPU shadow, so the
        // following read cannot conceal incorrect retention behind cached data.
        check("partial GPU clear", viewport->Clear2(1, &corner, D3DCLEAR_TARGET, 0xff0000ff, 1.f, 0));
        RECT retained{8, 8, 24, 24};
        DDSURFACEDESC2 read{}; read.dwSize = sizeof(read);
        check("read retained pixels", back->Lock(&retained, &read, DDLOCK_READONLY | DDLOCK_WAIT, nullptr));
        for (int y = 0; y < 16; ++y) {
          auto row = reinterpret_cast<uint16_t*>(static_cast<char*>(read.lpSurface) + y * read.lPitch);
          for (int x = 0; x < 16; ++x) wrong += row[x] != 0xf800;
        }
        check("Unlock", back->Unlock(nullptr));
      }
      check("DeleteViewport", device->DeleteViewport(viewport.Get()));
    }
    DestroyWindow(window);
    FreeLibrary(module);
    std::cout << "Burst and checked presents: " << wrong << " incorrect retained pixels\n";
    return wrong ? 1 : 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 2;
  }
}
