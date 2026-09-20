"""Synthetic marker atlases; no game artwork or external font files."""

from __future__ import annotations

from math import ceil
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

from gk3hd.textures.upscale.fonts.atlas import (
    FONT_ATLAS_COLOR_SIZES,
    font_atlas_recipe,
    parse_glyph_cells,
)
from tests.courier_fixtures import make_italic_courier_pair

if TYPE_CHECKING:
    from pathlib import Path


def make_sidney_pair(
    directory: Path,
    *,
    reverse: bool = False,
    include_medium: bool = False,
    include_pulldown: bool = False,
    include_tempus: bool = False,
) -> None:
    layouts = [("SID_TEXT_14.BMP", 517, 48, 3, 10), ("SID_TEXT_22.BMP", 518, 100, 4, 18)]
    if include_medium:
        layouts.append(("F_ARIAL_A12.BMP", 835, 17, 1, 12))
        layouts.append(("RC_GOUDY12.BMP", 1294, 16, 1, 12))
        layouts.append(("SID_TEXT_18.BMP", 527, 57, 3, 13))
        layouts.append(("SID_CAP_20.BMP", 513, 108, 4, 21))
        layouts.append(("SID_CAP_26.BMP", 648, 136, 4, 25))
    if include_pulldown:
        layouts.append(("SID_PDN_10.BMP", 512, 36, 3, 8))
        layouts.append(("SID_PDN_12.BMP", 517, 42, 3, 10))
        layouts.append(("SID_PDN_16.BMP", 514, 57, 3, 14))
    if include_tempus:
        layouts.append(("F_TEMPUS_A10.BMP", 183, 64, 4, 11))
    for name, width, height, rows, baseline in sorted(layouts, reverse=reverse):
        recipe = font_atlas_recipe(name)
        assert recipe is not None
        image = Image.new("RGB", (width, height), (0, 0, 0))
        image.putpixel((0, baseline), (205, 0, 0) if name == "F_TEMPUS_A10.BMP" else (255, 0, 0))
        if name == "F_ARIAL_A12.BMP":
            image.putpixel((0, baseline), (255, 255, 255))
        count = ceil(len(recipe.characters) / rows)
        for row in range(rows):
            top = row * (height // rows)
            left = 1
            image.putpixel((left, top), (0, 0, 255))
            for index in range(min(count, len(recipe.characters) - row * count)):
                advance = 2 + index % 4
                value = (2 + index % 29) * 8
                image.putpixel((left, top + 2), (value, value, value))
                image.putpixel((left + 1, top + 3), (248, 248, 248))
                # Nontrivial overlapping edge fields exercise the hint input,
                # rather than placing all its artwork far above the baseline.
                for y in range(max(1, baseline - 8), baseline):
                    level = (6 + (y * 3 + index) % 25) * 8
                    x = left + (y + index) % advance
                    image.putpixel((x, top + y), (level, level, level))
                left += advance
                if not recipe.implicit_right_edge or index + 1 < len(recipe.characters):
                    image.putpixel((left, top), (0, 0, 255))
        image.save(directory / name)


def make_sidney_color_source(directory: Path, *, size: int = 18) -> None:
    """Unequal rows with authored ink, edge colors and bright overshoot."""
    name = f"SID_NO_EMB_{size}.BMP"
    recipe = font_atlas_recipe(name)
    assert recipe is not None
    counts, baseline = {
        10: ((60, 62, 59), 9),
        11: ((60, 62, 59), 10),
        14: ((45, 48, 43, 45), 12),
        18: ((35, 42, 37, 32, 35), 15),
    }[size]
    image = Image.new("RGB", FONT_ATLAS_COLOR_SIZES[name], (172, 125, 49))
    image.putpixel((0, baseline), (255, 255, 255))
    colors = ((57, 60, 57), (90, 76, 57), (123, 97, 49), (164, 121, 49), (180, 133, 49))
    character_index = 0
    row_height = image.height // recipe.line_count
    for row, count in enumerate(counts):
        left, top = 1, row * row_height
        image.putpixel((left, top), (255, 255, 255))
        for index in range(count):
            advance = 5 + index % (8 if size == 18 else 4)
            glyph_colors = colors
            if size == 11 and recipe.characters[character_index] in (0xA9, 0xAE):
                glyph_colors = ((16, 16, 0), (57, 40, 16), (106, 76, 24), (156, 109, 41))
            for y in range(2, row_height - 3):
                for x in range(1, advance - 1):
                    if (x + y + index) % 7:
                        image.putpixel(
                            (left + x, top + y), glyph_colors[(x + y + index) % len(glyph_colors)]
                        )
            character_index += 1
            left += advance
            image.putpixel((left, top), (255, 255, 255))
    image.save(directory / name)


def make_sidney_embossed_source(directory: Path, *, size: int = 18) -> None:
    """A matching black letter mask over bounded, spatially varying gold shading."""
    if size in (22, 28):
        _make_large_embossed_source(directory, size=size)
        return
    make_sidney_color_source(directory, size=size)
    with Image.open(directory / f"SID_NO_EMB_{size}.BMP") as source:
        plain_image = source.convert("RGB")
    recipe = font_atlas_recipe(f"SID_EMB_{size}.BMP")
    assert recipe is not None
    image = plain_image.copy()
    if size in (10, 11):
        # Rewrap whole characters: the real sibling also has a different row
        # membership and width, without changing individual cell dimensions.
        image = Image.new("RGB", FONT_ATLAS_COLOR_SIZES[recipe.primary], (172, 125, 49))
        image.putpixel((0, 9 if size == 10 else 10), (255, 255, 255))
    cells = parse_glyph_cells(plain_image, recipe)
    key = np.array([21, 31, 6])
    left, top = 1, 0
    for index, cell in enumerate(cells):
        direction = (
            -key if size == 11 and cell.character in (0xA9, 0xAE) else np.array([7, 15, 7]) - key
        )
        plain = np.asarray(plain_image.crop(cell.rect)) >> np.array([3, 2, 3])
        if size == 10 and cell.character == ord("%"):
            assert np.all(plain[:, -1] == key)
            plain = plain[:, :-1]
        alpha = np.clip((plain - key) @ direction / (direction @ direction), 0, 1)
        y, x = np.indices(alpha.shape)
        light = ((x + y) % 5 - 2)[..., None]
        shade = key + light * np.array([1, 2, 1])
        codes = np.rint((1 - alpha[..., None]) * shade)
        codes[np.all(plain == key, axis=2)] = key
        rgb = np.floor(codes * 255 / [31, 63, 31]).astype(np.uint8)
        if size in (10, 11):
            if index in ((60, 122) if size == 10 else (62, 122)):
                left, top = 1, top + image.height // recipe.line_count
            image.putpixel((left, top), (255, 255, 255))
            image.paste(Image.fromarray(rgb), (left, top + 1))
            left += rgb.shape[1]
            image.putpixel((left, top), (255, 255, 255))
        else:
            image.paste(Image.fromarray(rgb), cell.rect[:2])
    image.save(directory / recipe.primary)


def _make_large_embossed_source(directory: Path, *, size: int) -> None:
    """Unpaired color artwork with real storage geometry, not copied game glyphs."""
    name = f"SID_EMB_{size}.BMP"
    recipe = font_atlas_recipe(name)
    assert recipe is not None
    image = Image.new("RGB", FONT_ATLAS_COLOR_SIZES[name], (172, 125, 49))
    image.putpixel((0, 18 if size == 22 else 22), (255, 255, 255))
    count = ceil(len(recipe.characters) / recipe.line_count)
    colors = ((0, 0, 0), (32, 24, 8), (131, 97, 32), (230, 178, 74))
    for row in range(recipe.line_count):
        left, top = 1, row * (image.height // recipe.line_count)
        image.putpixel((left, top), (255, 255, 255))
        for index in range(min(count, len(recipe.characters) - row * count)):
            advance = 5 + index % 7
            for y in range(2, image.height // recipe.line_count - 3):
                for x in range(1, advance - 1):
                    if (x + y + index) % 7:
                        image.putpixel((left + x, top + y), colors[(x + y + index) % len(colors)])
            left += advance
            image.putpixel((left, top), (255, 255, 255))
    image.save(directory / name)


def make_caption_source(directory: Path) -> None:
    """Make four variable-width rows with two overlapping the reserved column."""
    image = Image.new("RGB", (426, 84))
    image.putpixel((0, 16), (255, 0, 0))
    for row, first, last, count in (
        (0, 1, 415, 39),
        (1, 1, 425, 53),
        (2, 0, 417, 45),
        (3, 0, 421, 44),
    ):
        boundaries = [first + i * (last - first) // count for i in range(count + 1)]
        for x in boundaries:
            image.putpixel((x, row * 21), (255, 0, 0))
        for index, left in enumerate(boundaries[:-1]):
            image.putpixel((left, row * 21 + 2), (120, 120, 120))
            image.putpixel((left + 1, row * 21 + 3), (248, 248, 248))
            value = (2 + index % 29) * 8
            image.putpixel((left, row * 21 + 5), (value, value, value))
    image.save(directory / "SID_CAP_16.BMP")


def make_tempus_opacity_pair(directory: Path) -> None:
    """Create matched binary color and fractional eight-bit opacity planes."""
    make_sidney_pair(directory, include_tempus=True)
    recipe = font_atlas_recipe("F_TEMPUS_10.BMP")
    assert recipe is not None
    with Image.open(directory / "F_TEMPUS_A10.BMP") as image:
        color = image.convert("RGB")
    opacity = Image.new("L", color.size)
    for cell in parse_glyph_cells(color, recipe):
        pixels = np.asarray(color.crop(cell.rect))[:, :, 2].copy()
        # Non-multiples of eight must survive; this is not five-bit coverage.
        pixels[pixels > 0] += 3
        opacity.paste(Image.fromarray(pixels), cell.rect[:2])
        white = np.repeat(np.where(pixels > 0, 255, 0).astype(np.uint8)[:, :, None], 3, axis=2)
        color.paste(Image.fromarray(white), cell.rect[:2])
    for y in (1, 11):
        color.putpixel((0, y), (255, 255, 255))
    color.save(directory / "F_TEMPUS_10.BMP")
    opacity.save(directory / "F_TEMPUS_10_ALPHA.BMP")


def make_courier_opacity_pair(directory: Path, name: str) -> None:
    """Create paired samples with the authored two-cell sharp-s layout defect."""
    if name in {"COURIER_I_14.BMP", "COURIER_B_I_14.BMP"}:
        make_italic_courier_pair(directory, name)
        return
    recipe = font_atlas_recipe(name)
    assert recipe is not None
    assert recipe.alpha_companion is not None
    color = Image.new("RGB", FONT_ATLAS_COLOR_SIZES[name], (255, 0, 255))
    alpha = Image.new("L", color.size)
    baseline = {"COURIER_B_I_12.BMP": 10, "COURIER_B_14.BMP": 12}.get(name, 11)
    for y in (1, baseline):
        color.putpixel((0, y), (255, 255, 255))
    # Independent source contracts, not output geometry generated by the repair.
    rows = {
        "COURIER_R_12.BMP": ((1, 450, 63), (1, 454, 76), (1, 309, 43)),
        "COURIER_B_12.BMP": ((1, 464, 63), (1, 460, 71), (1, 371, 48)),
        "COURIER_B_14.BMP": ((1, 479, 56), (1, 471, 67), (1, 479, 56), (2, 28, 3)),
        "COURIER_I_12.BMP": ((1, 510, 63), (1, 515, 74), (1, 364, 45)),
        "COURIER_B_I_12.BMP": ((1, 518, 63), (1, 520, 71), (1, 408, 48)),
        "COURIER_R_14.BMP": ((1, 487, 56), (0, 484, 72), (0, 469, 54)),
    }[name]
    for row, (first, last, count) in enumerate(rows):
        top = row * color.height // len(rows)
        boundaries = [first + i * (last - first) // count for i in range(count + 1)]
        for x in boundaries:
            color.putpixel((x, top), (255, 255, 255))
        for index, left in enumerate(boundaries[:-1]):
            advance = boundaries[index + 1] - left
            for y in range(2, baseline):
                x = left + (y + index) % advance
                color.putpixel((x, top + y), (255, 255, 255))
                alpha.putpixel((x, top + y), 13 + (y * 11 + index) % 243)
    color.save(directory / name)
    alpha.save(directory / recipe.alpha_companion)


def make_times_italic_pair(directory: Path) -> None:
    """Create the shipped row-stride mismatch and omitted default-character slot."""
    name = "F_TIMES_R_I_12.BMP"
    recipe = font_atlas_recipe(name)
    assert recipe is not None
    assert recipe.alpha_companion is not None
    color = Image.new("RGB", FONT_ATLAS_COLOR_SIZES[name], (255, 0, 255))
    alpha = Image.new("L", color.size)
    for y in (1, 12):
        color.putpixel((0, y), (255, 255, 255))
    characters = recipe.characters.replace(b"\x9d", b"")
    assert len(characters) == 180
    for row in range(3):
        top, left = row * 16, 1
        color.putpixel((left, top), (255, 255, 255))
        for index, character in enumerate(characters[row * 60 : (row + 1) * 60]):
            advance = 4 if character == 0x20 else 6 + index % 4
            if character != 0x20:
                for y in range(1, 16):
                    x = left + (y + index) % advance
                    # Include hidden fractional opacity as well as visible ink.
                    value = (13 + y * 11 + index) % 256
                    color.putpixel((x, top + y), (255, 255, 255) if value > 48 else (255, 0, 255))
                    alpha.putpixel((x, top + y), value)
            left += advance
            color.putpixel((left, top), (255, 255, 255))
    color.save(directory / name)
    alpha.save(directory / recipe.alpha_companion)
