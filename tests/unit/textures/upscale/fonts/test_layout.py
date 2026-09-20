"""The reviewed Times italic repair preserves cells, metrics and keyed coverage."""

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
from gk3hd.textures.upscale.fonts.layout import TIMES_ITALIC, repair_times_italic_layout
from tests.font_fixtures import make_times_italic_pair

if TYPE_CHECKING:
    from pathlib import Path

_ALPHA = "F_TIMES_R_I_12A.BMP"


def test_repair_preserves_every_authored_cell_and_inserts_original_space(tmp_path: Path) -> None:
    make_times_italic_pair(tmp_path)
    recipe = font_atlas_recipe(TIMES_ITALIC)
    assert recipe is not None
    original_bytes = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with Image.open(tmp_path / TIMES_ITALIC) as c, Image.open(tmp_path / _ALPHA) as a:
        color, alpha = c.convert("RGB"), a.convert("L")
    repaired, opacity = repair_times_italic_layout(color, alpha, recipe)
    cells = parse_glyph_cells(repaired, recipe)
    assert len(cells) == 181
    assert bytes(cell.character for cell in cells) == recipe.characters
    # Independently derive the synthetic fixture's original artwork positions.
    originals = {}
    left = 1
    for index, character in enumerate(recipe.characters.replace(b"\x9d", b"")):
        within_row = index % 60
        if within_row == 0:
            left = 1
        width = 4 if character == 0x20 else 6 + within_row % 4
        top = index // 60 * 16 + 1
        originals[character] = (left, top, left + width, top + 15)
        left += width
    for cell in cells:
        old = originals[0x20 if cell.character == 0x9D else cell.character]
        left, top, right, bottom = cell.rect
        assert (right - left, bottom - top) == (old[2] - old[0], 16)
        new_art = (left, top, right, bottom - 1)
        assert repaired.crop(new_art).tobytes() == color.crop(old).tobytes()
        assert opacity.crop(new_art).tobytes() == alpha.crop(old).tobytes()
        assert set(repaired.crop((left, bottom - 1, right, bottom)).get_flattened_data()) == {
            (255, 0, 255)
        }
        assert not opacity.crop((left, bottom - 1, right, bottom)).getbbox()
    assert repaired.size == color.size == (491, 51)
    assert [y for y in range(51) if repaired.getpixel((0, y)) != (255, 0, 255)] == [1, 12]
    assert original_bytes == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


@pytest.mark.parametrize("name", [TIMES_ITALIC, _ALPHA])
@pytest.mark.slow
def test_banks_keep_raw_reference_but_reconstruct_only_visible_ink(
    tmp_path: Path, name: str
) -> None:
    make_times_italic_pair(tmp_path)
    recipe = font_atlas_recipe(name)
    assert recipe is not None
    with Image.open(tmp_path / TIMES_ITALIC) as c, Image.open(tmp_path / _ALPHA) as a:
        color, alpha = repair_times_italic_layout(c.convert("RGB"), a.convert("L"), recipe)
    cells = parse_glyph_cells(color, recipe)
    reference = _render_exact_raster_atlas(alpha if recipe.alpha else color, cells, recipe)
    result = regenerate_font_atlas(tmp_path / name)
    stride = color.width * 4
    assert result.size == (3928, 204)
    assert result.crop((0, 0, stride, result.height)).tobytes() == reference.tobytes()
    changed, hidden = 0, 0
    for cell in cells:
        left, top, right, bottom = (v * 4 for v in cell.rect)
        candidate = result.crop((stride + left, top, stride + right, bottom))
        source = reference.crop((left, top, right, bottom))
        if not recipe.alpha or cell.character == 0x9D:
            assert candidate.tobytes() == source.tobytes()
            continue
        before = np.asarray(alpha.crop(cell.rect))
        hidden += int(np.count_nonzero((before > 0) & (before <= 48)))
        expected = np.where(before > 48, before, 0).astype(np.int16) * 16
        summed = (
            np.asarray(candidate).reshape(before.shape[0], 4, before.shape[1], 4).sum(axis=(1, 3))
        )
        np.testing.assert_array_equal(summed, expected)
        changed += candidate.tobytes() != source.tobytes()
    if recipe.alpha:
        assert changed > 0
        assert hidden > 0


@pytest.mark.parametrize("name", [TIMES_ITALIC, _ALPHA])
@pytest.mark.parametrize("fault", ["width", "baseline", "row", "missing-cell", "tint", "mask"])
@pytest.mark.slow
def test_repair_rejects_unverified_inputs(tmp_path: Path, name: str, fault: str) -> None:
    make_times_italic_pair(tmp_path)
    with Image.open(tmp_path / TIMES_ITALIC) as source:
        color = source.copy()
    if fault == "width":
        color = color.crop((0, 0, 490, 51))
    else:
        location, value = {
            "baseline": ((0, 12), (255, 0, 255)),
            "row": ((1, 16), (255, 0, 255)),
            "missing-cell": ((7, 0), (255, 0, 255)),
            "tint": ((1, 2), (123, 123, 123)),
            # White zero-opacity samples are valid. Keying away visible positive
            # opacity, rather than adding invisible white, is a real mask error.
            "mask": ((5, 4), (255, 0, 255)),
        }[fault]
        if fault == "mask":
            assert color.getpixel(location) == (255, 255, 255)
            with Image.open(tmp_path / _ALPHA) as opacity:
                assert opacity.getpixel(location) == 57
        color.putpixel(location, value)
    color.save(tmp_path / TIMES_ITALIC)
    with pytest.raises(
        ValueError, match=r"dimensions|verified font layout|row markers|glyph cells|masks disagree"
    ):
        regenerate_font_atlas(tmp_path / name)


@pytest.mark.slow
def test_resume_rechecks_repaired_source_pixels(tmp_path: Path) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    make_times_italic_pair(source)
    assert texture_upscale.upscale(source, output).created == 2
    before = {path.name: path.read_bytes() for path in output.glob("*.PNG")}
    for name, value in ((TIMES_ITALIC, (255, 255, 255)), (_ALPHA, 200)):
        with (source / name).open("rb") as stream, Image.open(stream) as original:
            changed = original.copy()
        changed.putpixel((1, 2), value)
        changed.save(source / name)
    # A same-sized, previously completed bank is not automatically resumable.
    assert texture_upscale.upscale(source, output).created == 2
    after = {path.name: path.read_bytes() for path in output.glob("*.PNG")}
    assert before.keys() == after.keys()
    assert all(before[name] != after[name] for name in before)
