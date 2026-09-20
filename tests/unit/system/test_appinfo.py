"""Binary Steam cache bounds, version handling and selective metadata decoding."""

import struct
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from gk3hd.system import appinfo
from gk3hd.system.appinfo import AppInfoError, read_appinfo
from tests.unit.system.appinfo_fixture import cache_bytes

if TYPE_CHECKING:
    from gk3hd.system.steam import VdfValue


@pytest.mark.parametrize("version", [39, 40, 41])
def test_supported_versions_only_decode_requested_apps(tmp_path: Path, version: int) -> None:
    path = tmp_path / "appinfo.vdf"
    entry: dict[str, VdfValue] = {"appinfo": {"appid": "891390", "extended": {"tool": "é"}}}
    path.write_bytes(cache_bytes({12: {"ignored": "value"}, 891390: entry}, version))
    assert read_appinfo(path, frozenset({891390})) == {891390: entry}
    assert read_appinfo(path, frozenset({99})) == {}


@pytest.mark.parametrize("length", range(16))
def test_truncated_headers(tmp_path: Path, length: int) -> None:
    path = tmp_path / "appinfo.vdf"
    path.write_bytes(cache_bytes({})[:length])
    with pytest.raises(AppInfoError):
        read_appinfo(path, frozenset())


@pytest.mark.parametrize(
    ("offset", "replacement"),
    [
        (0, struct.pack("<I", 0x07564430)),
        (8, struct.pack("<Q", 1)),
        (8, struct.pack("<Q", 0xFFFFFFFF)),
        (20, struct.pack("<I", 1)),
        (20, struct.pack("<I", 0xFFFFFFFF)),
        (84, b"\xff"),  # Unsupported value kind.
        (85, struct.pack("<I", 0xFFFFFFFF)),  # Out-of-range interned key.
        (90, b"\xff"),  # Invalid UTF-8 string value.
    ],
)
def test_malformed_records(tmp_path: Path, offset: int, replacement: bytes) -> None:
    path = tmp_path / "appinfo.vdf"
    data = bytearray(cache_bytes({497360: {"name": "hello"}}))
    data[offset : offset + len(replacement)] = replacement
    path.write_bytes(data)
    with pytest.raises(AppInfoError):
        read_appinfo(path, frozenset({497360}))


def test_malformed_unselected_payload_is_not_parsed(tmp_path: Path) -> None:
    path = tmp_path / "appinfo.vdf"
    data = bytearray(cache_bytes({1: {"bad": "unused"}, 2: {"good": "selected"}}))
    data[84] = 0xFF
    path.write_bytes(data)
    assert read_appinfo(path, frozenset({2})) == {2: {"good": "selected"}}


def test_size_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "appinfo.vdf"
    path.write_bytes(cache_bytes({1: {"name": "value"}}))
    monkeypatch.setattr(appinfo, "_MAX_CACHE_BYTES", 16)
    with pytest.raises(AppInfoError, match="size"):
        read_appinfo(path, frozenset({1}))


@pytest.mark.parametrize(
    ("kind", "payload", "expected"),
    [
        (2, struct.pack("<i", -1), "-1"),
        (3, struct.pack("<f", 1.5), "1.5"),
        (4, struct.pack("<I", 2), "2"),
        (5, "é中".encode("utf-16-le") + b"\0\0", "é中"),
        (6, struct.pack("<I", 3), "3"),
        (7, struct.pack("<Q", 2**40), str(2**40)),
        (10, struct.pack("<q", -(2**40)), str(-(2**40))),
    ],
)
def test_scalar_types(tmp_path: Path, kind: int, payload: bytes, expected: str) -> None:
    path = tmp_path / "appinfo.vdf"
    record = bytes(60) + bytes([kind]) + b"value\0" + payload + b"\x08"
    path.write_bytes(struct.pack("<IIII", 0x07564428, 1, 497360, len(record)) + record + bytes(4))
    assert read_appinfo(path, frozenset({497360})) == {497360: {"value": expected}}


def test_nesting_bound(tmp_path: Path) -> None:
    path = tmp_path / "appinfo.vdf"
    nested: dict[str, VdfValue] = {}
    for _ in range(66):
        nested = {"child": nested}
    path.write_bytes(cache_bytes({1: nested}))
    with pytest.raises(AppInfoError, match="nesting"):
        read_appinfo(path, frozenset({1}))
