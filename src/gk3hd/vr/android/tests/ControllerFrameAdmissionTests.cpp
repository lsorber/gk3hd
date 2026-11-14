// Real parsed receiver states and atomic cuts, not a replacement state machine.
#include "WinXrApiUDP.h"
#include "controller_admission.h"
#include <array>
#include <cstdio>

static unsigned checks=0;
static void require(bool value,const char* text) {
  ++checks;if(!value){std::fprintf(stderr,"FAIL: %s\n",text);ExitProcess(3);}
}
static void packet(WinXrApiUDP& receiver,int frame,bool down,uint64_t generation=1,
                   bool focus=true,bool withdrawal=false) {
  std::array<char,168> bytes{};bytes[0]='W';bytes[1]='X';bytes[2]='R';bytes[3]=10;
  auto put=[&](size_t offset,const auto& value){std::memcpy(bytes.data()+offset,&value,sizeof(value));};
  const float level=down?1.f:0.f,one=1,hz=120;const uint32_t count=1,base=2,valid=15;
  const uint32_t buttons=down?1u<<10:0u,magic=0x3146494cu,flags=(focus?1u:0u)|(withdrawal?4u:0u);
  const uint64_t source=1,epoch=1;
  put(28,level);put(48,hz);put(52,frame);put(60,buttons);put(64,count);
  put(72,base);put(76,valid);put(104,one);put(136,magic);put(140,flags);
  put(144,source);put(152,epoch);put(160,generation);
  receiver.StorePacket(bytes.data(),int(bytes.size()));
}
int main() {
  using Admission=gk3hd::standalone::ControllerFrameAdmission<WxrHostState>;
  WinXrApiUDP ownedReceiver;auto* receiver=&ownedReceiver;if(!receiver->HasSocket())ExitProcess(77);
  Admission admitted;WxrHostState latest;
  auto owner=[&](uint64_t identity){if(admitted.setOwner(identity))receiver->RetireControllerEvents();};
  auto cut=[&](){WinXrApiUDP::ControllerEvents batch;
    require(receiver->GetInputFrame(latest,batch),"Receiver admission failed");
    const auto now=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
    admitted.admit(latest,std::move(batch),now);return admitted.read();};
  owner(1);packet(*receiver,1,false);require(cut().events.empty(),"Baseline invented action");
  packet(*receiver,2,true);packet(*receiver,3,false);
  const auto first=cut();require(first.events.size()==2,"Complete shortcut tap lost at runtime cut");
  require(first.poseFrame==3&&!latest.buttons[10],"Retained input falsified latest held/pose");
  require(first.events[0].frame==2&&first.events[0].state.buttons[10]&&
          first.events[1].frame==3&&!first.events[1].state.buttons[10],"Original event context changed");
  require(admitted.read().events.size()==2,"Query consumed input");
  require(!admitted.acknowledge(2,first.admission,first.events[0].sequence),"Foreign owner acknowledged input");
  require(!admitted.acknowledge(1,first.admission+1,first.events[0].sequence),"Future frame acknowledged input");
  packet(*receiver,4,false);const auto second=cut();
  require(second.events.size()==2&&second.events[0].sequence==first.events[0].sequence,
          "Unacknowledged input vanished or changed identity at next render frame");
  require(!admitted.acknowledge(1,first.admission,first.events[0].sequence),"Stale frame consumed current input");
  require(admitted.acknowledge(1,second.admission,first.events[0].sequence),"Exact action not acknowledged");
  require(admitted.read().events.size()==1&&!admitted.read().events[0].state.buttons[10],"Acknowledgement erased the next edge");
  require(!admitted.acknowledge(1,second.admission,first.events[0].sequence),"Action acknowledged twice");
  packet(*receiver,5,true);packet(*receiver,6,false);const auto more=cut();
  require(more.events.size()==3&&more.events.back().frame==6,"New arrival replaced pending release or tap");
  require(admitted.acknowledge(1,more.admission,more.events.back().sequence),"Whole accepted prefix not retired");
  require(admitted.read().events.empty(),"Consumed prefix replayed");
  require(first.events.size()==2&&first.events[0].state.buttons[10],"Later cut mutated prior returned frame");
  packet(*receiver,7,true);packet(*receiver,8,false);owner(2);
  require(cut().events.empty(),"Old scene actions leaked into new owner");
  packet(*receiver,9,false);cut();packet(*receiver,10,true);packet(*receiver,11,false);
  require(cut().events.size()==2,"New owner never rearmed");
  packet(*receiver,11,false,2,false,true);
  require(cut().events.empty()&&latest.frameId==11&&!latest.inputLifetime.focused,"Focus withdrawal replayed action or relabelled pose");
  packet(*receiver,12,true,3);require(cut().events.empty(),"Held resume invented an edge");
  packet(*receiver,13,false,3);packet(*receiver,14,true,3);require(cut().events.size()==2,"Focus recovery lost new edges");
  Sleep(270);require(cut().events.empty(),"New admission renewed old action age");
  owner(0);packet(*receiver,15,false,3);packet(*receiver,16,true,3);
  require(cut().events.empty(),"Disabled capability delivered actions");
  owner(3);packet(*receiver,17,false,3);const auto rearmed=cut();
  require(rearmed.events.size()==1&&rearmed.events[0].released==(1u<<10),
          "New owner lost the genuinely observed release");
  require(admitted.acknowledge(3,rearmed.admission,rearmed.events[0].sequence),
          "New owner could not retire its release before the capacity control");
  for(int frame=18;frame<50;++frame)packet(*receiver,frame,!(frame&1),3);
  const auto full=cut();require(full.events.size()==32,"Bounded admitted batch lost valid edges");
  packet(*receiver,50,true,3);packet(*receiver,51,false,3);const auto overflow=cut();
  require(overflow.events.empty()&&overflow.overflows==full.overflows+1,
          "Unacknowledged batch overflow replayed a truncated action train or was not reported");
  packet(*receiver,52,true,3);require(cut().events.size()==1,"Overflow prevented a genuinely new action");
  std::printf("Atomic frame input: %u checks passed; retained taps, original context, prefix acknowledgements, scene/focus retirement and expiry\n",checks);
  std::fflush(stdout);
  return 0;
}
