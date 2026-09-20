"""Four authored Courier rows retain their samples in the three-row descriptor."""

from __future__ import annotations

from dataclasses import replace
from itertools import pairwise
from typing import TYPE_CHECKING

import pytest
from PIL import Image

from gk3hd.textures.upscale.fonts.atlas import (
    font_atlas_output_size,
    font_atlas_recipe,
    parse_glyph_cells,
)
from gk3hd.textures.upscale.fonts.layout import repair_courier_layout
from tests.font_fixtures import make_courier_opacity_pair

if TYPE_CHECKING:
    from pathlib import Path

_NAME = "COURIER_B_14.BMP"
_ALPHA = "COURIER_B_14A.BMP"
_KEY = (255, 0, 255)


def test_courier_reflow_preserves_every_authored_sample_and_advance(tmp_path: Path) -> None:
    make_courier_opacity_pair(tmp_path, _NAME)
    recipe = font_atlas_recipe(_NAME)
    assert recipe is not None
    with Image.open(tmp_path / _NAME) as color, Image.open(tmp_path / _ALPHA) as alpha:
        originals = color.tobytes(), alpha.tobytes()
        rectangles = []
        for top in (0, 17, 34, 51):
            markers = [x for x in range(1, color.width) if color.getpixel((x, top)) != _KEY]
            rectangles.extend((a, top + 1, b, top + 17) for a, b in pairwise(markers))
        assert len(rectangles) == 182
        left, right = rectangles[148:150]
        rectangles[148:150] = [(left[0], left[1], right[2], right[3])]
        fixed, opacity = repair_courier_layout(color, alpha, recipe)
        assert fixed.size == opacity.size == (489, 66)
        assert recipe.line_count == 3
        assert fixed.height // recipe.line_count == color.height // recipe.line_count == 22
        assert [y for y in range(fixed.height) if fixed.getpixel((0, y)) != _KEY] == [1, 12]
        cells = parse_glyph_cells(fixed, recipe)
        assert len(cells) == 181
        assert cells[148].character == 0xDF
        assert cells[-1].character == 0xFF
        for cell, rect in zip(cells, rectangles, strict=True):
            lft, top, rgt, bottom = cell.rect
            assert rgt - lft == rect[2] - rect[0]
            assert bottom - top == 21
            art = (lft, top, rgt, top + 16)
            assert fixed.crop(art).tobytes() == color.crop(rect).tobytes()
            assert opacity.crop(art).tobytes() == alpha.crop(rect).tobytes()
            assert opacity.crop((lft, top + 16, rgt, bottom)).getbbox() is None
        assert (color.tobytes(), alpha.tobytes()) == originals
        with pytest.raises(ValueError, match="layout repair"):
            repair_courier_layout(fixed, opacity, recipe)


@pytest.mark.parametrize("name", [_NAME, _ALPHA])
def test_courier_reflow_dimensions_use_original_input_contract(name: str) -> None:
    assert font_atlas_output_size(name, (481, 68)) == (3912, 264)
    assert font_atlas_output_size(name, (489, 66)) == (1956, 264)


@pytest.mark.parametrize("fault", ["baseline", "anchor", "rows", "marker", "companion"])
def test_courier_reflow_rejects_unreviewed_sources(tmp_path: Path, fault: str) -> None:
    make_courier_opacity_pair(tmp_path, _NAME)
    recipe = font_atlas_recipe(_NAME)
    assert recipe is not None
    with Image.open(tmp_path / _NAME) as image, Image.open(tmp_path / _ALPHA) as image_a:
        color, alpha = image.copy(), image_a.copy()
    if fault == "baseline":
        recipe = replace(recipe, coverage_baseline=13)
    elif fault == "anchor":
        color.putpixel((0, 1), _KEY)
    elif fault == "rows":
        recipe = replace(recipe, line_count=4)
    elif fault == "marker":
        color.putpixel((2, 51), _KEY)
    else:
        alpha = alpha.crop((0, 0, 480, 68))
    with pytest.raises(ValueError, match=r"font recipe|layout repair|row markers"):
        repair_courier_layout(color, alpha, recipe)
