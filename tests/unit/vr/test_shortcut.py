"""Windows shortcuts support both launch locations and preserve edits."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from gk3hd import __version__
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
    monkeypatch.setattr(
        shortcut, "shutil", SimpleNamespace(which=lambda name: str(tmp_path / name))
    )

    def create(path: Path, launcher: Path, target: Path, *, prefix: tuple[str, ...]) -> None:
        path.write_text(f"{launcher.name} {' '.join(prefix)} launches VR in {target}")

    monkeypatch.setattr(shortcut, "_create", create)
    return game, programs / "GK3HD VR.lnk"


def test_install_can_repair_and_remove_its_shortcut(workspace: tuple[Path, Path]) -> None:
    game, link = workspace
    game_link = game / link.name
    assert shortcut.install(game, published=True)
    expected = link.read_bytes()
    assert expected.startswith(f"uvx.exe gk3hd@{__version__} ".encode())
    assert game_link.read_bytes() == expected
    link.unlink()
    assert shortcut.install(game, published=True)
    assert link.read_bytes() == expected
    game_link.unlink()
    assert shortcut.install(game, published=True)
    assert game_link.read_bytes() == expected
    shortcut.uninstall(game)
    assert not link.exists()
    assert not game_link.exists()
    assert (game / "GK3.exe").is_file()


@pytest.mark.parametrize("edit_game_folder", [False, True])
def test_edited_shortcut_is_preserved_on_reinstall_and_uninstall(
    workspace: tuple[Path, Path], *, edit_game_folder: bool
) -> None:
    game, link = workspace
    edited = game / link.name if edit_game_folder else link
    assert shortcut.install(game, published=True)
    edited.write_bytes(b"user-edited shortcut")

    with pytest.raises(ValueError, match="user-edited"):
        shortcut.install(game, published=True)
    with pytest.raises(ValueError, match="user-edited"):
        shortcut.uninstall(game)
    assert edited.read_bytes() == b"user-edited shortcut"


def test_missing_uvx_leaves_the_terminal_launch_available(monkeypatch: pytest.MonkeyPatch) -> None:
    discover = Mock()
    monkeypatch.setattr(shortcut, "discover_game", discover)
    monkeypatch.setattr(shortcut, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(shortcut, "shutil", SimpleNamespace(which=lambda _: None))

    assert shortcut.install(None, published=True) is False
    discover.assert_not_called()
