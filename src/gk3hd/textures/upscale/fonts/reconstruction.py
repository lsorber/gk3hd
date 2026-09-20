"""Verified coverage-font recipes with original-size artwork retained."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import numpy as np
from PIL import Image
from scipy.ndimage import label

from gk3hd.textures.flat import actual_files
from gk3hd.textures.upscale.fonts.atlas import (
    SCALE,
    FontAtlasRecipe,
    _render_exact_raster_atlas,
    parse_glyph_cells,
)
from gk3hd.textures.upscale.fonts.bank import font_row_bank_layout, stamp_font_row_bank
from gk3hd.textures.upscale.fonts.coverage import reconstruct_font_coverage

if TYPE_CHECKING:
    from pathlib import Path

    from numpy.typing import NDArray

    from gk3hd.textures.upscale.fonts.atlas import GlyphCell
    from gk3hd.textures.upscale.fonts.bank import FontRowBankLayout

_HINT_NAME: Final = "SID_TEXT_22.BMP"
_HINT_SIZE: Final = (518, 100)
_HINT_LINES: Final = 4
_SIZE_RATIO: Final = 0.62
_BASELINE_PHASE: Final = 0.25
_SOURCE_BASELINE: Final = 10
_BASELINES: Final = {
    "RC_GOUDY12.BMP": 12,
    "F_ARIAL_A12.BMP": 12,
    "SID_TEXT_14.BMP": 10,
    "SID_TEXT_18.BMP": 13,
    "SID_TEXT_22.BMP": 18,
    "SID_CAP_20.BMP": 21,
    "SID_CAP_16.BMP": 16,
    "SID_CAP_26.BMP": 25,
    "SID_PDN_10.BMP": 8,
    "SID_PDN_12.BMP": 10,
    "SID_PDN_16.BMP": 14,
    "F_TEMPUS_A10.BMP": 11,
}
_HINT_BASELINE: Final = 18
_PADDING: Final = 2
_FALLBACK_CHARACTER: Final = 0x9D
_RGB_COVERAGE_FONT: Final = "F_ARIAL_A12.BMP"
_FULL_COVERAGE: Final = 31
_PRECOLORED_ALPHA: Final = "F_DODGENBURN16.BMP"
_GRAY_ALPHA: Final = "F_CAPTION_GOUDY14AA.BMP"
_DODGE_PALETTE: Final = frozenset(
    {(0, 0, 0), (0, 4, 0), (8, 8, 8), (8, 12, 8), (123, 56, 255), (205, 56, 255)}
)
# The small pull-down S shapes have ambiguous narrow openings; reconstruction
# exaggerates those closures. The larger sibling does not resolve them. Keep exact
# source samples until their outlines are resolved; this is not pixel-art status.
SOURCE_GLYPH_EXCEPTIONS: Final = {
    "SID_PDN_10.BMP": frozenset({0x53, 0x73, 0xDF}),
    "SID_PDN_12.BMP": frozenset({0x53, 0x73, 0xDF}),
    # Five-bit sampling has filled the tiny e bowl. Smoothing its contour
    # makes it resemble c; preserve the authored sample until resolved.
    "F_TEMPUS_A10.BMP": frozenset({0x65}),
    "F_TEMPUS_10.BMP": frozenset({0x65}),
}


def reconstruct_alpha_font(
    original: Image.Image, opacity: Image.Image, recipe: FontAtlasRecipe
) -> Image.Image:
    """Reconstruct eight-bit opacity without changing native color or tint math.

    Both planes share the exact same reference and enlarged glyph coordinates.
    The original white/keyed or verified precolored plane stays unchanged; only fractional
    opacity is reconstructed. Full/empty source pixels and per-pixel ink sums
    are conserved, so reconstruction cannot move ink into black color samples.
    """
    layout = font_row_bank_layout(recipe.primary)
    if recipe.coverage_baseline is None or layout is None:
        msg = f"no verified paired coverage-font recipe: {recipe.primary}"
        raise ValueError(msg)
    if original.size != layout.source_size or opacity.size != original.size:
        msg = f"{recipe.primary}: source does not match the verified font recipe"
        raise ValueError(msg)
    key = (0, 0, 0) if recipe.primary in {"F_TEMPUS_10.BMP", _PRECOLORED_ALPHA} else (255, 0, 255)
    _validate_alpha_metadata(original, recipe, key)
    cells = parse_glyph_cells(original, recipe)
    if len(cells) != layout.glyph_count:
        msg = "paired coverage-font reconstruction requires a complete character map"
        raise ValueError(msg)
    # Validate both planes regardless of which output is requested.
    _validate_color_opacity(original, opacity, cells, recipe)
    reference = _render_exact_raster_atlas(opacity if recipe.alpha else original, cells, recipe)
    candidate = reference.copy()
    if recipe.alpha:
        for cell in cells:
            if cell.character in SOURCE_GLYPH_EXCEPTIONS.get(recipe.primary, frozenset()) | {
                _FALLBACK_CHARACTER
            }:
                continue
            coverage = np.asarray(opacity.crop(cell.rect))
            if recipe.coverage_key_threshold:
                # Preserve the raw opacity in the reference bank, but reconstruct
                # only visible ink. Color-keyed samples never contributed light
                # in the original game and must not bleed into adjacent strokes.
                coverage = np.where(coverage > recipe.coverage_key_threshold, coverage, 0)
            reconstructed = reconstruct_font_coverage(np.pad(coverage, _PADDING), bit_depth=8)
            margin = _PADDING * SCALE
            candidate.paste(
                Image.fromarray(reconstructed[margin:-margin, margin:-margin]),
                (cell.rect[0] * SCALE, cell.rect[1] * SCALE),
            )
    bank = Image.new(reference.mode, layout.image_size, 0 if recipe.alpha else key)
    bank.paste(reference)
    bank.paste(candidate, (layout.bank_distance, 0))
    if not recipe.alpha:
        _finish_alpha_color_bank(bank, original, recipe, cells, layout)
    return bank


def _finish_alpha_color_bank(
    bank: Image.Image,
    original: Image.Image,
    recipe: FontAtlasRecipe,
    cells: tuple[GlyphCell, ...],
    layout: FontRowBankLayout,
) -> None:
    """Keep parser metadata out of the second bank and close implicit final cells."""
    pixels = np.asarray(original)
    red, green, blue = pixels[0, 0]
    key = (int(red), int(green), int(blue))
    red, green, blue = pixels[2, 0]
    parser_background = (int(red), int(green), int(blue))
    row_height = layout.source_size[1] // layout.line_count * SCALE
    for row in range(layout.line_count):
        top = row * row_height
        bank.paste(parser_background, (layout.bank_distance, top, bank.width, top + 1))
    if recipe.implicit_right_edge:
        # The native parser otherwise treats both banks as the final glyph.
        # The remaining storage cell is not addressed by any descriptor byte.
        red, green, blue = pixels[0, cells[0].rect[0]]
        bank.putpixel((layout.bank_distance, 0), (int(red), int(green), int(blue)))
    stamp_font_row_bank(bank, key=key, ink=(255, 255, 255))


def _validate_color_opacity(
    original: Image.Image,
    opacity: Image.Image,
    cells: tuple[GlyphCell, ...],
    recipe: FontAtlasRecipe,
) -> None:
    """Keep each paired font's explicit color contract; never infer it from alpha."""
    key = np.asarray(original)[2, 0]
    for cell in cells:
        color = np.asarray(original.crop(cell.rect))
        alpha = np.asarray(opacity.crop(cell.rect))
        if recipe.primary == _GRAY_ALPHA:
            _validate_gray_opacity(color, alpha, recipe.primary)
            continue
        if recipe.primary == _PRECOLORED_ALPHA:
            # Its additive purple ink and low-level authored color noise are
            # independent of opacity. Both banks keep every RGB sample. Exact
            # alpha block sums therefore also conserve premultiplied RGB sums.
            colors = {tuple(pixel) for pixel in np.unique(color.reshape(-1, 3), axis=0)}
            if not colors <= _DODGE_PALETTE:
                msg = f"{recipe.primary}: unexpected precolored glyph palette"
                raise ValueError(msg)
            continue
        expected = np.where(
            (alpha > recipe.coverage_key_threshold)[:, :, None], (255, 255, 255), key
        )
        # White source samples with zero opacity are legitimate authored ink:
        # preserve their color bytes, but do not invent coverage there. Positive
        # opacity still requires the expected white/key color contract.
        transparent_white = (alpha == 0) & np.all(color == (255, 255, 255), axis=2)
        if not np.all(np.all(color == expected, axis=2) | transparent_white):
            msg = f"{recipe.primary}: glyph color and opacity masks disagree"
            raise ValueError(msg)


def _validate_gray_opacity(color: NDArray[np.uint8], alpha: NDArray[np.uint8], name: str) -> None:
    """Keep the authored grayscale plane; do not turn it into white lettering."""
    # Positive-opacity colors match the opacity quantized to RGB565. Applying
    # opacity to white instead would brighten fractional edges a second time.
    shifts = np.asarray((3, 2, 3), dtype=np.uint8)
    matching = np.all((color >> shifts) == (alpha[..., None] >> shifts), axis=2)
    empty = (alpha == 0) & (
        np.all(color == (255, 255, 255), axis=2) | np.all(color == (255, 0, 255), axis=2)
    )
    if not np.all(matching | empty):
        msg = f"{name}: grayscale color and opacity do not match the verified font recipe"
        raise ValueError(msg)


def _validate_alpha_metadata(
    original: Image.Image, recipe: FontAtlasRecipe, key: tuple[int, int, int]
) -> None:
    """Separate native recoloring anchors from precolored atlas metadata."""
    if recipe.primary == _GRAY_ALPHA:
        pixels = np.asarray(original)
        column = np.full((original.height, 3), 255, dtype=np.uint8)
        column[0] = key
        column[-1] = key
        column[13] = (0, 0, 0)
        rows = pixels[0, 1:]
        if np.array_equal(pixels[:, 0], column) and np.all(
            np.all(rows == (255, 255, 255), axis=1) | np.all(rows == (0, 0, 0), axis=1)
        ):
            return
    elif recipe.primary == _PRECOLORED_ALPHA:
        pixels = np.asarray(original)
        column = np.zeros((original.height, 3), dtype=np.uint8)
        column[14] = (255, 44, 0)
        column[54:] = (0, 4, 0)
        rows = pixels[::19, 1:]
        if np.array_equal(pixels[:, 0], column) and np.all(
            np.all(rows == key, axis=2) | np.all(rows == (0, 0, 213), axis=2)
        ):
            return
    else:
        markers = [y for y in range(original.height) if original.getpixel((0, y)) != key]
        if (
            recipe.coverage_baseline is not None
            and original.getpixel((0, 2)) == key
            and markers == [1, recipe.coverage_baseline]
            and original.getpixel((0, 1)) == (255, 255, 255)
            and original.getpixel((0, recipe.coverage_baseline)) == recipe.coverage_baseline_color
        ):
            return
    msg = f"{recipe.primary}: source does not match the verified font recipe"
    raise ValueError(msg)


def reconstruct_coverage_font(
    source: Path, original: Image.Image, reference: Image.Image, recipe: FontAtlasRecipe
) -> Image.Image:
    """Reconstruct the reviewed atlas; preserve original samples and all metrics.

    The 14-size recipe uses a larger original only for compatible directions,
    with one fixed isotropic scale and phase. Other recipes use their own
    coverage alone, preserving explicitly unresolved glyphs as source artwork.
    No character is stretched and no external typeface is used.
    """
    layout = font_row_bank_layout(recipe.primary)
    if layout is None:
        msg = f"no verified coverage-font reconstruction layout: {recipe.primary}"
        raise ValueError(msg)
    baseline = _BASELINES[recipe.primary]
    _validate(original, layout.source_size, baseline, recipe.primary)
    cells = parse_glyph_cells(original, recipe)
    if len(cells) != layout.glyph_count:
        msg = "coverage-font reconstruction requires complete, matching character maps"
        raise ValueError(msg)
    hints = (
        _direction_hints(source, original, recipe) if recipe.primary == "SID_TEXT_14.BMP" else {}
    )
    candidate = reference.copy()
    for cell in cells:
        # The default-character rectangle is authored artwork, not a letter.
        if cell.character == _FALLBACK_CHARACTER or cell.character in SOURCE_GLYPH_EXCEPTIONS.get(
            recipe.primary, frozenset()
        ):
            continue
        coverage = np.asarray(original.crop(cell.rect))[:, :, 2] >> 3
        direction = hints.get(cell.character)
        reconstructed = reconstruct_font_coverage(
            np.pad(coverage, _PADDING),
            edge_hint=None if direction is None else np.pad(direction, _PADDING * SCALE),
        )
        margin = _PADDING * SCALE
        blue = reconstructed[margin:-margin, margin:-margin]
        pixels = (
            _reconstruct_gray_rgb(np.asarray(original.crop(cell.rect)), blue)
            if recipe.primary == _RGB_COVERAGE_FONT
            else np.repeat((blue * 8)[:, :, None], 3, axis=2)
        )
        candidate.paste(Image.fromarray(pixels), (cell.rect[0] * SCALE, cell.rect[1] * SCALE))
    bank = Image.new("RGB", layout.image_size, (0, 0, 0))
    bank.paste(reference, (0, 0))
    bank.paste(candidate, (layout.bank_distance, 0))
    # Only the reference half may contribute native parser boundaries.
    row_height = layout.source_size[1] // layout.line_count * SCALE
    for row in range(layout.line_count):
        top = row * row_height
        bank.paste((0, 0, 0), (layout.bank_distance, top, bank.width, top + 1))
    if recipe.implicit_right_edge:
        # Single-row fonts use the bitmap width as their last boundary. The
        # second bank must not enlarge that final character. A closing marker
        # leaves one unaddressed storage cell: all 256 native byte lookups still
        # resolve to the original glyph slots, including the default character.
        marker = (255, 255, 255) if recipe.primary == _RGB_COVERAGE_FONT else (255, 0, 0)
        bank.putpixel((layout.bank_distance, 0), marker)
    ink = (255, 255, 255) if recipe.primary == _RGB_COVERAGE_FONT else (248, 248, 248)
    stamp_font_row_bank(bank, key=(0, 0, 0), ink=ink)
    return bank


def _reconstruct_gray_rgb(color: NDArray[np.uint8], blue: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Conserve all RGB565 channels of the reviewed antialiased Arial source.

    Its red/blue codes agree, while green has one extra precision bit. Keeping
    that bit per source block preserves RGB means as well as five-bit coverage,
    without assuming that the consumer uses alpha-blend recoloring. Disconnected
    components without solid ink remain exact samples: sharpening the source's
    small uncertain marks must not turn them into new bright spots.
    """
    old = color >> np.array([3, 2, 3], dtype=np.uint8)
    parity = old[..., 1].astype(np.int16) - 2 * old[..., 2]
    if not np.array_equal(old[..., 0], old[..., 2]) or not np.all((parity == 0) | (parity == 1)):
        msg = "F_ARIAL_A12.BMP: source does not match the verified grayscale RGB palette"
        raise ValueError(msg)
    components, count = label(old[..., 2] > 0, np.ones((3, 3), dtype=np.uint8))
    uncertain = np.zeros(old.shape[:2], dtype=bool)
    for number in range(1, count + 1):
        part = components == number
        if old[..., 2][part].max() < _FULL_COVERAGE:
            uncertain |= part
    copied = np.repeat(np.repeat(uncertain, SCALE, axis=0), SCALE, axis=1)
    baseline = np.repeat(np.repeat(old[..., 2], SCALE, axis=0), SCALE, axis=1)
    blue = np.where(copied, baseline, blue)
    green = (blue * 2 + np.repeat(np.repeat(parity, SCALE, axis=0), SCALE, axis=1)).astype(np.uint8)
    red_blue = (blue << 3) | (blue >> 2)
    return np.stack((red_blue, (green << 2) | (green >> 4), red_blue), axis=-1)


def _direction_hints(
    source: Path, original: Image.Image, recipe: FontAtlasRecipe
) -> dict[int, NDArray[np.float64]]:
    """Load the separately reviewed input-only guide for the 14-size recipe."""
    hint_path = actual_files(source.parent, suffix=".bmp").get(_HINT_NAME.casefold())
    if hint_path is None:
        msg = f"font reconstruction requires original companion: {_HINT_NAME}"
        raise ValueError(msg)
    with Image.open(hint_path) as opened:
        hint = opened.convert("RGB")
    _validate(hint, _HINT_SIZE, _HINT_BASELINE, _HINT_NAME)
    hint_recipe = FontAtlasRecipe(_HINT_NAME, recipe.characters, _HINT_LINES)
    cells = parse_glyph_cells(original, recipe)
    hint_cells = {cell.character: cell for cell in parse_glyph_cells(hint, hint_recipe)}
    if set(hint_cells) != {c.character for c in cells}:
        msg = "SIDNEY font reconstruction requires complete, matching character maps"
        raise ValueError(msg)
    result = {}
    for cell in cells:
        coverage = np.asarray(original.crop(cell.rect))[:, :, 2] >> 3
        sibling = np.asarray(hint.crop(hint_cells[cell.character].rect))[:, :, 2] >> 3
        result[cell.character] = _edge_hint(coverage, sibling)
    return result


def _validate(image: Image.Image, size: tuple[int, int], baseline: int, name: str) -> None:
    markers = [y for y in range(image.height) if image.getpixel((0, y)) != (0, 0, 0)]
    marker_color = (205, 0, 0) if name == "F_TEMPUS_A10.BMP" else (255, 0, 0)
    if name == _RGB_COVERAGE_FONT:
        marker_color = (255, 255, 255)
    if image.size != size or markers != [baseline] or image.getpixel((0, baseline)) != marker_color:
        msg = f"{name}: source dimensions or baseline markers do not match the verified font recipe"
        raise ValueError(msg)


def _edge_hint(source: NDArray[np.uint8], sibling: NDArray[np.uint8]) -> NDArray[np.float64]:
    """Align authored ink left and baseline, with one shared scale and phase."""
    height, width = source.shape
    source_ink, sibling_ink = np.nonzero(source), np.nonzero(sibling)
    if not len(source_ink[0]) or not len(sibling_ink[0]):
        return np.zeros((height * SCALE, width * SCALE))
    shift_x = float(source_ink[1].min() - sibling_ink[1].min() * _SIZE_RATIO)
    # Glyph crops start one row below the marker row.
    shift_y = _SOURCE_BASELINE - 1 - (_HINT_BASELINE - 1) * _SIZE_RATIO + _BASELINE_PHASE
    image = Image.fromarray((sibling / 31).astype(np.float32))
    result = image.transform(
        (width * SCALE, height * SCALE),
        Image.Transform.AFFINE,
        (
            1 / (SCALE * _SIZE_RATIO),
            0,
            -shift_x / _SIZE_RATIO,
            0,
            1 / (SCALE * _SIZE_RATIO),
            -shift_y / _SIZE_RATIO,
        ),
        resample=Image.Resampling.BICUBIC,
        fillcolor=0,
    )
    return np.asarray(np.clip(np.asarray(result), 0, 1), dtype=np.float64)
