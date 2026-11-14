#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdarg.h>
#include <sys/ioctl.h>
#define __user
/* UAPI supplied by the pinned Winlator/libadrenotools source, not a new SDK. */
#include "kgsl.h"

_Static_assert(sizeof(void *) == 8, "KGSL compatibility requires the 64-bit ABI");

static int (*next_ioctl)(int, unsigned long, ...);
static pthread_once_t resolved = PTHREAD_ONCE_INIT;

static void resolve_ioctl(void) {
    next_ioctl = dlsym(RTLD_NEXT, "ioctl");
}

/* Keep permitted operations unchanged. Some app policies deny the legacy
 * allocation API but allow its equivalent GPUOBJ API. No policy is modified.
 * This library belongs only to the private ARM64 guest's direct-driver route. */
int ioctl(int fd, unsigned long request, ...) {
    va_list args;
    va_start(args, request);
    void *argument = va_arg(args, void *);
    va_end(args);
    pthread_once(&resolved, resolve_ioctl);
    if (!next_ioctl) { errno = ENOSYS; return -1; }
    int result = next_ioctl(fd, request, argument);
    int error = errno;
    if (result != -1 || (error != EACCES && error != EPERM) || !argument)
        return result;
    if (request == IOCTL_KGSL_GPUMEM_ALLOC_ID) {
        struct kgsl_gpumem_alloc_id *legacy = argument;
        struct kgsl_gpuobj_alloc allocation = {.size = legacy->size, .flags = legacy->flags};
        result = next_ioctl(fd, IOCTL_KGSL_GPUOBJ_ALLOC, &allocation);
        if (result) return result;
        struct kgsl_gpuobj_info info = {.id = allocation.id};
        result = next_ioctl(fd, IOCTL_KGSL_GPUOBJ_INFO, &info);
        if (result) {
            error = errno;
            struct kgsl_gpuobj_free release = {.id = allocation.id};
            next_ioctl(fd, IOCTL_KGSL_GPUOBJ_FREE, &release);
            errno = error;
            return result;
        }
        /* Match the legacy kernel's returned fields; retain reserved words. */
        legacy->id = allocation.id;
        legacy->flags = (unsigned int)info.flags;
        legacy->size = info.size;
        legacy->mmapsize = allocation.mmapsize;
        legacy->gpuaddr = info.gpuaddr;
        return 0;
    }
    if (request == IOCTL_KGSL_GPUMEM_FREE_ID) {
        const struct kgsl_gpumem_free_id *legacy = argument;
        struct kgsl_gpuobj_free release = {.id = legacy->id};
        return next_ioctl(fd, IOCTL_KGSL_GPUOBJ_FREE, &release);
    }
    errno = error;
    return result;
}
