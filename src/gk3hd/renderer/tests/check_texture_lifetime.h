// A bound Texture2 must keep its parent alive, even after all application refs
// are released. Private wrapper refs alone used to permit parent memory reuse.
void checkBoundTextureLifetime(IDirectDraw4* dd4,IDirect3DDevice3* device) {
  for(DWORD stage=0;stage<8;++stage) {
    DDSURFACEDESC2 desc{};desc.dwSize=sizeof(desc);
    desc.dwFlags=DDSD_WIDTH|DDSD_HEIGHT|DDSD_CAPS|DDSD_PIXELFORMAT;
    desc.dwWidth=32;desc.dwHeight=32;
    desc.ddsCaps.dwCaps=DDSCAPS_TEXTURE|DDSCAPS_VIDEOMEMORY;
    desc.ddpfPixelFormat={sizeof(DDPIXELFORMAT),DDPF_RGB,0,16,0xf800,0x7e0,0x1f,0};
    ComPtr<IDirectDrawSurface4> surface;
    check("lifetime surface",dd4->CreateSurface(&desc,surface.GetAddressOf(),nullptr));
    writePixels<IDirectDrawSurface4,DDSURFACEDESC2>(surface.Get(),0x07e0);
    auto texture=query<IDirect3DTexture2>(surface.Get(),IID_IDirect3DTexture2);
    const ULONG before=surface->AddRef();surface->Release();
    check("lifetime bind",device->SetTexture(stage,texture.Get()));
    const ULONG after=surface->AddRef();surface->Release();
    if(before!=after) throw std::runtime_error("binding changed public surface refcount");
    // Exercise the same-binding assignment too, without leaking a parent ref.
    check("lifetime self bind",device->SetTexture(stage,texture.Get()));
    texture.Reset();surface.Reset();
    std::vector<ComPtr<IDirectDrawSurface4>> churn;
    desc.dwWidth=64;desc.dwHeight=64;
    for(unsigned i=0;i<32;++i) {
      ComPtr<IDirectDrawSurface4> other;
      check("lifetime churn",dd4->CreateSurface(&desc,other.GetAddressOf(),nullptr));
      churn.push_back(std::move(other));
    }
    ComPtr<IDirect3DTexture2> bound;
    check("get retained binding",device->GetTexture(stage,bound.GetAddressOf()));
    auto retained=query<IDirectDrawSurface4>(bound.Get(),IID_IDirectDrawSurface4);
    DDSURFACEDESC2 actual{};actual.dwSize=sizeof(actual);
    check("retained parent dimensions",retained->GetSurfaceDesc(&actual));
    if(actual.dwWidth!=32 || actual.dwHeight!=32)
      throw std::runtime_error("bound texture parent was replaced by recycled surface memory");
    expectPixels<IDirectDrawSurface4,DDSURFACEDESC2>("retained bound texture pixels",retained.Get(),0x07e0);
    bound.Reset();retained.Reset();
    check("lifetime unbind",device->SetTexture(stage,nullptr));
    check("get empty binding",device->GetTexture(stage,bound.GetAddressOf()));
    if(bound) throw std::runtime_error("unbinding retained a texture");
  }
}
