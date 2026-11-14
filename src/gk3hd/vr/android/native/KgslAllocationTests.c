/* Allocation adapter behavior screen. Compile with the pinned KGSL UAPI header;
 * no real device, allocation, GPU submission or security policy is involved. */
#define dlsym gk3hd_test_dlsym
#define ioctl gk3hd_test_ioctl
#include "KgslAllocation.c"
#undef ioctl
#undef dlsym
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "KgslAllocationProbe.h"

_Static_assert(sizeof(void *) == 8, "This control translates only the 64-bit ABI");
_Static_assert(sizeof(struct kgsl_gpumem_alloc_id) == 48, "Legacy allocation ABI");
_Static_assert(sizeof(struct kgsl_gpumem_free_id) == 8, "Legacy free ABI");
_Static_assert(sizeof(struct kgsl_gpuobj_alloc) == 48, "Allocation ABI");
_Static_assert(sizeof(struct kgsl_gpuobj_info) == 48, "Info ABI");
_Static_assert(sizeof(struct kgsl_gpuobj_free) == 32, "Free ABI");
_Static_assert(IOCTL_KGSL_GPUMEM_ALLOC_ID == 0xc0300934UL, "Allocation request ABI");
_Static_assert(IOCTL_KGSL_GPUMEM_FREE_ID == 0xc0080935UL, "Free request ABI");
_Static_assert(IOCTL_KGSL_GPUOBJ_ALLOC == 0xc0300945UL, "Current allocation ABI");
_Static_assert(IOCTL_KGSL_GPUOBJ_INFO == 0xc0300947UL, "Current info ABI");
_Static_assert(IOCTL_KGSL_GPUOBJ_FREE == 0x40200946UL, "Current free ABI");

static int calls, frees, original_error, allocation_error, info_error, free_error;
static int original_result;
static unsigned long original_request;
static void *original_argument;

static int kernel(int fd, unsigned long request, ...) {
    va_list ap;
    va_start(ap, request);
    void *argument = va_arg(ap, void *);
    va_end(ap);
    assert(fd == 17);
    ++calls;
    if (request == original_request && calls == 1) {
        assert(argument == original_argument);
        errno = original_error;
        return original_result;
    }
    if (request == IOCTL_KGSL_GPUOBJ_ALLOC) {
        struct kgsl_gpuobj_alloc *p = argument;
        assert(p->size == 4097 && p->flags == 0x80000011U);
        assert(p->va_len == 0 && p->metadata_len == 0 && p->metadata == 0);
        if (allocation_error) { errno = allocation_error; return -1; }
        p->id = 23; p->size = 8192; p->mmapsize = 12288;
        return 0;
    }
    if (request == IOCTL_KGSL_GPUOBJ_INFO) {
        struct kgsl_gpuobj_info *p = argument;
        assert(p->id == 23);
        if (info_error) { errno = info_error; return -1; }
        p->gpuaddr = 0x100000000123ULL;
        p->flags = 0x80000031U; p->size = 8192;
        return 0;
    }
    assert(request == IOCTL_KGSL_GPUOBJ_FREE);
    struct kgsl_gpuobj_free *p = argument;
    assert(p->id == 23 && p->flags == 0 && p->priv == 0 && p->type == 0 && p->len == 0);
    ++frees;
    if (free_error) { errno = free_error; return -1; }
    return 0;
}

void *gk3hd_test_dlsym(void *handle, const char *name) {
    assert(handle == RTLD_NEXT && strcmp(name, "ioctl") == 0);
    return (void *)kernel;
}

static void reset(unsigned long request, void *argument) {
    calls = frees = allocation_error = info_error = free_error = 0;
    original_request = request; original_argument = argument;
    original_result = -1; original_error = EACCES;
}

static int probe_allocation_error, probe_free_error, probe_cleanup_error, probe_calls;
static int probe_kernel(int fd, unsigned long request, void *argument) {
    assert(fd == 17);
    ++probe_calls;
    int error;
    if (request == IOCTL_KGSL_GPUMEM_ALLOC_ID) {
        struct kgsl_gpumem_alloc_id *p = argument;
        assert(p->size == 4096 && p->flags == 0);
        p->id = 77;
        error = probe_allocation_error;
    } else if (request == IOCTL_KGSL_GPUMEM_FREE_ID) {
        assert(((struct kgsl_gpumem_free_id *)argument)->id == 77);
        error = probe_free_error;
    } else {
        assert(request == IOCTL_KGSL_GPUOBJ_FREE);
        struct kgsl_gpuobj_free *p = argument;
        assert(p->id == 77 && p->flags == 0 && p->priv == 0);
        error = probe_cleanup_error;
    }
    if (error) { errno = error; return -1; }
    return 0;
}

int main(void) {
    struct kgsl_gpumem_alloc_id initial = {
        .id = 11, .flags = 0x80000011U, .size = 4097,
        .mmapsize = 42, .gpuaddr = 43, .__pad = {44, 45}
    };
    struct kgsl_gpumem_alloc_id allocation;
    for (int error = 0; error < 2; ++error) {
        allocation = initial;
        reset(IOCTL_KGSL_GPUMEM_ALLOC_ID, &allocation);
        original_error = error ? EPERM : EACCES;
        assert(gk3hd_test_ioctl(17, original_request, &allocation) == 0);
        assert(calls == 3 && frees == 0 && allocation.id == 23);
        assert(allocation.flags == 0x80000031U && allocation.size == 8192);
        assert(allocation.mmapsize == 12288 && allocation.gpuaddr == 0x100000000123ULL);
        assert(allocation.__pad[0] == 44 && allocation.__pad[1] == 45);
    }
    allocation = initial; reset(IOCTL_KGSL_GPUMEM_ALLOC_ID, &allocation);
    original_result = 0;
    assert(gk3hd_test_ioctl(17, original_request, &allocation) == 0 && calls == 1);
    assert(memcmp(&allocation, &initial, sizeof(initial)) == 0);
    reset(IOCTL_KGSL_GPUMEM_ALLOC_ID, &allocation); original_error = ENOMEM;
    assert(gk3hd_test_ioctl(17, original_request, &allocation) == -1 && errno == ENOMEM && calls == 1);
    reset(IOCTL_KGSL_GPUMEM_ALLOC_ID, &allocation); allocation_error = ENOTTY;
    assert(gk3hd_test_ioctl(17, original_request, &allocation) == -1 && errno == ENOTTY && calls == 2);
    assert(memcmp(&allocation, &initial, sizeof(initial)) == 0);
    for (int cleanup_error = 0; cleanup_error < 2; ++cleanup_error) {
        reset(IOCTL_KGSL_GPUMEM_ALLOC_ID, &allocation);
        info_error = EIO; free_error = cleanup_error ? EBUSY : 0;
        assert(gk3hd_test_ioctl(17, original_request, &allocation) == -1 && errno == EIO);
        assert(calls == 4 && frees == 1);
        assert(memcmp(&allocation, &initial, sizeof(initial)) == 0);
    }
    struct kgsl_gpumem_free_id release = {.id = 23, .__pad = 99};
    reset(IOCTL_KGSL_GPUMEM_FREE_ID, &release);
    assert(gk3hd_test_ioctl(17, original_request, &release) == 0 && calls == 2 && frees == 1);
    assert(release.id == 23 && release.__pad == 99);
    reset(IOCTL_KGSL_GPUMEM_FREE_ID, &release); free_error = EINVAL;
    assert(gk3hd_test_ioctl(17, original_request, &release) == -1 && errno == EINVAL && frees == 1);
    reset(IOCTL_KGSL_GPUMEM_FREE_ID, &release); original_result = 0;
    assert(gk3hd_test_ioctl(17, original_request, &release) == 0 && calls == 1 && frees == 0);
    reset(IOCTL_KGSL_GPUMEM_ALLOC_ID, NULL);
    assert(gk3hd_test_ioctl(17, original_request, NULL) == -1 && errno == EACCES && calls == 1);
    reset(0x12345678, &release);
    assert(gk3hd_test_ioctl(17, original_request, &release) == -1 && errno == EACCES && calls == 1);
    assert(gk3hdAllocationPolicy(17, probe_kernel) == 0 && probe_calls == 2);
    probe_calls = 0; probe_allocation_error = EACCES;
    assert(gk3hdAllocationPolicy(17, probe_kernel) == 1 && probe_calls == 1);
    probe_allocation_error = EPERM;
    assert(gk3hdAllocationPolicy(17, probe_kernel) == 1);
    probe_allocation_error = ENOMEM;
    assert(gk3hdAllocationPolicy(17, probe_kernel) == -ENOMEM);
    probe_calls = probe_allocation_error = 0; probe_free_error = EACCES;
    assert(gk3hdAllocationPolicy(17, probe_kernel) == 1 && probe_calls == 3);
    probe_free_error = EBUSY;
    assert(gk3hdAllocationPolicy(17, probe_kernel) == -EBUSY);
    probe_free_error = EACCES; probe_cleanup_error = EIO;
    assert(gk3hdAllocationPolicy(17, probe_kernel) == -EIO);
    puts("KGSL allocation ABI, passthrough, translation and failed-request cleanup passed");
    return 0;
}
