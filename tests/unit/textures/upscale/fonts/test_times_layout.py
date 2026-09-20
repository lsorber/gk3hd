"""A correct cell count cannot hide fused braces and a split quotation mark."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.upscale.fonts.atlas import font_atlas_recipe, parse_glyph_cells
from gk3hd.textures.upscale.fonts.layout import repair_times_underline_layout
from tests.times_fixtures import make_times_opacity_pair

if TYPE_CHECKING:
    from pathlib import Path

_NAME = "TIMES_B_U_14.BMP"


def test_punctuation_repair_changes_only_two_markers_and_keeps_advances(tmp_path: Path) -> None:
    make_times_opacity_pair(tmp_path, _NAME)
    recipe = font_atlas_recipe(_NAME)
    assert recipe is not None
    with Image.open(tmp_path / _NAME) as color:
        before = color.tobytes()
        old = parse_glyph_cells(color, recipe)
        fixed = repair_times_underline_layout(color, recipe)
        cells = parse_glyph_cells(fixed, recipe)
        assert len(old) == len(cells) == 181
        changed = np.argwhere(np.any(np.asarray(color) != np.asarray(fixed), axis=2))
        assert changed.tolist() == [[18, 159], [18, 179]]
        assert [c.rect for c in cells[:80]] == [c.rect for c in old[:80]]
        assert [c.rect for c in cells[87:]] == [c.rect for c in old[87:]]
        assert [(c.character, c.rect) for c in cells[80:87]] == [
            (0x7B, (154, 19, 159, 36)),
            (0x7D, (159, 19, 164, 36)),
            (0x7C, (164, 19, 166, 36)),
            (0x3B, (166, 19, 170, 36)),
            (0x27, (170, 19, 173, 36)),
            (0x3A, (173, 19, 176, 36)),
            (0x22, (176, 19, 183, 36)),
        ]
        for cell in cells:
            assert fixed.crop(cell.rect).tobytes() == color.crop(cell.rect).tobytes()
        assert sum(c.rect[2] - c.rect[0] for c in cells) == sum(c.rect[2] - c.rect[0] for c in old)
        assert color.tobytes() == before
        with pytest.raises(ValueError, match="row markers"):
            repair_times_underline_layout(fixed, recipe)


@pytest.mark.parametrize("fault", ["name", "size", "mode", "rows", "characters", "marker", "count"])
def test_punctuation_repair_rejects_unreviewed_sources(tmp_path: Path, fault: str) -> None:
    make_times_opacity_pair(tmp_path, _NAME)
    recipe = font_atlas_recipe(_NAME)
    assert recipe is not None
    with Image.open(tmp_path / _NAME) as image:
        color = image.copy()
    if fault == "name":
        recipe = replace(recipe, primary="TIMES_B_14.BMP")
    elif fault == "size":
        color = color.crop((0, 0, 500, 54))
    elif fault == "mode":
        color = color.convert("L")
    elif fault == "rows":
        recipe = replace(recipe, line_count=4)
    elif fault == "characters":
        recipe = replace(recipe, characters=recipe.characters.replace(b"{", b"}"))
    elif fault == "marker":
        color.putpixel((179, 18), (255, 0, 0))
    else:
        color.putpixel((179, 18), (255, 0, 255))
    with pytest.raises(ValueError, match=r"layout repair|row markers"):
        repair_times_underline_layout(color, recipe)


def test_small_underline_repairs_space_and_ij_without_moving_artwork(tmp_path: Path) -> None:
    name = "TIMES_B_U_12.BMP"
    make_times_opacity_pair(tmp_path, name)
    recipe = font_atlas_recipe(name)
    assert recipe is not None
    with Image.open(tmp_path / name) as color:
        before = color.tobytes()
        old = parse_glyph_cells(color, replace(recipe, characters=recipe.characters[:-1]))
        fixed = repair_times_underline_layout(color, recipe)
        cells = parse_glyph_cells(fixed, recipe)
        assert len(old) == 180
        assert len(cells) == 181
        changed = np.argwhere(np.any(np.asarray(color) != np.asarray(fixed), axis=2))
        assert changed.tolist() == [[0, 300], [0, 301], [0, 482]]
        assert [(c.character, c.rect) for c in cells[34:36]] == [
            (ord("i"), (296, 1, 300, 17)),
            (ord("j"), (300, 1, 305, 17)),
        ]
        assert [(c.character, c.rect) for c in cells[61:64]] == [
            (ord("9"), (476, 1, 482, 17)),
            (ord(" "), (482, 1, 489, 17)),
            (ord("!"), (489, 1, 492, 17)),
        ]
        assert cells[-1].character == 0xFF
        assert [c.rect for c in old[:34]] == [c.rect for c in cells[:34]]
        assert [c.rect for c in old[36:61]] == [c.rect for c in cells[36:61]]
        assert [c.rect for c in old[62:]] == [c.rect for c in cells[63:]]
        assert sum(c.rect[2] - c.rect[0] for c in old) == sum(c.rect[2] - c.rect[0] for c in cells)
        for cell in cells:
            assert fixed.crop(cell.rect).tobytes() == color.crop(cell.rect).tobytes()
        assert color.tobytes() == before
        with pytest.raises(ValueError, match="row markers"):
            repair_times_underline_layout(fixed, recipe)


@pytest.mark.parametrize("fault", ["size", "mode", "rows", "characters", "marker", "count"])
def test_small_underline_rejects_unverified_contracts(tmp_path: Path, fault: str) -> None:
    name = "TIMES_B_U_12.BMP"
    make_times_opacity_pair(tmp_path, name)
    recipe = font_atlas_recipe(name)
    assert recipe is not None
    with Image.open(tmp_path / name) as image:
        color = image.copy()
    if fault == "size":
        color = color.crop((0, 0, 500, 51))
    elif fault == "mode":
        color = color.convert("L")
    elif fault == "rows":
        recipe = replace(recipe, line_count=4)
    elif fault == "characters":
        recipe = replace(recipe, characters=recipe.characters.replace(b"ij", b"ji"))
    elif fault == "marker":
        color.putpixel((301, 0), (255, 0, 0))
    else:
        color.putpixel((482, 0), (255, 255, 255))
    with pytest.raises(ValueError, match=r"layout repair|row markers"):
        repair_times_underline_layout(color, recipe)
