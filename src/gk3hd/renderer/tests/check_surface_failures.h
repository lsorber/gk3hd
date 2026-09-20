// Private, process-local fault injection. No hooks or fault switches in the DLL.
// Every injected Unlock first releases the real lock, so a retry is legal.
class NativeTransferFault {
  using Lock = HRESULT(STDMETHODCALLTYPE*)(IDirectDrawSurface*,RECT*,DDSURFACEDESC*,DWORD,HANDLE);
  using Unlock = HRESULT(STDMETHODCALLTYPE*)(IDirectDrawSurface*,void*);
  void** table;
  inline static Lock originalLock;
  inline static Unlock originalUnlock;
  inline static DWORD selectedFlags;
  inline static bool atUnlock=false, armed=false, fired=false;
  inline static IDirectDrawSurface* unlockTarget=nullptr;

  static HRESULT STDMETHODCALLTYPE lock(IDirectDrawSurface* surface,RECT* rect,DDSURFACEDESC* desc,DWORD flags,HANDLE event) {
    if (armed && (flags&selectedFlags)) {
      armed=false;
      fired=true;
      if (!atUnlock) return DDERR_SURFACEBUSY;
      unlockTarget=surface;
    }
    return originalLock(surface,rect,desc,flags,event);
  }
  static HRESULT STDMETHODCALLTYPE unlock(IDirectDrawSurface* surface,void* data) {
    HRESULT hr=originalUnlock(surface,data);
    if (surface==unlockTarget) {
      unlockTarget=nullptr;
      check("real Unlock during fault injection",hr);
      return DDERR_SURFACEBUSY;
    }
    return hr;
  }
  void set(unsigned index,void* pointer) {
    DWORD protection;
    if (!VirtualProtect(table+index,sizeof(void*),PAGE_READWRITE,&protection))
      throw std::runtime_error("vtable VirtualProtect");
    table[index]=pointer;
    DWORD discarded;
    if (!VirtualProtect(table+index,sizeof(void*),protection,&discarded))
      throw std::runtime_error("vtable restore protection");
  }
public:
  explicit NativeTransferFault(IDirectDrawSurface* native):table(*reinterpret_cast<void***>(native)) {
    originalLock=reinterpret_cast<Lock>(table[25]);
    originalUnlock=reinterpret_cast<Unlock>(table[32]);
    set(25,reinterpret_cast<void*>(&lock));
    set(32,reinterpret_cast<void*>(&unlock));
  }
  ~NativeTransferFault() {
    armed=false;
    unlockTarget=nullptr;
    set(25,reinterpret_cast<void*>(originalLock));
    set(32,reinterpret_cast<void*>(originalUnlock));
  }
  void arm(DWORD flags,bool failUnlock) {
    selectedFlags=flags;
    atUnlock=failUnlock;
    armed=true;
    fired=false;
  }
  void expectFailure(const char* label,HRESULT hr) {
    const bool ok=fired && !armed && !unlockTarget && hr==DDERR_SURFACEBUSY;
    armed=false;
    unlockTarget=nullptr;
    std::cout<<label<<": injected="<<fired<<" result=0x"<<std::hex<<uint32_t(hr)<<std::dec<<'\n';
    if (!ok) ++failures;
  }
};

template<typename T,typename D>
void failReadbacks(T* target,IDirect3DViewport3* viewport,LONG height,NativeTransferFault& fault) {
  D3DRECT full{0,0,96,height};
  RECT region{8,8,24,24};
  for (bool unlock:{false,true}) {
    check("red before failed readback",viewport->Clear2(1,&full,D3DCLEAR_TARGET,0xffff0000,1.f,0));
    D desc{}; desc.dwSize=sizeof(desc);
    fault.arm(DDLOCK_WRITEONLY,unlock);
    HRESULT hr=target->Lock(&region,&desc,DDLOCK_READONLY|DDLOCK_WAIT,nullptr);
    if (SUCCEEDED(hr)) check("unexpected successful Lock cleanup",target->Unlock(nullptr));
    fault.expectFailure(unlock?"failed readback Unlock propagates":"failed readback Lock propagates",hr);
    expectPixels<T,D>("retry readback preserves GPU pixels",target,0xf800);

    check("green before failed GetDC",viewport->Clear2(1,&full,D3DCLEAR_TARGET,0xff00ff00,1.f,0));
    HDC dc=nullptr;
    fault.arm(DDLOCK_WRITEONLY,unlock);
    hr=target->GetDC(&dc);
    if (SUCCEEDED(hr)) check("unexpected successful DC cleanup",target->ReleaseDC(dc));
    fault.expectFailure("GetDC propagates readback failure",hr);
    expectPixels<T,D>("GetDC retry preserves GPU pixels",target,0x07e0);
  }
}

using CreateDDraw = HRESULT(WINAPI*)(GUID*,IDirectDraw**,IUnknown*);

template<typename T,typename D>
void failFullOverwrite(T* target,IDirect3DViewport3* viewport,LONG height) {
  D3DRECT full{0,0,96,height};
  check("prime green CPU mirror",viewport->Clear2(1,&full,D3DCLEAR_TARGET,0xff00ff00,1.f,0));
  expectPixels<T,D>("green CPU mirror",target,0x07e0);
  check("new red GPU image",viewport->Clear2(1,&full,D3DCLEAR_TARGET,0xffff0000,1.f,0));
  DDBLTFX invalid{}; // Invalid size makes the native fill fail before writing.
  const HRESULT hr=target->Blt(nullptr,nullptr,nullptr,DDBLT_COLORFILL|DDBLT_WAIT,&invalid);
  std::cout<<"invalid full fill result=0x"<<std::hex<<uint32_t(hr)<<std::dec<<'\n';
  if (SUCCEEDED(hr)) ++failures;
  expectPixels<T,D>("failed full fill retains authoritative GPU image",target,0xf800);
}

template<typename T,typename D>
void checkKeyedDestination(T* target,IUnknown* sprite,REFIID iid,IDirect3DViewport3* viewport,LONG height) {
  auto source=query<T>(sprite,iid);
  D3DRECT full{0,0,96,height};
  DDBLTFX prime{}; prime.dwSize=sizeof(prime); prime.dwFillColor=0x001f;
  check("prime keyed destination CPU pixels",target->Blt(nullptr,nullptr,nullptr,DDBLT_COLORFILL|DDBLT_WAIT,&prime));
  check("red GPU keyed destination",viewport->Clear2(1,&full,D3DCLEAR_TARGET,0xffff0000,1.f,0));
  check("keyed copy onto GPU image",target->Blt(nullptr,source.Get(),nullptr,DDBLT_KEYSRC|DDBLT_WAIT,nullptr));
  expectPixels<T,D>("keyed copy retains red GPU background",target,0xf800,{32,8,48,24});
  expectPixels<T,D>("keyed copy draws green source pixels",target,0x07e0);
}

void checkTransferFailures(CreateDDraw create,HWND window) {
  wchar_t system[MAX_PATH];
  if (!GetSystemDirectoryW(system,MAX_PATH)) throw std::runtime_error("GetSystemDirectoryW");
  std::wstring path=std::wstring(system)+L"\\ddraw.dll";
  HMODULE nativeModule=LoadLibraryW(path.c_str());
  if (!nativeModule) throw std::runtime_error("load native DirectDraw");
  auto nativeCreate=reinterpret_cast<CreateDDraw>(GetProcAddress(nativeModule,"DirectDrawCreate"));
  ComPtr<IDirectDraw> nativeDD;
  check("native create for fault fixture",nativeCreate(nullptr,nativeDD.GetAddressOf(),nullptr));
  check("native cooperative level",nativeDD->SetCooperativeLevel(window,DDSCL_NORMAL));
  DDSURFACEDESC nativeDesc{}; nativeDesc.dwSize=sizeof(nativeDesc);
  nativeDesc.dwFlags=DDSD_CAPS|DDSD_WIDTH|DDSD_HEIGHT|DDSD_PIXELFORMAT;
  nativeDesc.dwWidth=96; nativeDesc.dwHeight=64;
  nativeDesc.ddsCaps.dwCaps=DDSCAPS_SYSTEMMEMORY|DDSCAPS_OFFSCREENPLAIN;
  nativeDesc.ddpfPixelFormat={sizeof(DDPIXELFORMAT),DDPF_RGB,0,16,0xf800,0x7e0,0x1f,0};
  ComPtr<IDirectDrawSurface> nativeSurface;
  check("native fault fixture",nativeDD->CreateSurface(&nativeDesc,nativeSurface.GetAddressOf(),nullptr));
  NativeTransferFault fault(nativeSurface.Get());
  for (LONG height:{64,640}) {
    std::cout<<"Transfer failures, "<<height<<" rows\n";
    ComPtr<IDirectDraw> dd;
    check("create failure-test DirectDraw",create(nullptr,dd.GetAddressOf(),nullptr));
    auto dd4=query<IDirectDraw4>(dd.Get(),IID_IDirectDraw4);
    check("failure-test cooperative level",dd4->SetCooperativeLevel(window,DDSCL_NORMAL));
    DDSURFACEDESC2 desc{}; desc.dwSize=sizeof(desc);
    desc.dwFlags=nativeDesc.dwFlags;
    desc.dwWidth=96; desc.dwHeight=height;
    desc.ddsCaps.dwCaps=DDSCAPS_OFFSCREENPLAIN|DDSCAPS_3DDEVICE|DDSCAPS_VIDEOMEMORY;
    desc.ddpfPixelFormat=nativeDesc.ddpfPixelFormat;
    ComPtr<IDirectDrawSurface4> target;
    check("failure-test target",dd4->CreateSurface(&desc,target.GetAddressOf(),nullptr));
    auto d3d=query<IDirect3D3>(dd4.Get(),IID_IDirect3D3);
    ComPtr<IDirect3DDevice3> device;
    check("failure-test device",d3d->CreateDevice(IID_IDirect3DHALDevice,target.Get(),device.GetAddressOf(),nullptr));
    ComPtr<IDirect3DViewport3> viewport;
    check("failure-test viewport",d3d->CreateViewport(viewport.GetAddressOf(),nullptr));
    check("attach failure-test viewport",device->AddViewport(viewport.Get()));
    D3DVIEWPORT2 view{sizeof(view),0,0,96,DWORD(height),-1.f,1.f,2.f,2.f,0.f,1.f};
    check("failure-test viewport geometry",viewport->SetViewport2(&view));
    check("activate failure-test viewport",device->SetCurrentViewport(viewport.Get()));
    D3DRECT full{0,0,96,height},other{64,48,96,64};
    check("initial GPU pixels",viewport->Clear2(1,&full,D3DCLEAR_TARGET,0xffff0000,1.f,0));
    expectPixels<IDirectDrawSurface4,DDSURFACEDESC2>("warm CPU backing",target.Get(),0xf800);
    auto surface1=query<IDirectDrawSurface>(target.Get(),IID_IDirectDrawSurface);
    auto surface2=query<IDirectDrawSurface2>(target.Get(),IID_IDirectDrawSurface2);
    auto surface3=query<IDirectDrawSurface3>(target.Get(),IID_IDirectDrawSurface3);
    auto surface7=query<IDirectDrawSurface7>(target.Get(),IID_IDirectDrawSurface7);
    ComPtr<IDirectDrawSurface4> keyedSource;
    desc.ddsCaps.dwCaps=DDSCAPS_OFFSCREENPLAIN|DDSCAPS_SYSTEMMEMORY;
    check("create source-key fixture",dd4->CreateSurface(&desc,keyedSource.GetAddressOf(),nullptr));
    DDBLTFX keyFill{}; keyFill.dwSize=sizeof(keyFill); keyFill.dwFillColor=0xf81f;
    check("fill source-key fixture",keyedSource->Blt(nullptr,nullptr,nullptr,DDBLT_COLORFILL|DDBLT_WAIT,&keyFill));
    writePixels<IDirectDrawSurface4,DDSURFACEDESC2>(keyedSource.Get(),0x07e0);
    DDCOLORKEY key{0xf81f,0xf81f};
    check("set fixture source key",keyedSource->SetColorKey(DDCKEY_SRCBLT,&key));
    checkKeyedDestination<IDirectDrawSurface,DDSURFACEDESC>(surface1.Get(),keyedSource.Get(),IID_IDirectDrawSurface,viewport.Get(),height);
    checkKeyedDestination<IDirectDrawSurface2,DDSURFACEDESC>(surface2.Get(),keyedSource.Get(),IID_IDirectDrawSurface2,viewport.Get(),height);
    checkKeyedDestination<IDirectDrawSurface3,DDSURFACEDESC>(surface3.Get(),keyedSource.Get(),IID_IDirectDrawSurface3,viewport.Get(),height);
    checkKeyedDestination<IDirectDrawSurface4,DDSURFACEDESC2>(target.Get(),keyedSource.Get(),IID_IDirectDrawSurface4,viewport.Get(),height);
    checkKeyedDestination<IDirectDrawSurface7,DDSURFACEDESC2>(surface7.Get(),keyedSource.Get(),IID_IDirectDrawSurface7,viewport.Get(),height);
    failReadbacks<IDirectDrawSurface,DDSURFACEDESC>(surface1.Get(),viewport.Get(),height,fault);
    failReadbacks<IDirectDrawSurface2,DDSURFACEDESC>(surface2.Get(),viewport.Get(),height,fault);
    failReadbacks<IDirectDrawSurface3,DDSURFACEDESC>(surface3.Get(),viewport.Get(),height,fault);
    failReadbacks<IDirectDrawSurface4,DDSURFACEDESC2>(target.Get(),viewport.Get(),height,fault);
    failReadbacks<IDirectDrawSurface7,DDSURFACEDESC2>(surface7.Get(),viewport.Get(),height,fault);
    failFullOverwrite<IDirectDrawSurface,DDSURFACEDESC>(surface1.Get(),viewport.Get(),height);
    failFullOverwrite<IDirectDrawSurface2,DDSURFACEDESC>(surface2.Get(),viewport.Get(),height);
    failFullOverwrite<IDirectDrawSurface3,DDSURFACEDESC>(surface3.Get(),viewport.Get(),height);
    failFullOverwrite<IDirectDrawSurface4,DDSURFACEDESC2>(target.Get(),viewport.Get(),height);
    failFullOverwrite<IDirectDrawSurface7,DDSURFACEDESC2>(surface7.Get(),viewport.Get(),height);
    // On a tall surface, the first write owns only part of the CPU mirror.
    // GetDC needs the entire surface: it must upload those writes before
    // downloading the missing GPU pixels, and abort if that upload fails.
    if (height>256) for (bool unlock:{false,true}) {
      check("red before mixed transfer failure",viewport->Clear2(1,&full,D3DCLEAR_TARGET,0xffff0000,1.f,0));
      writePixels<IDirectDrawSurface4,DDSURFACEDESC2>(target.Get(),0x07e0);
      HDC dc=nullptr;
      fault.arm(DDLOCK_READONLY,unlock);
      HRESULT hr=surface7->GetDC(&dc);
      if (SUCCEEDED(hr)) check("mixed-transfer unexpected DC cleanup",surface7->ReleaseDC(dc));
      fault.expectFailure("full readback preserves pending writes on failure",hr);
      check("retry mixed-transfer DC",surface7->GetDC(&dc));
      check("release mixed-transfer DC",surface7->ReleaseDC(dc));
      expectPixels<IDirectDrawSurface4,DDSURFACEDESC2>("mixed-transfer retry retains green CPU write",target.Get(),0x07e0);
      expectPixels<IDirectDrawSurface4,DDSURFACEDESC2>("mixed-transfer retry retains red GPU pixels",target.Get(),0xf800,{64,500,80,516});
    }
    // A stretched blit can report a native Unlock failure after writing. The
    // wrapper must keep those CPU writes authoritative before returning it.
    auto scaleSource=query<IDirectDrawSurface>(keyedSource.Get(),IID_IDirectDrawSurface);
    RECT scaleFrom{8,8,24,24},scaleTo{8,8,40,40};
    DDBLTFX scaleFx{};scaleFx.dwSize=sizeof(scaleFx);scaleFx.dwROP=SRCCOPY;
    for (DWORD lockFlags:{DWORD(DDLOCK_READONLY),DWORD(DDLOCK_WRITEONLY)}) for (bool unlock:{false,true}) {
      check("red before stretch failure",viewport->Clear2(1,&full,D3DCLEAR_TARGET,0xffff0000,1.f,0));
      expectPixels<IDirectDrawSurface,DDSURFACEDESC>("warm stretch destination",surface1.Get(),0xf800);
      fault.arm(lockFlags,unlock);
      fault.expectFailure("stretch transfer failure propagates",surface1->Blt(&scaleTo,scaleSource.Get(),
        &scaleFrom,DDBLT_WAIT|DDBLT_KEYSRC|DDBLT_ROP,&scaleFx));
      check("GPU after failed stretch",viewport->Clear2(1,&other,D3DCLEAR_TARGET,0xff0000ff,1.f,0));
      expectPixels<IDirectDrawSurface,DDSURFACEDESC>("failed stretch preserves written or original pixels",
        surface1.Get(),unlock?0x07e0:0xf800);
      check("retry stretch",surface1->Blt(&scaleTo,scaleSource.Get(),&scaleFrom,DDBLT_WAIT|DDBLT_KEYSRC|DDBLT_ROP,&scaleFx));
      expectPixels<IDirectDrawSurface,DDSURFACEDESC>("retried stretch pixels",surface1.Get(),0x07e0);
    }
    for (bool unlock:{false,true}) {
      check("red before upload failure",viewport->Clear2(1,&full,D3DCLEAR_TARGET,0xffff0000,1.f,0));
      writePixels<IDirectDrawSurface4,DDSURFACEDESC2>(target.Get(),0x07e0);
      fault.arm(DDLOCK_READONLY,unlock);
      fault.expectFailure("partial clear propagates upload failure",viewport->Clear2(1,&other,D3DCLEAR_TARGET,0xff0000ff,1.f,0));
      check("retry partial GPU clear",viewport->Clear2(1,&other,D3DCLEAR_TARGET,0xff0000ff,1.f,0));
      expectPixels<IDirectDrawSurface4,DDSURFACEDESC2>("retry upload preserves CPU pixels",target.Get(),0x07e0);
      expectPixels<IDirectDrawSurface4,DDSURFACEDESC2>("retry GPU clear draws requested pixels",target.Get(),0x001f,{64,48,96,64});
    }
    check("detach failure-test viewport",device->DeleteViewport(viewport.Get()));
  }
}
