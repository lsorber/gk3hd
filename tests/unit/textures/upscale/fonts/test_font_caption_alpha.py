"""Caption opacity reconstruction retains color, metrics and parser background."""

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
from tests.caption_font_fixtures import make_caption_opacity_pair

if TYPE_CHECKING:
    from pathlib import Path

_COLOR = "F_CAPTION_GOUDY14AA.BMP"
_ALPHA = "F_CAPTION_GOUDY14AA_ALPHA.BMP"
_SIZE = (1485, 18)


@pytest.mark.slow
def test_caption_preserves_reference_and_color_times_opacity(tmp_path: Path) -> None:
    make_caption_opacity_pair(tmp_path)
    originals = {name: (tmp_path / name).read_bytes() for name in (_COLOR, _ALPHA)}
    color, alpha = (regenerate_font_atlas(tmp_path / name) for name in (_COLOR, _ALPHA))
    assert color.size == alpha.size == (11880, 72)
    assert has_font_row_bank(color)
    assert all(font_atlas_output_size(name, _SIZE) == color.size for name in originals)
    recipe = font_atlas_recipe(_COLOR)
    assert recipe is not None
    with Image.open(tmp_path / _COLOR) as c, Image.open(tmp_path / _ALPHA) as a:
        cells = parse_glyph_cells(c, recipe)
        assert len(cells) == 181
        for name, old, new in ((_COLOR, c, color), (_ALPHA, a, alpha)):
            member = font_atlas_recipe(name)
            assert member is not None
            expected = _render_exact_raster_atlas(old, cells, member)
            assert new.crop((0, 0, 5940, 72)).tobytes() == expected.tobytes()
        changes = 0
        for cell in cells:
            left, top, right, bottom = cell.rect
            height, width = bottom - top, right - left
            crop = (5940 + left * 4, top * 4, 5940 + right * 4, bottom * 4)
            old_c = np.asarray(c.crop(cell.rect)).astype(np.uint32)
            old_a = np.asarray(a.crop(cell.rect)).astype(np.uint32)
            new_c = np.asarray(color.crop(crop)).astype(np.uint32)
            new_a = np.asarray(alpha.crop(crop)).astype(np.uint32)
            np.testing.assert_array_equal(new_c, old_c.repeat(4, 0).repeat(4, 1))
            np.testing.assert_array_equal(
                new_a.reshape(height, 4, width, 4).sum((1, 3)), old_a * 16
            )
            product = (new_c * new_a[..., None]).reshape(height, 4, width, 4, 3)
            np.testing.assert_array_equal(product.sum((1, 3)), old_c * old_a[..., None] * 16)
            changes += int(np.count_nonzero(new_a != old_a.repeat(4, 0).repeat(4, 1)))
        assert changes > 0
    # The white parser background is not the magenta color key. No phantom
    # boundaries may appear in the extra, unaddressed bank-storage interval.
    assert color.getpixel((5940, 0)) == (0, 0, 0)
    assert color.crop((5941, 0, 11880, 1)).getcolors() == [(5939, (255, 255, 255))]
    assert originals == {name: (tmp_path / name).read_bytes() for name in originals}


@pytest.mark.parametrize("name", [_COLOR, _ALPHA])
@pytest.mark.parametrize("position", [(0, 13), (0, 2), (0, 17), (4, 0), (2, 4)])
@pytest.mark.slow
def test_caption_rejects_wrong_metadata_and_color(
    tmp_path: Path, name: str, position: tuple[int, int]
) -> None:
    make_caption_opacity_pair(tmp_path)
    with Image.open(tmp_path / _COLOR) as source:
        changed = source.copy()
    changed.putpixel(position, (255, 0, 0))
    changed.save(tmp_path / _COLOR)
    with pytest.raises(ValueError, match=r"verified.*recipe"):
        regenerate_font_atlas(tmp_path / name)
