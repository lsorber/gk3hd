"""Courier marker repair preserves every authored cell in both image planes."""

from __future__ import annotations

from dataclasses import replace
from itertools import pairwise
from typing import TYPE_CHECKING

import pytest
from PIL import Image

from gk3hd.textures.upscale.fonts.atlas import font_atlas_recipe, parse_glyph_cells
from gk3hd.textures.upscale.fonts.layout import repair_courier_layout
from tests.font_fixtures import make_courier_opacity_pair

if TYPE_CHECKING:
    from pathlib import Path

_NAMES = (
    "COURIER_R_12.BMP",
    "COURIER_B_12.BMP",
    "COURIER_I_12.BMP",
    "COURIER_B_I_12.BMP",
    "COURIER_R_14.BMP",
)
_KEY = (255, 0, 255)


@pytest.mark.parametrize("name", _NAMES)
def test_courier_repair_preserves_all_authored_samples_and_advances(
    tmp_path: Path, name: str
) -> None:
    make_courier_opacity_pair(tmp_path, name)
    recipe = font_atlas_recipe(name)
    assert recipe is not None
    assert recipe.alpha_companion is not None
    with (
        Image.open(tmp_path / name) as color,
        Image.open(tmp_path / recipe.alpha_companion) as alpha,
    ):
        before = color.tobytes(), alpha.tobytes()
        height = color.height // 3
        authored = []
        for top in range(0, color.height, height):
            markers = [x for x in range(color.width) if color.getpixel((x, top)) != _KEY]
            authored.extend(
                (left, top + 1, right, top + height) for left, right in pairwise(markers)
            )
        assert len(authored) == 182
        fixed, opacity = repair_courier_layout(color, alpha, recipe)
        cells = parse_glyph_cells(fixed, recipe)
        joined = (authored[148][0], authored[148][1], authored[149][2], authored[149][3])
        expected = [*authored[:148], joined, *authored[150:]]
        assert len(cells) == 181
        assert cells[148].character == 0xDF
        assert cells[-1].character == 0xFF
        for cell, rect in zip(cells, expected, strict=True):
            assert fixed.crop(cell.rect).size == color.crop(rect).size
            assert fixed.crop(cell.rect).tobytes() == color.crop(rect).tobytes()
            assert opacity.crop(cell.rect).tobytes() == alpha.crop(rect).tobytes()
        assert sum(cell.rect[2] - cell.rect[0] for cell in cells) == sum(
            rect[2] - rect[0] for rect in authored
        )
        assert (color.tobytes(), alpha.tobytes()) == before
        # A repeated repair must fail, not silently merge another character.
        with pytest.raises(ValueError, match="row markers"):
            repair_courier_layout(fixed, opacity, recipe)


@pytest.mark.parametrize("fault", ["name", "size", "mode", "rows", "characters", "marker", "edge"])
def test_courier_repair_rejects_unreviewed_layouts(tmp_path: Path, fault: str) -> None:
    name = "COURIER_R_14.BMP"
    make_courier_opacity_pair(tmp_path, name)
    recipe = font_atlas_recipe(name)
    assert recipe is not None
    assert recipe.alpha_companion is not None
    with (
        Image.open(tmp_path / name) as image,
        Image.open(tmp_path / recipe.alpha_companion) as image_a,
    ):
        color, alpha = image.copy(), image_a.copy()
    if fault == "name":
        recipe = replace(recipe, primary="UNKNOWN.BMP")
    elif fault == "size":
        alpha = alpha.crop((0, 0, 10, 10))
    elif fault == "mode":
        alpha = alpha.convert("RGB")
    elif fault == "rows":
        recipe = replace(recipe, line_count=4)
    elif fault == "characters":
        recipe = replace(recipe, characters=recipe.characters.replace(b"\xdf", b"\xff"))
    elif fault == "marker":
        color.putpixel((1, 0), (255, 0, 0))
    else:
        color.putpixel((color.width - 1, 20), (255, 255, 255))
    with pytest.raises(ValueError, match=r"layout repair|row markers|discard artwork"):
        repair_courier_layout(color, alpha, recipe)
