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
    std::cout << "Eight actual presents: " << wrong << " incorrect retained pixels\n";
    return wrong ? 1 : 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 2;
  }
}
