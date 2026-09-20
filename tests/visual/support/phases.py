"""Observe native blinking indicators; never paint or freeze captured pixels."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from PIL.Image import Image

EMAIL_NOTICE = (750, 144, 832, 160)
LOCATION_MARKER = (348, 204, 368, 226)
_GREEN_MINIMUM = 150
_GREEN_DOMINANCE = 70
_VISIBLE_FRACTION = 0.02


def fitted_point(size: tuple[int, int], x: int, y: int) -> tuple[int, int]:
    """Project a reference point into a contained, centered 4:3 viewport."""
    width, height = size
    fitted_height = min(height, width * 3 // 4)
    scale = fitted_height / 768
    return (
        round((width - fitted_height * 4 // 3) // 2 + x * scale),
        round((height - fitted_height) // 2 + y * scale),
    )


def green_indicator_visible(frame: Image, region: tuple[int, int, int, int]) -> bool:
    """Recognize the lit green phase inside a known reference-space indicator."""
    scale = frame.height / 768
    pillar = (frame.width - 1024 * scale) / 2
    left, top, right, bottom = region
    box = (
        round(left * scale + pillar),
        round(top * scale),
        round(right * scale + pillar),
        round(bottom * scale),
    )
    if region == LOCATION_MARKER:
        box = (*fitted_point(frame.size, left, top), *fitted_point(frame.size, right, bottom))
    pixels = np.asarray(frame.crop(box), dtype=np.int16)
    red, green, blue = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    visible = (
        (green > _GREEN_MINIMUM)
        & (green > red + _GREEN_DOMINANCE)
        & (green > blue + _GREEN_DOMINANCE)
    )
    return bool(float(visible.mean()) >= _VISIBLE_FRACTION)
