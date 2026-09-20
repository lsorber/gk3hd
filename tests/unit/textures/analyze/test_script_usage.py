from __future__ import annotations

import json
import struct
from typing import TYPE_CHECKING

import pytest
from PIL import Image

import gk3hd.textures.upscale.service as texture_upscale
from gk3hd.textures.analyze.manifest import analyze_directory
from gk3hd.textures.analyze.script_usage import script_data_textures
from gk3hd.textures.analyze.usage import analyze_usage
from gk3hd.textures.model import TEXTURE_MANIFEST_SCHEMA_VERSION, TextureKind
from gk3hd.textures.workspace import analysis_file
from tests.unit.textures.test_extraction import _write_barn_fixture

if TYPE_CHECKING:
    from pathlib import Path


def _section(name: bytes, records: list[bytes]) -> bytes:
    offsets = []
    content = b""
    for record in records:
        offsets.append(len(content))
        content += record
    header = 28 + len(records) * 4
    return (
        name.ljust(12, b"\0")
        + struct.pack("<4I", header, header, len(content), len(records))
        + b"".join(struct.pack("<I", offset) for offset in offsets)
        + content
    )


def _import(name: bytes) -> bytes:
    return struct.pack("<H", len(name)) + name + b"\0\x00\x05\x03\x02\x02\x02\x02"


def _call(*, count: int = 5, target: int = 0, string: int = 0) -> bytes:
    return (
        b"\x15"
        + struct.pack("<I", string)
        + b"\x33"
        + b"".join(b"\x14" + struct.pack("<f", value) for value in (100, 200, -5, -10))
        + b"\x13"
        + struct.pack("<I", count)
        + b"\x02"
        + struct.pack("<I", target)
    )


def _script(code: bytes, *, name: bytes = b"regions", setter: bytes = b"SetBoundaryMap") -> bytes:
    sections = [
        _section(b"SysImports", [_import(setter), _import(b"OtherFunction")]),
        _section(b"StringConsts", [name + b"\0", b"SetBoundaryMap\0"]),
        _section(b"Code", [code]),
    ]
    header = 28 + 4 * len(sections)
    offsets = [sum(map(len, sections[:index])) for index in range(len(sections))]
    return (
        b"GK3Sheep"
        + struct.pack("<5I", 0, header, header, sum(map(len, sections)), len(sections))
        + b"".join(struct.pack("<I", offset) for offset in offsets)
        + b"".join(sections)
    )


@pytest.mark.parametrize("name", [b"regions", b"Regions.BMP", b"F_CUSTOM_MAP"])
def test_literal_call_establishes_usage_independent_of_filename(name: bytes) -> None:
    expected = name.decode().upper().removesuffix(".BMP") + ".BMP"
    assert script_data_textures(_script(_call(), name=name), {expected}) == {expected}
    assert script_data_textures(_script(_call(), name=name), set()) == set()


@pytest.mark.parametrize(
    "code",
    [b"\x00", _call(count=4), _call(target=1), b"\x12" + _call()[1:], b"\x14" + _call()],
)
def test_strings_imports_or_operand_bytes_alone_are_not_bindings(code: bytes) -> None:
    assert not script_data_textures(_script(code), {"REGIONS.BMP"})


@pytest.mark.parametrize("name", [b"../regions", b"dir/regions", b"dir\\regions", b""])
def test_only_flat_resource_names_are_accepted(name: bytes) -> None:
    assert not script_data_textures(_script(_call(), name=name), {name.decode().upper() + ".BMP"})


def test_other_native_import_does_not_qualify() -> None:
    assert not script_data_textures(_script(_call(), setter=b"NotSetBoundaryMap"), {"REGIONS.BMP"})
    assert not script_data_textures(b"SetBoundaryMap(regions)", {"REGIONS.BMP"})


@pytest.mark.parametrize("fault", ["truncated", "header", "opcode", "string", "operand"])
def test_corrupt_binding_metadata_fails_closed(fault: str) -> None:
    payload = bytearray(_script(_call()))
    if fault == "truncated":
        del payload[-1:]
    elif fault == "header":
        struct.pack_into("<I", payload, 12, 0xFFFFFFFF)
    elif fault == "opcode":
        payload = bytearray(_script(b"\xff" + _call()))
    elif fault == "string":
        payload = bytearray(_script(_call(string=10000)))
    else:
        payload = bytearray(_script(_call() + b"\x15"))
    with pytest.raises(ValueError, match="compiled Sheep boundary-map binding"):
        script_data_textures(bytes(payload), {"REGIONS.BMP"})


def test_archive_script_binding_overrides_font_and_color_heuristics(tmp_path: Path) -> None:
    data = tmp_path / "Data"
    name = "F_CUSTOM_MAP.BMP"
    _write_barn_fixture(
        data,
        core_assets=[
            (name, b"pixels not needed", 0),
            ("EVENT.SHP", _script(_call(), name=b"f_custom_map"), 1),
        ],
    )
    usage = analyze_usage(data)
    assert usage.data == {name}
    source = tmp_path / "original"
    source.mkdir()
    Image.new("RGB", (8, 8), (255, 0, 255)).save(source / name)
    feature = analyze_directory(source, usage=usage).manifest.textures[0]
    assert feature.kind is TextureKind.DATA
    assert not feature.font_atlas
    assert not feature.alphatest


@pytest.mark.integration
def test_old_analysis_refreshes_script_bound_data_without_ai(tmp_path: Path) -> None:
    name = "REGIONS.BMP"
    _write_barn_fixture(
        tmp_path / "Data",
        core_assets=[
            (name, b"pixels not needed", 0),
            ("EVENT.SHP", _script(_call()), 1),
        ],
    )
    source = tmp_path / "gk3hd" / "textures" / "original"
    source.mkdir(parents=True)
    image = Image.new("RGB", (8, 8), (255, 0, 255))
    image.putpixel((4, 4), (255, 0, 0))
    image.save(source / name)
    original = (source / name).read_bytes()
    manifest = analysis_file(source)
    manifest.write_text(
        json.dumps({"schema_version": 128, "textures": [{"name": name, "kind": "color"}]}),
        encoding="utf-8",
    )
    output = tmp_path / "upscaled"
    output.mkdir()
    Image.new("RGB", (32, 32)).save(output / "REGIONS.PNG")
    report = texture_upscale.upscale(source, output)
    assert (report.textures, report.created, report.excluded) == (1, 0, 1)
    assert json.loads(manifest.read_text(encoding="utf-8"))["schema_version"] == (
        TEXTURE_MANIFEST_SCHEMA_VERSION
    )
    assert not list(output.glob("*.PNG"))
    assert (source / name).read_bytes() == original
