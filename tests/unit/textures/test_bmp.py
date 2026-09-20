from __future__ import annotations

import struct

import pytest

from gk3hd.textures.analyze.classify import classify_texture
from gk3hd.textures.bmp import BmpError, inspect_bmp_bytes
from gk3hd.textures.model import TextureKind


def _bmp24(rows: list[list[tuple[int, int, int]]], *, top_down: bool = False) -> bytes:
    height = len(rows)
    width = len(rows[0])
    row_size = ((24 * width + 31) // 32) * 4
    file_rows = rows if top_down else list(reversed(rows))
    pixels = bytearray()
    for row in file_rows:
        for red, green, blue in row:
            pixels.extend((blue, green, red))
        pixels.extend(b"\0" * (row_size - width * 3))
    pixel_offset = 54
    signed_height = -height if top_down else height
    header = struct.pack("<2sIHHI", b"BM", pixel_offset + len(pixels), 0, 0, pixel_offset)
    dib = struct.pack("<IiiHHIIiiII", 40, width, signed_height, 1, 24, 0, len(pixels), 0, 0, 0, 0)
    return header + dib + pixels


def _bmp8(rows: list[list[int]], palette: list[tuple[int, int, int]]) -> bytes:
    height = len(rows)
    width = len(rows[0])
    row_size = ((8 * width + 31) // 32) * 4
    pixels = bytearray()
    for row in reversed(rows):
        pixels.extend(row)
        pixels.extend(b"\0" * (row_size - width))
    palette_bytes = b"".join(
        struct.pack("<BBBB", blue, green, red, 0) for red, green, blue in palette
    )
    pixel_offset = 54 + len(palette_bytes)
    header = struct.pack("<2sIHHI", b"BM", pixel_offset + len(pixels), 0, 0, pixel_offset)
    dib = struct.pack(
        "<IiiHHIIiiII",
        40,
        width,
        height,
        1,
        8,
        0,
        len(pixels),
        0,
        0,
        len(palette),
        0,
    )
    return header + dib + palette_bytes + pixels


@pytest.mark.parametrize("top_down", [False, True])
def test_inspects_top_left_pixel_for_both_row_orders(*, top_down: bool) -> None:
    data = _bmp24([[(255, 0, 255), (1, 2, 3)], [(4, 5, 6), (7, 8, 9)]], top_down=top_down)

    info = inspect_bmp_bytes(data)

    assert (info.width, info.height, info.bits_per_pixel) == (2, 2, 24)
    assert info.top_left_rgb == (255, 0, 255)
    assert not info.palettized


def test_reports_whether_used_palette_entries_are_grayscale() -> None:
    grayscale = _bmp8([[0, 1]], [(0, 0, 0), (127, 127, 127)])
    categorical = _bmp8([[0, 1]], [(255, 255, 255), (0, 0, 255)])

    assert inspect_bmp_bytes(grayscale).used_palette_is_grayscale
    assert not inspect_bmp_bytes(categorical).used_palette_is_grayscale


@pytest.mark.parametrize("top_down", [False, True])
def test_constant_color_requires_every_visible_pixel_to_match(*, top_down: bool) -> None:
    pixels = [[(12, 34, 56)] * 3 for _ in range(2)]
    assert inspect_bmp_bytes(_bmp24(pixels, top_down=top_down)).constant_color
    pixels[1][2] = (12, 34, 57)
    assert not inspect_bmp_bytes(_bmp24(pixels, top_down=top_down)).constant_color


def test_constant_color_ignores_row_padding_and_unused_palette_entries() -> None:
    data = bytearray(_bmp24([[(12, 34, 56)], [(12, 34, 56)]]))
    data[57] = 12
    data[61] = 99
    assert inspect_bmp_bytes(bytes(data)).constant_color
    palette = [(20, 30, 40), (20, 30, 40), (255, 0, 255)]
    assert inspect_bmp_bytes(_bmp8([[0, 1]], palette)).constant_color
    assert not inspect_bmp_bytes(_bmp8([[0, 2]], palette)).constant_color


@pytest.mark.parametrize(
    ("bits", "pixels"),
    [(16, b"\x1f\x7c\x1f\xfc"), (32, b"\x01\x02\x03\0\x01\x02\x03\xff")],
)
def test_constant_color_ignores_reserved_bits(bits: int, pixels: bytes) -> None:
    header = struct.pack("<2sIHHI", b"BM", 54 + len(pixels), 0, 0, 54)
    dib = struct.pack("<IiiHHIIiiII", 40, 2, 1, 1, bits, 0, len(pixels), 0, 0, 0, 0)
    assert inspect_bmp_bytes(header + dib + pixels).constant_color
    changed = bytearray(pixels)
    changed[-bits // 8] ^= 1
    assert not inspect_bmp_bytes(header + dib + changed).constant_color


def test_rejects_truncated_pixels() -> None:
    data = _bmp24([[(1, 2, 3)]])

    with pytest.raises(BmpError, match="truncated pixel data"):
        inspect_bmp_bytes(data[:-1])


@pytest.mark.parametrize("top_down", [False, True])
def test_interior_magenta_is_keyed_but_data_classification_wins(*, top_down: bool) -> None:
    info = inspect_bmp_bytes(
        _bmp24([[(0, 0, 0), (0, 0, 0)], [(0, 0, 0), (255, 0, 255)]], top_down=top_down)
    )
    assert info.has_color_key
    assert classify_texture("BINOCMASK.BMP", info, {}).alphatest
    boundary = classify_texture("BNDRY1.BMP", info, {})
    assert boundary.kind is TextureKind.DATA
    assert not boundary.alphatest


def test_palette_key_must_be_used_by_a_pixel() -> None:
    palette = [(0, 0, 0), (255, 0, 255)]
    assert inspect_bmp_bytes(_bmp8([[0, 1]], palette)).has_color_key
    assert not inspect_bmp_bytes(_bmp8([[0, 0]], palette)).has_color_key


def test_key_bytes_must_align_with_pixels_and_exclude_padding() -> None:
    # BGR contains ff 00 ff across two pixels, but neither pixel is magenta.
    assert not inspect_bmp_bytes(_bmp24([[(0, 255, 1), (3, 2, 255)]])).has_color_key
    padded = bytearray(_bmp24([[(0, 0, 0)], [(0, 0, 0)]]))
    padded[57:60] = b"\xff\x00\xff"
    assert not inspect_bmp_bytes(bytes(padded)).has_color_key


@pytest.mark.parametrize(
    ("bits", "pixels"),
    [(16, b"\0\0\x1f\x7c"), (16, b"\0\0\x1f\xfc"), (32, b"\0\0\0\0\xff\0\xff\x80")],
)
def test_direct_color_key_ignores_unused_bits(bits: int, pixels: bytes) -> None:
    header = struct.pack("<2sIHHI", b"BM", 54 + len(pixels), 0, 0, 54)
    dib = struct.pack("<IiiHHIIiiII", 40, 2, 1, 1, bits, 0, len(pixels), 0, 0, 0, 0)
    assert inspect_bmp_bytes(header + dib + pixels).has_color_key
