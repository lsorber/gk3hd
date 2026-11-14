"""Prepare original item icons and labels for shared VR selection feedback.

The native inventory, noun and verb identifiers are different namespaces.
Keep these resources keyed by canonical name; the game-thread adapter must
resolve the current inventory value through the original inventory mapping.
No purchased game artwork or translated strings are distributed by GK3HD.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image

from gk3hd.textures.brn import BarnArchive
from gk3hd.textures.extraction import _decode_bmp_payload

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_NAME = re.compile(r"[A-Z0-9_]+", re.IGNORECASE)
_BITMAP = re.compile(r"[A-Z0-9_~'-]+(?:\.BMP)?", re.IGNORECASE)
_MAX_SOURCE_BYTES = 256 * 1024
_MAX_ICON_EXTENT = 128
_MAX_LABEL_BYTES = 192
_NAME_CAPACITY = 96
_HEADER_BYTES = 12
_MAGIC = b"GK3ITM01"
_MAX_ITEMS = 256
MAX_CATALOG_BYTES = 2 * 1024 * 1024
_RECORD = struct.Struct("<4H")


@dataclass(frozen=True, slots=True)
class InventoryVisual:
    """One original verb icon and its readable localized item name.

    Pixels are top-down premultiplied BGRA, matching the shared overlay canvas.
    Black is opaque content. Only the game's magenta key becomes transparent.
    An absent label key explicitly identifies a canonical-name fallback.
    """

    name: str
    label: str
    label_key: str | None
    width: int
    height: int
    bgra: bytes


def load_catalog(data_directory: Path) -> bytes:
    """Freeze original UI artwork into the player's private compiled assets."""
    archive = BarnArchive.open(data_directory)
    entries = {entry.name.upper(): entry for entry in archive.entries}
    with archive.reader() as read:

        def resource(name: str) -> bytes:
            if name not in entries:
                msg = f"missing original inventory feedback resource: {name}"
                raise ValueError(msg)
            return read(entries[name])

        visuals = inventory_visuals(resource("VERBS.TXT"), resource("ESTRINGS.TXT"), resource)
    return encode_catalog(visuals)


def encode_catalog(visuals: tuple[InventoryVisual, ...]) -> bytes:
    """Serialize bounded immutable data; no native pointers or host paths."""
    if len(visuals) > _MAX_ITEMS or len({item.name for item in visuals}) != len(visuals):
        msg = "invalid inventory visual count or duplicate name"
        raise ValueError(msg)
    result = bytearray(_MAGIC + struct.pack("<I", len(visuals)))
    for item in sorted(visuals, key=lambda item: item.name):
        name, label = item.name.encode("ascii"), item.label.encode("utf-8")
        if (
            not _NAME.fullmatch(item.name)
            or not 0 < len(name) < _NAME_CAPACITY
            or not 0 < len(label) <= _MAX_LABEL_BYTES
            or "\0" in item.label
            or not 0 < item.width <= _MAX_ICON_EXTENT
            or not 0 < item.height <= _MAX_ICON_EXTENT
            or len(item.bgra) != item.width * item.height * 4
        ):
            msg = "invalid inventory visual record"
            raise ValueError(msg)
        result.extend(_RECORD.pack(len(name), len(label), item.width, item.height))
        result.extend(name + label + item.bgra)
        if len(result) > MAX_CATALOG_BYTES:
            msg = "inventory visual catalog exceeds its size bound"
            raise ValueError(msg)
    return bytes(result)


def validate_catalog(payload: bytes) -> None:
    """Validate data read from an installed PE before recompiling its code."""
    if not _HEADER_BYTES <= len(payload) <= MAX_CATALOG_BYTES or payload[:8] != _MAGIC:
        msg = "invalid inventory visual catalog header"
        raise ValueError(msg)
    count = struct.unpack_from("<I", payload, 8)[0]
    if count > _MAX_ITEMS:
        msg = "invalid inventory visual catalog count"
        raise ValueError(msg)
    cursor, previous = _HEADER_BYTES, ""
    for _ in range(count):
        if cursor + _RECORD.size > len(payload):
            break
        names, labels, width, height = _RECORD.unpack_from(payload, cursor)
        cursor += _RECORD.size
        end = cursor + names + labels + width * height * 4
        if (
            not 0 < names < _NAME_CAPACITY
            or not 0 < labels <= _MAX_LABEL_BYTES
            or not 0 < width <= _MAX_ICON_EXTENT
            or not 0 < height <= _MAX_ICON_EXTENT
            or end > len(payload)
        ):
            break
        try:
            name = payload[cursor : cursor + names].decode("ascii")
            label = payload[cursor + names : cursor + names + labels].decode("utf-8")
        except UnicodeError:
            break
        if not _NAME.fullmatch(name) or name <= previous or "\0" in label:
            break
        previous, cursor = name, end
    else:
        if cursor == len(payload):
            return
    msg = "invalid inventory visual catalog records"
    raise ValueError(msg)


def inventory_visuals(
    verbs: bytes, strings: bytes, read_bitmap: Callable[[str], bytes]
) -> tuple[InventoryVisual, ...]:
    """Resolve explicit Inventory verb bindings, without guessing sprite names.

    The caller reads the original game's VERBS.TXT and localized strings, and
    supplies a case-insensitive Barn bitmap reader. This does not extract a
    texture corpus, call AI, write files or alter any game/puzzle state.
    """
    labels = _labels(strings)
    result = []
    for name, bitmap in sorted(_icons(verbs).items()):
        label_key = next((key for key in (f"V_{name}", f"N_{name}") if key in labels), None)
        label = labels[label_key] if label_key else name.replace("_", " ").capitalize()
        if not label or len(label.encode("utf-8")) > _MAX_LABEL_BYTES:
            msg = f"inventory label is empty or oversized: {name}"
            raise ValueError(msg)
        source = read_bitmap(bitmap)
        if not 0 < len(source) <= _MAX_SOURCE_BYTES:
            msg = f"inventory icon source is empty or oversized: {bitmap}"
            raise ValueError(msg)
        payload, _proprietary = _decode_bmp_payload(source, name=bitmap)
        with Image.open(BytesIO(payload)) as image:
            if not 0 < image.width <= _MAX_ICON_EXTENT or not 0 < image.height <= _MAX_ICON_EXTENT:
                msg = f"inventory icon dimensions exceed the bounded overlay: {bitmap}"
                raise ValueError(msg)
            rgb = image.convert("RGB")
        pixels = bytearray()
        data = rgb.tobytes()
        for offset in range(0, len(data), 3):
            red, green, blue = data[offset : offset + 3]
            pixels.extend(
                (0, 0, 0, 0) if (red, green, blue) == (255, 0, 255) else (blue, green, red, 255)
            )
        result.append(InventoryVisual(name, label, label_key, rgb.width, rgb.height, bytes(pixels)))
    return tuple(result)


def _lines(payload: bytes, section: str) -> list[str]:
    current = ""
    result = []
    for raw in payload.decode("cp1252").splitlines():
        line = raw.strip()
        if not line or line.startswith(("//", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip().upper()
        elif current == section:
            result.append(line)
    return result


def _labels(payload: bytes) -> dict[str, str]:
    labels = {}
    for line in _lines(payload, "TOOLTIPS"):
        key, separator, value = line.partition("=")
        if separator:
            labels[key.strip().upper()] = value.strip()
    return labels


def _icons(payload: bytes) -> dict[str, str]:
    result = {}
    for line in _lines(payload, "VERBS"):
        columns = line.split("//", 1)[0].split(",")
        fields = {}
        for column in columns[1:]:
            key, separator, value = column.partition("=")
            if separator:
                fields[key.strip().casefold()] = value.strip()
        if fields.get("type", "").casefold() != "inventory":
            continue
        name, bitmap = columns[0].strip().upper(), fields.get("up", "")
        if not _NAME.fullmatch(name) or not _BITMAP.fullmatch(bitmap):
            msg = f"invalid inventory icon binding: {name}"
            raise ValueError(msg)
        bitmap = bitmap.upper()
        if not bitmap.endswith(".BMP"):
            bitmap += ".BMP"
        if name in result and result[name] != bitmap:
            msg = f"conflicting inventory icon bindings: {name}"
            raise ValueError(msg)
        result[name] = bitmap
    return result
