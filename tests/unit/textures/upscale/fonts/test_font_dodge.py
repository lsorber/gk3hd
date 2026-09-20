"""The precolored paired font preserves color, opacity, geometry and metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.upscale.fonts.atlas import (
    _render_exact_raster_atlas,
    font_atlas_output_size,
    font_atlas_recipe,
    parse_glyph_cells,
    regenerate_font_atlas,
)
from gk3hd.textures.upscale.fonts.bank import has_font_row_bank
from tests.dodge_font_fixtures import make_dodge_font_pair

if TYPE_CHECKING:
    from pathlib import Path

_NAMES = ("F_DODGENBURN16.BMP", "F_DODGENBURN16_ALPHA.BMP")


@pytest.mark.slow
def test_precolored_opacity_conserves_each_channel_without_recoloring(tmp_path: Path) -> None:
    make_dodge_font_pair(tmp_path)
    original_bytes = {name: (tmp_path / name).read_bytes() for name in _NAMES}
    color = regenerate_font_atlas(tmp_path / _NAMES[0])
    alpha = regenerate_font_atlas(tmp_path / _NAMES[1])
    assert has_font_row_bank(color)
    assert color.size == alpha.size == (2152, 228)
    assert all(font_atlas_output_size(name, (269, 57)) == color.size for name in _NAMES)
    recipe = font_atlas_recipe(_NAMES[0])
    assert recipe is not None
    assert (len(recipe.characters), recipe.line_count) == (93, 3)
    assert recipe.characters[-1:] == b"?"
    with (
        Image.open(tmp_path / _NAMES[0]) as original_color,
        Image.open(tmp_path / _NAMES[1]) as original_alpha,
    ):
        cells = parse_glyph_cells(original_color, recipe)
        for name, output, original in zip(
            _NAMES, (color, alpha), (original_color, original_alpha), strict=True
        ):
            member = font_atlas_recipe(name)
            assert member is not None
            reference = _render_exact_raster_atlas(original, cells, member)
            assert output.crop((0, 0, 1076, 228)).tobytes() == reference.tobytes()
        changed = False
        for cell in cells:
            left, top, right, bottom = (value * 4 for value in cell.rect)
            crop = (1076 + left, top, 1076 + right, bottom)
            old_c = np.asarray(original_color.crop(cell.rect)).astype(np.uint32)
            old_a = np.asarray(original_alpha.crop(cell.rect)).astype(np.uint32)
            new_c = np.asarray(color.crop(crop)).astype(np.uint32)
            new_a = np.asarray(alpha.crop(crop)).astype(np.uint32)
            np.testing.assert_array_equal(new_c, np.repeat(np.repeat(old_c, 4, axis=0), 4, axis=1))
            sums = new_a.reshape(old_a.shape[0], 4, old_a.shape[1], 4).sum(axis=(1, 3))
            np.testing.assert_array_equal(sums, old_a * 16)
            premultiplied = (new_c * new_a[..., None]).reshape(
                old_a.shape[0], 4, old_a.shape[1], 4, 3
            )
            np.testing.assert_array_equal(
                premultiplied.sum(axis=(1, 3)), old_c * old_a[..., None] * 16
            )
            changed |= not np.array_equal(new_a, np.repeat(np.repeat(old_a, 4, axis=0), 4, axis=1))
        assert changed
    assert original_bytes == {name: (tmp_path / name).read_bytes() for name in _NAMES}


@pytest.mark.parametrize("name", _NAMES)
@pytest.mark.parametrize(
    ("position", "color"),
    [
        ((0, 14), (255, 255, 255)),
        ((0, 1), (255, 255, 255)),
        ((0, 54), (0, 0, 0)),
        ((1, 0), (255, 255, 255)),
        ((1, 2), (255, 255, 255)),
    ],
)
@pytest.mark.slow
def test_unreviewed_metadata_or_ink_is_rejected_in_both_planes(
    tmp_path: Path, name: str, position: tuple[int, int], color: tuple[int, int, int]
) -> None:
    make_dodge_font_pair(tmp_path)
    path = tmp_path / _NAMES[0]
    with Image.open(path) as original:
        modified = original.copy()
    modified.putpixel(position, color)
    modified.save(path)
    with pytest.raises(ValueError, match=r"verified font recipe|precolored glyph palette"):
        regenerate_font_atlas(tmp_path / name)
