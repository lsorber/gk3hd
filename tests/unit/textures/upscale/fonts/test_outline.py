"""Outline fidelity gates use synthetic rasters, never redistributed font files."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.upscale import service
from gk3hd.textures.upscale.fonts.atlas import FONT_OUTLINE_STAMP, GlyphCell
from gk3hd.textures.upscale.fonts.bank import font_bank_layout, read_font_bank_flags

if TYPE_CHECKING:
    from pathlib import Path

    from numpy.typing import NDArray

outline = pytest.importorskip("gk3hd.textures.upscale.fonts.outline", exc_type=ImportError)


def test_near_match_measures_ink_not_blank_cell_area() -> None:
    target = np.zeros((100, 100), dtype=np.bool_)
    target[10:15, 10:15] = True
    candidate = target.copy()
    candidate[12, 12] = False
    assert outline._small_raster_difference(candidate, target)
    candidate[12, 11:14] = False
    assert not outline._small_raster_difference(candidate, target)
    tiny = np.zeros_like(target)
    tiny[10:12, 10:12] = True
    changed = tiny.copy()
    changed[10, 10] = False
    assert not outline._small_raster_difference(changed, tiny)


def test_near_match_rejects_changed_extents_and_empty_glyphs() -> None:
    target = np.ones((10, 10), dtype=np.bool_)
    candidate = target.copy()
    candidate[0] = False
    assert not outline._small_raster_difference(candidate, target)
    assert not outline._small_raster_difference(np.zeros_like(target), target)


def test_near_match_is_not_written_into_reference_header(monkeypatch: pytest.MonkeyPatch) -> None:
    key = np.array([255, 0, 255], dtype=np.uint8)
    pixels = np.full((5, 5, 3), 255, dtype=np.uint8)
    native = np.ones((5, 5), dtype=np.bool_)
    native[2, 2] = False
    monkeypatch.setattr(outline, "_raster", lambda *_args, **_kwargs: (native, 0, 5))
    image, reason = outline._reconstruct_glyph(object(), 65, pixels, key, 5)
    assert image is None
    assert reason == "native-raster-near-match"


@pytest.mark.parametrize("origin", [(-1, 0), (0, -1), (2, 0), (0, 2), (9, 9)])
def test_outside_ink_is_counted_not_silently_clipped(origin: tuple[int, int]) -> None:
    pixels = np.ones((2, 2), dtype=np.bool_)
    placed, outside = outline._place(pixels, (3, 3), origin)
    assert outside > 0
    assert int(placed.sum()) + outside == 4


@pytest.mark.parametrize(
    ("fault", "reason"),
    [
        ("none", "verified-outline"),
        ("native", "native-raster-mismatch"),
        ("outside", "contour-outside-cell"),
        ("sample", "reference-sampling-mismatch"),
        ("empty", "missing-font-glyph"),
    ],
)
@pytest.mark.parametrize("character", [65, 0xA1, 0xC9, 0xFE, 0xFF])
def test_glyph_gates(
    monkeypatch: pytest.MonkeyPatch, fault: str, reason: str, character: int
) -> None:
    key = np.array([248, 0, 248], dtype=np.uint8)
    pixels = np.tile(key, (3, 3, 1))
    pixels[1, 1] = [96, 112, 128]

    def raster(_face: object, _character: int, *, scale: int) -> tuple[NDArray[np.bool_], int, int]:
        if scale == 1:
            native = np.ones((1, 2 if fault == "native" else 1), dtype=np.bool_)
            if fault == "empty":
                native[:] = False
            return native, 0, 1
        dense = np.ones((4, 20 if fault == "outside" else 4), dtype=np.bool_)
        if fault == "sample":
            dense[2, 2] = False
        return dense, 0, 4

    monkeypatch.setattr(outline, "_raster", raster)
    image, actual = outline._reconstruct_glyph(object(), character, pixels, key, 2)
    assert actual == reason
    assert (image is not None) == (fault == "none")
    if image is not None:
        assert np.array_equal(np.asarray(image)[2::4, 2::4], pixels)


@pytest.mark.parametrize("character", [0, 32, 127, 128, 0x9D, 0xA0, 256])
def test_special_cells_never_request_a_font_glyph(character: int) -> None:
    key = np.array([248, 0, 248], dtype=np.uint8)
    assert outline._reconstruct_glyph(object(), character, np.tile(key, (3, 3, 1)), key, 2) == (
        None,
        "authored-space-or-symbol",
    )


@pytest.mark.parametrize("character", [0xC9, 0xFF])
def test_unmapped_character_does_not_render_the_notdef_box(character: int) -> None:
    class UnmappedFace:
        @staticmethod
        def get_char_index(requested: int) -> int:
            assert requested == character
            return 0

    # This deliberately has no load_char: an absent cmap entry must stop here.
    pixels, left, top = outline._raster(outline._GlyphFace(UnmappedFace()), character, scale=1)
    assert pixels.size == 0
    assert (left, top) == (0, 0)


@pytest.mark.parametrize("scale", [1, 4])
def test_synthetic_bold_preserves_height_and_expands_rightward(scale: int) -> None:
    pixels = np.zeros((5, 6), dtype=np.bool_)
    pixels[1, 2] = pixels[3, 0] = True
    expected = np.zeros((5, 6 + scale), dtype=np.bool_)
    expected[1, 2 : 3 + scale] = True
    expected[3, : 1 + scale] = True
    actual = outline._horizontal_bold(pixels, scale=scale)
    assert np.array_equal(actual, expected)
    assert pixels.sum() == 2  # The unbolded glyph is not modified.


@pytest.mark.parametrize("character", [32, 65, 126, 127, 0x9D, 0xD8, 0xDA, 255])
def test_extended_mapping_is_specific_to_the_descriptor(character: int) -> None:
    for name in ("F_SSERIF_T8.BMP", "F_SSERIF_T8B.BMP", "F_ARIAL_T8.BMP"):
        assert outline._RECIPES[name].supports_character(character) == (33 <= character < 127)
    assert outline._RECIPES["F_TOOLTIP.BMP"].supports_character(character) == (
        33 <= character < 127 or 161 <= character < 256
    )


@pytest.mark.parametrize("scale", [1, 4])
@pytest.mark.parametrize("offset", [-1, 1])
@pytest.mark.parametrize("character", [42, 65])
def test_authored_vertical_bearing_moves_without_changing_raster(
    scale: int, offset: int, character: int
) -> None:
    bitmap = SimpleNamespace(buffer=[0xA0], rows=1, pitch=1, width=3)
    glyph = SimpleNamespace(bitmap=bitmap, bitmap_left=2, bitmap_top=9, render=lambda _mode: None)
    font = SimpleNamespace(
        glyph=glyph,
        get_char_index=lambda _character: 1,
        set_transform=lambda _matrix, _vector: None,
        load_char=lambda _character, _flags: None,
    )
    shifted = outline._GlyphFace(font, vertical_offsets=((42, offset),))
    pixels, left, top = outline._raster(shifted, character, scale=scale)
    assert pixels.tolist() == [[True, False, True]]
    assert left == 2
    assert top == 9 - (offset * scale if character == 42 else 0)


def test_authored_bearings_are_limited_to_verified_atlas_glyphs() -> None:
    offsets = {
        "F_SSERIF_T8.BMP": ((42, 1),),
        "F_SSERIF_T8B.BMP": ((42, 1),),
        "F_TOOLTIP.BMP": ((94, -1),),
    }
    for name, recipe in outline._RECIPES.items():
        assert recipe.vertical_offsets == offsets.get(name, ())


@pytest.mark.parametrize("scale", [1, 4])
@pytest.mark.parametrize("offset", [(-1, 0), (2, -3)])
def test_component_contours_keep_their_shape_scale_and_bearings(
    monkeypatch: pytest.MonkeyPatch, scale: int, offset: tuple[int, int]
) -> None:
    base = np.array([[True, False], [True, True]], dtype=np.bool_)
    accent = np.array([[False, True, False], [True, False, True]], dtype=np.bool_)

    def raster(_face: object, character: int, *, scale: int) -> tuple[NDArray[np.bool_], int, int]:
        mask = base if character == 65 else accent
        return mask.repeat(scale, 0).repeat(scale, 1), -scale, 2 * scale

    monkeypatch.setattr(outline, "_raster", raster)
    composition = outline._GlyphComposition(0xC2, 65, 0x02C6, offset)
    pixels, left, top = outline._compose_raster(object(), composition, scale=scale)
    expected = np.zeros((40, 40), dtype=np.bool_)
    for mask, dx, dy in ((base, 0, 0), (accent, *offset)):
        dense = mask.repeat(scale, 0).repeat(scale, 1)
        x, y = 12 + (dx - 1) * scale, 20 + (dy - 2) * scale
        expected[y : y + dense.shape[0], x : x + dense.shape[1]] |= dense
    actual = np.zeros_like(expected)
    actual[20 - top : 20 - top + pixels.shape[0], 12 + left : 12 + left + pixels.shape[1]] = pixels
    assert np.array_equal(actual, expected)


@pytest.mark.parametrize("missing", [65, 0x02C6])
def test_composition_requires_both_real_font_components(
    monkeypatch: pytest.MonkeyPatch, missing: int
) -> None:
    def raster(_face: object, character: int, *, scale: int) -> tuple[NDArray[np.bool_], int, int]:
        return np.full((scale, scale), character != missing, dtype=np.bool_), 0, scale

    monkeypatch.setattr(outline, "_raster", raster)
    pixels, _left, _top = outline._compose_raster(
        object(), outline._GlyphComposition(0xC2, 65, 0x02C6, (0, 0)), scale=4
    )
    assert not pixels.size


def test_compositions_are_only_the_verified_tooltip_circumflex_group() -> None:
    for name, recipe in outline._RECIPES.items():
        if name != "F_TOOLTIP.BMP":
            assert not recipe.compositions
            continue
        assert {item.character for item in recipe.compositions} == {0xD4, 0xE2, 0xEA, 0xEE, 0xF4}
        assert all(item.accent == 0x02C6 for item in recipe.compositions)


@pytest.mark.parametrize("ink_count", [0, 2])
def test_empty_or_processed_artwork_is_preserved(ink_count: int) -> None:
    key = np.array([248, 0, 248], dtype=np.uint8)
    pixels = np.tile(key, (3, 3, 1))
    for index in range(ink_count):
        pixels[index, index] = [index, 0, 0]
    assert outline._reconstruct_glyph(object(), 65, pixels, key, 2) == (
        None,
        "nonuniform-or-empty-artwork",
    )


def test_baseline_must_be_unambiguous() -> None:
    image = Image.new("RGB", (4, 7), "white")
    with pytest.raises(ValueError, match="exactly one"):
        outline._baseline(image)
    image.putpixel((0, 4), (0, 0, 0))
    assert outline._baseline(image) == 4
    image.putpixel((0, 5), (0, 0, 0))
    with pytest.raises(ValueError, match="exactly one"):
        outline._baseline(image)


def test_font_directory_matches_bytes_not_filenames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    font_bytes = b"synthetic fixture, not a font"
    digest = hashlib.sha256(font_bytes).hexdigest()
    monkeypatch.setattr(outline, "_RECIPES", {"TEST.BMP": outline._OutlineRecipe(digest, 11)})
    (tmp_path / "renamed.TTF").write_bytes(font_bytes)
    (tmp_path / "Arial.ttf").write_bytes(b"wrong bytes")
    assert outline.supplied_font_files(tmp_path) == {digest: font_bytes}
    assert outline.outline_font_digest("test.bmp") == digest
    assert outline.outline_font_digest("unknown.bmp") is None


def test_missing_or_unsupported_fonts_fail_explicitly(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        outline.supplied_font_files(tmp_path / "missing")
    with pytest.raises(ValueError, match="no verified font"):
        outline.supplied_font_files(tmp_path)
    with pytest.raises(ValueError, match="verified face"):
        outline.regenerate_outline_atlas(tmp_path / "F_ARIAL_T8.BMP", b"wrong font")
    with pytest.raises(ValueError, match="no verified outline recipe"):
        outline.regenerate_outline_atlas(tmp_path / "UNKNOWN.BMP", b"wrong font")


def test_outline_resume_checks_provenance_and_pixels(tmp_path: Path) -> None:
    image = Image.new("RGB", (12, 12), "white")
    image.info[FONT_OUTLINE_STAMP] = "verified fixture"
    atlas = outline.OutlineAtlas(image, (outline.OutlineGlyph(65, "verified-outline"),))
    output = tmp_path / "atlas.PNG"
    service._write_png_atomic(image, output)
    assert service._is_matching_font_outline(output, atlas)
    changed = image.copy()
    changed.putpixel((2, 2), (0, 0, 0))
    service._write_png_atomic(changed, output)
    assert not service._is_matching_font_outline(output, atlas)
    changed = image.copy()
    changed.info[FONT_OUTLINE_STAMP] = "different font"
    service._write_png_atomic(changed, output)
    assert not service._is_matching_font_outline(output, atlas)
    output.write_bytes(b"broken")
    with pytest.raises(ValueError, match="use --overwrite"):
        service._is_matching_font_outline(output, atlas)


def test_no_font_input_does_not_load_fonts() -> None:
    assert service._prepare_font_outlines([], [], None) == {}


def test_font_input_without_matching_sources_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(outline, "supplied_font_files", lambda _path: {"digest": b"bytes"})
    with pytest.raises(ValueError, match="do not match any supported atlas"):
        service._prepare_font_outlines([], [], tmp_path)


@pytest.mark.parametrize("fault", ["none", "outside", "sample"])
def test_outline_bank_keeps_full_ink_without_requiring_native_sampling(
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    key = np.array([248, 0, 248], dtype=np.uint8)
    pixels = np.tile(key, (3, 3, 1))
    pixels[1, 1] = [96, 112, 128]

    def raster(_face: object, _character: int, *, scale: int) -> tuple[NDArray[np.bool_], int, int]:
        if scale == 1:
            return np.ones((1, 1), dtype=np.bool_), 0, 1
        dense = np.zeros((4, 9), dtype=np.bool_)
        dense[:, 0] = True  # An overhang between reference sample positions.
        dense[:, 5:] = True
        if fault == "sample":
            dense[2, 7] = False
        return dense, -9 if fault == "outside" else -5, 4

    monkeypatch.setattr(outline, "_raster", raster)
    result = outline._padded_glyph(object(), 65, pixels, key, 2)
    assert (result is not None) == (fault != "outside")
    if result is not None:
        expected = np.pad(np.any(pixels != key, axis=2), 1)
        assert np.array_equal(np.any(np.asarray(result)[2::4, 2::4] != key, axis=2), expected) == (
            fault == "none"
        )


def test_paired_banks_keep_source_pixels_separate_from_outline_artwork(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = font_bank_layout("F_ARIAL_T8.BMP")
    assert layout is not None
    key = (248, 0, 248)
    original = Image.new("RGB", layout.source_size, key)
    original.putpixel((0, 1), (248, 252, 248))
    for y in range(2, original.height):
        original.putpixel((0, y), (0, 0, 0))
    original.putpixel((0, 7), key)
    original.putpixel((2, 5), (96, 112, 128))
    cell = GlyphCell(65, (1, 1, 5, 11))
    monkeypatch.setattr(outline, "parse_glyph_cells", lambda _image, _recipe: (cell,) * 94)
    contour = Image.new("RGB", (24, 48), key)
    contour.putpixel((5, 5), (96, 112, 128))
    monkeypatch.setattr(outline, "_padded_glyph", lambda *_args: contour)
    # A different header proves that reference-bank pixels come from the
    # original artwork, never from the already reconstructed header.
    header = original.resize((2160, 44), Image.Resampling.NEAREST)
    header.putpixel((0, 1), (248, 252, 248))
    header.putpixel((8, 20), (0, 0, 0))
    decisions = [outline.OutlineGlyph(65, "reference-sampling-mismatch")] * 94
    decisions[0] = outline.OutlineGlyph(65, "native-raster-mismatch")
    image, updated = outline._extend_glyph_bank(
        original, header, object(), "F_ARIAL_T8.BMP", decisions
    )
    assert read_font_bank_flags(image, layout) == (False,) + (True,) * 93
    expected = Image.new("RGB", (24, 48), key)
    expected.paste(original.crop(cell.rect).resize((16, 40), Image.Resampling.NEAREST), (4, 4))
    for index in range(94):
        left, top, right, bottom = layout.glyph_rect(index, 4)
        raster_box = (left * 4, top * 4, right * 4, bottom * 4)
        outline_box = tuple(
            v + (layout.bank_distance if i % 2 else 0) for i, v in enumerate(raster_box)
        )
        assert image.crop(raster_box).tobytes() == expected.tobytes()
        assert image.crop(outline_box).tobytes() == (contour if index else expected).tobytes()
        assert updated[index].outlined == bool(index)
