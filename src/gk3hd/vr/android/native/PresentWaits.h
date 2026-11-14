#ifndef GK3HD_PRESENT_WAITS_H
#define GK3HD_PRESENT_WAITS_H

#include <stdlib.h>
#include <vulkan/vulkan.h>

/* A virtual WSI must consume the binary waits just like native presentation.
 * Queue idle alone does not consume them. Submit once per present operation,
 * not once per window; the caller completes this queue before publishing to GL.
 * Keep the caller's queue identity rather than guessing a swapchain queue. */
static inline VkResult gk3hdConsumePresentWaits(
        PFN_vkQueueSubmit submit, VkQueue queue, const VkPresentInfoKHR* present) {
    if (!present) return VK_ERROR_INITIALIZATION_FAILED;
    if (!present->waitSemaphoreCount) return VK_SUCCESS;
    if (!submit || !queue || !present->pWaitSemaphores)
        return VK_ERROR_INITIALIZATION_FAILED;

    VkPipelineStageFlags local[8];
    VkPipelineStageFlags* stages = local;
    if (present->waitSemaphoreCount > sizeof(local) / sizeof(local[0])) {
        stages = calloc(present->waitSemaphoreCount, sizeof(*stages));
        if (!stages) return VK_ERROR_OUT_OF_HOST_MEMORY;
    }
    for (uint32_t i = 0; i < present->waitSemaphoreCount; ++i)
        stages[i] = VK_PIPELINE_STAGE_ALL_COMMANDS_BIT;

    const VkSubmitInfo info = {
        .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
        .waitSemaphoreCount = present->waitSemaphoreCount,
        .pWaitSemaphores = present->pWaitSemaphores,
        .pWaitDstStageMask = stages,
    };
    const VkResult result = submit(queue, 1, &info, VK_NULL_HANDLE);
    if (stages != local) free(stages);
    return result;
}

#endif
