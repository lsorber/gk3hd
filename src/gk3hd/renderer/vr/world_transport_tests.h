#pragma once

// Included by the GPU transport fixture after its common assertion helpers.
// Real legacy draws provide the reference, including the ordinary draw between
// submitted batches and another ordinary draw after the scenery scope ends.
void testPreparedWorld(IDirectDraw4* dd, IDirect3DDevice3* device,
                       IDirect3DViewport3* viewport, SceneBridge bridge, Pixels pixels,
                       Bridge world, bool color32) {
  using namespace world_bridge;
  struct Vertex { float x,y,z,u,v; };
  struct Geometry {
    IDirect3DDevice3* device;
    IDirect3DViewport3* viewport;
    Bridge world;
    IDirectDraw4* ownerDD;
    std::vector<Vertex> vertices;
    std::vector<uint16_t> indices;
    uint64_t generation = 1;
    unsigned rejections = 0, submissions = 0, retained = 0;
    unsigned targetCancels = 0;
    bool cancel = false, reuse = false, replacement = false;
    static int32_t GK3HD_XR_CALL draw(void* context, unsigned, const EyeCamera* camera) {
      return static_cast<Geometry*>(context)->paint(*camera, false);
    }
    static int32_t GK3HD_XR_CALL shared(void* context, const EyeCamera* source, const EyeCamera*) {
      return static_cast<Geometry*>(context)->paint(*source, true);
    }
    HRESULT operation(Operation phase, const void* input = nullptr) {
      return world(device,uint32_t(phase),const_cast<void*>(input));
    }
    void begin() {
      Request request{};
      request.bytes=sizeof(request);request.version=1;request.geometryKey=generation;
      request.vertices=vertices.data();request.vertexCount=uint32_t(vertices.size());
      request.indices=indices.data();request.indexCount=uint32_t(indices.size());
      require(operation(Operation::Begin,&request)==S_OK,"begin prepared scenery");
    }
    void submit(unsigned expected) {
      Result result{sizeof(Result),0,0,0};
      check(operation(Operation::Submit,&result),"submit prepared scenery");
      require(result.draws==expected,"rejected row leaked into scenery submission");
      ++submissions;
    }
    int32_t paint(const EyeCamera& camera, bool prepared) {
      for (const auto& state:std::array<std::pair<D3DRENDERSTATETYPE,DWORD>,8>{{
          {D3DRENDERSTATE_ZENABLE,TRUE},{D3DRENDERSTATE_ZWRITEENABLE,TRUE},
          {D3DRENDERSTATE_ZFUNC,D3DCMP_LESSEQUAL},{D3DRENDERSTATE_CULLMODE,D3DCULL_CCW},
          {D3DRENDERSTATE_LIGHTING,FALSE},{D3DRENDERSTATE_FOGENABLE,FALSE},
          {D3DRENDERSTATE_ALPHATESTENABLE,FALSE},{D3DRENDERSTATE_ALPHABLENDENABLE,FALSE}}})
        check(device->SetRenderState(state.first,state.second),"prepared scenery state");
      check(device->BeginScene(),"begin prepared scene");
      D3DRECT area{0,0,camera.camera.width,camera.camera.height};
      check(viewport->Clear2(1,&area,D3DCLEAR_TARGET|D3DCLEAR_ZBUFFER,0xff203040,1.f,0),"clear prepared scene");
      if (prepared) begin();
      struct NativeVertex { float x,y,z,rhw;DWORD color;float u,v,lu,lv; };
      constexpr std::array<DWORD,4> materialColors{0xff104020,0xff602010,0xff102060,0xff603060};
      auto ordinary = [&](unsigned item, DWORD color = 0, unsigned indexCount = 6) {
        if(!color)color=materialColors[item];
        std::array<NativeVertex,4> native{};
        for (unsigned corner=0;corner<4;++corner) {
          const auto& vertex=vertices[item*4+corner];
          const auto screen=engineScreenPoint(camera.projection,
            engineCameraPoint(camera.camera,{vertex.x,vertex.y,vertex.z}));
          native[corner]={screen[0],screen[1],screen[2],screen[3],color,vertex.u,vertex.v,0,0};
        }
        WORD order[]{0,2,1,2,3,1};
        check(device->DrawIndexedPrimitive(D3DPT_TRIANGLELIST,D3DFVF_XYZRHW|D3DFVF_DIFFUSE|D3DFVF_TEX2,
          native.data(),4,order,indexCount,0),"ordinary scenery draw");
      };
      for (unsigned item=0;item<3;++item) {
       // More than two 32-draw boundaries, with changing materials on
       // overlapping geometry. The last equal-depth draw must win exactly as
       // on the independent ordinary path, including its material identity.
       const unsigned repetitions=item==0?(replacement?2u:65u):1u;
       for(unsigned repeat=0;repeat<repetitions;++repeat) {
        const DWORD color=item==0&&repeat%2==0?materialColors[3]:materialColors[item];
        const unsigned indexCount=replacement&&item==0&&repeat==1?3u:6u;
        if (!prepared) {ordinary(item,color,indexCount);continue;}
        Draw draw{sizeof(Draw),item*6,indexCount,color,{0,0,1,1},1};
        HRESULT result=S_FALSE;
        if (reuse&&item!=1) {
          result=operation(Operation::AppendPrepared,&draw);
          if (result==S_OK) ++retained;
        }
        // The unsupported middle item must not be appended. Submit preceding
        // work, draw it through the untouched legacy path once, then resume.
        if (result==S_FALSE) {
          if (item==1) draw.uniform=2;
          result=operation(Operation::Append,&draw);
        }
        if (result==S_FALSE) {
          require(item==1,"supported scenery unexpectedly rejected");
          ++rejections;submit(replacement?2:65);ordinary(item);begin();
        } else check(result,"append prepared scenery");
       }
      }
      if (prepared) {
        if (cancel) {
          ComPtr<IDirectDrawSurface4> originalTarget,alternate;
          check(device->GetRenderTarget(originalTarget.GetAddressOf()),"get target before cancellation");
          DDSURFACEDESC2 current{};current.dwSize=sizeof(current);
          check(originalTarget->GetSurfaceDesc(&current),"get cancellation target format");
          DDSURFACEDESC2 changed{};changed.dwSize=sizeof(changed);
          changed.dwFlags=DDSD_WIDTH|DDSD_HEIGHT|DDSD_CAPS|DDSD_PIXELFORMAT;
          changed.dwWidth=current.dwWidth;changed.dwHeight=current.dwHeight;changed.ddpfPixelFormat=current.ddpfPixelFormat;
          changed.ddsCaps.dwCaps=DDSCAPS_OFFSCREENPLAIN|DDSCAPS_3DDEVICE;
          check(ownerDD->CreateSurface(&changed,alternate.GetAddressOf(),nullptr),"create alternate cancellation target");
          check(device->SetRenderTarget(alternate.Get(),0),"change target before cancellation");
          check(operation(Operation::Cancel),"cancel prepared scenery after target change");
          ++targetCancels;
          check(device->SetRenderTarget(originalTarget.Get(),0),"restore target after cancellation");
          check(device->EndScene(),"end cancelled scenery");
          return E_FAIL;
        }
        submit(1);
      }
      // Later ordinary drawing must survive the custom pipeline. This is a
      // separate visible foreground marker, not a fabricated sky acceptance.
      ordinary(3);
      check(device->EndScene(),"end prepared scene");
      return S_OK;
    }
  } geometry{device,viewport,world,dd};
  for (unsigned item=0;item<4;++item) {
    const float rx=item==0?35.f:item==1?3.f:item==2?1.f:.35f;
    const float ry=item==0?35.f:item==1?4.f:item==2?2.f:.5f;
    const float z=item==0?25.f:item==1?15.f:item==2?10.f:7.f;
    const auto base=uint16_t(geometry.vertices.size());
    for (unsigned corner=0;corner<4;++corner)
      geometry.vertices.push_back({corner%2?rx:-rx,corner/2?ry:-ry,z,float(corner%2),float(corner/2)});
    for (unsigned corner:{0u,2u,1u,2u,3u,1u}) geometry.indices.push_back(uint16_t(base+corner));
  }
  DDSURFACEDESC2 desc{};desc.dwSize=sizeof(desc);
  desc.dwFlags=DDSD_WIDTH|DDSD_HEIGHT|DDSD_CAPS|DDSD_PIXELFORMAT;desc.dwWidth=desc.dwHeight=1;
  desc.ddsCaps.dwCaps=DDSCAPS_TEXTURE|DDSCAPS_VIDEOMEMORY;
  desc.ddpfPixelFormat={sizeof(DDPIXELFORMAT),DDPF_RGB|DDPF_ALPHAPIXELS,0,32,0xff0000,0xff00,0xff,0xff000000};
  ComPtr<IDirectDrawSurface4> surface;
  check(dd->CreateSurface(&desc,surface.GetAddressOf(),nullptr),"create scenery texture");
  DDSURFACEDESC2 locked{};locked.dwSize=sizeof(locked);
  check(surface->Lock(nullptr,&locked,DDLOCK_WAIT,nullptr),"lock scenery texture");
  *static_cast<DWORD*>(locked.lpSurface)=0xffffffff;
  check(surface->Unlock(nullptr),"unlock scenery texture");
  ComPtr<IDirect3DTexture2> texture;
  check(surface->QueryInterface(IID_IDirect3DTexture2,reinterpret_cast<void**>(texture.GetAddressOf())),"query scenery texture");
  check(device->SetTexture(0,texture.Get()),"bind scenery texture");
  for (const auto& state:std::array<std::pair<D3DTEXTURESTAGESTATETYPE,DWORD>,13>{{
      {D3DTSS_COLOROP,D3DTOP_MODULATE2X},{D3DTSS_COLORARG1,D3DTA_TEXTURE},
      {D3DTSS_COLORARG2,D3DTA_DIFFUSE},{D3DTSS_ALPHAOP,D3DTOP_SELECTARG1},
      {D3DTSS_ALPHAARG1,D3DTA_TEXTURE},{D3DTSS_ADDRESSU,D3DTADDRESS_WRAP},
      {D3DTSS_ADDRESSV,D3DTADDRESS_WRAP},{D3DTSS_MAGFILTER,D3DTFG_ANISOTROPIC},
      {D3DTSS_MINFILTER,D3DTFN_ANISOTROPIC},{D3DTSS_MIPFILTER,D3DTFP_LINEAR},
      {D3DTSS_MAXANISOTROPY,16},{D3DTSS_MIPMAPLODBIAS,0},{D3DTSS_TEXCOORDINDEX,0}}})
    check(device->SetTextureStageState(0,state.first,state.second),"configure scenery material");
  check(device->SetTextureStageState(1,D3DTSS_COLOROP,D3DTOP_DISABLE),"disable scenery light map");
  SceneV1 request{};request.width=request.height=128;request.unitsPerMeter=40;
  request.camera.worldToCamera={1,0,0,0,1,0,0,0,1,0,0,0};
  request.camera.planes[0].distance=-2;request.camera.planes[1].distance=24000;
  request.context=&geometry;request.draw=Geometry::draw;
  std::vector<uint8_t> previous(256u*256*4);
  uint32_t frame=pixels(0,previous.data(),uint32_t(previous.size()));
  require(frame!=0,"prepared fixture requires an existing submitted reference");
  auto capture = [&]() {
    ++frame;
    std::array<std::vector<uint8_t>,2> output;
    for (unsigned eye=0;eye<2;++eye) {
      output[eye].resize(256u*256*4);
      require(pixels(eye,output[eye].data(),uint32_t(output[eye].size()))==frame,"fresh prepared output");
    }
    return output;
  };
  check(bridge(device,&request),"ordinary prepared-world reference");
  auto reference=capture();
  auto compare = [&](const std::array<std::vector<uint8_t>,2>& output) {
    for (unsigned eye=0;eye<2;++eye) {
      unsigned different=0, drawn=0;
      for (size_t offset=0;offset<reference[eye].size();offset+=4) {
        bool mismatch=false;
        for (unsigned channel=0;channel<4;++channel) {
          unsigned expected=output[eye][offset+channel];
          unsigned observed=reference[eye][offset+channel];
          if (!color32&&channel<3) {
            // Compare the exact stored RGB565 codes. Drivers can expand those
            // codes differently by one 8-bit value during native readback.
            const unsigned bits=channel==1?6:5;
            expected>>=8-bits;observed>>=8-bits;
          }
          mismatch=mismatch||observed!=expected;
        }
        different+=mismatch;
        drawn+=reference[eye][offset+1]>64;
      }
      std::cout<<"Prepared-world eye "<<eye<<" mismatches="<<different<<" drawn="<<drawn<<'\n';
      if (different>16) {
        const auto stamp=std::to_string(GetTickCount64())+"-"+std::to_string(eye);
        auto save=[&](const char* kind,const std::vector<uint8_t>& image) {
          std::ofstream file(std::string("prepared-")+kind+"-"+stamp+".ppm",std::ios::binary);
          file<<"P6\n256 256\n255\n";
          for (size_t offset=0;offset<image.size();offset+=4)
            file.write(reinterpret_cast<const char*>(&image[offset]),3);
        };
        save("reference",reference[eye]);save("candidate",output[eye]);
      }
      require(drawn>1000,"reference geometry was culled or absent");
      require(different<=16,"prepared-world pixels differ from ordinary draws");
    }
  };
  request.sharedDraw=Geometry::shared;
  check(bridge(device,&request),"mixed prepared-world rendering");compare(capture());
  require(geometry.rejections==1&&geometry.submissions==2,"mixed ordered path not exercised");
  geometry.reuse=true;
  check(bridge(device,&request),"retained prepared-world rendering");compare(capture());
  require(geometry.retained==66,"prepared material cache not exercised");
  geometry.cancel=true;
  require(FAILED(bridge(device,&request)),"cancelled prepared world submitted");
  require(geometry.targetCancels==1,"cancellation was blocked by changed render target");
  geometry.cancel=false;request.sharedDraw=nullptr;
  check(bridge(device,&request),"ordinary recovery after prepared cancellation");
  require(capture()==reference,"prepared cancellation leaked into ordinary rendering");
  for (unsigned corner=0;corner<4;++corner) geometry.vertices[8+corner].x+=2.2f;
  check(bridge(device,&request),"ordinary changed-geometry reference");
  const auto changed=capture();
  require(changed!=reference,"geometry replacement did not change visible output");
  reference=changed;
  ++geometry.generation;
  geometry.retained=0;request.sharedDraw=Geometry::shared;
  check(bridge(device,&request),"prepared generation replacement");compare(capture());
  // Each new generation misses its first material, then may legitimately
  // reuse that freshly established material for the remaining 64 equal-shape
  // draws in this same frame. The other geometry must also be rebuilt.
  require(geometry.retained==64,"prepared generation replacement reused stale materials or lost current-frame reuse");
  // Capture one geometry twice before finalization. The later material
  // covers only one triangle, so the earlier version must remain visible in
  // the other half; storing mutable cache-row aliases cannot pass this oracle.
  geometry.replacement=true;geometry.reuse=false;request.sharedDraw=nullptr;
  check(bridge(device,&request),"ordinary partial material replacement reference");
  reference=capture();
  request.sharedDraw=Geometry::shared;
  check(bridge(device,&request),"prepared immutable material replacement");compare(capture());
  std::cout<<"Prepared-row immutable replacement passed: earlier full material plus later partial geometry\n";
  check(device->SetTexture(0,nullptr),"retire scenery texture");
  std::cout<<"Prepared-world GPU passed: real pixels, ordered rejection/resume, later native draws, retained materials, cancellation and generation replacement\n";
}
