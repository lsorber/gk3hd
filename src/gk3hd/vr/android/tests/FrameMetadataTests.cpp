#include "frame_metadata.h"
#include <fstream>
#include <iostream>
#include <stdexcept>
using namespace gk3hd::frame_metadata;
static unsigned checks=0;
static void expect(bool value){++checks;if(!value)throw std::runtime_error("protocol check failed");}
int main(int argc,char** argv) {
  expect(argc==2);
  Epoch epoch{{0x11223344,0x55667788,0x99aabbcc,0xddeeff00}};
  expect(!empty({},4120,2061,6));expect(!empty(epoch,575,2061,6));
  expect(!empty(epoch,4120,1,6));expect(!empty(epoch,4120,2061,0));expect(!empty(epoch,4120,2061,17));
  Snapshot s=*empty(epoch,4120,2061,6);expect(valid(s));
  std::ofstream out(argv[1],std::ios::binary|std::ios::trunc);expect(bool(out));
  uint32_t random=0x12345678;
  for(uint32_t n=0;n<256;n++) {
    random^=random<<13;random^=random>>17;random^=random<<5;
    const uint32_t pose=n==0?0x80000000u:n==1?0xffffffffu:random;
    const uint32_t movie=n%3==0 ? 0 : n/3+1;
    expect(publish(s,n%6,pose,movie));expect(s.latest==n+1);
    const auto bytes=*encode(s);const auto parsed=decode(bytes.data(),bytes.size());
    expect(bool(parsed));expect(*encode(*parsed)==bytes);
    expect(bootstrap(*parsed,epoch,n+1,pose)==std::optional<uint32_t>(n%6));
    Epoch wrong=epoch;wrong[0]++;expect(!bootstrap(*parsed,wrong,n+1,pose));
    expect(!bootstrap(*parsed,epoch,n+1,pose^1));expect(!bootstrap(*parsed,epoch,0,pose));
    expect(!decode(bytes.data(),Bytes-1));expect(!decode(nullptr,Bytes));
    for(auto offset:std::array<size_t,7>{{0,8,12,24,48,63,64+6*16}}) {
      auto bad=bytes;bad[offset]^=0x80;expect(!decode(bad.data(),bad.size()));
    }
    auto future=s;future.images[0].serial=s.latest+1;expect(!valid(future));
    auto unowned=*empty(epoch,4120,2061,6);unowned.images[0].movie=1;expect(!valid(unowned));
    expect(parsed->images[n%6].movie==movie);
    if(n>0){auto duplicate=s;duplicate.images[1].serial=duplicate.images[0].serial;expect(!valid(duplicate));}
    out.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());expect(bool(out));
  }
  s.latest=UINT32_MAX;s.images[0].serial=UINT32_MAX;
  const auto saturated=*encode(s);expect(!publish(s,0,123));expect(*encode(s)==saturated);
  out.write(reinterpret_cast<const char*>(saturated.data()),saturated.size());out.close();expect(bool(out));
  std::cout<<checks<<" native wire/bounds/identity/serial checks passed; 257 cross-language vectors\n";
}
