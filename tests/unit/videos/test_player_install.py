"""Portable AV1 installs own and verify their private codecs, without registration."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from gk3hd.system.files import sha256_file
from gk3hd.videos.install import MovieInstaller
from gk3hd.videos.runtime import PLAYER_DLL, RECIPE, inspect_player, local_player, recipe_digest
from gk3hd.videos.service import upscale_movies
from tests.unit.videos.test_temporal import RecordingBackend

if TYPE_CHECKING:
    from pathlib import Path


def _player(directory: Path) -> Path:
    directory.mkdir(parents=True)
    pin = json.loads((RECIPE / "upstream.json").read_bytes())
    names = (*pin["files"], PLAYER_DLL)
    for name in names:
        (directory / name).write_bytes(b"bounded player test fixture: " + name.encode())
    (directory / "player.json").write_text(
        json.dumps(
            {
                "recipe_sha256": recipe_digest(),
                "files": {name: sha256_file(directory / name) for name in names},
            }
        ),
        encoding="utf-8",
    )
    return directory


def test_av1_lifecycle_preserves_originals_and_owns_every_playback_dependency(game: Path) -> None:
    source = game / "Data/intro.avi"
    original = source.read_bytes()
    output = game / "av1"
    upscale_movies([source], output, RecordingBackend())
    player = _player(game / "player-build")
    installer = MovieInstaller(process_probe=lambda: False)
    report = installer.install(game, output, player=player)
    assert report.videos == 1
    assert (report.directory / "GK3HD-INTRO.AVI").read_bytes() == (
        output / "intro.mkv"
    ).read_bytes()
    for name, digest, _size in inspect_player(player):
        assert sha256_file(report.directory / name) == digest
    assert installer.verify(game).videos == 1
    assert not installer.install(game, output, player=player).changed
    installer.uninstall(game)
    assert not report.directory.exists()
    assert source.read_bytes() == original
    assert (player / PLAYER_DLL).exists()
    assert (output / "intro.mkv").exists()


def test_missing_player_does_not_replace_a_working_install(game: Path) -> None:
    installer = MovieInstaller(process_probe=lambda: False)
    report = installer.install(game)
    previous = (report.directory / "GK3HD-INTRO.AVI").read_bytes()
    output = game / "av1"
    upscale_movies([game / "Data/intro.avi"], output, RecordingBackend())
    (local_player(game) / PLAYER_DLL).unlink()
    with pytest.raises(ValueError, match="videos build"):
        installer.install(game, output)
    assert (report.directory / "GK3HD-INTRO.AVI").read_bytes() == previous


@pytest.mark.parametrize("modified", ["codec", "license", "wrapper"])
def test_changed_player_resources_are_not_silently_removed(game: Path, modified: str) -> None:
    output = game / "av1"
    upscale_movies([game / "Data/intro.avi"], output, RecordingBackend())
    player = _player(game / "player-build")
    installer = MovieInstaller(process_probe=lambda: False)
    report = installer.install(game, output, player=player)
    name = {"codec": "LAVVideo.ax", "license": "COPYING", "wrapper": PLAYER_DLL}[modified]
    path = report.directory / name
    path.write_bytes(b"user replacement")
    with pytest.raises(ValueError, match="changed"):
        installer.uninstall(game)
    assert path.read_bytes() == b"user replacement"
