"""Paired glyph storage that preserves the original font metrics.

The binary signature and per-slot selection flags occupy unused pixels above
the glyphs. Explicit key/ink anchors let native recolored copies carry the same
bits. Padded single-row banks and complete multi-row atlas halves have distinct
signatures; recognizing storage does not approve a reconstruction recipe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from gk3hd.textures.upscale.fonts.atlas import FONT_ATLAS_COLOR_SIZES, SCALE

if TYPE_CHECKING:
    from collections.abc import Sequence

    from PIL.Image import Image

FONT_BANK_SIGNATURE: Final = b"GK3BANK2"
FONT_ROW_BANK_SIGNATURE: Final = b"GK3ROWS1"
FONT_BANK_METADATA_ROW: Final = 2
FONT_BANK_KEY_ANCHOR: Final = (1, 1)
FONT_BANK_INK_ANCHOR: Final = (2, 1)
MAX_PADDED_FONT_GLYPHS: Final = 256
_SIGNATURE_BITS: Final = tuple(
    bool(byte & (1 << bit)) for byte in FONT_BANK_SIGNATURE for bit in range(7, -1, -1)
)


@dataclass(frozen=True, slots=True)
class FontRowBankLayout:
    """Two complete atlas halves with parser metadata only in the reference half."""

    source_size: tuple[int, int]
    line_count: int
    glyph_count: int

    @property
    def bank_distance(self) -> int:
        """Physical horizontal distance between corresponding glyph samples."""
        return self.source_size[0] * SCALE

    @property
    def image_size(self) -> tuple[int, int]:
        """Retain the original number and height of marker rows."""
        return self.bank_distance * 2, self.source_size[1] * SCALE


# Storage support is not a reconstruction recipe or an analysis routing rule.
FONT_ROW_BANK_LAYOUTS: Final = {
    "SID_EMB_10.BMP": FontRowBankLayout((515, 39), 3, 181),
    "SID_EMB_11.BMP": FontRowBankLayout((538, 45), 3, 181),
    "SID_EMB_22.BMP": FontRowBankLayout((514, 162), 6, 181),
    "SID_EMB_28.BMP": FontRowBankLayout((525, 224), 7, 181),
    "SID_NO_EMB_10.BMP": FontRowBankLayout((516, 39), 3, 181),
    "SID_NO_EMB_11.BMP": FontRowBankLayout((540, 45), 3, 181),
    "SID_NO_EMB_18.BMP": FontRowBankLayout((518, 115), 5, 181),
    "COURIER_B_14.BMP": FontRowBankLayout((489, 66), 3, 181),
    "COURIER_I_14.BMP": FontRowBankLayout((523, 66), 3, 181),
    "COURIER_B_I_14.BMP": FontRowBankLayout((545, 66), 3, 181),
    "F_NUM_TLARGE.BMP": FontRowBankLayout((116, 21), 1, 10),
    "F_DODGENBURN16.BMP": FontRowBankLayout((269, 57), 3, 93),
    "F_CAPTION_GOUDY14AA.BMP": FontRowBankLayout((1485, 18), 1, 181),
    "TIMES_B_14.BMP": FontRowBankLayout((522, 72), 4, 181),
    "RC_GOUDY12.BMP": FontRowBankLayout((1294, 16), 1, 181),
    "F_ARIAL_A12.BMP": FontRowBankLayout((835, 17), 1, 94),
    "SID_TEXT_14.BMP": FontRowBankLayout((517, 48), 3, 181),
    "SID_TEXT_18.BMP": FontRowBankLayout((527, 57), 3, 181),
    "SID_TEXT_22.BMP": FontRowBankLayout((518, 100), 4, 181),
    "SID_CAP_20.BMP": FontRowBankLayout((513, 108), 4, 181),
    "SID_CAP_16.BMP": FontRowBankLayout((426, 84), 4, 181),
    "SID_CAP_26.BMP": FontRowBankLayout((648, 136), 4, 181),
    "SID_PDN_10.BMP": FontRowBankLayout((512, 36), 3, 181),
    "SID_PDN_12.BMP": FontRowBankLayout((517, 42), 3, 180),
    "SID_PDN_16.BMP": FontRowBankLayout((514, 57), 3, 149),
    "F_TEMPUS_A10.BMP": FontRowBankLayout((183, 64), 4, 94),
    "COURIER_R_12.BMP": FontRowBankLayout((455, 48), 3, 181),
    "COURIER_R_14.BMP": FontRowBankLayout((489, 51), 3, 181),
    "COURIER_B_12.BMP": FontRowBankLayout((467, 48), 3, 181),
    "COURIER_I_12.BMP": FontRowBankLayout((517, 48), 3, 181),
    "COURIER_B_I_12.BMP": FontRowBankLayout((522, 45), 3, 181),
    "F_TIMES_R_I_12.BMP": FontRowBankLayout((491, 51), 3, 181),
    "TIMES_R_12.BMP": FontRowBankLayout((485, 48), 3, 181),
    "TIMES_B_12.BMP": FontRowBankLayout((507, 51), 3, 181),
    "TIMES_B_U_12.BMP": FontRowBankLayout((507, 51), 3, 181),
    "TIMES_R_U_12.BMP": FontRowBankLayout((485, 48), 3, 181),
    "TIMES_R_14.BMP": FontRowBankLayout((499, 57), 3, 181),
    "TIMES_R_U_14.BMP": FontRowBankLayout((499, 57), 3, 181),
    "TIMES_B_U_14.BMP": FontRowBankLayout((522, 54), 3, 181),
}


def font_row_bank_layout(name: str) -> FontRowBankLayout | None:
    """Return only the verified resource's paired full-atlas storage contract."""
    # These resources have identical verified marker geometry. Keep one runtime
    # geometry-table entry; the color bank carries the signature for both planes.
    name = {
        "SID_EMB_18.BMP": "SID_NO_EMB_18.BMP",
        "SID_NO_EMB_14.BMP": "TIMES_B_14.BMP",
        "F_TEMPUS_10.BMP": "F_TEMPUS_A10.BMP",
        "F_TEMPUS_10_ALPHA.BMP": "F_TEMPUS_A10.BMP",
        "F_DODGENBURN16_ALPHA.BMP": "F_DODGENBURN16.BMP",
        "F_CAPTION_GOUDY14AA_ALPHA.BMP": "F_CAPTION_GOUDY14AA.BMP",
    }.get(name.upper(), name.upper())
    # Companion opacity shares its primary's physical bank layout, but no
    # signature pixels or RGB565 encoding. Only registered primary names match.
    if name not in FONT_ROW_BANK_LAYOUTS and name.endswith("A.BMP"):
        name = name[:-5] + ".BMP"
    return FONT_ROW_BANK_LAYOUTS.get(name)


def _row_image_layout(image: Image) -> FontRowBankLayout | None:
    return next(
        (layout for layout in FONT_ROW_BANK_LAYOUTS.values() if image.size == layout.image_size),
        None,
    )


def stamp_font_row_bank(
    image: Image, *, key: tuple[int, int, int], ink: tuple[int, int, int]
) -> None:
    """Mark the verified row-bank storage without touching glyphs or marker rows."""
    layout = _row_image_layout(image)
    if image.mode != "RGB" or layout is None or key == ink:
        msg = "row-bank metadata requires verified geometry and distinct RGB anchors"
        raise ValueError(msg)
    start = layout.bank_distance
    image.putpixel((start + 1, 1), key)
    image.putpixel((start + 2, 1), ink)
    bits = (bool(byte & (1 << bit)) for byte in FONT_ROW_BANK_SIGNATURE for bit in range(7, -1, -1))
    for x, bit in enumerate(bits, start=start + 1):
        image.putpixel((x, FONT_BANK_METADATA_ROW), ink if bit else key)


def has_font_row_bank(image: Image) -> bool:
    """Recognize signed row storage, including recolored key/ink copies."""
    layout = _row_image_layout(image)
    if image.mode != "RGB" or layout is None:
        return False
    start = layout.bank_distance
    key = image.getpixel((start + 1, 1))
    ink = image.getpixel((start + 2, 1))
    if key == ink:
        return False
    bits = (bool(byte & (1 << bit)) for byte in FONT_ROW_BANK_SIGNATURE for bit in range(7, -1, -1))
    return all(
        image.getpixel((x, FONT_BANK_METADATA_ROW)) == (ink if bit else key)
        for x, bit in enumerate(bits, start=start + 1)
    )


@dataclass(frozen=True, slots=True)
class FontBankLayout:
    """One verified single-row font's logical storage geometry, before 4x scaling."""

    source_size: tuple[int, int]
    max_advance: int
    glyph_count: int = 94

    def __post_init__(self) -> None:
        """Reject layouts that cannot hold their glyphs or metadata strip."""
        width, height = self.source_size
        if (
            self.max_advance <= 0
            or self.glyph_count <= 0
            or self.glyph_count > MAX_PADDED_FONT_GLYPHS
            or height <= 1
            or width - 1 < self.max_advance + 2
            or width * SCALE <= len(_SIGNATURE_BITS) + self.glyph_count
        ):
            msg = "font bank layout cannot hold its glyphs and metadata"
            raise ValueError(msg)

    @property
    def columns(self) -> int:
        """Keep column zero free for original parser metadata."""
        return (self.source_size[0] - 1) // (self.max_advance + 2)

    @property
    def bank_distance(self) -> int:
        """Physical row offset between identically laid-out raster/outline banks."""
        rows = (self.glyph_count + self.columns - 1) // self.columns
        return rows * (self.source_size[1] + 1) * SCALE

    @property
    def image_size(self) -> tuple[int, int]:
        """Keep the original header and separate reference/large-draw artwork."""
        width, height = self.source_size
        return width * SCALE, height * SCALE + 2 * self.bank_distance

    def glyph_rect(self, index: int, advance: int) -> tuple[int, int, int, int]:
        """Locate full padded ink without changing its logical text advance."""
        if not 0 <= index < self.glyph_count or not 0 < advance <= self.max_advance:
            msg = "font bank glyph index or advance is outside its verified layout"
            raise ValueError(msg)
        left = 1 + (index % self.columns) * (self.max_advance + 2)
        top = self.source_size[1] + (index // self.columns) * (self.source_size[1] + 1)
        return left, top, left + advance + 2, top + self.source_size[1] + 1


FONT_PADDED_BANK_LAYOUTS: Final = {
    name: FontBankLayout(FONT_ATLAS_COLOR_SIZES[name], advance, count)
    for name, advance, count in (
        ("F_ARIAL_T8.BMP", 12, 94),
        ("F_ARIAL_T10.BMP", 14, 94),
        ("F_ARIAL_T12.BMP", 16, 94),
        ("F_SSERIF_T8.BMP", 12, 96),
        ("F_SSERIF_T8B.BMP", 13, 96),
        ("F_TOOLTIP.BMP", 14, 180),
    )
}


def font_bank_layout(name: str) -> FontBankLayout | None:
    """Resolve only the verified single-row padded storage layouts."""
    return FONT_PADDED_BANK_LAYOUTS.get(name.upper())


def write_font_bank_flags(image: Image, layout: FontBankLayout, flags: Sequence[bool]) -> None:
    """Stamp storage selection, preserving marker rows and all visible artwork."""
    if image.mode != "RGB" or image.size != layout.image_size:
        msg = "font bank metadata requires its exact RGB storage dimensions"
        raise ValueError(msg)
    if len(flags) != layout.glyph_count or any(not isinstance(flag, bool) for flag in flags):
        msg = "font bank metadata requires one boolean for each glyph slot"
        raise ValueError(msg)
    key, ink = image.getpixel((0, 0)), image.getpixel((0, 1))
    if key is None or ink is None or key == ink:
        msg = "font bank key and replacement ink must be distinct"
        raise ValueError(msg)
    image.putpixel(FONT_BANK_KEY_ANCHOR, key)
    image.putpixel(FONT_BANK_INK_ANCHOR, ink)
    for x, bit in enumerate((*_SIGNATURE_BITS, *flags), start=1):
        image.putpixel((x, FONT_BANK_METADATA_ROW), ink if bit else key)


def read_font_bank_flags(image: Image, layout: FontBankLayout) -> tuple[bool, ...] | None:
    """Reject wrong geometry, unknown signatures and nonbinary metadata pixels."""
    if image.mode != "RGB" or image.size != layout.image_size:
        return None
    key, ink = image.getpixel(FONT_BANK_KEY_ANCHOR), image.getpixel(FONT_BANK_INK_ANCHOR)
    if key == ink:
        return None
    count = len(_SIGNATURE_BITS) + layout.glyph_count
    pixels = tuple(image.getpixel((x, FONT_BANK_METADATA_ROW)) for x in range(1, count + 1))
    if any(pixel not in (key, ink) for pixel in pixels):
        return None
    bits = tuple(pixel == ink for pixel in pixels)
    if bits[: len(_SIGNATURE_BITS)] != _SIGNATURE_BITS:
        return None
    return bits[len(_SIGNATURE_BITS) :]
