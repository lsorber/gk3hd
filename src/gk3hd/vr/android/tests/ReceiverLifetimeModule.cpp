#include "WinXrApiUDP.h"
extern "C" __declspec(dllexport) int __cdecl Gk3hdReceiverLifetimeCycle() {
  WinXrApiUDP receiver;
  if (!receiver.HasSocket()) return 0;
  receiver.KillReceiver();receiver.KillReceiver();return !receiver.HasSocket();
}
#pragma comment(linker,"/EXPORT:Gk3hdReceiverLifetimeCycle=_Gk3hdReceiverLifetimeCycle")
