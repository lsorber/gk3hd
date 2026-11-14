#include "vortek_serializer.h"
#include "DeviceFeatures.h"

static int deviceFeatures(void) {
    for (int position = 0; position < 3; ++position) {
        VkPhysicalDeviceRobustness2FeaturesEXT robust = {
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ROBUSTNESS_2_FEATURES_EXT,
            .robustBufferAccess2 = VK_TRUE, .robustImageAccess2 = VK_FALSE, .nullDescriptor = VK_TRUE};
        VkPhysicalDeviceTimelineSemaphoreFeatures timeline = {
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_TIMELINE_SEMAPHORE_FEATURES,
            .timelineSemaphore = VK_FALSE};
        VkPhysicalDeviceMapMemoryPlacedFeaturesEXT placed = {
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MAP_MEMORY_PLACED_FEATURES_EXT,
            .memoryMapPlaced = VK_TRUE, .memoryUnmapReserve = VK_TRUE};
        robust.pNext = &timeline;
        VkDeviceCreateInfo info = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .pNext = &robust};
        if (position == 0) {info.pNext = &placed; placed.pNext = &robust;}
        if (position == 1) {robust.pNext = &placed; placed.pNext = &timeline;}
        if (position == 2) timeline.pNext = &placed;
        gk3hdNativeDeviceFeatures(&info);
        gk3hdNativeDeviceFeatures(&info);
        if (info.pNext != &robust || robust.pNext != &timeline || timeline.pNext ||
            !robust.robustBufferAccess2 || robust.robustImageAccess2 || !robust.nullDescriptor ||
            timeline.timelineSemaphore || !placed.memoryMapPlaced || !placed.memoryUnmapReserve)
            return 10;
        info.pNext = &placed; placed.pNext = NULL;
        gk3hdNativeDeviceFeatures(&info);
        gk3hdNativeDeviceFeatures(&info);
        if (info.pNext) return 11;
    }
    puts("Client-emulated features removed; native feature order and requested bits preserved");
    return 0;
}

/* Exercise the real endpoint codec without Vulkan calls, hardware or a game. */
int main(void) {
    int featureResult = deviceFeatures();
    if (featureResult) return featureResult;
    const uint32_t types[]={0,1,VK_MAX_MEMORY_TYPES};
    const uint32_t heaps[]={1,2,VK_MAX_MEMORY_HEAPS};
    for(unsigned t=0;t<3;t++) for(unsigned h=0;h<3;h++) {
        VkPhysicalDeviceMemoryProperties input,output;
        memset(&input,0xcc,sizeof(input));memset(&output,0xa5,sizeof(output));
        input.memoryTypeCount=types[t];input.memoryHeapCount=heaps[h];
        for(uint32_t i=0;i<input.memoryTypeCount;i++) {
            input.memoryTypes[i].heapIndex=i%input.memoryHeapCount;
            input.memoryTypes[i].propertyFlags=(i&1)?VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT:VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT;
        }
        for(uint32_t i=0;i<input.memoryHeapCount;i++) {
            input.memoryHeaps[i].size=0x1234567800000000ull+i;
            input.memoryHeaps[i].flags=(i&1)?0:VK_MEMORY_HEAP_DEVICE_LOCAL_BIT;
        }
        int size=vt_sizeof_VkPhysicalDeviceMemoryProperties(&input);
        unsigned char bytes[1024];memset(bytes,0xed,sizeof(bytes));
        if(size<0||(size_t)size+16>sizeof(bytes)) return 2;
        vt_serialize_VkPhysicalDeviceMemoryProperties(&input,(char*)bytes+8);
        MemoryPool pool={0};
        vt_unserialize_VkPhysicalDeviceMemoryProperties(&output,(char*)bytes+8,&pool);
        if(input.memoryTypeCount!=output.memoryTypeCount||input.memoryHeapCount!=output.memoryHeapCount) return 3;
        for(uint32_t i=0;i<input.memoryTypeCount;i++)
            if(input.memoryTypes[i].heapIndex!=output.memoryTypes[i].heapIndex||
               input.memoryTypes[i].propertyFlags!=output.memoryTypes[i].propertyFlags) return 4;
        for(uint32_t i=0;i<input.memoryHeapCount;i++)
            if(input.memoryHeaps[i].size!=output.memoryHeaps[i].size||input.memoryHeaps[i].flags!=output.memoryHeaps[i].flags) return 5;
        for(int i=0;i<8;i++) if(bytes[i]!=0xed||bytes[size+8+i]!=0xed) return 6;
        printf("Wire fields and bounds pass: types=%u heaps=%u\n",types[t],heaps[h]);
    }
    /* Preserve the actual presentation queue and all binary wait identities. */
    VkObject* queue = VkObject_create(VK_OBJECT_TYPE_QUEUE, 0x123456789abcdef0ull);
    VkObject* sem = VkObject_create(VK_OBJECT_TYPE_SEMAPHORE, 0x223456789abcdef0ull);
    VkObject* swap = VkObject_create(VK_OBJECT_TYPE_SWAPCHAIN_KHR, 0x323456789abcdef0ull);
    VkSemaphore wait = VkObject_toHandle(sem);
    VkSwapchainKHR window = VkObject_toHandle(swap);
    uint32_t index = 2;
    VkPresentInfoKHR input = {.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR,
        .waitSemaphoreCount = 1, .pWaitSemaphores = &wait,
        .swapchainCount = 1, .pSwapchains = &window, .pImageIndices = &index};
    unsigned char bytes[1024];memset(bytes,0xed,sizeof(bytes));
    VkQueue sourceQueue = (VkQueue)&queue->id;
    int size = vt_sizeof_vkQueuePresentKHR(sourceQueue, &input);
    if (size <= 0 || size + 16 > (int)sizeof(bytes)) return 7;
    vt_serialize_vkQueuePresentKHR(sourceQueue, &input, (char*)bytes + 8);
    VkPresentInfoKHR output = {0};
    VkQueue targetQueue = VK_NULL_HANDLE;
    MemoryPool pool = {0};
    vt_unserialize_vkQueuePresentKHR((VkQueue)&targetQueue, &output, (char*)bytes + 8, &pool);
    if ((uint64_t)targetQueue != queue->id || output.waitSemaphoreCount != 1 ||
            output.swapchainCount != 1 || VkObject_fromHandle(output.pWaitSemaphores[0])->id != sem->id ||
            VkObject_fromHandle(output.pSwapchains[0])->id != swap->id || output.pImageIndices[0] != index)
        return 8;
    for (int i = 0; i < 8; ++i)
        if (bytes[i] != 0xed || bytes[size + 8 + i] != 0xed) return 9;
    puts("Presentation queue, semaphore, swapchain, image index and bounds pass");
    return 0;
}
