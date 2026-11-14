#ifndef GK3HD_HARDWARE_BUFFER_FORMAT_H
#define GK3HD_HARDWARE_BUFFER_FORMAT_H

#include <vulkan/vulkan.h>

/* Imported AHB storage must use the format reported by Android. An sRGB
 * swapchain view can still preserve encoded colors over compatible UNORM
 * storage, but only when the image explicitly permits that view format. */
static inline VkResult gk3hdHardwareBufferFormat(
        VkFormat requested, VkFormat storage, VkImageCreateInfo* image) {
    if (!image || storage == VK_FORMAT_UNDEFINED)
        return VK_ERROR_FORMAT_NOT_SUPPORTED;
    if (requested != storage) {
        if (!((requested == VK_FORMAT_B8G8R8A8_SRGB && storage == VK_FORMAT_B8G8R8A8_UNORM) ||
              (requested == VK_FORMAT_R8G8B8A8_SRGB && storage == VK_FORMAT_R8G8B8A8_UNORM)))
            return VK_ERROR_FORMAT_NOT_SUPPORTED;
        image->flags |= VK_IMAGE_CREATE_MUTABLE_FORMAT_BIT;
    }
    image->format = storage;
    return VK_SUCCESS;
}

#endif
