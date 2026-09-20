"""Synthetic caption color/opacity pair with distinct parser and color keys."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from pathlib import Path


def make_caption_opacity_pair(directory: Path) -> None:
    """Use unequal advances and grayscale colors already modulated by opacity."""
    color = Image.new("RGB", (1485, 18), "white")
    alpha = Image.new("L", color.size)
    color.putpixel((0, 0), (255, 0, 255))
    color.putpixel((0, 17), (255, 0, 255))
    color.putpixel((0, 13), (0, 0, 0))
    left = 1
    for index in range(181):
        color.putpixel((left, 0), (0, 0, 0))
        for dx, value in enumerate((31, 69, 137, 255), start=1):
            red, green = value >> 3, value >> 2
            rgb = ((red << 3) | (red >> 2), (green << 2) | (green >> 4), (red << 3) | (red >> 2))
            color.putpixel((left + dx, 4), rgb)
            alpha.putpixel((left + dx, 4), value)
        left += 9 if index < 36 else 8
    assert left == color.width
    color.save(directory / "F_CAPTION_GOUDY14AA.BMP")
    alpha.save(directory / "F_CAPTION_GOUDY14AA_ALPHA.BMP")
