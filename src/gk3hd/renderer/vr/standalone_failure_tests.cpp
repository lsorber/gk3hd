#include "standalone_failure.h"
#include <stdexcept>
#include <string>
#include <cstdio>

static void require(bool value) {if(!value)throw std::runtime_error("Standalone renderer failure behavior failed");}
int main() {
  char previous[256]{};
  const auto length=GetEnvironmentVariableA("GK3HD_FRAME_SESSION",previous,sizeof(previous));
  HANDLE owned=nullptr,other=nullptr;
  try {
    require(length<sizeof(previous));
    char token[33],second[33],name[96];
    std::snprintf(token,sizeof(token),"%016llx%016llx",static_cast<unsigned long long>(GetCurrentProcessId()),static_cast<unsigned long long>(GetTickCount64()));
    std::snprintf(second,sizeof(second),"%016llx%016llx",static_cast<unsigned long long>(GetCurrentProcessId()),static_cast<unsigned long long>(GetTickCount64()+1));
    require(std::string(token)!=second);
    std::snprintf(name,sizeof(name),"Local\\GK3HD.RendererFault.%s",token);
    owned=CreateEventA(nullptr,TRUE,FALSE,name);require(owned&&GetLastError()!=ERROR_ALREADY_EXISTS);
    std::snprintf(name,sizeof(name),"Local\\GK3HD.RendererFault.%s",second);
    other=CreateEventA(nullptr,TRUE,FALSE,name);require(other&&GetLastError()!=ERROR_ALREADY_EXISTS);
    for(const char* invalid : {"", "short", "ABCDEF0123456789abcdef0123456789", "0000000000000000000000000000000x", "000000000000000000000000000000000"}) {
      require(SetEnvironmentVariableA("GK3HD_FRAME_SESSION",invalid));
      gk3hd::vr::notifyStandaloneDeviceLost();
      require(WaitForSingleObject(owned,0)==WAIT_TIMEOUT&&WaitForSingleObject(other,0)==WAIT_TIMEOUT);
    }
    require(SetEnvironmentVariableA("GK3HD_FRAME_SESSION",token));
    SetLastError(1234);gk3hd::vr::notifyStandaloneDeviceLost();require(GetLastError()==1234);
    require(WaitForSingleObject(owned,0)==WAIT_OBJECT_0&&WaitForSingleObject(other,0)==WAIT_TIMEOUT);
    gk3hd::vr::notifyStandaloneDeviceLost();require(WaitForSingleObject(owned,0)==WAIT_OBJECT_0);
    require(SetEnvironmentVariableA("GK3HD_FRAME_SESSION",second));gk3hd::vr::notifyStandaloneDeviceLost();
    require(WaitForSingleObject(other,0)==WAIT_OBJECT_0);
    CloseHandle(owned);owned=nullptr;CloseHandle(other);other=nullptr;
    // Reporting alone must not leave a new event behind.
    gk3hd::vr::notifyStandaloneDeviceLost();require(!OpenEventA(SYNCHRONIZE,FALSE,name));
    require(SetEnvironmentVariableA("GK3HD_FRAME_SESSION",length?previous:nullptr));
    std::puts("Standalone renderer failure: session isolation, invalid input, repeat reporting and no object creation passed");return 0;
  }catch(const std::exception& e) {
    if(owned)CloseHandle(owned);if(other)CloseHandle(other);
    SetEnvironmentVariableA("GK3HD_FRAME_SESSION",length?previous:nullptr);
    std::fprintf(stderr,"%s\n",e.what());return 1;
  }
}
