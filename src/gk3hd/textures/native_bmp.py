"""Encode GK3's native RGB565 bitmaps without a lossy 24-bit loader round trip."""

from __future__ import annotations

import struct
import sys
from array import array
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image

_MAX_DIMENSION = 0xFFFF
PAIRED_UI_COLOR_SIZES = {"CAIN.BMP": (148, 160)}


def encode_rgb565(image: Image) -> bytes:
    """Write top-down, DWORD-padded ``61nM`` pixels in GK3's original BMP format.

    Extracted RGB565 channels use floor-scaled 8-bit values. Dropping their low
    bits recovers the original channel words exactly, including magenta. Sending
    those same values through GK3's 24-bit BMP loader can instead shift one color
    step (observed on the message-frame gold). Retain native words for verified
    source-derived geometric artwork, without changing ordinary AI image output.
    """
    width, height = image.size
    if not 0 < width <= _MAX_DIMENSION or not 0 < height <= _MAX_DIMENSION:
        msg = f"native BMP dimensions out of range: {width}x{height}"
        raise ValueError(msg)
    rgb = image.convert("RGB").tobytes()
    pixels = array(
        "H",
        (
            ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)
            for red, green, blue in zip(rgb[0::3], rgb[1::3], rgb[2::3], strict=True)
        ),
    )
    if sys.byteorder != "little":
        pixels.byteswap()
    raw = pixels.tobytes()
    header = struct.pack("<4sHH", b"61nM", height, width)
    if width & 1:
        stride = width * 2
        raw = b"".join(
            raw[start : start + stride] + b"\0\0" for start in range(0, len(raw), stride)
        )
    return header + raw
