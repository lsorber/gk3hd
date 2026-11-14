#ifndef GK3HD_QCOM_RGBA_LAYOUT_H
#define GK3HD_QCOM_RGBA_LAYOUT_H

#include <stdbool.h>
#include <stdint.h>

// Recognize the versioned Qualcomm Gralloc RGBA handle layout.
// The result must still agree with Turnip's modifier, pitch and allocation
// requirements before a caller imports the backing buffer.
static inline bool gk3hd_qcom_versioned_rgba_layout(
    int header_bytes, int descriptor_count, int word_count, const int *words,
    uint32_t width, uint32_t height, uint32_t stride, uint32_t format,
    uint32_t layers, uint64_t usage, int64_t descriptor_bytes) {
    // GPU sampled image, GPU color output and composer client target only.
    const uint64_t composer_gpu_rgba = UINT64_C(1) << 8 | UINT64_C(1) << 9 | UINT64_C(1) << 12;
    if (header_bytes != 12 || descriptor_count != 2 || word_count != 27 || !words ||
        !width || width > 8192 || width % 64 || !height || height > 4096 ||
        stride != width || format != 1 || layers != 1 || usage != composer_gpu_rgba ||
        descriptor_bytes <= 0) {
        return false;
    }

    const uint32_t aligned_height = (height + 15u) & ~15u;
    if (words[0] != 1 || (uint32_t)words[1] != UINT32_C(0x676d736d) ||
        !((uint32_t)words[2] & UINT32_C(0x08000000)) ||
        (uint32_t)words[3] != stride || (uint32_t)words[4] != aligned_height ||
        (uint32_t)words[5] != width || (uint32_t)words[6] != height) {
        return false;
    }

    const uint64_t metadata_stride = ((width + 15u) / 16u + 63u) & ~63u;
    const uint64_t metadata_rows = ((height + 3u) / 4u + 15u) & ~15u;
    const uint64_t metadata_bytes = (metadata_stride * metadata_rows + 4095u) & ~UINT64_C(4095);
    const uint64_t allocation_bytes = (uint64_t)stride * aligned_height * 4u + metadata_bytes;
    return (uint64_t)descriptor_bytes == allocation_bytes && (uint32_t)words[14] == allocation_bytes;
}

#endif
