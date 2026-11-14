#pragma once

// Native-game shortcut consumer capability. Included while the admission mutex
// is available; callers below serialize it with the original receiver cut.
using Gk3hdShortcutOwner=uint64_t (__cdecl*)();
struct Gk3hdNativeShortcutState {
  Gk3hdShortcutOwner query=nullptr;
  DWORD thread=0;
  uint64_t admission=0,owner=0,through=0;
  uint32_t mask=0;
  bool selected=false,armed=false;
};
static Gk3hdNativeShortcutState g_nativeShortcuts;
static constexpr uint32_t Gk3hdShortcutOverride=0x80000000u;

// These helpers run under g_controllerFrameMutex. The native query only reads
// its game-thread graph and atomic lifetime, never calls OpenXR or the receiver.
static uint64_t Gk3hdShortcutOwnerNow() {
  return g_nativeShortcuts.query&&g_nativeShortcuts.thread==GetCurrentThreadId()
    ?g_nativeShortcuts.query():0;
}
static void Gk3hdChangeShortcutOwner(uint64_t owner) {
  if(g_controllerFrame.setOwner(owner)&&udpReader)udpReader->RetireControllerEvents();
}
static void Gk3hdPrepareShortcutAdmission() {
  if(g_nativeShortcuts.query)Gk3hdChangeShortcutOwner(Gk3hdShortcutOwnerNow());
}
static void Gk3hdAdmittedShortcuts() {
  if(!g_nativeShortcuts.query)return;
  const auto info=g_controllerFrame.info();
  g_nativeShortcuts.admission=info.admission;g_nativeShortcuts.owner=info.owner;
  g_nativeShortcuts.through=0;g_nativeShortcuts.mask=0;g_nativeShortcuts.selected=false;
  g_nativeShortcuts.armed=info.owner!=0;
}
static bool Gk3hdShortcutProfileKnown() {
  std::lock_guard<std::mutex> lock(rt::g_controllerMutex);
  const auto profile=rt::g_pathStrings.find(rt::g_activeProfile);
  return profile!=rt::g_pathStrings.end()&&
    profile->second=="/interaction_profiles/oculus/touch_controller";
}
static uint32_t Gk3hdShortcutMask(const WxrHostState& state,uint32_t pressed) {
  // This first consumer follows the actual Touch bindings used by the Android
  // host. Other profiles keep normal Actions; do not guess their button map.
  std::lock_guard<std::mutex> lock(rt::g_controllerMutex);
  const auto profile=rt::g_pathStrings.find(rt::g_activeProfile);
  if(profile==rt::g_pathStrings.end()||
     profile->second!="/interaction_profiles/oculus/touch_controller")return 0;
  bool valid[2]{};
  for(const auto& pose:state.poses) {
    const auto space=static_cast<XrSpace>(uint32_t(pose.space));
    const auto found=rt::g_controllerSpaces.find(space);
    if(found==rt::g_controllerSpaces.end()||(pose.locationFlags&3)!=3)continue;
    if(found->second==1||found->second==2)valid[found->second-1]=true;
  }
  if((valid[0]&&(pressed&(1u<<9)))||(valid[1]&&(pressed&(1u<<11))))return 2;
  if(valid[0]&&(pressed&(1u<<1)))return 4;
  if((valid[0]&&(pressed&(1u<<8)))||(valid[1]&&(pressed&(1u<<10))))return 8;
  return 0;
}

// Register a native query, read one immutable decision, then acknowledge only
// after the enclosing native input transaction returns. No XrSession or C++
// object crosses this ABI; standard OpenXR action state remains independent.
extern "C" __declspec(dllexport) uint32_t __stdcall
Gk3hdControllerShortcutsV1(uint32_t operation,void* payload) {
  std::lock_guard<std::mutex> lock(g_controllerFrameMutex);
  auto& state=g_nativeShortcuts;
  if(operation==1) {
    if(!payload)return 0;
    const auto query=reinterpret_cast<Gk3hdShortcutOwner>(payload);
    if(state.query&&(state.thread!=GetCurrentThreadId()||state.query!=query))return 0;
    state.query=query;state.thread=GetCurrentThreadId();return 1;
  }
  if(!state.query||state.thread!=GetCurrentThreadId()||payload||
     (operation!=2&&operation!=3))return 0;
  const auto owner=Gk3hdShortcutOwnerNow();
  const auto info=g_controllerFrame.info();
  const bool same=owner&&owner==state.owner&&info.owner==owner&&
    info.admission==state.admission;
  if(!same) {
    Gk3hdChangeShortcutOwner(owner);state.through=0;state.mask=0;
    return operation==2&&state.armed?Gk3hdShortcutOverride:0;
  }
  if(operation==3) {
    if(state.through)g_controllerFrame.acknowledge(owner,info.admission,state.through);
    state.through=0;state.mask=0;state.selected=true;return 1;
  }
  if(!Gk3hdShortcutProfileKnown())return 0;
  const auto now=std::chrono::duration_cast<std::chrono::nanoseconds>(
    std::chrono::steady_clock::now().time_since_epoch()).count();
  const auto& events=g_controllerFrame.events();
  if(!events.empty()&&(now<events.front().received||
                      now-events.front().received>=250000000)) {
    state.through=events.back().sequence;state.mask=0;state.selected=true;
  }
  if(!state.selected) {
    state.selected=true;
    for(const auto& event:events) {
      state.through=event.sequence;
      state.mask=Gk3hdShortcutMask(event.state,event.pressed);
      if(state.mask)break;
    }
  }
  return Gk3hdShortcutOverride|state.mask;
}
#if defined(_M_IX86)
#pragma comment(linker,"/EXPORT:Gk3hdControllerShortcutsV1=_Gk3hdControllerShortcutsV1@8")
#endif
