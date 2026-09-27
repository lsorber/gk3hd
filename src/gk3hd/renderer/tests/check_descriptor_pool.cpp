#define NOMINMAX
#include <windows.h>
#include "../dxvk/dxvk_descriptor.cpp"
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

static unsigned capacity, calls, resets, destroys;
static bool failAllocation, failReset;
static VKAPI_ATTR VkResult VKAPI_CALL createPool(VkDevice, const VkDescriptorPoolCreateInfo* info,
    const VkAllocationCallbacks*, VkDescriptorPool* pool) {
  capacity = info->maxSets; *pool = VkDescriptorPool(1); return VK_SUCCESS;
}
static VKAPI_ATTR VkResult VKAPI_CALL allocate(VkDevice, const VkDescriptorSetAllocateInfo* info,
    VkDescriptorSet* set) {
  ++calls;
  if (failAllocation) return VK_ERROR_OUT_OF_POOL_MEMORY;
  if (info->descriptorSetCount != 1) std::abort();
  *set = VkDescriptorSet(calls); return VK_SUCCESS;
}
static VKAPI_ATTR VkResult VKAPI_CALL reset(VkDevice, VkDescriptorPool, VkDescriptorPoolResetFlags) {
  if (failReset) return VK_ERROR_OUT_OF_DEVICE_MEMORY;
  ++resets; return VK_SUCCESS;
}
static VKAPI_ATTR void VKAPI_CALL destroy(VkDevice, VkDescriptorPool, const VkAllocationCallbacks*) {
  ++destroys;
}
static void require(bool result) {
  if (!result) { std::cerr << "Descriptor pool behavior failed\n"; std::exit(1); }
}
int main() {
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
  std::cout << "Descriptor capacity, allocation failure, safe reset and recycling pass\n";
}
