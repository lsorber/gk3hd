"""Opt-in VR commands delegate safely and never masquerade as released VR."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING
from unittest.mock import ANY, Mock

import pytest
from rich.console import Console
from typer.testing import CliRunner

from gk3hd.cli import app
from gk3hd.vr import cli
from gk3hd.vr.runtime import RuntimeUnavailableError
from gk3hd.vr.status import TrackingStatus

if TYPE_CHECKING:
    from pathlib import Path

RUNNER = CliRunner()


def test_vr_help_exposes_prototype_without_running_it(monkeypatch: pytest.MonkeyPatch) -> None:
    service = Mock()
    monkeypatch.setattr(cli, "VRService", service)
    result = RUNNER.invoke(app, ["vr", "--help"])
    assert result.exit_code == 0
    assert "Not yet qualified for headset play" in result.output
    for name in ("build", "install", "verify", "launch", "uninstall"):
        assert name in result.output
    service.assert_not_called()


def test_install_defaults_to_verified_local_prototype(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = Mock()
    monkeypatch.setattr(cli, "VRService", lambda: service)
    result = RUNNER.invoke(app, ["vr", "install", "--game-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Not ready for headset play" in result.output
    service.install.assert_called_once_with(
        game_dir=tmp_path, dll=None, units_per_meter=pytest.approx(1 / 0.0254)
    )


def test_install_accepts_explicit_asset_and_calibration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = Mock()
    monkeypatch.setattr(cli, "VRService", lambda: service)
    asset = tmp_path / "prototype.dll"
    result = RUNNER.invoke(
        app,
        ["vr", "install", "--dll", str(asset), "--units-per-meter", "80"],
    )
    assert result.exit_code == 0, result.output
    service.install.assert_called_once_with(game_dir=None, dll=asset, units_per_meter=80)


@pytest.mark.parametrize("fails", [False, True])
def test_install_progress_works_with_redirected_windows_encoding(
    monkeypatch: pytest.MonkeyPatch, *, fails: bool
) -> None:
    """Progress cannot turn success into failure or mask the real failure."""
    service = Mock()
    if fails:
        service.install.side_effect = ValueError("VR compilation rejected")
    monkeypatch.setattr(cli, "VRService", lambda: service)
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="cp1252")
    monkeypatch.setattr(
        cli,
        "console",
        Console(file=stream, legacy_windows=True, force_terminal=False, color_system=None),
    )
    result = RUNNER.invoke(app, ["vr", "install"])
    stream.flush()
    assert result.exit_code == int(fails), result.output
    output = buffer.getvalue().decode("cp1252")
    assert "Compiling and verifying isolated VR player" in output
    assert ("VR prototype installed and verified" in output) is not fails
    if fails:
        assert "VR compilation rejected" in result.output
    service.install.assert_called_once()


@pytest.mark.parametrize("command", ["verify", "uninstall"])
def test_file_operations_do_not_launch_or_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    service = Mock()
    launcher = Mock()
    builder = Mock()
    monkeypatch.setattr(cli, "VRService", lambda: service)
    monkeypatch.setattr(cli.launcher, "launch", launcher)
    monkeypatch.setattr(cli.builder, "build", builder)
    result = RUNNER.invoke(app, ["vr", command, "--game-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    getattr(service, command).assert_called_once_with(game_dir=tmp_path)
    launcher.assert_not_called()
    builder.assert_not_called()


def test_launch_reports_runtime_failure_without_flat_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = Mock(side_effect=RuntimeUnavailableError("connect the headset"))
    monkeypatch.setattr(cli.launcher, "launch", launcher)
    runtime = tmp_path / "runtime.json"
    result = RUNNER.invoke(app, ["vr", "launch", "--runtime", str(runtime)])
    assert result.exit_code == 1
    assert "connect the headset" in result.output
    assert "Traceback" not in result.output
    launcher.assert_called_once_with(
        game_dir=None,
        runtime_manifest=runtime,
        pointing_hand=cli.PointingHand.RIGHT,
        on_tracking=ANY,
    )


def test_launch_accepts_left_handed_pointing(monkeypatch: pytest.MonkeyPatch) -> None:
    launcher = Mock(return_value=0)
    monkeypatch.setattr(cli.launcher, "launch", launcher)
    result = RUNNER.invoke(app, ["vr", "launch", "--hand", "left"])
    assert result.exit_code == 0, result.output
    launcher.assert_called_once_with(
        game_dir=None,
        runtime_manifest=None,
        pointing_hand=cli.PointingHand.LEFT,
        on_tracking=ANY,
    )


def test_invalid_pointing_preference_does_not_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    launcher = Mock()
    monkeypatch.setattr(cli.launcher, "launch", launcher)
    result = RUNNER.invoke(app, ["vr", "launch", "--hand", "unknown"])
    assert result.exit_code == 2
    launcher.assert_not_called()


def test_launch_owns_readable_tracking_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    def launched(**options: object) -> int:
        notify = options["on_tracking"]
        assert callable(notify)
        notify(TrackingStatus.UNAVAILABLE)
        notify(TrackingStatus.AVAILABLE)
        return 0

    monkeypatch.setattr(cli.launcher, "launch", launched)
    result = RUNNER.invoke(app, ["vr", "launch"])
    assert result.exit_code == 0, result.output
    assert "Headset tracking unavailable" in result.output
    assert "VR controller input is paused" in result.output
    assert "Headset tracking available" in result.output
    assert "Release held controls" in result.output


def test_build_never_installs_or_launches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    builder = Mock(return_value=Mock(path=tmp_path / "prototype.dll"))
    service = Mock()
    launcher = Mock()
    monkeypatch.setattr(cli.builder, "build", builder)
    monkeypatch.setattr(cli, "VRService", service)
    monkeypatch.setattr(cli.launcher, "launch", launcher)
    result = RUNNER.invoke(app, ["vr", "build", "--game-dir", str(tmp_path), "--jobs", "4"])
    assert result.exit_code == 0, result.output
    builder.assert_called_once_with(game_dir=tmp_path, output=None, jobs=4)
    service.assert_not_called()
    launcher.assert_not_called()


def test_build_rejects_invalid_parallelism_before_building(monkeypatch: pytest.MonkeyPatch) -> None:
    builder = Mock()
    monkeypatch.setattr(cli.builder, "build", builder)
    result = RUNNER.invoke(app, ["vr", "build", "--jobs", "0"])
    assert result.exit_code == 2
    builder.assert_not_called()
