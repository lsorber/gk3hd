#include "status_sample.h"
#include <cstdio>
#include <cstdlib>
static void need(bool value) { if(!value) std::abort(); }
int main() {
  namespace status=gk3hd::vr::status_detail;
  uint32_t random=0x54321;
  auto next=[&]() {random=random*1664525+1013904223;return random;};
  for(unsigned i=0;i<100000;++i) {
    const uint32_t a=next(),b=next(),c=next(),d=next();
    const double u=double(next()&65535)/65535,v=double(next()&65535)/65535;
    uint32_t expected=0;
    for(unsigned shift=0;shift<32;shift+=8) {
      const auto ch=[&](uint32_t p) {return (p>>shift)&255;};
      expected|=uint32_t(std::lround((1-v)*((1-u)*ch(a)+u*ch(b))+
                                     v*((1-u)*ch(c)+u*ch(d))))<<shift;
    }
    need(status::sample(a,b,c,d,u,v)==expected);
    need(status::sample(a,a,a,a,u,v)==a);
  }
  uint64_t blends=0;
  for(unsigned alpha=0;alpha<256;++alpha)
    for(unsigned dst=0;dst<256;++dst)
      for(unsigned src=0;src<256;++src) {
        const uint32_t source=(alpha<<24)|(src*0x010101);
        const uint32_t destination=dst*0x01010101;
        const uint32_t rgb=std::min(255u,src+(dst*(255-alpha)+127)/255);
        const uint32_t a=std::min(255u,alpha+(dst*(255-alpha)+127)/255);
        need(status::over(source,destination)==((a<<24)|(rgb*0x010101)));
        ++blends;
      }
  printf("100000 independent and 100000 uniform bilinear samples; %llu exact source-over cases.\n",
         (unsigned long long)blends);
}
