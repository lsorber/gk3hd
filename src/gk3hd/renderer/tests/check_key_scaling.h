// Stable fixed-16.16 pixel-center sampling is the fidelity contract. Native
// Windows stretching can give an original glyph and its exact 4x replica
// different footprints, so it is not a general fractional-scaling oracle.
std::vector<uint16_t> readRaster(IDirectDrawSurface4* surface) {
  DDSURFACEDESC2 desc{}; desc.dwSize=sizeof(desc);
  check("raster Lock",surface->Lock(nullptr,&desc,DDLOCK_READONLY|DDLOCK_WAIT,nullptr));
  std::vector<uint16_t> pixels(desc.dwWidth*desc.dwHeight);
  for (DWORD y=0;y<desc.dwHeight;++y)
    memcpy(pixels.data()+y*desc.dwWidth,static_cast<char*>(desc.lpSurface)+y*desc.lPitch,desc.dwWidth*2);
  check("raster Unlock",surface->Unlock(nullptr));
  return pixels;
}

uint16_t scalePattern(unsigned x,unsigned y) {
  return (x+y)%5==0 ? 0xf81f : uint16_t(((x&31)<<11)|((y&63)<<5)|((x^y)&31));
}

// Independent closed-form oracle, not the production row/column accumulator.
unsigned sampleCenter(unsigned offset,unsigned source,unsigned destination) {
  return unsigned((uint64_t(2*offset+1)*((uint64_t(source)*65536)/destination))/131072);
}

template<typename T>
void checkScalingInterface(REFIID iid,IDirectDrawSurface4* source,IDirectDrawSurface4* target4,
    IDirect3DDevice3* device,IDirect3DViewport3* viewport) {
  auto input=query<T>(source,iid),target=query<T>(target4,iid);
  struct Case { RECT src,dst; };
  const Case cases[]={{{0,0,32,32},{3,3,33,33}},{{8,8,40,40},{3,3,33,33}},
    {{0,0,8,8},{3,3,33,33}},{{0,0,16,16},{3,3,63,63}},
    {{4,4,44,44},{7,7,44,44}},{{8,8,56,56},{3,3,48,48}},
    {{0,0,7,7},{1,1,27,27}},{{2,2,10,10},{2,2,34,34}},
    {{2,2,34,34},{2,2,34,34}},{{0,0,64,48},{7,7,67,52}},
    {{0,0,12,17},{3,3,36,50}},{{0,0,48,68},{3,3,36,50}}};
  unsigned tests=0,wrongTotal=0;
  for (const auto& item:cases) for (bool keyed:{false,true}) for (bool rop:{false,true}) {
    const auto sw=item.src.right-item.src.left,sh=item.src.bottom-item.src.top;
    const auto dw=item.dst.right-item.dst.left,dh=item.dst.bottom-item.dst.top;
    std::vector<uint16_t> expected(96*64,0x001f);
    for (LONG y=0;y<dh;++y) for (LONG x=0;x<dw;++x) {
      const auto pixel=scalePattern(item.src.left+sampleCenter(x,sw,dw),item.src.top+sampleCenter(y,sh,dh));
      if (!keyed || pixel!=0xf81f) expected[(item.dst.top+y)*96+item.dst.left+x]=pixel;
    }
    D3DRECT full{0,0,96,64};
    check("begin scaling frame",device->BeginScene());
    check("end scaling frame",device->EndScene());
    check("GPU scaling background",viewport->Clear2(1,&full,D3DCLEAR_TARGET,0xff0000ff,1.f,0));
    DDBLTFX fx{};fx.dwSize=sizeof(fx);fx.dwROP=SRCCOPY;
    RECT dst=item.dst,src=item.src;
    check("fractional scaling",target->Blt(&dst,input.Get(),&src,
      DDBLT_WAIT|(keyed?DDBLT_KEYSRC:0)|(rop?DDBLT_ROP:0),rop?&fx:nullptr));
    // Force retained CPU pixels through an upload/readback as well.
    D3DRECT outside{92,60,96,64};
    check("scaled copy GPU roundtrip",viewport->Clear2(1,&outside,D3DCLEAR_TARGET,0xff0000ff,1.f,0));
    const auto actual=readRaster(target4);
    unsigned wrong=0;
    for (unsigned i=0;i<actual.size();++i) wrong+=actual[i]!=expected[i];
    if (wrong) std::cout<<"scale case "<<tests<<": "<<wrong<<" incorrect pixels\n";
    wrongTotal+=wrong;++tests;
  }
  std::cout<<tests<<" keyed/unkeyed/ROP scales: "<<wrongTotal<<" incorrect pixels\n";
  if (wrongTotal) ++failures;
}

template<typename T>
void checkReplicaScaling(REFIID iid,IDirectDrawSurface4* source,IDirectDrawSurface4* target4) {
  auto input=query<T>(source,iid),target=query<T>(target4,iid);
  // Synthetic 12x17 glyph and its exact 4x replica, in disjoint atlas cells.
  // The 33x47 destination reproduces an actual status ratio without assets.
  DDBLTFX fx{};fx.dwSize=sizeof(fx);fx.dwFillColor=0x001f;fx.dwROP=SRCCOPY;
  RECT dst{3,3,36,50},original{0,0,12,17},replica{16,0,64,68};
  check("original glyph background",target->Blt(nullptr,nullptr,nullptr,DDBLT_COLORFILL|DDBLT_WAIT,&fx));
  check("original glyph stretch",target->Blt(&dst,input.Get(),&original,DDBLT_WAIT|DDBLT_KEYSRC|DDBLT_ROP,&fx));
  auto expected=readRaster(target4);
  check("replica glyph background",target->Blt(nullptr,nullptr,nullptr,DDBLT_COLORFILL|DDBLT_WAIT,&fx));
  check("replica glyph stretch",target->Blt(&dst,input.Get(),&replica,DDBLT_WAIT|DDBLT_KEYSRC|DDBLT_ROP,&fx));
  if (expected!=readRaster(target4)) {std::cout<<"exact 4x replica changes glyph footprint\n";++failures;}
}

template<typename T>
void checkClippedStretch(REFIID iid,IDirectDrawSurface4* source,IDirectDrawSurface4* target4,
    IDirectDrawClipper* clipper,const std::vector<uint16_t>& expected) {
  auto input=query<T>(source,iid),target=query<T>(target4,iid);
  DDBLTFX fill{};fill.dwSize=sizeof(fill);fill.dwFillColor=0x001f;
  check("clipped stretch background",target->Blt(nullptr,nullptr,nullptr,DDBLT_COLORFILL|DDBLT_WAIT,&fill));
  check("stretch clipper",target->SetClipper(clipper));
  RECT src{0,0,32,32},dst{3,3,33,33};
  check("clipped stretch",target->Blt(&dst,input.Get(),&src,DDBLT_WAIT|DDBLT_KEYSRC,nullptr));
  check("detach stretch clipper",target->SetClipper(nullptr));
  if (readRaster(target4)!=expected) {std::cout<<"clipped stretch differs from native fallback\n";++failures;}
}

void checkStretchFallback(IDirectDraw4* dd,IDirectDrawSurface4* source,IDirectDrawSurface4* target4) {
  wchar_t system[MAX_PATH];
  if (!GetSystemDirectoryW(system,MAX_PATH)) throw std::runtime_error("GetSystemDirectoryW");
  const std::wstring path=std::wstring(system)+L"\\ddraw.dll";
  auto module=LoadLibraryW(path.c_str());
  if (!module) throw std::runtime_error("native stretch module");
  auto create=reinterpret_cast<CreateDDraw>(GetProcAddress(module,"DirectDrawCreate"));
  if (!create) throw std::runtime_error("native stretch export");
  ComPtr<IDirectDraw> native;
  check("native stretch DirectDraw",create(nullptr,native.GetAddressOf(),nullptr));
  check("native stretch cooperative level",native->SetCooperativeLevel(nullptr,DDSCL_NORMAL));
  auto native4=query<IDirectDraw4>(native.Get(),IID_IDirectDraw4);
  DDSURFACEDESC2 desc{};desc.dwSize=sizeof(desc);
  check("stretch fallback descriptor",source->GetSurfaceDesc(&desc));
  ComPtr<IDirectDrawSurface4> input,output;
  check("native fallback input",native4->CreateSurface(&desc,input.GetAddressOf(),nullptr));
  DDSURFACEDESC2 map{};map.dwSize=sizeof(map);
  check("native fallback raster",input->Lock(nullptr,&map,DDLOCK_WRITEONLY|DDLOCK_WAIT,nullptr));
  for (unsigned y=0;y<96;++y) for (unsigned x=0;x<96;++x)
    reinterpret_cast<uint16_t*>(static_cast<char*>(map.lpSurface)+y*map.lPitch)[x]=scalePattern(x,y);
  check("native fallback Unlock",input->Unlock(nullptr));
  DDCOLORKEY key{0xf81f,0xf81f};check("native fallback key",input->SetColorKey(DDCKEY_SRCBLT,&key));
  desc.dwHeight=64;
  check("native fallback output",native4->CreateSurface(&desc,output.GetAddressOf(),nullptr));
  struct {RGNDATAHEADER header;RECT rect;} clipData{};
  clipData.header={sizeof(RGNDATAHEADER),RDH_RECTANGLES,1,sizeof(RECT),{13,10,31,29}};
  clipData.rect=clipData.header.rcBound;
  ComPtr<IDirectDrawClipper> nativeClip,wrappedClip;
  check("native clipper",native4->CreateClipper(0,nativeClip.GetAddressOf(),nullptr));
  check("wrapped clipper",dd->CreateClipper(0,wrappedClip.GetAddressOf(),nullptr));
  for (auto clip:{nativeClip.Get(),wrappedClip.Get()})
    check("stretch clipping list",clip->SetClipList(reinterpret_cast<RGNDATA*>(&clipData),0));
  DDBLTFX fill{};fill.dwSize=sizeof(fill);fill.dwFillColor=0x001f;
  check("native clipped background",output->Blt(nullptr,nullptr,nullptr,DDBLT_COLORFILL|DDBLT_WAIT,&fill));
  check("native clipped target",output->SetClipper(nativeClip.Get()));
  RECT src{0,0,32,32},dst{3,3,33,33};
  check("native clipped reference",output->Blt(&dst,input.Get(),&src,DDBLT_WAIT|DDBLT_KEYSRC,nullptr));
  const auto expected=readRaster(output.Get());
#define CHECK_CLIPPED(T) checkClippedStretch<T>(IID_##T,source,target4,wrappedClip.Get(),expected)
  CHECK_CLIPPED(IDirectDrawSurface);CHECK_CLIPPED(IDirectDrawSurface2);CHECK_CLIPPED(IDirectDrawSurface3);
  CHECK_CLIPPED(IDirectDrawSurface4);CHECK_CLIPPED(IDirectDrawSurface7);
#undef CHECK_CLIPPED
}

void checkKeyScaling(IDirectDraw4* dd,IDirect3DDevice3* device,IDirect3DViewport3* viewport,
                     IDirectDrawSurface*,IDirectDrawSurface4* target4) {
  DDSURFACEDESC2 desc{};desc.dwSize=sizeof(desc);
  desc.dwFlags=DDSD_WIDTH|DDSD_HEIGHT|DDSD_CAPS|DDSD_PIXELFORMAT;
  desc.dwWidth=96;desc.dwHeight=96;
  desc.ddsCaps.dwCaps=DDSCAPS_OFFSCREENPLAIN|DDSCAPS_SYSTEMMEMORY;
  desc.ddpfPixelFormat={sizeof(DDPIXELFORMAT),DDPF_RGB,0,16,0xf800,0x7e0,0x1f,0};
  ComPtr<IDirectDrawSurface4> source;
  check("create scaling source",dd->CreateSurface(&desc,source.GetAddressOf(),nullptr));
  DDSURFACEDESC2 mapped{};mapped.dwSize=sizeof(mapped);
  check("initialize scaling raster",source->Lock(nullptr,&mapped,DDLOCK_WRITEONLY|DDLOCK_WAIT,nullptr));
  for (unsigned y=0;y<96;++y) for (unsigned x=0;x<96;++x)
    reinterpret_cast<uint16_t*>(static_cast<char*>(mapped.lpSurface)+y*mapped.lPitch)[x]=scalePattern(x,y);
  check("scaling raster Unlock",source->Unlock(nullptr));
  DDCOLORKEY key{0xf81f,0xf81f};
  check("scaling source key",source->SetColorKey(DDCKEY_SRCBLT,&key));
#define CHECK_SCALE(T) checkScalingInterface<T>(IID_##T,source.Get(),target4,device,viewport)
  CHECK_SCALE(IDirectDrawSurface);CHECK_SCALE(IDirectDrawSurface2);CHECK_SCALE(IDirectDrawSurface3);
  CHECK_SCALE(IDirectDrawSurface4);CHECK_SCALE(IDirectDrawSurface7);
#undef CHECK_SCALE
  checkStretchFallback(dd,source.Get(),target4);
  check("initialize exact replica",source->Lock(nullptr,&mapped,DDLOCK_WRITEONLY|DDLOCK_WAIT,nullptr));
  for (unsigned y=0;y<68;++y) for (unsigned x=0;x<48;++x)
    reinterpret_cast<uint16_t*>(static_cast<char*>(mapped.lpSurface)+y*mapped.lPitch)[16+x]=scalePattern(x/4,y/4);
  check("replica Unlock",source->Unlock(nullptr));
#define CHECK_REPLICA(T) checkReplicaScaling<T>(IID_##T,source.Get(),target4)
  CHECK_REPLICA(IDirectDrawSurface);CHECK_REPLICA(IDirectDrawSurface2);CHECK_REPLICA(IDirectDrawSurface3);
  CHECK_REPLICA(IDirectDrawSurface4);CHECK_REPLICA(IDirectDrawSurface7);
#undef CHECK_REPLICA
}
