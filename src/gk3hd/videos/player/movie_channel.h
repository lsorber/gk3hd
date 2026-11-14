#pragma once
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <filesystem>
#include <cstdint>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>

namespace gk3hd::movies {
class Channel {
  SOCKET socket_=INVALID_SOCKET;
  bool network_=false;
  std::string readLine() {
    std::string line;
    for(unsigned i=0;i<256;i++) {
      char c=0;if(recv(socket_,&c,1,0)!=1)throw std::runtime_error("Movie host disconnected");
      if(c=='\n')return line;if(c<32||c>126)throw std::runtime_error("Invalid movie host response");line+=c;
    }
    throw std::runtime_error("Oversized movie host response");
  }
public:
  explicit Channel(const std::filesystem::path& endpoint) {
    if(std::filesystem::file_size(endpoint)>256)throw std::runtime_error("Oversized movie endpoint");
    std::ifstream input(endpoint,std::ios::binary);std::string version,port,token,extra;
    if(!std::getline(input,version)||!std::getline(input,port)||!std::getline(input,token)||
       std::getline(input,extra)||version!="GK3HD-MOVIE1"||port.empty()||port.size()>5||token.size()!=32)
      throw std::runtime_error("Invalid movie endpoint");
    for(char c:port)if(c<'0'||c>'9')throw std::runtime_error("Invalid movie port");
    for(char c:token)if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')))throw std::runtime_error("Invalid movie session");
    unsigned number=std::stoul(port);if(!number||number>65535)throw std::runtime_error("Invalid movie port");
    WSADATA data{};if(WSAStartup(MAKEWORD(2,2),&data))throw std::runtime_error("Movie socket initialization failed");network_=true;
    try {
      socket_=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);if(socket_==INVALID_SOCKET)throw std::runtime_error("Movie socket failed");
      DWORD timeout=6500;setsockopt(socket_,SOL_SOCKET,SO_RCVTIMEO,reinterpret_cast<char*>(&timeout),sizeof(timeout));setsockopt(socket_,SOL_SOCKET,SO_SNDTIMEO,reinterpret_cast<char*>(&timeout),sizeof(timeout));
      BOOL immediate=TRUE;setsockopt(socket_,IPPROTO_TCP,TCP_NODELAY,reinterpret_cast<char*>(&immediate),sizeof(immediate));
      sockaddr_in address{};address.sin_family=AF_INET;address.sin_port=htons(static_cast<u_short>(number));inet_pton(AF_INET,"127.0.0.1",&address.sin_addr);
      if(connect(socket_,reinterpret_cast<sockaddr*>(&address),sizeof(address)))throw std::runtime_error("Movie host unavailable");
      if(command("HELLO "+token)!="OK 1")throw std::runtime_error("Movie session rejected");
    }catch(...){close();throw;}
  }
  Channel(const Channel&)=delete;Channel& operator=(const Channel&)=delete;
  ~Channel(){close();}
  void close()noexcept {if(socket_!=INVALID_SOCKET){closesocket(socket_);socket_=INVALID_SOCKET;}if(network_){WSACleanup();network_=false;}}
  std::string command(const std::string& text) {
    if(text.empty()||text.size()>254||text.find_first_of("\r\n")!=std::string::npos)throw std::runtime_error("Invalid movie command");
    std::string bytes=text+'\n';size_t sent=0;
    while(sent<bytes.size()){int n=send(socket_,bytes.data()+sent,static_cast<int>(bytes.size()-sent),0);if(n<=0)throw std::runtime_error("Movie send failed");sent+=n;}
    return readLine();
  }
};
struct Status {
  std::string state;
  int width=0,height=0,duration=0;
};
struct Clock {
  uint32_t position=0,duration=0;
};
inline bool clock(const std::string& text,uint64_t generation,Clock& value) {
  std::istringstream in(text);std::string label,extra;uint64_t returned=0,position=0,duration=0;
  if(!(in>>label>>returned>>position>>duration)||label!="CLOCK"||returned!=generation||
     in>>extra||!duration||duration>INT32_MAX||position>duration)return false;
  // This provider replaces Bink story movies. Their game/caption clock uses
  // milliseconds (the original Bink method multiplies seconds by 1000), not
  // the unconverted IMediaSeeking units exposed by the old AVI implementation.
  value.position=static_cast<uint32_t>(position);
  value.duration=static_cast<uint32_t>(duration);return true;
}
inline bool status(const std::string& text,uint64_t generation,Status& value) {
  std::istringstream in(text);std::string label,extra;uint64_t returned=0;
  if(!(in>>label>>returned>>value.state>>value.width>>value.height>>value.duration)||label!="STATE"||returned!=generation||in>>extra)return false;
  return value.width>0&&value.height>0&&value.width<=32768&&value.height<=32768&&value.duration>0;
}
inline std::filesystem::path endpoint() {
  wchar_t session[33]{},exe[32768]{};
  if(GetEnvironmentVariableW(L"GK3HD_FRAME_SESSION",session,33)!=32)throw std::runtime_error("No standalone movie session");
  for(wchar_t c:std::wstring(session))if(!((c>=L'0'&&c<=L'9')||(c>=L'a'&&c<=L'f')))throw std::runtime_error("Invalid standalone session");
  DWORD n=GetModuleFileNameW(nullptr,exe,32768);if(!n||n>=32768)throw std::runtime_error("No movie player directory");
  return std::filesystem::path(exe).parent_path()/(L"gk3hd-movie-"+std::wstring(session)+L".txt");
}
}
