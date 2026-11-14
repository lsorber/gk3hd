#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>

namespace gk3hd::frame_metadata {
constexpr size_t MaxImages=16,Bytes=320;
using Epoch=std::array<uint32_t,4>;
using Encoded=std::array<uint8_t,Bytes>;
struct Image {uint32_t index=0,serial=0,pose=0,movie=0;};
struct Snapshot {
  uint32_t width=0,height=0,count=0,latest=0;
  Epoch epoch{};
  std::array<Image,MaxImages> images{};
};
inline bool valid(const Snapshot& s) {
  if(s.width<576||s.width>8192||s.height<2||s.height>8192||s.count==0||s.count>MaxImages)return false;
  bool nonzero=false;for(auto v:s.epoch)nonzero|=v!=0;if(!nonzero)return false;
  uint32_t maximum=0;
  for(size_t i=0;i<MaxImages;i++) {
    const auto& row=s.images[i];
    if(i>=s.count) {if(row.index||row.serial||row.pose||row.movie)return false;continue;}
    if(row.index!=i||row.serial>s.latest||(!row.serial&&(row.pose||row.movie)))return false;
    if(row.serial)for(size_t j=0;j<i;j++)if(s.images[j].serial==row.serial)return false;
    if(row.serial>maximum)maximum=row.serial;
  }
  return maximum==s.latest;
}
inline std::optional<Snapshot> empty(Epoch epoch,uint32_t width,uint32_t height,uint32_t count) {
  if(count>MaxImages)return {};
  Snapshot s{};s.epoch=epoch;s.width=width;s.height=height;s.count=count;
  for(uint32_t i=0;i<count;i++)s.images[i].index=i;
  if(!valid(s))return {};return s;
}
inline bool publish(Snapshot& s,uint32_t index,uint32_t pose,uint32_t movie=0) {
  if(!valid(s)||index>=s.count||s.latest==UINT32_MAX)return false;
  s.images[index]={index,++s.latest,pose,movie};return true;
}
inline uint32_t word(const uint8_t* data,size_t offset) {
  uint32_t value=0;for(unsigned b=0;b<4;b++)value|=uint32_t(data[offset+b])<<(b*8);return value;
}
inline void word(Encoded& out,size_t offset,uint32_t value) {
  for(unsigned b=0;b<4;b++)out[offset+b]=uint8_t(value>>(b*8));
}
inline std::optional<Encoded> encode(const Snapshot& s) {
  if(!valid(s))return {};
  Encoded out{};const char magic[]="GPMP0002";
  for(size_t i=0;i<8;i++)out[i]=uint8_t(magic[i]);
  word(out,8,2);word(out,12,uint32_t(Bytes));word(out,16,s.width);word(out,20,s.height);
  word(out,24,s.count);word(out,28,s.latest);
  for(size_t i=0;i<4;i++)word(out,32+i*4,s.epoch[i]);
  for(size_t i=0;i<MaxImages;i++) {
    const auto& row=s.images[i];size_t base=64+i*16;
    word(out,base,row.index);word(out,base+4,row.serial);word(out,base+8,row.pose);word(out,base+12,row.movie);
  }
  return out;
}
inline std::optional<Snapshot> decode(const uint8_t* data,size_t bytes) {
  if(!data||bytes!=Bytes)return {};
  const char magic[]="GPMP0002";for(size_t i=0;i<8;i++)if(data[i]!=uint8_t(magic[i]))return {};
  if(word(data,8)!=2||word(data,12)!=Bytes)return {};
  for(size_t i=48;i<64;i++)if(data[i])return {};
  Snapshot s{};s.width=word(data,16);s.height=word(data,20);s.count=word(data,24);s.latest=word(data,28);
  for(size_t i=0;i<4;i++)s.epoch[i]=word(data,32+i*4);
  for(size_t i=0;i<MaxImages;i++) {
    size_t base=64+i*16;s.images[i]={word(data,base),word(data,base+4),word(data,base+8),word(data,base+12)};
  }
  if(!valid(s))return {};return s;
}
inline std::optional<uint32_t> bootstrap(const Snapshot& s,const Epoch& epoch,uint32_t serial,uint32_t pose) {
  if(!valid(s)||s.epoch!=epoch||!serial)return {};
  for(uint32_t i=0;i<s.count;i++)if(s.images[i].serial==serial&&s.images[i].pose==pose)return i;
  return {};
}
} // namespace gk3hd::frame_metadata
