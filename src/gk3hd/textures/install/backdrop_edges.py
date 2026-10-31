"""Repair forest backdrop sampling from the player's original scene resources."""

from __future__ import annotations

import math
import struct
from typing import TYPE_CHECKING

from gk3hd.textures.analyze.usage import _BSP_HEADER, _INDEX, _POLYGON, _UV, _Reader, _texture_name
from gk3hd.textures.brn import BarnArchive

if TYPE_CHECKING:
    from pathlib import Path

# These authored background sheets repeat horizontally, but their foliage/sky
# silhouettes do not repeat vertically. Keep U repetition and all geometry.
_BACKDROPS = frozenset({"FULLTREE01.BMP", "FULLTREE01ENDS.BMP", "TILEDTREES.BMP"})
_MAX_GENERATED_BYTES = 64 * 1024 * 1024
_NATIVE_HEADER_SIZE = 8
_BMP_HEIGHT_END = 26
_MIN_TEXTURE_HEIGHT = 2
_CYCLE_EDGE_TOLERANCE = 0.05


def backdrop_edge_fixes(game_dir: Path, textures: set[str]) -> dict[str, bytes]:
    """Generate bounded loose BSP overrides only for installed backdrop textures.

    Original BRNs remain untouched. The texture install transaction owns these
    generated resources alongside its BMPs and removes them on uninstall.
    The inset uses original texture pixels, never the monitor resolution or the
    enlarged texture density. No game-owned scene data ships with the package.
    """
    selected = textures & _BACKDROPS
    data = game_dir / "Data"
    if not selected or not data.is_dir():
        return {}
    archive = BarnArchive.open(data)
    entries = {entry.name.upper(): entry for entry in archive.entries}
    results: dict[str, bytes] = {}
    total = 0
    with archive.reader() as read:
        heights = {
            name: _bitmap_height(read(entries[name])) for name in selected if name in entries
        }
        for name, entry in entries.items():
            if not name.endswith(".BSP"):
                continue
            original = read(entry)
            if not any(
                texture.removesuffix(".BMP").encode() in original.upper() for texture in heights
            ):
                continue
            corrected = inset_backdrop_uvs(original, heights)
            if corrected != original:
                total += len(corrected)
                if total > _MAX_GENERATED_BYTES:
                    msg = "generated backdrop scene corrections exceed 64 MiB"
                    raise ValueError(msg)
                results[name] = corrected
    return results


def _bitmap_height(payload: bytes) -> int:
    if payload.startswith(b"61nM") and len(payload) >= _NATIVE_HEADER_SIZE:
        height = struct.unpack_from("<H", payload, 4)[0]
    elif payload.startswith(b"BM") and len(payload) >= _BMP_HEIGHT_END:
        height = abs(struct.unpack_from("<i", payload, 22)[0])
    else:
        msg = "unsupported original backdrop bitmap header"
        raise ValueError(msg)
    if height < _MIN_TEXTURE_HEIGHT:
        msg = "original backdrop bitmap must have at least two rows"
        raise ValueError(msg)
    return height


def inset_backdrop_uvs(payload: bytes, heights: dict[str, int]) -> bytes:
    """Inset one-cycle backdrop V coordinates, preserving repeating U and picking.

    Retail BSPs use negative V cycles. Slight authored overshoot and filtering
    across a cycle endpoint sample opaque ground at the top of the sky. Move
    only the boundary coordinates to original texel centers. Do not normalize
    or clamp actual multi-cycle geometry, or UVs shared with another material.
    """
    reader = _Reader(payload)
    header = _BSP_HEADER.unpack(reader.take(_BSP_HEADER.size))
    if header[0] != b"NECS":
        msg = "invalid backdrop BSP signature"
        raise ValueError(msg)
    reader.skip(header[4] * 32)
    surfaces = [_texture_name(reader.take(60)[4:36]) for _ in range(header[9])]
    reader.skip(header[11] * 16)
    polygons = list(_POLYGON.iter_unpack(reader.take(header[12] * _POLYGON.size)))
    reader.skip(header[10] * 16 + header[5] * 12)
    offset = reader.offset
    coordinates = list(_UV.iter_unpack(reader.take(header[6] * _UV.size)))
    indices = [item[0] for item in _INDEX.iter_unpack(reader.take(header[7] * _INDEX.size))]
    used, owners = _surface_vertices(polygons, indices, len(surfaces), len(coordinates))
    result = bytearray(payload)
    for surface, referenced in used.items():
        if surfaces[surface] not in heights:
            continue
        values = [coordinates[index][1] for index in referenced]
        if not all(math.isfinite(value) for value in values):
            continue
        low = round(min(values))
        high = low + 1
        if (
            abs(min(values) - low) > _CYCLE_EDGE_TOLERANCE
            or abs(max(values) - high) > _CYCLE_EDGE_TOLERANCE
        ):
            continue
        inset = 0.5 / heights[surfaces[surface]]
        for index in referenced:
            if owners[index] != {surface}:
                continue
            _u, v = coordinates[index]
            fixed = max(low + inset, min(high - inset, v))
            if fixed != v:
                struct.pack_into("<f", result, offset + index * _UV.size + 4, fixed)
    return bytes(result)


def _surface_vertices(
    polygons: list[tuple[int, ...]], indices: list[int], surfaces: int, coordinates: int
) -> tuple[dict[int, set[int]], dict[int, set[int]]]:
    used: dict[int, set[int]] = {}
    owners: dict[int, set[int]] = {}
    for start, _unused, count, surface in polygons:
        if surface >= surfaces or start + count > len(indices):
            msg = "invalid backdrop BSP polygon indices"
            raise ValueError(msg)
        for index in indices[start : start + count]:
            if index >= coordinates:
                msg = "invalid backdrop BSP texture coordinate index"
                raise ValueError(msg)
            used.setdefault(surface, set()).add(index)
            owners.setdefault(index, set()).add(surface)
    return used, owners
