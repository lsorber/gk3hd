#include "PresentWaits.h"
#include <stdint.h>
#include <stdio.h>

static unsigned calls;
static VkResult outcome;
static VkQueue expectedQueue;
static const VkPresentInfoKHR* expectedPresent;

static VKAPI_ATTR VkResult VKAPI_CALL observe(
        VkQueue queue, uint32_t count, const VkSubmitInfo* info, VkFence fence) {
    ++calls;
    if (queue != expectedQueue || count != 1 || fence != VK_NULL_HANDLE ||
            info->sType != VK_STRUCTURE_TYPE_SUBMIT_INFO || info->pNext ||
            info->waitSemaphoreCount != expectedPresent->waitSemaphoreCount ||
            info->commandBufferCount || info->signalSemaphoreCount)
        return VK_ERROR_UNKNOWN;
    for (uint32_t i = 0; i < info->waitSemaphoreCount; ++i)
        if (info->pWaitSemaphores[i] != expectedPresent->pWaitSemaphores[i] ||
                info->pWaitDstStageMask[i] != VK_PIPELINE_STAGE_ALL_COMMANDS_BIT)
            return VK_ERROR_UNKNOWN;
    return outcome;
}

int main(void) {
    VkSemaphore semaphores[257];
    for (unsigned i = 0; i < 257; ++i)
        semaphores[i] = (VkSemaphore)(uintptr_t)(i + 10);
    VkPresentInfoKHR present = {.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR};
    if (gk3hdConsumePresentWaits(NULL, VK_NULL_HANDLE, &present) != VK_SUCCESS || calls)
        return 1;
    const unsigned sizes[] = {1, 8, 9, 257};
    expectedQueue = (VkQueue)(uintptr_t)0x1234;
    expectedPresent = &present;
    present.pWaitSemaphores = semaphores;
    for (unsigned i = 0; i < sizeof(sizes) / sizeof(sizes[0]); ++i) {
        present.waitSemaphoreCount = sizes[i];
        present.swapchainCount = 3; /* All windows share one set of waits. */
        outcome = VK_SUCCESS;
        if (gk3hdConsumePresentWaits(observe, expectedQueue, &present) != VK_SUCCESS || calls != i + 1)
            return 2;
    }
    const VkResult errors[] = {VK_ERROR_DEVICE_LOST, VK_ERROR_OUT_OF_HOST_MEMORY,
                              VK_ERROR_OUT_OF_DEVICE_MEMORY};
    for (unsigned i = 0; i < sizeof(errors) / sizeof(errors[0]); ++i) {
        outcome = errors[i];
        if (gk3hdConsumePresentWaits(observe, expectedQueue, &present) != outcome)
            return 3;
    }
    const unsigned before = calls;
    if (gk3hdConsumePresentWaits(NULL, expectedQueue, &present) != VK_ERROR_INITIALIZATION_FAILED ||
            gk3hdConsumePresentWaits(observe, VK_NULL_HANDLE, &present) != VK_ERROR_INITIALIZATION_FAILED ||
            gk3hdConsumePresentWaits(observe, expectedQueue, NULL) != VK_ERROR_INITIALIZATION_FAILED)
        return 4;
    present.pWaitSemaphores = NULL;
    if (gk3hdConsumePresentWaits(observe, expectedQueue, &present) != VK_ERROR_INITIALIZATION_FAILED || calls != before)
        return 5;
    puts("Presentation waits: zero/many, exact queue, single consumption and errors pass");
    return 0;
}
