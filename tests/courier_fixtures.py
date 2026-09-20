"""Synthetic artwork with independently specified italic Courier marker defects."""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from pathlib import Path

_KEY = (255, 0, 255)
_INK = (255, 255, 255)


def make_italic_courier_pair(directory: Path, name: str) -> None:
    """Include empty end cells, partial-alpha stray markers and a missing boundary."""
    italic = name == "COURIER_I_14.BMP"
    width, baseline = (522, 13) if italic else (528, 12)
    rows = ((519, 56), (502, 68), (501, 55)) if italic else ((526, 56), (522, 65), (514, 55))
    color = Image.new("RGB", (width, 68), _KEY)
    alpha = Image.new("L", color.size)
    for y in (1, baseline):
        color.putpixel((0, y), _INK)
    for row, (last, count) in enumerate(rows):
        marks = [1 + i * (last - 1) // count for i in range(count + 1)]
        if italic and row == 2:
            # Fifty-five genuine cells, plus the two stray marker samples.
            marks = [1 + i * 186 // 20 for i in range(21)]
            marks += [197 + i * (last - 197) // 34 for i in range(35)]
        _draw_row(color, alpha, marks, row * 17)
        color.putpixel((520 if italic else 527, row * 17), _INK)
    if italic:
        for x, value in ((187, 130), (189, 117), (190, 68), (197, 130)):
            color.putpixel((x, 34), _INK)
            alpha.putpixel((x, 34), value)
        _draw_row(color, alpha, [1, 11, 20, 31], 51)
        color.putpixel((31, 51), _KEY)
        color.putpixel((520, 51), _INK)
        # Preserve one-pixel bearing and complete accented-y lower body.
        color.paste(_KEY, (20, 58, 31, 68))
        alpha.paste(0, (20, 58, 31, 68))
        color.paste(color.crop((1, 58, 11, 68)), (21, 58))
        alpha.paste(alpha.crop((1, 58, 11, 68)), (21, 58))
        color.putpixel((80, 60), (255, 32, 255))  # Invisible unused source noise.
        for position in ((519, 0), (520, 17), (520, 34), (520, 51)):
            color.putpixel(position, (255, 32, 255))
    else:
        _draw_row(color, alpha, [1, 10, 20, 30, 40, 50, 61], 51)
    color.save(directory / name)
    alpha.save(directory / name.replace(".BMP", "A.BMP"))


def _draw_row(color: Image.Image, alpha: Image.Image, marks: list[int], top: int) -> None:
    for x in marks:
        color.putpixel((x, top), _INK)
    for index, (left, right) in enumerate(pairwise(marks)):
        for y in range(2, 14):
            x = left + (y + index) % (right - left)
            color.putpixel((x, top + y), _INK)
            alpha.putpixel((x, top + y), 13 + (y * 11 + index) % 243)
