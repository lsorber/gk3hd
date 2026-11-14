// Compiled into the guest renderer, not a second installable helper DLL.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d.h>
#include <emmintrin.h>
#include "world_adapter.h"

namespace dxvk {
HRESULT __stdcall Gk3hdWorldDeferredV1(IDirect3DDevice3*,unsigned,const void*);
}
namespace {
using namespace gk3hd::vr;
bool equalBytes(const void* source, const void* expected, size_t bytes) {
  auto* a=static_cast<const uint8_t*>(source);
  auto* b=static_cast<const uint8_t*>(expected);
  // Check the whole span without overreading either allocation. These small,
  // repeatedly validated engine records otherwise use scalar memcmp loops.
  __m128i same=_mm_set1_epi8(-1);
  while(bytes>=16) {
    same=_mm_and_si128(same,_mm_cmpeq_epi8(
      _mm_loadu_si128(reinterpret_cast<const __m128i*>(a)),
      _mm_loadu_si128(reinterpret_cast<const __m128i*>(b))));
    a+=16;b+=16;bytes-=16;
  }
  return _mm_movemask_epi8(same)==0xffff&&!std::memcmp(a,b,bytes);
}
bool read(void*, uint32_t address, void* output, size_t bytes) {
  if (address<0x10000||!bytes||bytes>4u*1024*1024||uint64_t(address)+bytes>0x7fff0000) return false;
  // Keep SEH in a leaf without C++ objects requiring unwinding. The game owns
  // these engine structures; an unsupported/unreadable source stays native.
  __try {std::memcpy(output,reinterpret_cast<const void*>(uintptr_t(address)),bytes);return true;}
  __except(EXCEPTION_EXECUTE_HANDLER) {return false;}
}
bool equal(void*,const WorldAdapter::SourceRange* ranges,size_t count) {
  if(!ranges||!count||count>15)return false;
  __try {
    for(size_t i=0;i<count;++i) {
      const auto& range=ranges[i];
      if(range.address<0x10000||!range.bytes||range.bytes>96||
         uint64_t(range.address)+range.bytes>0x7fff0000)return false;
      const auto* source=reinterpret_cast<const uint8_t*>(uintptr_t(range.address));
      if(range.expected) {
        if(range.bytes>=16) {if(!equalBytes(source,range.expected,range.bytes))return false;}
        else if(std::memcmp(source,range.expected,range.bytes))return false;
      }
      else {
        // A span of at most 96 bytes touches at most two Windows memory pages.
        const volatile uint8_t* probe=source;
        (void)probe[0];(void)probe[range.bytes-1];
      }
    }
    return true;
  }__except(EXCEPTION_EXECUTE_HANDLER){return false;}
}
int32_t submit(void*, uint32_t device, world_bridge::Operation operation, const void* argument) {
  return dxvk::Gk3hdWorldDeferredV1(reinterpret_cast<IDirect3DDevice3*>(uintptr_t(device)),uint32_t(operation),argument);
}
WorldAdapter& adapter() {
  static thread_local WorldAdapter state{nullptr,read,submit,equal};
  return state;
}
}
extern "C" __declspec(dllexport) uint32_t __stdcall Gk3hdWorldScopeV1(
    const gk3hd::vr::WorldAdapterConfig* config, void* root, uint32_t phase) {
  if (phase==2) {adapter().cancel();return uint32_t(gk3hd::vr::WorldAction::Native);}
  const auto address=uint32_t(reinterpret_cast<uintptr_t>(root));
  if (phase==1) return uint32_t(adapter().end(address));
  if (phase!=0) return uint32_t(gk3hd::vr::WorldAction::Failed);
  gk3hd::vr::WorldAdapterConfig verified{};
  if (!read(nullptr,uint32_t(reinterpret_cast<uintptr_t>(config)),&verified,sizeof(verified)))
    return uint32_t(gk3hd::vr::WorldAction::Native);
  return uint32_t(adapter().begin(verified,address));
}
extern "C" __declspec(dllexport) uint32_t __stdcall Gk3hdWorldDrawV1(const uint32_t* arguments, uint32_t surface) {
  std::array<uint32_t,8> verified{};
  if (!read(nullptr,uint32_t(reinterpret_cast<uintptr_t>(arguments)),verified.data(),sizeof(verified))) {
    adapter().cancel();return uint32_t(gk3hd::vr::WorldAction::Failed);
  }
  return uint32_t(adapter().draw(verified,surface));
}
extern "C" __declspec(dllexport) uint32_t __stdcall Gk3hdWorldPreparedV1(void* root, uint32_t surface) {
  return uint32_t(adapter().prepared(uint32_t(reinterpret_cast<uintptr_t>(root)),surface));
}
