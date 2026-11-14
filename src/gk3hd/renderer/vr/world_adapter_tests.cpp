#include "world_adapter.h"
#include <cstdio>
#include <stdexcept>
#include <string>

namespace {
using namespace gk3hd::vr;
using Operation=world_bridge::Operation;
unsigned checks=0;
void require(bool ok,const char* reason) {
  if (!ok) throw std::runtime_error(reason);
  ++checks;
}
struct Fixture {
  std::vector<uint8_t> memory=std::vector<uint8_t>(0x100000);
  std::vector<std::string> events;
  std::vector<uint64_t> generations;
  std::vector<float> positions;
  uint32_t rows=0;
  int reject=-1,failAppend=-1;
  bool failBegin=false, rejectBegin=false, rejectPrepared=false, open=false;
  WorldAdapterConfig config{sizeof(WorldAdapterConfig),1,0x70000,0x80000,0x90000};
  WorldAdapter adapter;
  template<class T> void put(uint32_t address,const T& value) {
    std::memcpy(memory.data()+address,&value,sizeof(value));
  }
  void word(uint32_t address,uint32_t value) {put(address,value);}
  static bool equal(void* context,const WorldAdapter::SourceRange* ranges,size_t count) {
    auto& self=*static_cast<Fixture*>(context);
    for(size_t i=0;i<count;++i) {
      const auto& r=ranges[i];
      if(r.address>self.memory.size()||r.bytes>self.memory.size()-r.address||
         (r.expected&&std::memcmp(self.memory.data()+r.address,r.expected,r.bytes)))return false;
    }
    return true;
  }
  static bool read(void* context,uint32_t address,void* output,size_t bytes) {
    auto& self=*static_cast<Fixture*>(context);
    if (address>self.memory.size()||bytes>self.memory.size()-address) return false;
    std::memcpy(output,self.memory.data()+address,bytes);return true;
  }
  static int32_t submit(void* context,uint32_t device,Operation operation,const void* argument) {
    auto& self=*static_cast<Fixture*>(context);
    require(device==0xc0000||device==0xc1000,"wrong native device reached renderer");
    if (operation==Operation::Begin) {
      require(!self.open,"nested backend scope");
      self.events.push_back("begin");
      if (self.rejectBegin) return 1;
      self.open=true;self.rows=0;
      if (self.failBegin) return int32_t(0x80004005u);
      const auto& request=*static_cast<const world_bridge::Request*>(argument);
      self.generations.push_back(request.geometryKey);
      self.positions.push_back(static_cast<const WorldVertex*>(request.vertices)[2].xyz[0]);
      return 0;
    }
    require(self.open,"renderer operation without scope");
    if (operation==Operation::Cancel) {self.open=false;self.rows=0;self.events.push_back("cancel");return 0;}
    if (operation==Operation::Submit) {
      self.events.push_back("submit:"+std::to_string(self.rows));
      self.open=false;return 0;
    }
    const auto& draw=*static_cast<const world_bridge::Draw*>(argument);
    self.events.push_back(std::string(operation==Operation::Append?"append:":"prepared:")+std::to_string(draw.first));
    if (int(draw.first)==self.failAppend) return int32_t(0x80004005u);
    if (int(draw.first)==self.reject || (operation==Operation::AppendPrepared&&self.rejectPrepared)) return 1;
    ++self.rows;return 0;
  }
  Fixture(bool ranges=true): adapter(this,read,submit,ranges?equal:nullptr) {
    word(0x70000,0x71000);word(0x714e8,0xc0000);word(0x90000,1);
    word(0x40000,0x123456);word(0x400e8,0x10000);word(0x400f0,0x20000);
    word(0x400fc,0x42000);word(0x40120,4);word(0x40130,3);word(0x40144,0x30000);
    word(0x40060,0x61000);
    put(0x10000,std::array<float,12>{0,0,0,1,0,0,1,1,0,0,1,0});
    put(0x20000,std::array<float,8>{0,0,1,0,1,1,0,1});
    for (uint32_t sid=0;sid<3;++sid) {
      const uint32_t primitive=0x50000+sid*0x100;
      word(0x30000+sid*4,primitive);word(primitive+32,4);word(primitive+36,2);
      put(primitive+40,std::array<uint16_t,10>{0,1,2,3,0,1,2,0,2,3});
      word(0x42000+sid*32,0x60000);
      put(0x42004+sid*32,std::array<float,4>{0,0,1,1});
      word(0x63000+sid*4,0x65000+sid*0x100);
      word(0x67000+sid*4,0xd0000+sid*0x100);
    }
    word(0x60030,0x62000);word(0x60038,0x66000);word(0x6003c,1);
    word(0x61030,0x63000);word(0x61038,0x67000);word(0x6103c,3);
    word(0x62000,0x64000);word(0x66000,0xe0000);
    for (unsigned vertex=0;vertex<4;++vertex) word(0xa0010+vertex*36,0xff806040);
  }
  std::array<uint32_t,8> arguments() const {return {0xc0000,4,0x244,0xa0000,4,0xa1000,6,0};}
  void start() {require(adapter.begin(config,0x40000)==WorldAction::Handled,"begin rejected valid world");}
  void draw(uint32_t sid) {require(adapter.draw(arguments(),sid)==WorldAction::Handled,"ordinary capture not handled");}
  void end() {require(adapter.end(0x40000)==WorldAction::Handled&&!open,"world scope not submitted/closed");}
  void populate() {start();for (uint32_t sid=0;sid<3;++sid) draw(sid);end();events.clear();}
};
void run() {
  {
    Fixture f;auto bad=f.config;bad.version=0;
    require(f.adapter.begin(bad,0x40000)==WorldAction::Native&&f.events.empty(),"bad config changed renderer");
    f.word(0x70000,0);
    require(f.adapter.begin(f.config,0x40000)==WorldAction::Native&&f.events.empty(),"missing manager did not retain native");
  }
  {
    Fixture f;f.populate();f.start();
    for (uint32_t sid=0;sid<3;++sid)
      require(f.adapter.prepared(0x40000,sid)==WorldAction::Handled,"unchanged prepared surface not reused");
    f.end();
    require(f.events==std::vector<std::string>{"begin","prepared:0","prepared:6","prepared:12","submit:3"},"prepared draw order changed");
    f.events.clear();f.start();f.memory[0x80000]=1;
    require(f.adapter.prepared(0x40000,0)==WorldAction::Native,"changed texture format reused stale material");
    f.draw(0);f.end();
    require(f.events==std::vector<std::string>{"begin","append:0","submit:1"},"changed material did not follow native preparation");
  }
  {
    Fixture f;f.reject=6;f.start();f.draw(0);
    require(f.adapter.draw(f.arguments(),1)==WorldAction::Native,"unsupported draw was suppressed");
    require(!f.open,"supported work not submitted before native fallback");
    f.events.push_back("native");f.draw(2);f.end();
    require(f.events==std::vector<std::string>{"begin","append:0","append:6","submit:1","native","begin","append:12","submit:1"},"fallback reordered or repeated draws");
  }
  {
    Fixture f;f.failAppend=6;f.start();f.draw(0);
    require(f.adapter.draw(f.arguments(),1)==WorldAction::Failed&&!f.open,"failed append not cancelled");
    const auto count=f.events.size();
    require(f.adapter.draw(f.arguments(),2)==WorldAction::Failed&&f.events.size()==count,"failed frame continued rendering");
    require(f.adapter.end(0x40000)==WorldAction::Failed,"failed frame reported successful end");
    require(f.events==std::vector<std::string>{"begin","append:0","append:6","cancel"},"partial failed batch was submitted");
    f.failAppend=-1;f.events.clear();f.start();f.draw(0);f.end();
  }
  {
    Fixture f;f.failBegin=true;
    require(f.adapter.begin(f.config,0x40000)==WorldAction::Failed&&!f.open,"failed begin stranded renderer ownership");
    require(f.events==std::vector<std::string>{"begin","cancel"},"failed begin was treated as unsupported");
    f.failBegin=false;f.start();f.draw(0);f.end();
  }
  {
    Fixture f;f.rejectBegin=true;
    require(f.adapter.begin(f.config,0x40000)==WorldAction::Native&&!f.open,"known unsupported begin changed ownership");
    require(f.events==std::vector<std::string>{"begin"},"unsupported begin issued extra operations");
  }
  {
    Fixture f;f.populate();f.start();f.rejectPrepared=true;
    require(f.adapter.prepared(0x40000,0)==WorldAction::Native,"missing GPU material suppressed original");
    f.draw(0);f.end();
    require(f.events==std::vector<std::string>{"begin","prepared:0","append:0","submit:1"},"missing GPU material did not recapture");
  }
  {
    Fixture f;f.populate();const auto old=f.generations.back();
    f.word(0x90000,2);f.put(0x10000,std::array<float,12>{0,0,0,2,0,0,2,1,0,0,1,0});
    f.start();
    require(f.adapter.prepared(0x40000,0)==WorldAction::Native,"scene reload reused old prepared material");
    f.draw(0);f.end();
    require(f.generations.back()>old&&f.positions.back()==2,"same-address scene reload retained old geometry");
    f.word(0x714e8,0xc1000);f.start();
    require(f.adapter.prepared(0x40000,0)==WorldAction::Native,"new device reused old prepared material");
    f.adapter.cancel();require(!f.open,"explicit cancellation left a backend scope");
  }
  {
    Fixture f;f.start();f.draw(0);
    require(f.adapter.draw(f.arguments(),0)==WorldAction::Failed&&!f.open,"duplicate surface silently reused");
    f.adapter.cancel();f.start();
    auto args=f.arguments();args[0]=0xc1000;
    require(f.adapter.draw(args,0)==WorldAction::Failed&&!f.open,"foreign device was rendered");
    f.adapter.cancel();
    f.word(0x40120,65536);
    require(f.adapter.begin(f.config,0x40000)==WorldAction::Native,"unsupported geometry replaced original");
  }
}
}
int main() {
  try {run();std::printf("world adapter: %u behavior checks passed\n",checks);return 0;}
  catch (const std::exception& error) {std::fprintf(stderr,"FAIL: %s\n",error.what());return 1;}
}
