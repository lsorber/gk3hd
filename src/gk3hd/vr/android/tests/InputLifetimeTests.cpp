#include "host_input_lifetime.h"
#include "WinXrApiUDP.h"
#include <fstream>
#include <iterator>
#include <cstdio>

using namespace gk3hd::standalone;
static unsigned checks;
static void require(bool value,const char* text) {
    ++checks;if(!value){std::fprintf(stderr,"FAIL: %s\n",text);ExitProcess(3);}
}
static std::vector<char> file(const std::string& root,const char* name) {
    std::ifstream in(root+"/"+name,std::ios::binary);
    std::vector<char> bytes((std::istreambuf_iterator<char>(in)),{});
    require(bytes.size()==168,"Missing bounded Java lifetime datagram");return bytes;
}
template<class T> static void put(std::vector<char>& bytes,size_t offset,T value) {
    require(offset+sizeof(value)<=bytes.size(),"Fixture mutation exceeds packet");
    std::memcpy(bytes.data()+offset,&value,sizeof(value));
}
int main(int argc,char** argv) {
    InputSourceOrder order;
    HostInputLifetime a;a.present=true;a.source=11;a.poseEpoch=1;a.generation=1;a.focused=true;
    auto withdrawal=a;withdrawal.focused=false;withdrawal.withdrawal=true;withdrawal.generation=2;
    require(!order.accept(withdrawal,100),"Control-only notification bound a new source");
    require(order.accept(a,0xfffffffeu)&&order.accept(a,0xffffffffu)&&order.accept(a,0),"Frame wrap rejected");
    require(!order.accept(a,0)&&!order.accept(a,0xffffffffu),"Duplicate/older rendering packet accepted");
    require(order.accept(withdrawal,0xffffffffu),"Focus generation required a new rendering pose");
    require(!order.accept(withdrawal,0),"Duplicate withdrawal accepted");
    require(!order.accept(a,1),"Old focus generation resurrected controls");
    a.generation=3;require(!order.accept(a,0xffffffffu),"Focus generation rolled back a pose");
    require(order.accept(a,1),"Fresh focused pose did not recover");
    auto inconsistent=a;inconsistent.focused=false;
    require(!order.accept(inconsistent,2),"Focus changed without advancing its input generation");
    a.poseEpoch=2;require(order.accept(a,0xfffffff0u),"Explicit pose epoch did not permit a new frame sequence");
    auto foreign=a;foreign.source=12;
    require(!order.accept(foreign,0xfffffff1u),"Another host replaced a bound source");
    require(!order.accept(HostInputLifetime{},10),"Legacy packet bypassed source binding");
    a.poseEpoch=1;a.generation=100;
    require(!order.accept(a,100),"Old coordinate epoch accepted");
    if(argc!=2){std::printf("Input lifetime order checks: %u\n",checks);return 0;}
    WinXrApiUDP ownedReceiver;auto* receiver=&ownedReceiver;if(!receiver->HasSocket())ExitProcess(77);
    const auto first=file(argv[1],"focused.bin"),withdrawn=file(argv[1],"withdrawal.bin"),reset=file(argv[1],"new-epoch.bin");
    WxrHostState state;
    receiver->StorePacket(first.data(),int(first.size()));
    require(receiver->GetState(state)&&state.frameId==100&&state.inputLifetime.focused&&state.poses[0].pose[0]==1,"Initial real host packet changed");
    require(state.buttons[18]&&state.inputLifetime.present,"Focused controls/lifetime missing");
    receiver->LastOpenXRFrameID=100;
    Sleep(170);receiver->StorePacket(withdrawn.data(),int(withdrawn.size()));
    require(receiver->GetState(state)&&state.frameId==100&&state.poses[0].pose[0]==1&&!state.inputLifetime.focused,"Withdrawal invented or lost a pose");
    require(!state.buttons[18]&&state.floats[6]==0,"Withdrawal retained a trigger");
    receiver->StorePacket(first.data(),int(first.size()));
    require(receiver->GetState(state)&&!state.inputLifetime.focused,"Delayed focused packet undid pause");
    Sleep(110);require(receiver->GetState(state)&&state.poses[0].locationFlags==0,"Control-only message renewed old tracking age");
    receiver->StorePacket(reset.data(),int(reset.size()));
    require(receiver->GetState(state)&&state.frameId==3&&state.inputLifetime.focused&&state.poses[0].pose[0]==9,"Fresh reference epoch failed to recover");
    const auto source=state.inputLifetime.source,epoch=state.inputLifetime.poseEpoch,generation=state.inputLifetime.generation;
    auto rejected=[&](std::vector<char> packet,bool malformed) {
        bool threw=false;try{receiver->StorePacket(packet.data(),int(packet.size()));}catch(const std::invalid_argument&){threw=true;}
        require(threw==malformed,"Wrong malformed/stale packet outcome");
        require(receiver->GetState(state)&&state.frameId==3&&state.inputLifetime.source==source&&
            state.inputLifetime.poseEpoch==epoch&&state.inputLifetime.generation==generation&&state.poses[0].pose[0]==9,
            "Rejected update changed admitted input/tracking");
    };
    auto bad=reset;put(bad,144,source+1);rejected(bad,false);
    bad=reset;put(bad,152,epoch-1);put(bad,160,generation+100);rejected(bad,false);
    bad=reset;put(bad,52,int32_t(2));put(bad,160,generation+1);rejected(bad,false);
    bad=reset;bad.pop_back();rejected(bad,true);
    bad=reset;bad.push_back(0);rejected(bad,true);
    for(size_t offset:{size_t(144),size_t(152),size_t(160)}) {
        bad=reset;put(bad,offset,uint64_t(0));rejected(bad,true);
    }
    bad=reset;put(bad,140,uint32_t(9));rejected(bad,true);
    bad=reset;put(bad,140,uint32_t(5));rejected(bad,true);
    const auto inactive=file(argv[1],"unfocused.bin");receiver->StorePacket(inactive.data(),int(inactive.size()));
    require(receiver->GetState(state)&&state.frameId==4&&!state.inputLifetime.focused&&!state.buttons[18],"Unfocused full packet retained actions");
    std::printf("Actual Java/native input lifetime checks: %u; no pose-age renewal or scene-action acceptance claimed\n",checks);
    std::fflush(stdout);
    return 0;
}
