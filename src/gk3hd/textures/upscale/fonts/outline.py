"""Opt-in, glyph-gated outline reconstruction from explicitly supplied fonts.

These are partial outline recipes, not whole-font identification. A glyph changes
only if its native raster agrees within the small measured tolerance below and
its full contour fits the independent enlarged bank.
Paired banks preserve original raster samples for reference-size draws. Failed
and unrecognized glyphs retain original pixel artwork.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Final

import freetype as ft
import numpy as np
from freetype.ft_enums.ft_load_flags import FT_LOAD_FLAGS
from freetype.ft_enums.ft_load_targets import FT_LOAD_TARGETS
from freetype.ft_enums.ft_render_modes import FT_RENDER_MODES
from PIL import Image

from gk3hd.textures.upscale.fonts.atlas import (
    FONT_ATLAS_COLOR_SIZES,
    FONT_OUTLINE_STAMP,
    SCALE,
    font_atlas_recipe,
    parse_glyph_cells,
    regenerate_font_atlas,
)
from gk3hd.textures.upscale.fonts.bank import font_bank_layout, write_font_bank_flags

if TYPE_CHECKING:
    from pathlib import Path

    from numpy.typing import NDArray

_RENDERER_VERSION: Final = (2, 13, 2)
_REGULAR: Final = "35c0f3559d8db569e36c31095b8a60d441643d95f59139de40e23fada819b833"
_BOLD: Final = "4044aa6b5bebbc36980206b45b0aaaaa5681552a48bcadb41746d5d1d71fd7b4"
_SANS_SERIF: Final = "89b42a12ea0379133fb2f4a1d1bd53058fb61e2343c1d509452d5761acc85b7a"
# Compare ink, not the mostly empty cell: a large margin cannot hide a bad face.
# Both limits must pass; the original raster is still used at reference size.
_MAX_NATIVE_MISMATCH_FRACTION: Final = 0.10
_MAX_NATIVE_MISMATCH_PIXELS: Final = 2


@dataclass(frozen=True, slots=True)
class _GlyphComposition:
    """Independently hinted, unwarped components at verified native offsets."""

    character: int
    base: int
    accent: int
    offset: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _OutlineRecipe:
    font_sha256: str
    pixel_size: int
    synthetic_bold: bool = False
    extended: bool = False
    vertical_offsets: tuple[tuple[int, int], ...] = ()
    compositions: tuple[_GlyphComposition, ...] = ()

    def supports_character(self, character: int) -> bool:
        return _PRINTABLE_START <= character < _PRINTABLE_END or (
            self.extended and _EXTENDED_START <= character < _EXTENDED_END
        )


@dataclass(frozen=True, slots=True)
class _GlyphFace:
    font: ft.Face
    synthetic_bold: bool = False
    vertical_offsets: tuple[tuple[int, int], ...] = ()
    compositions: tuple[_GlyphComposition, ...] = ()


_RECIPES: Final = {
    "F_ARIAL_T8.BMP": _OutlineRecipe(_REGULAR, 11),
    "F_ARIAL_T10.BMP": _OutlineRecipe(_REGULAR, 13),
    "F_ARIAL_T12.BMP": _OutlineRecipe(_BOLD, 16),
    # The authored caret uses the matching glyph one native pixel above the
    # font's default bearing; move its whole outline, never reshape the accent.
    "F_TOOLTIP.BMP": _OutlineRecipe(
        _REGULAR,
        13,
        extended=True,
        vertical_offsets=((94, -1),),
        # The authored composites match independently hinted bases/circumflex,
        # not the font's jointly hinted accented glyphs. No component is scaled
        # or deformed separately; complete native identity is still required.
        compositions=(
            _GlyphComposition(0xD4, ord("O"), 0x02C6, (2, -3)),
            _GlyphComposition(0xE2, ord("a"), 0x02C6, (1, 0)),
            _GlyphComposition(0xEA, ord("e"), 0x02C6, (1, 0)),
            _GlyphComposition(0xEE, 0x0131, 0x02C6, (-1, 0)),
            _GlyphComposition(0xF4, ord("o"), 0x02C6, (1, 0)),
        ),
    ),
    # Both authored asterisks are exactly the native font raster shifted down
    # one pixel. Preserve that bearing at both scales, without changing shape.
    "F_SSERIF_T8.BMP": _OutlineRecipe(_SANS_SERIF, 11, vertical_offsets=((42, 1),)),
    "F_SSERIF_T8B.BMP": _OutlineRecipe(
        _SANS_SERIF, 11, synthetic_bold=True, vertical_offsets=((42, 1),)
    ),
}
_PRINTABLE_START: Final = 33
_PRINTABLE_END: Final = 127
_EXTENDED_START: Final = 161
_EXTENDED_END: Final = 256
_FIXED_ONE: Final = 65536
_CENTER_PHASE: Final = 32


@dataclass(frozen=True, slots=True)
class OutlineGlyph:
    """A character's accepted contour or explicit source-artwork fallback."""

    character: int
    reason: str

    @property
    def outlined(self) -> bool:
        """Whether every fidelity gate passed."""
        return self.reason in {
            "verified-outline",
            "verified-outline-padded",
            "verified-outline-scaled",
            "outline-within-tolerance",
        }


@dataclass(frozen=True, slots=True)
class OutlineAtlas:
    """A complete atlas with partial outline coverage recorded in its PNG."""

    image: Image.Image
    glyphs: tuple[OutlineGlyph, ...]


def supplied_font_files(directory: Path) -> dict[str, bytes]:
    """Identify supported font bytes by content, never by filename or OS lookup."""
    if not directory.is_dir():
        msg = "the supplied font directory does not exist"
        raise ValueError(msg)
    supported = {recipe.font_sha256 for recipe in _RECIPES.values()}
    result = {}
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.suffix.casefold() == ".ttf":
            payload = path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            if digest in supported:
                result[digest] = payload
    if not result:
        msg = "no verified font files found; supplied TTF files must match a supported font digest"
        raise ValueError(msg)
    return result


def outline_font_digest(name: str) -> str | None:
    """Return the explicit font input required by a supported atlas recipe."""
    recipe = _RECIPES.get(name.upper())
    return recipe.font_sha256 if recipe is not None else None


def regenerate_outline_atlas(source: Path, font_bytes: bytes) -> OutlineAtlas:
    """Render verified glyphs at 4x without altering advances or clipping contours."""
    name = source.name.upper()
    contract = _RECIPES.get(name)
    recipe = font_atlas_recipe(name)
    if contract is None or recipe is None:
        msg = f"no verified outline recipe for {name}"
        raise ValueError(msg)
    digest = contract.font_sha256
    if hashlib.sha256(font_bytes).hexdigest() != digest:
        msg = f"{name}: font bytes do not match the verified face"
        raise ValueError(msg)
    if ft.version() != _RENDERER_VERSION:
        msg = f"font reconstruction requires FreeType {_RENDERER_VERSION}, got {ft.version()}"
        raise ValueError(msg)
    source_bytes = source.read_bytes()
    with Image.open(BytesIO(source_bytes)) as opened:
        original = opened.convert("RGB")
    if original.size != FONT_ATLAS_COLOR_SIZES[name]:
        msg = f"{name}: unexpected original atlas dimensions"
        raise ValueError(msg)
    baseline = _baseline(original)
    face = _GlyphFace(
        ft.Face.from_bytes(font_bytes),
        contract.synthetic_bold,
        contract.vertical_offsets,
        contract.compositions,
    )
    face.font.set_pixel_sizes(0, contract.pixel_size)
    output = regenerate_font_atlas(source)
    key = np.asarray(original.getpixel((0, 0)), dtype=np.uint8)
    decisions = []
    for cell in parse_glyph_cells(original, recipe):
        pixels = np.asarray(original.crop(cell.rect))
        if not contract.supports_character(cell.character):
            # SSerif D8/DA are authored arrows, not Unicode letters. Only the
            # verified Tooltip descriptor uses Latin-1 for extended slots.
            dense, reason = None, "authored-space-or-symbol"
        else:
            dense, reason = _reconstruct_glyph(face, cell.character, pixels, key, baseline)
        if dense is not None:
            output.paste(dense, (cell.rect[0] * SCALE, cell.rect[1] * SCALE))
        decisions.append(OutlineGlyph(cell.character, reason))
    output, decisions = _extend_glyph_bank(original, output, face, name, decisions)
    if source.read_bytes() != source_bytes:
        msg = "font atlas source changed during reconstruction"
        raise ValueError(msg)
    output.info[FONT_OUTLINE_STAMP] = json.dumps(
        {
            "recipe": 9,
            "native_mismatch_limits": {
                "ink_union_fraction": _MAX_NATIVE_MISMATCH_FRACTION,
                "pixels": _MAX_NATIVE_MISMATCH_PIXELS,
            },
            "atlas": name,
            "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "font_sha256": digest,
            "freetype": ".".join(map(str, _RENDERER_VERSION)),
            "glyphs": [{"character": row.character, "result": row.reason} for row in decisions],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return OutlineAtlas(output, tuple(decisions))


def _extend_glyph_bank(
    original: Image.Image,
    header: Image.Image,
    face: _GlyphFace,
    name: str,
    decisions: list[OutlineGlyph],
) -> tuple[Image.Image, list[OutlineGlyph]]:
    """Store verified overhangs separately, preserving original text advances."""
    layout = font_bank_layout(name)
    recipe = font_atlas_recipe(name)
    if layout is None or recipe is None:
        return header, decisions
    key = np.asarray(original.getpixel((0, 0)), dtype=np.uint8)
    background = tuple(int(value) for value in key)
    bank = Image.new("RGB", layout.image_size, background)
    bank.paste(header, (0, 0))
    marker_background = original.getpixel((0, 2))
    if marker_background is None:
        msg = "font atlas has no baseline background"
        raise ValueError(msg)
    bank.paste(marker_background, (0, original.height * SCALE, 1, bank.height))
    baseline = _baseline(original)
    updated = []
    flags = []
    for index, (cell, decision) in enumerate(
        zip(parse_glyph_cells(original, recipe), decisions, strict=True)
    ):
        left, top, right, bottom = layout.glyph_rect(index, cell.rect[2] - cell.rect[0])
        canvas = Image.new("RGB", ((right - left) * SCALE, (bottom - top) * SCALE), background)
        pixels = original.crop(cell.rect)
        canvas.paste(
            pixels.resize((pixels.width * SCALE, pixels.height * SCALE), Image.Resampling.NEAREST),
            (SCALE, SCALE),
        )
        padded = None
        if decision.reason in {
            "contour-outside-cell",
            "reference-sampling-mismatch",
            "native-raster-near-match",
        }:
            padded = _padded_glyph(face, cell.character, np.asarray(pixels), key, baseline)
        flags.append(padded is not None)
        updated.append(
            OutlineGlyph(
                cell.character,
                "outline-within-tolerance"
                if decision.reason == "native-raster-near-match"
                else "verified-outline-scaled",
            )
            if padded is not None
            else decision
        )
        bank.paste(canvas, (left * SCALE, top * SCALE))
        bank.paste(
            padded if padded is not None else canvas,
            (left * SCALE, top * SCALE + layout.bank_distance),
        )
    if not any(flags):
        return header, decisions
    write_font_bank_flags(bank, layout, flags)
    bank.info.update(header.info)
    return bank, updated


def _padded_glyph(
    face: _GlyphFace,
    character: int,
    pixels: NDArray[np.uint8],
    key: NDArray[np.uint8],
    baseline: int,
) -> Image.Image | None:
    """Accept the full contour only after native fidelity and no lost ink.

    Called only after the native raster gate passed. Padding is storage,
    not another scale, altered pen position, or permission to clip any ink.
    """
    target = np.any(pixels != key, axis=2)
    native, left, _top = _raster(face, character, scale=1)
    pen = int(np.nonzero(target)[1].min()) - int(np.nonzero(native)[1].min()) - left
    contour, left, top = _raster(face, character, scale=SCALE)
    expected = np.pad(target, 1)
    dense, outside = _place(
        contour,
        (expected.shape[0] * SCALE, expected.shape[1] * SCALE),
        ((pen + 1) * SCALE + left, (baseline + 1) * SCALE - top),
    )
    if outside:
        return None
    ink = np.unique(pixels[target], axis=0)
    if len(ink) != 1:
        return None
    rgb = np.empty((*dense.shape, 3), dtype=np.uint8)
    rgb[:] = key
    rgb[dense] = ink[0]
    return Image.fromarray(rgb)


def _baseline(original: Image.Image) -> int:
    """Read the single-row family's authored baseline rather than fitting text."""
    background = original.getpixel((0, 2))
    markers = [y for y in range(2, original.height) if original.getpixel((0, y)) != background]
    if len(markers) != 1:
        msg = "font atlas requires exactly one original baseline marker"
        raise ValueError(msg)
    return markers[0]


def _reconstruct_glyph(
    face: _GlyphFace,
    character: int,
    pixels: NDArray[np.uint8],
    key: NDArray[np.uint8],
    baseline: int,
) -> tuple[Image.Image | None, str]:
    """Keep all failed gates visible; never repair a candidate's shape to pass."""
    # The extended descriptor's Latin-1 artwork has the same Unicode mapping.
    # Keep control/default cells (including 0x9d) authored. The Tooltip's last
    # cell is actual y-diaeresis (0xff), not a default symbol. Missing cmap
    # entries are rejected by _raster before a .notdef box can be mistaken for ink.
    if not (
        _PRINTABLE_START <= character < _PRINTABLE_END
        or _EXTENDED_START <= character < _EXTENDED_END
    ):
        return None, "authored-space-or-symbol"
    target = np.any(pixels != key, axis=2)
    ink = np.unique(pixels[target], axis=0)
    if len(ink) != 1:
        return None, "nonuniform-or-empty-artwork"
    native, left, top = _raster(face, character, scale=1)
    if not native.any():
        return None, "missing-font-glyph"
    pen = int(np.nonzero(target)[1].min()) - int(np.nonzero(native)[1].min()) - left
    placed, outside = _place(native, target.shape, (pen + left, baseline - top))
    if outside or not np.array_equal(placed, target):
        # Never replace reference-size pixels with an approximation. Only
        # the bank path may accept this glyph, keeping native draws exact.
        reason = (
            "native-raster-near-match"
            if not outside and _small_raster_difference(placed, target)
            else "native-raster-mismatch"
        )
        return None, reason
    contour, left, top = _raster(face, character, scale=SCALE)
    dense, outside = _place(
        contour,
        (target.shape[0] * SCALE, target.shape[1] * SCALE),
        (pen * SCALE + left, baseline * SCALE - top),
    )
    sample_matches = np.array_equal(dense[SCALE // 2 :: SCALE, SCALE // 2 :: SCALE], target)
    if outside or not sample_matches:
        return None, "contour-outside-cell" if outside else "reference-sampling-mismatch"
    rgb = np.empty((*dense.shape, 3), dtype=np.uint8)
    rgb[:] = key
    rgb[dense] = ink[0]
    return Image.fromarray(rgb), "verified-outline"


def _small_raster_difference(candidate: NDArray[np.bool_], target: NDArray[np.bool_]) -> bool:
    """Allow a tiny ink disagreement, never changed extents or an empty glyph."""
    if not candidate.any() or not target.any():
        return False
    for mask in (candidate, target):
        rows, columns = np.nonzero(mask)
        bounds = (rows.min(), columns.min(), rows.max(), columns.max())
        if mask is candidate:
            candidate_bounds = bounds
        elif bounds != candidate_bounds:
            return False
    changed = int(np.count_nonzero(candidate != target))
    union = int(np.count_nonzero(candidate | target))
    return (
        changed <= _MAX_NATIVE_MISMATCH_PIXELS and changed / union <= _MAX_NATIVE_MISMATCH_FRACTION
    )


def _raster(face: _GlyphFace, character: int, *, scale: int) -> tuple[NDArray[np.bool_], int, int]:
    """Transform native-size hinted outlines, not a newly hinted larger font."""
    composition = next((item for item in face.compositions if item.character == character), None)
    if composition is not None:
        return _compose_raster(face, composition, scale=scale)
    font = face.font
    if font.get_char_index(character) == 0:
        return np.zeros((0, 0), dtype=np.bool_), 0, 0
    phase = _CENTER_PHASE if scale == SCALE else 0
    font.set_transform(
        ft.Matrix(scale * _FIXED_ONE, 0, 0, scale * _FIXED_ONE), ft.Vector(phase, -phase)
    )
    font.load_char(
        chr(character), FT_LOAD_TARGETS["FT_LOAD_TARGET_MONO"] | FT_LOAD_FLAGS["FT_LOAD_NO_BITMAP"]
    )
    font.glyph.render(FT_RENDER_MODES["FT_RENDER_MODE_MONO"])
    bitmap = font.glyph.bitmap
    rows = np.asarray(bitmap.buffer, dtype=np.uint8).reshape(bitmap.rows, abs(bitmap.pitch))
    pixels = np.unpackbits(rows, axis=1)[:, : bitmap.width] != 0
    if face.synthetic_bold:
        pixels = _horizontal_bold(pixels, scale=scale)
    offset = dict(face.vertical_offsets).get(character, 0)
    return pixels, font.glyph.bitmap_left, font.glyph.bitmap_top - offset * scale


def _compose_raster(
    face: _GlyphFace, composition: _GlyphComposition, *, scale: int
) -> tuple[NDArray[np.bool_], int, int]:
    """Join complete component contours, preserving their common scale and bearings."""
    base, base_left, base_top = _raster(face, composition.base, scale=scale)
    accent, accent_left, accent_top = _raster(face, composition.accent, scale=scale)
    if not base.any() or not accent.any():
        return np.zeros((0, 0), dtype=np.bool_), 0, 0
    accent_left += composition.offset[0] * scale
    accent_top -= composition.offset[1] * scale
    left = min(base_left, accent_left)
    top = max(base_top, accent_top)
    right = max(base_left + base.shape[1], accent_left + accent.shape[1])
    bottom = max(base.shape[0] - base_top, accent.shape[0] - accent_top)
    pixels = np.zeros((top + bottom, right - left), dtype=np.bool_)
    for raster, raster_left, raster_top in (
        (base, base_left, base_top),
        (accent, accent_left, accent_top),
    ):
        x = raster_left - left
        y = top - raster_top
        pixels[y : y + raster.shape[0], x : x + raster.shape[1]] |= raster
    return pixels, left, top


def _horizontal_bold(pixels: NDArray[np.bool_], *, scale: int) -> NDArray[np.bool_]:
    """Reproduce the verified one-native-pixel rightward GDI stroke expansion."""
    expanded = np.zeros((pixels.shape[0], pixels.shape[1] + scale), dtype=np.bool_)
    for shift in range(scale + 1):
        expanded[:, shift : shift + pixels.shape[1]] |= pixels
    return expanded


def _place(
    pixels: NDArray[np.bool_], size: tuple[int, int], origin: tuple[int, int]
) -> tuple[NDArray[np.bool_], int]:
    """Measure out-of-cell ink as an error, not a permission to discard it."""
    height, width = size
    x, y = origin
    rows, columns = pixels.shape
    result = np.zeros(size, dtype=np.bool_)
    left, top, right, bottom = max(0, x), max(0, y), min(width, x + columns), min(height, y + rows)
    if right > left and bottom > top:
        result[top:bottom, left:right] = pixels[top - y : bottom - y, left - x : right - x]
    return result, int(pixels.sum() - result.sum())
