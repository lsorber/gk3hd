"""Reconstruct SIDNEY bevel artwork without substituting glyphs or font metrics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

from gk3hd.textures.upscale.fonts.atlas import SCALE, font_atlas_recipe, parse_glyph_cells
from gk3hd.textures.upscale.fonts.bank import font_row_bank_layout, stamp_font_row_bank
from gk3hd.textures.upscale.fonts.color import conserve_sidney_color, validate_plain_color_font
from gk3hd.textures.upscale.fonts.coverage import reconstruct_font_coverage

if TYPE_CHECKING:
    from pathlib import Path

    from numpy.typing import NDArray

    from gk3hd.textures.upscale.fonts.atlas import FontAtlasRecipe

_COMPANIONS: Final = {
    "SID_EMB_10.BMP": "SID_NO_EMB_10.BMP",
    "SID_EMB_11.BMP": "SID_NO_EMB_11.BMP",
    "SID_EMB_18.BMP": "SID_NO_EMB_18.BMP",
}
_KEY: Final = (172, 125, 49)
_MARKER: Final = (255, 255, 255)
_KEY_CODES: Final = np.array([21, 31, 6])
_DIRECTION: Final = np.array([7, 15, 7]) - _KEY_CODES
_SHIFTS: Final = np.array([3, 2, 3], dtype=np.uint8)
_PADDING: Final = 2
_OPAQUE: Final = 0.999
# These sizes have no plain companion. Reconstruct their RGB samples directly;
# do not infer a letter mask from the ambiguous relationship between color/alpha.
_COLOR_BASELINES: Final = {"SID_EMB_22.BMP": 18, "SID_EMB_28.BMP": 22}
_COLOR_MAXIMA: Final = (28, 44, 9)
_SHADE_LIMITS: Final = {
    "SID_EMB_10.BMP": (31, 47, 16),
    "SID_EMB_11.BMP": (31, 47, 16),
    "SID_EMB_18.BMP": (28, 44, 10),
}
# These authored glyphs do not share their plain sibling's edge coverage:
# the 10-size sharp-s/diaeresis have different solid ink; the others imply
# impossible lighting. Keep source samples, not a guessed replacement outline.
_RETAINED_GLYPHS: Final = {
    "SID_EMB_10.BMP": frozenset(b"oq2\xdf\xef"),
    "SID_EMB_11.BMP": frozenset(b"EH"),
}


def reconstruct_embossed_font(
    source: Path, original: Image.Image, reference: Image.Image, recipe: FontAtlasRecipe
) -> Image.Image:
    """Retain native artwork; enlarge the verified black-ink/gold-shading source.

    The plain companion supplies the letter mask, not substitute glyphs. Black
    pixels must match fully covered companion pixels exactly. Shading is inferred
    only where visible, interpolated behind opaque ink, and finally constrained
    to the original RGB565 block sums and key mask. No descriptor is rewritten.
    The two larger sizes instead use direct, source-constrained color interpolation.
    """
    if recipe.primary in _COLOR_BASELINES:
        return _reconstruct_direct_color(original, reference, recipe)
    companion_name = _COMPANIONS.get(recipe.primary)
    layout = font_row_bank_layout(recipe.primary)
    plain_recipe = font_atlas_recipe(companion_name) if companion_name is not None else None
    if companion_name is None or layout is None or plain_recipe is None:
        msg = f"{recipe.primary}: no verified embossed-font recipe"
        raise ValueError(msg)
    companion = source.with_name(companion_name)
    if not companion.is_file():
        msg = f"{recipe.primary}: font matte companion is missing: {companion_name}"
        raise ValueError(msg)
    with Image.open(companion) as image:
        plain = image.convert("RGB")
    plain_cells = validate_plain_color_font(plain, plain_recipe)
    if original.size != layout.source_size or original.height != plain.height:
        msg = f"{recipe.primary}: embossed font dimensions differ from its verified layout"
        raise ValueError(msg)
    old, matte = np.asarray(original), np.asarray(plain)
    stride = original.height // recipe.line_count
    cells = parse_glyph_cells(original, recipe)
    if (
        not np.array_equal(old[:, 0], matte[:, 0])
        or not np.all(
            np.all(old[::stride, 1:] == _KEY, axis=2)
            | np.all(old[::stride, 1:] == (255, 255, 255), axis=2)
        )
        or (recipe.primary == "SID_EMB_18.BMP" and cells != plain_cells)
    ):
        msg = f"{recipe.primary}: embossed font and plain companion markers differ"
        raise ValueError(msg)
    candidate = reference.copy()
    mattes = {cell.character: cell for cell in plain_cells}
    for cell in cells:
        color = np.asarray(original.crop(cell.rect)) >> _SHIFTS
        mask = np.asarray(plain.crop(mattes[cell.character].rect)) >> _SHIFTS
        if recipe.primary == "SID_EMB_10.BMP" and cell.character == ord("%"):
            mask = _trim_percent_matte(mask, color.shape)
        if color.shape != mask.shape:
            msg = f"{recipe.primary}: companion dimensions differ for glyph {cell.character:#04x}"
            raise ValueError(msg)
        if cell.character in _RETAINED_GLYPHS.get(recipe.primary, ()):
            continue
        direction = (
            -_KEY_CODES
            if recipe.primary == "SID_EMB_11.BMP" and cell.character in (0xA9, 0xAE)
            else _DIRECTION
        )
        reconstructed = _reconstruct_glyph(color, mask, direction=direction, name=recipe.primary)
        candidate.paste(
            Image.fromarray(reconstructed), (cell.rect[0] * SCALE, cell.rect[1] * SCALE)
        )
    return _make_bank(reference, candidate, recipe)


def _make_bank(
    reference: Image.Image, candidate: Image.Image, recipe: FontAtlasRecipe
) -> Image.Image:
    layout = font_row_bank_layout(recipe.primary)
    if layout is None:
        msg = f"{recipe.primary}: no verified embossed-font storage"
        raise ValueError(msg)
    stride = layout.source_size[1] // recipe.line_count
    bank = Image.new("RGB", layout.image_size, _KEY)
    bank.paste(reference)
    bank.paste(candidate, (layout.bank_distance, 0))
    for row in range(layout.line_count):
        top = row * stride * SCALE
        bank.paste(_KEY, (layout.bank_distance, top, bank.width, top + 1))
    stamp_font_row_bank(bank, key=_KEY, ink=(255, 255, 255))
    return bank


def _reconstruct_direct_color(
    original: Image.Image, reference: Image.Image, recipe: FontAtlasRecipe
) -> Image.Image:
    """Interpolate the actual bevel colors, preserving every native pixel average."""
    layout = font_row_bank_layout(recipe.primary)
    baseline = _COLOR_BASELINES[recipe.primary]
    if (
        layout is None
        or original.size != layout.source_size
        or [y for y in range(original.height) if original.getpixel((0, y)) != _KEY] != [baseline]
        or original.getpixel((0, baseline)) != (255, 255, 255)
    ):
        msg = f"{recipe.primary}: source does not match the verified color-font layout"
        raise ValueError(msg)
    pixels = np.asarray(original)
    markers = pixels[:: original.height // recipe.line_count, 1:]
    if not np.all(np.all(markers == _KEY, axis=2) | np.all(markers == _MARKER, axis=2)):
        msg = f"{recipe.primary}: unexpected color-font marker colors"
        raise ValueError(msg)
    candidate = reference.copy()
    for cell in parse_glyph_cells(original, recipe):
        old = np.asarray(original.crop(cell.rect)) >> _SHIFTS
        if np.any(old > _COLOR_MAXIMA):
            msg = f"{recipe.primary}: color shading is outside the verified source range"
            raise ValueError(msg)
        proposal = _interpolate_color(old).astype(np.float64)
        candidate.paste(
            Image.fromarray(conserve_sidney_color(old, proposal)),
            (cell.rect[0] * SCALE, cell.rect[1] * SCALE),
        )
    return _make_bank(reference, candidate, recipe)


def _interpolate_color(values: NDArray[np.uint8] | NDArray[np.float64]) -> NDArray[np.float32]:
    """Keep neighboring glyphs and atlas markers outside the interpolation footprint."""
    margin = _PADDING * SCALE
    size = ((values.shape[1] + 2 * _PADDING) * SCALE, (values.shape[0] + 2 * _PADDING) * SCALE)
    channels = []
    for channel in range(3):
        padded = np.pad(
            values[..., channel].astype(np.float32), _PADDING, constant_values=_KEY_CODES[channel]
        )
        interpolated = Image.fromarray(padded).resize(size, Image.Resampling.BICUBIC)
        channels.append(np.asarray(interpolated)[margin:-margin, margin:-margin])
    return np.stack(channels, axis=-1)


def _trim_percent_matte(mask: NDArray[np.uint8], shape: tuple[int, ...]) -> NDArray[np.uint8]:
    """Drop only the verified blank column; never resize or crop actual ink."""
    if mask.shape != (shape[0], shape[1] + 1, 3) or not np.all(mask[:, -1] == _KEY_CODES):
        msg = "SID_EMB_10.BMP: percent companion must have one extra blank right column"
        raise ValueError(msg)
    return mask[:, :-1]


def _reconstruct_glyph(
    old: NDArray[np.uint8],
    plain: NDArray[np.uint8],
    *,
    direction: NDArray[np.int64],
    name: str,
) -> NDArray[np.uint8]:
    alpha = np.clip((plain.astype(float) - _KEY_CODES) @ direction / (direction @ direction), 0, 1)
    opaque = alpha >= _OPAQUE
    if not np.array_equal(opaque, np.all(old == 0, axis=2)):
        msg = f"{name}: black ink and plain companion coverage disagree"
        raise ValueError(msg)
    shade = old.astype(float) / np.maximum(1 - alpha, 0.001)[..., None]
    if np.any(shade > _SHADE_LIMITS[name]):
        msg = f"{name}: color shading is outside the verified source range"
        raise ValueError(msg)
    if opaque.all():
        shade[:] = _KEY_CODES
    elif opaque.any():
        indices = distance_transform_edt(opaque, return_distances=False, return_indices=True)
        shade = shade[tuple(indices)]
    quantized = np.rint(alpha * 255).astype(np.uint8)
    coverage = reconstruct_font_coverage(np.pad(quantized, _PADDING), bit_depth=8)
    margin = _PADDING * SCALE
    coverage = coverage[margin:-margin, margin:-margin].astype(float) / 255
    proposed = _interpolate_color(shade) * (1 - coverage[..., None])
    return conserve_sidney_color(old, proposed)
