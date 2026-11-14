#pragma once

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace gk3hd::standalone {
// Diagnostic resource bounds, independent of a headset's recommended extent.
// Six eye files stay below 96 MiB; one RGBA readback stays below 64 MiB.
inline bool projectionCaptureFits(uint32_t sourceWidth, uint32_t sourceHeight,
                                  int32_t x, int32_t y, int32_t width, int32_t height) {
    return sourceWidth && sourceHeight && x >= 0 && y >= 0 && width > 0 && height > 0 &&
        uint64_t(x) + uint32_t(width) <= sourceWidth &&
        uint64_t(y) + uint32_t(height) <= sourceHeight &&
        uint64_t(sourceWidth) * sourceHeight <= (64u * 1024u * 1024u) / 4 &&
        uint64_t(width) * uint32_t(height) <= (16u * 1024u * 1024u) / 3;
}

inline std::vector<uint8_t> projectionCaptureRgb(const std::vector<uint8_t>& rgba,
        uint32_t sourceWidth, uint32_t sourceHeight,
        int32_t x, int32_t y, int32_t width, int32_t height, bool bgra) {
    if (!projectionCaptureFits(sourceWidth, sourceHeight, x, y, width, height) ||
        rgba.size() != uint64_t(sourceWidth) * sourceHeight * 4)
        throw std::invalid_argument("Invalid diagnostic eye region or pixel extent");
    std::vector<uint8_t> rgb(size_t(width) * height * 3);
    for (int32_t row = 0; row < height; ++row)
        for (int32_t col = 0; col < width; ++col) {
            const size_t src = (size_t(y + row) * sourceWidth + x + col) * 4;
            const size_t dst = (size_t(row) * width + col) * 3;
            rgb[dst] = rgba[src + (bgra ? 2 : 0)];
            rgb[dst + 1] = rgba[src + 1];
            rgb[dst + 2] = rgba[src + (bgra ? 0 : 2)];
        }
    return rgb;
}
}
