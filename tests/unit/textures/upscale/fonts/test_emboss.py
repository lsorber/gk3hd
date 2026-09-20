"""A plain companion constrains glyph shape without replacing authored shading."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

import gk3hd.textures.upscale.service as texture_upscale
from gk3hd.textures.upscale.fonts.atlas import (
    _render_exact_raster_atlas,
    font_atlas_recipe,
    parse_glyph_cells,
    regenerate_font_atlas,
)
from gk3hd.textures.upscale.fonts.bank import font_row_bank_layout, has_font_row_bank
from tests.font_fixtures import make_sidney_embossed_source

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("size", [10, 11, 28])
@pytest.mark.slow
def test_embossed_atlas_conserves_color_mask_and_reference(tmp_path: Path, size: int) -> None:
    make_sidney_embossed_source(tmp_path, size=size)
    source = tmp_path / f"SID_EMB_{size}.BMP"
    with Image.open(source) as image:
        original = image.convert("RGB")
    recipe = font_atlas_recipe(source.name)
    assert recipe is not None
    cells = parse_glyph_cells(original, recipe)
    result = regenerate_font_atlas(source)
    layout = font_row_bank_layout(source.name)
    assert layout is not None
    assert result.size == layout.image_size
    assert has_font_row_bank(result)
    reference = _render_exact_raster_atlas(original, cells, recipe)
    offset = layout.bank_distance
    assert result.crop((0, 0, offset, result.height)).tobytes() == reference.tobytes()
    changed = 0
    for cell in cells:
        old = np.asarray(original.crop(cell.rect)) >> np.array([3, 2, 3])
        left, top, right, bottom = (value * 4 for value in cell.rect)
        new = np.asarray(result.crop((left + offset, top, right + offset, bottom))) >> np.array(
            [3, 2, 3]
        )
        nearest = np.repeat(np.repeat(old, 4, axis=0), 4, axis=1)
        assert np.array_equal(
            new.reshape(old.shape[0], 4, old.shape[1], 4, 3).sum(axis=(1, 3)), old * 16
        )
        if (size == 11 and cell.character in b"EH") or (
            size == 10 and cell.character in b"oq2\xdf\xef"
        ):
            assert np.array_equal(new, nearest)
        assert np.array_equal(
            np.all(new == (21, 31, 6), axis=2), np.all(nearest == (21, 31, 6), axis=2)
        )
        assert np.all(new[np.all(nearest == 0, axis=2)] == 0)
        changed += np.count_nonzero(new != nearest)
    assert changed > 0


@pytest.mark.parametrize("size", [22, 28])
@pytest.mark.parametrize("fault", ["size", "baseline", "column", "marker", "shading"])
@pytest.mark.slow
def test_large_embossed_atlas_rejects_changed_source_contract(
    tmp_path: Path, size: int, fault: str
) -> None:
    make_sidney_embossed_source(tmp_path, size=size)
    source = tmp_path / f"SID_EMB_{size}.BMP"
    with Image.open(source) as opened:
        image = opened.copy()
    if fault == "size":
        image = image.crop((0, 0, image.width - 1, image.height))
    else:
        position, color = {
            "baseline": ((0, 18 if size == 22 else 22), (172, 125, 49)),
            "column": ((0, 1), (0, 0, 0)),
            "marker": ((1, 0), (0, 0, 0)),
            "shading": ((2, 2), (255, 255, 255)),
        }[fault]
        image.putpixel(position, color)
    image.save(source)
    with pytest.raises(ValueError, match="SID_EMB_"):
        regenerate_font_atlas(source)


@pytest.mark.parametrize("size", [22, 28])
@pytest.mark.slow
def test_large_embossed_atlas_does_not_read_or_infer_a_plain_companion(
    tmp_path: Path, size: int
) -> None:
    make_sidney_embossed_source(tmp_path, size=size)
    source = tmp_path / f"SID_EMB_{size}.BMP"
    expected = regenerate_font_atlas(source).tobytes()
    (tmp_path / f"SID_NO_EMB_{size}.BMP").write_bytes(b"not a font or a matte")
    assert regenerate_font_atlas(source).tobytes() == expected


@pytest.mark.slow
def test_small_embossed_atlas_maps_characters_across_different_rows(tmp_path: Path) -> None:
    make_sidney_embossed_source(tmp_path, size=11)
    recipe = font_atlas_recipe("SID_EMB_11.BMP")
    assert recipe is not None
    with Image.open(tmp_path / "SID_EMB_11.BMP") as embossed:
        cells = parse_glyph_cells(embossed, recipe)
    with Image.open(tmp_path / "SID_NO_EMB_11.BMP") as plain:
        mattes = parse_glyph_cells(plain, recipe)
    assert cells[60].rect[1] != mattes[60].rect[1]
    assert regenerate_font_atlas(tmp_path / recipe.primary).size == (4304, 180)


@pytest.mark.slow
def test_small_embossed_atlas_rejects_changed_character_advance(tmp_path: Path) -> None:
    make_sidney_embossed_source(tmp_path, size=11)
    path = tmp_path / "SID_EMB_11.BMP"
    with Image.open(path) as source:
        image = source.copy()
    image.putpixel((6, 0), (172, 125, 49))
    image.putpixel((7, 0), (255, 255, 255))
    image.save(path)
    with pytest.raises(ValueError, match="companion dimensions differ"):
        regenerate_font_atlas(path)


@pytest.mark.parametrize("fault", ["ink", "width"])
@pytest.mark.slow
def test_percent_matte_may_only_lose_one_empty_column(tmp_path: Path, fault: str) -> None:
    make_sidney_embossed_source(tmp_path, size=10)
    source = tmp_path / "SID_EMB_10.BMP"
    path = tmp_path / "SID_NO_EMB_10.BMP" if fault == "ink" else source
    recipe = font_atlas_recipe(path.name)
    assert recipe is not None
    with Image.open(path) as opened:
        image = opened.copy()
    cell = next(c for c in parse_glyph_cells(image, recipe) if c.character == ord("%"))
    if fault == "ink":
        image.putpixel((cell.rect[2] - 1, cell.rect[1] + 1), (57, 60, 57))
    else:
        # Move the end marker: the other glyph's space must not be borrowed.
        right, marker_y = cell.rect[2], cell.rect[1] - 1
        image.putpixel((right, marker_y), (172, 125, 49))
        image.putpixel((right + 1, marker_y), (255, 255, 255))
    image.save(path)
    with pytest.raises(ValueError, match="percent companion must have one extra blank"):
        regenerate_font_atlas(source)


@pytest.mark.parametrize("fault", ["missing", "size", "marker", "ink", "shading", "plain-palette"])
@pytest.mark.parametrize("size", [10, 11, 18])
@pytest.mark.slow
def test_embossed_atlas_rejects_unverified_pair(tmp_path: Path, fault: str, size: int) -> None:
    make_sidney_embossed_source(tmp_path, size=size)
    source = tmp_path / f"SID_EMB_{size}.BMP"
    companion = tmp_path / f"SID_NO_EMB_{size}.BMP"
    if fault == "missing":
        companion.unlink()
    else:
        path = companion if fault == "plain-palette" else source
        with path.open("rb") as stream, Image.open(stream) as original:
            image = original.copy()
        if fault == "size":
            image = image.crop((0, 0, 517, 115))
        else:
            position, color = {
                "marker": ((0, {10: 9, 11: 10, 18: 15}[size]), (172, 125, 49)),
                "ink": ((2, 2), (0, 0, 0)),
                "shading": ((2, 2), (255, 255, 255)),
                "plain-palette": ((2, 2), (255, 0, 255)),
            }[fault]
            image.putpixel(position, color)
        image.save(path)
    with pytest.raises(ValueError, match=rf"SID_.*{size}"):
        regenerate_font_atlas(source)


@pytest.mark.parametrize("size", [10])
@pytest.mark.slow
def test_resume_rechecks_plain_companion_pixels(tmp_path: Path, size: int) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    make_sidney_embossed_source(source, size=size)
    assert texture_upscale.upscale(source, output).created == 2
    destination = output / f"SID_EMB_{size}.PNG"
    previous = destination.read_bytes()
    companion = source / f"SID_NO_EMB_{size}.BMP"
    with companion.open("rb") as stream, Image.open(stream) as original:
        image = original.copy()
    pixels = np.asarray(image)
    y, x = np.argwhere(np.all(pixels == (90, 76, 57), axis=2))[0]
    image.putpixel((int(x), int(y)), (98, 80, 57))
    image.save(companion)
    assert texture_upscale.upscale(source, output).created == 2
    assert destination.read_bytes() != previous
