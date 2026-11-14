#define NOMINMAX
#include <windows.h>
#include "../dxvk/dxvk_descriptor.cpp"
#include <map>
#include <set>
#include <cstdlib>
#include <iostream>

// Supply the actual wrapper with a permissive driver, without a GPU or loader.
// A conforming caller must manage its own declared pool capacity.
namespace dxvk::vk {
LibraryLoader::~LibraryLoader() { }
DeviceLoader::DeviceLoader(const Rc<InstanceLoader>& library, bool owned, VkDevice device)
  : m_library(library), m_getDeviceProcAddr(nullptr), m_device(device), m_owned(owned) { }
PFN_vkVoidFunction DeviceLoader::sym(const char*) const { return nullptr; }
DeviceFn::DeviceFn(const Rc<InstanceLoader>& library, bool owned, VkDevice device)
  : DeviceLoader(library, owned, device) { }
DeviceFn::~DeviceFn() { }
}
namespace dxvk {
void DxvkDevice::recycleDescriptorPool(const Rc<DxvkDescriptorPool>&) { std::abort(); }
}

static unsigned capacity, calls, resets, destroys, allocated;
static uint64_t nextHandle;
static std::map<VkDescriptorSet,VkDescriptorSetLayout> live;
static std::set<VkDescriptorSet> consumed;
static bool failBatch, fatalAllocation;
static bool failAllocation, failReset;
static VKAPI_ATTR VkResult VKAPI_CALL createPool(VkDevice, const VkDescriptorPoolCreateInfo* info,
    const VkAllocationCallbacks*, VkDescriptorPool* pool) {
  capacity = info->maxSets; *pool = VkDescriptorPool(1); return VK_SUCCESS;
}
static VKAPI_ATTR VkResult VKAPI_CALL allocate(VkDevice, const VkDescriptorSetAllocateInfo* info,
    VkDescriptorSet* set) {
  ++calls;
  if (fatalAllocation) return VK_ERROR_OUT_OF_DEVICE_MEMORY;
  if (failAllocation || (failBatch && info->descriptorSetCount>1)) return VK_ERROR_OUT_OF_POOL_MEMORY;
  if (!info->descriptorSetCount || allocated+info->descriptorSetCount>capacity) std::abort();
  allocated+=info->descriptorSetCount;
  for(unsigned i=0;i<info->descriptorSetCount;i++) {set[i]=VkDescriptorSet(++nextHandle);live.emplace(set[i],info->pSetLayouts[i]);}
  return VK_SUCCESS;
}
static VKAPI_ATTR VkResult VKAPI_CALL reset(VkDevice, VkDescriptorPool, VkDescriptorPoolResetFlags) {
  if (failReset) return VK_ERROR_OUT_OF_DEVICE_MEMORY;
  ++resets; allocated=0;live.clear();consumed.clear();return VK_SUCCESS;
}
static VKAPI_ATTR void VKAPI_CALL destroy(VkDevice, VkDescriptorPool, const VkAllocationCallbacks*) {
  ++destroys;
}
static void require(bool result) {
  if (!result) { std::cerr << "Descriptor pool behavior failed\n"; std::exit(1); }
}
int main() {
  _putenv_s("GK3HD_XR_DESCRIPTOR_BATCH", "");
  dxvk::Rc<dxvk::vk::DeviceFn> driver = new dxvk::vk::DeviceFn(nullptr, false, VK_NULL_HANDLE);
  driver->vkCreateDescriptorPool = createPool; driver->vkAllocateDescriptorSets = allocate;
  driver->vkResetDescriptorPool = reset; driver->vkDestroyDescriptorPool = destroy;
  {
    dxvk::DxvkDescriptorPool pool(driver);
    require(capacity > 0);
    for (unsigned cycle = 0; cycle < 3; ++cycle) {
      failAllocation = true; require(pool.alloc(VK_NULL_HANDLE) == VK_NULL_HANDLE);
      failAllocation = false;
      for (unsigned i = 0; i < capacity; ++i) require(pool.alloc(VK_NULL_HANDLE) != VK_NULL_HANDLE);
      unsigned before = calls;
      require(pool.alloc(VK_NULL_HANDLE) == VK_NULL_HANDLE && calls == before);
      failReset = true;
      bool threw = false;
      try { pool.reset(); } catch (const dxvk::DxvkError&) { threw = true; }
      require(threw && pool.alloc(VK_NULL_HANDLE) == VK_NULL_HANDLE && calls == before);
      failReset = false; pool.reset();
    }
  }
  require(resets == 3 && destroys == 1);
  // The standalone native-driver host opts in. Direct Turnip and PC-VR
  // retain ordinary allocation; run the same safety checks for either build.
  _putenv_s("GK3HD_XR_DESCRIPTOR_BATCH", "1");
  {
    dxvk::DxvkDescriptorPool pool(driver);
    const VkDescriptorSetLayout a=VkDescriptorSetLayout(11), b=VkDescriptorSetLayout(22);
    auto take=[&](VkDescriptorSetLayout layout) {
      auto set=pool.alloc(layout);
      require(set!=VK_NULL_HANDLE && live.at(set)==layout && consumed.insert(set).second);
      return set;
    };
    for(unsigned i=0;i<256;i++) take(i%2?a:b);
    pool.reset();
    failBatch=true;
    take(a);require(allocated==1);
    failBatch=false;
    pool.reset();
    fatalAllocation=true;
    unsigned before=calls;
    require(pool.alloc(a)==VK_NULL_HANDLE && calls==before+1);
    fatalAllocation=false;
    take(a);take(b);
    failReset=true;
    bool threw=false;try {pool.reset();} catch(const dxvk::DxvkError&) {threw=true;}
    require(threw);take(a);take(b);
    failReset=false;pool.reset();take(a);
    pool.reset();
    // More layouts than the bounded cache: unused prefetched sets must stay
    // charged to pool capacity and no stale handles may survive reset.
    unsigned delivered=0;
    while(delivered<capacity*2) {
      auto layout=VkDescriptorSetLayout(100+delivered%19);
      auto set=pool.alloc(layout);if(set==VK_NULL_HANDLE) break;
      require(live.at(set)==layout && consumed.insert(set).second);delivered++;
    }
    require(delivered>0 && delivered<=allocated && allocated<=capacity);
    pool.reset();take(a);pool.reset();
  }
  std::cout << "Descriptor uniqueness/layouts, capacity/eviction, fallback, fatal errors and reset behavior pass\n";
}
