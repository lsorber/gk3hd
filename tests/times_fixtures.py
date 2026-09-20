"""Synthetic Times color/opacity pairs, including the reviewed marker defect."""

from __future__ import annotations

from itertools import pairwise
from math import ceil
from typing import TYPE_CHECKING, Final

from PIL import Image

from gk3hd.textures.upscale.fonts.atlas import FONT_ATLAS_COLOR_SIZES, font_atlas_recipe

if TYPE_CHECKING:
    from pathlib import Path


# Source marker positions are independent of the production repair functions.
_ROW_ANCHORS: Final = {
    "TIMES_R_U_14.BMP": (
        ((0, 1), (59, 497)),
        ((0, 1), (70, 497)),
        ((0, 1), (52, 415)),
    ),
    "TIMES_B_U_14.BMP": (
        ((0, 1), (59, 520)),
        (
            (0, 1),
            (21, 154),
            (22, 164),
            (23, 166),
            (24, 170),
            (25, 173),
            (26, 176),
            (27, 179),
            (28, 183),
            (72, 520),
        ),
        ((0, 1), (50, 414)),
    ),
    "TIMES_B_U_12.BMP": (
        (
            (0, 1),
            (34, 296),
            (35, 301),
            (36, 305),
            (60, 469),
            (61, 476),
            (62, 489),
            (63, 492),
            (64, 504),
        ),
        ((0, 1), (74, 505)),
        ((0, 1), (42, 303)),
    ),
}


def _boundaries(name: str, row: int, cells: int) -> list[int]:
    if name == "TIMES_B_14.BMP":
        name = "TIMES_B_U_14.BMP"
    if name not in _ROW_ANCHORS:
        boundaries = [1]
        for index in range(cells):
            boundaries.append(boundaries[-1] + 2 + index % 4)
        return boundaries
    anchors = _ROW_ANCHORS[name][row]
    boundaries = []
    for (first, left), (last, right) in pairwise(anchors):
        boundaries.extend(left + i * (right - left) // (last - first) for i in range(last - first))
    boundaries.append(anchors[-1][1])
    return boundaries


def make_times_opacity_pair(directory: Path, name: str) -> None:
    """Populate varied fractional samples without shipping game artwork."""
    recipe = font_atlas_recipe(name)
    assert recipe is not None
    assert recipe.alpha_companion is not None
    assert recipe.coverage_baseline is not None
    color = Image.new("RGB", FONT_ATLAS_COLOR_SIZES[name], (255, 0, 255))
    alpha = Image.new("L", color.size)
    for y in (1, recipe.coverage_baseline):
        color.putpixel((0, y), (255, 255, 255))
    if name == "TIMES_R_U_14.BMP":
        color.putpixel((0, 1), (255, 0, 255))
    source_rows = 3 if name == "TIMES_B_14.BMP" else recipe.line_count
    count = ceil(len(recipe.characters) / source_rows)
    for row in range(source_rows):
        top = row * color.height // source_rows
        cells = min(count, len(recipe.characters) - row * count)
        boundaries = _boundaries(name, row, cells)
        for x in boundaries:
            color.putpixel((x, top), (255, 255, 255))
        for index, (left, right) in enumerate(pairwise(boundaries)):
            if recipe.coverage_key_threshold:
                # Hidden nonzero alpha must stay in the reference, not bleed
                # into the reconstructed visible strokes.
                bottom = (row + 1) * color.height // source_rows
                alpha.putpixel((left, bottom - 1), recipe.coverage_key_threshold)
            for y in range(2, recipe.coverage_baseline):
                x = left + (y + index) % (right - left)
                color.putpixel((x, top + y), (255, 255, 255))
                alpha.putpixel((x, top + y), 13 + (y * 11 + index) % 243)
    color.save(directory / name)
    alpha.save(directory / recipe.alpha_companion)
