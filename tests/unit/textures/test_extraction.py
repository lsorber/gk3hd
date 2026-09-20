from __future__ import annotations

import struct
import zlib
from typing import TYPE_CHECKING

import lzokay
import pytest
from typer.testing import CliRunner

from gk3hd.cli import app
from gk3hd.textures.bmp import inspect_bmp
from gk3hd.textures.brn import BarnArchive, BrnError
from gk3hd.textures.extraction import extract_bmps
from gk3hd.textures.workspace import source_directory

if TYPE_CHECKING:
    from pathlib import Path

_BARN_HEADER = struct.Struct("<8sHHHHII")
_DIRECTORY_HEADER = struct.Struct("<4sHHIIIII")
_CATALOG_HEADER = struct.Struct("<32s4s40sII")
_FILE_HEADER = struct.Struct("<IIIBBB")


def _standard_bmp(red: int = 1, green: int = 2, blue: int = 3) -> bytes:
    pixels = bytes((blue, green, red, 0))
    header = struct.pack("<2sIHHI", b"BM", 54 + len(pixels), 0, 0, 54)
    dib = struct.pack("<IiiHHIIiiII", 40, 1, 1, 1, 24, 0, len(pixels), 0, 0, 0, 0)
    return header + dib + pixels


def _proprietary_bmp() -> bytes:
    # Two top-down rows of three RGB565 pixels plus GK3's odd-width padding.
    top = (0xF800, 0x07E0, 0x001F, 0)
    bottom = (0xFFFF, 0, 0x8410, 0)
    return struct.pack("<4sHH", b"61nM", 2, 3) + struct.pack("<8H", *top, *bottom)


def _packed(payload: bytes, compression: int) -> bytes:
    if compression == 0:
        return payload
    compressed = zlib.compress(payload) if compression == 1 else lzokay.compress(payload)
    return struct.pack("<II", len(payload), 0) + compressed


def _file_table(assets: list[tuple[str, bytes, int]]) -> tuple[bytes, bytes]:
    table = bytearray()
    data = bytearray()
    for name, payload, compression in assets:
        packed = _packed(payload, compression)
        encoded_name = name.encode("ascii")
        table.extend(
            _FILE_HEADER.pack(
                len(packed),
                len(data),
                0,
                0,
                compression,
                len(encoded_name),
            )
        )
        table.extend(encoded_name + b"\0")
        data.extend(packed)
    return bytes(table), bytes(data)


def _catalog_header(barn_name: str, count: int) -> bytes:
    encoded = barn_name.encode("ascii")
    return _CATALOG_HEADER.pack(
        encoded + b"\0" * (32 - len(encoded)),
        b"TEST",
        b"fixture" + b"\0" * 33,
        0,
        count,
    )


def _write_barn_fixture(
    directory: Path,
    *,
    core_assets: list[tuple[str, bytes, int]] | None = None,
    child_assets: list[tuple[str, bytes, int]] | None = None,
) -> None:
    core_assets = core_assets or []
    child_assets = child_assets or []
    directory.mkdir()

    child_table, child_data = _file_table(child_assets)
    child_directory_offset = _BARN_HEADER.size
    child_data_offset = child_directory_offset + 4 + _DIRECTORY_HEADER.size
    child = (
        _BARN_HEADER.pack(
            b"GK3!Barn", 0, 0, 0, 0, child_data_offset + len(child_data), child_directory_offset
        )
        + struct.pack("<I", 1)
        + _DIRECTORY_HEADER.pack(b"ataD", 0, 0, 0, 0, 0, 0, child_data_offset)
        + child_data
    )
    (directory / "CHILD.BRN").write_bytes(child)

    core_table, core_data = _file_table(core_assets)
    directory_offset = _BARN_HEADER.size
    directory_count = 3
    directories_end = directory_offset + 4 + directory_count * _DIRECTORY_HEADER.size
    core_catalog_offset = directories_end
    child_catalog_offset = core_catalog_offset + _CATALOG_HEADER.size
    core_table_offset = child_catalog_offset + _CATALOG_HEADER.size
    child_table_offset = core_table_offset + len(core_table)
    core_data_offset = child_table_offset + len(child_table)
    core = (
        _BARN_HEADER.pack(
            b"GK3!Barn",
            0,
            0,
            0,
            0,
            core_data_offset + len(core_data),
            directory_offset,
        )
        + struct.pack("<I", directory_count)
        + _DIRECTORY_HEADER.pack(b"ataD", 0, 0, 0, 0, 0, 0, core_data_offset)
        + _DIRECTORY_HEADER.pack(b"riDD", 0, 0, 0, 0, 0, core_catalog_offset, core_table_offset)
        + _DIRECTORY_HEADER.pack(b"riDD", 0, 0, 0, 0, 0, child_catalog_offset, child_table_offset)
        + _catalog_header("", len(core_assets))
        + _catalog_header("CHILD.BRN", len(child_assets))
        + core_table
        + child_table
        + core_data
    )
    (directory / "CORE.BRN").write_bytes(core)


def test_extracts_all_compression_and_bitmap_variants(tmp_path: Path) -> None:
    data = tmp_path / "Data"
    standard = _standard_bmp()
    zlib_standard = _standard_bmp(4, 5, 6)
    _write_barn_fixture(
        data,
        core_assets=[("PLAIN.BMP", standard, 0), ("ZLIB.BMP", zlib_standard, 1)],
        child_assets=[("ODD.BMP", _proprietary_bmp(), 2)],
    )
    output = tmp_path / "textures"

    report = extract_bmps(data, output)

    assert report.extracted == 3
    assert report.copied_standard == 2
    assert report.converted_proprietary == 1
    assert report.skipped == 0
    assert (output / "PLAIN.BMP").read_bytes() == standard
    assert (output / "ZLIB.BMP").read_bytes() == zlib_standard
    info = inspect_bmp(output / "ODD.BMP")
    assert (info.width, info.height, info.bits_per_pixel) == (3, 2, 24)
    assert info.top_left_rgb == (255, 0, 0)


def test_skips_existing_outputs_and_can_overwrite(tmp_path: Path) -> None:
    data = tmp_path / "Data"
    expected = _standard_bmp()
    _write_barn_fixture(data, core_assets=[("ONE.BMP", expected, 0)])
    output = tmp_path / "textures"
    output.mkdir()
    destination = output / "ONE.BMP"
    destination.write_bytes(b"existing")

    skipped = extract_bmps(data, output)
    replaced = extract_bmps(data, output, overwrite=True)

    assert skipped.skipped == 1
    assert skipped.extracted == 0
    assert replaced.extracted == 1
    assert destination.read_bytes() == expected


def test_creates_explicit_dos_name_before_conflicting_long_name(tmp_path: Path) -> None:
    data = tmp_path / "Data"
    bitmap = _standard_bmp()
    _write_barn_fixture(
        data,
        core_assets=[("FLOORTILE.BMP", bitmap, 0), ("FLOORT~1.BMP", bitmap, 0)],
    )
    output = tmp_path / "textures"

    report = extract_bmps(data, output)

    assert report.extracted == 2
    assert {path.name.upper() for path in output.iterdir()} == {
        "FLOORTILE.BMP",
        "FLOORT~1.BMP",
    }


def test_never_overwrites_a_long_file_through_its_ntfs_alias(tmp_path: Path) -> None:
    data = tmp_path / "Data"
    bitmap = _standard_bmp()
    _write_barn_fixture(data, core_assets=[("FLOORT~1.BMP", bitmap, 0)])
    output = tmp_path / "textures"
    output.mkdir()
    long_name = output / "FLOORTILE.BMP"
    long_name.write_bytes(b"keep me")
    alias = output / "FLOORT~1.BMP"
    if not alias.exists():
        pytest.skip("filesystem does not generate NTFS 8.3 aliases")

    with pytest.raises(BrnError, match="NTFS short-name alias"):
        extract_bmps(data, output, overwrite=True)

    assert long_name.read_bytes() == b"keep me"


def test_rejects_duplicate_flat_names_before_writing(tmp_path: Path) -> None:
    data = tmp_path / "Data"
    bitmap = _standard_bmp()
    _write_barn_fixture(
        data,
        core_assets=[("SAME.BMP", bitmap, 0)],
        child_assets=[("same.bmp", bitmap, 0)],
    )
    output = tmp_path / "textures"

    with pytest.raises(BrnError, match="duplicate BMP catalog name"):
        extract_bmps(data, output)

    assert not output.exists()


def test_reports_missing_referenced_child_barn(tmp_path: Path) -> None:
    data = tmp_path / "Data"
    _write_barn_fixture(data, child_assets=[("ONE.BMP", _standard_bmp(), 0)])
    (data / "CHILD.BRN").unlink()

    with pytest.raises(BrnError, match="referenced child barn is missing"):
        BarnArchive.open(data)


def test_rejects_malformed_proprietary_payload(tmp_path: Path) -> None:
    data = tmp_path / "Data"
    _write_barn_fixture(data, core_assets=[("BAD.BMP", b"61nM\x01\x00\x01\x00", 0)])

    with pytest.raises(BrnError, match="payload is 8 bytes, expected 12"):
        extract_bmps(data, tmp_path / "textures")


def test_extract_bmps_cli_reports_counts(tmp_path: Path) -> None:
    data = tmp_path / "Data"
    _write_barn_fixture(data, core_assets=[("ONE.BMP", _standard_bmp(), 0)])
    (tmp_path / "GK3.exe").write_bytes(b"fixture")
    output = tmp_path / "textures"

    result = CliRunner().invoke(
        app,
        ["textures", "extract", str(output), "--game-dir", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert (output / "ONE.BMP").is_file()
    assert "Extracted" in result.output
    assert "1 textures" in result.output


def test_extract_cli_defaults_to_game_workspace(tmp_path: Path) -> None:
    data = tmp_path / "Data"
    _write_barn_fixture(data, core_assets=[("ONE.BMP", _standard_bmp(), 0)])
    (tmp_path / "GK3.exe").write_bytes(b"fixture")

    result = CliRunner().invoke(
        app,
        ["textures", "extract", "--game-dir", str(tmp_path)],
    )

    expected = source_directory(tmp_path)
    assert result.exit_code == 0, result.output
    assert (expected / "ONE.BMP").is_file()
    assert str(expected) in result.output.replace("\n", "")
