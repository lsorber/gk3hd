"""Private preparation compiles real hooks but never executes synthetic binaries."""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

import gk3hd
from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.model import ProfileId
from gk3hd.system.discovery import GameTarget
from gk3hd.vr import artifact, items
from gk3hd.vr.standalone import build as builder
from gk3hd.vr.standalone import pack as packer
from gk3hd.vr.standalone import prepare as preparation
from gk3hd.vr.standalone.apk import COMPONENT_ASSET
from tests.unit.renderer.test_artifact import renderer_dll, vr_dll
from tests.unit.vr.standalone.test_apk import binary_manifest
from tests.unit.vr.standalone.test_assets import installed_pack_fixture, installed_video_fixture
from tests.unit.vr.test_compiler import flat_bytes

if TYPE_CHECKING:
    from pathlib import Path

    from gk3hd.patch.builds import BuildProfile

__all__ = ["flat_bytes", "renderer_dll", "vr_dll"]


def _pe(*, dll: bool, runtime: bool = False) -> bytes:
    """Small PE headers/export data, deliberately no executable code."""
    data = bytearray(1536)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 0x84, 0x14C, 1, 0, 0, 0, 0xE0, 0x2002 if dll else 2)
    struct.pack_into("<H", data, 0x98, 0x10B)
    for offset, value in [
        (28, 0x400000),
        (32, 0x1000),
        (36, 0x200),
        (56, 0x2000),
        (60, 0x200),
        (92, 16),
    ]:
        struct.pack_into("<I", data, 0x98 + offset, value)
    struct.pack_into(
        "<8sIIIIIIHHI", data, 0x178, b".data", 1024, 0x1000, 1024, 0x200, 0, 0, 0, 0, 0x40000040
    )
    if runtime:
        struct.pack_into("<II", data, 0x98 + 96, 0x1000, 128)
        struct.pack_into("<I", data, 0x200 + 24, 1)
        struct.pack_into("<I", data, 0x200 + 32, 0x1040)
        struct.pack_into("<I", data, 0x240, 0x1060)
        name = b"xrNegotiateLoaderRuntimeInterface\0"
        data[0x260 : 0x260 + len(name)] = name
    return bytes(data)


@dataclass
class Environment:
    game: Path
    components: Path
    output: Path
    profile: BuildProfile
    baseline: dict[str, bytes]


@pytest.fixture
def environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    vr_dll: Path,
    flat_bytes: tuple[bytes, BuildProfile],
) -> Environment:
    flat, profile = flat_bytes
    game = tmp_path / "game"
    (game / "Data").mkdir(parents=True)
    for name, value in {
        "GK3.exe": b"original",
        "binkw32.dll": _pe(dll=True),
        "GK3.ini": b"user preferences",
        "save0001.gk3": b"user save",
    }.items():
        (game / name).write_bytes(value)
    (game / "Data/core.brn").write_bytes(b"private game data")
    monkeypatch.setattr(items, "load_catalog", lambda _data: items.encode_catalog(()))
    (game / "Data/intro.bik").write_bytes(b"movie data")
    (game / "Data/SiErRa.AvI").write_bytes(b"publisher logo")
    (game / "Data/story.avi").write_bytes(b"story movie")
    installed_pack_fixture(game)
    installed_video_fixture(game)
    (tmp_path / "openxr_wxr32.dll").write_bytes(_pe(dll=True, runtime=True))
    (tmp_path / "gk3hd-wine-launcher.exe").write_bytes(_pe(dll=False))
    monkeypatch.setattr(packer, "RECIPE", artifact.RECIPE)
    monkeypatch.setattr(
        packer,
        "discover_game",
        Mock(return_value=GameTarget(game, game / "GK3.exe", game / "Data", game / "GK3.ini")),
    )
    monkeypatch.setattr(packer, "original_source", lambda exe: exe)
    monkeypatch.setattr(
        packer,
        "prepare_base_game",
        Mock(side_effect=lambda _raw, **_kwargs: (PEFile(flat), profile)),
    )
    baseline = {path.name: path.read_bytes() for path in game.iterdir() if path.is_file()}
    assert vr_dll.parent == tmp_path
    return Environment(game, tmp_path, tmp_path / "private.zip", profile, baseline)


def test_preparation_is_private_dormant_and_self_describing(environment: Environment) -> None:
    env = environment
    receipt = packer.pack(game_dir=env.game, build_dir=env.components, output=env.output)
    with ZipFile(receipt.path) as archive:
        metadata = json.loads(archive.read("game/gk3hd-player.json"))
        assert metadata["graphics_backend"] in {"native-vulkan", "turnip"}
        assert metadata["profile"] == "recommended"
        image = PEFile(archive.read("game/GK3-VR.exe"))
        switches = metadata["launch_switches"]
        assert metadata["output_contract"] == "stereo-only"
        assert switches
        assert len(switches) == len(set(switches))
        activation = archive.read("game/launch-switches.txt").decode().split()
        assert int(activation[0]) == len(switches)
        assert [int(address, 16) for address in activation[1:]] == switches
        assert all(image.read_u32_va(address) == 0 for address in switches)
        desktop = int(archive.read("game/desktop-input-switch.txt"), 16)
        assert desktop in switches
        assert b"CUSTOM PATHS" in archive.read("game/GK3.ini")
        assert b"do-not-copy" not in archive.read("game/GK3.ini")
        assert archive.read("game/conf.txt") == b"controller_profile=/oculus/touch_controller\n"
        assert json.loads(archive.read("game/gk3hd-textures.json"))["mode"] == "installed-hd"
        assert json.loads(archive.read("game/gk3hd-videos.json"))["video_count"] == 1
        assert metadata["quality"] == "recommended"
        assert metadata["features"] == {"hd_textures": True, "hd_videos": True}
        assert (
            archive.read("game/gk3hd/videos/installed/GK3HD-INTRO.AVI")
            == b"synthetic encoded movie"
        )
        assert "game/gk3hd/videos/installed/gk3hd-videos.dll" in archive.namelist()
        assert "game/gk3hd/videos/installed/LAVVideo.ax" in archive.namelist()
        assert archive.read("game/Data/intro.bik") == b"movie data"
        assert archive.read("game/Data/story.avi") == b"story movie"
        assert archive.read("game/Data/SiErRa.AvI") == b"publisher logo"
        assert "game/save0001.gk3" not in archive.namelist()
        assert b"OpenXR.txt" in archive.read("game/renderer-notices.txt")
        assert b"game_dir" not in archive.read("game/gk3hd-player.json")
    assert {name: (env.game / name).read_bytes() for name in env.baseline} == env.baseline
    assert (env.game / "Data/SiErRa.AvI").read_bytes() == b"publisher logo"


def test_testing_movies_are_explicit(environment: Environment) -> None:
    env = environment
    packer.pack(
        game_dir=env.game,
        build_dir=env.components,
        output=env.output,
        options=packer.PreparationOptions(profile=ProfileId("testing")),
    )
    with ZipFile(env.output) as archive:
        assert json.loads(archive.read("game/gk3hd-player.json"))["profile"] == "testing"


def test_preparation_reuses_bundle_across_cli_releases_and_rebuilds_on_payload_changes(
    environment: Environment, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = environment
    game = GameTarget(env.game, env.game / "GK3.exe", env.game / "Data", env.game / "GK3.ini")
    events = []
    bundle = preparation._prepare_bundle(game, env.components, events.append)
    original = bundle.read_bytes()

    events.clear()
    monkeypatch.setattr(gk3hd, "__version__", "99.0.0")
    assert preparation._prepare_bundle(game, env.components, events.append) == bundle
    assert bundle.read_bytes() == original
    assert any("Reusing" in event.message for event in events)

    monkeypatch.setattr(packer, "config_bytes", lambda **_: b"new packaged renderer configuration")
    assert preparation._prepare_bundle(game, env.components, events.append) == bundle
    assert bundle.read_bytes() != original
    with ZipFile(bundle) as archive:
        assert archive.read("game/dxvk.conf") == b"new packaged renderer configuration"


@pytest.mark.parametrize("backend", list(packer.GraphicsBackend))
def test_selected_graphics_backend_is_carried_to_the_private_player(
    environment: Environment, backend: packer.GraphicsBackend
) -> None:
    env = environment
    packer.pack(
        game_dir=env.game,
        build_dir=env.components,
        output=env.output,
        options=packer.PreparationOptions(backend=backend),
    )
    with ZipFile(env.output) as archive:
        metadata = json.loads(archive.read("game/gk3hd-player.json"))
        assert metadata["graphics_backend"] == backend.value
        assert metadata["output_contract"] == "stereo-only"
    assert {name: (env.game / name).read_bytes() for name in env.baseline} == env.baseline


def test_wrong_runtime_is_rejected_before_publication(environment: Environment) -> None:
    env = environment
    (env.components / "openxr_wxr32.dll").write_bytes(_pe(dll=True))
    with pytest.raises(ValueError, match="not an OpenXR runtime"):
        packer.pack(game_dir=env.game, build_dir=env.components, output=env.output)
    assert not env.output.exists()


def test_source_change_prevents_bundle_publication(environment: Environment) -> None:
    env = environment

    def change_source(_done: int, _total: int) -> None:
        (env.game / "GK3.exe").write_bytes(b"changed externally")

    with pytest.raises(ValueError, match="changed during preparation"):
        packer.pack(
            game_dir=env.game,
            build_dir=env.components,
            output=env.output,
            on_progress=change_source,
        )
    assert not env.output.exists()
    assert not list(env.output.parent.glob(".gk3hd-player-*"))


def test_existing_output_is_preserved(environment: Environment) -> None:
    env = environment
    env.output.write_bytes(b"keep this archive")
    with pytest.raises(FileExistsError):
        packer.pack(game_dir=env.game, build_dir=env.components, output=env.output)
    assert env.output.read_bytes() == b"keep this archive"


def _support_record(env: Environment) -> Path:
    apk = env.components / "gk3hd-standalone.apk"
    with ZipFile(apk, "w") as archive:
        archive.writestr("AndroidManifest.xml", binary_manifest())
        archive.writestr(
            COMPONENT_ASSET,
            "".join(
                f"{hashlib.sha256((env.components / name).read_bytes()).hexdigest()}  {name}\n"
                for name in ("openxr_wxr32.dll", "gk3hd-wine-launcher.exe")
            ),
        )
    for name in ("OpenXR-WXR-LICENSE.txt", "Winlator-LICENSE.txt", "Vortek-LICENSE.txt"):
        (env.components / name).write_bytes(b"fixture notice")
    record = env.components / "standalone-components.json"
    record.write_text(
        json.dumps(
            {
                "schema": 1,
                "kind": "standalone-development-components",
                "upstream": json.loads(
                    (builder.RECIPE / "upstream.json").read_text(encoding="utf-8")
                ),
                "inputs": builder.source_hashes(),
                "checks": sorted(builder._CHECKS),
                "outputs": {
                    name: hashlib.sha256((env.components / name).read_bytes()).hexdigest()
                    for name in ("openxr_wxr32.dll", "gk3hd-wine-launcher.exe", apk.name)
                },
            }
        ),
        encoding="utf-8",
    )
    return record


def test_built_support_provenance_and_notices_follow_private_player(
    environment: Environment,
) -> None:
    env = environment
    record = _support_record(env)
    packer.pack(game_dir=env.game, build_dir=env.components, output=env.output)
    with ZipFile(env.output) as archive:
        assert archive.read("game/support-provenance.json") == record.read_bytes()
        assert archive.read("game/Winlator-LICENSE.txt") == b"fixture notice"
        assert archive.read("game/Vortek-LICENSE.txt") == b"fixture notice"
        metadata = json.loads(archive.read("game/gk3hd-player.json"))
        assert metadata["support_validation"].endswith("not release qualification")
        assert "game/gk3hd-standalone.apk" not in archive.namelist()


def test_stale_build_record_is_not_downgraded_to_unverified_components(
    environment: Environment,
) -> None:
    env = environment
    _support_record(env)
    (env.components / "gk3hd-wine-launcher.exe").write_bytes(_pe(dll=False) + b"changed")
    with pytest.raises(ValueError, match="component changed"):
        packer.pack(game_dir=env.game, build_dir=env.components, output=env.output)
    assert not env.output.exists()


def test_changed_support_during_packing_prevents_publication(environment: Environment) -> None:
    env = environment
    _support_record(env)

    def change_support(_done: int, _total: int) -> None:
        (env.components / "gk3hd-wine-launcher.exe").write_bytes(b"externally replaced")

    with pytest.raises(ValueError, match="component changed"):
        packer.pack(
            game_dir=env.game,
            build_dir=env.components,
            output=env.output,
            on_progress=change_support,
        )
    assert not env.output.exists()


def test_prepared_hd_resources_and_custom_path_leave_flat_installation_unchanged(
    environment: Environment,
) -> None:
    env = environment
    directory = installed_pack_fixture(env.game)
    desktop_ini = (env.game / "GK3.ini").read_bytes()
    packer.pack(game_dir=env.game, build_dir=env.components, output=env.output)
    with ZipFile(env.output) as archive:
        for path in directory.iterdir():
            name = f"game/gk3hd/textures/installed/{path.name}"
            assert archive.read(name) == path.read_bytes()
        assert b"CUSTOM PATHS = gk3hd/textures/installed" in archive.read("game/GK3.ini")
        assert b"do-not-copy" not in archive.read("game/GK3.ini")
        assert json.loads(archive.read("game/gk3hd-textures.json"))["mode"] == "installed-hd"
    assert (env.game / "GK3.ini").read_bytes() == desktop_ini


def test_original_baseline_can_explicitly_exclude_an_installed_pack(
    environment: Environment,
) -> None:
    env = environment
    directory = installed_pack_fixture(env.game)
    (directory / "SKIN.BMP").write_bytes(b"irrelevant modified desktop texture")
    packer.pack(
        game_dir=env.game,
        build_dir=env.components,
        output=env.output,
        options=packer.PreparationOptions(textures=False),
    )
    with ZipFile(env.output) as archive:
        assert not any("/textures/installed/" in name for name in archive.namelist())
        assert json.loads(archive.read("game/gk3hd-textures.json"))["mode"] == "original"
        assert not archive.read("game/GK3.ini")


def test_original_video_control_preserves_movies_and_is_not_recommended(
    environment: Environment,
) -> None:
    env = environment
    directory = installed_video_fixture(env.game)
    movie = directory / "GK3HD-INTRO.AVI"
    movie.write_bytes(b"irrelevant changed video")
    receipt = packer.pack(
        game_dir=env.game,
        build_dir=env.components,
        output=env.output,
        options=packer.PreparationOptions(videos=False),
    )
    with ZipFile(receipt.path) as archive:
        assert not any("/videos/installed/" in name for name in archive.namelist())
        assert archive.read("game/Data/intro.bik") == b"movie data"
        metadata = json.loads(archive.read("game/gk3hd-player.json"))
        assert metadata["quality"] == "diagnostic"
        assert metadata["features"] == {"hd_textures": True, "hd_videos": False}
    assert movie.read_bytes() == b"irrelevant changed video"
