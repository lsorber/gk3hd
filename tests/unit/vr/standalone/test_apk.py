"""APK identity checks do not require an Android SDK or run APK code."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING
from zipfile import ZipFile

import pytest

from gk3hd.vr.standalone.apk import APPLICATION_ID, manifest_package, require_player_apk

if TYPE_CHECKING:
    from pathlib import Path


def _encoded_length(size: int, *, utf8: bool) -> bytes:
    if utf8:
        return bytes([size]) if size < 128 else bytes([(size >> 8) | 0x80, size & 255])
    return struct.pack("<H", size)


def binary_manifest(package: str = APPLICATION_ID, *, utf8: bool = True, raw: bool = True) -> bytes:
    """Minimal binary root/string fixtures, not a distributable executable APK."""
    strings = ["manifest", "package", package]
    payload = bytearray()
    offsets = []
    for text in strings:
        offsets.append(len(payload))
        encoded = text.encode("utf-8" if utf8 else "utf-16le")
        payload.extend(_encoded_length(len(text), utf8=utf8))
        if utf8:
            payload.extend(_encoded_length(len(encoded), utf8=True))
        payload.extend(encoded)
        payload.extend(b"\0" if utf8 else b"\0\0")
    start = 28 + len(offsets) * 4
    pool = struct.pack(
        "<HHIIIIII", 1, 28, start + len(payload), len(strings), 0, 256 if utf8 else 0, start, 0
    )
    pool += struct.pack("<3I", *offsets) + payload
    extension = struct.pack("<IIHHHHHH", 0xFFFFFFFF, 0, 20, 20, 1, 0, 0, 0)
    attribute = struct.pack("<IIIHBBI", 0xFFFFFFFF, 1, 2 if raw else 0xFFFFFFFF, 8, 0, 3, 2)
    element = struct.pack("<HHIII", 0x0102, 16, 16 + len(extension) + len(attribute), 1, 0xFFFFFFFF)
    element += extension + attribute
    return struct.pack("<HHI", 3, 8, 8 + len(pool) + len(element)) + pool + element


@pytest.mark.parametrize("utf8", [True, False])
@pytest.mark.parametrize("raw", [True, False])
def test_binary_package_identity(utf8: bool, raw: bool) -> None:
    assert manifest_package(binary_manifest(utf8=utf8, raw=raw)) == APPLICATION_ID


def test_extended_utf8_length() -> None:
    package = "com." + "a" * 260
    assert manifest_package(binary_manifest(package)) == package


@pytest.mark.parametrize("length", [0, 4, 8, 16, 40, 80, 130])
def test_truncated_manifests_are_rejected(length: int) -> None:
    with pytest.raises(ValueError, match=r"[Aa]ndroid manifest"):
        manifest_package(binary_manifest()[:length])


def test_corrupt_chunk_does_not_escape_bounds() -> None:
    data = bytearray(binary_manifest())
    struct.pack_into("<I", data, 12, 0xFFFFFFFF)
    with pytest.raises(ValueError, match="bounds"):
        manifest_package(bytes(data))


def test_typed_package_cannot_disagree_with_raw_identity() -> None:
    data = bytearray(binary_manifest())
    struct.pack_into("<I", data, len(data) - 4, 1)
    with pytest.raises(ValueError, match="Conflicting"):
        manifest_package(bytes(data))


@pytest.mark.parametrize(
    "package", ["com.winlator", "com.example.personal", "org.gk3hd.standalone.probe"]
)
def test_other_apps_cannot_be_replaced(tmp_path: Path, package: str) -> None:
    apk = tmp_path / "wrong.apk"
    with ZipFile(apk, "w") as archive:
        archive.writestr("AndroidManifest.xml", binary_manifest(package))
    with pytest.raises(ValueError, match="other apps were preserved"):
        require_player_apk(apk)


def test_apk_identity_is_checked_without_executing_payload(tmp_path: Path) -> None:
    apk = tmp_path / "player.apk"
    with ZipFile(apk, "w") as archive:
        archive.writestr("AndroidManifest.xml", binary_manifest())
        archive.writestr("classes.dex", b"not executed")
    require_player_apk(apk)


def test_invalid_zip_has_actionable_error(tmp_path: Path) -> None:
    apk = tmp_path / "broken.apk"
    apk.write_bytes(b"not an APK")
    with pytest.raises(ValueError, match="not a valid archive"):
        require_player_apk(apk)
