"""Read selected Steam app-cache records without a third-party VDF dependency.

Versions 39-41 use sized records; version 41 interns keys in a string table.
Only requested apps are decoded. Credentials in record headers are skipped.
Format: https://github.com/ValveResourceFormat/SteamAppInfo
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from gk3hd.system.steam import VdfValue

_MAX_CACHE_BYTES = 128 * 1024 * 1024
_MAX_DEPTH = 64
_MAGIC_VERSIONS = {0x07564427: 40, 0x07564428: 60, 0x07564429: 60}
_INTERNED_MAGIC = 0x07564429
_NUMBER_FORMATS = {2: "<i", 3: "<f", 4: "<I", 6: "<I", 7: "<Q", 10: "<q"}
_OBJECT_END = 8
_STRING = 1
_WIDE_STRING = 5


class AppInfoError(ValueError):
    """Reject unsupported, truncated or inconsistent Steam cache data."""


@dataclass(slots=True)
class _Reader:
    data: bytes
    position: int = 0

    def take(self, size: int) -> bytes:
        end = self.position + size
        if size < 0 or end > len(self.data):
            msg = "truncated Steam appinfo record"
            raise AppInfoError(msg)
        value = self.data[self.position : end]
        self.position = end
        return value

    def number(self, fmt: str) -> int | float:
        value: int | float = struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]
        return value

    def integer(self, fmt: str = "<I") -> int:
        return int(self.number(fmt))

    def string(self, width: int = 1) -> str:
        start = self.position
        while self.take(width) != b"\0" * width:
            pass
        return self.data[start : self.position - width].decode(
            "utf-8" if width == 1 else "utf-16-le"
        )

    def object(self, keys: tuple[str, ...] | None, depth: int = 0) -> dict[str, VdfValue]:
        if depth > _MAX_DEPTH:
            msg = "Steam appinfo nesting is too deep"
            raise AppInfoError(msg)
        result: dict[str, VdfValue] = {}
        while (kind := self.integer("<B")) != _OBJECT_END:
            key = self.string() if keys is None else keys[self.integer()]
            if key in result:
                msg = "duplicate Steam appinfo key"
                raise AppInfoError(msg)
            result[key] = self.value(kind, keys, depth)
        return result

    def value(self, kind: int, keys: tuple[str, ...] | None, depth: int) -> VdfValue:
        if kind == 0:
            return self.object(keys, depth + 1)
        if kind == _STRING:
            return self.string()
        if kind == _WIDE_STRING:
            return self.string(2)
        if fmt := _NUMBER_FORMATS.get(kind):
            return str(self.number(fmt))
        msg = f"unsupported Steam appinfo value type {kind}"
        raise AppInfoError(msg)


def read_appinfo(path: Path, app_ids: frozenset[int]) -> dict[int, dict[str, VdfValue]]:
    """Read requested app metadata, rejecting malformed cache snapshots."""
    with path.open("rb") as stream:
        data = stream.read(_MAX_CACHE_BYTES + 1)
    if len(data) > _MAX_CACHE_BYTES:
        msg = "Steam appinfo cache exceeds the supported size"
        raise AppInfoError(msg)
    try:
        return _records(data, app_ids)
    except (IndexError, UnicodeError) as exc:
        msg = "invalid Steam appinfo string or string-table reference"
        raise AppInfoError(msg) from exc


def _records(data: bytes, app_ids: frozenset[int]) -> dict[int, dict[str, VdfValue]]:
    reader = _Reader(data)
    magic = reader.integer()
    if magic not in _MAGIC_VERSIONS:
        msg = "unsupported Steam appinfo version; update gk3hd or select GK3HD_PROTON explicitly"
        raise AppInfoError(msg)
    reader.take(4)  # Universe, not needed for installed-tool lookup.
    keys = None
    if magic == _INTERNED_MAGIC:
        offset = reader.integer("<Q")
        if not reader.position <= offset <= len(data) - 4:
            msg = "invalid Steam appinfo string-table offset"
            raise AppInfoError(msg)
        table = _Reader(data, offset)
        count = table.integer()
        if count > len(data) - table.position:
            msg = "invalid Steam appinfo string-table count"
            raise AppInfoError(msg)
        keys = tuple(table.string() for _ in range(count))
        reader.data = data[:offset]
    results = {}
    while app_id := reader.integer():
        size = reader.integer()
        metadata_size = _MAGIC_VERSIONS[magic]
        if size < metadata_size:
            msg = "invalid Steam appinfo record size"
            raise AppInfoError(msg)
        record = reader.take(size)
        if app_id not in app_ids:
            continue
        if app_id in results:
            msg = "duplicate Steam appinfo record"
            raise AppInfoError(msg)
        entry = _Reader(record, metadata_size)
        results[app_id] = entry.object(keys)
        if entry.position != len(record):
            msg = "trailing Steam appinfo record data"
            raise AppInfoError(msg)
    return results
