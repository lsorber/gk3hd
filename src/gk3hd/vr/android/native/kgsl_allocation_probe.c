#include <jni.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include "KgslAllocationProbe.h"

static int allocation_ioctl(int fd, unsigned long request, void *argument) {
    return ioctl(fd, (int)request, argument);
}

JNIEXPORT jint JNICALL
Java_org_gk3hd_standalone_GpuAllocationCompat_legacyAllocationPolicy(JNIEnv *env, jclass type) {
    (void)env;
    (void)type;
    int fd = open("/dev/kgsl-3d0", O_RDWR | O_CLOEXEC);
    if (fd < 0) return -errno;
    int policy = gk3hdAllocationPolicy(fd, allocation_ioctl);
    close(fd);
    return policy;
}
