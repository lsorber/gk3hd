#include "HardwareBufferFormat.h"
#include <stdio.h>
int main(void) {
    const VkFormat storage[] = {VK_FORMAT_R8G8B8A8_UNORM, VK_FORMAT_B8G8R8A8_UNORM};
    const VkFormat srgb[] = {VK_FORMAT_R8G8B8A8_SRGB, VK_FORMAT_B8G8R8A8_SRGB};
    for (unsigned i = 0; i < 2; ++i) {
        VkImageCreateInfo image = {.flags = VK_IMAGE_CREATE_ALIAS_BIT};
        if (gk3hdHardwareBufferFormat(storage[i], storage[i], &image) != VK_SUCCESS ||
                image.format != storage[i] || image.flags != VK_IMAGE_CREATE_ALIAS_BIT)
            return 1;
        if (gk3hdHardwareBufferFormat(srgb[i], storage[i], &image) != VK_SUCCESS ||
                image.format != storage[i] ||
                image.flags != (VK_IMAGE_CREATE_ALIAS_BIT | VK_IMAGE_CREATE_MUTABLE_FORMAT_BIT))
            return 2;
        VkImageCreateInfo original = image;
        if (gk3hdHardwareBufferFormat(srgb[1-i], storage[i], &image) != VK_ERROR_FORMAT_NOT_SUPPORTED ||
                image.flags != original.flags || image.format != original.format)
            return 3;
        if (gk3hdHardwareBufferFormat(storage[i], VK_FORMAT_UNDEFINED, &image) != VK_ERROR_FORMAT_NOT_SUPPORTED)
            return 4;
    }
    if (gk3hdHardwareBufferFormat(storage[0], storage[0], NULL) != VK_ERROR_FORMAT_NOT_SUPPORTED)
        return 5;
    puts("Hardware-buffer formats: native storage, compatible sRGB views and rejected channel mismatches pass");
    return 0;
}
