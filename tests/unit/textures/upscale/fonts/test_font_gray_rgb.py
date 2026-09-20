"""Gray RGB reconstruction retains green precision and uncertain source marks."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.upscale.fonts.atlas import (
    font_atlas_recipe,
    parse_glyph_cells,
    regenerate_font_atlas,
)
from gk3hd.textures.upscale.fonts.coverage import reconstruct_font_coverage
from gk3hd.textures.upscale.fonts.reconstruction import _reconstruct_gray_rgb
from tests.font_fixtures import make_sidney_pair

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("parity", [0, 1])
def test_rgb_precision_is_conserved_and_uncertain_components_are_not_sharpened(parity: int) -> None:
    source = np.zeros((10, 10, 3), dtype=np.uint8)
    source[2:5, 2:5] = (15, 30 + parity, 15)
    source[3, 3] = (31, 62 + parity, 31)
    source[8, 8] = (23, 46 + parity, 23)
    shifts = np.array([3, 2, 3], dtype=np.uint8)
    color = source << shifts
    blue = reconstruct_font_coverage(np.pad(source[..., 2], 2))[8:-8, 8:-8]
    original_blue = blue.copy()
    output = _reconstruct_gray_rgb(color, blue) >> shifts
    np.testing.assert_array_equal(blue, original_blue)
    np.testing.assert_array_equal(
        output.reshape(10, 4, 10, 4, 3).sum(axis=(1, 3)), source.astype(np.uint16) * 16
    )
    np.testing.assert_array_equal(output[32:36, 32:36], np.tile(source[8, 8], (4, 4, 1)))
    nearest = np.repeat(np.repeat(source, 4, axis=0), 4, axis=1)
    assert np.any(output[8:20, 8:20] != nearest[8:20, 8:20])
    assert np.all(output[:8] == 0)
    np.testing.assert_array_equal(output[..., 0], output[..., 2])


@pytest.mark.parametrize("color", [(16, 128, 16), (16, 16, 128)])
@pytest.mark.slow
def test_unverified_colored_glyphs_are_rejected(
    tmp_path: Path, color: tuple[int, int, int]
) -> None:
    make_sidney_pair(tmp_path, include_medium=True)
    path = tmp_path / "F_ARIAL_A12.BMP"
    with Image.open(path) as original:
        changed = original.copy()
    changed.putpixel((1, 2), color)
    changed.save(path)
    with pytest.raises(ValueError, match="verified grayscale RGB palette"):
        regenerate_font_atlas(path)


@pytest.mark.slow
def test_atlas_preserves_each_rgb_mean_and_its_own_character_geometry(tmp_path: Path) -> None:
    make_sidney_pair(tmp_path, include_medium=True)
    path = tmp_path / "F_ARIAL_A12.BMP"
    before = path.read_bytes()
    output = regenerate_font_atlas(path)
    recipe = font_atlas_recipe(path.name)
    assert recipe is not None
    assert output.size == (6680, 68)
    with Image.open(path) as original:
        cells = parse_glyph_cells(original, recipe)
        assert len(cells) == 94
        for cell in cells:
            shifts = np.array([3, 2, 3], dtype=np.uint8)
            old = np.asarray(original.crop(cell.rect)) >> shifts
            left, top, right, bottom = (value * 4 for value in cell.rect)
            new = np.asarray(output.crop((3340 + left, top, 3340 + right, bottom))) >> shifts
            sums = new.reshape(old.shape[0], 4, old.shape[1], 4, 3).sum(axis=(1, 3))
            np.testing.assert_array_equal(sums, old.astype(np.uint16) * 16)
    assert path.read_bytes() == before
