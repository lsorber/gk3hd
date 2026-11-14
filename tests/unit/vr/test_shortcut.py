"""Start menu ownership stays separate from the installed game."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from gk3hd.vr import shortcut

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    game = tmp_path / "Game library"
    game.mkdir()
    (game / "GK3.exe").touch()
    programs = tmp_path / "Redirected Programs"
    programs.mkdir()
    monkeypatch.setattr(shortcut, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(shortcut, "cache_directory", lambda: tmp_path / "cache")
    monkeypatch.setattr(shortcut, "_programs", lambda: programs)
    monkeypatch.setattr(shortcut, "_persistent_launcher", lambda: tmp_path / "gk3hd.exe")

    def create(path: Path, launcher: Path, target: Path) -> None:
        path.write_text(f"{launcher} launches VR in {target}")

    monkeypatch.setattr(shortcut, "_create", create)
    return game, programs / "GK3HD VR.lnk"


def test_install_can_repair_and_remove_its_shortcut(workspace: tuple[Path, Path]) -> None:
    game, link = workspace
    assert shortcut.install(game)
    expected = link.read_bytes()
    link.unlink()
    assert shortcut.install(game)
    assert link.read_bytes() == expected
    shortcut.uninstall(game)
    assert not link.exists()
    assert (game / "GK3.exe").is_file()


def test_edited_shortcut_is_preserved_on_reinstall_and_uninstall(
    workspace: tuple[Path, Path],
) -> None:
    game, link = workspace
    assert shortcut.install(game)
    link.write_bytes(b"user-edited shortcut")

    with pytest.raises(ValueError, match="user-edited"):
        shortcut.install(game)
    with pytest.raises(ValueError, match="user-edited"):
        shortcut.uninstall(game)
    assert link.read_bytes() == b"user-edited shortcut"


def test_temporary_tool_install_creates_no_shortcut(monkeypatch: pytest.MonkeyPatch) -> None:
    discover = Mock()
    monkeypatch.setattr(shortcut, "discover_game", discover)
    monkeypatch.setattr(shortcut, "_persistent_launcher", lambda: None)

    assert shortcut.install(None) is False
    discover.assert_not_called()
