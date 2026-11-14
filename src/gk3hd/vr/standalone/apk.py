"""Read the APK package identity before allowing an Android app installation.

This is not APK signature verification. Android verifies the signature during
installation, and development callers must supply an APK they trust.
"""

from __future__ import annotations

import json
import struct
from typing import TYPE_CHECKING
from zipfile import BadZipFile, ZipFile

from gk3hd.system.files import is_sha256

if TYPE_CHECKING:
    from pathlib import Path

APPLICATION_ID = "org.gk3hd.standalone"
MAX_APK_BYTES = 256 * 1024**2
_MAX_MANIFEST = 1024**2
_XML = 0x0003
_STRINGS = 0x0001
_START_ELEMENT = 0x0102
_STRING_TYPE = 3
_UTF8 = 0x100
_NONE = 0xFFFFFFFF
_MAX_STRINGS = 100_000
_NODE_HEADER = 16
_VALUE_SIZE = 8
COMPONENT_ASSET = "assets/gk3hd-components.sha256"
COMPONENT_UPDATE_ASSET = "assets/gk3hd-component-update"
COMPONENT_FILES = frozenset({"openxr_wxr32.dll", "gk3hd-wine-launcher.exe"})
_MAX_COMPONENTS = 512
_COMPONENT_COLUMNS = 2


def _length(data: bytes, offset: int, *, utf8: bool) -> tuple[int, int]:
    unit, mask, shift = (1, 0x80, 8) if utf8 else (2, 0x8000, 16)
    if offset + unit > len(data):
        msg = "Truncated Android string length"
        raise ValueError(msg)
    first = int.from_bytes(data[offset : offset + unit], "little")
    offset += unit
    if not first & mask:
        return first, offset
    if offset + unit > len(data):
        msg = "Truncated extended Android string length"
        raise ValueError(msg)
    second = int.from_bytes(data[offset : offset + unit], "little")
    return ((first & (mask - 1)) << shift) | second, offset + unit


def _strings(chunk: bytes, header: int) -> tuple[str, ...]:
    minimum_header = 28
    if header < minimum_header:
        msg = "Invalid Android string pool"
        raise ValueError(msg)
    count, styles, flags, start, _end = struct.unpack_from("<IIIII", chunk, 8)
    table_end = header + (count + styles) * 4
    if count > _MAX_STRINGS or not table_end <= start <= len(chunk):
        msg = "Android string pool exceeds manifest bounds"
        raise ValueError(msg)
    utf8 = bool(flags & _UTF8)
    result = []
    for index in range(count):
        offset = start + struct.unpack_from("<I", chunk, header + index * 4)[0]
        if utf8:
            _characters, offset = _length(chunk, offset, utf8=True)
        size, offset = _length(chunk, offset, utf8=utf8)
        size *= 1 if utf8 else 2
        terminator = 1 if utf8 else 2
        if offset + size + terminator > len(chunk) or any(
            chunk[offset + size : offset + size + terminator]
        ):
            msg = "Android string is truncated or unterminated"
            raise ValueError(msg)
        result.append(chunk[offset : offset + size].decode("utf-8" if utf8 else "utf-16le"))
    return tuple(result)


def _package_attribute(chunk: bytes, header: int, strings: tuple[str, ...]) -> str:
    extension_size, attribute_size = 20, 20
    if header < _NODE_HEADER or header + extension_size > len(chunk):
        msg = "Truncated Android manifest element"
        raise ValueError(msg)
    _namespace, name, start, width, count = struct.unpack_from("<IIHHH", chunk, header)
    if name >= len(strings) or strings[name] != "manifest":
        msg = "The APK's first element is not a manifest"
        raise ValueError(msg)
    base = header + start
    if start < extension_size or width != attribute_size or base + count * width > len(chunk):
        msg = "Invalid Android manifest attributes"
        raise ValueError(msg)
    packages = []
    for index in range(count):
        namespace, name, raw, size, _reserved, kind, value = struct.unpack_from(
            "<IIIHBBI", chunk, base + index * width
        )
        if name >= len(strings):
            msg = "Invalid Android attribute name"
            raise ValueError(msg)
        if namespace != _NONE or strings[name] != "package":
            continue
        if size != _VALUE_SIZE or kind != _STRING_TYPE or value >= len(strings):
            msg = "Invalid Android package attribute"
            raise ValueError(msg)
        if raw != _NONE and (raw >= len(strings) or strings[raw] != strings[value]):
            msg = "Conflicting raw and typed Android package identity"
            raise ValueError(msg)
        packages.append(strings[value])
    if len(packages) != 1:
        msg = "The APK must declare exactly one package identity"
        raise ValueError(msg)
    return packages[0]


def manifest_package(data: bytes) -> str:
    """Decode only the bounded binary XML fields needed to identify an APK."""
    chunk_header = 8
    if len(data) < chunk_header or len(data) > _MAX_MANIFEST:
        msg = "Invalid Android manifest size"
        raise ValueError(msg)
    kind, header, length = struct.unpack_from("<HHI", data)
    if kind != _XML or header != chunk_header or length != len(data):
        msg = "The APK requires a complete binary Android manifest"
        raise ValueError(msg)
    offset = header
    strings: tuple[str, ...] | None = None
    while offset + chunk_header <= length:
        kind, header, size = struct.unpack_from("<HHI", data, offset)
        if header < chunk_header or size < header or offset + size > length:
            msg = "Invalid Android manifest chunk bounds"
            raise ValueError(msg)
        chunk = data[offset : offset + size]
        if kind == _STRINGS:
            if strings is not None:
                msg = "Duplicate Android manifest string pool"
                raise ValueError(msg)
            strings = _strings(chunk, header)
        elif kind == _START_ELEMENT:
            if strings is None:
                msg = "Android manifest has no string pool"
                raise ValueError(msg)
            return _package_attribute(chunk, header, strings)
        offset += size
    msg = "Android manifest has no root element"
    raise ValueError(msg)


def require_player_apk(path: Path) -> None:
    """Reject another app's APK before ADB can replace that app's installation."""
    if not path.is_file() or path.stat().st_size > MAX_APK_BYTES:
        msg = "Missing or oversized standalone APK"
        raise ValueError(msg)
    try:
        with ZipFile(path) as archive:
            entries = [
                entry for entry in archive.infolist() if entry.filename == "AndroidManifest.xml"
            ]
            if len(entries) != 1 or entries[0].file_size > _MAX_MANIFEST:
                msg = "The APK must contain one bounded Android manifest"
                raise ValueError(msg)
            package = manifest_package(archive.read(entries[0]))
    except BadZipFile as error:
        msg = "The standalone APK is not a valid archive"
        raise ValueError(msg) from error
    if package != APPLICATION_ID:
        msg = f"Refusing APK for {package}: expected {APPLICATION_ID}; other apps were preserved"
        raise ValueError(msg)


def player_components(path: Path) -> dict[str, str]:
    """Read the bounded producer identities embedded by the Android build."""
    try:
        with ZipFile(path) as archive:
            entries = [entry for entry in archive.infolist() if entry.filename == COMPONENT_ASSET]
            if len(entries) != 1 or entries[0].file_size > _MAX_COMPONENTS:
                msg = "Standalone APK has no valid component pairing; rebuild the player"
                raise ValueError(msg)
            lines = archive.read(entries[0]).decode("ascii").splitlines()
    except (BadZipFile, UnicodeError) as error:
        msg = "Invalid standalone APK component pairing"
        raise ValueError(msg) from error
    result: dict[str, str] = {}
    for line in lines:
        fields = line.split()
        if (
            len(fields) != _COMPONENT_COLUMNS
            or not is_sha256(fields[0])
            or fields[1] not in COMPONENT_FILES
            or fields[1] in result
        ):
            msg = "Invalid standalone APK component pairing"
            raise ValueError(msg)
        result[fields[1]] = fields[0]
    if set(result) != COMPONENT_FILES:
        msg = "Incomplete standalone APK component pairing"
        raise ValueError(msg)
    return result


def require_player_components(apk: Path, bundle: Path) -> None:
    """Match the already inspected private bundle before any headset mutation."""
    expected = player_components(apk)
    with ZipFile(bundle) as archive:
        metadata = archive.getinfo("bundle.json")
        if metadata.file_size > 2 * 1024**2:
            msg = "Oversized standalone manifest"
            raise ValueError(msg)
        inventory = json.loads(archive.read(metadata))["files"]
    for name, digest in expected.items():
        entry = inventory.get(f"game/{name}") if isinstance(inventory, dict) else None
        if not isinstance(entry, dict) or entry.get("sha256") != digest:
            msg = (
                f"Standalone APK and game bundle do not match: {name}. "
                "Prepare the bundle with this player build before installing; no app was installed"
            )
            raise ValueError(msg)


def supports_component_update(
    apk: Path, *, verification_only: bool = False, additions: bool = False
) -> bool:
    """Require the target APK to advertise its component archive schema."""
    with ZipFile(apk) as archive:
        try:
            entry = archive.getinfo(COMPONENT_UPDATE_ASSET)
        except KeyError:
            return False
        if additions:
            versions = (b"4",)
        else:
            versions = (b"3", b"4") if verification_only else (b"2", b"3", b"4")
        return entry.file_size == 1 and archive.read(entry) in versions
