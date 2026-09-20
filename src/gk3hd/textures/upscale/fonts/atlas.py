"""Produce source-faithful 4x artwork for recognized GK3 font atlases.

GK3 stores glyph boundaries and row membership as colored pixels in each
atlas. Those control pixels stay one pixel wide; the executable patch maps
their enlarged coordinates back to the original logical metrics. Source-copy
fallbacks repeat each authored sample in a 4x4 block. Reviewed coverage and
color recipes instead preserve original samples in a reference bank and
reconstruct enlarged draws. Optional verified outline recipes are implemented
separately in font_outline; this module does not infer replacement typefaces.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Final

from PIL import Image

if TYPE_CHECKING:
    from collections.abc import Iterable

SCALE: Final = 4
FONT_OUTLINE_STAMP: Final = "gk3hd-font-outline"
# Verified RGB565 originals. Keep the exact source-density guard at installation;
# opacity companions and arbitrary replacements must retain their own encoding.
FONT_ATLAS_COLOR_SIZES: Final = {
    "SID_EMB_10.BMP": (515, 39),
    "SID_EMB_11.BMP": (538, 45),
    "SID_NO_EMB_10.BMP": (516, 39),
    "SID_NO_EMB_11.BMP": (540, 45),
    "SID_NO_EMB_14.BMP": (522, 72),
    "SID_EMB_18.BMP": (518, 115),
    "SID_EMB_22.BMP": (514, 162),
    "SID_EMB_28.BMP": (525, 224),
    "SID_NO_EMB_18.BMP": (518, 115),
    "TIMES_B_14.BMP": (522, 54),
    "SID_TEXT_14.BMP": (517, 48),
    "SID_TEXT_18.BMP": (527, 57),
    "SID_TEXT_22.BMP": (518, 100),
    "SID_CAP_20.BMP": (513, 108),
    "SID_CAP_16.BMP": (426, 84),
    "SID_CAP_26.BMP": (648, 136),
    "SID_PDN_10.BMP": (512, 36),
    "SID_PDN_12.BMP": (517, 42),
    "SID_PDN_16.BMP": (514, 57),
    "F_TEMPUS_A10.BMP": (183, 64),
    "F_TEMPUS_10.BMP": (183, 64),
    "F_TIMES_R_I_12.BMP": (491, 51),
    "F_ARIAL_T10.BMP": (642, 14),
    "F_ARIAL_T12.BMP": (835, 18),
    "F_ARIAL_A12.BMP": (835, 17),
    "F_ARIAL_T8.BMP": (540, 11),
    "F_CAPTION_GOUDY14.BMP": (1466, 17),
    "F_CAPTION_GOUDY14AA.BMP": (1485, 18),
    "F_CAPTION_GOUDY14DS.BMP": (1466, 18),
    "F_CAPTION_GOUDY18.BMP": (1764, 23),
    "F_SSERIF_T8.BMP": (553, 13),
    "F_SSERIF_T8B.BMP": (646, 13),
    "F_TOOLTIP.BMP": (1180, 18),
    "RC_GOUDY12.BMP": (1294, 16),
    "COURIER_B_12.BMP": (467, 48),
    "COURIER_B_14.BMP": (481, 68),
    "COURIER_I_14.BMP": (522, 68),
    "COURIER_B_I_14.BMP": (528, 68),
    "F_NUM_TLARGE.BMP": (116, 21),
    "F_DODGENBURN16.BMP": (269, 57),
    "COURIER_B_I_12.BMP": (522, 45),
    "COURIER_I_12.BMP": (517, 48),
    "COURIER_R_12.BMP": (455, 48),
    "COURIER_R_14.BMP": (489, 51),
    "TIMES_B_12.BMP": (507, 51),
    "TIMES_B_U_12.BMP": (507, 51),
    "TIMES_B_U_14.BMP": (522, 54),
    "TIMES_R_12.BMP": (485, 48),
    "TIMES_R_14.BMP": (499, 57),
    "TIMES_R_U_12.BMP": (485, 48),
    "TIMES_R_U_14.BMP": (499, 57),
}
_MINIMUM_ATLAS_HEIGHT: Final = 3
_MINIMUM_ROW_HEIGHT: Final = 2  # Marker row followed by at least one glyph row.
_ASCII_CHARACTERS = (
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 "
    b"!@#$%^&*()-=_+[]\\{}|;':\",./<>?\x9d"
)
# These byte slots are menu artwork, not Unicode Ø/Ú: the shipped atlases
# contain right/down submenu arrows followed by their default-character symbol.
# A future outline renderer must keep these authored symbols separate from text.
_SSERIF_CHARACTERS = _ASCII_CHARACTERS[:-1] + b"\xd8\xda\x9d"
_EXTENDED_CHARACTERS = _ASCII_CHARACTERS + bytes(
    (*range(0xA1, 0xB2), 0xB4, 0xB5, 0xB7, 0xB8, 0xBB, *range(0xBF, 0x100))
)


@dataclass(frozen=True, slots=True)
class FontAtlasRecipe:
    """Verified artwork labels and native marker geometry, not a descriptor rewrite."""

    primary: str
    characters: bytes
    line_count: int
    alpha: bool = False
    alpha_companion: str | None = None
    # The 1999 format specification requires an explicit end marker per row.
    # Some shipped single-row atlases instead end their final cell at the image
    # edge. This is a verified recipe exception, not a rule for all single rows.
    implicit_right_edge: bool = False
    # Explicitly reviewed separate-opacity reconstruction, not every alpha font.
    coverage_baseline: int | None = None
    # Some separate-opacity fonts additionally key away low-coverage pixels.
    # This threshold is a verified source contract, not an output alpha test.
    coverage_key_threshold: int = 0
    # Metadata color, not glyph ink: numeric indicators use a blue baseline.
    coverage_baseline_color: tuple[int, int, int] = (255, 255, 255)


@dataclass(frozen=True, slots=True)
class GlyphCell:
    """One original glyph's exact half-open source rectangle."""

    character: int
    rect: tuple[int, int, int, int]


_RECIPES: Final = {
    name: FontAtlasRecipe(name, characters, 1, implicit_right_edge=True)
    for name, characters in (
        ("F_ARIAL_T8.BMP", _ASCII_CHARACTERS),
        ("F_ARIAL_T10.BMP", _ASCII_CHARACTERS),
        ("F_ARIAL_T12.BMP", _ASCII_CHARACTERS),
        ("F_ARIAL_A12.BMP", _ASCII_CHARACTERS),
        ("F_SSERIF_T8.BMP", _SSERIF_CHARACTERS),
        ("F_SSERIF_T8B.BMP", _SSERIF_CHARACTERS),
    )
}
_RECIPES["SID_TEXT_14.BMP"] = FontAtlasRecipe("SID_TEXT_14.BMP", _EXTENDED_CHARACTERS, 3)
_RECIPES["SID_NO_EMB_18.BMP"] = FontAtlasRecipe("SID_NO_EMB_18.BMP", _EXTENDED_CHARACTERS, 5)
for _plain_name, _plain_rows in (
    ("SID_NO_EMB_10.BMP", 3),
    ("SID_NO_EMB_11.BMP", 3),
    ("SID_NO_EMB_14.BMP", 4),
):
    _RECIPES[_plain_name] = FontAtlasRecipe(_plain_name, _EXTENDED_CHARACTERS, _plain_rows)
_RECIPES["SID_EMB_18.BMP"] = FontAtlasRecipe("SID_EMB_18.BMP", _EXTENDED_CHARACTERS, 5)
_RECIPES["SID_EMB_22.BMP"] = FontAtlasRecipe("SID_EMB_22.BMP", _EXTENDED_CHARACTERS, 6)
_RECIPES["SID_EMB_28.BMP"] = FontAtlasRecipe("SID_EMB_28.BMP", _EXTENDED_CHARACTERS, 7)
_RECIPES["SID_EMB_11.BMP"] = FontAtlasRecipe("SID_EMB_11.BMP", _EXTENDED_CHARACTERS, 3)
_RECIPES["SID_EMB_10.BMP"] = FontAtlasRecipe("SID_EMB_10.BMP", _EXTENDED_CHARACTERS, 3)
_RECIPES["SID_TEXT_18.BMP"] = FontAtlasRecipe("SID_TEXT_18.BMP", _EXTENDED_CHARACTERS, 3)
_RECIPES["SID_TEXT_22.BMP"] = FontAtlasRecipe("SID_TEXT_22.BMP", _EXTENDED_CHARACTERS, 4)
_RECIPES["SID_CAP_20.BMP"] = FontAtlasRecipe("SID_CAP_20.BMP", _EXTENDED_CHARACTERS, 4)
_RECIPES["SID_CAP_16.BMP"] = FontAtlasRecipe("SID_CAP_16.BMP", _EXTENDED_CHARACTERS, 4)
_RECIPES["SID_CAP_26.BMP"] = FontAtlasRecipe("SID_CAP_26.BMP", _EXTENDED_CHARACTERS, 4)
_RECIPES["SID_PDN_10.BMP"] = FontAtlasRecipe("SID_PDN_10.BMP", _EXTENDED_CHARACTERS, 3)
# This is the drawn artwork map, not a replacement for the shipped descriptor.
# The original descriptor has an extra CF byte; preserve every physical cell
# and leave that runtime lookup unchanged, including its original FF fallback.
_RECIPES["SID_PDN_12.BMP"] = FontAtlasRecipe(
    "SID_PDN_12.BMP", _EXTENDED_CHARACTERS.replace(b"\xcf", b""), 3
)
# The 16-size artwork ends after capital thorn, followed by a small-cap
# y-diaeresis, not the descriptor's double-S. The remaining lowercase accents
# have no cells. Preserve the original lookup/fallback; these are artwork labels.
_RECIPES["SID_PDN_16.BMP"] = FontAtlasRecipe(
    "SID_PDN_16.BMP", _EXTENDED_CHARACTERS[:148] + b"\xff", 3
)
_RECIPES["F_TEMPUS_A10.BMP"] = FontAtlasRecipe("F_TEMPUS_A10.BMP", _ASCII_CHARACTERS, 4)

# This descriptor omits the logical-not byte present in the other extended
# tables. Preserve its authored 180 slots instead of shifting accented glyphs.
_RECIPES["F_TOOLTIP.BMP"] = FontAtlasRecipe(
    "F_TOOLTIP.BMP",
    _EXTENDED_CHARACTERS.replace(b"\xac", b""),
    1,
    implicit_right_edge=True,
)


def _register_paired_recipe(recipe: FontAtlasRecipe) -> None:
    """Register a color atlas and the alpha atlas parsed through its markers."""
    alpha = recipe.alpha_companion or f"{Path(recipe.primary).stem}A.BMP"
    _RECIPES[recipe.primary] = replace(recipe, alpha_companion=alpha)
    _RECIPES[alpha] = replace(recipe, alpha=True, alpha_companion=alpha)


_register_paired_recipe(
    FontAtlasRecipe(
        "F_TEMPUS_10.BMP",
        _ASCII_CHARACTERS,
        4,
        alpha_companion="F_TEMPUS_10_ALPHA.BMP",
        coverage_baseline=11,
    )
)

_register_paired_recipe(
    FontAtlasRecipe(
        "F_NUM_TLARGE.BMP",
        b"1234567890",
        1,
        implicit_right_edge=True,
        coverage_baseline=19,
        coverage_baseline_color=(16, 56, 255),
    )
)

_register_paired_recipe(
    FontAtlasRecipe(
        "F_DODGENBURN16.BMP",
        _ASCII_CHARACTERS[:-1],
        3,
        alpha_companion="F_DODGENBURN16_ALPHA.BMP",
        coverage_baseline=14,
        coverage_baseline_color=(255, 44, 0),
    )
)

for _name in (
    "COURIER_R_12.BMP",
    "COURIER_B_12.BMP",
    "COURIER_I_12.BMP",
    "COURIER_B_I_12.BMP",
    "COURIER_R_14.BMP",
    "COURIER_B_14.BMP",
    "COURIER_I_14.BMP",
    "COURIER_B_I_14.BMP",
):
    _register_paired_recipe(
        FontAtlasRecipe(
            _name,
            _EXTENDED_CHARACTERS,
            3,
            coverage_baseline={
                "COURIER_B_I_12.BMP": 10,
                "COURIER_B_14.BMP": 12,
                "COURIER_I_14.BMP": 13,
                "COURIER_B_I_14.BMP": 12,
            }.get(_name, 11),
        )
    )

_register_paired_recipe(
    FontAtlasRecipe(
        "F_TIMES_R_I_12.BMP",
        _EXTENDED_CHARACTERS,
        3,
        coverage_baseline=12,
        coverage_key_threshold=48,
    )
)

for _name in (
    "TIMES_R_12.BMP",
    "TIMES_B_14.BMP",
    "TIMES_B_12.BMP",
    "TIMES_R_U_12.BMP",
    "TIMES_B_U_12.BMP",
    "TIMES_R_14.BMP",
    "TIMES_R_U_14.BMP",
    "TIMES_B_U_14.BMP",
):
    _baseline = {
        "TIMES_B_14.BMP": 13,
        "TIMES_R_12.BMP": 11,
        "TIMES_B_12.BMP": 11,
        "TIMES_R_U_12.BMP": 11,
        "TIMES_B_U_12.BMP": 11,
        "TIMES_R_14.BMP": 13,
        "TIMES_R_U_14.BMP": 13,
        "TIMES_B_U_14.BMP": 13,
    }.get(_name)
    _register_paired_recipe(
        FontAtlasRecipe(
            _name,
            _EXTENDED_CHARACTERS,
            4 if _name == "TIMES_B_14.BMP" else 3,
            coverage_baseline=_baseline,
            coverage_key_threshold=1 if _name == "TIMES_R_U_14.BMP" else 0,
        )
    )

for _name in (
    "RC_GOUDY12.BMP",
    "F_CAPTION_GOUDY14.BMP",
    "F_CAPTION_GOUDY18.BMP",
    "F_CAPTION_GOUDY14DS.BMP",
):
    _RECIPES[_name] = FontAtlasRecipe(_name, _EXTENDED_CHARACTERS, 1, implicit_right_edge=True)

_GOUDY_AA_ALPHA: Final = "F_CAPTION_GOUDY14AA_ALPHA.BMP"
_RECIPES["F_CAPTION_GOUDY14AA.BMP"] = FontAtlasRecipe(
    "F_CAPTION_GOUDY14AA.BMP",
    _EXTENDED_CHARACTERS,
    1,
    alpha_companion=_GOUDY_AA_ALPHA,
    implicit_right_edge=True,
    coverage_baseline=13,
    coverage_baseline_color=(0, 0, 0),
)
_RECIPES[_GOUDY_AA_ALPHA] = FontAtlasRecipe(
    "F_CAPTION_GOUDY14AA.BMP",
    _EXTENDED_CHARACTERS,
    1,
    alpha=True,
    alpha_companion=_GOUDY_AA_ALPHA,
    implicit_right_edge=True,
    coverage_baseline=13,
    coverage_baseline_color=(0, 0, 0),
)


def font_atlas_recipe(name: str) -> FontAtlasRecipe | None:
    """Return the exact native format contract for an atlas basename."""
    return _RECIPES.get(Path(name).name.upper())


def regenerable_font_atlas_names() -> frozenset[str]:
    """Return every atlas whose marker layout is understood."""
    return frozenset(_RECIPES)


def font_atlas_output_size(name: str, source_size: tuple[int, int]) -> tuple[int, int]:
    """Describe verified storage without mistaking a paired bank for an 8x glyph."""
    from gk3hd.textures.upscale.fonts.bank import font_row_bank_layout  # noqa: PLC0415

    width, height = source_size
    layout = font_row_bank_layout(name)
    recipe = font_atlas_recipe(name)
    if (
        layout is not None
        and recipe is not None
        and source_size == FONT_ATLAS_COLOR_SIZES.get(recipe.primary, layout.source_size)
    ):
        return layout.image_size
    return width * SCALE, height * SCALE


def regenerate_font_atlas(source: Path, *, scale: int = SCALE) -> Image.Image:
    """Enlarge a recognized atlas without changing any glyph geometry."""
    if scale != SCALE:
        msg = f"font atlases support {SCALE}x regeneration, not {scale}x"
        raise ValueError(msg)
    recipe = font_atlas_recipe(source.name)
    if recipe is None:
        msg = f"no faithful font recipe exists for {source.name}"
        raise ValueError(msg)
    primary, alpha = _load_font_sources(source, recipe)
    cells = parse_glyph_cells(primary, recipe)
    if recipe.coverage_baseline is not None:
        from gk3hd.textures.upscale.fonts.reconstruction import (  # noqa: PLC0415
            reconstruct_alpha_font,
        )

        if alpha is None:
            msg = f"{source.name}: paired reconstruction requires an opacity companion"
            raise ValueError(msg)
        return reconstruct_alpha_font(primary, alpha, recipe)
    if recipe.alpha:
        if alpha is None:
            msg = f"{source.name}: alpha recipe has no companion"
            raise ValueError(msg)
        return _render_exact_raster_atlas(alpha, cells, recipe)
    reference = _render_exact_raster_atlas(primary, cells, recipe)
    if recipe.primary in {
        "SID_EMB_10.BMP",
        "SID_EMB_11.BMP",
        "SID_EMB_18.BMP",
        "SID_EMB_22.BMP",
        "SID_EMB_28.BMP",
    }:
        from gk3hd.textures.upscale.fonts.emboss import reconstruct_embossed_font  # noqa: PLC0415

        return reconstruct_embossed_font(source, primary, reference, recipe)
    if recipe.primary in {
        "SID_NO_EMB_10.BMP",
        "SID_NO_EMB_11.BMP",
        "SID_NO_EMB_14.BMP",
        "SID_NO_EMB_18.BMP",
    }:
        from gk3hd.textures.upscale.fonts.color import reconstruct_color_font  # noqa: PLC0415

        return reconstruct_color_font(primary, reference, recipe)
    if recipe.primary in {
        "RC_GOUDY12.BMP",
        "F_ARIAL_A12.BMP",
        "SID_TEXT_14.BMP",
        "SID_TEXT_18.BMP",
        "SID_TEXT_22.BMP",
        "SID_CAP_20.BMP",
        "SID_CAP_16.BMP",
        "SID_CAP_26.BMP",
        "SID_PDN_10.BMP",
        "SID_PDN_12.BMP",
        "SID_PDN_16.BMP",
        "F_TEMPUS_A10.BMP",
    }:
        from gk3hd.textures.upscale.fonts.reconstruction import (  # noqa: PLC0415
            reconstruct_coverage_font,
        )

        return reconstruct_coverage_font(source, primary, reference, recipe)
    return reference


def _load_font_sources(
    source: Path, recipe: FontAtlasRecipe
) -> tuple[Image.Image, Image.Image | None]:
    """Load both original planes and apply only explicitly verified layout repairs."""
    primary_path = source.with_name(recipe.primary)
    if not primary_path.is_file():
        msg = f"font atlas companion is missing: {primary_path.name}"
        raise ValueError(msg)
    with Image.open(primary_path) as primary_image:
        primary = primary_image.convert("RGB")
    alpha = _load_alpha_companion(source.parent, primary.size, recipe)
    from gk3hd.textures.upscale.fonts.layout import (  # noqa: PLC0415
        repair_courier_layout,
        repair_times_bold_layout,
        repair_times_italic_layout,
    )

    paired_repair = (
        repair_courier_layout
        if recipe.primary.startswith("COURIER_")
        else {
            "TIMES_B_14.BMP": repair_times_bold_layout,
            "F_TIMES_R_I_12.BMP": repair_times_italic_layout,
        }.get(recipe.primary)
    )
    if paired_repair is not None:
        if alpha is None:
            msg = f"{source.name}: layout repair requires its opacity companion"
            raise ValueError(msg)
        return paired_repair(primary, alpha, recipe)
    if recipe.primary == "TIMES_R_U_14.BMP":
        from gk3hd.textures.upscale.fonts.layout import (  # noqa: PLC0415
            repair_times_replacement_anchor,
        )

        return repair_times_replacement_anchor(primary, recipe), alpha
    if recipe.primary in {"TIMES_B_U_12.BMP", "TIMES_B_U_14.BMP"}:
        from gk3hd.textures.upscale.fonts.layout import (  # noqa: PLC0415
            repair_times_underline_layout,
        )

        return repair_times_underline_layout(primary, recipe), alpha
    if recipe.primary == "SID_CAP_16.BMP":
        from gk3hd.textures.upscale.fonts.layout import repair_caption_layout  # noqa: PLC0415

        return repair_caption_layout(primary, recipe), alpha
    return primary, alpha


def _load_alpha_companion(
    directory: Path,
    primary_size: tuple[int, int],
    recipe: FontAtlasRecipe,
) -> Image.Image | None:
    """Validate paired coverage even when generating the color output first."""
    if recipe.alpha_companion is None:
        return None
    path = directory / recipe.alpha_companion
    if not path.is_file():
        msg = f"font atlas companion is missing: {path.name}"
        raise ValueError(msg)
    with Image.open(path) as image:
        if image.size != primary_size:
            msg = f"{path.name}: alpha atlas dimensions do not match {recipe.primary}"
            raise ValueError(msg)
        return image.convert("L")


def _render_exact_raster_atlas(
    source: Image.Image,
    cells: tuple[GlyphCell, ...],
    recipe: FontAtlasRecipe,
) -> Image.Image:
    """Turn each glyph pixel into a 4x4 block and keep metadata sparse."""
    if recipe.alpha:
        alpha = source.convert("L")
        output = Image.new("L", (alpha.width * SCALE, alpha.height * SCALE), 0)
        _copy_scaled_cells(alpha, output, cells)
        return output

    color = source.convert("RGB")
    background = color.getpixel((0, 0))
    output = Image.new("RGB", (color.width * SCALE, color.height * SCALE), background)
    _copy_scaled_cells(color, output, cells)

    # These pixels encode the atlas parser's boundaries and replacement color;
    # broadening them would create phantom glyph cells. Move them to their
    # exact scaled coordinates as single pixels instead.
    source_pixels = color.load()
    output_pixels = output.load()
    if source_pixels is None or output_pixels is None:
        msg = f"{recipe.primary}: atlas pixels are unavailable"
        raise ValueError(msg)
    output_pixels[0, 1] = source_pixels[0, 1]
    parser_background = source_pixels[0, 2]
    # The parser compares markers with (0, 2), not the transparency key at
    # (0, 0). Caption atlases use white for the former and magenta for the
    # latter. Filling their marker rows with the key would erase every
    # boundary even though the visible glyph rasters remained correct.
    output.paste(parser_background, (0, 2, 1, output.height))
    line_height = color.height // recipe.line_count
    for line in range(recipe.line_count):
        y = line * line_height
        output.paste(parser_background, (1, y * SCALE, output.width, y * SCALE + 1))
        for x in range(1, color.width):
            pixel = source_pixels[x, y]
            if pixel != parser_background:
                output_pixels[x * SCALE, y * SCALE] = pixel
    for y in range(color.height):
        if y == 1:
            continue
        pixel = source_pixels[0, y]
        if pixel != parser_background:
            output_pixels[0, y * SCALE] = pixel
    return output


def _copy_scaled_cells(
    source: Image.Image,
    output: Image.Image,
    cells: tuple[GlyphCell, ...],
) -> None:
    """Copy every half-open cell to the same coordinate and size at 4x."""
    for cell in cells:
        left, top, right, bottom = cell.rect
        glyph = source.crop(cell.rect).resize(
            ((right - left) * SCALE, (bottom - top) * SCALE),
            Image.Resampling.NEAREST,
        )
        output.paste(glyph, (left * SCALE, top * SCALE))


def parse_glyph_cells(image: Image.Image, recipe: FontAtlasRecipe) -> tuple[GlyphCell, ...]:
    """Reproduce GK3's marker-table parser and expose its source rectangles."""
    if recipe.line_count < 1:
        msg = f"{recipe.primary}: line count must be positive"
        raise ValueError(msg)
    if image.height < _MINIMUM_ATLAS_HEIGHT or image.height % recipe.line_count != 0:
        msg = f"{recipe.primary}: height does not divide into {recipe.line_count} lines"
        raise ValueError(msg)
    line_height = image.height // recipe.line_count
    if line_height < _MINIMUM_ROW_HEIGHT:
        msg = f"{recipe.primary}: each line needs a marker row and glyph pixels"
        raise ValueError(msg)
    pixels = image.load()
    if pixels is None:
        msg = f"{recipe.primary}: atlas pixels are unavailable"
        raise ValueError(msg)
    background = pixels[0, 2]
    rectangles: list[tuple[int, int, int, int]] = []
    for line in range(recipe.line_count):
        y = line * line_height
        boundaries = [x for x in range(1, image.width) if pixels[x, y] != background]
        if recipe.implicit_right_edge:
            boundaries.append(image.width)
        rectangles.extend(
            (left, y + 1, right, y + line_height) for left, right in pairwise(boundaries)
        )

    # An extra cell can be inside the character map, not unused padding at its
    # end. Require an exact map after verified layout repairs; never discard FF
    # (the y-diaeresis artwork) merely to make a mismatched table parse.
    minimum = len(recipe.characters)
    if len(rectangles) < minimum:
        msg = (
            f"{recipe.primary}: marker table has {len(rectangles)} glyph cells; "
            f"at least {minimum} are required"
        )
        raise ValueError(msg)
    maximum = len(recipe.characters)
    if len(rectangles) > maximum:
        msg = (
            f"{recipe.primary}: marker table has {len(rectangles)} glyph cells; "
            f"at most {maximum} are allowed by its verified recipe"
        )
        raise ValueError(msg)
    return tuple(
        GlyphCell(character, rect)
        for character, rect in zip(recipe.characters, rectangles, strict=True)
    )


def iter_regenerable_primary_names() -> Iterable[str]:
    """Yield recognized primary atlases in stable order for diagnostics."""
    return (
        name
        for name, recipe in sorted(_RECIPES.items())
        if not recipe.alpha and name == recipe.primary
    )
