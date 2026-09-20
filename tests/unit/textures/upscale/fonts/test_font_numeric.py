"""Numeric fonts preserve blue parser metadata and terminate the reference bank."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image

from gk3hd.textures.upscale.fonts.atlas import font_atlas_recipe, regenerate_font_atlas
from gk3hd.textures.upscale.fonts.bank import has_font_row_bank
from tests.numeric_font_fixtures import make_numeric_font_pair

if TYPE_CHECKING:
    from pathlib import Path

_COLOR = "F_NUM_TLARGE.BMP"
_ALPHA = "F_NUM_TLARGEA.BMP"
_KEY = (255, 0, 255)
_BLUE = (16, 56, 255)


@pytest.mark.slow
def test_numeric_bank_preserves_blue_markers_and_final_digit_advance(tmp_path: Path) -> None:
    make_numeric_font_pair(tmp_path)
    recipe = font_atlas_recipe(_COLOR)
    assert recipe is not None
    assert recipe.characters == b"1234567890"
    assert recipe.implicit_right_edge
    assert recipe.coverage_baseline_color == _BLUE
    result = regenerate_font_atlas(tmp_path / _COLOR)
    assert result.size == (928, 84)
    assert has_font_row_bank(result)
    for start in (0, 464):
        assert result.getpixel((start, 76)) == _BLUE
    assert result.getpixel((0, 1)) == (255, 255, 255)
    markers = [x for x in range(1, result.width) if result.getpixel((x, 0)) != _KEY]
    assert markers == [4, 40, 88, 132, 184, 232, 280, 320, 368, 416, 464]
    assert markers[-1] - markers[-2] == 12 * 4
    assert all(result.getpixel((x, 0)) == _BLUE for x in markers)
    assert regenerate_font_atlas(tmp_path / _ALPHA).mode == "L"


@pytest.mark.parametrize("requested", [_COLOR, _ALPHA])
@pytest.mark.parametrize("fault", ["baseline-color", "baseline-position", "replacement-color"])
@pytest.mark.slow
def test_numeric_font_rejects_unverified_metadata(
    tmp_path: Path, requested: str, fault: str
) -> None:
    make_numeric_font_pair(tmp_path)
    with Image.open(tmp_path / _COLOR) as original:
        color = original.copy()
    if fault == "baseline-color":
        color.putpixel((0, 19), (255, 255, 255))
    elif fault == "baseline-position":
        color.putpixel((0, 19), _KEY)
        color.putpixel((0, 18), _BLUE)
    else:
        color.putpixel((0, 1), _BLUE)
    color.save(tmp_path / _COLOR)
    with pytest.raises(ValueError, match="verified font recipe"):
        regenerate_font_atlas(tmp_path / requested)
