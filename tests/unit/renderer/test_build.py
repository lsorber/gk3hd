"""Renderer build locations are game-relative, never tied to the invoking shell."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from gk3hd.renderer import build


def test_workspace_uses_discovered_game(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    discovery = Mock(return_value=Mock(game_dir=tmp_path / "game"))
    monkeypatch.setattr(build, "discover_game", discovery)
    assert build.workspace() == tmp_path / "game" / "gk3hd" / "renderer"
    discovery.assert_called_once_with(game_dir=None)


def test_license_changes_invalidate_build_reuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    license_file = tmp_path / "LICENSE"
    license_file.write_text("Original attribution\n")
    monkeypatch.setattr(build, "RECIPE", tmp_path)
    previous = build.recipe_digest()
    license_file.write_text("Updated attribution\n")
    assert build.recipe_digest() != previous


@pytest.mark.parametrize("name", ["renderer.patch", "build.ps1", "upstream.json", "LICENSE"])
def test_line_endings_do_not_invalidate_build_reuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    recipe = tmp_path / name
    recipe.write_bytes(b"first line\nsecond line\n")
    monkeypatch.setattr(build, "RECIPE", tmp_path)
    previous = build.recipe_digest()
    recipe.write_bytes(b"first line\r\nsecond line\r\n")
    assert build.recipe_digest() == previous
    recipe.write_bytes(b"changed line\nsecond line\n")
    assert build.recipe_digest() != previous


@pytest.mark.parametrize("custom_output", [False, True])
def test_build_records_output_for_the_game_and_local_lookup_ignores_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, custom_output: bool
) -> None:
    game = tmp_path / "game"
    game.mkdir()
    (game / "GK3.exe").write_bytes(b"fixture")
    root = game / "gk3hd" / "renderer"
    output = tmp_path / "custom-build" if custom_output else None
    digest = "a" * 64
    target = output or root / digest[:16]
    pin = json.loads((build.RECIPE / "upstream.json").read_text(encoding="utf-8"))
    asset = Mock(path=target / f"dxvk-sarek-{pin['version']}.dll", dll_sha256="b" * 64)
    inspect = Mock(return_value=asset)
    compiler = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(build, "sys", Mock(platform="win32"))
    monkeypatch.setattr(build.shutil, "which", Mock(return_value="pwsh"))
    monkeypatch.setattr(build.subprocess, "run", compiler)
    monkeypatch.setattr(build, "recipe_digest", lambda: digest)
    monkeypatch.setattr(build, "inspect_dll", inspect)

    assert build.build(game_dir=game, output=output) is asset
    inspect.assert_called_once_with(asset.path)
    compiler.assert_called_once()
    arguments = compiler.call_args.args[0]
    assert arguments[arguments.index("-OutputRoot") + 1] == str(target.resolve())
    record = json.loads((root / "latest.json").read_text())
    assert record["dll"] == str(asset.path.resolve())

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert build.local_build(game_dir=game) is asset
    assert not (elsewhere / "build").exists()
