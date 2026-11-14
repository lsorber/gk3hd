// Exercise the production receiver using original parsed packet histories.
#include "WinXrApiUDP.h"
#include <array>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <thread>

static unsigned checks=0;
static void require(bool value,const char* message) {
  ++checks;
  if(!value){std::fprintf(stderr,"FAIL: %s\n",message);ExitProcess(3);}
}
static gk3hd::standalone::HostInputLifetime life(uint64_t epoch=1,uint64_t generation=1,
                                              bool focused=true,bool withdrawal=false,uint64_t source=1) {
  return {source,epoch,generation,true,focused,false,withdrawal};
}
static void packet(WinXrApiUDP& receiver,int frame,bool trigger,uint32_t flags=15,
                   gk3hd::standalone::HostInputLifetime lifetime=life()) {
  std::array<char,168> bytes{};
  bytes[0]='W';bytes[1]='X';bytes[2]='R';bytes[3]=10;
  auto put=[&](size_t offset,const auto& value){std::memcpy(bytes.data()+offset,&value,sizeof(value));};
  float level=trigger?1.f:0.f,ipd=.064f,fov=90,hz=90,one=1,position=float(frame);
  uint32_t buttons=trigger?1u<<18:0,count=1,space=1,base=2;
  put(28,level);put(36,ipd);put(40,fov);put(44,fov);put(48,hz);
  put(52,frame);put(60,buttons);put(64,count);
  put(68,space);put(72,base);put(76,flags);put(80,position);put(104,one);
  uint32_t magic=0x3146494cu,lifetimeFlags=(lifetime.focused?1u:0u)|(lifetime.withdrawal?4u:0u);
  put(136,magic);put(140,lifetimeFlags);put(144,lifetime.source);
  put(152,lifetime.poseEpoch);put(160,lifetime.generation);
  receiver.StorePacket(bytes.data(),int(bytes.size()));
}
static WinXrApiUDP::ControllerEvents take(WinXrApiUDP& receiver,WxrHostState* frozen=nullptr) {
  WxrHostState local;auto& latest=frozen?*frozen:local;
  WinXrApiUDP::ControllerEvents batch;
  require(receiver.GetInputFrame(latest,batch),"atomic input frame unavailable");
  for(const auto& event:batch.events)
    require(uint32_t(uint32_t(latest.frameId)-event.frame)<0x80000000u,
            "event is newer than its frozen input frame");
  return batch;
}
int main() {
  WinXrApiUDP ownedReceiver;auto* receiver=&ownedReceiver;
  if(!receiver->HasSocket())ExitProcess(77);
  WxrHostState latest;
  packet(*receiver,1,false);
  require(receiver->GetState(latest)&&latest.frameId==1,"initial pose unavailable");
  require(take(*receiver).events.empty(),"initial input invented a press");
  packet(*receiver,2,true);packet(*receiver,3,false);
  require(receiver->GetState(latest)&&latest.frameId==3&&!latest.buttons[18],"old control state delayed latest tracking");
  require(latest.poses[0].pose[0]==3,"latest head pose replaced by queued event");
  require(receiver->GetState(latest)&&latest.frameId==3,"pose query changed frame identity");
  auto batch=take(*receiver);
  require(batch.events.size()==2,"actual receiver lost the completed tap");
  require(batch.events[0].frame==2&&batch.events[0].state.buttons[18]&&
          batch.events[0].state.poses[0].pose[0]==2,"press context was relabelled with latest pose");
  require(batch.events[1].frame==3&&!batch.events[1].state.buttons[18],"release ordering changed");
  require(batch.events[0].pressed==(1u<<18)&&!batch.events[0].released&&
          batch.events[1].released==(1u<<18)&&!batch.events[1].pressed,
          "Actual parsed receiver did not preserve observed digital edges");
  require(take(*receiver).events.empty(),"receiver delivered tap twice");
  for(int frame=4;frame<8;++frame)packet(*receiver,frame,!(frame&1));
  packet(*receiver,6,true);
  require(receiver->GetState(latest)&&latest.frameId==7&&!latest.buttons[18],"older packet rolled tracking back");
  batch=take(*receiver);
  require(batch.events.size()==4,"double tap lost transitions");
  for(size_t i=0;i<batch.events.size();++i)
    require(batch.events[i].frame==4+i,"double tap order changed");
  const auto generation=batch.generation;
  packet(*receiver,8,true);packet(*receiver,9,false,0);
  batch=take(*receiver);
  require(batch.events.empty()&&batch.generation>generation,"tracking barrier replayed old input");
  packet(*receiver,10,true);
  require(take(*receiver).events.empty(),"tracking recovery invented a press");
  packet(*receiver,11,false);packet(*receiver,12,true);
  require(take(*receiver).events.size()==2,"neutral recovery lost new input");
  packet(*receiver,13,false);
  Sleep(270);
  require(receiver->GetState(latest)&&latest.frameId==13&&latest.poses[0].locationFlags==0,
          "expiry changed tracking identity or retained validity");
  require(take(*receiver).events.empty(),"expired event was replayed");
  packet(*receiver,14,false);packet(*receiver,15,true);packet(*receiver,16,false);
  receiver->RetireControllerEvents();
  batch=take(*receiver,&latest);
  require(batch.events.empty()&&batch.generation>generation&&latest.frameId==16&&
          latest.poses[0].locationFlags==15,"explicit retirement rewrote tracking or replayed input");
  packet(*receiver,17,true);
  batch=take(*receiver);
  require(batch.events.size()==1&&batch.events[0].frame==17&&
          batch.events[0].pressed==(1u<<18),"consumer handoff swallowed the first new press");
  packet(*receiver,18,false);packet(*receiver,19,true);
  require(take(*receiver).events.size()==2,"consumer recovery never rearmed input");
  packet(*receiver,20,false);packet(*receiver,21,true);packet(*receiver,22,false);
  auto frozen=take(*receiver,&latest);
  require(latest.frameId==22&&frozen.events.size()==3&&!latest.buttons[18],
          "atomic admission lost its current state or pending transitions");
  packet(*receiver,23,true);packet(*receiver,24,false);
  require(latest.frameId==22&&latest.poses[0].pose[0]==22&&
          frozen.events.back().frame==22&&!frozen.events.back().state.buttons[18],
          "arrival after admission mutated a frozen frame or event context");
  batch=take(*receiver,&latest);
  require(latest.frameId==24&&batch.events.size()==2&&batch.events[0].frame==23&&
          batch.events[1].frame==24,"next admission mixed old and newly arrived events");
  require(take(*receiver).events.empty(),"atomic frame admission delivered events twice");
  packet(*receiver,25,true);
  require(receiver->GetState(latest)&&receiver->GetState(latest)&&latest.frameId==25,
          "ordinary pose queries no longer preserve latest tracking");
  require(take(*receiver).events.size()==1,"ordinary pose queries consumed controller actions");
  // Exercise actual StorePacket/condition-variable admission on separate
  // threads. Acknowledge only the frozen cut, never a separately read state.
  std::atomic<int> admitted{25};
  const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(2);
  std::thread producer([&] {
    for(int frame=26;frame<=225;++frame) {
      while(admitted.load()<frame-1) {
        if(std::chrono::steady_clock::now()>=deadline)ExitProcess(4);
        std::this_thread::yield();
      }
      packet(*receiver,frame,(frame&1)!=0);
    }
  });
  size_t transitions=0;uint64_t sequence=0;
  while(admitted.load()<225) {
    require(std::chrono::steady_clock::now()<deadline,"concurrent frame admission stalled");
    WinXrApiUDP::ControllerEvents input;
    require(receiver->GetInputFrame(latest,input,true,admitted.load()),"waiting input admission failed");
    require(latest.poses[0].pose[0]==latest.frameId&&latest.buttons[18]==((latest.frameId&1)!=0),
            "concurrent admission mixed pose and current button state");
    for(const auto& event:input.events) {
      require(event.frame<=uint32_t(latest.frameId)&&event.sequence>sequence&&
              event.state.poses[0].pose[0]==event.frame,
              "concurrent event is newer, duplicated or relabelled");
      sequence=event.sequence;++transitions;
    }
    admitted.store(latest.frameId);
  }
  producer.join();
  require(transitions==200&&take(*receiver).events.empty(),
          "concurrent atomic admission lost or repeated a transition");
  packet(*receiver,226,false);packet(*receiver,227,true);
  packet(*receiver,227,false,15,life(1,2,false,true));
  batch=take(*receiver,&latest);
  require(latest.frameId==227&&!latest.buttons[18]&&latest.inputLifetime.generation==2&&
          !latest.inputLifetime.focused&&batch.events.empty(),
          "control-only focus withdrawal retained events or changed pose identity");
  packet(*receiver,228,true); // Delayed formerly focused packet.
  batch=take(*receiver,&latest);
  require(latest.frameId==227&&batch.events.empty(),"old focus generation revived input");
  packet(*receiver,228,true,15,life(1,2,false));
  batch=take(*receiver,&latest);
  require(latest.frameId==228&&!latest.buttons[18]&&batch.events.empty(),
          "unfocused packet retained controller actions");
  packet(*receiver,229,true,15,life(1,3));
  require(take(*receiver).events.empty(),"resume invented a held press");
  packet(*receiver,230,false,15,life(1,3));packet(*receiver,231,true,15,life(1,3));
  packet(*receiver,232,false,15,life(1,3,true,false,2));
  batch=take(*receiver,&latest);
  require(latest.frameId==231&&batch.events.size()==2,
          "foreign host changed newest pose or erased pending transitions");
  for(const auto& event:batch.events)
    require(event.state.inputLifetime.source==1&&event.state.inputLifetime.generation==3&&
            event.state.inputLifetime.poseEpoch==1,
            "event lost original host identity, generation or epoch");
  packet(*receiver,232,false,15,life(1,3));
  packet(*receiver,1,true,15,life(2,4));
  batch=take(*receiver,&latest);
  require(latest.frameId==1&&latest.inputLifetime.poseEpoch==2&&batch.events.empty(),
          "explicit tracking epoch inherited old actions or could not reset frame IDs");
  packet(*receiver,999,false,15,life(1,5));
  batch=take(*receiver,&latest);
  require(latest.frameId==1&&batch.events.empty(),"new generation revived retired tracking epoch");
  packet(*receiver,2,false,15,life(2,4));packet(*receiver,3,true,15,life(2,4));
  require(take(*receiver).events.size()==2,"post-epoch neutral recovery lost a fresh tap");
  std::printf("actual receiver event history: %u behavior checks passed\n",checks);
  std::fflush(stdout);return 0;
}
