// Optional standalone provider. Ordinary Windows/Linux and PC-VR graphs stay native.
#include "movie_channel.h"
#include <amstream.h>
#include <array>
#include <algorithm>
#include <map>
#include <memory>
#include <mutex>
#include <atomic>

extern "C" HRESULT WINAPI Gk3hdSetMovieState(IAMMultiMediaStream*,STREAM_STATE);
namespace {
using Complete=void (__thiscall*)(void*,int);
using Close=void (__thiscall*)(void*);
using Destroy=void* (__thiscall*)(void*,unsigned);
struct Movie {
  void** original=nullptr;
  std::array<void*,24> table{};
  std::unique_ptr<gk3hd::movies::Channel> channel;
  std::string name;
  uint64_t generation=0;
  Complete complete=nullptr;
  std::string lastState;
};
static_assert(sizeof(void*)==4,"GK3 movie object is a Win32 ABI");
std::recursive_mutex mutex;
std::map<void*,std::unique_ptr<Movie>> movies;
uint32_t generation=0;
std::atomic<uint32_t> externalMovie{0};
Movie* find(void* owner){auto i=movies.find(owner);return i==movies.end()?nullptr:i->second.get();}
std::string command(const Movie& movie,const char* operation){return std::string(operation)+" "+std::to_string(movie.generation);}
bool open(Movie& movie) {
  if(generation==UINT32_MAX)return false;
  movie.channel=std::make_unique<gk3hd::movies::Channel>(gk3hd::movies::endpoint());movie.generation=++generation;
  gk3hd::movies::Status state;
  return gk3hd::movies::status(movie.channel->command(command(movie,"OPEN")+" "+movie.name),movie.generation,state)&&state.state=="READY";
}
void stop(Movie& movie)noexcept {
  try{if(movie.channel)movie.channel->command(command(movie,"CLOSE"));}catch(...){OutputDebugStringA("GK3HD native movie Close disconnected\n");}
  movie.channel.reset();
  uint32_t expected=static_cast<uint32_t>(movie.generation);
  externalMovie.compare_exchange_strong(expected,0);
}
HRESULT __fastcall start(void* owner,void*)noexcept {
  std::lock_guard<std::recursive_mutex> lock(mutex);Movie* movie=find(owner);if(!movie)return E_FAIL;
  OutputDebugStringA("GK3HD native movie Start\n");
  try {if(!movie->channel&&!open(*movie)){stop(*movie);return E_FAIL;}movie->channel->command(command(*movie,"PLAY"));externalMovie=static_cast<uint32_t>(movie->generation);return S_OK;}
  catch(...){stop(*movie);return E_FAIL;}
}
HRESULT __fastcall pause(void* owner,void*)noexcept {
  std::lock_guard<std::recursive_mutex> lock(mutex);Movie* movie=find(owner);if(!movie||!movie->channel)return E_FAIL;
  try{movie->channel->command(command(*movie,"PAUSE"));return S_OK;}catch(...){stop(*movie);return E_FAIL;}
}
HRESULT __fastcall halted(void* owner,void*)noexcept {
  std::lock_guard<std::recursive_mutex> lock(mutex);Movie* movie=find(owner);if(movie)stop(*movie);return S_OK;
}
unsigned char __fastcall update(void* owner,void*)noexcept {
  std::lock_guard<std::recursive_mutex> lock(mutex);Movie* movie=find(owner);if(!movie)return 0;
  bool running=false;
  try {
    gk3hd::movies::Status state;
    bool valid=movie->channel&&gk3hd::movies::status(movie->channel->command(command(*movie,"STATE")),movie->generation,state);
    if(valid&&state.state!=movie->lastState){movie->lastState=state.state;OutputDebugStringA(("GK3HD native movie state "+state.state+"\n").c_str());}
    if(valid&&state.state=="ENDED")OutputDebugStringA("GK3HD native movie reached EOF\n");
    running=valid&&state.state!="ENDED"&&state.state!="FAILED";
  }
  catch(...){OutputDebugStringA("GK3HD native movie status disconnected\n");}
  if(running)return 1;
  Complete complete=movie->complete;complete(owner,1);return 0; // Completion may unload this object.
}
// The native Draw thiscall has two stack arguments (ret 8), even though the
// host cinema does not consume either. Preserve that ABI when replacing it.
void __fastcall draw(void*,void*,void*,void*)noexcept {}
void __fastcall times(void* owner,void*,uint32_t* position,uint32_t* duration)noexcept {
  if(!position||!duration)return;
  *position=*duration=0;
  std::lock_guard<std::recursive_mutex> lock(mutex);Movie* movie=find(owner);
  if(!movie||!movie->channel)return;
  try {
    gk3hd::movies::Clock clock;
    if(gk3hd::movies::clock(movie->channel->command(command(*movie,"CLOCK")),movie->generation,clock)) {
      *position=clock.position;*duration=clock.duration;
    }
  }catch(...){OutputDebugStringA("GK3HD native movie clock disconnected\n");}
}
std::unique_ptr<Movie> detach(void* owner) {
  auto found=movies.find(owner);if(found==movies.end())return nullptr;
  auto movie=std::move(found->second);movies.erase(found);*reinterpret_cast<void***>(owner)=movie->original;stop(*movie);return movie;
}
void __fastcall close(void* owner,void*)noexcept {
  std::lock_guard<std::recursive_mutex> lock(mutex);auto movie=detach(owner);if(movie)reinterpret_cast<Close>(movie->original[0x30/4])(owner);
}
void* __fastcall destroy(void* owner,void*,unsigned flags)noexcept {
  std::lock_guard<std::recursive_mutex> lock(mutex);auto movie=detach(owner);if(!movie)return owner;
  reinterpret_cast<Close>(movie->original[0x30/4])(owner);
  return reinterpret_cast<Destroy>(movie->original[0])(owner,flags);
}
}
extern "C" __declspec(dllexport) uint32_t WINAPI Gk3hdNativeMovieOwner()noexcept {
  return externalMovie.load();
}
extern "C" __declspec(dllexport) BOOL WINAPI Gk3hdAttachNativeMovie(void* owner,Complete complete)noexcept {
  std::lock_guard<std::recursive_mutex> lock(mutex);
  if(find(owner))return TRUE;
  // Invoked only by the validated fullscreen-replacement layout hook. This
  // component owns neither the executable's addresses nor its scene selection.
  if(!owner||!complete||IsBadReadPtr(owner,0x68))return FALSE;
  auto original=*reinterpret_cast<void***>(owner);
  if(!original||IsBadReadPtr(original-1,24*sizeof(void*)))return FALSE;
  const char* name=static_cast<const char*>(owner)+8;size_t count=0;
  while(count<31&&name[count])count++;
  if(count<11||count>30)return FALSE;
  std::string alias(name,count);
  if(alias.rfind("GK3HD-",0)!=0||alias.substr(alias.size()-4)!=".AVI")return FALSE;
  for(char c:alias)if(!((c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='-'||c=='_'||c=='.'))return FALSE;
  try {
    // Leave ordinary Windows/Linux and PC-VR playback untouched without a provider.
    if(!std::filesystem::is_regular_file(gk3hd::movies::endpoint()))return FALSE;
    auto fields=reinterpret_cast<void**>(owner);
    auto stream=static_cast<IAMMultiMediaStream*>(fields[0x54/4]);
    const bool wasRunning=(*reinterpret_cast<unsigned*>(static_cast<char*>(owner)+0x34)&3)==1;
    struct RestoreGraph {
      IAMMultiMediaStream* stream;bool running;
      ~RestoreGraph(){if(running)try{if(FAILED(Gk3hdSetMovieState(stream,STREAMSTATE_RUN)))OutputDebugStringA("GK3HD graph rollback failed\n");}catch(...){OutputDebugStringA("GK3HD graph rollback exception\n");}}
    } restore{stream,wasRunning};
    if(FAILED(Gk3hdSetMovieState(stream,STREAMSTATE_STOP)))return FALSE;
    OutputDebugStringA("GK3HD translated graph stopped before native preparation\n");
    auto movie=std::make_unique<Movie>();movie->name=alias;movie->original=original;movie->complete=complete;
    if(!open(*movie))return FALSE; // RestoreGraph resumes an original running graph.
    std::copy(original-1,original+23,movie->table.begin());
    auto slot=[&](unsigned offset,void* value){movie->table[1+offset/4]=value;};
    slot(0,reinterpret_cast<void*>(destroy));slot(0x30,reinterpret_cast<void*>(close));slot(0x34,reinterpret_cast<void*>(start));slot(0x38,reinterpret_cast<void*>(pause));slot(0x3c,reinterpret_cast<void*>(start));slot(0x40,reinterpret_cast<void*>(update));slot(0x44,reinterpret_cast<void*>(draw));slot(0x48,reinterpret_cast<void*>(halted));
    slot(0x54,reinterpret_cast<void*>(times));
    auto inserted=movies.emplace(owner,std::move(movie)).first;
    restore.running=false; // Native ownership accepted; do not resume retired COM objects.
    OutputDebugStringA("GK3HD native movie accepted after translated graph stop\n");
    // Native Close's exact COM order, preserving its independent logical-size
    // surface. Start/Update/Draw will no longer touch the retired graph.
    for(unsigned offset:{0x5cu,0x58u,0x54u})if(fields[offset/4]){static_cast<IUnknown*>(fields[offset/4])->Release();fields[offset/4]=nullptr;}
    OutputDebugStringA("GK3HD translated movie references retired\n");
    *reinterpret_cast<void***>(owner)=inserted->second->table.data()+1;
    if((*reinterpret_cast<unsigned*>(static_cast<char*>(owner)+0x34)&3)==1)start(owner,nullptr);
    OutputDebugStringA("GK3HD native fullscreen movie attached\n");return TRUE;
  }catch(...){OutputDebugStringA("GK3HD native movie unavailable; retaining desktop playback\n");return FALSE;}
}
