#pragma once
#ifdef _WIN32
#include <windows.h>
#include <cstdio>

namespace gk3hd::vr {
// Exceptional path only. Never create or reset another session's event. The
// launcher owns this random namespace and the lifetime of its game child.
inline void notifyStandaloneDeviceLost() noexcept {
  const DWORD previous=GetLastError();
  char token[33],name[96];
  const DWORD length=GetEnvironmentVariableA("GK3HD_FRAME_SESSION",token,sizeof(token));
  if(length==32) {
    bool valid=true;
    for(unsigned i=0;i<32;++i)
      valid=valid&&((token[i]>='0'&&token[i]<='9')||(token[i]>='a'&&token[i]<='f'));
    if(valid) {
      std::snprintf(name,sizeof(name),"Local\\GK3HD.RendererFault.%s",token);
      HANDLE event=OpenEventA(EVENT_MODIFY_STATE,FALSE,name);
      if(event) {SetEvent(event);CloseHandle(event);}
    }
  }
  SetLastError(previous);
}
}
#endif
