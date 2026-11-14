/* No GPU or headset. Exercise the runtime's enable2 callbacks with a strict
 * Vulkan resolver which correctly rejects vkCreateDevice at a NULL instance.
 */
#define WIN32_LEAN_AND_MEAN
#define XR_USE_GRAPHICS_API_VULKAN
#include <windows.h>
#include <vulkan/vulkan.h>
#include <openxr/openxr.h>
#include <openxr/openxr_platform.h>
#include <loader_interfaces.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>

static VkInstance instance=(VkInstance)(uintptr_t)0x1234;
static VkDevice device=(VkDevice)(uintptr_t)0x5678;
static int deviceCalls;
static VkResult VKAPI_CALL createInstance(const VkInstanceCreateInfo *info,const VkAllocationCallbacks *allocator,VkInstance *out) {
    (void)info;(void)allocator;*out=instance;return VK_SUCCESS;
}
static VkResult VKAPI_CALL createDevice(VkPhysicalDevice physical,const VkDeviceCreateInfo *info,const VkAllocationCallbacks *allocator,VkDevice *out) {
    (void)physical;(void)info;(void)allocator;*out=device;deviceCalls++;return VK_SUCCESS;
}
static PFN_vkVoidFunction VKAPI_CALL resolve(VkInstance context,const char *name) {
    if(strcmp(name,"vkCreateInstance")==0 && context==VK_NULL_HANDLE) return (PFN_vkVoidFunction)createInstance;
    if(strcmp(name,"vkCreateDevice")==0 && context==instance) return (PFN_vkVoidFunction)createDevice;
    return NULL;
}
#define REQUIRE(test) do {if(!(test)) {fprintf(stderr,"Failed: %s\n",#test);return 1;}} while(0)
int wmain(int argc,wchar_t **argv) {
    REQUIRE(argc==2);
    HMODULE library=LoadLibraryW(argv[1]);REQUIRE(library!=NULL);
    PFN_xrNegotiateLoaderRuntimeInterface negotiate=(PFN_xrNegotiateLoaderRuntimeInterface)GetProcAddress(library,"xrNegotiateLoaderRuntimeInterface");
    REQUIRE(negotiate!=NULL);
    XrNegotiateLoaderInfo loader={XR_LOADER_INTERFACE_STRUCT_LOADER_INFO,1,sizeof(loader),1,1,XR_MAKE_VERSION(1,0,0),XR_CURRENT_API_VERSION};
    XrNegotiateRuntimeRequest runtime={XR_LOADER_INTERFACE_STRUCT_RUNTIME_REQUEST,1,sizeof(runtime)};
    REQUIRE(negotiate(&loader,&runtime)==XR_SUCCESS);
    PFN_xrCreateVulkanInstanceKHR createVkInstance=NULL;
    PFN_xrCreateVulkanDeviceKHR createVkDevice=NULL;
    REQUIRE(runtime.getInstanceProcAddr(XR_NULL_HANDLE,"xrCreateVulkanInstanceKHR",(PFN_xrVoidFunction *)&createVkInstance)==XR_SUCCESS);
    REQUIRE(runtime.getInstanceProcAddr(XR_NULL_HANDLE,"xrCreateVulkanDeviceKHR",(PFN_xrVoidFunction *)&createVkDevice)==XR_SUCCESS);
    VkInstanceCreateInfo instanceInfo={VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    XrVulkanInstanceCreateInfoKHR xrInstance={XR_TYPE_VULKAN_INSTANCE_CREATE_INFO_KHR};
    xrInstance.pfnGetInstanceProcAddr=resolve;xrInstance.vulkanCreateInfo=&instanceInfo;
    VkResult result=VK_ERROR_UNKNOWN;VkInstance createdInstance=VK_NULL_HANDLE;
    REQUIRE(createVkInstance(XR_NULL_HANDLE,&xrInstance,&createdInstance,&result)==XR_SUCCESS);
    REQUIRE(result==VK_SUCCESS && createdInstance==instance);
    VkDeviceCreateInfo deviceInfo={VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
    XrVulkanDeviceCreateInfoKHR xrDevice={XR_TYPE_VULKAN_DEVICE_CREATE_INFO_KHR};
    xrDevice.pfnGetInstanceProcAddr=resolve;xrDevice.vulkanCreateInfo=&deviceInfo;
    VkDevice createdDevice=VK_NULL_HANDLE;
    REQUIRE(createVkDevice(XR_NULL_HANDLE,&xrDevice,&createdDevice,&result)==XR_SUCCESS);
    REQUIRE(result==VK_SUCCESS && createdDevice==device && deviceCalls==1);
    FreeLibrary(library);
    puts("Vulkan binding: instance dispatch preserved for device creation; no GPU or headset used");
    return 0;
}
