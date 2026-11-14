#pragma once
#include "controller_admission.h"

// Included after rt::g_session is defined. Match the runtime's
// existing serialized frame admission; protect custom queries and owner changes
// with the same lock so no old-owner cut can publish after retirement.
static std::mutex g_controllerFrameMutex;
static gk3hd::standalone::ControllerFrameAdmission<WxrHostState> g_controllerFrame;
#include "controller_shortcuts.h"
static void Gk3hdRetireControllerAdmission() {
  std::lock_guard<std::mutex> lock(g_controllerFrameMutex);
  g_nativeShortcuts={};g_controllerFrame={};if(udpReader)udpReader->RetireControllerEvents();
}
static bool Gk3hdReadControllerHost(WxrHostState& host) {
  std::lock_guard<std::mutex> lock(g_controllerFrameMutex);
  Gk3hdPrepareShortcutAdmission();
  WinXrApiUDP::ControllerEvents events;
  if(!udpReader->GetInputFrame(host,events,true,host.frameId))return false;
  const auto now=std::chrono::duration_cast<std::chrono::nanoseconds>(
    std::chrono::steady_clock::now().time_since_epoch()).count();
  g_controllerFrame.admit(host,std::move(events),now);
  Gk3hdAdmittedShortcuts();return true;
}
