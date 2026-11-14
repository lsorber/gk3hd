#pragma once
#include "frame_metadata.h"
#include "mapped_frame_writer.h"
#include <windows.h>
#include <array>
#include <cstring>
#include <optional>
#include <string>

namespace gk3hd::frame_metadata {
// Labels for submitted compositions, not GPU completion. The host still owns
// real image leases and independently verifies their embedded GPU markers.
class Publisher {
  bool active_=false,initialized_=false,pending_=false;
  uint64_t key_=0;
  Snapshot committed_{},next_{};
  std::wstring destination_;
  MappedWriter writer_;
  static bool absent(const std::wstring& path) {
    if(GetFileAttributesW(path.c_str())!=INVALID_FILE_ATTRIBUTES)return false;
    return GetLastError()==ERROR_FILE_NOT_FOUND;
  }
  static bool epoch(Epoch& out) {
    // Dynamically resolve the OS RNG rather than invent cross-process epochs
    // from pointer addresses or relying on an added static import/library.
    using Random=BOOLEAN (WINAPI*)(PVOID,ULONG);
    HMODULE module=GetModuleHandleW(L"advapi32.dll");
    bool loaded=false;
    if(!module){module=LoadLibraryW(L"advapi32.dll");loaded=module!=nullptr;}
    if(!module)return false;
    auto random=reinterpret_cast<Random>(GetProcAddress(module,"SystemFunction036"));
    bool result=random&&random(out.data(),static_cast<ULONG>(sizeof(out)))!=FALSE;
    if(loaded)FreeLibrary(module);
    bool nonzero=false;for(auto v:out)nonzero|=v!=0;
    return result&&nonzero;
  }
public:
  explicit Publisher(const wchar_t* directory=L".") {
    if(!directory)return;
    char token[33]{};
    if(GetEnvironmentVariableA("GK3HD_FRAME_SESSION",token,sizeof(token))!=32)return;
    std::wstring wide;
    for(unsigned i=0;i<32;i++) {
      if(!((token[i]>='0'&&token[i]<='9')||(token[i]>='a'&&token[i]<='f')))return;
      wide+=static_cast<wchar_t>(token[i]);
    }
    destination_=std::wstring(directory)+L"/gk3hd-frame-"+wide+L".map";
    active_=absent(destination_);
  }
  bool active() const {return active_;}
  struct PendingGuard {
    Publisher& publisher;
    ~PendingGuard(){if(publisher.pending_)publisher.cancel();}
  };
  const std::wstring& destination() const {return destination_;}
  std::optional<std::array<uint32_t,5>> begin(uint64_t key,uint32_t width,uint32_t height,
                                           uint32_t count,uint32_t index,uint32_t pose,uint32_t movie=0) {
    if(!active_)return {};
    if(pending_){active_=false;return {};}
    if(!key||index>=count||count>MaxImages)return {};
    if(!writer_.claim(destination_)){active_=false;return {};}
    if(!initialized_||key!=key_||committed_.width!=width||committed_.height!=height||
       committed_.count!=count||committed_.latest==UINT32_MAX) {
      Epoch fresh{};if(!epoch(fresh))return {};
      auto emptyState=empty(fresh,width,height,count);if(!emptyState)return {};
      committed_=*emptyState;key_=key;initialized_=true;
    }
    next_=committed_;
    if(!publish(next_,index,pose,movie))return {};
    pending_=true;
    return std::array<uint32_t,5>{next_.epoch[0],next_.epoch[1],next_.epoch[2],next_.epoch[3],next_.latest};
  }
  bool commitSubmitted() {
    if(!active_||!pending_)return false;
    committed_=next_;pending_=false;
    auto bytes=encode(committed_);
    if(!bytes||!writer_.publish(destination_,*bytes)){active_=false;return false;}
    return true;
  }
  void cancel() {pending_=false;initialized_=false;key_=0;}
};
} // namespace gk3hd::frame_metadata
