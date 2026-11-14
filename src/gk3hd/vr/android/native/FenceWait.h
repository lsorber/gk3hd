#ifndef GK3HD_FENCE_WAIT_H
#define GK3HD_FENCE_WAIT_H

#include <stdint.h>
#include <vulkan/vulkan.h>

/* Some Android drivers incorrectly time out a mixed initially-signaled /
 * unsubmitted wait-any set. Read fence state directly without consuming it.
 * Vulkan callers must not reset/destroy fences concurrently with a wait. */
static inline VkResult gk3hdFencePredicate(VkDevice device, uint32_t count,
        const VkFence* fences, VkBool32 all, PFN_vkGetFenceStatus status) {
    uint32_t ready = 0;
    for (uint32_t i = 0; i < count; ++i) {
        const VkResult result = status(device, fences[i]);
        if (result == VK_SUCCESS) ++ready;
        else if (result != VK_NOT_READY) return result;
    }
    return (all ? ready == count : ready != 0) ? VK_SUCCESS : VK_TIMEOUT;
}

/* Query the complete wait-all/any predicate without exporting/resetting fence
 * payloads. The query must release the transport lock before returning, so a
 * different renderer thread can submit the work that satisfies this wait.
 * A monotonic relative deadline avoids millisecond truncation and overflow. */
static inline VkResult gk3hdWaitFences(void* state, uint64_t timeout,
        VkResult (*query)(void*), uint64_t (*clock)(void*),
        void (*pause)(void*, uint64_t)) {
    const int finite = timeout != 0 && timeout != UINT64_MAX;
    const uint64_t start = finite ? clock(state) : 0;
    if (finite && start == UINT64_MAX) return VK_ERROR_DEVICE_LOST;
    uint64_t delay = 20000; /* Short sleep, not a busy spin or serialized wait. */
    for (;;) {
        const VkResult result = query(state);
        if (result != VK_TIMEOUT || timeout == 0) return result;
        uint64_t sleep = delay;
        if (finite) {
            const uint64_t now = clock(state);
            if (now == UINT64_MAX) return VK_ERROR_DEVICE_LOST;
            const uint64_t elapsed = now - start;
            if (elapsed >= timeout) return VK_TIMEOUT;
            const uint64_t remaining = timeout - elapsed;
            if (sleep > remaining) sleep = remaining;
        }
        pause(state, sleep);
        if (delay < 200000) {
            delay *= 2;
            if (delay > 200000) delay = 200000;
        }
    }
}

#endif
