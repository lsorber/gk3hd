"""Repair verified shipped atlas layout errors without inventing glyph artwork."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING, Final

from PIL import Image

if TYPE_CHECKING:
    from gk3hd.textures.upscale.fonts.atlas import FontAtlasRecipe

TIMES_ITALIC: Final = "F_TIMES_R_I_12.BMP"
CAPTION_16: Final = "SID_CAP_16.BMP"
TIMES_BOLD_UNDERLINE_14: Final = "TIMES_B_U_14.BMP"
TIMES_BOLD_UNDERLINE_12: Final = "TIMES_B_U_12.BMP"
TIMES_BOLD_14: Final = "TIMES_B_14.BMP"
_TIMES_BOLD_ROWS: Final = 4
_TIMES_BOLD_BASELINE: Final = 13
_TIMES_SMALL_UNDERLINE_ROWS: Final = ((0, 504, 64), (17, 505, 74), (34, 303, 42))
_TIMES_REGULAR_UNDERLINE_ROWS: Final = ((0, 497, 59), (19, 497, 70), (38, 415, 52))
_TIMES_REGULAR_UNDERLINE_BASELINE: Final = 13
_TIMES_UNDERLINE_ROWS: Final = ((0, 520, 59), (18, 520, 72), (36, 414, 50))
_TIMES_UNDERLINE_GLYPHS: Final = 181
_TIMES_PUNCTUATION_ROW: Final = 18
_CAPTION_ROWS: Final = ((0, 1, 415, 39), (21, 1, 425, 53), (42, 0, 417, 45), (63, 0, 421, 44))
_CAPTION_HEIGHT: Final = 21
_CAPTION_SIZE: Final = (426, 84)
_CAPTION_BASELINE: Final = 16
_CAPTION_GLYPHS: Final = 181
_BLACK: Final = (0, 0, 0)
_RED: Final = (255, 0, 0)
_SIZE: Final = (491, 51)
_KEY: Final = (255, 0, 255)
_INK: Final = (255, 255, 255)
_SOURCE_ROWS: Final = (0, 16, 32)
_ART_HEIGHT: Final = 15
_ROW_HEIGHT: Final = 17
_FALLBACK: Final = 0x9D
_SPACE: Final = 0x20
_GLYPHS: Final = 180


@dataclass(frozen=True, slots=True)
class CourierLayout:
    """Reviewed atlas size and each row's first marker, last marker and cell count."""

    size: tuple[int, int]
    rows: tuple[tuple[int, int, int], ...]


COURIER_LAYOUTS: Final = {
    "COURIER_R_12.BMP": CourierLayout((455, 48), ((1, 450, 63), (1, 454, 76), (1, 309, 43))),
    "COURIER_B_12.BMP": CourierLayout((467, 48), ((1, 464, 63), (1, 460, 71), (1, 371, 48))),
    "COURIER_B_14.BMP": CourierLayout(
        (481, 68), ((1, 479, 56), (1, 471, 67), (1, 479, 56), (2, 28, 3))
    ),
    "COURIER_I_14.BMP": CourierLayout(
        (522, 68), ((1, 520, 57), (1, 520, 69), (1, 520, 58), (1, 520, 3))
    ),
    "COURIER_B_I_14.BMP": CourierLayout(
        (528, 68), ((1, 527, 57), (1, 527, 66), (1, 527, 56), (1, 61, 6))
    ),
    "COURIER_I_12.BMP": CourierLayout((517, 48), ((1, 510, 63), (1, 515, 74), (1, 364, 45))),
    "COURIER_B_I_12.BMP": CourierLayout((522, 45), ((1, 518, 63), (1, 520, 71), (1, 408, 48))),
    "COURIER_R_14.BMP": CourierLayout((489, 51), ((1, 487, 56), (0, 484, 72), (0, 469, 54))),
}
_COURIER_JOIN_SLOT: Final = 148
_COURIER_CHARACTER_COUNT: Final = 181
_SHARP_S: Final = 0xDF
_COURIER_ITALIC_14: Final = "COURIER_I_14.BMP"
_COURIER_ITALIC_REFLOWS: Final = frozenset({_COURIER_ITALIC_14, "COURIER_B_I_14.BMP"})
_COURIER_REFLOWS: Final = {
    "COURIER_B_14.BMP": ((489, 66), 12),
    _COURIER_ITALIC_14: ((523, 66), 13),
    "COURIER_B_I_14.BMP": ((545, 66), 12),
}
_COURIER_REFLOW_HEIGHT: Final = 22
_COURIER_DESCRIPTOR_ROWS: Final = 3
_COURIER_FINAL_ROW: Final = 51
_COURIER_STRAY_ROW: Final = 34
_COURIER_NOISY_BOUNDARIES: Final = frozenset({(519, 0), (520, 17), (520, 34), (520, 51)})


def repair_times_underline_layout(color: Image.Image, recipe: FontAtlasRecipe) -> Image.Image:
    """Correct independently verified marker defects in the two underlined sizes.

    The smaller atlas joins nine and space and misplaces the i/j boundary.
    The larger joins braces and splits a quotation mark. Move only marker
    pixels; all glyph artwork, opacity samples and total advances stay intact.
    """
    if recipe.primary == TIMES_BOLD_UNDERLINE_12:
        return _repair_times_small_underline_layout(color, recipe)
    return _repair_times_large_punctuation_layout(color, recipe)


def _repair_times_large_punctuation_layout(
    color: Image.Image, recipe: FontAtlasRecipe
) -> Image.Image:
    """Both large bold sources share the same independently verified markers."""
    if (
        recipe.primary not in {TIMES_BOLD_UNDERLINE_14, TIMES_BOLD_14}
        or color.mode != "RGB"
        or color.size != (522, 54)
        or recipe.line_count != (_TIMES_BOLD_ROWS if recipe.primary == TIMES_BOLD_14 else 3)
        or len(recipe.characters) != _TIMES_UNDERLINE_GLYPHS
        or recipe.characters[80:87] != b"{}|;':\""
    ):
        msg = f"{recipe.primary}: source does not match the verified punctuation layout repair"
        raise ValueError(msg)
    for top, last, count in _TIMES_UNDERLINE_ROWS:
        markers = [x for x in range(1, color.width) if color.getpixel((x, top)) != _KEY]
        if (
            len(markers) != count + 1
            or markers[0] != 1
            or markers[-1] != last
            or any(color.getpixel((x, top)) != _INK for x in markers)
            or (
                top == _TIMES_PUNCTUATION_ROW
                and markers[21:29] != [154, 164, 166, 170, 173, 176, 179, 183]
            )
        ):
            msg = f"{recipe.primary}: invalid authored punctuation row markers"
            raise ValueError(msg)
    repaired = color.copy()
    repaired.putpixel((159, 18), _INK)
    repaired.putpixel((179, 18), _KEY)
    return repaired


def repair_times_bold_layout(
    color: Image.Image, opacity: Image.Image, recipe: FontAtlasRecipe
) -> tuple[Image.Image, Image.Image]:
    """Preserve three authored rows inside the shipped four-row descriptor.

    Add one empty, explicitly terminated row. A completely unmarked empty row
    makes the retail parser decrement its character count and lose the final
    glyph. No glyph samples, opacity, advances or descriptor bytes are changed.
    """
    if (
        recipe.primary != TIMES_BOLD_14
        or recipe.line_count != _TIMES_BOLD_ROWS
        or recipe.coverage_baseline != _TIMES_BOLD_BASELINE
        or color.size != (522, 54)
        or opacity.size != color.size
        or color.mode != "RGB"
        or opacity.mode != "L"
        or any(color.getpixel((0, y)) != (_INK if y in (1, 13) else _KEY) for y in range(54))
    ):
        msg = f"{recipe.primary}: source does not match the verified font recipe for row padding"
        raise ValueError(msg)
    repaired = Image.new("RGB", (522, 72), _KEY)
    repaired.paste(_repair_times_large_punctuation_layout(color, recipe))
    repaired.putpixel((1, 54), _INK)
    alpha = Image.new("L", repaired.size)
    alpha.paste(opacity)
    return repaired, alpha


def repair_times_replacement_anchor(color: Image.Image, recipe: FontAtlasRecipe) -> Image.Image:
    """Restore the missing ink-color metadata without modifying any glyph samples.

    The large regular underline source names its transparent key as replacement
    ink, so tint requests leave white letters unchanged. The shipped white
    descriptor renders identically after restoring this one metadata pixel.
    """
    if (
        recipe.primary != "TIMES_R_U_14.BMP"
        or recipe.line_count != len(_TIMES_REGULAR_UNDERLINE_ROWS)
        or len(recipe.characters) != _TIMES_UNDERLINE_GLYPHS
        or recipe.coverage_baseline != _TIMES_REGULAR_UNDERLINE_BASELINE
        or color.mode != "RGB"
        or color.size != (499, 57)
        or any(
            color.getpixel((0, y)) != (_INK if y == _TIMES_REGULAR_UNDERLINE_BASELINE else _KEY)
            for y in range(color.height)
        )
    ):
        msg = f"{recipe.primary}: source does not match the verified font recipe for anchor repair"
        raise ValueError(msg)
    for top, last, count in _TIMES_REGULAR_UNDERLINE_ROWS:
        markers = [x for x in range(1, color.width) if color.getpixel((x, top)) != _KEY]
        if (
            len(markers) != count + 1
            or markers[0] != 1
            or markers[-1] != last
            or any(color.getpixel((x, top)) != _INK for x in markers)
        ):
            msg = f"{recipe.primary}: row markers do not match the verified font recipe"
            raise ValueError(msg)
    repaired = color.copy()
    repaired.putpixel((0, 1), _INK)
    return repaired


def _repair_times_small_underline_layout(
    color: Image.Image, recipe: FontAtlasRecipe
) -> Image.Image:
    """Restore the missing space boundary and the authored i/j advances."""
    if (
        color.mode != "RGB"
        or color.size != (507, 51)
        or recipe.line_count != len(_TIMES_SMALL_UNDERLINE_ROWS)
        or len(recipe.characters) != _TIMES_UNDERLINE_GLYPHS
        or recipe.characters[34:36] != b"ij"
        or recipe.characters[61:65] != b"9 !@"
    ):
        msg = f"{recipe.primary}: source does not match the verified small underline layout repair"
        raise ValueError(msg)
    for top, last, count in _TIMES_SMALL_UNDERLINE_ROWS:
        markers = [x for x in range(1, color.width) if color.getpixel((x, top)) != _KEY]
        if (
            len(markers) != count + 1
            or markers[0] != 1
            or markers[-1] != last
            or any(color.getpixel((x, top)) != _INK for x in markers)
            or (top == 0 and markers[34:37] != [296, 301, 305])
            or (top == 0 and markers[60:65] != [469, 476, 489, 492, 504])
        ):
            msg = f"{recipe.primary}: invalid authored small underline row markers"
            raise ValueError(msg)
    repaired = color.copy()
    repaired.putpixel((300, 0), _INK)
    repaired.putpixel((301, 0), _KEY)
    repaired.putpixel((482, 0), _INK)
    return repaired


def repair_courier_layout(
    color: Image.Image, opacity: Image.Image, recipe: FontAtlasRecipe
) -> tuple[Image.Image, Image.Image]:
    """Keep the authored two-s spelling in one sharp-s character slot.

    The shipped marker tables split that spelling into two cells although the
    descriptor has one byte for it. Joining their rectangles restores all later
    accented letters, including the final y-diaeresis. R14 also has two rows in
    the reserved first column; shift those rows together in both planes first.
    No character artwork is discarded, redrawn or fitted to a different width.
    """
    layout = COURIER_LAYOUTS.get(recipe.primary)
    if (
        layout is None
        or color.size != layout.size
        or opacity.size != color.size
        or color.mode != "RGB"
        or opacity.mode != "L"
        or recipe.line_count != _COURIER_DESCRIPTOR_ROWS
        or len(recipe.characters) != _COURIER_CHARACTER_COUNT
        or recipe.characters[_COURIER_JOIN_SLOT] != _SHARP_S
    ):
        msg = f"{recipe.primary}: source does not match the verified Courier layout repair"
        raise ValueError(msg)
    repaired, alpha = color.copy(), opacity.copy()
    height = color.height // len(layout.rows)
    rectangles: list[tuple[int, int, int, int]] = []
    for row, (first, last, count) in enumerate(layout.rows):
        top = row * height
        markers = [x for x in range(color.width) if color.getpixel((x, top)) != _KEY]
        if (
            len(markers) != count + 1
            or markers[0] != first
            or markers[-1] != last
            or not _valid_courier_markers(color, opacity, markers, top, recipe)
        ):
            msg = f"{recipe.primary}: invalid authored Courier row markers"
            raise ValueError(msg)
        if first == 0:
            _shift_courier_row(repaired, alpha, top, height)
            markers = [x + 1 for x in markers]
        if recipe.primary in _COURIER_ITALIC_REFLOWS:
            markers = _repair_courier_italic_markers(color, opacity, markers, top, recipe)
        rectangles.extend((a, top + 1, b, top + height) for a, b in pairwise(markers))
    left, right = rectangles[_COURIER_JOIN_SLOT : _COURIER_JOIN_SLOT + 2]
    if left[1] != right[1] or left[2] != right[0]:
        msg = f"{recipe.primary}: sharp-s artwork does not occupy adjacent cells"
        raise ValueError(msg)
    repaired.putpixel((right[0], right[1] - 1), _KEY)
    if recipe.primary in _COURIER_REFLOWS:
        rectangles[_COURIER_JOIN_SLOT : _COURIER_JOIN_SLOT + 2] = [
            (left[0], left[1], right[2], right[3])
        ]
        return _reflow_courier(color, opacity, rectangles, recipe)
    return repaired, alpha


def _valid_courier_markers(
    color: Image.Image,
    opacity: Image.Image,
    markers: list[int],
    top: int,
    recipe: FontAtlasRecipe,
) -> bool:
    """Accept only authored white markers and four verified invisible key defects."""
    for x in markers:
        noisy = recipe.primary == _COURIER_ITALIC_14 and (x, top) in _COURIER_NOISY_BOUNDARIES
        expected = (255, 32, 255) if noisy else _INK
        if color.getpixel((x, top)) != expected or (noisy and opacity.getpixel((x, top))):
            return False
    return True


def _repair_courier_italic_markers(
    color: Image.Image,
    opacity: Image.Image,
    markers: list[int],
    top: int,
    recipe: FontAtlasRecipe,
) -> list[int]:
    """Remove verified empty trailing cells, not the genuine space character."""
    if top < _COURIER_FINAL_ROW:
        for y in range(top + 1, top + 17):
            for x in range(markers[-2], markers[-1]):
                if opacity.getpixel((x, y)) and color.getpixel((x, y)) != _KEY:
                    msg = f"{recipe.primary}: trailing cell repair would discard visible artwork"
                    raise ValueError(msg)
        markers = markers[:-1]
    if recipe.primary != _COURIER_ITALIC_14:
        return markers
    if top == _COURIER_STRAY_ROW:
        if [opacity.getpixel((x, top)) for x in (187, 189, 190, 197)] != [130, 117, 68, 130]:
            msg = "Courier italic stray markers do not match the verified source"
            raise ValueError(msg)
        markers = [x for x in markers if x not in (189, 190)]
    if top == _COURIER_FINAL_ROW:
        _validate_courier_italic_tail(opacity, markers)
        markers = [*markers[:-1], 31]
    return markers


def _validate_courier_italic_tail(opacity: Image.Image, markers: list[int]) -> None:
    """Recover the final y-diaeresis advance without clipping its rightmost ink.

    Its lower body exactly matches the adjacent accented y shifted right one
    pixel. Preserve that authored bearing and all eleven columns. The remaining
    malformed 500-column cell is fully transparent, including non-key RGB noise.
    """
    if (
        markers != [1, 11, 20, 520]
        or opacity.crop((31, 52, opacity.width, 68)).getbbox() is not None
        or any(opacity.getpixel((20, y)) for y in range(58, 68))
        or opacity.crop((21, 58, 31, 68)).tobytes() != opacity.crop((1, 58, 11, 68)).tobytes()
    ):
        msg = "Courier italic final glyph does not match the verified bearing repair"
        raise ValueError(msg)


def _reflow_courier(
    color: Image.Image,
    opacity: Image.Image,
    rectangles: list[tuple[int, int, int, int]],
    recipe: FontAtlasRecipe,
) -> tuple[Image.Image, Image.Image]:
    """Fit four artwork rows into three descriptor rows without squeezing glyphs.

    The retail reader divides 68 by three: preserve its 22-pixel row stride,
    21-pixel logical height and baseline. Wider storage accommodates all cells;
    each original advance and every color/opacity sample remain unchanged.
    """
    size, baseline = _COURIER_REFLOWS[recipe.primary]
    if recipe.coverage_baseline != baseline or any(
        color.getpixel((0, y)) != (_INK if y in (1, baseline) else _KEY)
        for y in range(color.height)
    ):
        msg = f"{recipe.primary}: source does not match the verified font recipe"
        raise ValueError(msg)
    repaired = Image.new("RGB", size, _KEY)
    alpha = Image.new("L", repaired.size)
    for y in (1, baseline):
        repaired.putpixel((0, y), _INK)
    row, left = 0, 1
    for rect in rectangles:
        width = rect[2] - rect[0]
        if left + width >= repaired.width:
            row, left = row + 1, 1
        if row >= recipe.line_count or left + width >= repaired.width:
            msg = f"{recipe.primary}: glyphs do not fit the verified repaired layout"
            raise ValueError(msg)
        top = row * _COURIER_REFLOW_HEIGHT
        repaired.paste(color.crop(rect), (left, top + 1))
        alpha.paste(opacity.crop(rect), (left, top + 1))
        repaired.putpixel((left, top), _INK)
        repaired.putpixel((left + width, top), _INK)
        left += width
    return repaired, alpha


def _shift_courier_row(color: Image.Image, opacity: Image.Image, top: int, height: int) -> None:
    """Reclaim column zero without losing visible color or opacity artwork."""
    bottom = top + height
    if any(color.getpixel((color.width - 1, y)) != _KEY for y in range(top, bottom)):
        msg = "Courier row repair would discard artwork"
        raise ValueError(msg)
    pixels = color.crop((0, top, color.width - 1, bottom))
    alpha = opacity.crop((0, top, color.width - 1, bottom))
    color.paste(_KEY, (0, top, color.width, bottom))
    opacity.paste(0, (0, top, color.width, bottom))
    color.paste(pixels, (1, top))
    opacity.paste(alpha, (1, top))


def repair_caption_layout(color: Image.Image, recipe: FontAtlasRecipe) -> Image.Image:
    """Move two misplaced marker rows off the reserved first column.

    The third and fourth authored rows start at x=0. GK3 scans from x=1,
    skipping their first cells (question mark and O-tilde) and mislabeling
    subsequent characters. Shift those rows one pixel right into verified
    unused space. No glyph samples, advances, baseline or dimensions change.
    This corrects the malformed source lookup, not the font's artwork.
    """
    if (
        recipe.primary != CAPTION_16
        or recipe.line_count != len(_CAPTION_ROWS)
        or len(recipe.characters) != _CAPTION_GLYPHS
        or color.size != _CAPTION_SIZE
        or color.mode != "RGB"
        or any(
            color.getpixel((0, y)) != (_RED if y == _CAPTION_BASELINE else _BLACK)
            for y in range(_CAPTION_HEIGHT * 2)
        )
    ):
        msg = f"{recipe.primary}: source does not match the verified caption layout repair"
        raise ValueError(msg)
    repaired = color.copy()
    for top, first, last, count in _CAPTION_ROWS:
        markers = [x for x in range(color.width) if color.getpixel((x, top)) != _BLACK]
        if (
            len(markers) != count + 1
            or markers[0] != first
            or markers[-1] != last
            or any(color.getpixel((x, top)) != _RED for x in markers)
        ):
            msg = f"{recipe.primary}: invalid authored caption row markers"
            raise ValueError(msg)
        if first == 0:
            bottom = top + _CAPTION_HEIGHT
            if color.crop((color.width - 1, top, color.width, bottom)).getbbox() is not None:
                msg = f"{recipe.primary}: caption row repair would discard artwork"
                raise ValueError(msg)
            repaired.paste(_BLACK, (0, top, color.width, bottom))
            repaired.paste(color.crop((0, top, color.width - 1, bottom)), (1, top))
    return repaired


def repair_times_italic_layout(
    color: Image.Image, opacity: Image.Image, recipe: FontAtlasRecipe
) -> tuple[Image.Image, Image.Image]:
    """Reflow the reviewed 180 authored cells into the descriptor's 181 slots.

    Artwork rows start at 0/16/32, whereas GK3 divides the 51-pixel atlas into
    three 17-pixel rows. The artwork also omits the descriptor's default slot.
    Copy every cell without resampling, add its original space for that slot,
    and preserve the original logical height, baseline and advances. Sources
    are never modified; this is deliberately not a heuristic atlas repair.
    """
    if (
        recipe.primary != TIMES_ITALIC
        or recipe.line_count != len(_SOURCE_ROWS)
        or len(recipe.characters) != _GLYPHS + 1
        or recipe.characters.count(_FALLBACK) != 1
        or color.size != _SIZE
        or opacity.size != _SIZE
        or color.mode != "RGB"
        or opacity.mode != "L"
        or any(
            color.getpixel((0, y)) != (_INK if y in (1, 12) else _KEY) for y in range(color.height)
        )
    ):
        msg = f"{recipe.primary}: source does not match the verified font layout repair"
        raise ValueError(msg)
    rectangles: list[tuple[int, int, int, int]] = []
    for row in _SOURCE_ROWS:
        boundaries = [x for x in range(1, color.width) if color.getpixel((x, row)) != _KEY]
        if (
            not boundaries
            or boundaries[0] != 1
            or any(color.getpixel((x, row)) != _INK for x in boundaries)
        ):
            msg = f"{recipe.primary}: invalid authored row markers"
            raise ValueError(msg)
        rectangles.extend((a, row + 1, b, row + 1 + _ART_HEIGHT) for a, b in pairwise(boundaries))
    if len(rectangles) != _GLYPHS:
        msg = f"{recipe.primary}: expected {_GLYPHS} authored glyph cells, got {len(rectangles)}"
        raise ValueError(msg)
    artwork = dict(zip(recipe.characters.replace(bytes([_FALLBACK]), b""), rectangles, strict=True))
    repaired = Image.new("RGB", _SIZE, _KEY)
    alpha = Image.new("L", _SIZE)
    for y in (1, 12):
        repaired.putpixel((0, y), _INK)
    row, left = 0, 1
    for character in recipe.characters:
        rect = artwork[_SPACE if character == _FALLBACK else character]
        width = rect[2] - rect[0]
        if left + width >= color.width:
            repaired.putpixel((left, row * _ROW_HEIGHT), _INK)
            row, left = row + 1, 1
        if row >= len(_SOURCE_ROWS) or left + width >= color.width:
            msg = f"{recipe.primary}: glyphs do not fit the verified repaired layout"
            raise ValueError(msg)
        repaired.putpixel((left, row * _ROW_HEIGHT), _INK)
        position = (left, row * _ROW_HEIGHT + 1)
        repaired.paste(color.crop(rect), position)
        alpha.paste(opacity.crop(rect), position)
        left += width
    repaired.putpixel((left, row * _ROW_HEIGHT), _INK)
    return repaired, alpha
