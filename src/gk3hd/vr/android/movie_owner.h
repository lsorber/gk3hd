#pragma once
#include <windows.h>
#include <cstdint>

namespace gk3hd::standalone {
// The optional player owns the decision to retire native movie rendering.
// A missing export leaves all ordinary OpenXR composition unchanged.
inline uint32_t externalMovieOwner() {
    using Query=uint32_t (WINAPI*)();
    static Query query=nullptr;
    if(!query) {
        HMODULE player=GetModuleHandleW(L"gk3hd-videos.dll");
        if(player)query=reinterpret_cast<Query>(GetProcAddress(player,"_Gk3hdNativeMovieOwner@0"));
    }
    return query ? query() : 0;
}
}
