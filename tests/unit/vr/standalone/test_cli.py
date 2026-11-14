"""User-facing standalone workflow defaults and diagnostics without a device."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from gk3hd.cli import app
from gk3hd.vr.standalone import cli
from gk3hd.vr.standalone.device import Broker, DeviceProbe
from gk3hd.vr.standalone.install import InstalledPlayer
from gk3hd.vr.standalone.paths import BUILD_RECORD, record_build

if TYPE_CHECKING:
    from pathlib import Path

RUNNER = CliRunner()


@pytest.mark.parametrize("release", [False, True])
def test_build_discovers_toolchain_instead_of_requiring_sdk_argument(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, release: bool
) -> None:
    build = Mock(return_value=tmp_path / "build")
    monkeypatch.setattr(cli.builder, "build", build)
    args = ["vr", "standalone", "build", "--game-dir", str(tmp_path)]
    result = RUNNER.invoke(app, [*args, "--release"] if release else args)
    assert result.exit_code == 0, result.output
    toolchain = build.call_args.kwargs["toolchain"]
    assert toolchain.android_sdk is None
    assert toolchain.release is release
    assert build.call_args.kwargs["game_dir"] == tmp_path
    assert ("package draft --vr" if release else "standalone install --local") in result.output


def test_pack_defaults_to_gameplay_with_textures_without_installing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack = Mock(return_value=Mock(path=tmp_path / "private.zip"))
    install = Mock()
    monkeypatch.setattr(cli.packer, "pack", pack)
    monkeypatch.setattr(cli.installer, "install", install)
    result = RUNNER.invoke(app, ["vr", "standalone", "pack"])
    assert result.exit_code == 0, result.output
    options = pack.call_args.kwargs["options"]
    assert options.profile == "recommended"
    assert options.textures is True
    assert options.backend == "turnip"
    assert "Keep this bundle private" in result.output
    install.assert_not_called()


def test_pack_accepts_explicit_baseline_and_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack = Mock(return_value=Mock(path=tmp_path / "private.zip"))
    monkeypatch.setattr(cli.packer, "pack", pack)
    result = RUNNER.invoke(
        app,
        ["vr", "standalone", "pack", "--no-textures", "--backend", "native-vulkan", "--testing"],
    )
    assert result.exit_code == 0, result.output
    options = pack.call_args.kwargs["options"]
    assert options.textures is False
    assert options.profile == "testing"
    assert options.backend == "native-vulkan"


def test_install_local_prepares_a_bundle_for_the_recorded_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = InstalledPlayer("quest", "a" * 64, 5, "Private player installed")
    install = Mock(return_value=installed)
    root = tmp_path / "gk3hd/vr/standalone"
    candidate = root / "build" / ("a" * 32)
    candidate.mkdir(parents=True)
    record = candidate / BUILD_RECORD
    record.write_text("{}")
    record_build(root, record, release=False)
    apk, bundle = candidate / "gk3hd-standalone.apk", root / "ready/private.zip"
    prepare = Mock(return_value=(apk, bundle, "quest"))
    monkeypatch.setattr(cli.installer, "install", install)
    monkeypatch.setattr(cli.preparation, "prepare", prepare)
    result = RUNNER.invoke(
        app,
        [
            "vr",
            "standalone",
            "install",
            "--local",
            "--game-dir",
            str(tmp_path),
            "--device",
            "quest",
        ],
    )
    assert result.exit_code == 0, result.output
    arguments = install.call_args.kwargs
    assert arguments["apk"] == apk
    assert arguments["bundle"] == bundle
    assert arguments["device"] == "quest"
    assert prepare.call_args.kwargs["build_dir"] == candidate


def test_default_install_prepares_release_components_and_uses_the_selected_headset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare = Mock(return_value=(tmp_path / "player.apk", tmp_path / "private.zip", "quest"))
    install = Mock(return_value=InstalledPlayer("quest", "a" * 64, 5, "Private player updated"))
    monkeypatch.setattr(cli.preparation, "prepare", prepare)
    monkeypatch.setattr(cli.installer, "install", install)
    result = RUNNER.invoke(app, ["vr", "standalone", "install"])
    assert result.exit_code == 0, result.output
    assert install.call_args.kwargs["device"] == "quest"
    assert install.call_args.kwargs["apk"] == tmp_path / "player.apk"
    assert install.call_args.kwargs["bundle"] == tmp_path / "private.zip"
    assert prepare.call_args.kwargs["device"] is None


@pytest.mark.parametrize("machine_readable", [False, True])
def test_doctor_is_vendor_neutral_and_json_is_parseable(
    monkeypatch: pytest.MonkeyPatch, *, machine_readable: bool
) -> None:
    report = DeviceProbe(
        "quest",
        {"manufacturer": "Meta", "model": "Quest 3", "api": "32", "abis": "arm64-v8a"},
        8000,
        (Broker("runtime", "runtime advertised; session not tested", "package_name=runtime"),),
        (),
    )
    probe = Mock(return_value=report)
    install = Mock()
    monkeypatch.setattr(cli.devices, "probe", probe)
    monkeypatch.setattr(cli.installer, "install", install)
    result = RUNNER.invoke(
        app,
        [
            "vr",
            "standalone",
            "doctor",
            "--device",
            "quest",
            *(["--json"] if machine_readable else []),
        ],
    )
    assert result.exit_code == 0, result.output
    if machine_readable:
        assert json.loads(result.output)["properties"]["model"] == "Quest 3"
    else:
        assert "Quest 3" in result.output
        assert "session not tested" in result.output
    probe.assert_called_once_with(adb=None, device="quest")
    install.assert_not_called()
