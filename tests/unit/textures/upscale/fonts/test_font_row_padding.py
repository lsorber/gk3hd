"""A malformed descriptor can be honored without changing glyph artwork."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.upscale.fonts.atlas import (
    font_atlas_output_size,
    font_atlas_recipe,
    parse_glyph_cells,
    regenerate_font_atlas,
)
from gk3hd.textures.upscale.fonts.layout import repair_times_bold_layout
from tests.times_fixtures import make_times_opacity_pair

if TYPE_CHECKING:
    from pathlib import Path

_PRIMARY = "TIMES_B_14.BMP"
_ALPHA = "TIMES_B_14A.BMP"


def test_padding_preserves_artwork_and_terminates_empty_descriptor_row(tmp_path: Path) -> None:
    make_times_opacity_pair(tmp_path, _PRIMARY)
    recipe = font_atlas_recipe(_PRIMARY)
    assert recipe is not None
    with Image.open(tmp_path / _PRIMARY) as c, Image.open(tmp_path / _ALPHA) as a:
        color, opacity = c.copy(), a.copy()
    repaired, alpha = repair_times_bold_layout(color, opacity, recipe)
    assert repaired.size == alpha.size == (522, 72)
    assert parse_glyph_cells(repaired, recipe)[-1].character == 0xFF
    assert len(parse_glyph_cells(repaired, recipe)) == len(recipe.characters)
    delta = np.any(np.asarray(color) != np.asarray(repaired)[:54], axis=2)
    assert np.argwhere(delta).tolist() == [[18, 159], [18, 179]]
    assert alpha.crop((0, 0, 522, 54)).tobytes() == opacity.tobytes()
    assert alpha.crop((0, 54, 522, 72)).getbbox() is None
    assert repaired.getpixel((1, 54)) == (255, 255, 255)
    for name in (_PRIMARY, _ALPHA):
        assert font_atlas_output_size(name, (522, 54)) == (4176, 288)
        assert font_atlas_output_size(name, (520, 54)) == (2080, 216)


@pytest.mark.parametrize("fault", ["size", "companion", "baseline", "marker"])
def test_padding_rejects_unverified_sources(tmp_path: Path, fault: str) -> None:
    make_times_opacity_pair(tmp_path, _PRIMARY)
    recipe = font_atlas_recipe(_PRIMARY)
    assert recipe is not None
    with Image.open(tmp_path / _PRIMARY) as c, Image.open(tmp_path / _ALPHA) as a:
        color, opacity = c.copy(), a.copy()
    if fault == "size":
        color = color.crop((0, 0, 522, 53))
    elif fault == "companion":
        opacity = opacity.crop((0, 0, 522, 53))
    elif fault == "baseline":
        color.putpixel((0, 13), (255, 0, 255))
    else:
        color.putpixel((154, 18), (255, 0, 255))
    with pytest.raises(ValueError, match=r"verified|markers"):
        repair_times_bold_layout(color, opacity, recipe)


@pytest.mark.slow
def test_zero_opacity_white_ink_stays_exact_in_both_color_banks(tmp_path: Path) -> None:
    make_times_opacity_pair(tmp_path, _PRIMARY)
    with (
        Image.open(tmp_path / _PRIMARY) as c,
        (tmp_path / _ALPHA).open("rb") as stream,
        Image.open(stream) as a,
    ):
        color, opacity = c.copy(), a.copy()
    color.putpixel((2, 4), (255, 255, 255))
    opacity.putpixel((2, 4), 0)
    color.save(tmp_path / _PRIMARY)
    opacity.save(tmp_path / _ALPHA)
    output = regenerate_font_atlas(tmp_path / _PRIMARY)
    alpha = regenerate_font_atlas(tmp_path / _ALPHA)
    for bank in (0, 2088):
        assert set(output.crop((bank + 8, 16, bank + 12, 20)).get_flattened_data()) == {
            (255, 255, 255)
        }
        assert alpha.crop((bank + 8, 16, bank + 12, 20)).getbbox() is None
