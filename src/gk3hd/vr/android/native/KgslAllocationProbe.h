#ifndef GK3HD_KGSL_ALLOCATION_PROBE_H
#define GK3HD_KGSL_ALLOCATION_PROBE_H
#include <errno.h>
#ifndef __user
#define __user
#endif
#include "kgsl.h"

typedef int (*Gk3hdAllocationIoctl)(int, unsigned long, void *);

/* One owned page, no GPU commands: 0=legacy permitted, 1=compatibility needed,
 * negative errno=unknown/failure. Test actual API behavior, not device names. */
static inline int gk3hdAllocationPolicy(int fd, Gk3hdAllocationIoctl call) {
    struct kgsl_gpumem_alloc_id allocation = {.size = 4096};
    if (call(fd, IOCTL_KGSL_GPUMEM_ALLOC_ID, &allocation))
        return errno == EACCES || errno == EPERM ? 1 : -errno;
    struct kgsl_gpumem_free_id release = {.id = allocation.id};
    if (!call(fd, IOCTL_KGSL_GPUMEM_FREE_ID, &release)) return 0;
    int error = errno;
    /* Release our page even when only the legacy free operation is denied. */
    struct kgsl_gpuobj_free current = {.id = allocation.id};
    if (call(fd, IOCTL_KGSL_GPUOBJ_FREE, &current)) return -errno;
    return error == EACCES || error == EPERM ? 1 : -error;
}
#endif
