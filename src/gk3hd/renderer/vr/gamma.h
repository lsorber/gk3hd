#pragma once

#include <cstddef>
#include <cstdint>

namespace gk3hd::vr {

// GK3's corrected default uses the classic 256-step neutral ramp. Treat only
// that exact curve as neutral for immersive legacy rendering. Other ramps,
// including user brightness adjustments, keep the ordinary correction path.
// The caller retains the requested data for GetGammaRamp; this never edits it.
inline bool isNeutralLegacyXrRamp(bool immersive, bool legacy,
                                  const uint16_t* red, const uint16_t* green,
                                  const uint16_t* blue, size_t count) noexcept {
  if (!immersive || !legacy || count != 256 || !red || !green || !blue)
    return false;
  for (size_t i = 0; i < count; ++i) {
    const auto expected = static_cast<uint16_t>(i * 256);
    if (red[i] != expected || green[i] != expected || blue[i] != expected)
      return false;
  }
  return true;
}

} // namespace gk3hd::vr
