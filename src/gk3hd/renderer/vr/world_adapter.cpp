#include "world_adapter.h"
#include <stdexcept>

namespace gk3hd::vr {
namespace {
uint32_t word(const void* data, size_t offset) {
  uint32_t result;
  std::memcpy(&result,static_cast<const uint8_t*>(data)+offset,4);
  return result;
}
void checked(int32_t result) {
  if (result<0) throw std::runtime_error("prepared scenery operation failed");
}
}
bool WorldAdapter::load(uint64_t address, void* output, size_t bytes) const {
  return address>=0x10000 && bytes && bytes<=4u*1024*1024 &&
    address+bytes<=0x7fff0000 && read_(context_,uint32_t(address),output,bytes);
}
bool WorldAdapter::resource(uint32_t address, uint32_t entry, Resource& result) const {
  result={};result.resource=address;
  std::array<uint8_t,96> header{};
  if (!load(address,header.data(),header.size())) return false;
  result.bitmapTable=word(header.data(),0x30);
  result.textureTable=word(header.data(),0x38);result.count=word(header.data(),0x3c);
  if (!result.bitmapTable || !result.count || result.count>8192 || entry>=result.count ||
      !load(uint64_t(result.bitmapTable)+entry*4,&result.bitmap,4) ||
      !load(result.bitmap,result.header.data(),result.header.size())) return false;
  if (result.textureTable && !load(uint64_t(result.textureTable)+entry*4,&result.texture,4)) return false;
  const auto format=word(result.header.data(),8);
  return format<64 && load(uint64_t(config_.formats)+format*64,result.format.data(),result.format.size());
}
bool WorldAdapter::signature(uint32_t sid, Signature& result) const {
  result={};
  return load(uint64_t(word(header_.data(),0xfc))+sid*32,result.material.data(),result.material.size()) &&
    resource(word(result.material.data(),0),0,result.base) &&
    resource(word(header_.data(),0x60),sid,result.light);
}
bool WorldAdapter::comparisons(uint32_t sid, Prepared& cache) {
  cache.rangeCount=0;
  auto add=[&](uint64_t address,const void* expected,size_t bytes) {
    if(address<0x10000||!bytes||address+bytes>0x7fff0000||cache.rangeCount==cache.ranges.size())return false;
    cache.ranges[cache.rangeCount++]={uint32_t(address),expected,bytes};return true;
  };
  auto resource=[&](const Resource& r,uint32_t entry) {
    return add(r.resource,nullptr,96)&&add(uint64_t(r.resource)+0x30,&r.bitmapTable,4)&&
      add(uint64_t(r.resource)+0x38,&r.textureTable,8)&&
      add(uint64_t(r.bitmapTable)+uint64_t(entry)*4,&r.bitmap,4)&&
      add(r.bitmap,r.header.data(),r.header.size())&&
      (!r.textureTable||add(uint64_t(r.textureTable)+uint64_t(entry)*4,&r.texture,4))&&
      add(uint64_t(config_.formats)+uint64_t(word(r.header.data(),8))*64,r.format.data(),r.format.size());
  };
  return add(uint64_t(word(header_.data(),0xfc))+uint64_t(sid)*32,
             cache.signature.material.data(),cache.signature.material.size())&&
    resource(cache.signature.base,0)&&resource(cache.signature.light,sid);
}
bool WorldAdapter::unchanged(uint32_t sid,const Prepared& cache) const {
  if(!equal_) {
    Signature current{};
    return signature(sid,current)&&!std::memcmp(&current,&cache.signature,sizeof(current));
  }
  return word(header_.data(),0x60)==cache.signature.light.resource&&
    cache.rangeCount&&equal_(context_,cache.ranges.data(),cache.rangeCount);
}
bool WorldAdapter::collect() {
  if (collecting_) return true;
  world_bridge::Request request{};
  request.bytes=sizeof(request);request.version=1;request.flags=1;request.geometryKey=geometry_.key();
  request.vertexCount=uint32_t(source_->vertices.size());request.indexCount=uint32_t(source_->indices.size());
  request.vertices=source_->vertices.data();request.indices=source_->indices.data();
  const auto result=submit_(context_,device_,world_bridge::Operation::Begin,&request);
  if (result==1) return false;
  collecting_=true;checked(result);return true;
}
void WorldAdapter::finish() {
  if (!collecting_) return;
  world_bridge::Result result{sizeof(result),0,0,0};
  checked(submit_(context_,device_,world_bridge::Operation::Submit,&result));
  collecting_=false;
}
WorldAction WorldAdapter::fallback(uint32_t sid) {
  finish();
  if (sid<prepared_.size()) prepared_[sid].valid=false;
  return WorldAction::Native;
}
WorldAction WorldAdapter::fail() noexcept {
  if (collecting_) {
    try { submit_(context_,device_,world_bridge::Operation::Cancel,nullptr); } catch (...) {}
  }
  collecting_=false;failed_=true;
  for (auto& item:prepared_) item.valid=false;
  return WorldAction::Failed;
}
void WorldAdapter::cancel() noexcept {
  fail();active_=false;failed_=false;root_=0;
}
WorldAction WorldAdapter::begin(const WorldAdapterConfig& config, uint32_t root) noexcept {
  if (active_) return fail();
  failed_=false;
  try {
    if (config.bytes!=sizeof(config)||config.version!=1||!config.manager||!config.formats||!config.lifetime)
      return WorldAction::Native;
    uint32_t manager=0,device=0,lifetime=0;
    std::array<uint8_t,0x150> header{};
    if (!load(config.manager,&manager,4)||!load(uint64_t(manager)+0x4e8,&device,4)||!device||
        !load(config.lifetime,&lifetime,4)||!load(root,header.data(),header.size())) return WorldAction::Native;
    if (device_!=device || config_.manager!=config.manager || config_.formats!=config.formats ||
        config_.lifetime!=config.lifetime) {geometry_.invalidate();prepared_.clear();}
    device_=device;config_=config;
    const auto identity=WorldGeometryIdentity::native(root,lifetime,header);
    const auto prepared=geometry_.prepare(identity,[&](uint32_t address,void* data,size_t bytes){return load(address,data,bytes);});
    if (prepared==WorldPreparation::Unsupported) {source_.reset();prepared_.clear();return WorldAction::Native;}
    source_=geometry_.snapshot();
    if (prepared==WorldPreparation::Rebuilt) prepared_.assign(source_->primitives.size(),Prepared{});
    header_=header;root_=root;
    if (!collect()) return WorldAction::Native;
    ++pass_;active_=true;return WorldAction::Handled;
  } catch (...) {
    if (!collecting_) {
      geometry_.invalidate();source_.reset();prepared_.clear();
      return WorldAction::Native;
    }
    // A failed renderer begin is not silently treated as unsupported.
    return fail();
  }
}
WorldAction WorldAdapter::end(uint32_t root) noexcept {
  if (!active_) return failed_?WorldAction::Failed:WorldAction::Native;
  if (root!=root_) return fail();
  try {if (!failed_) finish();} catch (...) {fail();}
  active_=false;
  return failed_?WorldAction::Failed:WorldAction::Handled;
}
WorldAction WorldAdapter::draw(const std::array<uint32_t,8>& args, uint32_t sid) noexcept {
  if (failed_) return WorldAction::Failed;
  if (!active_) return WorldAction::Native;
  try {
    if (args[0]!=device_) return fail();
    if (sid>=source_->primitives.size()||args[1]!=4||args[2]!=0x244||
        !args[4]||args[4]>65536||!args[6]||args[6]>1000000) return fallback(sid);
    if (!collect()) return fallback(sid);
    world_bridge::Draw draw{};draw.bytes=sizeof(draw);
    draw.first=source_->primitives[sid][0];draw.count=source_->primitives[sid][1];draw.uniform=1;
    if (!load(uint64_t(word(header_.data(),0xfc))+sid*32+4,draw.uv,16)||
        !load(uint64_t(args[3])+16,&draw.diffuse,4)) return fail();
    for (uint32_t index=1;index<args[4];++index) {
      uint32_t diffuse=0;
      if (!load(uint64_t(args[3])+index*36+16,&diffuse,4)) return fail();
      if (diffuse!=draw.diffuse) {draw.uniform=0;break;}
    }
    const auto appended=submit_(context_,device_,world_bridge::Operation::Append,&draw);
    if (appended==1) return fallback(sid);
    checked(appended);
    auto& cache=prepared_[sid];
    if (cache.drawPass==pass_) return fail();
    cache.drawPass=pass_;cache.draw=draw;cache.valid=signature(sid,cache.signature);
    if(cache.valid&&equal_)cache.valid=comparisons(sid,cache);
    return WorldAction::Handled;
  } catch (...) {return fail();}
}
WorldAction WorldAdapter::prepared(uint32_t root, uint32_t sid) noexcept {
  if (failed_) return WorldAction::Failed;
  if (!active_) return WorldAction::Native;
  try {
    if (root!=root_||sid>=prepared_.size()) return fail();
    auto& cache=prepared_[sid];
    if (!cache.valid) return WorldAction::Native;
    if (!collect()) return WorldAction::Native;
    if (!unchanged(sid,cache)) {
      cache.valid=false;return WorldAction::Native;
    }
    if (cache.fastPass==pass_) return fail();
    const auto result=submit_(context_,device_,world_bridge::Operation::AppendPrepared,&cache.draw);
    if (result==1) {cache.valid=false;return WorldAction::Native;}
    checked(result);cache.fastPass=pass_;return WorldAction::Handled;
  } catch (...) {return fail();}
}
} // namespace gk3hd::vr
