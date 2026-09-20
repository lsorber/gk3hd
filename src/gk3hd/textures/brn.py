"""Strict reader for the small subset of GK3 Barn archives that we need.

``CORE.BRN`` owns the global asset catalog and points into its own data section
or one of several child barns.  This module indexes that catalog and returns
decompressed payload bytes; interpretation of those bytes belongs elsewhere.
"""

from __future__ import annotations

import mmap
import struct
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import lzokay

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from typing import BinaryIO

_BARN_MAGIC = b"GK3!Barn"
_DATA_DIRECTORY = b"ataD"
_CATALOG_DIRECTORY = b"riDD"
_BARN_HEADER = struct.Struct("<8sHHHHII")
_DIRECTORY_HEADER = struct.Struct("<4sHHIIIII")
_CATALOG_HEADER = struct.Struct("<32s4s40sII")
_FILE_HEADER = struct.Struct("<IIIBBB")
_UINT32 = struct.Struct("<I")
_COMPRESSED_PREFIX_SIZE = 8
_MAX_DIRECTORY_COUNT = 1_024
_MAX_DECOMPRESSED_SIZE = (1 << 31) - 1


class BrnError(ValueError):
    """Report a malformed, unsupported, or incomplete GK3 Barn archive."""


@dataclass(frozen=True, slots=True)
class BarnEntry:
    """Location and compression metadata for one catalogued asset."""

    name: str
    barn_path: Path
    offset: int
    size: int
    compression: int


@dataclass(frozen=True, slots=True)
class _Directory:
    """The offsets used from a Barn directory header."""

    kind: bytes
    header_offset: int
    data_offset: int


@dataclass(frozen=True, slots=True)
class _EntryLocation:
    """Shared barn location for a contiguous group of catalog records."""

    barn_path: Path
    barn_data_offset: int
    source: Path


class BarnArchive:
    """Indexed ``CORE.BRN`` catalog with lazy asset reads."""

    def __init__(self, data_directory: Path, entries: tuple[BarnEntry, ...]) -> None:
        """Retain an immutable catalog index without opening asset barns."""
        self.data_directory = data_directory
        self.entries = entries

    @classmethod
    def open(cls, data_directory: Path) -> BarnArchive:
        """Open the full-game catalog in *data_directory* and index its entries."""
        root = data_directory.resolve()
        if not root.is_dir():
            msg = f"GK3 data directory does not exist: {root}"
            raise BrnError(msg)

        files = _case_insensitive_files(root)
        core_path = files.get("CORE.BRN")
        if core_path is None:
            msg = f"CORE.BRN was not found in GK3 data directory: {root}"
            raise BrnError(msg)
        core = _read_file(core_path)
        directories = _read_directories(core, source=core_path)
        core_data_offset = _find_data_offset(directories, source=core_path)

        entries: list[BarnEntry] = []
        for directory in directories:
            if directory.kind != _CATALOG_DIRECTORY:
                continue
            barn_name, file_count = _read_catalog_header(
                core,
                directory.header_offset,
                source=core_path,
            )
            if barn_name:
                barn_path = files.get(barn_name.upper())
                if barn_path is None:
                    msg = f"{core_path}: referenced child barn is missing: {barn_name}"
                    raise BrnError(msg)
                barn_directories = _read_directories_from_file(barn_path)
                barn_data_offset = _find_data_offset(barn_directories, source=barn_path)
            else:
                barn_path = core_path
                barn_data_offset = core_data_offset
            entries.extend(
                _read_file_entries(
                    core,
                    directory.data_offset,
                    file_count,
                    location=_EntryLocation(
                        barn_path=barn_path,
                        barn_data_offset=barn_data_offset,
                        source=core_path,
                    ),
                )
            )

        if not entries:
            msg = f"{core_path}: catalog contains no files"
            raise BrnError(msg)
        return cls(root, tuple(entries))

    def read(self, entry: BarnEntry) -> bytes:
        """Read and decompress one previously indexed entry."""
        try:
            with entry.barn_path.open("rb") as stream:
                stream.seek(entry.offset)
                packed = stream.read(entry.size)
        except OSError as exc:
            msg = f"cannot read {entry.name} from {entry.barn_path}: {exc}"
            raise BrnError(msg) from exc
        if len(packed) != entry.size:
            msg = f"{entry.name}: truncated data in {entry.barn_path}"
            raise BrnError(msg)
        return _decompress(packed, entry)

    @contextmanager
    def reader(self) -> Iterator[Callable[[BarnEntry], bytes]]:
        """Map every referenced Barn once and yield a thread-safe entry reader.

        Extraction touches thousands of small assets. Reopening a multi-gigabyte
        Barn for every asset is disproportionately expensive on Windows; read-only
        mappings let the OS cache the archives while independent workers slice and
        decompress entries without sharing a seek cursor.
        """
        streams: list[BinaryIO] = []
        mappings: dict[Path, mmap.mmap] = {}
        try:
            for path in dict.fromkeys(entry.barn_path for entry in self.entries):
                stream = path.open("rb")
                streams.append(stream)
                mappings[path] = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
            yield lambda entry: _read_mapped_entry(entry, mappings)
        except OSError as exc:
            msg = f"cannot map GK3 Barn archives: {exc}"
            raise BrnError(msg) from exc
        finally:
            for mapping in mappings.values():
                mapping.close()
            for stream in streams:
                stream.close()


def _read_mapped_entry(entry: BarnEntry, mappings: dict[Path, mmap.mmap]) -> bytes:
    """Read and decompress one entry from an already mapped Barn."""
    mapping = mappings[entry.barn_path]
    packed = mapping[entry.offset : entry.offset + entry.size]
    if len(packed) != entry.size:
        msg = f"{entry.name}: truncated data in {entry.barn_path}"
        raise BrnError(msg)
    return _decompress(packed, entry)


def _case_insensitive_files(directory: Path) -> dict[str, Path]:
    """Index top-level files while rejecting ambiguous case-only duplicates."""
    result: dict[str, Path] = {}
    for path in directory.iterdir():
        if not path.is_file():
            continue
        key = path.name.upper()
        previous = result.get(key)
        if previous is not None:
            msg = f"ambiguous filenames in {directory}: {previous.name} and {path.name}"
            raise BrnError(msg)
        result[key] = path
    return result


def _read_file(path: Path) -> bytes:
    """Read a reasonably sized catalog file with a contextual error."""
    try:
        return path.read_bytes()
    except OSError as exc:
        msg = f"cannot read Barn archive {path}: {exc}"
        raise BrnError(msg) from exc


def _read_directories_from_file(path: Path) -> tuple[_Directory, ...]:
    """Read only a child barn's header and directory table, not its asset data."""
    try:
        with path.open("rb") as stream:
            header = stream.read(_BARN_HEADER.size)
            directory_offset = _directory_offset(header, source=path)
            stream.seek(directory_offset)
            raw_count = stream.read(_UINT32.size)
            if len(raw_count) != _UINT32.size:
                msg = f"{path}: truncated directory count"
                raise BrnError(msg)
            (count,) = _UINT32.unpack(raw_count)
            _validate_directory_count(count, source=path)
            table = stream.read(count * _DIRECTORY_HEADER.size)
    except OSError as exc:
        msg = f"cannot read Barn archive {path}: {exc}"
        raise BrnError(msg) from exc
    if len(table) != count * _DIRECTORY_HEADER.size:
        msg = f"{path}: truncated directory table"
        raise BrnError(msg)
    return _parse_directories(table, count, offset=0)


def _read_directories(data: bytes, *, source: Path) -> tuple[_Directory, ...]:
    """Read and validate a directory table from an in-memory core catalog."""
    directory_offset = _directory_offset(data, source=source)
    _require_range(data, directory_offset, _UINT32.size, source=source, label="directory count")
    (count,) = _UINT32.unpack_from(data, directory_offset)
    _validate_directory_count(count, source=source)
    table_offset = directory_offset + 4
    table_size = count * _DIRECTORY_HEADER.size
    _require_range(data, table_offset, table_size, source=source, label="directory table")
    return _parse_directories(data, count, offset=table_offset)


def _directory_offset(data: bytes, *, source: Path) -> int:
    """Validate a Barn header and return its directory-table offset."""
    _require_range(data, 0, _BARN_HEADER.size, source=source, label="Barn header")
    values = _BARN_HEADER.unpack_from(data)
    if values[0] != _BARN_MAGIC:
        msg = f"{source}: invalid Barn magic"
        raise BrnError(msg)
    return values[-1]


def _validate_directory_count(count: int, *, source: Path) -> None:
    """Reject implausible counts before multiplying or allocating."""
    if not 0 < count <= _MAX_DIRECTORY_COUNT:
        msg = f"{source}: invalid directory count {count}"
        raise BrnError(msg)


def _parse_directories(data: bytes, count: int, *, offset: int) -> tuple[_Directory, ...]:
    """Parse the fields relevant to catalog and data lookup."""
    result = []
    for index in range(count):
        values = _DIRECTORY_HEADER.unpack_from(data, offset + index * _DIRECTORY_HEADER.size)
        result.append(_Directory(kind=values[0], header_offset=values[-2], data_offset=values[-1]))
    return tuple(result)


def _find_data_offset(directories: tuple[_Directory, ...], *, source: Path) -> int:
    """Find the single data-section base used by file entry offsets."""
    matches = [
        directory.data_offset for directory in directories if directory.kind == _DATA_DIRECTORY
    ]
    if len(matches) != 1:
        msg = f"{source}: expected one Data directory, found {len(matches)}"
        raise BrnError(msg)
    return matches[0]


def _read_catalog_header(data: bytes, offset: int, *, source: Path) -> tuple[str, int]:
    """Return the child-barn name and file count from a DDir header."""
    _require_range(data, offset, _CATALOG_HEADER.size, source=source, label="catalog header")
    values = _CATALOG_HEADER.unpack_from(data, offset)
    barn_name = _decode_c_string(values[0], source=source, label="child barn name")
    if barn_name and (Path(barn_name).name != barn_name or "/" in barn_name or "\\" in barn_name):
        msg = f"{source}: unsafe child barn name {barn_name!r}"
        raise BrnError(msg)
    return barn_name, values[-1]


def _read_file_entries(
    data: bytes,
    offset: int,
    count: int,
    *,
    location: _EntryLocation,
) -> list[BarnEntry]:
    """Read variable-length catalog records from the core barn."""
    result = []
    barn_size = location.barn_path.stat().st_size
    cursor = offset
    for index in range(count):
        _require_range(
            data,
            cursor,
            _FILE_HEADER.size,
            source=location.source,
            label="file header",
        )
        values = _FILE_HEADER.unpack_from(data, cursor)
        size, relative_offset, _checksum, _kind, compression, name_length = values
        cursor += _FILE_HEADER.size
        _require_range(
            data,
            cursor,
            name_length + 1,
            source=location.source,
            label="asset name",
        )
        name_bytes = data[cursor : cursor + name_length]
        if data[cursor + name_length] != 0:
            msg = f"{location.source}: catalog entry {index} has an unterminated name"
            raise BrnError(msg)
        name = _decode_c_string(
            name_bytes,
            source=location.source,
            label=f"catalog entry {index}",
        )
        cursor += name_length + 1
        absolute_offset = location.barn_data_offset + relative_offset
        if absolute_offset > barn_size or size > barn_size - absolute_offset:
            msg = f"{location.source}: {name} points outside {location.barn_path.name}"
            raise BrnError(msg)
        result.append(
            BarnEntry(
                name=name,
                barn_path=location.barn_path,
                offset=absolute_offset,
                size=size,
                compression=compression,
            )
        )
    return result


def _decode_c_string(data: bytes, *, source: Path, label: str) -> str:
    """Decode the ASCII identifiers used throughout the GK3 catalog."""
    value = data.split(b"\0", 1)[0]
    try:
        return value.decode("ascii")
    except UnicodeDecodeError as exc:
        msg = f"{source}: {label} is not ASCII"
        raise BrnError(msg) from exc


def _decompress(packed: bytes, entry: BarnEntry) -> bytes:
    """Apply the compression tag used by one catalog entry."""
    if entry.compression in {0, 3}:
        return packed
    if entry.compression not in {1, 2}:
        msg = f"{entry.name}: unsupported Barn compression {entry.compression}"
        raise BrnError(msg)
    if len(packed) < _COMPRESSED_PREFIX_SIZE:
        msg = f"{entry.name}: truncated compressed-data prefix"
        raise BrnError(msg)
    (expected_size,) = struct.unpack_from("<I", packed)
    if not 0 < expected_size <= _MAX_DECOMPRESSED_SIZE:
        msg = f"{entry.name}: invalid decompressed size {expected_size}"
        raise BrnError(msg)
    compressed = packed[_COMPRESSED_PREFIX_SIZE:]
    if entry.compression == 1:
        try:
            result = zlib.decompress(compressed)
        except zlib.error as exc:
            msg = f"{entry.name}: zlib decompression failed: {exc}"
            raise BrnError(msg) from exc
    else:
        result = _decompress_lzo(compressed, expected_size, name=entry.name)
    if len(result) != expected_size:
        msg = f"{entry.name}: decompressed to {len(result)} bytes, expected {expected_size}"
        raise BrnError(msg)
    return bytes(result)


def _decompress_lzo(data: bytes, expected_size: int, *, name: str) -> bytes:
    """Decode the LZO geometry/images shared by extraction and usage analysis."""
    try:
        return bytes(lzokay.decompress(data, expected_size))
    except lzokay.LzokayError as exc:
        msg = f"{name}: LZO decompression failed: {exc}"
        raise BrnError(msg) from exc


def _require_range(data: bytes, offset: int, size: int, *, source: Path, label: str) -> None:
    """Reject negative, overflowing, or truncated byte ranges."""
    if offset < 0 or size < 0 or offset > len(data) or size > len(data) - offset:
        msg = f"{source}: truncated {label}"
        raise BrnError(msg)
