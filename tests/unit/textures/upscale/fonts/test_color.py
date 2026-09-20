"""Colored reconstruction must preserve native color, keying and glyph geometry."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.upscale.fonts.atlas import (
    _render_exact_raster_atlas,
    font_atlas_recipe,
    parse_glyph_cells,
    regenerate_font_atlas,
)
from gk3hd.textures.upscale.fonts.bank import has_font_row_bank
from gk3hd.textures.upscale.fonts.color import _preserve_key_mask, _reconstruct_glyph
from gk3hd.textures.upscale.fonts.coverage import conserve_font_channel
from tests.font_fixtures import make_sidney_color_source

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("size", [11, 18])
@pytest.mark.slow
def test_color_font_keeps_reference_metrics_colors_and_key(tmp_path: Path, size: int) -> None:
    make_sidney_color_source(tmp_path, size=size)
    path = tmp_path / f"SID_NO_EMB_{size}.BMP"
    original_bytes = path.read_bytes()
    with Image.open(path) as image:
        original = image.convert("RGB")
    recipe = font_atlas_recipe(path.name)
    assert recipe is not None
    cells = parse_glyph_cells(original, recipe)
    bank = regenerate_font_atlas(path)
    offset = original.width * 4
    assert bank.size == (offset * 2, original.height * 4)
    assert has_font_row_bank(bank)
    reference = bank.crop((0, 0, offset, bank.height))
    assert reference.tobytes() == _render_exact_raster_atlas(original, cells, recipe).tobytes()
    assert len(cells) == 181
    shifts = np.array([3, 2, 3], dtype=np.uint8)
    changed = 0
    for cell in cells:
        old = np.asarray(original.crop(cell.rect)) >> shifts
        left, top, right, bottom = (value * 4 for value in cell.rect)
        new = np.asarray(bank.crop((left + offset, top, right + offset, bottom))) >> shifts
        nearest = np.repeat(np.repeat(old, 4, axis=0), 4, axis=1)
        assert np.array_equal(
            new.reshape(old.shape[0], 4, old.shape[1], 4, 3).sum(axis=(1, 3)),
            old.astype(np.uint16) * 16,
        )
        assert np.array_equal(
            np.all(new == (21, 31, 6), axis=2), np.all(nearest == (21, 31, 6), axis=2)
        )
        changed += np.count_nonzero(new != nearest)
    assert changed > 0
    assert path.read_bytes() == original_bytes


@pytest.mark.parametrize(
    ("position", "color"),
    [
        ((0, 15), (172, 125, 49)),
        ((0, 1), (255, 0, 0)),
        ((0, 0), (0, 0, 0)),
        ((1, 0), (90, 76, 57)),
        ((3, 3), (200, 140, 70)),
        ((3, 3), (255, 255, 255)),
    ],
)
@pytest.mark.slow
def test_color_recipe_rejects_unverified_source(
    tmp_path: Path, position: tuple[int, int], color: tuple[int, int, int]
) -> None:
    make_sidney_color_source(tmp_path)
    path = tmp_path / "SID_NO_EMB_18.BMP"
    with path.open("rb") as stream, Image.open(stream) as original:
        image = original.copy()
    image.putpixel(position, color)
    image.save(path)
    with pytest.raises(ValueError, match="SID_NO_EMB_18"):
        regenerate_font_atlas(path)


def test_key_repair_falls_back_when_no_bounded_donor_exists() -> None:
    old = np.array([[[20, 31, 6]]], dtype=np.uint8)
    result = np.full((4, 4, 3), (21, 31, 6), dtype=np.uint8)
    _preserve_key_mask(result, old)
    assert np.all(result == old)


@pytest.mark.parametrize("fault", ["dimensions", "mapping"])
@pytest.mark.slow
def test_color_font_rejects_different_geometry(tmp_path: Path, fault: str) -> None:
    make_sidney_color_source(tmp_path)
    path = tmp_path / "SID_NO_EMB_18.BMP"
    with path.open("rb") as stream, Image.open(stream) as original:
        image = original.copy()
    if fault == "dimensions":
        image = image.crop((0, 0, 517, 115))
    else:
        image.putpixel((1, 0), (172, 125, 49))
    image.save(path)
    with pytest.raises(ValueError, match="SID_NO_EMB_18"):
        regenerate_font_atlas(path)


def test_solid_key_stays_key() -> None:
    source = np.full((4, 6, 3), (172, 125, 49), dtype=np.uint8)
    assert np.all((_reconstruct_glyph(source) >> np.array([3, 2, 3])) == (21, 31, 6))


@pytest.mark.slow
def test_small_font_symbols_use_their_own_ink_axis(tmp_path: Path) -> None:
    make_sidney_color_source(tmp_path, size=11)
    path = tmp_path / "SID_NO_EMB_11.BMP"
    with Image.open(path) as image:
        original = image.convert("RGB")
    recipe = font_atlas_recipe(path.name)
    assert recipe is not None
    bank = regenerate_font_atlas(path)
    for cell in parse_glyph_cells(original, recipe):
        if cell.character not in (0xA9, 0xAE):
            continue
        pixels = np.asarray(original.crop(cell.rect))
        expected = _reconstruct_glyph(pixels, ink=(0, 0, 0))
        assert not np.array_equal(expected, _reconstruct_glyph(pixels))
        left, top, right, bottom = (value * 4 for value in cell.rect)
        offset = original.width * 4
        assert np.array_equal(
            np.asarray(bank.crop((left + offset, top, right + offset, bottom))), expected
        )


@pytest.mark.parametrize("character", [ord("A"), 0xA9])
@pytest.mark.slow
def test_small_font_rejects_crossed_ink_palettes(tmp_path: Path, character: int) -> None:
    make_sidney_color_source(tmp_path, size=11)
    path = tmp_path / "SID_NO_EMB_11.BMP"
    with path.open("rb") as stream, Image.open(stream) as source:
        image = source.copy()
    recipe = font_atlas_recipe(path.name)
    assert recipe is not None
    cell = next(c for c in parse_glyph_cells(image, recipe) if c.character == character)
    wrong = (16, 16, 0) if character == ord("A") else (57, 60, 57)
    image.putpixel((cell.rect[0] + 1, cell.rect[1] + 1), wrong)
    image.save(path)
    with pytest.raises(ValueError, match="palette inside glyph"):
        regenerate_font_atlas(path)


@pytest.mark.parametrize("maximum", [31, 63, 255])
def test_channel_conservation(maximum: int) -> None:
    source = np.array([[0, maximum // 2, maximum]], dtype=np.uint8)
    proposal = np.linspace(-maximum, 2 * maximum, 48).reshape(4, 12)
    output = conserve_font_channel(source, proposal, maximum=maximum)
    assert np.array_equal(output.reshape(1, 4, 3, 4).sum(axis=(1, 3)), source.astype(int) * 16)


@pytest.mark.parametrize(
    ("maximum", "shape", "value"), [(7, (4, 4), 0), (31, (4, 5), 0), (31, (4, 4), np.nan)]
)
def test_channel_rejects_invalid_proposals(
    maximum: int, shape: tuple[int, int], value: float
) -> None:
    with pytest.raises(ValueError, match="font channel"):
        conserve_font_channel(
            np.zeros((1, 1), dtype=np.uint8), np.full(shape, value), maximum=maximum
        )
