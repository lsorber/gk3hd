#include "WinXrApiUDP.h"
#include <array>
#include <atomic>
#include <chrono>
#include <iostream>
#include <memory>
#include <stdexcept>

namespace {
void check(bool value,const char* message) {
  if (!value) throw std::runtime_error(message);
}
void sendPacket(SOCKET sender,int frame) {
  std::array<char,136> bytes{};bytes[0]='W';bytes[1]='X';bytes[2]='R';bytes[3]=8;
  auto put=[&](size_t offset,const auto& value){std::memcpy(bytes.data()+offset,&value,sizeof(value));};
  float hz=90,one=1;int count=1,flags=15,buttons=1<<18,base=2;
  put(48,hz);put(52,frame);put(60,buttons);put(64,count);put(72,base);put(76,flags);put(104,one);
  sockaddr_in target{};target.sin_family=AF_INET;target.sin_addr.s_addr=htonl(INADDR_LOOPBACK);target.sin_port=htons(7872);
  check(sendto(sender,bytes.data(),int(bytes.size()),0,reinterpret_cast<sockaddr*>(&target),sizeof(target))==int(bytes.size()),"Independent sender lost its Winsock lifetime");
}
}
int main(int argc,char** argv) {
  HANDLE finished=CreateEventW(nullptr,TRUE,FALSE,nullptr);if(!finished)return 2;
  std::thread watchdog([&]{if(WaitForSingleObject(finished,12000)!=WAIT_OBJECT_0){std::cerr<<"Receiver lifetime test timed out\n";ExitProcess(124);}});
  int result=1;WSADATA data{};bool startup=WSAStartup(MAKEWORD(2,2),&data)==0;
  SOCKET sender=INVALID_SOCKET;
  try {
    check(startup,"Independent Winsock initialization failed");
    sender=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);check(sender!=INVALID_SOCKET,"Independent sender failed");
    for(int i=0;i<32;++i) {
      auto reader=std::make_unique<WinXrApiUDP>();check(reader->HasSocket(),"Preserve occupied receiver port");
      reader->KillReceiver();reader->KillReceiver();
      sendPacket(sender,i+1);
    }
    for(int i=0;i<16;++i) {
      auto reader=std::make_unique<WinXrApiUDP>();check(reader->HasSocket(),"Port did not rebind after stop");
      sendPacket(sender,100+i);WxrHostState state;
      check(reader->GetState(state)&&state.frameId==100+i,"First packet not consumed faithfully");
      check(state.poses.size()==1&&state.poses[0].locationFlags==15&&state.buttons[18],"Packet properties changed");
      reader->KillReceiver();
      check(!reader->GetState(state),"Retired receiver returned its last packet");
    }
    {
      auto owner=std::make_unique<WinXrApiUDP>();check(owner->HasSocket(),"Port unavailable for conflict control");
      {auto conflict=std::make_unique<WinXrApiUDP>();check(!conflict->HasSocket(),"Conflicting receiver stole the port");}
      sendPacket(sender,300);WxrHostState state;check(owner->GetState(state)&&state.frameId==300,"Conflicting receiver damaged owner");
    }
    {
      auto reader=std::make_unique<WinXrApiUDP>();check(reader->HasSocket(),"Waiting-reader setup failed");
      std::atomic<bool> entered{false},available{true};
      std::thread waiting([&]{entered=true;WxrHostState state;available=reader->GetState(state);});
      while(!entered.load())Sleep(0);Sleep(2);reader->KillReceiver();waiting.join();
      check(!available.load(),"Pending reader published state after retirement");
    }
    check(argc==2,"Receiver module argument missing");
    for(int i=0;i<16;++i) {
      HMODULE module=LoadLibraryA(argv[1]);check(module!=nullptr,"Receiver module load failed");
      auto run=reinterpret_cast<int(__cdecl*)()>(GetProcAddress(module,"Gk3hdReceiverLifetimeCycle"));
      check(run!=nullptr,"Receiver module export missing");check(run()==1,"Receiver module cycle failed");
      check(FreeLibrary(module)!=FALSE,"Receiver module unload failed");
      WinXrApiUDP rebound;check(rebound.HasSocket(),"Unloaded receiver retained the port");
    }
    std::cout<<"Receiver lifetime: idle/early stop, packet fidelity, waiting readers, repeated stop, port conflict/reuse, independent Winsock and 16 module unloads passed\n";
    result=0;
  } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';}
  if(sender!=INVALID_SOCKET)closesocket(sender);if(startup)WSACleanup();
  SetEvent(finished);watchdog.join();CloseHandle(finished);return result;
}
