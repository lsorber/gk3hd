"""Synthetic numeric opacity font with its distinct blue metadata contract."""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from pathlib import Path


def make_numeric_font_pair(directory: Path) -> None:
    """Make unequal advances, fractional coverage and an implicit final edge."""
    color = Image.new("RGB", (116, 21), (255, 0, 255))
    alpha = Image.new("L", color.size)
    color.putpixel((0, 1), (255, 255, 255))
    color.putpixel((0, 19), (16, 56, 255))
    boundaries = [1, 10, 22, 33, 46, 58, 70, 80, 92, 104, 116]
    for left, right in pairwise(boundaries):
        color.putpixel((left, 0), (16, 56, 255))
        for y in range(1, 21):
            x = left + y % (right - left)
            color.putpixel((x, y), (255, 255, 255))
            alpha.putpixel((x, y), 10 + y * 11)
    color.save(directory / "F_NUM_TLARGE.BMP")
    alpha.save(directory / "F_NUM_TLARGEA.BMP")
