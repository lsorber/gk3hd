#include "controller_history.h"
#include <cstdio>
#include <cstring>
#include <limits>

namespace {
unsigned checks=0;
void require(bool value,const char* message) {
  ++checks;
  if(!value)throw std::runtime_error(message);
}
struct Pose {
  int space=0,baseSpace=0;
  uint32_t locationFlags=15;
  float pose[7]{};
};
struct State {
  float floats[12]{};
  int32_t frameId=0,recenterId=0;
  bool buttons[19]{};
  std::vector<Pose> poses;
};
using History=gk3hd::standalone::ControllerHistory<State,4>;
using Result=History::Result;
gk3hd::standalone::HostInputLifetime life(uint64_t epoch=1,uint64_t generation=1,
                                         bool focused=true,bool withdrawal=false,uint64_t source=1) {
  return {source,epoch,generation,true,focused,false,withdrawal};
}
State packet(uint32_t frame,bool trigger=false) {
  State state;std::memcpy(&state.frameId,&frame,4);
  state.buttons[18]=trigger;state.floats[6]=trigger?1.f:0.f;
  state.poses={{1,2,15,{0,1,2,0,0,0,1}},{3,2,15,{3,4,5,0,0,0,1}}};
  return state;
}
void run() {
  {
    History history;history.observe(life(1),packet(1),0);
    history.retirePending();
    require(history.observe(life(1),packet(2,true),1)==Result::Queued,
            "UI handoff swallowed the first new press");
    history.retirePending();
    require(history.observe(life(1),packet(3,true),2)==Result::Unchanged,
            "UI handoff turned an existing hold into a press");
    require(history.drain(3).events.empty(),"UI handoff retained old actions");
    require(history.observe(life(1),packet(4),4)==Result::Queued,
            "UI handoff lost a genuine release");
  }
  {
    History history;
    require(history.observe(life(1),packet(1),0)==Result::Baseline,"initial state generated an event");
    require(history.observe(life(1),packet(2,true),100)==Result::Queued,"press disappeared");
    require(history.observe(life(1),packet(3),200)==Result::Queued,"release disappeared");
    auto batch=history.drain(300);
    require(batch.events.size()==2,"completed tap was coalesced");
    require(batch.events[0].frame==2&&batch.events[0].state.buttons[18]&&
            batch.events[1].frame==3&&!batch.events[1].state.buttons[18],"tap order or level changed");
    require(batch.events[0].sequence<batch.events[1].sequence,"event identity repeated");
    require(batch.events[0].pressed==(1u<<18)&&!batch.events[0].released&&
            !batch.events[1].pressed&&batch.events[1].released==(1u<<18),
            "Observed down/up edges were not retained explicitly");
    require(history.drain(301).events.empty(),"events consumed twice");
    for(uint32_t frame=4;frame<8;++frame)
      require(history.observe(life(1),packet(frame,!(frame&1)),frame*100)==Result::Queued,"multiple tap lost");
    require(history.drain(800).events.size()==4,"double tap lost transitions");
  }
  {
    History history;history.observe(life(1),packet(1,true),0);
    require(history.drain(1).events.empty(),"initial held input invented a press");
    history.observe(life(1),packet(2),2);history.drain(3);
    auto source=packet(3,true);history.observe(life(1),source,4);
    source.poses[0].pose[0]=100;
    auto latest=packet(4,true);latest.poses[0].pose[0]=200;latest.floats[0]=.9f;
    require(history.observe(life(1),latest,5)==Result::Unchanged,"head/stick motion generated button history");
    auto batch=history.drain(6);
    require(batch.events.size()==1&&batch.events[0].state.poses[0].pose[0]==0,
            "event pose context aliased a later sample");
    require(batch.events[0].state.floats[0]==0&&latest.floats[0]==.9f,
            "event context replaced the latest continuous state");
  }
  {
    History history;history.observe(life(4),packet(10),100);history.observe(life(4),packet(11,true),101);
    require(history.observe(life(4),packet(11),102)==Result::Rejected,"duplicate packet changed history");
    require(history.observe(life(4),packet(9),103)==Result::Rejected,"older packet changed history");
    require(history.observe(life(3),packet(12),104)==Result::Rejected,"old source epoch accepted");
    auto batch=history.drain(105);
    require(batch.events.size()==1&&batch.events[0].frame==11,"rejected packet changed queued press");
    history.observe(life(4),packet(12),106);
    require(history.observe(life(5),packet(1,true),107)==Result::Baseline,"trusted new epoch not adopted");
    batch=history.drain(108);
    require(batch.events.empty(),"new source inherited old events or manufactured held press");
    require(history.observe(life(4),packet(99),109)==Result::Rejected,"previous epoch revived");
  }
  {
    History history;history.observe(life(1),packet(0xfffffffeu),0);
    require(history.observe(life(1),packet(0xffffffffu,true),1)==Result::Queued,"pre-wrap press rejected");
    require(history.observe(life(1),packet(0),2)==Result::Queued,"frame wrap rejected");
    require(history.observe(life(1),packet(0x80000000u),3)==Result::Rejected,"ambiguous half-range admitted");
    require(history.drain(4).events.size()==2,"wrap changed tap count");
  }
  {
    History history;history.observe(life(1),packet(1),0);history.observe(life(1),packet(2,true),1);
    auto next=packet(3);next.recenterId=1;
    require(history.observe(life(1),next,2)==Result::Barrier,"recenter did not retire history");
    require(history.drain(3).events.empty(),"pre-recenter press replayed");
    next=packet(4,true);next.recenterId=1;
    require(history.observe(life(1),next,4)==Result::Queued,"post-recenter press absent");
    next=packet(5);next.recenterId=1;next.poses[1].locationFlags=0;
    history.observe(life(1),next,5);
    require(history.drain(6).events.empty(),"tracking loss retained actions");
    next=packet(6,true);next.recenterId=1;history.observe(life(1),next,7);
    require(history.drain(8).events.empty(),"tracking recovery manufactured held press");
  }
  {
    History history;history.observe(life(1),packet(1),0);
    auto next=packet(2);std::reverse(next.poses.begin(),next.poses.end());
    require(history.observe(life(1),next,1)==Result::Unchanged,"pose ordering changed ownership");
    next=packet(3);for(auto& pose:next.poses)pose.locationFlags=3;
    require(history.observe(life(1),next,2)==Result::Unchanged,"active tracking confused with pose validity");
    next=packet(4);next.poses[0].baseSpace=7;
    require(history.observe(life(1),next,3)==Result::Barrier,"reference-space owner change ignored");
  }
  {
    History history;history.observe(life(1),packet(1),0);
    for(uint32_t frame=2;frame<6;++frame)history.observe(life(1),packet(frame,!(frame&1)),frame);
    require(history.observe(life(1),packet(6,true),6)==Result::Overflow,"bounded history did not report overflow");
    auto batch=history.drain(7);
    require(batch.events.empty()&&batch.overflows==1,"overflow replayed a partial action train");
    history.observe(life(1),packet(7),8);history.observe(life(1),packet(8,true),9);
    require(history.drain(10).events.size()==1,"neutral recovery after overflow failed");
    history.observe(life(1),packet(9),11);
    require(history.drain(250000011).events.empty(),"expired action replayed");
    require(history.observe(life(1),packet(8,true),250000012)==Result::Rejected,"expiry allowed frame rollback");
  }
  {
    History history;history.observe(life(),packet(1,true),0);
    auto analog=packet(2,true);analog.floats[6]=.75f;
    require(history.observe(life(),analog,1)==Result::Queued,"Changed analog context was not retained");
    auto batch=history.drain(2);
    require(batch.events.size()==1&&!batch.events[0].pressed&&!batch.events[0].released&&
            batch.events[0].state.buttons[18],"Analog change turned an initial held button into a new press");
    auto mixed=packet(3);mixed.buttons[1]=mixed.buttons[10]=true;
    history.observe(life(),mixed,3);batch=history.drain(4);
    require(batch.events.size()==1&&batch.events[0].pressed==((1u<<1)|(1u<<10))&&
            batch.events[0].released==(1u<<18),"Simultaneous independent edges changed identity");
  }
  {
    History history;history.observe(life(1),packet(1),100);history.observe(life(1),packet(2,true),101);
    require(history.observe(life(1),packet(3),99)==Result::Barrier,"backward clock kept queued actions");
    require(history.drain(99).events.empty(),"clock discontinuity replayed event");
    history.observe(life(1),packet(4,true),102);
    require(history.drain(100).events.empty(),"backward drain clock replayed event");
    history.observe(life(1),packet(5),103);history.observe(life(1),packet(6,true),104);
    history.retire();
    require(history.drain(105).events.empty(),"explicit ownership retirement replayed input");
  }
  {
    History history;
    history.observe(life(),packet(10),0);
    history.observe(life(),packet(11,true),1);
    require(history.observe(life(1,2,false,true),packet(11),2)==Result::Barrier,
            "same-frame focus withdrawal retained queued press");
    auto batch=history.drain(3);
    require(batch.events.empty(),"withdrawn action reached consumer");
    const auto retired=batch.generation;
    require(history.observe(life(),packet(12),4)==Result::Rejected,
            "late focused generation undid pause");
    require(history.observe(life(1,2,false),packet(12,true),5)==Result::Unchanged,
            "unfocused sample queued controls");
    require(history.observe(life(1,3),packet(13,true),6)==Result::Baseline,
            "resume did not establish a new control baseline");
    require(history.drain(7).events.empty(),"resume fabricated held press");
    history.observe(life(1,3),packet(14),8);
    history.observe(life(1,3),packet(15,true),9);
    require(history.observe(life(1,3,true,false,2),packet(16),10)==Result::Rejected,
            "foreign source changed action ownership");
    batch=history.drain(11);
    require(batch.generation>retired&&batch.events.size()==2,
            "recovery lost new transitions or foreign packet erased them");
    history.observe(life(1,3),packet(16),12);
    require(history.observe(life(2,4),packet(1,true),13)==Result::Baseline,
            "new explicit pose epoch could not reset sequence");
    require(history.drain(14).events.empty(),"new epoch inherited queued actions");
    require(history.observe(life(1,5),packet(99),15)==Result::Rejected,
            "higher input generation revived an older pose epoch");
    history.observe(life(2,4),packet(2),16);
    history.observe(life(2,4),packet(3,true),17);
    require(history.observe(life(2,3),packet(4),18)==Result::Rejected,
            "older input generation admitted a new frame");
    require(history.drain(19).events.size()==2,"rejected generation changed pending actions");
  }
  {
    History history;history.observe(life(1),packet(1),0);history.observe(life(1),packet(2,true),1);
    auto bad=packet(3);bad.floats[6]=(std::numeric_limits<float>::quiet_NaN)();
    require(history.observe(life(1),bad,2)==Result::Invalid,"non-finite analog accepted");
    require(history.drain(3).events.empty(),"invalid control sample retained queued input");
    bad=packet(4);bad.poses.push_back(bad.poses[0]);
    require(history.observe(life(1),bad,4)==Result::Invalid,"duplicate pose owner accepted");
    bad=packet(5);bad.poses[0].locationFlags=16;
    require(history.observe(life(1),bad,5)==Result::Invalid,"unknown location flags accepted");
    bad=packet(6);bad.poses.resize(257);
    require(history.observe(life(1),bad,6)==Result::Invalid,"unbounded pose history accepted");
    require(history.observe(life(0),packet(7),7)==Result::Rejected,"missing source ownership accepted");
  }
}
}
int main() {
  try {run();std::printf("controller history: %u behavior checks passed\n",checks);return 0;}
  catch(const std::exception& e){std::fprintf(stderr,"FAIL: %s\n",e.what());return 1;}
}
