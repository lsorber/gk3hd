#define NOMINMAX
#include <windows.h>
#include <ddraw.h>
#include <wrl/client.h>
#include <iostream>
#include <stdexcept>
#include <random>
#include <vector>
#include "private_area_blt.h"

using Microsoft::WRL::ComPtr;
void require(bool value) { if (!value) throw std::runtime_error("area-blit assertion"); }
void success(HRESULT value) { require(SUCCEEDED(value)); }

struct Surface {
  std::vector<uint16_t> storage;
  DDSURFACEDESC desc{};
  HRESULT description=DD_OK,lockResult=DD_OK,unlockResult=DD_OK;
  unsigned locks=0,unlocks=0;
  bool locked=false,badFormatOnLock=false;
  void* overrideMap=nullptr;
  void* lastMap=nullptr;
  LONG pitchOverride=0;
  Surface(unsigned width=64,unsigned height=64):storage((width+4)*height,0x1234) {
    desc.dwSize=sizeof(desc);desc.dwWidth=width;desc.dwHeight=height;desc.lPitch=(width+4)*2;
    desc.ddpfPixelFormat={sizeof(DDPIXELFORMAT),DDPF_RGB,0,16,0xf800,0x7e0,0x1f,0};
  }
  HRESULT GetSurfaceDesc(DDSURFACEDESC* out) { *out=desc;return description; }
  HRESULT Lock(RECT* r,DDSURFACEDESC* out,DWORD flags,HANDLE) {
    ++locks;if (FAILED(lockResult)) return lockResult;
    require(!locked && (flags&DDLOCK_WAIT));locked=true;*out=desc;
    lastMap=overrideMap ? overrideMap : storage.data()+r->top*(desc.lPitch/2)+r->left;
    out->lpSurface=lastMap;if(pitchOverride)out->lPitch=pitchOverride;
    if(badFormatOnLock)out->ddpfPixelFormat.dwRBitMask=0x7c00;
    return DD_OK;
  }
  HRESULT Unlock(void* p) { require(locked && p==lastMap);locked=false;++unlocks;return unlockResult; }
};

// Independent integer reference accumulates each input texel into its affected
// destination pixels, rather than iterating the implementation's footprints.
std::vector<uint16_t> reference(const std::vector<uint16_t>& input,int pitch,RECT src,int dw,int dh) {
  const int sw=src.right-src.left,sh=src.bottom-src.top;
  std::vector<uint64_t> sums(size_t(dw)*dh*3);
  for(int sy=0;sy<sh;++sy)for(int sx=0;sx<sw;++sx) {
    const uint16_t p=input[(src.top+sy)*pitch+src.left+sx];
    const uint32_t channels[]={uint32_t(p>>11),uint32_t((p>>5)&63),uint32_t(p&31)};
    for(int y=sy*dh/sh;y<((sy+1)*dh+sh-1)/sh;++y)
      for(int x=sx*dw/sw;x<((sx+1)*dw+sw-1)/sw;++x) {
        const uint64_t wx=std::min((sx+1)*dw,(x+1)*sw)-std::max(sx*dw,x*sw);
        const uint64_t wy=std::min((sy+1)*dh,(y+1)*sh)-std::max(sy*dh,y*sh);
        for(int c=0;c<3;++c)sums[(y*dw+x)*3+c]+=channels[c]*wx*wy;
      }
  }
  std::vector<uint16_t> output(dw*dh);
  const uint64_t area=uint64_t(sw)*sh;
  for(size_t i=0;i<output.size();++i)output[i]=uint16_t(
    (((sums[i*3]+area/2)/area)<<11)|(((sums[i*3+1]+area/2)/area)<<5)|((sums[i*3+2]+area/2)/area));
  return output;
}

void exercise(int sw,int sh,int dw,int dh,uint32_t seed) {
  Surface source(sw+5,sh+6),target(dw+7,dh+8);std::mt19937 random(seed);
  for(auto& p:source.storage)p=uint16_t(random());
  const auto before=target.storage,original=source.storage;
  RECT src{2,3,2+sw,3+sh},dst{3,4,3+dw,4+dh};
  const auto expected=reference(source.storage,source.desc.lPitch/2,src,dw,dh);
  const auto result=dxvk::AreaBlt565Surface(&target,&source,dst,src);
  require(result.handled && result.written && result.result==DD_OK && source.storage==original);
  for(unsigned y=0;y<target.desc.dwHeight;++y)for(unsigned x=0;x<unsigned(target.desc.lPitch/2);++x) {
    const bool inside=x>=3&&x<unsigned(3+dw)&&y>=4&&y<unsigned(4+dh);
    const size_t index=y*(target.desc.lPitch/2)+x;
    require(target.storage[index]==(inside ? expected[(y-4)*dw+x-3] : before[index]));
  }
  require(source.locks==1&&source.unlocks==1&&target.locks==1&&target.unlocks==1);
}

void faults() {
  const RECT src{2,3,34,35},dst{3,4,19,20};
  for(unsigned fault=0;fault<18;++fault) {
    Surface source,target;auto sourceRect=src,destRect=dst;
    const auto before=target.storage,original=source.storage;
    switch(fault) {
      case 0:sourceRect.left=-1;break;case 1:sourceRect.right=sourceRect.left;break;
      case 2:sourceRect.bottom=65;break;case 3:destRect.top=-1;break;
      case 4:destRect.right=65;break;case 5:sourceRect.right=2048;break;
      case 6:destRect.right=40;break;case 7:destRect.bottom=40;break;
      case 8:destRect={0,0,32,32};break;
      case 9:source.desc.ddpfPixelFormat.dwFlags|=DDPF_ALPHAPIXELS;break;
      case 10:target.desc.ddpfPixelFormat.dwRGBBitCount=32;break;
      case 11:source.description=DDERR_GENERIC;break;case 12:target.description=DDERR_GENERIC;break;
      case 13:source.pitchOverride=-128;break;case 14:target.pitchOverride=31;break;
      case 15:source.overrideMap=reinterpret_cast<char*>(source.storage.data())+1;break;
      case 16:target.overrideMap=source.storage.data()+3*68+4;break;
      case 17:source.badFormatOnLock=true;break;
    }
    const auto result=dxvk::AreaBlt565Surface(&target,&source,destRect,sourceRect);
    require(!result.handled&&!result.written&&target.storage==before&&source.storage==original);
    require(!source.locked&&!target.locked&&source.locks==source.unlocks&&target.locks==target.unlocks);
  }
  for(unsigned fault=0;fault<4;++fault) {
    Surface source,target;std::fill(source.storage.begin(),source.storage.end(),0x4567);
    if(fault==0)source.lockResult=DDERR_SURFACELOST;
    if(fault==1)target.lockResult=DDERR_SURFACEBUSY;
    if(fault==2)source.unlockResult=DDERR_SURFACEBUSY;
    if(fault==3)target.unlockResult=DDERR_SURFACEBUSY;
    const auto result=dxvk::AreaBlt565Surface(&target,&source,dst,src);
    require(result.handled&&FAILED(result.result)&&result.written==(fault>=2));
    require(!source.locked&&!target.locked);
    require(target.storage[4*68+3]==(fault>=2 ? 0x4567 : 0x1234));
  }
  Surface source;
  require(!dxvk::AreaBlt565Surface(&source,&source,dst,src).handled);
  require(!dxvk::AreaBlt565Surface<Surface>(nullptr,&source,dst,src).handled);
}

void realExport(const char* path) {
  HMODULE module=LoadLibraryA(path);require(module!=nullptr);
  using Export=DWORD(WINAPI*)(dxvk::AreaBlt565Args*);
  auto area=reinterpret_cast<Export>(GetProcAddress(module,"Gk3hdAreaBlt565"));require(area&&!area(nullptr));
  auto create=reinterpret_cast<HRESULT(WINAPI*)(GUID*,IDirectDraw**,IUnknown*)>(GetProcAddress(module,"DirectDrawCreate"));require(create);
  HWND window=CreateWindowExW(0,L"STATIC",L"gk3hd area sampler test",WS_OVERLAPPEDWINDOW,0,0,128,128,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);require(window);
  {
    ComPtr<IDirectDraw> dd;success(create(nullptr,dd.GetAddressOf(),nullptr));
    success(dd->SetCooperativeLevel(window,DDSCL_NORMAL));
    for(DWORD caps:{DWORD(DDSCAPS_OFFSCREENPLAIN|DDSCAPS_SYSTEMMEMORY),DWORD(DDSCAPS_OFFSCREENPLAIN|DDSCAPS_VIDEOMEMORY|DDSCAPS_3DDEVICE)}) {
      DDSURFACEDESC desc{};desc.dwSize=sizeof(desc);desc.dwFlags=DDSD_WIDTH|DDSD_HEIGHT|DDSD_CAPS|DDSD_PIXELFORMAT;
      desc.dwWidth=desc.dwHeight=128;desc.ddsCaps.dwCaps=caps;
      desc.ddpfPixelFormat={sizeof(DDPIXELFORMAT),DDPF_RGB,0,16,0xf800,0x7e0,0x1f,0};
      ComPtr<IDirectDrawSurface> source,target;
      success(dd->CreateSurface(&desc,source.GetAddressOf(),nullptr));success(dd->CreateSurface(&desc,target.GetAddressOf(),nullptr));
      DDSURFACEDESC locked{};locked.dwSize=sizeof(locked);
      success(source->Lock(nullptr,&locked,DDLOCK_WAIT|DDLOCK_WRITEONLY,nullptr));
      std::vector<uint16_t> pixels(128*128);std::mt19937 random(4168);
      for(int y=0;y<128;++y)for(int x=0;x<128;++x) {
        pixels[y*128+x]=uint16_t(random());
        reinterpret_cast<uint16_t*>(static_cast<char*>(locked.lpSurface)+y*locked.lPitch)[x]=pixels[y*128+x];
      }
      success(source->Unlock(locked.lpSurface));
      for(const RECT sourceRect:{RECT{0,0,128,128},RECT{7,5,123,127}})for(int extent:{32,33,90,115}) {
        DDBLTFX fill{};fill.dwSize=sizeof(fill);fill.dwFillColor=0x1234;
        success(target->Blt(nullptr,nullptr,nullptr,DDBLT_WAIT|DDBLT_COLORFILL,&fill));
        dxvk::AreaBlt565Args request{sizeof(request),target.Get(),source.Get(),{1,1,1+extent,1+extent},sourceRect,E_FAIL};
        const auto expected=reference(pixels,128,request.sourceRect,extent,extent);
        require(area(&request)==1&&request.result==DD_OK);
        success(target->Lock(nullptr,&locked,DDLOCK_WAIT|DDLOCK_READONLY,nullptr));
        for(int y=0;y<128;++y)for(int x=0;x<128;++x) {
          const uint16_t value=reinterpret_cast<uint16_t*>(static_cast<char*>(locked.lpSurface)+y*locked.lPitch)[x];
          require(value==((x>=1&&x<=extent&&y>=1&&y<=extent) ? expected[(y-1)*extent+x-1] : 0x1234));
        }
        success(target->Unlock(locked.lpSurface));
      }
      dxvk::AreaBlt565Args request{sizeof(request),target.Get(),source.Get(),{0,0,32,32},{0,0,128,128},E_FAIL};
      ComPtr<IDirectDrawClipper> clipper;success(dd->CreateClipper(0,clipper.GetAddressOf(),nullptr));
      success(target->SetClipper(clipper.Get()));require(!area(&request)&&request.result==E_FAIL);
      success(target->SetClipper(nullptr));success(source->SetClipper(clipper.Get()));require(!area(&request));success(source->SetClipper(nullptr));
      auto bad=request;bad.size--;require(!area(&bad)&&bad.result==E_FAIL);
      bad=request;bad.destination=bad.source;require(!area(&bad));
      ComPtr<IDirectDrawSurface4> surface4;success(source->QueryInterface(IID_IDirectDrawSurface4,reinterpret_cast<void**>(surface4.GetAddressOf())));
      bad=request;bad.source=reinterpret_cast<IDirectDrawSurface*>(surface4.Get());require(!area(&bad));
      bad=request;bad.source=reinterpret_cast<IDirectDrawSurface*>(uintptr_t(1));require(!area(&bad));
      // Source and destination lifetimes stay with the caller: no export-held references.
    }
  }
  DestroyWindow(window);FreeLibrary(module);
}

int main(int argc,char** argv) {
  try {
    static_assert(sizeof(void*)!=4||sizeof(dxvk::AreaBlt565Args)==48,"x86 request ABI drift");
    faults();std::mt19937 random(4168);
    for(unsigned i=0;i<200;++i){int sw=2+random()%40,sh=2+random()%40;exercise(sw,sh,1+random()%(sw-1),1+random()%sh,i);}
    exercise(128,128,32,32,1);exercise(128,128,33,33,2);exercise(128,128,90,90,3);
    exercise(1024,1024,1,1,4);exercise(32,1,7,1,5);exercise(1,32,1,7,6);
    if(argc==2)realExport(argv[1]);
    std::cout<<"206 exact area cases, refusal/failure cases and supplied DLL export passed\n";
  } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
