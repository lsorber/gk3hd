"""Atlas-level contracts for source-guided reconstruction and paired storage."""

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
from gk3hd.textures.upscale.fonts.bank import FONT_ROW_BANK_LAYOUTS, has_font_row_bank
from gk3hd.textures.upscale.fonts.reconstruction import SOURCE_GLYPH_EXCEPTIONS
from tests.font_fixtures import make_sidney_pair

if TYPE_CHECKING:
    from pathlib import Path

_GRAY_FONTS = tuple(
    name
    for name in FONT_ROW_BANK_LAYOUTS
    if (recipe := font_atlas_recipe(name)) is not None
    and recipe.coverage_baseline is None
    # Repaired geometry and colored artwork have separate source contracts/tests.
    and name != "SID_CAP_16.BMP"
    and not name.startswith(("SID_NO_EMB_", "SID_EMB_"))
)


@pytest.mark.slow
def test_single_row_bank_closes_the_last_character_before_candidate_storage(tmp_path: Path) -> None:
    make_sidney_pair(tmp_path, include_medium=True)
    source = tmp_path / "RC_GOUDY12.BMP"
    output = regenerate_font_atlas(source)
    layout = FONT_ROW_BANK_LAYOUTS[source.name]
    with Image.open(source) as original:
        boundaries = [x for x in range(1, original.width) if original.getpixel((x, 0)) != (0, 0, 0)]
        # The retail parser appends bitmap width for every single-row atlas.
        # Explicitly close the last mapped slot; the remaining storage interval
        # has no character assigned to it (including the fallback byte).
        original_ends = [*boundaries, original.width]
    output_ends = [x for x in range(1, output.width) if output.getpixel((x, 0)) != (0, 0, 0)]
    assert output_ends == [x * 4 for x in original_ends]
    assert len(output_ends) == layout.glyph_count + 1
    assert output_ends[-1] == layout.bank_distance


@pytest.mark.slow
def test_goudy_reconstruction_uses_native_five_bit_blue_coverage(tmp_path: Path) -> None:
    make_sidney_pair(tmp_path, include_medium=True)
    source = tmp_path / "RC_GOUDY12.BMP"
    before = regenerate_font_atlas(source)
    with Image.open(source) as opened:
        changed = opened.copy()
    # Decoded RGB565 is not necessarily gray. Native AlphaBlend font tinting
    # indexes its gradient with blue's five bits, ignoring these other channels.
    changed.putpixel((2, 3), (16, 128, 248))
    changed.save(source)
    after = regenerate_font_atlas(source)
    stride = FONT_ROW_BANK_LAYOUTS[source.name].bank_distance
    alternate = (stride, 0, after.width, after.height)
    reference = (0, 0, stride, after.height)
    assert before.crop(alternate).tobytes() == after.crop(alternate).tobytes()
    assert before.crop(reference).tobytes() != after.crop(reference).tobytes()


@pytest.mark.parametrize("name", ["RC_GOUDY12.BMP", "SID_TEXT_14.BMP", "SID_TEXT_22.BMP"])
@pytest.mark.slow
def test_row_reconstruction_preserves_reference_markers_and_each_glyph(
    tmp_path: Path, name: str
) -> None:
    make_sidney_pair(tmp_path, include_medium=True, include_pulldown=True, include_tempus=True)
    source = tmp_path / name
    layout = FONT_ROW_BANK_LAYOUTS[name]
    recipe = font_atlas_recipe(source.name)
    assert recipe is not None
    with Image.open(source) as original:
        cells = parse_glyph_cells(original, recipe)
        reference = _render_exact_raster_atlas(original, cells, recipe)
        output = regenerate_font_atlas(source)
        stride = layout.bank_distance
        assert has_font_row_bank(output)
        assert output.size == layout.image_size
        assert output.crop((0, 0, stride, output.height)).tobytes() == reference.tobytes()
        for cell in cells:
            left, top, right, bottom = (v * 4 for v in cell.rect)
            candidate = output.crop((stride + left, top, stride + right, bottom))
            if cell.character == 0x9D or cell.character in SOURCE_GLYPH_EXCEPTIONS.get(
                name, frozenset()
            ):
                assert candidate.tobytes() == reference.crop((left, top, right, bottom)).tobytes()
            else:
                old = np.asarray(original.crop(cell.rect))[:, :, 2] >> 3
                new = np.asarray(candidate)[:, :, 2] >> 3
                sums = new.reshape(old.shape[0], 4, old.shape[1], 4).sum(axis=(1, 3))
                np.testing.assert_array_equal(sums, old.astype(np.int16) * 16)
        for row in range(layout.line_count):
            top = row * (layout.source_size[1] // layout.line_count) * 4
            start = stride
            if recipe.implicit_right_edge:
                expected_marker = (255, 255, 255) if name == "F_ARIAL_A12.BMP" else (255, 0, 0)
                assert output.getpixel((stride, top)) == expected_marker
                start += 1
            assert output.crop((start, top, output.width, top + 1)).getbbox() is None


@pytest.mark.parametrize("member", _GRAY_FONTS)
@pytest.mark.parametrize("fault", ["size", "baseline", "mapping"])
@pytest.mark.slow
def test_unverified_source_layout_is_rejected(tmp_path: Path, member: str, fault: str) -> None:
    make_sidney_pair(tmp_path, include_medium=True, include_pulldown=True, include_tempus=True)
    path = tmp_path / member
    with Image.open(path) as opened:
        image = opened.copy()
    if fault == "size":
        image = image.crop((0, 0, image.width - 1, image.height))
    elif fault == "baseline":
        image.putpixel((0, 3), (255, 0, 0))
    else:
        image.putpixel((1, 0), (0, 0, 0))
    image.save(path)
    with pytest.raises(ValueError, match=r"verified font recipe|marker table has"):
        regenerate_font_atlas(path)
    if member == "SID_TEXT_22.BMP":
        with pytest.raises(ValueError, match=r"verified font recipe|marker table has"):
            regenerate_font_atlas(tmp_path / "SID_TEXT_14.BMP")


@pytest.mark.parametrize(
    "member",
    [
        "SID_TEXT_22.BMP",
    ],
)
@pytest.mark.slow
def test_larger_recipe_uses_own_source_and_resume_rechecks_it(tmp_path: Path, member: str) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    make_sidney_pair(source, include_medium=True, include_pulldown=True, include_tempus=True)
    # Neither the smaller font nor its direction-guide companion is required.
    for other in set(_GRAY_FONTS) - {member}:
        (source / other).unlink()
    assert texture_upscale.upscale(source, output).created == 1
    path = source / member
    destination = output / f"{path.stem}.PNG"
    before = destination.read_bytes()
    with Image.open(path) as opened:
        changed = opened.copy()
    changed.putpixel((1, 5), (120, 120, 120))
    changed.save(path)
    assert texture_upscale.upscale(source, output).created == 1
    assert destination.read_bytes() != before


@pytest.mark.slow
def test_hint_required_but_not_renamed_or_written(tmp_path: Path) -> None:
    make_sidney_pair(tmp_path)
    hint = tmp_path / "SID_TEXT_22.BMP"
    before = hint.read_bytes()
    lower = tmp_path / "sid_text_22.bmp"
    # A temporary different basename makes this case-only rename work on Windows too.
    intermediate = tmp_path / "rename.bmp"
    hint.rename(intermediate)
    intermediate.rename(lower)
    regenerate_font_atlas(tmp_path / "SID_TEXT_14.BMP")
    assert lower.read_bytes() == before
    lower.unlink()
    with pytest.raises(ValueError, match=r"requires original companion: SID_TEXT_22\.BMP"):
        regenerate_font_atlas(tmp_path / "SID_TEXT_14.BMP")


@pytest.mark.slow
def test_resume_rechecks_both_originals_and_refreshes_corrupt_bank(tmp_path: Path) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    make_sidney_pair(source)
    assert texture_upscale.upscale(source, output).created == 2
    destination = output / "SID_TEXT_14.PNG"
    previous = destination.read_bytes()
    hint = source / "SID_TEXT_22.BMP"
    with Image.open(hint) as opened:
        changed = opened.copy()
    # Remove the sibling edge field, without changing any parser markers.
    for row in range(4):
        changed.paste((0, 0, 0), (1, row * 25 + 1, changed.width, (row + 1) * 25))
    changed.save(hint)
    assert texture_upscale.upscale(source, output).created == 2
    assert destination.read_bytes() != previous
    with Image.open(destination) as opened:
        broken = opened.copy()
    broken.putpixel((2069, 2), (17, 19, 23))
    broken.save(destination)
    assert texture_upscale.upscale(source, output).created == 1
