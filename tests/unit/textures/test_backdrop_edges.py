"""Scene-edge correction preserves geometry and real texture repetition."""

import struct
from pathlib import Path

import pytest

from gk3hd.textures.install.backdrop_edges import backdrop_edge_fixes, inset_backdrop_uvs
from tests.unit.textures.test_extraction import _write_barn_fixture


def _bsp(*, repeat_v: bool = False, shared: bool = False) -> tuple[bytes, int]:
    surfaces = [b"FULLTREE01"] + ([b"STONE"] if shared else [])
    uv = [(-2.4, -0.0002), (-2.4, -1.002), (3.1, -0.9999), (3.1, -0.0002)]
    if repeat_v:
        uv[1] = (-2.4, -2.002)
    header = struct.pack(
        "<4s12I",
        b"NECS",
        256,
        0,
        0,
        0,
        0,
        4,
        4 * len(surfaces),
        0,
        len(surfaces),
        0,
        0,
        len(surfaces),
    )
    materials = b"".join(bytes(4) + name.ljust(32, b"\0") + bytes(24) for name in surfaces)
    polygons = b"".join(struct.pack("<4H", n * 4, 0, 4, n) for n in range(len(surfaces)))
    offset = len(header + materials + polygons)
    coords = b"".join(struct.pack("<ff", *pair) for pair in uv)
    indices = struct.pack("<" + "H" * (4 * len(surfaces)), *(list(range(4)) * len(surfaces)))
    return header + materials + polygons + coords + indices + b"preserved scene data", offset


def test_inset_removes_vertical_wrap_without_changing_horizontal_repeat_or_geometry() -> None:
    source, offset = _bsp()
    corrected = inset_backdrop_uvs(source, {"FULLTREE01.BMP": 128})
    assert corrected[:offset] == source[:offset]
    assert corrected[offset + 32 :] == source[offset + 32 :]
    for index in range(4):
        u, v = struct.unpack_from("<ff", corrected, offset + index * 8)
        original_u = struct.unpack_from("<f", source, offset + index * 8)[0]
        assert u == original_u
        assert -1 + 0.5 / 128 <= v <= -0.5 / 128
    assert corrected != source
    assert inset_backdrop_uvs(corrected, {"FULLTREE01.BMP": 128}) == corrected


@pytest.mark.parametrize("kwargs", [{"repeat_v": True}, {"shared": True}])
def test_actual_vertical_repeat_and_other_materials_keep_their_coordinates(
    kwargs: dict[str, bool],
) -> None:
    source, _offset = _bsp(**kwargs)
    assert inset_backdrop_uvs(source, {"FULLTREE01.BMP": 128}) == source


def test_scene_overrides_are_derived_from_the_game_and_only_for_installed_textures(
    tmp_path: Path,
) -> None:
    source, _offset = _bsp()
    bitmap = b"61nM" + struct.pack("<HH", 128, 256)
    _write_barn_fixture(
        tmp_path / "Data", core_assets=[("FULLTREE01.BMP", bitmap, 0), ("SCENE.BSP", source, 0)]
    )
    before = (tmp_path / "Data/CORE.BRN").read_bytes()
    assert backdrop_edge_fixes(tmp_path, {"OTHER.BMP"}) == {}
    assert backdrop_edge_fixes(tmp_path, {"FULLTREE01.BMP"}) == {
        "SCENE.BSP": inset_backdrop_uvs(source, {"FULLTREE01.BMP": 128})
    }
    assert (tmp_path / "Data/CORE.BRN").read_bytes() == before
