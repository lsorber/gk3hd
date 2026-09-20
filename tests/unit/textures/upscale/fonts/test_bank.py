"""Storage padding must not become different advances or ambiguous metadata."""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

import pytest
from PIL import Image

from gk3hd.textures.install.conversion import _save_bmp
from gk3hd.textures.native_bmp import encode_rgb565
from gk3hd.textures.pack.format import TexturePackError
from gk3hd.textures.upscale.fonts.bank import (
    FONT_BANK_METADATA_ROW,
    FONT_ROW_BANK_LAYOUTS,
    FontBankLayout,
    font_bank_layout,
    has_font_row_bank,
    read_font_bank_flags,
    stamp_font_row_bank,
    write_font_bank_flags,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("name", "size", "advance"),
    [
        ("F_ARIAL_T8.BMP", (2160, 332), 12),
        ("F_ARIAL_T10.BMP", (2568, 416), 14),
        ("F_ARIAL_T12.BMP", (3340, 528), 16),
        ("F_SSERIF_T8.BMP", (2212, 388), 12),
        ("F_SSERIF_T8B.BMP", (2584, 388), 13),
        ("F_TOOLTIP.BMP", (4720, 528), 14),
    ],
)
def test_verified_layout(name: str, size: tuple[int, int], advance: int) -> None:
    layout = font_bank_layout(name.lower())
    assert layout is not None
    assert layout.image_size == size
    assert layout.max_advance == advance
    occupied = set()
    for index in range(layout.glyph_count):
        left, top, right, bottom = layout.glyph_rect(index, advance)
        assert left > 0
        assert top >= layout.source_size[1]
        assert right * 4 <= size[0]
        assert bottom * 4 <= layout.source_size[1] * 4 + layout.bank_distance
        assert bottom * 4 + layout.bank_distance <= size[1]
        assert right - left == advance + 2
        points = {(x, y) for x in range(left, right) for y in range(top, bottom)}
        assert not occupied & points
        occupied.update(points)
    assert font_bank_layout("UNKNOWN.BMP") is None


def _fixture(name: str = "F_ARIAL_T10.BMP") -> tuple[Image.Image, FontBankLayout, tuple[bool, ...]]:
    layout = font_bank_layout(name)
    assert layout is not None
    image = Image.new("RGB", layout.image_size, (248, 0, 248))
    image.putpixel((0, 1), (248, 252, 248))
    flags = tuple(index % 3 == 0 for index in range(layout.glyph_count))
    return image, layout, flags


@pytest.mark.parametrize("ink", [(248, 252, 248), (176, 0, 216), (0, 0, 0)])
@pytest.mark.parametrize("name", ["F_ARIAL_T8.BMP", "F_TOOLTIP.BMP"])
def test_metadata_survives_png_and_font_recoloring(ink: tuple[int, int, int], name: str) -> None:
    image, layout, flags = _fixture(name)
    original_ink = image.getpixel((0, 1))
    write_font_bank_flags(image, layout, flags)
    # Recolor only the small metadata strip, just as the engine's font copy
    # recolors replacement ink; no font files or game artwork are fixtures.
    for y in range(3):
        for x in range(65 + layout.glyph_count):
            if image.getpixel((x, y)) == original_ink:
                image.putpixel((x, y), ink)
    image.putpixel((0, 0), (0, 0, 0))
    stream = BytesIO()
    image.save(stream, format="PNG")
    stream.seek(0)
    with Image.open(stream) as decoded:
        assert read_font_bank_flags(decoded, layout) == flags


@pytest.mark.parametrize("fault", ["signature", "unknown-color", "anchors", "mode", "size"])
def test_invalid_metadata_is_not_a_font_bank(fault: str) -> None:
    image, layout, flags = _fixture()
    write_font_bank_flags(image, layout, flags)
    if fault == "signature":
        image.putpixel((1, FONT_BANK_METADATA_ROW), (248, 252, 248))
    elif fault == "unknown-color":
        image.putpixel((80, FONT_BANK_METADATA_ROW), (17, 25, 33))
    elif fault == "anchors":
        image.putpixel((2, 1), (248, 0, 248))
    elif fault == "mode":
        image = image.convert("L")
    else:
        image = image.crop((0, 0, image.width - 1, image.height))
    assert read_font_bank_flags(image, layout) is None


@pytest.mark.parametrize("index", [-1, 94])
def test_unknown_slot_is_rejected(index: int) -> None:
    _, layout, _ = _fixture()
    with pytest.raises(ValueError, match="index or advance"):
        layout.glyph_rect(index, 4)


@pytest.mark.parametrize("advance", [0, -1, 15])
def test_invalid_advance_is_rejected(advance: int) -> None:
    _, layout, _ = _fixture()
    with pytest.raises(ValueError, match="index or advance"):
        layout.glyph_rect(0, advance)


def test_stamping_does_not_touch_parser_markers_or_visible_glyph_rows() -> None:
    image, layout, flags = _fixture()
    image.paste((96, 104, 112), (4, 4, 20, 20))
    markers = image.crop((0, 0, image.width, 1)).tobytes()
    glyphs = image.crop((0, 3, image.width, image.height)).tobytes()
    write_font_bank_flags(image, layout, flags)
    assert image.crop((0, 0, image.width, 1)).tobytes() == markers
    assert image.crop((0, 3, image.width, image.height)).tobytes() == glyphs
    assert image.getpixel((0, 1)) == (248, 252, 248)
    with pytest.raises(ValueError, match="one boolean"):
        write_font_bank_flags(image, layout, flags[:-1])


@pytest.mark.parametrize(
    ("size", "advance", "count"),
    [
        ((642, 14), 0, 94),
        ((642, 14), -2, 94),
        ((642, 14), 14, 0),
        ((642, 14), 14, 257),
        ((642, 1), 14, 94),
        ((10, 14), 14, 94),
        ((20, 14), 14, 94),
    ],
)
def test_invalid_layout_is_rejected(size: tuple[int, int], advance: int, count: int) -> None:
    with pytest.raises(ValueError, match="cannot hold"):
        FontBankLayout(size, advance, count)


@pytest.mark.parametrize("name", ["F_ARIAL_T8.BMP", "F_TOOLTIP.BMP"])
def test_padded_font_install_preserves_native_color_and_rejects_corrupt_metadata(
    tmp_path: Path,
    name: str,
) -> None:
    layout = font_bank_layout(name)
    assert layout is not None
    image = Image.new("RGB", layout.image_size, (248, 0, 248))
    image.putpixel((0, 1), (248, 252, 248))
    write_font_bank_flags(
        image, layout, tuple(index % 3 == 0 for index in range(layout.glyph_count))
    )
    path = tmp_path / name
    _save_bmp(image, path, mode="RGB")
    expected = encode_rgb565(image)
    assert path.read_bytes() == expected
    image.putpixel((1, FONT_BANK_METADATA_ROW), (17, 19, 23))
    with pytest.raises(TexturePackError, match="invalid padded font"):
        _save_bmp(image, path, mode="RGB")
    assert path.read_bytes() == expected


@pytest.mark.parametrize("ink", [(248, 252, 248), (176, 0, 216), (0, 0, 0)])
@pytest.mark.parametrize("name", ["F_NUM_TLARGE.BMP", "SID_TEXT_14.BMP", "SID_EMB_28.BMP"])
@pytest.mark.slow
def test_row_font_metadata_roundtrip(tmp_path: Path, ink: tuple[int, int, int], name: str) -> None:
    layout = FONT_ROW_BANK_LAYOUTS[name]
    key = (248, 0, 248)
    image = Image.new("RGB", layout.image_size, (72, 80, 88))
    markers = image.crop((0, 0, image.width, 1)).tobytes()
    glyphs = image.crop((0, 3, image.width, image.height)).tobytes()
    stamp_font_row_bank(image, key=key, ink=ink)
    assert has_font_row_bank(image)
    assert image.crop((0, 0, image.width, 1)).tobytes() == markers
    assert image.crop((0, 3, image.width, image.height)).tobytes() == glyphs
    stream = BytesIO()
    image.save(stream, format="PNG")
    stream.seek(0)
    path = tmp_path / name
    with Image.open(stream) as decoded:
        assert has_font_row_bank(decoded)
        _save_bmp(decoded, path, mode="RGB")
    expected = encode_rgb565(image)
    assert path.read_bytes() == expected
    # Native bitmap decoding is deliberately handled by the game's reader.
    for fault in ("signature", "anchors", "mode", "size"):
        broken = image.copy()
        if fault == "signature":
            broken.putpixel((layout.bank_distance + 1, 2), ink)
        elif fault == "anchors":
            broken.putpixel((layout.bank_distance + 2, 1), key)
        elif fault == "mode":
            broken = broken.convert("L")
        else:
            broken = broken.crop((0, 0, broken.width - 1, broken.height))
        assert not has_font_row_bank(broken)
    image.putpixel((layout.bank_distance + 1, 2), (17, 19, 23))
    with pytest.raises(TexturePackError, match="invalid row font"):
        _save_bmp(image, path, mode="RGB")
    assert path.read_bytes() == expected
