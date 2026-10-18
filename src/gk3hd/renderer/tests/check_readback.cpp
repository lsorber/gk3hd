#define NOMINMAX
#include <windows.h>
#include <ddraw.h>
#include <d3d.h>
#include <wrl/client.h>
#include <cstdint>
#include <iostream>
#include <stdexcept>

using Microsoft::WRL::ComPtr;

static void check(const char* operation, HRESULT result) {
  if (FAILED(result)) {
    std::cerr << operation << ": 0x" << std::hex << uint32_t(result) << '\n';
    throw std::runtime_error(operation);
  }
}

template<class T> static ComPtr<T> query(IUnknown* object, REFIID iid) {
  ComPtr<T> result;
  check("QueryInterface", object->QueryInterface(iid, reinterpret_cast<void**>(result.GetAddressOf())));
  return result;
}

template<class Description, class Surface, class Pixel>
static void expect_pixels(Surface* surface, RECT region, Pixel expected) {
  Description mapped{};
  mapped.dwSize = sizeof(mapped);
  check("read GPU pixels", surface->Lock(&region, &mapped, DDLOCK_READONLY | DDLOCK_WAIT, nullptr));
  unsigned wrong = 0;
  for (LONG y = 0; y < region.bottom - region.top; ++y) {
    auto row = reinterpret_cast<const uint16_t*>(static_cast<const char*>(mapped.lpSurface) + y * mapped.lPitch);
    for (LONG x = 0; x < region.right - region.left; ++x)
      wrong += row[x] != expected(x, y);
  }
  check("unlock readback", surface->Unlock(nullptr));
  if (wrong) throw std::runtime_error("GPU readback changed pixels");
}

template<class Description, class Surface>
static void expect(Surface* surface, RECT region, uint16_t expected) {
  expect_pixels<Description>(surface, region, [expected](LONG, LONG) { return expected; });
}

template<class Description, class Surface>
static void check_opaque_crop_copy(Surface* source, Surface* target, IDirect3DViewport3* viewport, bool fast) {
  RECT whole{0,0,1280,800}, crop{0,0,32,32}, written{97,251,129,283};
  D3DRECT full{0,0,1280,800}, outside{1264,784,1280,800};
  DDBLTFX fill{}; fill.dwSize=sizeof(fill); fill.dwFillColor=0x07e0;
  // The backing exists, but these subsequent GPU clears invalidate its pixels.
  // No target read is allowed to prime the destination before the fast copy.
  for (unsigned frame=0;frame<3;++frame) {
    // Dirty a CPU-authored source on every transaction. A crop must never
    // overwrite unrelated destination pixels, regardless of its copy path.
    check("prepare opaque green source", source->Blt(&crop,nullptr,nullptr,DDBLT_COLORFILL|DDBLT_WAIT,&fill));
    check("invalidate opaque destination", viewport->Clear2(1,&full,D3DCLEAR_TARGET,0xffff0000,1.f,0));
    if (fast)
      check("opaque fast copy onto GPU-only scene", target->BltFast(written.left,written.top,source,&crop,DDBLTFAST_WAIT));
    else
      check("opaque crop copy onto GPU-only scene", target->Blt(&written,source,&crop,DDBLT_WAIT,nullptr));
    check("flush copy and change unrelated corner", viewport->Clear2(1,&outside,D3DCLEAR_TARGET,0xff0000ff,1.f,0));
    expect_pixels<Description>(target,whole,[&](LONG x,LONG y) {
      if (x>=outside.x1 && y>=outside.y1) return uint16_t(0x001f);
      if (x>=written.left && x<written.right && y>=written.top && y<written.bottom) return uint16_t(0x07e0);
      return uint16_t(0xf800);
    });
    RECT invalid{-1,0,31,32};
    const auto rejected = fast ? target->BltFast(0,0,source,&invalid,DDBLTFAST_WAIT) :
      target->Blt(&written,source,&invalid,DDBLT_WAIT,nullptr);
    if (SUCCEEDED(rejected)) throw std::runtime_error("invalid opaque crop copy succeeded");
    expect<Description>(target,written,0x07e0);
  }
}

static void check_overlay_backgrounds(IDirectDraw* dd, IDirect3D3* d3d) {
  // GK3 uses the original DirectDraw surface interface for save-under blits.
  // Exercise those transactions, including ROP copies and the cross-interface
  // render target, rather than checking only Surface4 Lock results.
  DDSURFACEDESC desc{};
  desc.dwSize = sizeof(desc);
  desc.dwFlags = DDSD_WIDTH | DDSD_HEIGHT | DDSD_CAPS | DDSD_PIXELFORMAT;
  desc.dwWidth = 1280; desc.dwHeight = 800;
  desc.ddpfPixelFormat = {sizeof(DDPIXELFORMAT), DDPF_RGB, 0, 16, 0xf800, 0x7e0, 0x1f, 0};
  desc.ddsCaps.dwCaps = DDSCAPS_OFFSCREENPLAIN | DDSCAPS_3DDEVICE | DDSCAPS_VIDEOMEMORY;
  ComPtr<IDirectDrawSurface> target;
  check("create legacy color target", dd->CreateSurface(&desc, target.GetAddressOf(), nullptr));
  auto target4 = query<IDirectDrawSurface4>(target.Get(), IID_IDirectDrawSurface4);
  ComPtr<IDirect3DDevice3> device;
  check("create legacy device", d3d->CreateDevice(IID_IDirect3DHALDevice, target4.Get(), device.GetAddressOf(), nullptr));
  ComPtr<IDirect3DViewport3> viewport;
  check("create legacy viewport", d3d->CreateViewport(viewport.GetAddressOf(), nullptr));
  check("attach legacy viewport", device->AddViewport(viewport.Get()));
  D3DVIEWPORT2 view{sizeof(view), 0, 0, 1280, 800, -1.f, 1.f, 2.f, 2.f, 0.f, 1.f};
  check("configure legacy viewport", viewport->SetViewport2(&view));
  check("select legacy viewport", device->SetCurrentViewport(viewport.Get()));
  check("disable overlay-test depth", device->SetRenderState(D3DRENDERSTATE_ZENABLE, FALSE));
  check("disable overlay-test culling", device->SetRenderState(D3DRENDERSTATE_CULLMODE, D3DCULL_NONE));
  check("disable overlay-test blending", device->SetRenderState(D3DRENDERSTATE_ALPHABLENDENABLE, FALSE));
  D3DTLVERTEX vertices[] = {{0, 0, .5f, 1, 0xffff0000, 0, 0, 0}, {1280, 0, .5f, 1, 0xffff0000, 0, 0, 0},
                          {0, 800, .5f, 1, 0xffff0000, 0, 0, 0}, {1280, 800, .5f, 1, 0xffff0000, 0, 0, 0}};
  D3DRECT full{0, 0, 1280, 800}, outside{1264, 784, 1280, 800};
  const RECT regions[] = {{97, 251, 133, 287}, {408, 390, 630, 445}, {0, 0, 1280, 800}};
  DDBLTFX fill{}; fill.dwSize = sizeof(fill); fill.dwFillColor = 0x07e0;
  DDBLTFX copy{}; copy.dwSize = sizeof(copy); copy.dwROP = SRCCOPY;
  for (bool rasterized : {false, true}) for (RECT region : regions) {
    for (bool useRop : {false, true}) {
      RECT local{0, 0, region.right - region.left, region.bottom - region.top};
      desc.dwWidth = local.right; desc.dwHeight = local.bottom;
      desc.ddsCaps.dwCaps = DDSCAPS_OFFSCREENPLAIN | DDSCAPS_SYSTEMMEMORY;
      ComPtr<IDirectDrawSurface> saved;
      check("create legacy saved background", dd->CreateSurface(&desc, saved.GetAddressOf(), nullptr));
      check("draw legacy GPU scene", viewport->Clear2(1, &full, D3DCLEAR_TARGET, 0xffff0000, 1.f, 0));
      if (rasterized) {
        check("begin legacy scene", device->BeginScene());
        check("rasterize legacy scene", device->DrawPrimitive(D3DPT_TRIANGLESTRIP, D3DFVF_TLVERTEX, vertices, 4, 0));
        check("end legacy scene", device->EndScene());
      }
      const DWORD flags = DDBLT_WAIT | (useRop ? DDBLT_ROP : 0);
      // Cursor save-under uses BltFast. A small GPU source crop must keep its
      // exact pixels, including crops that span the backing's readback bands.
      if (useRop)
        check("save overlay background with ROP", saved->Blt(&local, target.Get(), &region, flags, &copy));
      else
        check("save cursor background with BltFast", saved->BltFast(0, 0, target.Get(), &region,
              DDBLTFAST_NOCOLORKEY | DDBLTFAST_WAIT));
      expect<DDSURFACEDESC>(saved.Get(), local, 0xf800);
      if (local.right < 1280) {
        // A transparent cursor/button must preserve the GPU scene around
        // its opaque pixels, not leave a black rectangular footprint.
        ComPtr<IDirectDrawSurface> overlay;
        check("create keyed overlay", dd->CreateSurface(&desc, overlay.GetAddressOf(), nullptr));
        const auto opaque = [local](LONG x, LONG y) {
          return x >= local.right / 3 && x < local.right * 2 / 3
              && y >= local.bottom / 3 && y < local.bottom * 2 / 3;
        };
        DDSURFACEDESC mapped{}; mapped.dwSize = sizeof(mapped);
        check("write keyed overlay", overlay->Lock(nullptr, &mapped, DDLOCK_WRITEONLY | DDLOCK_WAIT, nullptr));
        for (LONG y = 0; y < local.bottom; ++y) {
          auto row = reinterpret_cast<uint16_t*>(static_cast<char*>(mapped.lpSurface) + y * mapped.lPitch);
          for (LONG x = 0; x < local.right; ++x) row[x] = opaque(x, y) ? 0x07e0 : 0xf81f;
        }
        check("unlock keyed overlay", overlay->Unlock(nullptr));
        DDCOLORKEY key{0xf81f, 0xf81f};
        check("set magenta color key", overlay->SetColorKey(DDCKEY_SRCBLT, &key));
        if (rasterized)
          check("draw keyed overlay", target->Blt(&region, overlay.Get(), &local, DDBLT_KEYSRC | DDBLT_WAIT, nullptr));
        else
          check("draw keyed fast cursor", target->BltFast(region.left, region.top, overlay.Get(), &local,
                DDBLTFAST_SRCCOLORKEY | DDBLTFAST_WAIT));
        check("invalidate keyed CPU snapshot", viewport->Clear2(1, &outside, D3DCLEAR_TARGET, 0xff0000ff, 1.f, 0));
        expect_pixels<DDSURFACEDESC>(target.Get(), region,
            [opaque](LONG x, LONG y) { return uint16_t(opaque(x, y) ? 0x07e0 : 0xf800); });
      }
      check("draw temporary overlay", target->Blt(&region, nullptr, nullptr, DDBLT_COLORFILL | DDBLT_WAIT, &fill));
      if (useRop)
        check("restore overlay background", target->Blt(&region, saved.Get(), &local, flags, &copy));
      else
        check("restore fast cursor background", target->BltFast(region.left, region.top, saved.Get(), &local,
              DDBLTFAST_NOCOLORKEY | DDBLTFAST_WAIT));
      expect<DDSURFACEDESC>(target.Get(), region, 0xf800);
      check("invalidate legacy CPU snapshot", viewport->Clear2(1, &outside, D3DCLEAR_TARGET, 0xff0000ff, 1.f, 0));
      RECT restored = region;
      if (restored.right == 1280) restored.right = outside.x1;
      expect<DDSURFACEDESC>(target.Get(), restored, 0xf800);
    }
  }
  desc.dwWidth=32; desc.dwHeight=32;
  desc.ddsCaps.dwCaps=DDSCAPS_OFFSCREENPLAIN|DDSCAPS_SYSTEMMEMORY;
  ComPtr<IDirectDrawSurface> opaque;
  check("create opaque fast-copy source",dd->CreateSurface(&desc,opaque.GetAddressOf(),nullptr));
  for (bool fast : {false,true}) check_opaque_crop_copy<DDSURFACEDESC>(opaque.Get(),target.Get(),viewport.Get(),fast);
  auto opaque2=query<IDirectDrawSurface2>(opaque.Get(),IID_IDirectDrawSurface2);
  auto target2=query<IDirectDrawSurface2>(target.Get(),IID_IDirectDrawSurface2);
  for (bool fast : {false,true}) check_opaque_crop_copy<DDSURFACEDESC>(opaque2.Get(),target2.Get(),viewport.Get(),fast);
  auto opaque3=query<IDirectDrawSurface3>(opaque.Get(),IID_IDirectDrawSurface3);
  auto target3=query<IDirectDrawSurface3>(target.Get(),IID_IDirectDrawSurface3);
  for (bool fast : {false,true}) check_opaque_crop_copy<DDSURFACEDESC>(opaque3.Get(),target3.Get(),viewport.Get(),fast);
  auto opaque4=query<IDirectDrawSurface4>(opaque.Get(),IID_IDirectDrawSurface4);
  for (bool fast : {false,true}) check_opaque_crop_copy<DDSURFACEDESC2>(opaque4.Get(),target4.Get(),viewport.Get(),fast);
  auto opaque7=query<IDirectDrawSurface7>(opaque.Get(),IID_IDirectDrawSurface7);
  auto target7=query<IDirectDrawSurface7>(target.Get(),IID_IDirectDrawSurface7);
  for (bool fast : {false,true}) check_opaque_crop_copy<DDSURFACEDESC2>(opaque7.Get(),target7.Get(),viewport.Get(),fast);
  check("detach legacy viewport", device->DeleteViewport(viewport.Get()));
}

int wmain(int argc, wchar_t** argv) {
  SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
  try {
    if (argc != 2) throw std::runtime_error("provide one renderer DLL path");
    HMODULE module = LoadLibraryW(argv[1]);
    if (!module) throw std::runtime_error("LoadLibraryW");
    auto create = reinterpret_cast<HRESULT(WINAPI*)(GUID*, IDirectDraw**, IUnknown*)>(
      GetProcAddress(module, "DirectDrawCreate"));
    if (!create) throw std::runtime_error("DirectDrawCreate export");
    HWND window = CreateWindowExW(0, L"STATIC", L"gk3hd readback test", WS_OVERLAPPEDWINDOW,
      0, 0, 128, 128, nullptr, nullptr, GetModuleHandleW(nullptr), nullptr);
    if (!window) throw std::runtime_error("CreateWindowExW");
    {
      ComPtr<IDirectDraw> dd;
      check("create legacy DirectDraw", create(nullptr, dd.GetAddressOf(), nullptr));
      check("legacy cooperative level", dd->SetCooperativeLevel(window, DDSCL_NORMAL));
      auto d3d = query<IDirect3D3>(dd.Get(), IID_IDirect3D3);
      check_overlay_backgrounds(dd.Get(), d3d.Get());
    }
    {
      ComPtr<IDirectDraw> dd;
      check("DirectDrawCreate", create(nullptr, dd.GetAddressOf(), nullptr));
      auto dd4 = query<IDirectDraw4>(dd.Get(), IID_IDirectDraw4);
      check("SetCooperativeLevel", dd4->SetCooperativeLevel(window, DDSCL_NORMAL));
      DDSURFACEDESC2 desc{};
      desc.dwSize = sizeof(desc);
      desc.dwFlags = DDSD_WIDTH | DDSD_HEIGHT | DDSD_CAPS | DDSD_PIXELFORMAT;
      desc.dwWidth = 1280;
      desc.dwHeight = 800;
      desc.ddsCaps.dwCaps = DDSCAPS_OFFSCREENPLAIN | DDSCAPS_3DDEVICE | DDSCAPS_VIDEOMEMORY;
      desc.ddpfPixelFormat = {sizeof(DDPIXELFORMAT), DDPF_RGB, 0, 16, 0xf800, 0x7e0, 0x1f, 0};
      ComPtr<IDirectDrawSurface4> color, depth, saved;
      check("create color target", dd4->CreateSurface(&desc, color.GetAddressOf(), nullptr));
      desc.ddsCaps.dwCaps = DDSCAPS_OFFSCREENPLAIN | DDSCAPS_SYSTEMMEMORY;
      check("create saved background", dd4->CreateSurface(&desc, saved.GetAddressOf(), nullptr));
      desc.ddsCaps.dwCaps = DDSCAPS_ZBUFFER | DDSCAPS_VIDEOMEMORY;
      desc.ddpfPixelFormat = {};
      desc.ddpfPixelFormat.dwSize = sizeof(DDPIXELFORMAT);
      desc.ddpfPixelFormat.dwFlags = DDPF_ZBUFFER;
      desc.ddpfPixelFormat.dwZBufferBitDepth = 16;
      desc.ddpfPixelFormat.dwZBitMask = 0xffff;
      check("create depth target", dd4->CreateSurface(&desc, depth.GetAddressOf(), nullptr));
      check("attach depth target", color->AddAttachedSurface(depth.Get()));
      auto d3d = query<IDirect3D3>(dd4.Get(), IID_IDirect3D3);
      ComPtr<IDirect3DDevice3> device;
      check("create device", d3d->CreateDevice(IID_IDirect3DHALDevice, color.Get(), device.GetAddressOf(), nullptr));
      ComPtr<IDirect3DViewport3> viewport;
      check("create viewport", d3d->CreateViewport(viewport.GetAddressOf(), nullptr));
      check("attach viewport", device->AddViewport(viewport.Get()));
      D3DVIEWPORT2 view{sizeof(view), 0, 0, 1280, 800, -1.f, 1.f, 2.f, 2.f, 0.f, 1.f};
      check("configure viewport", viewport->SetViewport2(&view));
      check("select viewport", device->SetCurrentViewport(viewport.Get()));
      D3DRECT full{0, 0, 1280, 800};
      RECT all{0, 0, 1280, 800}, cursor{97, 251, 133, 287};
      for (unsigned frame = 0; frame < 3; ++frame) {
        check("clear targets", viewport->Clear2(1, &full, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER, 0xffff0000, 1.f, 0));
        // Single-sample depth must copy directly, not resolve into itself. This
        // triggers the same startup readback that crashed the AMD Vulkan driver.
        expect<DDSURFACEDESC2>(depth.Get(), all, 0xffff);
        RECT savedCursor{0, 0, cursor.right - cursor.left, cursor.bottom - cursor.top};
        check("save Surface4 cursor crop", saved->BltFast(0, 0, color.Get(), &cursor,
              DDBLTFAST_NOCOLORKEY | DDBLTFAST_WAIT));
        expect<DDSURFACEDESC2>(saved.Get(), savedCursor, 0xf800);
        expect<DDSURFACEDESC2>(color.Get(), cursor, 0xf800);
        check("save complete background", saved->Blt(nullptr, color.Get(), nullptr, DDBLT_WAIT, nullptr));
        check("overwrite background", viewport->Clear2(1, &full, D3DCLEAR_TARGET, 0xff0000ff, 1.f, 0));
        check("restore complete background", color->Blt(nullptr, saved.Get(), nullptr, DDBLT_WAIT, nullptr));
        expect<DDSURFACEDESC2>(color.Get(), all, 0xf800);
        // Invalidate the CPU snapshot without touching the test region, then
        // verify the restored pixels really survived the roundtrip to the GPU.
        D3DRECT corner{1200, 700, 1280, 800};
        check("partial GPU draw", viewport->Clear2(1, &corner, D3DCLEAR_TARGET, 0xff0000ff, 1.f, 0));
        expect<DDSURFACEDESC2>(color.Get(), cursor, 0xf800);
      }
      check("detach viewport", device->DeleteViewport(viewport.Get()));
    }
    DestroyWindow(window);
    std::cout << "Single-sample depth and cursor/menu/full-screen background restoration preserved pixels\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
