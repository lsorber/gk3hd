"""Caption repair restores two lost slots without changing authored glyphs."""

from __future__ import annotations

from dataclasses import replace
from itertools import pairwise
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
from gk3hd.textures.upscale.fonts.bank import has_font_row_bank
from gk3hd.textures.upscale.fonts.layout import CAPTION_16, repair_caption_layout
from tests.font_fixtures import make_caption_source

if TYPE_CHECKING:
    from pathlib import Path


def test_repair_preserves_every_sample_and_restores_both_leading_cells(tmp_path: Path) -> None:
    make_caption_source(tmp_path)
    path = tmp_path / CAPTION_16
    before = path.read_bytes()
    recipe = font_atlas_recipe(CAPTION_16)
    assert recipe is not None
    with Image.open(path) as opened:
        original = opened.convert("RGB")
    repaired = repair_caption_layout(original, recipe)
    cells = parse_glyph_cells(repaired, recipe)
    original_cells = []
    for top in (0, 21, 42, 63):
        boundaries = [x for x in range(426) if original.getpixel((x, top)) == (255, 0, 0)]
        original_cells.extend((a, top + 1, b, top + 21) for a, b in pairwise(boundaries))
    assert len(cells) == len(original_cells) == 181
    assert bytes(c.character for c in cells) == recipe.characters
    assert cells[92].character == ord("?")
    assert cells[138].character == 0xD5
    for cell, rect in zip(cells, original_cells, strict=True):
        assert repaired.crop(cell.rect).tobytes() == original.crop(rect).tobytes()
        assert cell.rect[2] - cell.rect[0] == rect[2] - rect[0]
    assert original.crop((0, 0, 426, 42)).tobytes() == repaired.crop((0, 0, 426, 42)).tobytes()
    assert [y for y in range(84) if repaired.getpixel((0, y)) != (0, 0, 0)] == [16]
    assert path.read_bytes() == before
    assert repaired.size == original.size == (426, 84)


@pytest.mark.slow
def test_repaired_reference_bank_and_each_pixel_coverage_are_preserved(tmp_path: Path) -> None:
    make_caption_source(tmp_path)
    recipe = font_atlas_recipe(CAPTION_16)
    assert recipe is not None
    with Image.open(tmp_path / CAPTION_16) as opened:
        original = repair_caption_layout(opened.convert("RGB"), recipe)
    cells = parse_glyph_cells(original, recipe)
    reference = _render_exact_raster_atlas(original, cells, recipe)
    output = regenerate_font_atlas(tmp_path / CAPTION_16)
    assert output.size == (3408, 336)
    assert has_font_row_bank(output)
    assert output.crop((0, 0, 1704, 336)).tobytes() == reference.tobytes()
    changed = 0
    for cell in cells:
        left, top, right, bottom = (v * 4 for v in cell.rect)
        candidate = output.crop((1704 + left, top, 1704 + right, bottom))
        if cell.character == 0x9D:
            assert candidate.tobytes() == reference.crop((left, top, right, bottom)).tobytes()
            continue
        before = np.asarray(original.crop(cell.rect))[:, :, 2] >> 3
        after = np.asarray(candidate)[:, :, 2] >> 3
        sums = after.reshape(before.shape[0], 4, before.shape[1], 4).sum(axis=(1, 3))
        np.testing.assert_array_equal(sums, before.astype(np.int16) * 16)
        changed += candidate.tobytes() != reference.crop((left, top, right, bottom)).tobytes()
    assert changed > 0


@pytest.mark.parametrize(
    "fault", ["size", "mode", "baseline", "missing", "extra", "tint", "edge", "repaired"]
)
def test_repair_rejects_unverified_layouts(tmp_path: Path, fault: str) -> None:
    make_caption_source(tmp_path)
    recipe = font_atlas_recipe(CAPTION_16)
    assert recipe is not None
    with Image.open(tmp_path / CAPTION_16) as opened:
        color = opened.convert("RGB")
    if fault == "size":
        color = color.crop((0, 0, 425, 84))
    elif fault == "mode":
        color = color.convert("L")
    elif fault == "repaired":
        color = repair_caption_layout(color, recipe)
    else:
        point, value = {
            "baseline": ((0, 16), (0, 0, 0)),
            "missing": ((0, 42), (0, 0, 0)),
            "extra": ((2, 0), (255, 0, 0)),
            "tint": ((0, 63), (0, 0, 255)),
            "edge": ((425, 43), (120, 120, 120)),
        }[fault]
        color.putpixel(point, value)
    with pytest.raises(ValueError, match=r"verified caption layout|row markers|discard artwork"):
        repair_caption_layout(color, recipe)


@pytest.mark.parametrize("fault", ["name", "rows", "characters"])
def test_repair_rejects_other_recipes(tmp_path: Path, fault: str) -> None:
    make_caption_source(tmp_path)
    recipe = font_atlas_recipe(CAPTION_16)
    assert recipe is not None
    if fault == "name":
        recipe = replace(recipe, primary="SID_CAP_20.BMP")
    elif fault == "rows":
        recipe = replace(recipe, line_count=3)
    else:
        recipe = replace(recipe, characters=recipe.characters[:-1])
    with (
        Image.open(tmp_path / CAPTION_16) as opened,
        pytest.raises(ValueError, match="verified caption layout"),
    ):
        repair_caption_layout(opened.convert("RGB"), recipe)


@pytest.mark.slow
def test_resume_rechecks_source_ink_in_the_reserved_column(tmp_path: Path) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    make_caption_source(source)
    assert texture_upscale.upscale(source, output).created == 1
    before = (output / "SID_CAP_16.PNG").read_bytes()
    path = source / CAPTION_16
    with path.open("rb") as stream, Image.open(stream) as opened:
        changed = opened.copy()
    changed.putpixel((0, 44), (80, 80, 80))
    changed.save(path)
    assert texture_upscale.upscale(source, output).created == 1
    assert (output / "SID_CAP_16.PNG").read_bytes() != before
