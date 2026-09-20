"""Repair missing tint metadata without changing glyphs or the native lookup."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.upscale.fonts.atlas import font_atlas_recipe, parse_glyph_cells
from gk3hd.textures.upscale.fonts.layout import repair_times_replacement_anchor
from tests.times_fixtures import make_times_opacity_pair

if TYPE_CHECKING:
    from pathlib import Path

_NAME = "TIMES_R_U_14.BMP"


def test_anchor_repair_changes_only_tint_metadata(tmp_path: Path) -> None:
    make_times_opacity_pair(tmp_path, _NAME)
    recipe = font_atlas_recipe(_NAME)
    assert recipe is not None
    with Image.open(tmp_path / _NAME) as color:
        before = color.tobytes()
        old_cells = parse_glyph_cells(color, recipe)
        fixed = repair_times_replacement_anchor(color, recipe)
        cells = parse_glyph_cells(fixed, recipe)
        assert cells == old_cells
        assert len(cells) == 181
        assert np.argwhere(np.any(np.asarray(color) != np.asarray(fixed), axis=2)).tolist() == [
            [1, 0]
        ]
        assert fixed.getpixel((0, 1)) == (255, 255, 255)
        for cell in cells:
            assert fixed.crop(cell.rect).tobytes() == color.crop(cell.rect).tobytes()
        assert color.tobytes() == before
        with pytest.raises(ValueError, match="verified font recipe"):
            repair_times_replacement_anchor(fixed, recipe)


@pytest.mark.parametrize(
    "fault", ["name", "size", "mode", "rows", "characters", "baseline", "anchor", "marker"]
)
def test_anchor_repair_rejects_other_source_contracts(tmp_path: Path, fault: str) -> None:
    make_times_opacity_pair(tmp_path, _NAME)
    recipe = font_atlas_recipe(_NAME)
    assert recipe is not None
    with Image.open(tmp_path / _NAME) as image:
        color = image.copy()
    if fault == "name":
        recipe = replace(recipe, primary="TIMES_R_14.BMP")
    elif fault == "size":
        color = color.crop((0, 0, 490, 57))
    elif fault == "mode":
        color = color.convert("L")
    elif fault == "rows":
        recipe = replace(recipe, line_count=4)
    elif fault == "characters":
        recipe = replace(recipe, characters=recipe.characters[:-1])
    elif fault == "baseline":
        recipe = replace(recipe, coverage_baseline=12)
    elif fault == "anchor":
        color.putpixel((0, 1), (128, 128, 128))
    else:
        color.putpixel((1, 0), (255, 0, 255))
    with pytest.raises(ValueError, match="verified font recipe"):
        repair_times_replacement_anchor(color, recipe)
