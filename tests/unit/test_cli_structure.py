"""All operations have a single public CLI; pytest owns visual automation."""

import tomllib
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from gk3hd.cli import app
from gk3hd.renderer import build, cli


@pytest.mark.parametrize("command", ["renderer", "package", "patch", "textures"])
def test_component_help_is_portable(command: str) -> None:
    result = CliRunner().invoke(app, [command, "--help"])
    assert result.exit_code == 0, result.output


def test_visual_task_is_only_a_pytest_shortcut() -> None:
    root = Path(__file__).resolve().parents[2]
    tasks = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["poe"]["tasks"]
    assert "tools" not in tasks
    assert tasks["visual"]["cmd"] == "pytest tests/visual --visual"


def test_build_reports_the_successful_artifact_without_installing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset = Mock(path=Path("verified.dll"))
    builder = Mock(return_value=asset)
    installer = Mock()
    monkeypatch.setattr(build, "build", builder)
    monkeypatch.setattr(cli, "RendererService", lambda: installer)
    result = CliRunner().invoke(app, ["renderer", "build"])
    assert result.exit_code == 0, result.output
    builder.assert_called_once_with(game_dir=None, output=None, jobs=12)
    assert str(asset.path) in result.output
    installer.install.assert_not_called()


def test_build_rejects_installation_option(monkeypatch: pytest.MonkeyPatch) -> None:
    builder = Mock()
    monkeypatch.setattr(build, "build", builder)
    result = CliRunner().invoke(app, ["renderer", "build", "--install"])
    assert result.exit_code == 2
    builder.assert_not_called()


def test_build_forwards_game_selection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    builder = Mock(return_value=Mock(path=tmp_path / "renderer.dll"))
    monkeypatch.setattr(build, "build", builder)
    result = CliRunner().invoke(app, ["renderer", "build", "--game-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    builder.assert_called_once_with(game_dir=tmp_path, output=None, jobs=12)


def test_build_rejects_unsupported_platform_without_running_compiler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build, "sys", Mock(platform="linux"))
    run = Mock()
    monkeypatch.setattr(build.subprocess, "run", run)
    result = CliRunner().invoke(app, ["renderer", "build"])
    assert result.exit_code == 1
    assert "require Windows" in result.output
    run.assert_not_called()
