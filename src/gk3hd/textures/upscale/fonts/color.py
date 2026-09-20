"""Source-constrained reconstruction of the verified plain SIDNEY color fonts.

This is not a generic color-to-coverage conversion. Its RGB565 palette follows
one ink/background axis per glyph; embossed siblings do not. Keep the native reference
bank, all character metrics, every channel's block sum, and the exact key mask.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import numpy as np
from PIL import Image

from gk3hd.textures.upscale.fonts.atlas import SCALE, parse_glyph_cells
from gk3hd.textures.upscale.fonts.bank import font_row_bank_layout, stamp_font_row_bank
from gk3hd.textures.upscale.fonts.coverage import conserve_font_channel, reconstruct_font_coverage

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from gk3hd.textures.upscale.fonts.atlas import FontAtlasRecipe, GlyphCell

_KEY: Final = (172, 125, 49)
_INK: Final = (57, 60, 57)
_MARKER: Final = (255, 255, 255)
_MAXIMA: Final = (31, 63, 31)
_SHIFTS: Final = np.array([3, 2, 3], dtype=np.uint8)
_BACKGROUND: Final = np.array(_KEY, dtype=np.uint8) >> _SHIFTS
# Includes the original bright overshoot samples, not a clipped two-color ramp.
_PALETTE: Final = frozenset(
    {
        _KEY,
        _INK,
        (65, 64, 57),
        (74, 68, 57),
        (82, 72, 57),
        (90, 76, 57),
        (98, 80, 57),
        (106, 89, 57),
        (115, 93, 57),
        (123, 97, 49),
        (131, 101, 49),
        (139, 105, 49),
        (148, 109, 49),
        (156, 117, 49),
        (164, 117, 49),
        (164, 121, 49),
        (172, 121, 49),
        (180, 129, 49),
        (180, 133, 49),
    }
)
_BASELINES: Final = {
    "SID_NO_EMB_10.BMP": 9,
    "SID_NO_EMB_11.BMP": 10,
    "SID_NO_EMB_14.BMP": 12,
    "SID_NO_EMB_18.BMP": 15,
}
_SMALL_PALETTE: Final = _PALETTE | {(123, 97, 57), (131, 105, 49), (156, 113, 49)}
# Only the 11-size copyright/registered symbols use this darker ink axis.
# Applying the letter palette to them changes their apparent weight.
_SYMBOL_PALETTE: Final = frozenset(
    {
        _KEY,
        (16, 16, 0),
        (41, 32, 8),
        (57, 40, 16),
        (65, 48, 16),
        (82, 56, 24),
        (90, 68, 24),
        (106, 76, 24),
        (115, 85, 32),
        (131, 93, 32),
        (139, 101, 41),
        (156, 109, 41),
        (164, 121, 49),
    }
)
_PADDING: Final = 2


def validate_plain_color_font(
    original: Image.Image, recipe: FontAtlasRecipe
) -> tuple[GlyphCell, ...]:
    """Validate the reviewed plain source, also used as an embossed-font matte."""
    layout = font_row_bank_layout(recipe.primary)
    baseline = _BASELINES.get(recipe.primary)
    if (
        baseline is None
        or layout is None
        or original.size != layout.source_size
        or original.getpixel((0, 0)) != _KEY
        or original.getpixel((0, 2)) != _KEY
        or original.getpixel((0, 1)) != _KEY
        or [y for y in range(original.height) if original.getpixel((0, y)) != _KEY] != [baseline]
        or original.getpixel((0, baseline)) != _MARKER
    ):
        msg = f"{recipe.primary}: source does not match the verified color-font recipe"
        raise ValueError(msg)
    cells = parse_glyph_cells(original, recipe)
    pixels = np.asarray(original)
    colors = {tuple(color) for color in np.unique(pixels.reshape(-1, 3), axis=0)}
    marker_rows = pixels[:: original.height // recipe.line_count, 1:]
    palette = _SMALL_PALETTE if recipe.primary == "SID_NO_EMB_10.BMP" else _PALETTE
    allowed = palette | (_SYMBOL_PALETTE if recipe.primary == "SID_NO_EMB_11.BMP" else set())
    if not colors <= allowed | {_MARKER} or not np.all(
        np.all(marker_rows == _KEY, axis=2) | np.all(marker_rows == _MARKER, axis=2)
    ):
        msg = f"{recipe.primary}: unexpected color-font palette or marker colors"
        raise ValueError(msg)
    for cell in cells:
        color = np.asarray(original.crop(cell.rect))
        glyph_palette = _SYMBOL_PALETTE if _dark_symbol(recipe, cell) else palette
        if not {tuple(pixel) for pixel in np.unique(color.reshape(-1, 3), axis=0)} <= glyph_palette:
            msg = f"{recipe.primary}: unexpected palette inside glyph {cell.character:#04x}"
            raise ValueError(msg)
    return cells


def reconstruct_color_font(
    original: Image.Image, reference: Image.Image, recipe: FontAtlasRecipe
) -> Image.Image:
    """Reconstruct the reviewed plain fonts; reject other artwork."""
    cells = validate_plain_color_font(original, recipe)
    layout = font_row_bank_layout(recipe.primary)
    if layout is None:
        msg = f"{recipe.primary}: missing verified color-font layout"
        raise ValueError(msg)
    candidate = reference.copy()
    for cell in cells:
        color = np.asarray(original.crop(cell.rect))
        candidate.paste(
            Image.fromarray(
                _reconstruct_glyph(color, ink=(0, 0, 0) if _dark_symbol(recipe, cell) else _INK)
            ),
            (cell.rect[0] * SCALE, cell.rect[1] * SCALE),
        )
    bank = Image.new("RGB", layout.image_size, _KEY)
    bank.paste(reference)
    bank.paste(candidate, (layout.bank_distance, 0))
    for row in range(layout.line_count):
        top = row * original.height // layout.line_count * SCALE
        bank.paste(_KEY, (layout.bank_distance, top, bank.width, top + 1))
    stamp_font_row_bank(bank, key=_KEY, ink=_MARKER)
    return bank


def _dark_symbol(recipe: FontAtlasRecipe, cell: GlyphCell) -> bool:
    return recipe.primary == "SID_NO_EMB_11.BMP" and cell.character in (0xA9, 0xAE)


def _reconstruct_glyph(
    color: NDArray[np.uint8], *, ink: tuple[int, int, int] = _INK
) -> NDArray[np.uint8]:
    old = color >> _SHIFTS
    direction = (np.array(ink, dtype=np.uint8) >> _SHIFTS).astype(float) - _BACKGROUND
    alpha = np.clip((old.astype(float) - _BACKGROUND) @ direction / (direction @ direction), 0, 1)
    quantized = np.rint(alpha * 255).astype(np.uint8)
    margin = _PADDING * SCALE
    coverage = reconstruct_font_coverage(np.pad(quantized, _PADDING), bit_depth=8)
    coverage = coverage[margin:-margin, margin:-margin].astype(float) / 255
    nearest = np.repeat(np.repeat(old, SCALE, axis=0), SCALE, axis=1).astype(float)
    low = np.repeat(np.repeat(quantized.astype(float) / 255, SCALE, axis=0), SCALE, axis=1)
    proposed = nearest + (coverage - low)[..., None] * direction
    return conserve_sidney_color(old, proposed)


def conserve_sidney_color(
    old: NDArray[np.uint8], proposed: NDArray[np.float64]
) -> NDArray[np.uint8]:
    """Keep RGB565 means and the authored brown key mask of verified SIDNEY fonts.

    Input is in channel code units, output in bit-expanded RGB. This numerical
    step does not approve an atlas or infer coverage from an arbitrary palette.
    """
    result = np.empty_like(proposed, dtype=np.uint8)
    for channel, maximum in enumerate(_MAXIMA):
        result[..., channel] = conserve_font_channel(
            old[..., channel], proposed[..., channel], maximum=maximum
        )
    background = np.repeat(
        np.repeat(np.all(old == _BACKGROUND, axis=2), SCALE, axis=0), SCALE, axis=1
    )
    result[background] = _BACKGROUND
    _preserve_key_mask(result, old)
    return np.stack(
        (
            (result[..., 0] << 3) | (result[..., 0] >> 2),
            (result[..., 1] << 2) | (result[..., 1] >> 4),
            (result[..., 2] << 3) | (result[..., 2] >> 2),
        ),
        axis=-1,
    ).astype(np.uint8)


def _repair_key_pixel(block: NDArray[np.uint8], old: NDArray[np.uint8], hole: int) -> bool:
    """Transfer one code unit without changing sums or introducing donor extrema."""
    for channel in np.argsort(-np.abs(old.astype(float) - _BACKGROUND)):
        delta = int(np.sign(float(old[channel]) - _BACKGROUND[channel]))
        if not delta:
            continue
        low = min(int(block[:, channel].min()), int(old[channel]))
        high = max(int(block[:, channel].max()), int(old[channel]))
        for donor in range(SCALE**2):
            if donor == hole or np.all(block[donor] == _BACKGROUND):
                continue
            proposed = block[donor].astype(int)
            proposed[channel] -= delta
            if not low <= proposed[channel] <= high or np.all(proposed == _BACKGROUND):
                continue
            block[hole, channel] = int(block[hole, channel]) + delta
            block[donor] = proposed
            return True
    return False


def _preserve_key_mask(result: NDArray[np.uint8], old: NDArray[np.uint8]) -> None:
    """Never turn opaque source pixels into key holes; fall back locally if needed."""
    for y, x in np.argwhere(np.any(old != _BACKGROUND, axis=2)):
        block = (
            result[y * SCALE : y * SCALE + SCALE, x * SCALE : x * SCALE + SCALE]
            .copy()
            .reshape(SCALE**2, 3)
        )
        for hole in np.flatnonzero(np.all(block == _BACKGROUND, axis=1)):
            if not _repair_key_pixel(block, old[y, x], int(hole)):
                block[:] = old[y, x]
                break
        result[y * SCALE : y * SCALE + SCALE, x * SCALE : x * SCALE + SCALE] = block.reshape(
            SCALE, SCALE, 3
        )
