"""Synthetic precolored font cells with independent eight-bit opacity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from pathlib import Path


def make_dodge_font_pair(directory: Path) -> None:
    """Use unequal advances and both purple inks, including fractional alpha."""
    color = Image.new("RGB", (269, 57))
    alpha = Image.new("L", color.size)
    color.putpixel((0, 14), (255, 44, 0))
    color.paste((0, 4, 0), (0, 54, 1, 57))
    alpha.paste(6, (0, 54, 1, 57))
    palette = ((123, 56, 255), (205, 56, 255), (0, 4, 0), (8, 8, 8), (8, 12, 8))
    for row in range(3):
        left, top = 1, row * 19
        color.putpixel((left, top), (0, 0, 213))
        for index in range(31):
            color.putpixel((left, top + 2), palette[index % len(palette)])
            alpha.putpixel((left, top + 2), 37 + index)
            color.putpixel((left + 1, top + 3), palette[(index + 1) % len(palette)])
            alpha.putpixel((left + 1, top + 3), 255)
            # Opacity over black is valid but contributes no additive color.
            alpha.putpixel((left + 1, top + 5), 6)
            left += 3 + index % 4
            color.putpixel((left, top), (0, 0, 213))
    color.save(directory / "F_DODGENBURN16.BMP")
    alpha.save(directory / "F_DODGENBURN16_ALPHA.BMP")
