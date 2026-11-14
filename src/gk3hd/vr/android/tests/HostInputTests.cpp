#include "WinXrApiUDP.h"
#include <array>
#include <cstdlib>
#include <algorithm>
#include <fstream>
#include <iterator>

static void require(bool value,const char* message) {
    if(!value){std::cerr<<message<<std::endl;ExitProcess(3);}
}
static void packet(SOCKET socket,int frame) {
    std::array<char,136> bytes{};
    bytes[0]='W';bytes[1]='X';bytes[2]='R';bytes[3]=8;
    auto put=[&](size_t offset,const auto& value){std::memcpy(bytes.data()+offset,&value,sizeof(value));};
    float hz=90,one=1;int count=1,flags=15,buttons=1<<18,base=2;
    put(48,hz);put(52,frame);put(60,buttons);put(64,count);
    put(72,base);put(76,flags);put(104,one);
    sockaddr_in destination{};destination.sin_family=AF_INET;
    destination.sin_addr.s_addr=htonl(INADDR_LOOPBACK);destination.sin_port=htons(7872);
    require(sendto(socket,bytes.data(),int(bytes.size()),0,reinterpret_cast<sockaddr*>(&destination),sizeof(destination))==int(bytes.size()),"send failed");
}
int main(int argc,char** argv) {
    // Normal return exercises receiver retirement after the packet checks.
    WinXrApiUDP ownedReader;
    auto* reader=&ownedReader;
    require(reader->HasSocket(),"Preserve occupied localhost port; input test cannot run");
    SOCKET sender=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
    require(sender!=INVALID_SOCKET,"sender socket failed");
    packet(sender,1);WxrHostState state;
    require(reader->GetState(state)&&state.frameId==1,"initial packet unavailable");
    require(state.poses.size()==1&&state.poses[0].locationFlags==15&&state.buttons[18],"packet content changed");
    auto start=std::chrono::steady_clock::now();
    require(reader->GetState(state,true,1)&&state.frameId==1,"bounded missing-packet fallback changed identity");
    auto elapsed=std::chrono::steady_clock::now()-start;
    require(elapsed>=std::chrono::milliseconds(1),"missing host packet did not pace the frame");
    require(elapsed<std::chrono::milliseconds(250),"fresh wait unbounded");
    std::thread producer([&]{Sleep(2);packet(sender,2);});
    require(reader->GetState(state,true,1),"new-packet wait failed");
    producer.join();
    if(state.frameId!=2)require(reader->GetState(state,true,1),"late host packet failed");
    require(state.frameId==2&&state.poses[0].locationFlags==15,"new packet not consumed faithfully");
    Sleep(270);
    require(reader->GetState(state,true,2)&&state.frameId==2,"expiry changed packet identity");
    require(std::none_of(std::begin(state.buttons),std::end(state.buttons),[](bool x){return x;}),"stale controls retained");
    require(state.poses[0].locationFlags==0,"stale tracking promoted");
    packet(sender,3);
    require(reader->GetState(state,true,2)&&state.frameId==3&&state.poses[0].locationFlags==15,"fresh recovery failed");
    if(argc==2) {
        std::ifstream file(argv[1],std::ios::binary);
        std::vector<char> bytes((std::istreambuf_iterator<char>(file)),{});
        require(bytes.size()==256,"Missing Java exact-view lifetime packet");
        reader->StorePacket(bytes.data(),int(bytes.size()));
        require(reader->GetState(state)&&state.frameId==73&&state.stereo.present,"Exact-view wire not consumed");
        require(state.poses.size()==1&&state.poses[0].locationFlags==15,"Exact optics changed tracking flags");
        XrPosef head{{0,float(std::sqrt(.5)),0,float(std::sqrt(.5))},{1,2,3}};
        const auto left=gk3hd::standalone::hostEyeInSpace(head,state.stereo.eyes[0]);
        const auto right=gk3hd::standalone::hostEyeInSpace(head,state.stereo.eyes[1]);
        auto approx=[](float a,float b){require(std::abs(a-b)<1e-5f,"Head-space eye composition changed");};
        approx(left.pose.position.x,1.004f);approx(left.pose.position.y,2.002f);approx(left.pose.position.z,3.032f);
        approx(right.pose.position.x,1.005f);approx(right.pose.position.y,1.997f);approx(right.pose.position.z,2.967f);
        approx(left.pose.orientation.y,float(std::sin(.7853981633974483+.05)));
        approx(right.pose.orientation.y,float(std::sin(.7853981633974483-.07)));
        approx(left.fov.angleLeft,-.9f);approx(left.fov.angleRight,.7f);
        approx(right.fov.angleLeft,-.65f);approx(right.fov.angleDown,-.9f);
        auto rejected=[&](std::vector<char> bad){
            bool caught=false;try{reader->StorePacket(bad.data(),int(bad.size()));}catch(const std::exception&){caught=true;}
            require(caught,"Malformed exact-eye packet accepted");
            require(reader->GetState(state)&&state.frameId==73&&state.stereo.present,"Malformed update replaced good state");
        };
        auto shortPacket=bytes;shortPacket.pop_back();rejected(shortPacket);
        auto bad=bytes;float value=2;std::memcpy(bad.data()+196,&value,4);rejected(bad);
        // The optics extension never restores expired head/controller validity.
        Sleep(270);require(reader->GetState(state)&&state.poses[0].locationFlags==0&&state.stereo.present,"Optics bypassed tracking expiry");
        std::cout<<"Java-to-native exact views: canted eyes, asymmetric FOV, rotated head space, malformed update atomicity and expiry passed"<<std::endl;
    }
    closesocket(sender);
    std::cout<<"Actual loopback packet: initial state, bounded timeout, notification wake, identity, expiry and fresh recovery passed"<<std::endl;
    return 0;
}
