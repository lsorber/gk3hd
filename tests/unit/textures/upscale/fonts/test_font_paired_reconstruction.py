"""Paired color/opacity coverage preserves original cells and eight-bit ink."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.upscale.fonts.atlas import (
    FontAtlasRecipe,
    _render_exact_raster_atlas,
    font_atlas_output_size,
    font_atlas_recipe,
    parse_glyph_cells,
    regenerate_font_atlas,
)
from gk3hd.textures.upscale.fonts.bank import has_font_row_bank
from gk3hd.textures.upscale.fonts.layout import (
    repair_courier_layout,
    repair_times_bold_layout,
    repair_times_replacement_anchor,
    repair_times_underline_layout,
)
from gk3hd.textures.upscale.fonts.reconstruction import SOURCE_GLYPH_EXCEPTIONS
from tests.font_fixtures import make_courier_opacity_pair, make_tempus_opacity_pair
from tests.numeric_font_fixtures import make_numeric_font_pair
from tests.times_fixtures import make_times_opacity_pair

if TYPE_CHECKING:
    from pathlib import Path

_COLOR = "F_TEMPUS_10.BMP"
_ALPHA = "F_TEMPUS_10_ALPHA.BMP"
_PAIRS = (
    _COLOR,
    "F_NUM_TLARGE.BMP",
    "TIMES_B_14.BMP",
    "COURIER_R_12.BMP",
    "COURIER_B_12.BMP",
    "COURIER_B_14.BMP",
    "COURIER_I_12.BMP",
    "COURIER_B_I_12.BMP",
    "COURIER_R_14.BMP",
    "TIMES_R_12.BMP",
    "TIMES_B_12.BMP",
    "TIMES_B_U_12.BMP",
    "TIMES_R_U_12.BMP",
    "TIMES_R_14.BMP",
    "TIMES_R_U_14.BMP",
    "TIMES_B_U_14.BMP",
)


def _repair_pair(
    color: Image.Image, opacity: Image.Image, recipe: FontAtlasRecipe
) -> tuple[Image.Image, Image.Image]:
    primary = recipe.primary
    if primary == "TIMES_B_14.BMP":
        return repair_times_bold_layout(color, opacity, recipe)
    if primary.startswith("COURIER_"):
        return repair_courier_layout(color, opacity, recipe)
    if primary in {"TIMES_B_U_12.BMP", "TIMES_B_U_14.BMP"}:
        color = repair_times_underline_layout(color, recipe)
    elif primary == "TIMES_R_U_14.BMP":
        color = repair_times_replacement_anchor(color, recipe)
    return color, opacity


@pytest.mark.parametrize(
    "primary", [_COLOR, "F_NUM_TLARGE.BMP", "TIMES_B_14.BMP", "COURIER_I_12.BMP"]
)
@pytest.mark.slow
def test_both_planes_share_cells_and_preserve_full_precision(tmp_path: Path, primary: str) -> None:
    if primary == _COLOR:
        make_tempus_opacity_pair(tmp_path)
    elif primary == "F_NUM_TLARGE.BMP":
        make_numeric_font_pair(tmp_path)
    elif primary.startswith("TIMES_"):
        make_times_opacity_pair(tmp_path, primary)
    else:
        make_courier_opacity_pair(tmp_path, primary)
    recipe = font_atlas_recipe(primary)
    assert recipe is not None
    assert recipe.alpha_companion is not None
    names = (primary, recipe.alpha_companion)
    originals = {name: (tmp_path / name).read_bytes() for name in names}
    with Image.open(tmp_path / primary) as c, Image.open(tmp_path / recipe.alpha_companion) as a:
        color, opacity = c.convert("RGB"), a.convert("L")
    source_size = color.size
    color, opacity = _repair_pair(color, opacity, recipe)
    cells = parse_glyph_cells(color, recipe)
    for name in names:
        recipe = font_atlas_recipe(name)
        assert recipe is not None
        with (opacity if recipe.alpha else color).copy() as original:
            reference = _render_exact_raster_atlas(original, cells, recipe)
            result = regenerate_font_atlas(tmp_path / name)
            stride = original.width * 4
            assert result.size == font_atlas_output_size(name, source_size)
            assert result.size == (stride * 2, original.height * 4)
            assert result.mode == ("L" if recipe.alpha else "RGB")
            assert result.crop((0, 0, stride, result.height)).tobytes() == reference.tobytes()
            changed = 0
            for cell in cells:
                left, top, right, bottom = (v * 4 for v in cell.rect)
                candidate = result.crop((stride + left, top, stride + right, bottom))
                source_copy = reference.crop((left, top, right, bottom))
                if not recipe.alpha or cell.character in SOURCE_GLYPH_EXCEPTIONS.get(
                    primary, frozenset()
                ) | {0x9D}:
                    assert candidate.tobytes() == source_copy.tobytes()
                else:
                    before, after = np.asarray(original.crop(cell.rect)), np.asarray(candidate)
                    sums = after.reshape(before.shape[0], 4, before.shape[1], 4).sum(axis=(1, 3))
                    visible = np.where(before > recipe.coverage_key_threshold, before, 0)
                    np.testing.assert_array_equal(sums, visible.astype(np.int16) * 16)
                    changed += candidate.tobytes() != source_copy.tobytes()
            if recipe.alpha:
                assert changed > 0
            else:
                assert has_font_row_bank(result)
    assert originals == {name: (tmp_path / name).read_bytes() for name in originals}


@pytest.mark.parametrize("primary", _PAIRS)
@pytest.mark.parametrize("request_alpha", [False, True])
@pytest.mark.parametrize("fault", ["missing", "size", "baseline", "mask", "tint"])
@pytest.mark.slow
def test_either_output_rejects_invalid_pair(
    tmp_path: Path, primary: str, request_alpha: bool, fault: str
) -> None:
    if primary == _COLOR:
        make_tempus_opacity_pair(tmp_path)
    elif primary == "F_NUM_TLARGE.BMP":
        make_numeric_font_pair(tmp_path)
    elif primary.startswith("TIMES_"):
        make_times_opacity_pair(tmp_path, primary)
    else:
        make_courier_opacity_pair(tmp_path, primary)
    recipe = font_atlas_recipe(primary)
    assert recipe is not None
    assert recipe.alpha_companion is not None
    companion = recipe.alpha_companion
    requested = companion if request_alpha else primary
    if fault == "missing":
        (tmp_path / companion).unlink()
    elif fault == "size":
        Image.new("L", (182, 64)).save(tmp_path / companion)
    else:
        with Image.open(tmp_path / primary) as opened:
            color = opened.copy()
        pixel, value = {
            "baseline": ((0, 11), (255, 0, 0)),
            "mask": ((1, 2), (0, 0, 0)),
            "tint": ((1, 2), (128, 128, 128)),
        }[fault]
        color.putpixel(pixel, value)
        color.save(tmp_path / primary)
    with pytest.raises(
        ValueError, match=r"companion|dimensions|verified font recipe|masks disagree"
    ):
        regenerate_font_atlas(tmp_path / requested)
