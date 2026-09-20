"""Recover texture usage from the player's geometry, font, and verb definitions."""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from gk3hd.textures.analyze.script_usage import script_data_textures
from gk3hd.textures.brn import BarnArchive

if TYPE_CHECKING:
    from collections.abc import Callable

_BSP_HEADER = struct.Struct("<4s12I")
_POLYGON = struct.Struct("<4H")
_UV = struct.Struct("<ff")
_INDEX = struct.Struct("<H")
_UV_EPSILON = 0.0001


def _has_usage_metadata(name: str) -> bool:
    """Select geometry, resource bindings and the three shared UI layouts."""
    return Path(name).suffix.upper() in {
        ".BSP",
        ".MOD",
        ".FON",
        ".CUR",
        ".SIF",
        ".SCN",
        ".SHP",
    } or (name.upper() in {"VERBS.TXT", "TBLAYOUT.TXT", "OBLAYOUT.TXT"})


@dataclass(frozen=True, slots=True)
class TextureUsage:
    """Facts derived from game resources, independent of image appearance."""

    tiled: frozenset[str] = frozenset()
    fonts: frozenset[str] = frozenset()
    action_buttons: frozenset[str] = frozenset()
    toolbar_buttons: frozenset[str] = frozenset()
    cursor_opacity_pairs: frozenset[tuple[str, str]] = frozenset()
    data: frozenset[str] = frozenset()


def discover_data_directory(source: Path) -> Path | None:
    """Find Data/CORE.BRN only in the source's own ancestry, never another game."""
    if not source.is_dir():
        return None
    for parent in (source, *source.parents):
        candidates = [p for p in parent.iterdir() if p.name.casefold() == "data" and p.is_dir()]
        for candidate in candidates:
            if any(p.name.casefold() == "core.brn" for p in candidate.iterdir()):
                return candidate
    return None


def analyze_usage(
    data_directory: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> TextureUsage:
    """Read resource definitions directly; no extraction or AI is required."""
    archive = BarnArchive.open(data_directory)
    names = {entry.name.upper() for entry in archive.entries if entry.name.upper().endswith(".BMP")}
    entries = [entry for entry in archive.entries if _has_usage_metadata(entry.name)]
    tiled: set[str] = set()
    fonts = {name for name in names if name.startswith("F_")}
    action_buttons: set[str] = set()
    toolbar_buttons: set[str] = set()
    cursor_opacity_pairs: set[tuple[str, str]] = set()
    data: set[str] = set()
    geometry_readers = {".BSP": bsp_tiled_textures, ".MOD": mod_tiled_textures}
    with archive.reader() as read:
        for index, entry in enumerate(entries, start=1):
            try:
                payload = read(entry)
                suffix = Path(entry.name).suffix.upper()
                geometry_reader = geometry_readers.get(suffix)
                if geometry_reader is not None:
                    tiled.update(geometry_reader(payload))
                elif suffix == ".FON":
                    fonts.update(font_textures(payload, entry.name, names))
                elif suffix == ".CUR":
                    pair = cursor_opacity_textures(payload, entry.name, names)
                    if pair is not None:
                        cursor_opacity_pairs.add(pair)
                elif suffix in {".SIF", ".SCN", ".SHP"}:
                    data.update(_resource_data_textures(payload, suffix, names))
                elif entry.name.upper() == "VERBS.TXT":
                    action_buttons.update(action_button_textures(payload, names))
                else:
                    toolbar_buttons.update(toolbar_button_textures(payload, names))
            except ValueError as exc:
                message = f"cannot analyze texture usage in {entry.name}: {exc}"
                raise ValueError(message) from exc
            if progress is not None:
                progress(index, len(entries))
    return TextureUsage(
        tiled=frozenset(tiled & names),
        fonts=frozenset(fonts & names),
        action_buttons=frozenset(action_buttons),
        toolbar_buttons=frozenset(toolbar_buttons),
        cursor_opacity_pairs=frozenset(cursor_opacity_pairs),
        data=frozenset(data),
    )


def _resource_data_textures(payload: bytes, suffix: str, available: set[str]) -> set[str]:
    if suffix == ".SHP":
        return script_data_textures(payload, available)
    return scene_data_textures(payload, suffix, available)


def scene_data_textures(payload: bytes, suffix: str, available: set[str]) -> set[str]:
    """Resolve navigation bindings and implicitly named skybox hit maps.

    Every conditional GENERAL section contributes potential usage; analysis
    must not depend on the currently loaded save. The retail skybox loader
    appends _mask to each face's name. These are hit-region data, not opacity.
    """
    result: set[str] = set()
    section = ""
    for raw_line in payload.decode("latin-1").splitlines():
        line = raw_line.split("//", 1)[0].split(";", 1)[0].strip(" \t\r\0")
        if line.startswith("["):
            section = line[1:].split("=", 1)[0].split("]", 1)[0].strip().casefold()
            continue
        key, separator, value = line.partition("=")
        if not separator:
            continue
        field = key.strip().casefold()
        stem = value.split(",", 1)[0].strip().strip('"').upper().removesuffix(".BMP")
        if not stem or "/" in stem or "\\" in stem:
            continue
        candidate = ""
        if suffix.upper() == ".SIF" and section == "general" and field == "boundary":
            candidate = f"{stem}.BMP"
        elif (
            suffix.upper() == ".SCN"
            and section == "skybox"
            and field in {"left", "right", "front", "back", "up", "down"}
            and f"{stem}.BMP" in available
        ):
            candidate = f"{stem}_MASK.BMP"
        if candidate in available:
            result.add(candidate)
    return result


def cursor_opacity_textures(
    payload: bytes, filename: str, available: set[str]
) -> tuple[str, str] | None:
    """Read active cursor color/opacity bindings, never commented-out examples."""
    fields: dict[str, str] = {}
    for raw_line in payload.decode("latin-1").splitlines():
        line = raw_line.split(";", 1)[0].split("//", 1)[0].strip(" \t\r\0")
        key, separator, value = line.partition("=")
        if separator and value.strip():
            fields[key.strip().casefold()] = value.strip().strip('"')
    opacity = fields.get("alpha channel")
    if not opacity:
        return None
    color = fields.get("sprite name", Path(filename).stem)
    pair = tuple(f"{Path(name).stem.upper()}.BMP" for name in (color, opacity))
    if all(name in available for name in pair):
        return pair[0], pair[1]
    return None


def toolbar_button_textures(payload: bytes, available: set[str]) -> set[str]:
    """Resolve button states in shipped toolbar layouts, excluding backgrounds."""
    result: set[str] = set()
    for raw_line in payload.decode("latin-1").splitlines():
        line = raw_line.split("//", 1)[0].strip(" \t\r\0")
        if line.startswith(";"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip().casefold().endswith(
            ("spriteup", "spritedown", "spritedis", "spritehover")
        ):
            continue
        candidate = value.strip().strip('"').upper()
        if not candidate.endswith(".BMP"):
            candidate += ".BMP"
        if candidate in available:
            result.add(candidate)
    return result


def action_button_textures(payload: bytes, available: set[str]) -> set[str]:
    """Read verb-menu sprite states, not arbitrary small texture filenames."""
    result: set[str] = set()
    for raw_line in payload.decode("latin-1").splitlines():
        line = raw_line.split("//", 1)[0].strip(" \t\r\0")
        if line.startswith(";"):
            continue
        for field in line.split(","):
            key, separator, value = field.partition("=")
            if not separator or key.strip().casefold() not in {"up", "down", "hover"}:
                continue
            candidate = value.strip().strip('"').upper()
            if not candidate.endswith(".BMP"):
                candidate += ".BMP"
            if candidate in available:
                result.add(candidate)
    return result


def font_textures(payload: bytes, name: str, available: set[str]) -> set[str]:
    """Resolve .FON bitmap/alpha references, with the engine's same-name fallback."""
    result: set[str] = set()
    bitmap_declared = False
    for raw_line in payload.decode("latin-1").splitlines():
        line = raw_line.split("//", 1)[0].strip(" \t\r\0")
        if line.startswith(";") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().casefold()
        if key not in {"bitmap name", "alpha channel"}:
            continue
        bitmap_declared |= key == "bitmap name"
        for token in re.findall(r"[A-Za-z0-9_.]+", value):
            candidate = token.upper()
            if not candidate.endswith(".BMP"):
                candidate += ".BMP"
            if candidate in available:
                result.add(candidate)
    fallback = Path(name).stem.upper() + ".BMP"
    if not bitmap_declared and fallback in available:
        result.add(fallback)
    return result


@dataclass(slots=True)
class _Reader:
    data: bytes
    offset: int = 0

    def take(self, size: int) -> bytes:
        if size < 0 or self.offset + size > len(self.data):
            message = "truncated geometry resource"
            raise ValueError(message)
        start = self.offset
        self.offset += size
        return self.data[start : self.offset]

    def skip(self, size: int) -> None:
        self.take(size)

    def expect(self, magic: bytes) -> None:
        if self.take(len(magic)) != magic:
            message = f"unexpected geometry signature; expected {magic!r}"
            raise ValueError(message)

    def uint(self) -> int:
        return int.from_bytes(self.take(4), "little")


def _outside_unit_square(pair: tuple[float, float]) -> bool:
    if not all(math.isfinite(value) for value in pair):
        # Collision-only meshes (e.g. camera boundaries) contain undefined UVs.
        # Those vertices supply no evidence of visible texture repetition.
        return False
    return any(value < -_UV_EPSILON or value > 1 + _UV_EPSILON for value in pair)


def _texture_name(raw: bytes) -> str:
    name = raw.split(b"\0", 1)[0].decode("latin-1").upper()
    return name if name.endswith(".BMP") else name + ".BMP"


def bsp_tiled_textures(payload: bytes) -> set[str]:
    """Find out-of-range UVs actually referenced by BSP polygon surfaces."""
    reader = _Reader(payload)
    header = _BSP_HEADER.unpack(reader.take(_BSP_HEADER.size))
    if header[0] != b"NECS":
        message = "invalid BSP signature"
        raise ValueError(message)
    reader.skip(header[4] * 32)
    surfaces = [_texture_name(reader.take(60)[4:36]) for _ in range(header[9])]
    reader.skip(header[11] * 16)
    polygons = list(_POLYGON.iter_unpack(reader.take(header[12] * _POLYGON.size)))
    reader.skip(header[10] * 16 + header[5] * 12)
    coords = list(_UV.iter_unpack(reader.take(header[6] * _UV.size)))
    indices = [index[0] for index in _INDEX.iter_unpack(reader.take(header[7] * _INDEX.size))]
    result: set[str] = set()
    for start, _unused, count, surface in polygons:
        if surface >= len(surfaces) or start + count > len(indices):
            message = "invalid BSP polygon indices"
            raise ValueError(message)
        for index in indices[start : start + count]:
            if index >= len(coords):
                # The shipped DEFAULT.BSP has fewer UVs than vertices. Its
                # unmapped vertices provide no evidence of texture repetition.
                continue
            if _outside_unit_square(coords[index]):
                result.add(surfaces[surface])
    return result


def mod_tiled_textures(payload: bytes) -> set[str]:
    """Find repeating UVs in each MOD mesh section, respecting LOD blocks."""
    reader = _Reader(payload)
    reader.expect(b"LDOM")
    minor, major = reader.take(2)
    reader.skip(2)
    meshes = reader.uint()
    reader.skip(12)
    if (major, minor) == (1, 9):
        reader.skip(24)
    result: set[str] = set()
    for _ in range(meshes):
        reader.expect(b"HSEM")
        reader.skip(48)
        sections = reader.uint()
        reader.skip(24)
        for _ in range(sections):
            result.update(_mod_section(reader))
    return result


def _mod_section(reader: _Reader) -> set[str]:
    reader.expect(b"PRGM")
    name = _texture_name(reader.take(32))
    reader.skip(8)
    vertices, triangles, lods = reader.uint(), reader.uint(), reader.uint()
    reader.skip(4 + vertices * 24)
    coordinates = _UV.iter_unpack(reader.take(vertices * _UV.size))
    repeating = False
    for pair in coordinates:
        repeating |= _outside_unit_square(pair)
    reader.skip(triangles * 8)
    for _ in range(lods):
        reader.expect(b"KDOL")
        first, second, third = reader.uint(), reader.uint(), reader.uint()
        reader.skip(first * 8 + second * 4 + third * 2)
    return {name} if repeating else set()
