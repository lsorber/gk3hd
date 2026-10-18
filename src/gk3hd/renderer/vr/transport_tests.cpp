#define NOMINMAX
#include <windows.h>
#include <ddraw.h>
#include <d3d.h>
#include <wrl/client.h>

#include "frame_bridge.h"
#include "scene.h"
#include "panel_bridge.h"
#include "overlay.h"
#include "keyboard.h"

#include <array>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;
using namespace gk3hd::vr;
using Bridge = HRESULT (WINAPI*)(IDirect3DDevice3*, uint32_t, void*);
using SceneBridge = HRESULT (WINAPI*)(IDirect3DDevice3*, const SceneV1*);
using Pixels = uint32_t (WINAPI*)(unsigned, uint8_t*, uint32_t);
using TestInput = uint32_t (WINAPI*)(uint32_t, uint32_t, uint32_t, float, float);
using PanelPixels = uint32_t (WINAPI*)(uint8_t*, uint32_t, float*);
using TestAim = uint32_t (WINAPI*)(uint32_t, float, float, float);
using FrameStats = uint32_t (WINAPI*)(uint64_t*, uint32_t);
using MainWaits = uint32_t (WINAPI*)();
using TextBridge = HRESULT (WINAPI*)(IDirect3DDevice3*, TextFrame*);

namespace {
void require(bool value, const char* reason) { if (!value) throw std::runtime_error(reason); }
void check(HRESULT value, const char* reason) {
  if (FAILED(value)) {
    std::cerr << reason << ": 0x" << std::hex << uint32_t(value) << std::dec << '\n';
    throw std::runtime_error(reason);
  }
}
constexpr std::array<D3DCOLOR, 4> colors{0xff804020, 0xff208040, 0xff402080, 0xff808080};

struct SceneDraws {
  IDirect3DDevice3* device;
  IDirect3DViewport3* viewport;
  std::vector<EyeCamera> cameras;
  int failEye = -1;
  float depth = 1.f;
  int32_t pickKind = 2;
  unsigned queries = 0;
  bool clearDepth = true;
  bool detailPixel = false;
  bool quadrants = false;
  static int32_t GK3HD_XR_CALL draw(void* context, unsigned eye, const EyeCamera* camera) {
    auto& state = *static_cast<SceneDraws*>(context);
    if (eye != state.cameras.size() || !camera) return E_INVALIDARG;
    state.cameras.push_back(*camera);
    if (int(eye) == state.failEye) return E_FAIL;
    HRESULT result = state.device->BeginScene();
    if (FAILED(result)) return result;
    D3DRECT area{0, 0, camera->camera.width, camera->camera.height};
    result = state.viewport->Clear2(1, &area,
      D3DCLEAR_TARGET | (state.clearDepth ? D3DCLEAR_ZBUFFER : 0), colors[eye], state.depth, 0);
    if (SUCCEEDED(result) && state.quadrants) {
      for (unsigned quarter = 0; quarter < 4 && SUCCEEDED(result); ++quarter) {
        const auto width = camera->camera.width, height = camera->camera.height;
        const LONG x = LONG(quarter%2)*width/2, y = LONG(quarter/2)*height/2;
        D3DRECT part{x,y,x+width/2,y+height/2};
        result = state.viewport->Clear2(1,&part,D3DCLEAR_TARGET,colors[(quarter+eye)%4],1.f,0);
      }
    }
    if (SUCCEEDED(result) && state.detailPixel) {
      D3DRECT pixel{camera->camera.width - 1, camera->camera.height - 1,
                    camera->camera.width, camera->camera.height};
      result = state.viewport->Clear2(1, &pixel, D3DCLEAR_TARGET, colors[3], 1.f, 0);
    }
    const auto ended = state.device->EndScene();
    return FAILED(result) ? result : ended;
  }
  static int32_t GK3HD_XR_CALL pick(void* context, unsigned hand, const EngineAimRay* ray,
                                   XrVector3f* hit) {
    auto& state = *static_cast<SceneDraws*>(context);
    require(hand == 0 && state.cameras.empty(), "GPU query was stale or after an eye draw");
    ++state.queries;
    *hit = {ray->origin.x, ray->origin.y, ray->origin.z + 10.f};
    return state.pickKind;
  }
};

void testNativeTransforms(IDirect3DDevice3* device, IDirect3DViewport3* viewport,
                          IDirectDrawSurface4* target) {
  const std::array<D3DTRANSFORMSTATETYPE,3> types{
    D3DTRANSFORMSTATE_WORLD,D3DTRANSFORMSTATE_VIEW,D3DTRANSFORMSTATE_PROJECTION};
  std::array<D3DMATRIX,3> saved{};
  for (size_t i=0;i<types.size();++i) check(device->GetTransform(types[i],&saved[i]),"save native transform");
  const std::array<D3DRENDERSTATETYPE,5> states{D3DRENDERSTATE_CULLMODE,
    D3DRENDERSTATE_ZENABLE,D3DRENDERSTATE_FOGENABLE,D3DRENDERSTATE_ALPHABLENDENABLE,
    D3DRENDERSTATE_ALPHATESTENABLE};
  std::array<DWORD,states.size()> savedStates{};
  for(size_t i=0;i<states.size();++i) check(device->GetRenderState(states[i],&savedStates[i]),"save draw state");
  check(device->SetTexture(0,nullptr),"clear native transform texture");
  check(device->SetRenderState(D3DRENDERSTATE_CULLMODE,D3DCULL_NONE),"disable transform culling");
  for (size_t i=1;i<states.size();++i) check(device->SetRenderState(states[i],FALSE),"disable draw state");
  D3DMATRIX identity{};
  identity._11=identity._22=identity._33=identity._44=1.f;
  auto world=identity,view=identity,projection=identity;
  struct Vertex { float x,y,z; DWORD color; };
  std::array<Vertex,6> vertices{{{-.5f,-.5f,.5f,0xff806040},{.5f,-.5f,.5f,0xff806040},
    {.5f,.5f,.5f,0xff806040},{-.5f,-.5f,.5f,0xff806040},
    {.5f,.5f,.5f,0xff806040},{-.5f,.5f,.5f,0xff806040}}};
  for(unsigned phase=0;phase<4;++phase) {
    if(phase==1) world._41=.75f;
    if(phase==2) view._41=-.75f;
    if(phase==3) projection._11=.5f;
    const std::array<D3DMATRIX,3> values{world,view,projection};
    // Repeated equal writes still produce the current transform, while later
    // changes and reversals must update the shader's real GPU-visible state.
    for(unsigned repeat=0;repeat<32;++repeat) for(size_t i=0;i<types.size();++i) {
      check(device->SetTransform(types[i],const_cast<D3DMATRIX*>(&values[i])),"set native transform");
      D3DMATRIX observed{};
      check(device->GetTransform(types[i],&observed),"read native transform");
      require(!std::memcmp(&observed,&values[i],sizeof(observed)),"native transform readback changed");
    }
    D3DRECT area{0,0,128,128};
    check(device->BeginScene(),"begin transformed GPU draw");
    check(viewport->Clear2(1,&area,D3DCLEAR_TARGET,0xff000000,1.f,0),"clear transformed target");
    check(device->DrawPrimitive(D3DPT_TRIANGLELIST,D3DFVF_XYZ|D3DFVF_DIFFUSE,
      vertices.data(),DWORD(vertices.size()),D3DDP_DONOTLIGHT|D3DDP_DONOTCLIP),"draw transformed vertices");
    check(device->EndScene(),"end transformed GPU draw");
    DDSURFACEDESC2 desc{};desc.dwSize=sizeof(desc);
    check(target->Lock(nullptr,&desc,DDLOCK_READONLY|DDLOCK_WAIT,nullptr),"read transformed pixels");
    auto lit=[&](unsigned x,unsigned y) {
      const auto* p=static_cast<const uint8_t*>(desc.lpSurface)+y*desc.lPitch+x*(desc.ddpfPixelFormat.dwRGBBitCount/8);
      uint32_t value=0;std::memcpy(&value,p,desc.ddpfPixelFormat.dwRGBBitCount/8);
      return (value & (desc.ddpfPixelFormat.dwRBitMask|desc.ddpfPixelFormat.dwGBitMask|desc.ddpfPixelFormat.dwBBitMask))!=0;
    };
    const bool center=lit(64,64),left=lit(40,64);
    check(target->Unlock(nullptr),"unlock transformed pixels");
    require(center==(phase!=1),"changed world/view transform did not reach GPU");
    require(left==(phase==0||phase==2),"changed projection transform did not reach GPU");
  }
  for(size_t i=0;i<types.size();++i) check(device->SetTransform(types[i],&saved[i]),"restore native transform");
  for(size_t i=0;i<states.size();++i) check(device->SetRenderState(states[i],savedStates[i]),"restore draw state");
  std::cout<<"Native GPU transforms passed: repeated writes, world/view changes and projection changes\n";
}

void testReticle(IDirect3DDevice3* device, IDirect3DViewport3* viewport,
                 SceneBridge bridge, Pixels pixels, TestInput input, TestAim aim) {
  SceneDraws draws{device, viewport, {}, -1};
  SceneV1 request{};
  request.unitsPerMeter = 40; request.width = request.height = 128;
  request.camera.worldToCamera = {1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0};
  request.camera.planes[0].distance = -2; request.camera.planes[1].distance = 24000;
  request.context = &draws; request.draw = SceneDraws::draw; request.pick = SceneDraws::pick;
  WorldTargetV1 target{}; request.target = &target;
  require(input(0, 3, 0, 0, 0) && input(1, 0, 0, 0, 0) && aim(0, 0, 0, 0),
          "prepare fresh tracked reticle input");
  const std::array<D3DRENDERSTATETYPE, 9> states{D3DRENDERSTATE_ZWRITEENABLE,
    D3DRENDERSTATE_ZFUNC, D3DRENDERSTATE_CULLMODE, D3DRENDERSTATE_FOGENABLE,
    D3DRENDERSTATE_ALPHATESTENABLE, D3DRENDERSTATE_ALPHABLENDENABLE, D3DRENDERSTATE_FILLMODE,
    D3DRENDERSTATE_SRCBLEND, D3DRENDERSTATE_DESTBLEND};
  std::array<DWORD, states.size()> saved{};
  std::array<unsigned, 2> unoccludedBeam{};
  for (size_t i = 0; i < states.size(); ++i) check(device->GetRenderState(states[i], &saved[i]), "save legacy state");
  for (unsigned phase = 0; phase < 5; ++phase) {
    draws.cameras.clear(); draws.queries = 0;
    draws.depth = phase == 1 ? .5f : 1.f;
    draws.pickKind = phase == 2 ? SceneWorldMiss : phase == 4 ? 0 : 2;
    if (phase == 3) require(input(0, 1, 0, 0, 0), "lose reticle tracking");
    if (phase == 4) require(input(0, 3, 0, 0, 0), "restore pointer tracking");
    require(bridge(device, &request) == S_OK, "GPU reticle scene failed");
    require(draws.queries == (phase == 3 ? 0u : 1u), "reticle resampled between eyes or queried lost tracking");
    require(target.kind == (phase >= 2 ? 0u : 2u), "reticle target completion disagrees");
    std::array<double, 2> centers{};
    for (unsigned eye = 0; eye < 2; ++eye) {
      std::vector<uint8_t> capture(256*256*4);
      require(pixels(eye, capture.data(), uint32_t(capture.size())), "capture reticle eye");
      unsigned count = 0, beamCount = 0;
      for (size_t i = 0; i < capture.size(); i += 4) {
        // The private eye target renders directly at the runtime's 256px size.
        // Count blended marker pixels too, not only full-coverage orange.
        if (capture[i] >= 180 && capture[i+1] >= 120 && capture[i+1] <= 210 && capture[i+2] <= 90) {
          ++count; centers[eye] += double((i/4)%256);
        }
        const unsigned blue = colors[eye] & 255u;
        if (capture[i+2] > blue+40 && capture[i+2] > capture[i]+25) ++beamCount;
      }
      if (phase == 0 ? count == 0 : count != 0)
        std::cerr << "reticle phase " << phase << " eye " << eye << " pixels " << count
                  << " hit " << target.point.x << ',' << target.point.y << ',' << target.point.z << '\n';
      require(phase == 0 ? count > 0 : count == 0,
              "reticle missing, ignored scene depth, or survived a miss/tracking loss");
      if (phase == 0) unoccludedBeam[eye] = beamCount;
      std::cerr << "pointer phase " << phase << " eye " << eye << " ring " << count
                << " beam " << beamCount << '\n';
      if (phase == 1)
        require(beamCount < unoccludedBeam[eye], "beam behind geometry ignored scene depth");
      else
        require(phase == 0 || phase == 2 ? beamCount > 0 : beamCount == 0,
                "beam missing or survived lost ownership/tracking");
      if (count) centers[eye] /= count;
    }
    if (phase == 0) require(centers[0] > centers[1], "reticle has no binocular disparity");
    for (size_t i = 0; i < states.size(); ++i) {
      DWORD value = 0; check(device->GetRenderState(states[i], &value), "read restored legacy state");
      require(value == saved[i], "reticle leaked renderer state into the game");
    }
  }
  require(input(0, 0, 0, 0, 0), "clear reticle fixture input");
}

HRESULT CALLBACK depthFormat(DDPIXELFORMAT* format, void* context) {
  *static_cast<DDPIXELFORMAT*>(context) = *format;
  return D3DENUMRET_CANCEL;
}

void testScene(IDirect3DDevice3* device, IDirect3DViewport3* viewport,
               SceneBridge bridge, Pixels pixels) {
  ComPtr<IDirectDrawSurface4> desktop;
  check(device->GetRenderTarget(desktop.GetAddressOf()), "get desktop target before stereo");
  auto desktopPixels = [&] {
    DDSURFACEDESC2 locked{}; locked.dwSize = sizeof(locked);
    check(desktop->Lock(nullptr, &locked, DDLOCK_READONLY | DDLOCK_WAIT, nullptr),
          "read desktop target around stereo");
    const size_t row = locked.dwWidth * (locked.ddpfPixelFormat.dwRGBBitCount / 8);
    std::vector<uint8_t> image(row * locked.dwHeight);
    for (unsigned y = 0; y < locked.dwHeight; ++y)
      std::memcpy(image.data() + row*y, static_cast<uint8_t*>(locked.lpSurface) + locked.lPitch*y, row);
    check(desktop->Unlock(nullptr), "unlock desktop after stereo read");
    return image;
  };
  const auto untouched = desktopPixels();
  SceneDraws draws{device, viewport, {}, -1};
  SceneV1 request{};
  request.unitsPerMeter = 40;
  request.width = request.height = 128;
  request.camera.worldToCamera = {1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0};
  request.camera.planes[0].distance = -2;
  request.camera.planes[1].distance = 24000;
  request.draw = SceneDraws::draw;
  request.context = &draws;
  const auto saved = request.camera;
  request.size = 0;
  require(FAILED(bridge(device, &request)), "unversioned scene request accepted");
  require(draws.cameras.empty(), "invalid request reached engine draw callback");
  request.size = sizeof(request);
  // A failed second eye must not publish a partial image pair. Subsequent
  // frames must still be playable, without restarting the device or runtime.
  draws.failEye = 1;
  require(FAILED(bridge(device, &request)), "engine draw failure was ignored");
  require(desktopPixels() == untouched, "failed eye draw overwrote the desktop image");
  std::array<std::vector<uint8_t>, 2> captures;
  for (unsigned eye = 0; eye < 2; ++eye) {
    captures[eye].resize(256 * 256 * 4);
    require(pixels(eye, captures[eye].data(), uint32_t(captures[eye].size())) == 3,
      "failed scene submitted a partial frame");
  }
  for (unsigned frame = 0; frame < 2; ++frame) {
    draws.failEye = -1; draws.cameras.clear();
    draws.detailPixel = frame == 1;
    request.flags = frame ? 1 : 0; // Explicit recenter also retains binocular separation.
    require(bridge(device, &request) == S_OK, "scene could not recover and submit stereo");
    require(draws.cameras.size() == 2, "scene did not draw both engine eyes");
    for (const auto& camera : draws.cameras)
      require(camera.camera.width == 256 && camera.camera.height == 256,
              "runtime eye size replaced with desktop dimensions");
    require(std::abs(draws.cameras[0].camera.position.x + 1.28f) < .0001f &&
            std::abs(draws.cameras[1].camera.position.x - 1.28f) < .0001f,
      "native scene lost runtime eye separation or calibrated world scale");
    require(std::memcmp(&saved, &request.camera, sizeof(saved)) == 0,
      "scene modified the authored game camera");
    for (unsigned eye = 0; eye < 2; ++eye) {
      auto& output = captures[eye];
      require(pixels(eye, output.data(), uint32_t(output.size())) == 4 + frame,
        "scene did not submit one layer per engine transaction");
      for (size_t offset = 0; offset < output.size(); offset += 4) {
        for (unsigned channel = 0; channel < 3; ++channel) {
          const auto color = draws.detailPixel && offset == output.size() - 4 ? colors[3] : colors[eye];
          const int expected = (color >> (16 - 8 * channel)) & 255;
          require(std::abs(int(output[offset + channel]) - expected) <= 7,
            "scene callback pixels did not reach the correct XR eye");
        }
        require(output[offset + 3] == 255, "scene eye is not opaque");
      }
    }
    require(desktopPixels() == untouched, "eye draw overwrote the desktop image");
  }
}

void testCachedNativeDrawState(IDirect3DDevice3* device, IDirect3DViewport3* viewport,
                               SceneBridge bridge, Pixels pixels) {
  struct Draw {
    IDirect3DDevice3* device; IDirect3DViewport3* viewport;
    bool blendCached = false;
    static int32_t GK3HD_XR_CALL run(void* context, unsigned, const EyeCamera* camera) {
      auto& state = *static_cast<Draw*>(context);
      check(state.device->BeginScene(), "begin cached native draw");
      D3DRECT area{0,0,camera->camera.width,camera->camera.height};
      check(state.viewport->Clear2(1,&area,D3DCLEAR_TARGET,0xff804020,1.f,0), "clear cached native draw");
      // Emulate the engine's write-eliding render-state cache across eyes and
      // frames. A bridge must not restore an old GPU blend state behind it.
      if (!state.blendCached) {
        check(state.device->SetRenderState(D3DRENDERSTATE_ALPHABLENDENABLE,TRUE), "enable cached native blend");
        state.blendCached = true;
      }
      struct Vertex { float x,y,z,rhw; DWORD color; };
      const float left=camera->camera.width*.25f, right=camera->camera.width*.75f;
      const float top=camera->camera.height*.25f, bottom=camera->camera.height*.75f;
      std::array<Vertex,4> vertices{{{left,top,.5f,1,0x40000000},{right,top,.5f,1,0x40000000},
                                   {right,bottom,.5f,1,0x40000000},{left,bottom,.5f,1,0x40000000}}};
      check(state.device->DrawPrimitive(D3DPT_TRIANGLEFAN,D3DFVF_XYZRHW|D3DFVF_DIFFUSE,
            vertices.data(),uint32_t(vertices.size()),0), "draw cached native shadow");
      check(state.device->EndScene(), "end cached native draw");
      return S_OK;
    }
  } draws{device,viewport};
  const std::array<D3DRENDERSTATETYPE,8> states{D3DRENDERSTATE_ZENABLE,D3DRENDERSTATE_CULLMODE,
    D3DRENDERSTATE_FOGENABLE,D3DRENDERSTATE_ALPHATESTENABLE,D3DRENDERSTATE_ALPHABLENDENABLE,
    D3DRENDERSTATE_SRCBLEND,D3DRENDERSTATE_DESTBLEND,D3DRENDERSTATE_FILLMODE};
  std::array<DWORD,states.size()> saved{};
  for(size_t i=0;i<states.size();++i) check(device->GetRenderState(states[i],&saved[i]),"save cached-draw state");
  const std::array<DWORD,states.size()> values{FALSE,D3DCULL_NONE,FALSE,FALSE,FALSE,
                                             D3DBLEND_SRCALPHA,D3DBLEND_INVSRCALPHA,D3DFILL_SOLID};
  for(size_t i=0;i<states.size();++i) check(device->SetRenderState(states[i],values[i]),"set cached-draw state");
  check(device->SetTexture(0,nullptr),"clear cached-draw texture");
  check(device->SetTextureStageState(0,D3DTSS_COLOROP,D3DTOP_SELECTARG1),"set cached color operation");
  check(device->SetTextureStageState(0,D3DTSS_COLORARG1,D3DTA_DIFFUSE),"set cached color source");
  check(device->SetTextureStageState(0,D3DTSS_ALPHAOP,D3DTOP_SELECTARG1),"set cached alpha operation");
  check(device->SetTextureStageState(0,D3DTSS_ALPHAARG1,D3DTA_DIFFUSE),"set cached alpha source");
  SceneV1 request{};request.width=request.height=128;request.unitsPerMeter=40;
  request.camera.worldToCamera={1,0,0,0,1,0,0,0,1,0,0,0};
  request.camera.planes[0].distance=-2;request.camera.planes[1].distance=24000;
  request.draw=Draw::run;request.context=&draws;
  for(unsigned frame=0;frame<3;++frame) {
    require(bridge(device,&request)==S_OK,"cached native state scene failed");
    for(unsigned eye=0;eye<2;++eye) {
      std::vector<uint8_t> capture(256*256*4);
      require(pixels(eye,capture.data(),uint32_t(capture.size())),"capture cached native state eye");
      const size_t center=(128*256+128)*4;
      const std::array<int,3> expected{96,48,24};
      for(unsigned channel=0;channel<3;++channel)
        require(std::abs(int(capture[center+channel])-expected[channel])<=8,
                "eye state restoration desynchronized the native blend cache");
    }
  }
  for(size_t i=0;i<states.size();++i) check(device->SetRenderState(states[i],saved[i]),"restore cached-draw state");
}

void testSceneMirror(IDirectDraw4* dd, IDirect3DDevice3* device, IDirect3DViewport3* viewport,
                     SceneBridge bridge) {
  ComPtr<IDirectDrawSurface4> original;
  check(device->GetRenderTarget(original.GetAddressOf()),"retain original mirror target");
  auto read = [](IDirectDrawSurface4* surface) {
    DDSURFACEDESC2 locked{}; locked.dwSize = sizeof(locked);
    check(surface->Lock(nullptr,&locked,DDLOCK_READONLY|DDLOCK_WAIT,nullptr),"lock current mirror");
    const auto bytes = locked.ddpfPixelFormat.dwRGBBitCount/8;
    std::vector<uint32_t> image(size_t(locked.dwWidth)*locked.dwHeight);
    for (uint32_t y=0;y<locked.dwHeight;++y) for (uint32_t x=0;x<locked.dwWidth;++x) {
      uint32_t value=0;
      std::memcpy(&value,static_cast<const uint8_t*>(locked.lpSurface)+size_t(y)*locked.lPitch+size_t(x)*bytes,bytes);
      image[size_t(y)*locked.dwWidth+x]=value;
    }
    check(surface->Unlock(nullptr),"unlock current mirror"); return image;
  };
  for (const auto& size : std::array<std::array<uint32_t,2>,3>{{{128,128},{192,96},{96,192}}}) {
    DDSURFACEDESC2 desc{}; desc.dwSize=sizeof(desc);
    check(original->GetSurfaceDesc(&desc),"read native mirror format");
    desc.dwFlags=DDSD_WIDTH|DDSD_HEIGHT|DDSD_CAPS|DDSD_PIXELFORMAT;
    desc.dwWidth=size[0]; desc.dwHeight=size[1]; desc.ddsCaps={};
    // A plain offscreen surface is mapped to the implicit legacy backbuffer
    // when attached to a device. Use a genuine independently sized 3D target.
    desc.ddsCaps.dwCaps=DDSCAPS_3DDEVICE;
    ComPtr<IDirectDrawSurface4> target, preview;
    check(dd->CreateSurface(&desc,target.GetAddressOf(),nullptr),"create independent mirror canvas");
    check(dd->CreateSurface(&desc,preview.GetAddressOf(),nullptr),"create native save-preview copy");
    check(device->SetRenderTarget(target.Get(),0),"bind independent mirror canvas");
    DDBLTFX fill{}; fill.dwSize=sizeof(fill); fill.dwFillColor=0;
    check(target->Blt(nullptr,nullptr,nullptr,DDBLT_COLORFILL|DDBLT_WAIT,&fill),"prime old mirror bytes");
    const auto old=read(target.Get()); // Materialize the CPU cache before GPU replacement.
    ComPtr<IDirectDrawGammaControl> gamma;
    check(target->QueryInterface(IID_IDirectDrawGammaControl,
      reinterpret_cast<void**>(gamma.GetAddressOf())),"query mirror presentation gamma");
    DDGAMMARAMP ramp{};
    for (unsigned i=0;i<256;++i) ramp.red[i]=ramp.green[i]=ramp.blue[i]=WORD(std::pow(double(i)/255,1.5)*65535);
    check(gamma->SetGammaRamp(0,&ramp),"apply non-neutral mirror presentation gamma");
    SceneDraws draws{device,viewport,{},1}; draws.quadrants=true; draws.clearDepth=false;
    SceneV1 scene{}; scene.flags=SceneMirror; scene.unitsPerMeter=40;
    scene.width=size[0]; scene.height=size[1];
    scene.camera.worldToCamera={1,0,0,0,1,0,0,0,1,0,0,0};
    scene.camera.planes[0].distance=-2; scene.camera.planes[1].distance=24000;
    scene.draw=SceneDraws::draw; scene.context=&draws;
    require(FAILED(bridge(device,&scene)),"partial eye pair accepted for mirror");
    require(read(target.Get())==old,"failed second eye replaced mirror pixels");
    draws.failEye=-1; draws.cameras.clear();
    require(bridge(device,&scene)==S_OK,"completed eye pair could not mirror");
    const auto image=read(target.Get());
    for (unsigned quarter=0;quarter<4;++quarter) {
      const auto x=(quarter%2)*size[0]/2+size[0]/4, y=(quarter/2)*size[1]/2+size[1]/4;
      const auto value=image[size_t(y)*size[0]+x];
      const std::array<DWORD,3> masks{desc.ddpfPixelFormat.dwRBitMask,desc.ddpfPixelFormat.dwGBitMask,desc.ddpfPixelFormat.dwBBitMask};
      for (unsigned channel=0;channel<3;++channel) {
        DWORD mask=masks[channel]; unsigned shift=0; while (!(mask&1)) { mask>>=1; ++shift; }
        const int actual=int(((value&masks[channel])>>shift)*255/mask);
        const int expected=int((colors[quarter]>>(16-8*channel))&255);
        require(std::abs(actual-expected)<=8,"mirror pixels came from wrong eye, stale cache or gamma-adjusted image");
      }
    }
    ComPtr<IDirectDrawSurface4> restored;
    check(device->GetRenderTarget(restored.GetAddressOf()),"get restored mirror target");
    require(restored.Get()==target.Get(),"mirroring retained a private eye render target");
    check(preview->Blt(nullptr,target.Get(),nullptr,DDBLT_WAIT,nullptr),"copy mirror to native preview");
    require(read(preview.Get())==image,"native preview copied stale pre-mirror pixels");
    draws.failEye=1; draws.cameras.clear();
    require(FAILED(bridge(device,&scene)),"failed later eye pair accepted");
    require(read(target.Get())==image,"failed later frame replaced last valid mirror");
    draws.failEye=-1; draws.cameras.clear(); ++scene.width;
    require(FAILED(bridge(device,&scene)),"mismatched mirror canvas accepted");
    require(read(target.Get())==image,"mismatched mirror canvas changed desktop pixels");
    --scene.width; draws.cameras.clear();
    require(bridge(device,&scene)==S_OK,"mirror could not recover after invalid canvas");
    require(read(target.Get())==image,"recovered mirror changed expected source pixels");
    for (unsigned i=0;i<256;++i) ramp.red[i]=ramp.green[i]=ramp.blue[i]=WORD(i*257);
    check(gamma->SetGammaRamp(0,&ramp),"restore neutral mirror gamma");
    check(device->SetRenderTarget(original.Get(),0),"restore original native target");
  }
}

void testTransitions(IDirectDraw4* dd, IDirectDrawSurface4* target, IDirect3DDevice3* device,
                     IDirect3DViewport3* viewport, SceneBridge scene, Pixels pixels) {
  ComPtr<IDirectDrawGammaControl> gamma;
  check(target->QueryInterface(IID_IDirectDrawGammaControl,
        reinterpret_cast<void**>(gamma.GetAddressOf())), "query transition gamma");
  DDSURFACEDESC2 desc{}; desc.dwSize = sizeof(desc);
  check(target->GetSurfaceDesc(&desc), "get transition canvas format");
  desc.dwFlags = DDSD_WIDTH | DDSD_HEIGHT | DDSD_CAPS | DDSD_PIXELFORMAT;
  desc.dwWidth = desc.dwHeight = 256;
  desc.ddsCaps = {}; desc.ddsCaps.dwCaps = DDSCAPS_3DDEVICE | DDSCAPS_OFFSCREENPLAIN;
  ComPtr<IDirectDrawSurface4> sameSize;
  check(dd->CreateSurface(&desc, sameSize.GetAddressOf(), nullptr), "create 1:1 transition canvas");
  SceneDraws draws{device, viewport, {}, -1};
  draws.clearDepth = false; // The 1:1 color-only fixture has no depth attachment.
  SceneV1 world{}; world.unitsPerMeter = 40;
  world.camera.worldToCamera = {1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0};
  world.camera.planes[0].distance = -2; world.camera.planes[1].distance = 24000;
  world.context = &draws; world.draw = SceneDraws::draw;
  WorldInputV1 output{}; world.worldInput = &output;
  for (const bool copy : {false, true}) {
    world.width = world.height = copy ? 256 : 128;
    if (copy) check(device->SetRenderTarget(sameSize.Get(), 0), "bind 1:1 transition canvas");
    D3DVIEWPORT2 view{}; view.dwSize = sizeof(view);
    view.dwWidth = view.dwHeight = world.width;
    view.dvClipX = -1; view.dvClipY = 1; view.dvClipWidth = view.dvClipHeight = 2;
    view.dvMinZ = 0; view.dvMaxZ = 1;
    check(viewport->SetViewport2(&view), "set transition viewport");
    for (const bool corrected : {false, true}) {
      DDGAMMARAMP ramp{};
      for (unsigned i = 0; i < 256; ++i) {
        const double x = double(i)/255;
        ramp.red[i] = ramp.green[i] = ramp.blue[i] =
          WORD(std::lround((corrected ? .1+.8*x*x : x)*65535));
      }
      check(gamma->SetGammaRamp(0, &ramp), "set transition brightness");
      world.camera.position.x += 40; // Every variant is a new authored cut.
      for (unsigned frame = 0; frame <= 20; ++frame) {
        draws.cameras.clear();
        require(scene(device, &world) == S_OK, "camera transition stopped XR submission");
        const double p = std::min(double(frame)*11111111/200000000, 1.);
        const double gain = p*p*(3-2*p);
        require(gain == 1 || !output.rayMask, "obscured GPU frame retained world selection");
        for (unsigned eye = 0; eye < 2; ++eye) {
          std::vector<uint8_t> image(256*256*4);
          require(pixels(eye, image.data(), uint32_t(image.size())), "capture camera fade");
          for (size_t offset = 0; offset < image.size(); offset += 4) {
            for (unsigned c = 0; c < 3; ++c) {
              const unsigned source = (colors[eye] >> (16-8*c)) & 255;
              const int expected = int(std::lround(double(ramp.red[source])*255/65535*gain));
              if (std::abs(int(image[offset+c])-expected) > 7)
                std::cerr << "transition copy=" << copy << " corrected=" << corrected
                          << " frame=" << frame << " eye=" << eye << " channel=" << c
                          << " offset=" << offset << " actual=" << int(image[offset+c])
                          << " expected=" << expected << '\n';
              require(std::abs(int(image[offset+c])-expected) <= 7,
                      "camera fade skipped, doubled gamma or differs between eyes");
            }
            require(image[offset+3] == 255, "world fade made the projection translucent");
          }
        }
      }
    }
  }
  check(device->SetRenderTarget(target, 0), "restore transition canvas");
  DDGAMMARAMP neutral{};
  for (unsigned i = 0; i < 256; ++i) neutral.red[i] = neutral.green[i] = neutral.blue[i] = WORD(i*257);
  check(gamma->SetGammaRamp(0, &neutral), "restore transition brightness");
  std::cout << "XR camera cuts passed: opaque black, timed stereo fade, neutral/corrected gamma, 1:1/scaled copies\n";
}

void testShared(IDirect3DDevice3* device, IDirect3DViewport3* viewport, SceneBridge scene,
                Bridge panel, Bridge raw, Pixels pixels, PanelPixels panelPixels, TestInput input,
                FrameStats stats, MainWaits mainWaits) {
  auto counters = [&] {
    std::array<uint64_t, 5> values{};
    require(stats(values.data(), uint32_t(values.size())) != 0, "read test frame counters");
    return values;
  };
  SceneDraws draws{device, viewport, {}, -1};
  SceneV1 world{};
  world.unitsPerMeter = 40; world.width = world.height = 128;
  world.camera.worldToCamera = {1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0};
  world.camera.planes[0].distance = -2; world.camera.planes[1].distance = 24000;
  world.draw = SceneDraws::draw; world.context = &draws; world.flags = SceneDeferred;
  WorldInputV1 worldInput{};
  world.worldInput = &worldInput;
  PanelFrame ui{}; ui.canvasWidth = ui.canvasHeight = 128;
  auto drawWorld = [&] { draws.cameras.clear(); return scene(device, &world); };
  auto present = [&] { return panel(device, uint32_t(PanelOperation::Present), &ui); };
  auto close = [&] { return panel(device, uint32_t(PanelOperation::Close), nullptr); };
  require(input(0, 3, 0, 0, 0), "neutralize controller before shared frame");
  require(drawWorld() == S_OK && close() == S_OK, "prime shared controller actions");
  const auto before = counters();
  require(input(0, 3, Select, 0, 0), "press select before world draw");
  require(drawWorld() == S_OK, "deferred world failed");
  require(worldInput.rayMask == 1 && worldInput.input.hands[0].pressed == Select &&
          worldInput.input.hands[0].held == Select,
          "renderer did not export its focused predicted world input");
  require(counters()[2] == before[2] && counters()[0] == before[0]+1,
          "world submitted before completed UI");
  FrameViews diagnostic{};
  require(FAILED(raw(device, uint32_t(FrameOperation::Begin), &diagnostic)) &&
          FAILED(raw(device, uint32_t(FrameOperation::Cancel), nullptr)),
          "raw diagnostic bridge stole the shared frame");
  require(input(0, 3, Menu, 0, 0), "change input between world and UI hooks");
  check(device->BeginScene(), "begin completed UI draw");
  D3DRECT area{0, 0, 128, 128};
  check(viewport->Clear2(1, &area, D3DCLEAR_TARGET, colors[3], 1.f, 0), "draw completed UI color");
  check(device->EndScene(), "end completed UI draw");
  require(present() == S_OK, "world and panel could not share frame");
  const auto after = counters();
  require(after[0] == before[0]+1 && after[1] == before[1]+1 &&
          after[2] == before[2]+1 && after[3] == before[3]+1 && after[4] == 2,
          "combined frame did not sync once and submit two layers together");
  require(ui.input.hands[0].pressed == Select && ui.input.hands[0].held == Select,
          "panel used a different controller snapshot from its world");
  require(std::memcmp(&worldInput.input, &ui.input, sizeof(ui.input)) == 0,
          "world ray and panel input were sampled at different times");
  std::vector<uint8_t> output(256*256*4);
  for (unsigned eye = 0; eye < 2; ++eye) {
    require(pixels(eye, output.data(), uint32_t(output.size())) == after[2], "shared eye submission missing");
    for (size_t i = 0; i < output.size(); i += 4)
      for (unsigned c = 0; c < 3; ++c)
        require(std::abs(int(output[i+c])-int((colors[eye]>>(16-8*c))&255)) <= 7,
                "completed UI overwrote a previously rendered eye");
  }
  std::array<float, 9> geometry{};
  output.resize(128*128*4);
  require(panelPixels(output.data(), uint32_t(output.size()), geometry.data()) == after[3],
          "shared panel capture missing");
  for (size_t i = 0; i < 128*128*4; i += 4)
    require(output[i] >= 121 && output[i] <= 135, "shared panel lost completed UI pixels");
  require(close() == S_OK && counters() == after, "repeated finalizer submitted another frame");
  require(present() == S_OK && ui.input.hands[0].pressed == Menu && counters()[4] == 1,
          "panel-only frame did not consume the next controller edge");
  const auto panelOnly = counters();
  require(drawWorld() == S_OK && close() == S_OK && counters()[4] == 1 &&
          counters()[2] == panelOnly[2]+1 && counters()[3] == panelOnly[3],
          "panel closure did not finalize world-only frame");
  const auto valid = counters();
  require(drawWorld() == S_OK, "draw before invalid panel");
  ui.canvasWidth = 127;
  require(FAILED(present()) && counters()[2] == valid[2] && counters()[4] == 0,
          "invalid UI submitted or stranded a pending world");
  ui.canvasWidth = 128;
  require(drawWorld() == S_OK && FAILED(drawWorld()) && counters()[4] == 0,
          "duplicate world draw was not cancelled");
  require(drawWorld() == S_OK && present() == S_OK && counters()[4] == 2,
          "shared frame could not recover after cancellation");
  const auto beforeWorld = counters();
  require(drawWorld() == S_OK, "draw world-only snapshot");
  const auto sampledWorld = worldInput.input;
  require(input(0, 3, Inventory, .4f, .2f), "change physical input after world-only sample");
  require(panel(device, uint32_t(PanelOperation::World), &ui) == S_OK,
          "world-only finalizer failed");
  require(std::memcmp(&sampledWorld, &ui.input, sizeof(ui.input)) == 0,
          "world-only finalizer lost its predicted controller snapshot");
  require(!ui.pointer.flags && !ui.geometry.size[0] && counters()[4] == 1,
          "world-only finalizer submitted an opaque panel or manufactured a panel hit");
  require(counters()[0] == beforeWorld[0]+1 && counters()[3] == beforeWorld[3],
          "world-only finalizer began another frame or captured UI");
  const auto completedWorld = counters();
  require(panel(device, uint32_t(PanelOperation::World), &ui) == S_FALSE &&
          counters() == completedWorld && !ui.input.flags && !ui.pointer.held,
          "empty world finalizer began a frame or resurrected stale input");
  const auto beforeBlank = counters();
  require(panel(device, uint32_t(PanelOperation::Blank), nullptr) == S_OK &&
          counters()[0] == beforeBlank[0]+1 && counters()[4] == 0 &&
          counters()[2] == beforeBlank[2] && counters()[3] == beforeBlank[3],
          "idle scene teardown did not submit a layerless frame without capturing game pixels");
  require(drawWorld() == S_OK, "draw outgoing world before teardown");
  const auto pendingBlank = counters();
  require(panel(device, uint32_t(PanelOperation::Blank), nullptr) == S_OK &&
          counters()[0] == pendingBlank[0] && counters()[4] == 0 &&
          counters()[2] == pendingBlank[2] && counters()[3] == pendingBlank[3],
          "teardown resampled or submitted the outgoing world/UI");
  require(drawWorld() == S_OK && present() == S_OK && counters()[4] == 2,
          "normal stereo and UI could not recover after a loading clear");
  const auto beforeLoading = counters();
  require(panel(device, uint32_t(PanelOperation::Loading), nullptr) == S_OK,
          "loading frame owner did not start");
  const auto initialMainWaits = mainWaits();
  for (unsigned boundary = 0; boundary < 4; ++boundary) {
    require(panel(device, uint32_t(PanelOperation::Loading), nullptr) == S_OK &&
            close() == S_OK && mainWaits() == initialMainWaits,
            "nested loading or empty UI finalization interrupted the loading frame owner");
  }
  Sleep(20);
  // A requested blank frame joins the loading owner. Empty Close must not stop
  // its coverage before the next actual frame. Observe ordinary counters only
  // after the join: those test-runtime diagnostics are not concurrent atomics.
  require(panel(device, uint32_t(PanelOperation::Blank), nullptr) == S_OK &&
          counters()[0] > beforeLoading[0]+1 && counters()[4] == 0 &&
          counters()[2] == beforeLoading[2] && counters()[3] == beforeLoading[3],
          "loading did not keep empty XR frames flowing, or submitted stale images");
  require(drawWorld() == S_OK && present() == S_OK && counters()[4] == 2,
          "stereo could not recover after joining the loading owner");
  close(); input(0, 0, 0, 0, 0);
}

void testPanel(IDirectDraw4* dd, IDirect3DDevice3* device, IDirect3DViewport3* viewport,
               Bridge bridge, PanelPixels pixels, TestInput input, TestAim aim, bool color32) {
  PanelFrame request{};
  request.canvasWidth = request.canvasHeight = 128;
  auto present = [&] { return bridge(device, uint32_t(PanelOperation::Present), &request); };
  require(bridge(device, 99, nullptr) == E_INVALIDARG, "unknown panel operation accepted");
  request.size = 0;
  require(FAILED(present()), "unversioned panel request accepted");
  request.size = sizeof(request);
  request.canvasWidth = 127;
  require(FAILED(present()), "panel accepted canvas/target mismatch");
  require(!request.pointer.flags && !request.input.flags, "failed panel exposes stale input");
  request.canvasWidth = 128;
  std::array<float, 9> geometry{};
  std::vector<uint8_t> output(128 * 128 * 4);
  for (unsigned sequence = 0; sequence < 3; ++sequence) {
    check(device->BeginScene(), "begin panel draw");
    for (unsigned quarter = 0; quarter < 4; ++quarter) {
      const LONG x = (quarter % 2) * 64, y = (quarter / 2) * 64;
      D3DRECT area{x, y, x+64, y+64};
      check(viewport->Clear2(1, &area, D3DCLEAR_TARGET, colors[(quarter+sequence)%4], 1.f, 0), "draw panel color");
    }
    check(device->EndScene(), "end panel draw");
    require(present() == S_OK, "panel did not recover after invalid canvas");
    require(pixels(output.data(), uint32_t(output.size()), geometry.data()) == sequence+1,
      "wrong quad submission count or panel pixel extent");
    require(geometry[3] == 1 && geometry[6] == -1.6f && geometry[7] == 1.6f && geometry[8] == 1.6f,
      "quad geometry does not match panel hit testing");
    require(std::memcmp(geometry.data(), &request.geometry, sizeof(geometry)) == 0,
      "pointer bridge reports a different pose/size from the submitted quad");
    for (unsigned y = 0; y < 128; ++y) for (unsigned x = 0; x < 128; ++x) {
      const unsigned quarter = (y/64)*2+x/64;
      const auto color = colors[(quarter+sequence)%4];
      const auto offset = (y*128+x)*4;
      for (unsigned channel = 0; channel < 3; ++channel)
        require(std::abs(int(output[offset+channel])-int((color>>(16-8*channel))&255)) <= 7,
          "panel changed encoded colors, pixel positions, or orientation");
      require(output[offset+3] == 255, "panel is not opaque");
    }
  }
  require(input(0, 3, 0, 0, 0) && input(1, 3, 0, 0, 0), "activate panel pointers");
  for (unsigned hand = 0; hand < 2; ++hand) {
    request.hand = hand;
    for (float x : {-.79f, -.4f, 0.f, .4f, .79f})
      for (float y : {-.79f, 0.f, .79f}) {
        require(aim(hand, x, y, 0), "position pointing controller");
        require(present() == S_OK && request.pointer.flags == PointerHit && request.pointer.hand == hand,
          "GPU panel bridge lost controller hit or hand identity");
        require(std::abs(request.pointer.x-(.5f+x/1.6f)*128) < .0001f &&
                std::abs(request.pointer.y-(.5f-y/1.6f)*128) < .0001f,
          "GPU panel pointer drifts toward canvas edges");
      }
  }
  require(input(0, 0, 0, 0, 0) && input(1, 0, 0, 0, 0), "clear panel pointers");
  check(bridge(device, uint32_t(PanelOperation::Close), nullptr), "close interface panel");
  // A different UI canvas must allocate its own correctly sized target rather
  // than stretching into the headset eye image or reusing a stale square panel.
  DDSURFACEDESC2 desc{}; desc.dwSize = sizeof(desc);
  desc.dwFlags = DDSD_WIDTH | DDSD_HEIGHT | DDSD_CAPS | DDSD_PIXELFORMAT;
  desc.dwWidth = 320; desc.dwHeight = 240;
  desc.ddsCaps.dwCaps = DDSCAPS_3DDEVICE | DDSCAPS_VIDEOMEMORY;
  desc.ddpfPixelFormat = {sizeof(DDPIXELFORMAT), DDPF_RGB, 0, 16, 0xf800, 0x7e0, 0x1f, 0};
  if (color32) desc.ddpfPixelFormat = {sizeof(DDPIXELFORMAT), DDPF_RGB, 0, 32, 0xff0000, 0xff00, 0xff, 0};
  ComPtr<IDirectDrawSurface4> target;
  check(dd->CreateSurface(&desc, target.GetAddressOf(), nullptr), "create resized panel canvas");
  check(device->SetRenderTarget(target.Get(), 0), "select resized panel canvas");
  D3DVIEWPORT2 view{sizeof(view), 0, 0, 320, 240, -1.f, 1.f, 2.f, 2.f, 0.f, 1.f};
  check(viewport->SetViewport2(&view), "resize panel viewport");
  check(device->BeginScene(), "begin resized panel draw");
  D3DRECT area{0, 0, 320, 240};
  check(viewport->Clear2(1, &area, D3DCLEAR_TARGET, colors[3], 1.f, 0), "clear resized panel canvas");
  check(device->EndScene(), "end resized panel draw");
  request.canvasWidth = 320; request.canvasHeight = 240;
  request.flags = PanelRecenter;
  require(present() == S_OK, "resized panel failed");
  output.resize(320 * 240 * 4);
  require(pixels(output.data(), uint32_t(output.size()), geometry.data()) == 34 &&
          std::abs(geometry[8]-1.2f) < .00001f, "resized quad lost canvas aspect ratio");
  for (size_t offset = 0; offset < output.size(); offset += 4)
    for (unsigned channel = 0; channel < 3; ++channel)
      if (std::abs(int(output[offset+channel])-128) > 7) {
        std::cerr << "resized pixel " << offset/4 << " channel " << channel << " value " << int(output[offset+channel]) << '\n';
        throw std::runtime_error("resized panel pixels corrupted");
      }
  // A completed 2D page may be newer than its last 3D draw. The bridge must
  // upload dirty DirectDraw pixels itself, without relying on a later Flip.
  DDBLTFX fill{}; fill.dwSize = sizeof(fill);
  fill.dwFillColor = color32 ? 0x0000ff00 : 0x07e0;
  check(target->Blt(nullptr, nullptr, nullptr, DDBLT_COLORFILL | DDBLT_WAIT, &fill), "CPU-authored panel page");
  require(present() == S_OK, "CPU-authored panel failed");
  require(pixels(output.data(), uint32_t(output.size()), geometry.data()) == 35,
          "CPU-authored quad not submitted");
  for (size_t offset = 0; offset < output.size(); offset += 4)
    require(output[offset] <= 7 && output[offset+1] >= 248 && output[offset+2] <= 7,
            "quad sampled stale GPU pixels instead of final DirectDraw page");
}

void testCaptions(IDirectDraw4* dd, IDirect3DDevice3* device, IDirect3DViewport3* viewport,
                  SceneBridge scene, Bridge panel, Pixels eyes, PanelPixels pixels,
                  TestInput input, FrameStats stats) {
  DDSURFACEDESC2 desc{}; desc.dwSize = sizeof(desc);
  desc.dwFlags = DDSD_WIDTH | DDSD_HEIGHT | DDSD_CAPS | DDSD_PIXELFORMAT;
  desc.dwWidth = desc.dwHeight = 128;
  desc.ddsCaps.dwCaps = DDSCAPS_OFFSCREENPLAIN | DDSCAPS_SYSTEMMEMORY;
  desc.ddpfPixelFormat = {sizeof(DDPIXELFORMAT), DDPF_RGB, 0, 16, 0xf800, 0x7e0, 0x1f, 0};
  ComPtr<IDirectDrawSurface4> source4;
  check(dd->CreateSurface(&desc, source4.GetAddressOf(), nullptr), "create CPU caption canvas");
  ComPtr<IDirectDrawSurface> source;
  check(source4->QueryInterface(IID_IDirectDrawSurface, reinterpret_cast<void**>(source.GetAddressOf())),
        "query caption producer Surface1");
  DDCOLORKEY key{1, 1};
  check(source->SetColorKey(DDCKEY_SRCBLT, &key), "set explicit caption key");
  DDSURFACEDESC locked{}; locked.dwSize = sizeof(locked);
  check(source->Lock(nullptr, &locked, DDLOCK_WAIT, nullptr), "author native caption cache");
  for (unsigned y = 0; y < 128; ++y) {
    auto* row = reinterpret_cast<uint16_t*>(static_cast<uint8_t*>(locked.lpSurface) + y*locked.lPitch);
    for (unsigned x = 0; x < 128; ++x) row[x] = 1;
    if (y >= 96 && y < 112)
      for (unsigned x = 32; x < 96; ++x)
        row[x] = x < 48 ? 0 : x < 64 ? 0xffff : x < 80 ? 0xf800 : 0x7e0;
    // Non-key content outside the declared glyph bounds must not leak.
    row[1] = 0xffff;
  }
  check(source->Unlock(locked.lpSurface), "release authored caption cache");
  CaptionPanelFrame request{};
  request.panel.canvasWidth = request.panel.canvasHeight = 128;
  request.panel.flags = PanelTransparent;
  request.surface = uint32_t(uintptr_t(source.Get())); request.key = 1;
  request.left = 32; request.top = 96; request.right = 96; request.bottom = 112;
  SceneDraws draws{device, viewport, {}, -1};
  SceneV1 world{}; world.width = world.height = 128; world.unitsPerMeter = 40;
  world.flags = SceneDeferred;
  world.camera.worldToCamera = {1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0};
  world.camera.planes[0].distance = -2; world.camera.planes[1].distance = 24000;
  world.context = &draws; world.draw = SceneDraws::draw;
  WorldInputV1 sampled{}; world.worldInput = &sampled;
  auto counters = [&] { std::array<uint64_t, 6> value{};
    require(stats(value.data(), uint32_t(value.size())), "read caption layer statistics"); return value; };
  auto caption = [&] { return panel(device, uint32_t(PanelOperation::Caption), &request); };
  auto draw = [&] { draws.cameras.clear(); return scene(device, &world); };
  require(input(0, 3, Inventory, 0, 0) && input(1, 0, 0, 0, 0), "activate caption shortcuts");
  const auto before = counters();
  require(draw() == S_OK && caption() == S_OK, "transparent caption did not complete stereo world");
  const auto after = counters();
  require(after[0] == before[0]+1 && after[1] == before[1]+1 && after[2] == before[2]+1 &&
          after[3] == before[3]+1 && after[4] == 2 &&
          after[5] == XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT,
          "caption did not share one frame or submit source-alpha quad over stereo");
  require(!request.panel.pointer.flags && request.panel.pointer.held == Inventory &&
          std::memcmp(&sampled.input, &request.panel.input, sizeof(sampled.input)) == 0,
          "caption swallowed world pointing or lost shortcuts/predicted input");
  std::vector<uint8_t> output(128*128*4); std::array<float, 9> geometry{};
  require(pixels(output.data(), uint32_t(output.size()), geometry.data()) == after[3],
          "transparent caption texture missing");
  for (unsigned y = 0; y < 128; ++y) for (unsigned x = 0; x < 128; ++x) {
    const size_t offset = (y*128+x)*4;
    const bool inside = y >= 96 && y < 112 && x >= 32 && x < 96;
    const std::array<uint8_t, 4> expected = !inside ? std::array<uint8_t, 4>{0, 0, 0, 0} :
      x < 48 ? std::array<uint8_t, 4>{0, 0, 0, 255} :
      x < 64 ? std::array<uint8_t, 4>{255, 255, 255, 255} :
      x < 80 ? std::array<uint8_t, 4>{255, 0, 0, 255} : std::array<uint8_t, 4>{0, 255, 0, 255};
    require(std::memcmp(output.data()+offset, expected.data(), 4) == 0,
            "caption lost true black/alpha/color/orientation or leaked pixels beyond glyph bounds");
  }
  output.resize(256*256*4);
  for (unsigned eye = 0; eye < 2; ++eye) {
    require(eyes(eye, output.data(), uint32_t(output.size())) == after[2], "caption lost stereo eye");
    require(std::abs(int(output[0])-int((colors[eye]>>16)&255)) <= 7,
            "caption upload overwrote the world eye");
  }
  require(caption() == S_FALSE && counters() == after && !request.panel.input.flags,
          "stale caption started a new world or resurrected input");
  request.panel.flags = 0;
  require(draw() == S_OK && panel(device, uint32_t(PanelOperation::World), &request.panel) == S_OK &&
          counters()[4] == 1 && counters()[3] == after[3],
          "expired caption remained visible in the next world frame");
  request.panel.flags = PanelTransparent;
  request.key = 2;
  require(FAILED(caption()), "incorrect producer color key accepted");
  request.key = 1; request.right = 129;
  require(FAILED(caption()), "out-of-canvas caption rectangle accepted");
  check(source->Lock(nullptr, &locked, DDLOCK_READONLY | DDLOCK_WAIT, nullptr), "failed caption stranded producer lock");
  check(source->Unlock(locked.lpSurface), "release recovered caption lock");
  request.right = 96;
  require(draw() == S_OK && caption() == S_OK, "caption did not recover after invalid source");
  // Returning to an ordinary interface must remove transparent mode.
  PanelFrame opaque{}; opaque.canvasWidth = opaque.canvasHeight = 128;
  require(panel(device, uint32_t(PanelOperation::Present), &opaque) == S_OK && counters()[5] == 0,
          "ordinary interface inherited caption alpha");
  check(panel(device, uint32_t(PanelOperation::Close), nullptr), "close caption fixture");
  require(input(0, 0, 0, 0, 0), "clear caption controls");
}

void testOverlayParts(IDirectDraw4* dd, IDirectDrawSurface4* target, IDirect3DDevice3* device,
                      IDirect3DViewport3* viewport, SceneBridge scene, Bridge panel,
                      Pixels eyes, PanelPixels panels, PanelPixels auxiliary, PanelPixels subtitles,
                      TestInput input, TestAim aim, FrameStats stats) {
  auto source = [&](uint32_t width, bool keyed, uint32_t height = 16) {
    DDSURFACEDESC2 desc{}; desc.dwSize = sizeof(desc);
    desc.dwFlags = DDSD_WIDTH | DDSD_HEIGHT | DDSD_CAPS | DDSD_PIXELFORMAT;
    desc.dwWidth = width; desc.dwHeight = height;
    desc.ddsCaps.dwCaps = DDSCAPS_OFFSCREENPLAIN | DDSCAPS_SYSTEMMEMORY;
    desc.ddpfPixelFormat = {sizeof(DDPIXELFORMAT), DDPF_RGB, 0, 16, 0xf800, 0x7e0, 0x1f, 0};
    ComPtr<IDirectDrawSurface4> surface4;
    check(dd->CreateSurface(&desc, surface4.GetAddressOf(), nullptr), "create isolated UI piece");
    ComPtr<IDirectDrawSurface> surface;
    check(surface4->QueryInterface(IID_IDirectDrawSurface,
          reinterpret_cast<void**>(surface.GetAddressOf())), "query UI piece Surface1");
    if (keyed) { DDCOLORKEY key{1, 1};
      check(surface->SetColorKey(DDCKEY_SRCBLT, &key), "set UI piece explicit key"); }
    DDSURFACEDESC locked{}; locked.dwSize = sizeof(locked);
    check(surface->Lock(nullptr, &locked, DDLOCK_WAIT, nullptr), "author isolated UI piece");
    for (unsigned y = 0; y < height; ++y) {
      auto* row = reinterpret_cast<uint16_t*>(static_cast<uint8_t*>(locked.lpSurface) + y*locked.lPitch);
      for (unsigned x = 0; x < width; ++x)
        row[x] = keyed ? (x < 16 ? 0xf800 : x < 32 ? 1 : x < 48 ? 0x7e0 : 0x1f) :
                         (x < 16 ? 0 : 0xffff);
    }
    check(surface->Unlock(locked.lpSurface), "finish isolated UI piece");
    return surface;
  };
  const auto opaque = source(32, false), keyed = source(64, true);
  ComPtr<IDirectDrawSurface> page;
  check(target->QueryInterface(IID_IDirectDrawSurface,
        reinterpret_cast<void**>(page.GetAddressOf())), "query forbidden completed page");
  OverlayPanelFrame overlay{};
  overlay.panel.canvasWidth = overlay.panel.canvasHeight = 128;
  overlay.panel.flags = PanelTransparent; overlay.count = 3;
  overlay.parts[0] = {uint32_t(uintptr_t(opaque.Get())), 0, 0, 0, 0, 32, 16, 40, 40};
  overlay.parts[1] = {uint32_t(uintptr_t(keyed.Get())), OverlayKeyed, 1, 0, 0, 64, 16, 32, 44};
  overlay.parts[2] = {uint32_t(uintptr_t(opaque.Get())), 0, 0, 0, 0, 32, 16, -16, 124};
  const auto baseline = overlay;
  SceneDraws draws{device, viewport, {}, -1};
  SceneV1 world{}; world.width = world.height = 128; world.unitsPerMeter = 40;
  world.flags = SceneDeferred;
  world.camera.worldToCamera = {1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0};
  world.camera.planes[0].distance = -2; world.camera.planes[1].distance = 24000;
  world.context = &draws; world.draw = SceneDraws::draw;
  WorldInputV1 sampled{}; world.worldInput = &sampled;
  auto counters = [&] { std::array<uint64_t, 6> value{};
    require(stats(value.data(), uint32_t(value.size())), "read composed UI frame statistics"); return value; };
  auto present = [&] { return panel(device, uint32_t(PanelOperation::Overlay), &overlay); };
  auto draw = [&] { draws.cameras.clear(); return scene(device, &world); };
  require(input(0, 3, Inventory, 0, 0), "activate composed UI shortcut");
  for (const auto extent : {std::array<uint32_t, 2>{128, 128}, {96, 160}}) {
    overlay.panel.canvasWidth = extent[0]; overlay.panel.canvasHeight = extent[1];
    const auto before = counters();
    require(draw() == S_OK && present() == S_OK, "compose isolated UI over a completed stereo world");
    const auto after = counters();
    require(after[0] == before[0]+1 && after[1] == before[1]+1 && after[2] == before[2]+1 &&
            after[3] == before[3]+1 && after[4] == 2 &&
            after[5] == XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT,
            "composed UI duplicated a frame, omitted stereo or lost alpha composition");
    require(!overlay.panel.pointer.flags && overlay.panel.pointer.held == Inventory &&
            std::memcmp(&sampled.input, &overlay.panel.input, sizeof(sampled.input)) == 0,
            "display-only UI pieces intercepted world input or resampled controls");
    std::vector<uint8_t> output(size_t(extent[0])*extent[1]*4); std::array<float, 9> geometry{};
    require(panels(output.data(), uint32_t(output.size()), geometry.data()) == after[3],
            "composed UI image missing");
    for (unsigned y = 0; y < extent[1]; ++y) for (unsigned x = 0; x < extent[0]; ++x) {
      std::array<uint8_t, 4> expected{};
      if (y >= 40 && y < 56 && x >= 40 && x < 72)
        expected = x < 56 ? std::array<uint8_t, 4>{0, 0, 0, 255} :
                           std::array<uint8_t, 4>{255, 255, 255, 255};
      if (y >= 44 && y < 60 && x >= 32 && x < 96) {
        if (x < 48) expected = {255, 0, 0, 255};
        else if (x >= 64) expected = x < 80 ? std::array<uint8_t, 4>{0, 255, 0, 255} :
                                            std::array<uint8_t, 4>{0, 0, 255, 255};
      }
      if (y >= 124 && y < 140 && x < 16) expected = {255, 255, 255, 255};
      require(std::memcmp(output.data()+(size_t(y)*extent[0]+x)*4, expected.data(), 4) == 0,
              "UI composition changed alpha, opaque black, local origin, clipping, z-order or colors");
    }
    output.resize(256*256*4);
    for (unsigned eye = 0; eye < 2; ++eye) {
      require(eyes(eye, output.data(), uint32_t(output.size())) == after[2], "UI composition lost a stereo eye");
      require(std::abs(int(output[0])-int((colors[eye]>>16)&255)) <= 7,
              "UI composition altered a world eye");
    }
    require(present() == S_FALSE && counters() == after && !overlay.panel.input.flags,
            "stale UI sources began a fresh world or reused stale input");
  }
  // The renderer must pick exactly the current interactive source coverage,
  // not every opaque label and not the entire rectangular alpha canvas.
  // Move, shrink, clip and remove a producer without resizing its canvas.
  // Spare upload capacity must never expose old pixels, affect geometry, or
  // move picking to the upload texture's local origin.
  overlay = baseline; overlay.count = 1; overlay.panel.hand = 0;
  require(input(0, 3, 0, 0, 0), "release controls for moving overlay");
  std::array<float, 9> anchored{};
  for (unsigned step = 0; step < 6; ++step) {
    const std::array<int32_t, 4> placements[]{{40, 40, 32, 16}, {103, 7, 8, 4},
      {-4, 123, 8, 8}, {150, 150, 32, 16}, {2, 91, 4, 2}, {40, 40, 32, 16}};
    const auto position = placements[step];
    overlay.parts[0] = {uint32_t(uintptr_t(opaque.Get())), OverlayInteractive, 0,
                       0, 0, position[2], position[3], position[0], position[1]};
    const float px = float(std::max(position[0], 0))+.5f;
    const float py = float(std::max(position[1], 0))+.5f;
    require(aim(0, (px/128.f-.5f)*1.6f, (.5f-py/128.f)*1.6f, 0), "aim at moving overlay");
    require(draw() == S_OK && present() == S_OK, "present moved or empty overlay");
    std::vector<uint8_t> output(128*128*4); std::array<float, 9> geometry{};
    require(panels(output.data(), uint32_t(output.size()), geometry.data()) == counters()[3],
            "moving overlay image missing");
    if (step == 0) anchored = geometry;
    else require(geometry == anchored, "upload crop changed full-canvas panel placement or scale");
    for (int y = 0; y < 128; ++y) for (int x = 0; x < 128; ++x) {
      std::array<uint8_t, 4> expected{};
      if (x >= position[0] && x < position[0]+position[2] &&
          y >= position[1] && y < position[1]+position[3])
        expected = x-position[0] < 16 ? std::array<uint8_t, 4>{0, 0, 0, 255} :
                                       std::array<uint8_t, 4>{255, 255, 255, 255};
      require(std::memcmp(output.data()+(size_t(y)*128+size_t(x))*4, expected.data(), 4) == 0,
              "moved overlay retained old pixels, exposed capacity padding or shifted its crop");
    }
    require(bool(overlay.panel.pointer.flags & PointerHit) == (step != 3),
            "moving overlay retained stale coverage or shifted native hitboxes");
    if (step != 3) require(std::abs(overlay.panel.pointer.x-px) < .001f &&
                           std::abs(overlay.panel.pointer.y-py) < .001f,
                           "cropped upload changed physical pointer coordinates");
  }
  overlay = baseline;
  overlay.parts[0].flags = OverlayInteractive;
  require(input(0, 3, 0, 0, 0) && input(1, 3, 0, 0, 0), "activate isolated menu pointers");
  require(draw() == S_OK && present() == S_OK, "release controls before isolated menu selection");
  require(input(0, 3, Select, 0, 0) && input(1, 3, Select, 0, 0), "select isolated menu controls");
  for (unsigned hand = 0; hand < 2; ++hand) {
    overlay.panel.hand = hand;
    for (const auto point : {std::array<unsigned, 3>{44, 42, 1}, {60, 42, 1}, {44, 46, 0},
                             {52, 46, 1}, {66, 46, 0}, {10, 128, 0}, {120, 120, 0}}) {
      const float x = float(point[0])+.5f, y = float(point[1])+.5f;
      require(aim(hand, (x/128.f-.5f)*1.6f, (.5f-y/128.f)*1.6f, 0), "aim at isolated menu pixel");
      const auto before = counters();
      require(draw() == S_OK && present() == S_OK, "present interactive isolated menu");
      const auto after = counters();
      if (bool(overlay.panel.pointer.flags & PointerHit) != bool(point[2]) ||
          overlay.panel.pointer.hand != hand || overlay.panel.pointer.held != Select)
        std::cerr << "coverage hand " << hand << " pixel " << x << ',' << y << " expected " << point[2]
                  << " actual " << overlay.panel.pointer.flags << " hand " << overlay.panel.pointer.hand
                  << " held " << overlay.panel.pointer.held << " point " << overlay.panel.pointer.x << ','
                  << overlay.panel.pointer.y << '\n';
      require(bool(overlay.panel.pointer.flags & PointerHit) == bool(point[2]) &&
              overlay.panel.pointer.hand == hand && overlay.panel.pointer.held == Select &&
              std::memcmp(&sampled.input, &overlay.panel.input, sizeof(sampled.input)) == 0 &&
              after[0] == before[0]+1 && after[1] == before[1]+1 && after[2] == before[2]+1 &&
              after[3] == before[3]+1 && after[4] == 2 &&
              after[5] == XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT,
              "isolated menu coverage captured labels/holes, lost input or duplicated an XR frame");
      if (point[2]) require(std::abs(overlay.panel.pointer.x-x) < .001f &&
                            std::abs(overlay.panel.pointer.y-y) < .001f,
                            "isolated menu pointer disagrees with submitted pixel placement");
      else require(overlay.panel.pointer.x == 0 && overlay.panel.pointer.y == 0,
                   "uncovered menu point retained an earlier hit");
    }
  }
  // Withdraw interaction without destroying or recentering the panel. Its
  // current source still draws, but cannot retain the previous menu's hits.
  require(aim(1, (44.5f/128.f-.5f)*1.6f, (.5f-42.5f/128.f)*1.6f, 0), "aim at withdrawn menu");
  overlay.parts[0].flags = 0;
  require(draw() == S_OK && present() == S_OK && !overlay.panel.pointer.flags &&
          overlay.panel.pointer.held == Select, "display-only next frame inherited menu coverage");
  require(input(1, 0, 0, 0, 0) && input(0, 3, Inventory, 0, 0), "restore display-only input");
  // A readable menu keeps native source pixels/coordinates, but changes the
  // quad's physical scale/anchor. HUD and captions remain a separate ordinary
  // canvas. Exercise real GPU uploads, layer retirement and both-hand picking.
  check(panel(device, uint32_t(PanelOperation::Close), nullptr), "reset readable menu anchor");
  overlay = baseline; overlay.panel.flags |= PanelReadableMenu;
  overlay.parts[0] = {uint32_t(uintptr_t(keyed.Get())), OverlayKeyed|OverlayInteractive,
                     1, 0, 0, 64, 16, 48, 16};
  overlay.parts[1] = {uint32_t(uintptr_t(opaque.Get())), OverlayMenuCompanion,
                     0, 0, 0, 32, 16, 48, 34};
  overlay.parts[2] = {uint32_t(uintptr_t(opaque.Get())), 0, 0, 0, 0, 32, 16, 4, 104};
  require(input(0, 3, 0, 0, 0) && input(1, 3, 0, 0, 0), "neutral readable-menu controllers");
  require(draw() == S_OK && present() == S_OK, "present enlarged menu with ordinary caption");
  std::vector<uint8_t> menuImage(128*128*4), labelImage(128*128*4);
  std::array<float, 9> menuGeometry{}, labelGeometry{};
  require(panels(menuImage.data(), uint32_t(menuImage.size()), menuGeometry.data()) &&
          auxiliary(labelImage.data(), uint32_t(labelImage.size()), labelGeometry.data()),
          "readable menu or display-only GPU image missing");
  require(std::abs(menuGeometry[7]/labelGeometry[7]-1.8f) < .0001f &&
          std::abs(menuGeometry[8]/labelGeometry[8]-1.8f) < .0001f &&
          labelGeometry[4] == 0 && labelGeometry[5] == 0 && labelGeometry[6] == -1.6f &&
          labelGeometry[7] == 1.6f && labelGeometry[8] == 1.6f &&
          std::abs(menuGeometry[4]+(80.f/128.f-.5f)*menuGeometry[7]) < .0001f &&
          std::abs(menuGeometry[5]+(.5f-16.f/128.f)*menuGeometry[8]-.04f) < .0001f &&
          counters()[4] == 3 && counters()[5] == XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT,
          "menu is not readable/aspect-correct or moved/magnified opaque HUD captions");
  for (unsigned y = 0; y < 128; ++y) for (unsigned x = 0; x < 128; ++x) {
    std::array<uint8_t,4> menuPixel{}, labelPixel{};
    if (y >= 16 && y < 32 && x >= 48 && x < 112) {
      if (x < 64) menuPixel={255,0,0,255};
      else if (x >= 80) menuPixel=x < 96 ? std::array<uint8_t,4>{0,255,0,255} :
                                                         std::array<uint8_t,4>{0,0,255,255};
    }
    if (y >= 34 && y < 50 && x >= 48 && x < 80)
      menuPixel=x < 64 ? std::array<uint8_t,4>{0,0,0,255} : std::array<uint8_t,4>{255,255,255,255};
    if (y >= 104 && y < 120 && x >= 4 && x < 36)
      labelPixel=x < 20 ? std::array<uint8_t,4>{0,0,0,255} : std::array<uint8_t,4>{255,255,255,255};
    const auto offset=(size_t(y)*128+x)*4;
    require(std::memcmp(menuImage.data()+offset,menuPixel.data(),4)==0 &&
            std::memcmp(labelImage.data()+offset,labelPixel.data(),4)==0,
            "auxiliary upload overwrote menu pixels or menu/HUD separation altered native pixels");
  }
  const auto readable = overlay;
  // Three simultaneous quads: menu+tooltip, ordinary HUD, enlarged dialogue.
  // Pixel content must remain independent despite sharing the upload texture.
  overlay.count=4;
  overlay.parts[3]={uint32_t(uintptr_t(opaque.Get())),OverlaySubtitle,0,0,0,32,16,48,110};
  require(draw()==S_OK && present()==S_OK,"present menu/HUD/subtitle in one predicted frame");
  std::vector<uint8_t> captionImage(128*128*4);
  std::array<float,9> captionGeometry{};
  require(subtitles(captionImage.data(),uint32_t(captionImage.size()),captionGeometry.data()) &&
          panels(menuImage.data(),uint32_t(menuImage.size()),menuGeometry.data()) &&
          auxiliary(labelImage.data(),uint32_t(labelImage.size()),labelGeometry.data()) &&
          counters()[4]==4 && captionGeometry[7]>labelGeometry[7] &&
          captionGeometry[7]==captionGeometry[8],"subtitle layer replaced/magnified HUD or lost aspect ratio");
  for (unsigned y=0;y<128;++y) for (unsigned x=0;x<128;++x) {
    const bool inside=x>=48 && x<80 && y>=110 && y<126;
    const uint8_t v=inside && x>=64 ? 255 : 0;
    const std::array<uint8_t,4> expected{v,v,v,uint8_t(inside ? 255 : 0)};
    require(std::memcmp(captionImage.data()+(size_t(y)*128+x)*4,expected.data(),4)==0,
            "subtitle GPU pixels contain stale HUD/menu content");
  }
  overlay=readable;
  require(draw()==S_OK && present()==S_OK && counters()[4]==3 &&
          !subtitles(captionImage.data(),uint32_t(captionImage.size()),captionGeometry.data()),
          "retired subtitle retained its GPU quad");
  // A score can fade while an enlarged menu stays open. Its independent
  // display plane must use fresh premultiplied pixels on every frame, retire
  // at zero opacity and reappear without retaining the previous glyph area.
  const auto unchangedMenu = menuImage;
  std::array<std::vector<uint8_t>,2> unchangedEyes;
  for (unsigned eye=0;eye<2;++eye) {
    unchangedEyes[eye].resize(256*256*4);
    require(eyes(eye,unchangedEyes[eye].data(),uint32_t(unchangedEyes[eye].size())),
            "capture world before independent HUD fade");
  }
  for (const float opacity : {1.f,.75f,.5f,.25f,0.f}) {
    overlay.parts[2].opacity=opacity;
    require(draw()==S_OK && present()==S_OK,"fade HUD while readable menu stays open");
    std::array<float,9> fadeMenu{},fadeLabel{};
    require(panels(menuImage.data(),uint32_t(menuImage.size()),fadeMenu.data()) &&
            fadeMenu==menuGeometry && menuImage==unchangedMenu,
            "HUD fade altered menu pixels or physical placement");
    const bool visible=opacity>0;
    require(bool(auxiliary(labelImage.data(),uint32_t(labelImage.size()),fadeLabel.data()))==visible &&
            counters()[4]==(visible ? 3u : 2u),
            "invisible HUD retained its previous compositor layer");
    if (visible) {
      require(fadeLabel==labelGeometry,"HUD fade moved or magnified its display plane");
      const auto alpha=uint8_t(std::lround(double(opacity)*255));
      for (unsigned y=0;y<128;++y) for (unsigned x=0;x<128;++x) {
        const bool inside=y>=104 && y<120 && x>=4 && x<36;
        const uint8_t value=inside && x>=20 ? alpha : 0;
        const std::array<uint8_t,4> expected{value,value,value,uint8_t(inside ? alpha : 0)};
        require(std::memcmp(labelImage.data()+(size_t(y)*128+x)*4,expected.data(),4)==0,
                "independent HUD fade left stale pixels or lost source alpha");
      }
    }
    for (unsigned eye=0;eye<2;++eye) {
      std::vector<uint8_t> image(256*256*4);
      require(eyes(eye,image.data(),uint32_t(image.size())) && image==unchangedEyes[eye],
              "independent HUD fade contaminated a stereo eye");
    }
  }
  overlay.parts[2].opacity=1.f; overlay.parts[2].x=84;
  require(draw()==S_OK && present()==S_OK &&
          auxiliary(labelImage.data(),uint32_t(labelImage.size()),labelGeometry.data()),
          "retired HUD failed to reappear on its ordinary display plane");
  for (unsigned y=0;y<128;++y) for (unsigned x=0;x<128;++x) {
    const bool inside=y>=104 && y<120 && x>=84 && x<116;
    const uint8_t value=inside && x>=100 ? 255 : 0;
    const std::array<uint8_t,4> expected{value,value,value,uint8_t(inside ? 255 : 0)};
    require(std::memcmp(labelImage.data()+(size_t(y)*128+x)*4,expected.data(),4)==0,
            "reappearing HUD retained pixels at its former location");
  }
  overlay=readable;
  require(draw()==S_OK && present()==S_OK,"restore readable menu after HUD retirement");
  for (unsigned hand=0; hand<2; ++hand) {
    overlay.panel.hand=hand;
    for (const auto point : {std::array<unsigned,3>{49,17,1},{65,17,0},{81,17,1},
                             {97,17,1},{49,35,0},{21,105,0},{47,17,0},{112,17,0}}) {
      const float x=float(point[0])+.5f,y=float(point[1])+.5f;
      require(input(hand,3,Select,0,0) &&
              aim(hand,menuGeometry[4]+(x/128.f-.5f)*menuGeometry[7],
                       menuGeometry[5]+(.5f-y/128.f)*menuGeometry[8],0),
              "aim at displayed readable-menu pixel");
      require(draw()==S_OK && present()==S_OK &&
              bool(overlay.panel.pointer.flags&PointerHit)==bool(point[2]) &&
              overlay.panel.pointer.hand==hand && overlay.panel.pointer.held==Select,
              "magnified menu picking differs from visible controls, holes, tooltip or caption");
      if (point[2]) require(std::abs(overlay.panel.pointer.x-x)<.001f &&
                            std::abs(overlay.panel.pointer.y-y)<.001f,
                            "enlarged menu changed original game hit coordinates");
    }
  }
  overlay.count=4;
  overlay.parts[3]={uint32_t(uintptr_t(opaque.Get())),OverlayInteractive,0,0,0,32,16,4,52};
  require(draw()==S_OK && present()==S_OK, "expand readable menu");
  std::array<float,9> expanded{}, expandedLabels{};
  require(panels(menuImage.data(),uint32_t(menuImage.size()),expanded.data()) && expanded==menuGeometry &&
          auxiliary(labelImage.data(),uint32_t(labelImage.size()),expandedLabels.data()) && expandedLabels==labelGeometry,
          "submenu growth refit the existing menu or moved HUD/captions");
  // An invalid late display part must cancel the whole batch, not publish a
  // half-updated menu. The next valid frame must recover with both planes.
  overlay.parts[2].right=33;
  const auto beforeBad=counters();
  require(draw()==S_OK && FAILED(present()) && counters()[3]==beforeBad[3],
          "invalid auxiliary source submitted a partial readable menu");
  overlay=readable;
  require(draw()==S_OK && present()==S_OK && counters()[4]==3,
          "readable menu failed to recover after rejected auxiliary source");
  overlay.count=2;
  require(draw()==S_OK && present()==S_OK && counters()[4]==2 &&
          !auxiliary(labelImage.data(),uint32_t(labelImage.size()),expandedLabels.data()),
          "withdrawn caption retained a stale compositor quad");
  overlay.count=1; overlay.panel.flags=PanelTransparent; overlay.parts[0]=readable.parts[2];
  require(draw()==S_OK && present()==S_OK && counters()[4]==2 &&
          panels(menuImage.data(),uint32_t(menuImage.size()),expanded.data()) && expanded==labelGeometry &&
          !overlay.panel.pointer.flags,
          "closing readable menu retained magnification or caption interaction");
  for (unsigned eye=0;eye<2;++eye) {
    std::vector<uint8_t> image(256*256*4);
    require(eyes(eye,image.data(),uint32_t(image.size())),"capture world after readable menu retirement");
    for(size_t offset=0;offset<image.size();offset+=4) for(unsigned c=0;c<3;++c)
      require(std::abs(int(image[offset+c])-int((colors[eye]>>(16-8*c))&255))<=7,
              "readable menu or retired caption contaminated a stereo eye");
  }
  require(input(1,0,0,0,0) && input(0,3,Inventory,0,0),"restore controls after readable menus");
  // Full-size desktop canvases with independent, widely separated crops.
  const auto fullHud = source(1089, false, 48);
  for (const auto extent : {std::array<uint32_t,2>{1280,800}, {3840,2160}}) {
    overlay = readable; overlay.count = 2;
    overlay.panel.canvasWidth = extent[0]; overlay.panel.canvasHeight = extent[1];
    overlay.parts[0] = {uint32_t(uintptr_t(opaque.Get())), OverlayInteractive, 0,
                       0,0,32,16,int32_t(extent[0]/2),int32_t(extent[1]/2)};
    overlay.parts[1] = {uint32_t(uintptr_t(fullHud.Get())), 0, 0,0,0,1089,48,14,14};
    require(draw()==S_OK && present()==S_OK,"present desktop-sized menu and HUD crops");
    std::vector<uint8_t> hudPixels(size_t(extent[0])*extent[1]*4);
    std::array<float,9> hudGeometry{};
    require(auxiliary(hudPixels.data(),uint32_t(hudPixels.size()),hudGeometry.data()),"capture desktop-sized HUD");
    require(hudGeometry[7]==1.6f && std::abs(hudGeometry[8]-1.6f*float(extent[1])/float(extent[0]))<.0001f,
            "desktop size changed auxiliary HUD scale");
    for (unsigned y=0;y<extent[1];++y) for(unsigned x=0;x<extent[0];++x) {
      std::array<uint8_t,4> expected{};
      if(y>=14 && y<62 && x>=14 && x<1103)
        expected=x<30 ? std::array<uint8_t,4>{0,0,0,255} : std::array<uint8_t,4>{255,255,255,255};
      require(std::memcmp(hudPixels.data()+(size_t(y)*extent[0]+x)*4,expected.data(),4)==0,
              "desktop-sized auxiliary crop changed source pixels or retained old content");
    }
  }
  // Reject a failed later part atomically and release every already-locked
  // producer. A following valid scene must recover without a stranded frame.
  for (unsigned kind = 0; kind < 11; ++kind) {
    overlay = baseline;
    switch (kind) {
      case 0: overlay.count = 0; break;
      case 1: overlay.count = MaxOverlayParts+1; break;
      case 2: overlay.parts[1].key = 2; break;
      case 3: overlay.parts[1].right = 65; break;
      case 4: overlay.parts[1].flags = 8; break;
      case 5: overlay.parts[1].surface = 0; break;
      case 6: overlay.parts[1].surface = uint32_t(uintptr_t(page.Get())); break;
      case 7: overlay.parts[1].opacity = -.01f; break;
      case 8: overlay.parts[1].opacity = 1.01f; break;
      case 9: overlay.parts[1].opacity = std::numeric_limits<float>::quiet_NaN(); break;
      case 10: overlay.parts[1].opacity = std::numeric_limits<float>::infinity(); break;
    }
    const auto before = counters();
    require(draw() == S_OK && FAILED(present()), "invalid UI source was accepted");
    require(counters()[3] == before[3], "partially composed UI was submitted after a failed source");
    DDSURFACEDESC locked{}; locked.dwSize = sizeof(locked);
    check(opaque->Lock(nullptr, &locked, DDLOCK_READONLY | DDLOCK_WAIT, nullptr), "failed composition leaked producer lock");
    check(opaque->Unlock(locked.lpSurface), "release recovered UI producer lock");
    locked = {}; locked.dwSize = sizeof(locked);
    check(keyed->Lock(nullptr, &locked, DDLOCK_READONLY | DDLOCK_WAIT, nullptr), "failed composition leaked keyed producer lock");
    check(keyed->Unlock(locked.lpSurface), "release recovered keyed producer lock");
    overlay = baseline;
    require(draw() == S_OK && present() == S_OK, "UI composition did not recover after failed source");
  }
  overlay = baseline; overlay.count = MaxOverlayParts;
  for (uint32_t i = 3; i < overlay.count; ++i) overlay.parts[i] = baseline.parts[2];
  require(draw() == S_OK && present() == S_OK, "bounded overlay rejected its advertised maximum part count");
  PanelFrame flat{}; flat.canvasWidth = flat.canvasHeight = 128;
  require(panel(device, uint32_t(PanelOperation::Present), &flat) == S_OK && counters()[5] == 0,
          "ordinary flat panel inherited composed overlay alpha");
  check(panel(device, uint32_t(PanelOperation::Close), nullptr), "close UI composition fixture");
  require(input(0, 0, 0, 0, 0), "clear UI composition controls");
  std::cout << "XR isolated UI composition passed: readable anchored menus, independent HUD/captions, both-hand picking, retirement, keyed/opaque sources and atomic recovery\n";
}

void testBrightness(IDirectDraw4* dd, IDirectDrawSurface4* target, IDirect3DDevice3* device,
                    IDirect3DViewport3* viewport, SceneBridge scene, Bridge panel,
                    Pixels eyes, PanelPixels panels, FrameStats stats) {
  // Exercise the application's existing gamma interface. XR must apply exactly
  // the same accepted ramp as desktop presentation, not its own brightness knob.
  ComPtr<IDirectDrawGammaControl> gamma;
  check(target->QueryInterface(IID_IDirectDrawGammaControl,
        reinterpret_cast<void**>(gamma.GetAddressOf())), "query application gamma control");
  DDSURFACEDESC2 desc{}; desc.dwSize = sizeof(desc);
  desc.dwFlags = DDSD_WIDTH | DDSD_HEIGHT | DDSD_CAPS | DDSD_PIXELFORMAT;
  desc.dwWidth = desc.dwHeight = 128;
  desc.ddsCaps.dwCaps = DDSCAPS_OFFSCREENPLAIN | DDSCAPS_SYSTEMMEMORY;
  desc.ddpfPixelFormat = {sizeof(DDPIXELFORMAT), DDPF_RGB, 0, 16, 0xf800, 0x7e0, 0x1f, 0};
  ComPtr<IDirectDrawSurface4> canvas4;
  check(dd->CreateSurface(&desc, canvas4.GetAddressOf(), nullptr), "create brightness overlay");
  ComPtr<IDirectDrawSurface> canvas;
  check(canvas4->QueryInterface(IID_IDirectDrawSurface,
        reinterpret_cast<void**>(canvas.GetAddressOf())), "query brightness overlay");
  DDCOLORKEY key{1, 1};
  check(canvas->SetColorKey(DDCKEY_SRCBLT, &key), "key brightness overlay");
  DDSURFACEDESC locked{}; locked.dwSize = sizeof(locked);
  check(canvas->Lock(nullptr, &locked, DDLOCK_WAIT, nullptr), "write brightness overlay");
  for (unsigned y = 0; y < 128; ++y) {
    auto* row = reinterpret_cast<uint16_t*>(static_cast<uint8_t*>(locked.lpSurface) + y*locked.lPitch);
    for (unsigned x = 0; x < 128; ++x)
      row[x] = y >= 96 && y < 112 && x >= 32 && x < 96 ? (x < 64 ? 0 : 0x8410) : 1;
  }
  check(canvas->Unlock(locked.lpSurface), "finish brightness overlay");
  CaptionPanelFrame overlay{};
  overlay.panel.canvasWidth = overlay.panel.canvasHeight = 128;
  overlay.panel.flags = PanelTransparent;
  overlay.surface = uint32_t(uintptr_t(canvas.Get())); overlay.key = 1;
  overlay.left = 32; overlay.top = 96; overlay.right = 96; overlay.bottom = 112;
  SceneDraws draws{device, viewport, {}, -1};
  SceneV1 world{}; world.width = world.height = 128; world.unitsPerMeter = 40;
  world.camera.worldToCamera = {1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0};
  world.camera.planes[0].distance = -2; world.camera.planes[1].distance = 24000;
  world.context = &draws; world.draw = SceneDraws::draw;
  std::array<std::vector<uint8_t>, 2> neutral;
  std::vector<uint8_t> neutralPanel, neutralOverlay;
  for (unsigned phase = 0; phase < 3; ++phase) {
    DDGAMMARAMP ramp{};
    for (unsigned i = 0; i < 256; ++i) {
      const double x = double(i)/255;
      ramp.red[i] = WORD(std::lround((phase == 1 ? std::pow(x, .65) : x)*65535));
      ramp.green[i] = WORD(std::lround((phase == 1 ? x*x : x)*65535));
      // A raised black point catches invisible pixels becoming coloured while
      // retaining alpha=0. Those must remain valid premultiplied transparency.
      ramp.blue[i] = WORD(std::lround((phase == 1 ? .05+.75*x : x)*65535));
    }
    check(gamma->SetGammaRamp(0, &ramp), "set application brightness");
    DDGAMMARAMP accepted{};
    check(gamma->GetGammaRamp(0, &accepted), "read accepted application brightness");
    require(std::memcmp(&accepted, &ramp, sizeof(ramp)) == 0, "brightness request was ignored");
    auto expected = [&](unsigned channel, unsigned source) {
      const WORD* points = channel == 0 ? ramp.red : channel == 1 ? ramp.green : ramp.blue;
      return int(std::lround(double(points[source])*255/65535));
    };
    auto compare = [&](const std::vector<uint8_t>& image, unsigned offset, D3DCOLOR color) {
      for (unsigned c = 0; c < 3; ++c) {
        const unsigned source = (color >> (16-8*c)) & 255;
        const int wanted = expected(c, source);
        if (std::abs(int(image[offset+c])-wanted) > 8)
          std::cerr << "XR brightness phase " << phase << " channel " << c
                    << " actual " << int(image[offset+c]) << " expected " << wanted << '\n';
        require(std::abs(int(image[offset+c])-wanted) <= 8, "XR ignored or duplicated application brightness");
      }
      require(image[offset+3] == 255, "brightness changed opaque alpha");
    };
    world.flags = 0; draws.cameras.clear();
    std::array<std::vector<uint8_t>, 2> cleanWorld;
    require(scene(device, &world) == S_OK, "draw brightness eyes");
    for (unsigned eye = 0; eye < 2; ++eye) {
      std::vector<uint8_t> image(256*256*4);
      require(eyes(eye, image.data(), uint32_t(image.size())), "capture brightness eyes");
      compare(image, (128*256+128)*4, colors[eye]);
      cleanWorld[eye] = image;
      if (phase == 0) neutral[eye] = image;
      if (phase == 2) require(image == neutral[eye], "return to neutral retained an XR correction");
    }
    check(device->BeginScene(), "begin brightness panel");
    D3DRECT area{0, 0, 128, 128};
    check(viewport->Clear2(1, &area, D3DCLEAR_TARGET, colors[2], 1.f, 0), "paint brightness panel");
    check(device->EndScene(), "end brightness panel");
    PanelFrame ui{}; ui.canvasWidth = ui.canvasHeight = 128;
    require(panel(device, uint32_t(PanelOperation::Present), &ui) == S_OK, "present brightness panel");
    std::vector<uint8_t> capture(128*128*4); float geometry[9]{};
    require(panels(capture.data(), uint32_t(capture.size()), geometry), "capture brightness panel");
    compare(capture, (64*128+64)*4, colors[2]);
    if (phase == 0) neutralPanel = capture;
    if (phase == 2) require(capture == neutralPanel, "opaque panel retained an XR correction");
    world.flags = SceneDeferred; draws.cameras.clear();
    overlay.panel.flags = PanelTransparent;
    require(scene(device, &world) == S_OK &&
            panel(device, uint32_t(PanelOperation::Caption), &overlay) == S_OK,
            "present transparent brightness overlay");
    require(panels(capture.data(), uint32_t(capture.size()), geometry), "capture transparent brightness");
    unsigned covered = 0;
    for (unsigned offset = 0; offset < capture.size(); offset += 4) {
      if (capture[offset+3]) {
        ++covered;
        require(capture[offset+3] == 255, "brightness changed binary caption coverage");
      } else {
        for (unsigned c = 0; c < 3; ++c)
          require(capture[offset+c] == 0, "brightness polluted transparent pixels");
      }
    }
    require(covered == 64*16, "brightness changed caption bounds or coverage");
    compare(capture, (104*128+48)*4, 0xff000000);
    compare(capture, (104*128+80)*4, 0xff848284);
    if (phase == 0) neutralOverlay = capture;
    if (phase == 2) require(capture == neutralOverlay, "transparent panel retained an XR correction");
    // Uniform authored opacity is carried separately from RGB565 content.
    // Verify real GPU upload/shader transport applies the accepted brightness
    // to unpremultiplied color, then restores the same fractional coverage.
    // In particular, a raised black point must not tint fully invisible pixels.
    OverlayPanelFrame faded{}; faded.panel = overlay.panel; faded.count = 1;
    faded.parts[0] = {overlay.surface, OverlayKeyed, 1, 32, 96, 96, 112, 32, 96};
    for (const float opacity : {1.f, .75f, .5f, .25f, 0.f}) {
      faded.parts[0].opacity = opacity;
      draws.cameras.clear();
      require(scene(device, &world) == S_OK &&
              panel(device, uint32_t(PanelOperation::Overlay), &faded) == S_OK,
              "present independently faded brightness overlay");
      require(panels(capture.data(), uint32_t(capture.size()), geometry), "capture faded brightness overlay");
      const int alpha = int(std::lround(double(opacity)*255));
      for (unsigned y = 0; y < 128; ++y) for (unsigned x = 0; x < 128; ++x) {
        const unsigned offset = (y*128+x)*4;
        const bool inside = y >= 96 && y < 112 && x >= 32 && x < 96;
        require(capture[offset+3] == (inside ? alpha : 0), "GPU transport changed fade coverage");
        for (unsigned c = 0; c < 3; ++c) {
          const unsigned color = x < 64 ? 0 : (c == 1 ? 130 : 132);
          const int wanted = inside ? int(std::lround(double(expected(c, color))*alpha/255)) : 0;
          require(std::abs(int(capture[offset+c])-wanted) <= 2,
                  "GPU fade lost source color, premultiplication, gamma or placement");
          require(capture[offset+c] <= capture[offset+3], "GPU fade has nonpremultiplied color");
        }
      }
      for (unsigned eye = 0; eye < 2; ++eye) {
        std::vector<uint8_t> image(256*256*4);
        require(eyes(eye, image.data(), uint32_t(image.size())), "capture world during HUD fade");
        require(image == cleanWorld[eye], "fading HUD contaminated the world eye or retained old pixels");
      }
    }
    // Retirement must omit the old quad, not merely display its last uploaded
    // image. Verify both eyes remain identical to the clean world afterward.
    PanelFrame retired{}; retired.canvasWidth = retired.canvasHeight = 128;
    draws.cameras.clear();
    require(scene(device, &world) == S_OK &&
            panel(device, uint32_t(PanelOperation::World), &retired) == S_OK,
            "retire faded HUD into a world-only frame");
    std::array<uint64_t, 6> retiredStats{};
    require(stats(retiredStats.data(), uint32_t(retiredStats.size())) && retiredStats[4] == 1,
            "retired HUD retained a compositor layer");
    for (unsigned eye = 0; eye < 2; ++eye) {
      std::vector<uint8_t> image(256*256*4);
      require(eyes(eye, image.data(), uint32_t(image.size())), "capture world after HUD retirement");
      require(image == cleanWorld[eye], "retired HUD left pixels in the world eye");
    }
  }
  check(panel(device, uint32_t(PanelOperation::Close), nullptr), "close brightness fixture");
  std::cout << "XR brightness passed: accepted gamma in both eyes and panels, transparent black points, neutral reset\n";
}

void testModalSubtitles(IDirectDraw4* dd, IDirectDrawSurface4* target,
                       IDirect3DDevice3* device, IDirect3DViewport3* viewport,
                       Bridge panel, PanelPixels panels, PanelPixels subtitles,
                       TestInput input, TestAim aim, FrameStats stats) {
  using namespace gk3hd::vr;
  check(panel(device, uint32_t(PanelOperation::Close), nullptr), "reset modal subtitle fixture");
  D3DRECT full{0,0,128,128}, glyphs{32,96,96,112};
  check(device->BeginScene(), "begin native caption page");
  check(viewport->Clear2(1,&full,D3DCLEAR_TARGET,0xff806040,1.f,0), "author native page");
  check(viewport->Clear2(1,&glyphs,D3DCLEAR_TARGET,0xffffffff,1.f,0), "author baked caption marker");
  check(device->EndScene(), "finish native caption page");
  PanelFrame opaque{}; opaque.canvasWidth=opaque.canvasHeight=128; opaque.widthMeters=2.4f;
  require(input(1,3,0,0,0) && input(0,0,0,0,0) && aim(1,0,0,0), "aim at native modal canvas");
  check(panel(device,uint32_t(PanelOperation::Present),&opaque), "capture native page baseline");
  std::vector<uint8_t> baseline(128*128*4), image(baseline.size()), caption(baseline.size());
  std::array<float,9> geometry{}, subtitleGeometry{};
  require(panels(baseline.data(),uint32_t(baseline.size()),geometry.data()), "native page baseline missing");
  auto nativePixels=[&] {
    DDSURFACEDESC2 locked{};locked.dwSize=sizeof(locked);
    check(target->Lock(nullptr,&locked,DDLOCK_READONLY|DDLOCK_WAIT,nullptr), "observe unchanged game page");
    std::vector<uint8_t> bytes;
    const auto stride=128*(locked.ddpfPixelFormat.dwRGBBitCount/8);
    for(unsigned y=0;y<128;++y) {
      const auto* row=static_cast<const uint8_t*>(locked.lpSurface)+y*locked.lPitch;
      bytes.insert(bytes.end(),row,row+stride);
    }
    check(target->Unlock(nullptr), "release native page observation");return bytes;
  };
  const auto nativeBefore=nativePixels();
  DDSURFACEDESC2 desc{};desc.dwSize=sizeof(desc);
  desc.dwFlags=DDSD_WIDTH|DDSD_HEIGHT|DDSD_CAPS|DDSD_PIXELFORMAT;
  desc.dwWidth=desc.dwHeight=128;desc.ddsCaps.dwCaps=DDSCAPS_OFFSCREENPLAIN|DDSCAPS_SYSTEMMEMORY;
  desc.ddpfPixelFormat={sizeof(DDPIXELFORMAT),DDPF_RGB,0,16,0xf800,0x7e0,0x1f,0};
  ComPtr<IDirectDrawSurface4> source4;
  check(dd->CreateSurface(&desc,source4.GetAddressOf(),nullptr), "create modal subtitle source");
  ComPtr<IDirectDrawSurface> source;
  check(source4->QueryInterface(IID_IDirectDrawSurface,reinterpret_cast<void**>(source.GetAddressOf())), "query subtitle source");
  DDCOLORKEY key{1,1};check(source->SetColorKey(DDCKEY_SRCBLT,&key), "set subtitle key");
  DDSURFACEDESC locked{};locked.dwSize=sizeof(locked);
  check(source->Lock(nullptr,&locked,DDLOCK_WAIT,nullptr), "author modal subtitle pixels");
  for(unsigned y=0;y<128;++y) {
    auto* row=reinterpret_cast<uint16_t*>(static_cast<uint8_t*>(locked.lpSurface)+y*locked.lPitch);
    for(unsigned x=0;x<128;++x) row[x]=(x>=32 && x<96 && y>=96 && y<112 && x!=48) ? 0xffff : 1;
  }
  check(source->Unlock(locked.lpSurface), "finish subtitle source");
  OverlayPanelFrame request{};request.panel=opaque;request.count=1;
  request.parts[0]={uint32_t(uintptr_t(source.Get())),OverlayKeyed|OverlaySubtitle,1,32,96,96,112,32,96};
  std::array<uint64_t,6> before{},after{};
  require(stats(before.data(),uint32_t(before.size())), "read modal frame baseline");
  check(panel(device,uint32_t(PanelOperation::ModalSubtitles),&request), "compose opaque movie and readable subtitle");
  require(stats(after.data(),uint32_t(after.size())) && after[0]==before[0]+1 && after[1]==before[1]+1 &&
          after[2]==before[2] && after[3]==before[3]+1 && after[4]==2,
          "modal subtitles duplicated frames or omitted a layer");
  require(panels(image.data(),uint32_t(image.size()),geometry.data()) &&
          subtitles(caption.data(),uint32_t(caption.size()),subtitleGeometry.data()), "modal layers not captured");
  require(request.panel.pointer.flags==PointerHit && request.panel.pointer.hand==1 &&
          geometry[7]==opaque.widthMeters && subtitleGeometry[7]>geometry[7],
          "modal subtitle altered picking or failed to retain independent readable scale");
  for(unsigned y=0;y<128;++y) for(unsigned x=0;x<128;++x) {
    const auto offset=(size_t(y)*128+x)*4;
    const bool inside=x>=32 && x<96 && y>=96 && y<112;
    const std::array<uint8_t,4> black{0,0,0,255}, white{255,255,255,255}, empty{};
    require(std::memcmp(image.data()+offset,inside ? black.data() : baseline.data()+offset,4)==0,
            "modal matte changed pixels outside the baked caption or left duplicate glyphs");
    require(std::memcmp(caption.data()+offset,inside ? (x==48 ? black.data() : white.data()) : empty.data(),4)==0,
            "readable modal subtitle changed source colors or retained stale pixels");
  }
  require(nativePixels()==nativeBefore, "modal subtitle matte modified the actual game page");
  request.parts[0].flags|=OverlayInteractive;
  require(FAILED(panel(device,uint32_t(PanelOperation::ModalSubtitles),&request)), "modal subtitle became interactive");
  check(panel(device,uint32_t(PanelOperation::Present),&opaque), "retire modal subtitle");
  require(panels(image.data(),uint32_t(image.size()),geometry.data()) && image==baseline &&
          !subtitles(caption.data(),uint32_t(caption.size()),subtitleGeometry.data()),
          "retired subtitle retained matte, glyphs or an auxiliary layer");
  check(panel(device,uint32_t(PanelOperation::Close),nullptr), "close modal subtitle fixture");
  require(input(0,0,0,0,0) && input(1,0,0,0,0), "clear modal subtitle input fixture");
  std::cout << "XR cinematic subtitles passed: independent readable quad, exact private matte, native page/picking preservation, one frame and clean retirement\n";
}

void testKeyboard(IDirect3DDevice3* device, Bridge panel, TextBridge text, PanelPixels capture,
                  TestInput input, TestAim aim, FrameStats stats) {
  TextFrame request{}; request.epoch = 17; request.available = 1;
  check(text(device, &request), "configure native keyboard epoch");
  PanelFrame ui{}; ui.canvasWidth = ui.canvasHeight = 128;
  // The input fixture resets the controller's default X position on each
  // update. Keep the button state and displayed-key ray paired explicitly.
  auto pointing = [&](uint32_t buttons) {
    return input(1, 3, buttons, 0, 0) && aim(1, -.543f, -.912f, 0);
  };
  require(pointing(0), "keyboard controller setup");
  check(panel(device, uint32_t(PanelOperation::Present), &ui), "present editor and keyboard");
  std::vector<uint8_t> image(1200*456*4); float geometry[9]{};
  require(capture(image.data(), uint32_t(image.size()), geometry), "keyboard GPU image missing");
  require(std::abs(geometry[7]-1.2f) < .0001f && std::abs(geometry[8]-.456f) < .0001f &&
          std::abs(geometry[5]+1.088f) < .0001f && std::abs(geometry[6]+1.58f) < .0001f,
          "keyboard quad moved, stretched or replaced its editor");
  require(image[0] == 22 && image[1] == 27 && image[2] == 34 && image[3] == 255,
          "GPU keyboard changed encoded background colors or opacity");
  unsigned glyphs = 0;
  for (size_t i = 0; i < image.size(); i += 4) {
    require(image[i+3] == 255, "GPU keyboard lost label/background opacity");
    glyphs += image[i] > 200 && image[i+1] > 200 && image[i+2] > 200;
  }
  require(glyphs > 2000, "GPU keyboard labels are missing");
  uint64_t counts[5]{}; require(stats(counts, 5) && counts[4] == 2, "editor and keyboard did not share one XR frame");
  check(text(device, &request), "retrieve released keyboard state");
  require(!request.action.kind, "release typed a key");
  require(pointing(Select), "press keyboard select");
  check(panel(device, uint32_t(PanelOperation::Present), &ui), "select keyboard key");
  require(!(ui.pointer.held & Select) && !(ui.pointer.pressed & Select) && !(ui.pointer.flags & PointerHit) &&
          !(ui.input.hands[1].pressed & Select), "keyboard click reached native editor controls");
  check(text(device, &request), "retrieve typed key");
  require(request.action.epoch == 17 && request.action.kind == 1 && request.action.value == '1',
          "controller keyboard did not deliver its displayed key");
  check(panel(device, uint32_t(PanelOperation::Present), &ui), "hold keyboard select");
  check(text(device, &request), "retrieve held key state");
  require(!request.action.kind, "keyboard repeated a held key");
  require(pointing(0), "release keyboard select");
  check(panel(device, uint32_t(PanelOperation::Present), &ui), "release selected key");
  require(pointing(Select), "press another keyboard key");
  check(panel(device, uint32_t(PanelOperation::Present), &ui), "prepare stale keyboard event");
  request.epoch = 18;
  check(text(device, &request), "replace native editor epoch");
  require(!request.action.kind, "old keyboard event crossed native editor epoch");
  request.epoch = 0;
  check(text(device, &request), "retire editor keyboard");
  check(panel(device, uint32_t(PanelOperation::Present), &ui), "present editor without keyboard");
  require(!capture(image.data(), uint32_t(image.size()), geometry) && stats(counts, 5) && counts[4] == 1,
          "retired keyboard remained visible or retained its layer");
  check(panel(device, uint32_t(PanelOperation::Close), nullptr), "close keyboard test");
  require(input(1, 0, 0, 0, 0), "clear keyboard controller");
  std::cout << "XR keyboard passed: actual GPU labels/colors, independent quad, controller typing, native select isolation, held/stale rejection and retirement\n";
}

void testDevice(IDirectDraw4* dd, Bridge bridge, SceneBridge scene, Bridge panel, Pixels pixels,
                PanelPixels panelPixels, TestInput input, TestAim aim, FrameStats stats, MainWaits mainWaits, bool color32,
                TextBridge text, PanelPixels keyboardPixels, PanelPixels subtitlePixels, bool criticalCopyOnly) {
  DDSURFACEDESC2 desc{}; desc.dwSize = sizeof(desc);
  desc.dwFlags = DDSD_WIDTH | DDSD_HEIGHT | DDSD_CAPS | DDSD_PIXELFORMAT;
  desc.dwWidth = desc.dwHeight = 128;
  desc.ddsCaps.dwCaps = DDSCAPS_OFFSCREENPLAIN | DDSCAPS_3DDEVICE | DDSCAPS_VIDEOMEMORY;
  desc.ddpfPixelFormat = {sizeof(DDPIXELFORMAT), DDPF_RGB, 0, 16, 0xf800, 0x7e0, 0x1f, 0};
  if (color32) desc.ddpfPixelFormat = {sizeof(DDPIXELFORMAT), DDPF_RGB, 0, 32, 0xff0000, 0xff00, 0xff, 0};
  ComPtr<IDirectDrawSurface4> target;
  check(dd->CreateSurface(&desc, target.GetAddressOf(), nullptr), "create color target");
  ComPtr<IDirect3D3> d3d;
  check(dd->QueryInterface(IID_IDirect3D3, reinterpret_cast<void**>(d3d.GetAddressOf())), "query D3D3");
  DDSURFACEDESC2 depthDesc{}; depthDesc.dwSize = sizeof(depthDesc);
  depthDesc.dwFlags = DDSD_WIDTH | DDSD_HEIGHT | DDSD_CAPS | DDSD_PIXELFORMAT;
  depthDesc.dwWidth = depthDesc.dwHeight = 128;
  depthDesc.ddsCaps.dwCaps = DDSCAPS_ZBUFFER | DDSCAPS_VIDEOMEMORY;
  check(d3d->EnumZBufferFormats(IID_IDirect3DHALDevice, depthFormat, &depthDesc.ddpfPixelFormat), "select native depth format");
  ComPtr<IDirectDrawSurface4> depth;
  check(dd->CreateSurface(&depthDesc, depth.GetAddressOf(), nullptr), "create native depth target");
  check(target->AddAttachedSurface(depth.Get()), "attach native depth target");
  ComPtr<IDirect3DDevice3> device;
  check(d3d->CreateDevice(IID_IDirect3DHALDevice, target.Get(), device.GetAddressOf(), nullptr), "create device");
  ComPtr<IDirect3DViewport3> viewport;
  check(d3d->CreateViewport(viewport.GetAddressOf(), nullptr), "create viewport");
  check(device->AddViewport(viewport.Get()), "attach viewport");
  D3DVIEWPORT2 view{sizeof(view), 0, 0, 128, 128, -1.f, 1.f, 2.f, 2.f, 0.f, 1.f};
  check(viewport->SetViewport2(&view), "configure viewport");
  check(device->SetCurrentViewport(viewport.Get()), "select viewport");
  if (criticalCopyOnly) {
    // Clear-only producers isolate presentation correctness from ordinary game
    // shaders, whose configured async policy deliberately remains unchanged.
    // The very first gamma/alpha variant must be correct, without warmup/retry.
    testBrightness(dd, target.Get(), device.Get(), viewport.Get(), scene, panel, pixels, panelPixels, stats);
    check(device->DeleteViewport(viewport.Get()), "detach critical copy viewport");
    return;
  }
  testNativeTransforms(device.Get(),viewport.Get(),target.Get());
  auto call = [&](FrameOperation operation, void* output = nullptr) {
    return bridge(device.Get(), uint32_t(operation), output);
  };
  require(FAILED(call(FrameOperation::Left)), "eye without frame accepted");
  require(FAILED(call(FrameOperation::Submit)), "submit without frame accepted");
  require(bridge(device.Get(), 99, nullptr) == E_INVALIDARG, "unknown operation accepted");
  FrameViews frame{};
  frame.size = 0;
  require(call(FrameOperation::Begin, &frame) == E_INVALIDARG, "incorrect bridge version accepted");
  frame.size = sizeof(frame);
  std::array<std::vector<uint8_t>, 2> captures;
  for (unsigned sequence = 0; sequence < 4; ++sequence) {
    require(call(FrameOperation::Begin, &frame) == S_OK, "no usable XR frame");
    require(FAILED(call(FrameOperation::Begin, &frame)), "nested frame accepted");
    require(FAILED(call(FrameOperation::Submit)), "incomplete stereo frame accepted");
    for (unsigned eye = 0; eye < 2; ++eye) {
      require(frame.eyes[eye].width == 256 && frame.eyes[eye].height == 256, "wrong target dimensions");
      require(frame.eyes[eye].orientation[3] == 1 && frame.eyes[eye].fov[0] < 0, "wrong predicted eye data");
      require(std::abs(frame.eyes[eye].position[0] - (eye ? .032f : -.032f)) < .00001f, "tracking eyes collapsed");
      check(device->BeginScene(), "begin GPU draw");
      for (unsigned quarter = 0; quarter < 4; ++quarter) {
        const LONG x = (quarter % 2) * 64, y = (quarter / 2) * 64;
        D3DRECT area{x, y, x + 64, y + 64};
        check(viewport->Clear2(1, &area, D3DCLEAR_TARGET,
          colors[(quarter + eye + sequence) % 4], 1.f, 0), "draw encoded GPU color");
      }
      check(device->EndScene(), "end GPU draw");
      const auto operation = eye ? FrameOperation::Right : FrameOperation::Left;
      check(call(operation), "transport eye pixels");
      require(FAILED(call(operation)), "duplicate eye accepted");
      if (sequence == 3) break; // Cancel after a partial frame, submit no layer.
    }
    check(call(sequence == 3 ? FrameOperation::Cancel : FrameOperation::Submit), "finish XR frame");
    for (unsigned eye = 0; eye < 2; ++eye) {
      std::vector<uint8_t> output(256 * 256 * 4);
      require(pixels(eye, output.data(), uint32_t(output.size())) == (sequence == 3 ? 3 : sequence + 1),
        "wrong projection-layer submission count");
      if (sequence == 3) {
        require(output == captures[eye], "cancelled frame changed submitted eye");
        continue;
      }
      for (unsigned quarter = 0; quarter < 4; ++quarter) {
        const auto color = colors[(quarter + eye + sequence) % 4];
        const unsigned x = (quarter % 2) * 128, y = (quarter / 2) * 128;
        // Ignore interpolation at quarter seams. Mid-tones catch accidental
        // sRGB re-encoding that primary-color-only checks would miss.
        for (unsigned row = y + 12; row < y + 116; ++row)
          for (unsigned col = x + 12; col < x + 116; ++col) {
            const auto offset = (row * 256 + col) * 4;
            for (unsigned channel = 0; channel < 3; ++channel) {
              const int expected = (color >> (16 - 8 * channel)) & 255;
              require(std::abs(int(output[offset + channel]) - expected) <= 7,
                "eye pixels changed color, orientation, or stereo identity");
            }
            require(output[offset + 3] == 255, "eye alpha is not opaque");
          }
      }
      captures[eye] = std::move(output);
    }
    if (sequence < 3) require(captures[0] != captures[1], "eyes contain identical pixels");
  }
  require(input(0, 3, 0, 0, 0) && input(1, 3, 0, 0, 0), "configure input fixture");
  check(call(FrameOperation::Begin, &frame), "input baseline frame");
  require(frame.input.flags == InputFocused && frame.input.hands[0].flags == AimValid &&
          frame.input.hands[1].flags == AimValid && frame.input.hands[0].position[0] == -.3f &&
          frame.input.hands[1].position[0] == .3f, "frame bridge lost predicted controller poses");
  check(call(FrameOperation::Cancel), "cancel input baseline");
  require(input(0, 3, Select, .4f, -.5f), "configure selection fixture");
  check(call(FrameOperation::Begin, &frame), "selection frame");
  require(frame.input.hands[0].pressed == Select && !frame.input.hands[1].held &&
          frame.input.hands[0].stick[0] == .4f && frame.input.hands[0].stick[1] == -.5f,
          "renderer lost controller action identity or stick state");
  check(call(FrameOperation::Cancel), "cancel selection frame");
  check(call(FrameOperation::Begin, &frame), "held selection frame");
  require(!frame.input.hands[0].pressed && frame.input.hands[0].held == Select,
          "frame bridge repeats held selection");
  check(call(FrameOperation::Cancel), "cancel held selection");
  require(input(0, 1, Select, .4f, -.5f), "drop pointing tracking");
  check(call(FrameOperation::Begin, &frame), "lost tracking frame");
  require(!frame.input.hands[0].flags && !frame.input.hands[0].held,
          "renderer exposes lost controller tracking");
  check(call(FrameOperation::Cancel), "cancel lost tracking");
  require(input(0, 3, Select, .4f, -.5f), "restore pointing tracking");
  check(call(FrameOperation::Begin, &frame), "tracking recovery frame");
  require(frame.input.hands[0].flags == AimValid && !frame.input.hands[0].held &&
          !frame.input.hands[0].stick[0], "renderer recovery activates held controls");
  check(call(FrameOperation::Cancel), "cancel recovered frame");
  require(input(0, 0, 0, 0, 0) && input(1, 0, 0, 0, 0), "clear input fixture");
  testScene(device.Get(), viewport.Get(), scene, pixels);
  testPanel(dd, device.Get(), viewport.Get(), panel, panelPixels, input, aim, color32);
  for (unsigned eye = 0; eye < 2; ++eye) {
    std::vector<uint8_t> output(256 * 256 * 4);
    require(pixels(eye, output.data(), uint32_t(output.size())) == 5,
      "quad presentation incorrectly submits projection eyes");
  }
  check(device->SetRenderTarget(target.Get(), 0), "return to world canvas");
  check(viewport->SetViewport2(&view), "restore world viewport");
  testKeyboard(device.Get(), panel, text, keyboardPixels, input, aim, stats);
  require(call(FrameOperation::Begin, &frame) == S_OK, "world cannot resume after panel");
  check(call(FrameOperation::Left), "resume left eye");
  check(call(FrameOperation::Right), "resume right eye");
  check(call(FrameOperation::Submit), "submit world after panel");
  for (unsigned eye = 0; eye < 2; ++eye) {
    std::vector<uint8_t> output(256 * 256 * 4);
    require(pixels(eye, output.data(), uint32_t(output.size())) == 6,
      "world projection did not resume after panel");
  }
  testShared(device.Get(), viewport.Get(), scene, panel, bridge, pixels, panelPixels, input, stats, mainWaits);
  testReticle(device.Get(), viewport.Get(), scene, pixels, input, aim);
  testCaptions(dd, device.Get(), viewport.Get(), scene, panel, pixels, panelPixels, input, stats);
  testOverlayParts(dd, target.Get(), device.Get(), viewport.Get(), scene, panel, pixels, panelPixels, keyboardPixels, subtitlePixels, input, aim, stats);
  // The fixture captures auxiliary quads by submission order. A modal page
  // has no projection or menu/HUD quad, so its subtitle is the second quad.
  testModalSubtitles(dd, target.Get(), device.Get(), viewport.Get(), panel, panelPixels, keyboardPixels, input, aim, stats);
  testBrightness(dd, target.Get(), device.Get(), viewport.Get(), scene, panel, pixels, panelPixels, stats);
  testTransitions(dd, target.Get(), device.Get(), viewport.Get(), scene, pixels);
  testSceneMirror(dd,device.Get(),viewport.Get(),scene);
  testCachedNativeDrawState(device.Get(), viewport.Get(), scene, pixels);
  check(device->DeleteViewport(viewport.Get()), "detach viewport");
}
} // namespace

int wmain(int argc, wchar_t** argv) {
  SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
  HWND window = nullptr;
  HMODULE renderer = nullptr, runtime = nullptr;
  int result = 1;
  try {
    require(argc == 3 || (argc == 4 && std::wstring(argv[3]) == L"--critical-copy"),
            "provide renderer DLL and GPU test runtime DLL paths, optionally --critical-copy");
    const bool criticalCopyOnly = argc == 4;
    renderer = LoadLibraryW(argv[1]); runtime = LoadLibraryW(argv[2]);
    require(renderer && runtime, "load fixtures");
    auto create = reinterpret_cast<HRESULT(WINAPI*)(GUID*, IDirectDraw**, IUnknown*)>(GetProcAddress(renderer, "DirectDrawCreate"));
    auto bridge = reinterpret_cast<Bridge>(GetProcAddress(renderer, "Gk3hdXrFrameV1"));
    auto scene = reinterpret_cast<SceneBridge>(GetProcAddress(renderer, "Gk3hdXrSceneV1"));
    auto panel = reinterpret_cast<Bridge>(GetProcAddress(renderer, "Gk3hdXrPanelV1"));
    auto pixels = reinterpret_cast<Pixels>(GetProcAddress(runtime, "Gk3hdXrTestPixels"));
    auto input = reinterpret_cast<TestInput>(GetProcAddress(runtime, "Gk3hdXrTestInput"));
    auto panelPixels = reinterpret_cast<PanelPixels>(GetProcAddress(runtime, "Gk3hdXrTestPanel"));
    auto aim = reinterpret_cast<TestAim>(GetProcAddress(runtime, "Gk3hdXrTestAim"));
    auto stats = reinterpret_cast<FrameStats>(GetProcAddress(runtime, "Gk3hdXrTestFrameStats"));
    auto mainWaits = reinterpret_cast<MainWaits>(GetProcAddress(runtime, "Gk3hdXrTestMainWaits"));
    auto text = reinterpret_cast<TextBridge>(GetProcAddress(renderer, "Gk3hdXrTextV1"));
    auto keyboardPixels = reinterpret_cast<PanelPixels>(GetProcAddress(runtime, "Gk3hdXrTestKeyboard"));
    auto subtitlePixels = reinterpret_cast<PanelPixels>(GetProcAddress(runtime, "Gk3hdXrTestSubtitle"));
    require(create && bridge && scene && panel && pixels && panelPixels && input && aim && stats && mainWaits && text && keyboardPixels && subtitlePixels, "required prototype/test export missing");
    window = CreateWindowExW(0, L"STATIC", L"gk3hd XR GPU transport test", WS_OVERLAPPEDWINDOW,
      0, 0, 128, 128, nullptr, nullptr, GetModuleHandleW(nullptr), nullptr);
    require(window != nullptr, "create fixture window");
    // Recreate the device/session and then repeat image acquisition and writes.
    for (unsigned cycle = 0; cycle < 4; ++cycle) {
      ComPtr<IDirectDraw> dd;
      check(create(nullptr, dd.GetAddressOf(), nullptr), "create DirectDraw");
      ComPtr<IDirectDraw4> dd4;
      check(dd->QueryInterface(IID_IDirectDraw4, reinterpret_cast<void**>(dd4.GetAddressOf())), "query DirectDraw4");
      check(dd4->SetCooperativeLevel(window, DDSCL_NORMAL), "normal cooperative level");
      testDevice(dd4.Get(), bridge, scene, panel, pixels, panelPixels, input, aim, stats, mainWaits,
                 cycle >= 2, text, keyboardPixels, subtitlePixels, criticalCopyOnly);
    }
    if (criticalCopyOnly)
      std::cout << "XR critical copies passed: first-use gamma/alpha variants, eyes/panels, cropped fades, neutral reset, device recreation\n";
    else
      std::cout << "XR GPU transport passed: stereo scenes, native-resolution quad panels, exact pose/size bridge, canvas resizing, encoded colors, controller actions, failure recovery, device recreation\n";
    result = 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; }
  if (window) DestroyWindow(window);
  if (renderer) FreeLibrary(renderer);
  if (runtime) FreeLibrary(runtime);
  return result;
}
