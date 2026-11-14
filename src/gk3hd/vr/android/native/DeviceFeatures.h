#ifndef GK3HD_DEVICE_FEATURES_H
#define GK3HD_DEVICE_FEATURES_H

#include <vulkan/vulkan.h>

/* Placed-memory mapping is implemented by the client, not the Android driver.
 * Removing its extension name alone leaves enabled virtual feature bits in
 * pNext, which a driver can correctly reject with FEATURE_NOT_PRESENT. */
static inline void gk3hdNativeDeviceFeatures(VkDeviceCreateInfo* info) {
    VkBaseOutStructure* previous = NULL;
    VkBaseOutStructure* node = (VkBaseOutStructure*)info->pNext;
    while (node) {
        VkBaseOutStructure* next = node->pNext;
        if (node->sType == VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MAP_MEMORY_PLACED_FEATURES_EXT) {
            if (previous) previous->pNext = next;
            else info->pNext = next;
        } else previous = node;
        node = next;
    }
}

#endif
