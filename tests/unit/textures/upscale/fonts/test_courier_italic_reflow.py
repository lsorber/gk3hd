"""Italic Courier repairs preserve artwork and reject unverified discarded regions."""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING

import pytest
from PIL import Image

from gk3hd.textures.upscale.fonts.atlas import (
    font_atlas_recipe,
    parse_glyph_cells,
    regenerate_font_atlas,
)
from gk3hd.textures.upscale.fonts.layout import repair_courier_layout
from tests.courier_fixtures import make_italic_courier_pair

if TYPE_CHECKING:
    from pathlib import Path

_NAMES = ("COURIER_I_14.BMP", "COURIER_B_I_14.BMP")
_KEY = (255, 0, 255)


@pytest.mark.parametrize("name", _NAMES)
@pytest.mark.slow
def test_italic_reflow_preserves_samples_advances_and_complete_final_cell(
    tmp_path: Path, name: str
) -> None:
    make_italic_courier_pair(tmp_path, name)
    recipe = font_atlas_recipe(name)
    assert recipe is not None
    assert recipe.alpha_companion is not None
    with Image.open(tmp_path / name) as color, Image.open(tmp_path / recipe.alpha_companion) as a:
        before = color.tobytes(), a.tobytes()
        rects = []
        for row, top in enumerate((0, 17, 34, 51)):
            marks = [x for x in range(1, color.width) if color.getpixel((x, top)) != _KEY]
            if row < 3:
                marks.pop()
            if name == _NAMES[0] and row == 2:
                marks.remove(189)
                marks.remove(190)
            if name == _NAMES[0] and row == 3:
                marks[-1] = 31
            rects.extend((lft, top + 1, rgt, top + 17) for lft, rgt in pairwise(marks))
        assert len(rects) == 182
        left, right = rects[148:150]
        rects[148:150] = [(left[0], left[1], right[2], right[3])]
        fixed, alpha = repair_courier_layout(color, a, recipe)
        assert fixed.size == ((523, 66) if name == _NAMES[0] else (545, 66))
        cells = parse_glyph_cells(fixed, recipe)
        assert len(cells) == 181
        assert cells[-1].character == 255
        assert cells[-1].rect[2] - cells[-1].rect[0] == 11
        for cell, rect in zip(cells, rects, strict=True):
            lft, top, rgt, bottom = cell.rect
            assert rgt - lft == rect[2] - rect[0]
            assert bottom - top == 21
            assert fixed.crop((lft, top, rgt, top + 16)).tobytes() == color.crop(rect).tobytes()
            assert alpha.crop((lft, top, rgt, top + 16)).tobytes() == a.crop(rect).tobytes()
        assert before == (color.tobytes(), a.tobytes())
    # Exercise the public path, not only the marker helper.
    assert regenerate_font_atlas(tmp_path / name).size == (fixed.width * 8, 264)
    assert regenerate_font_atlas(tmp_path / recipe.alpha_companion).size == (fixed.width * 8, 264)


@pytest.mark.parametrize("fault", ["trailing", "tail", "bearing", "stray", "noisy-boundary"])
def test_italic_reflow_refuses_to_discard_or_reinterpret_unverified_ink(
    tmp_path: Path, fault: str
) -> None:
    name = _NAMES[0]
    make_italic_courier_pair(tmp_path, name)
    recipe = font_atlas_recipe(name)
    assert recipe is not None
    assert recipe.alpha_companion is not None
    with Image.open(tmp_path / name) as c, Image.open(tmp_path / recipe.alpha_companion) as a:
        color, alpha = c.copy(), a.copy()
    x, y = {
        "trailing": (519, 2),
        "tail": (31, 60),
        "bearing": (20, 60),
        "stray": (189, 34),
        "noisy-boundary": (520, 51),
    }[fault]
    color.putpixel((x, y), (255, 255, 255))
    alpha.putpixel((x, y), 255)
    with pytest.raises(
        ValueError, match=r"discard visible|bearing repair|stray markers|row markers"
    ):
        repair_courier_layout(color, alpha, recipe)
