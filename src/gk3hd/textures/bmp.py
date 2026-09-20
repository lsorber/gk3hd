"""Small, strict parser for the uncompressed BMP variants used by GK3."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.textures.analyze.alpha_shape import is_alpha_silhouette

if TYPE_CHECKING:
    from pathlib import Path

_FILE_HEADER_SIZE = 14
_INFO_HEADER_SIZE = 40
_BI_RGB = 0
_PALETTIZED_BITS = 8
_RGB555_BITS = 16


class BmpError(ValueError):
    """Report a malformed or unsupported extracted BMP."""


@dataclass(frozen=True, slots=True)
class BmpInfo:
    """BMP facts used by semantic classification."""

    width: int
    height: int
    bits_per_pixel: int
    palettized: bool
    top_left_rgb: tuple[int, int, int]
    used_palette_is_grayscale: bool | None
    has_color_key: bool
    constant_color: bool = False
    alpha_silhouette: bool = False


def inspect_bmp(path: Path) -> BmpInfo:
    """Read and validate one extracted BMP without third-party image libraries."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        msg = f"cannot read BMP {path}: {exc}"
        raise BmpError(msg) from exc
    return inspect_bmp_bytes(data, source=str(path))


def inspect_bmp_bytes(data: bytes, *, source: str = "<bytes>") -> BmpInfo:
    """Inspect a BMP byte string and return the facts needed by the classifier."""
    if len(data) < _FILE_HEADER_SIZE + _INFO_HEADER_SIZE or data[:2] != b"BM":
        detail = f"{source}: not a standard BMP"
        raise BmpError(detail)

    pixel_offset = _unpack_from("<I", data, 10, source=source)[0]
    header_size = _unpack_from("<I", data, 14, source=source)[0]
    if header_size < _INFO_HEADER_SIZE:
        detail = f"{source}: unsupported DIB header size {header_size}"
        raise BmpError(detail)

    width, signed_height, planes, bits_per_pixel, compression = _unpack_from(
        "<iiHHI", data, 18, source=source
    )
    if width <= 0 or signed_height == 0:
        detail = f"{source}: invalid dimensions {width}x{signed_height}"
        raise BmpError(detail)
    if planes != 1:
        detail = f"{source}: expected one color plane, found {planes}"
        raise BmpError(detail)
    if compression != _BI_RGB:
        detail = f"{source}: compressed BMPs are unsupported"
        raise BmpError(detail)
    if bits_per_pixel not in {8, 16, 24, 32}:
        detail = f"{source}: unsupported bit depth {bits_per_pixel}"
        raise BmpError(detail)

    height = abs(signed_height)
    row_size = ((bits_per_pixel * width + 31) // 32) * 4
    pixel_size = row_size * height
    if pixel_offset > len(data) or pixel_size > len(data) - pixel_offset:
        detail = f"{source}: truncated pixel data"
        raise BmpError(detail)

    top_row = pixel_offset if signed_height < 0 else pixel_offset + row_size * (height - 1)
    palette: tuple[tuple[int, int, int], ...] | None = None
    used_palette_is_grayscale: bool | None = None
    if bits_per_pixel == _PALETTIZED_BITS:
        palette = _read_palette(data, header_size=header_size, source=source)
        used = _used_palette_indexes(
            data,
            pixel_offset=pixel_offset,
            width=width,
            height=height,
            row_size=row_size,
        )
        if used and max(used) >= len(palette):
            detail = f"{source}: pixel references a missing palette entry"
            raise BmpError(detail)
        used_palette_is_grayscale = all(
            palette[index][0] == palette[index][1] == palette[index][2] for index in used
        )
        top_left_rgb = palette[data[top_row]]
        has_color_key = any(palette[index] == (255, 0, 255) for index in used)
        constant_color = len({palette[index] for index in used}) == 1
    else:
        top_left_rgb = _read_direct_pixel(data, top_row, bits_per_pixel)
        has_color_key = any(
            _row_contains_color_key(
                data[start : start + width * (bits_per_pixel // 8)], bits_per_pixel
            )
            for start in range(pixel_offset, pixel_offset + pixel_size, row_size)
        )
        constant_color = all(
            _row_is_constant(data[start : start + width * (bits_per_pixel // 8)], bits_per_pixel)
            and _read_direct_pixel(data, start, bits_per_pixel) == top_left_rgb
            for start in range(pixel_offset, pixel_offset + pixel_size, row_size)
        )

    return BmpInfo(
        width=width,
        height=height,
        bits_per_pixel=bits_per_pixel,
        palettized=bits_per_pixel == _PALETTIZED_BITS,
        top_left_rgb=top_left_rgb,
        used_palette_is_grayscale=used_palette_is_grayscale,
        has_color_key=has_color_key,
        constant_color=constant_color,
        alpha_silhouette=(
            is_alpha_silhouette(
                tuple(
                    bytes(palette[index][0] for index in data[start : start + width])
                    for start in range(pixel_offset, pixel_offset + pixel_size, row_size)
                )
            )
            if palette is not None and used_palette_is_grayscale
            else False
        ),
    )


def _row_is_constant(row: bytes, bits_per_pixel: int) -> bool:
    """Compare visible channels only, excluding RGB555/RGB32 reserved bits."""
    if bits_per_pixel == _RGB555_BITS:
        return row[::2] == row[:1] * (len(row) // 2) and all(
            value & 0x7F == row[1] & 0x7F for value in row[1::2]
        )
    stride = bits_per_pixel // 8
    return all(
        row[channel::stride] == row[channel : channel + 1] * (len(row) // stride)
        for channel in range(3)
    )


def _row_contains_color_key(row: bytes, bits_per_pixel: int) -> bool:
    """Find exact magenta pixels, ignoring padding and cross-pixel byte matches."""
    stride = bits_per_pixel // 8
    # BI_RGB RGB555 ignores the high bit; RGB32 ignores its reserved byte.
    patterns = (b"\x1f\x7c", b"\x1f\xfc") if bits_per_pixel == _RGB555_BITS else (b"\xff\x00\xff",)
    for pattern in patterns:
        position = row.find(pattern)
        while position >= 0:
            if position % stride == 0:
                return True
            position = row.find(pattern, position + 1)
    return False


def _unpack_from(format_string: str, data: bytes, offset: int, *, source: str) -> tuple[int, ...]:
    """Unpack a fixed structure after an explicit bounds check."""
    size = struct.calcsize(format_string)
    if offset > len(data) or size > len(data) - offset:
        detail = f"{source}: truncated header"
        raise BmpError(detail)
    return struct.unpack_from(format_string, data, offset)


def _read_palette(
    data: bytes,
    *,
    header_size: int,
    source: str,
) -> tuple[tuple[int, int, int], ...]:
    """Read a BMP palette as RGB triples."""
    color_count = _unpack_from("<I", data, 46, source=source)[0] or 256
    palette_offset = _FILE_HEADER_SIZE + header_size
    palette_size = color_count * 4
    if palette_offset > len(data) or palette_size > len(data) - palette_offset:
        detail = f"{source}: truncated color palette"
        raise BmpError(detail)
    colors = []
    for index in range(color_count):
        blue, green, red, _reserved = struct.unpack_from("<4B", data, palette_offset + index * 4)
        colors.append((red, green, blue))
    return tuple(colors)


def _used_palette_indexes(
    data: bytes,
    *,
    pixel_offset: int,
    width: int,
    height: int,
    row_size: int,
) -> set[int]:
    """Collect only meaningful index bytes, excluding row padding."""
    used: set[int] = set()
    for row in range(height):
        start = pixel_offset + row * row_size
        used.update(data[start : start + width])
    return used


def _read_direct_pixel(data: bytes, offset: int, bits_per_pixel: int) -> tuple[int, int, int]:
    """Decode one direct-color pixel from an uncompressed BMP."""
    if bits_per_pixel == _RGB555_BITS:
        # BI_RGB 16-bit BMPs use RGB555. GK3's proprietary RGB565 images must be
        # converted by gk3-extractor before they reach this analyzer.
        value = struct.unpack_from("<H", data, offset)[0]
        red = ((value >> 10) & 0x1F) * 255 // 31
        green = ((value >> 5) & 0x1F) * 255 // 31
        blue = (value & 0x1F) * 255 // 31
        return red, green, blue
    blue, green, red = struct.unpack_from("<3B", data, offset)
    return red, green, blue
