"""Movie ownership, component independence and interrupted-update behavior."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

import gk3hd.videos.transaction as transactions
from gk3hd.videos.install import MovieInstaller
from gk3hd.videos.manifest import JOURNAL_FILENAME, STATE_FILENAME
from gk3hd.videos.service import upscale_movies
from tests.unit.videos.test_temporal import RecordingBackend
from tests.unit.videos.test_video import _make_movie

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _add_movie(game: Path, name: str) -> None:
    source = game / "Data" / name
    _make_movie(source, audio=True)
    upscale_movies(
        [source],
        game / "gk3hd/videos/upscaled",
        RecordingBackend(),
    )


def _installer() -> MovieInstaller:
    return MovieInstaller(process_probe=lambda: False)


def test_technical_replacement_is_not_installed_over_native_animation(game: Path) -> None:
    installer = _installer()
    installed = installer.install(game)
    previous = (installed.directory / "GK3HD-INTRO.AVI").read_bytes()
    record = game / "gk3hd/videos/upscaled/intro.mkv.json"
    payload = json.loads(record.read_bytes())
    payload["pipeline"] = "nearest"
    record.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="original game files"):
        installer.install(game)
    assert (installed.directory / "GK3HD-INTRO.AVI").read_bytes() == previous


@pytest.mark.parametrize("known", [True, False])
def test_incompatible_or_missing_codec_does_not_replace_an_installed_set(
    game: Path, known: bool
) -> None:
    installer = _installer()
    installed = installer.install(game)
    previous = (installed.directory / "GK3HD-INTRO.AVI").read_bytes()
    record = game / "gk3hd/videos/upscaled/intro.mkv.json"
    payload = json.loads(record.read_bytes())
    if known:
        payload["codec"] = "cinepak"
    else:
        del payload["codec"]
    record.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="regenerate with gk3hd videos upscale"):
        installer.install(game)
    assert (installed.directory / "GK3HD-INTRO.AVI").read_bytes() == previous
    assert installer.verify(game).videos == 1


def test_install_verify_repeat_and_uninstall_preserve_originals_settings_and_outputs(
    game: Path,
) -> None:
    original = (game / "Data/intro.avi").read_bytes()
    ini = (game / "GK3.ini").read_bytes()
    generated = game / "gk3hd/videos/upscaled/intro.mkv"
    installer = _installer()
    report = installer.install(game)
    assert report.videos == 1
    assert report.changed
    assert (report.directory / "GK3HD-INTRO.AVI").read_bytes() == generated.read_bytes()
    assert installer.verify(game).videos == 1
    assert not installer.install(game).changed
    assert installer.uninstall(game).videos == 1
    assert not installer.uninstall(game).changed
    assert (game / "Data/intro.avi").read_bytes() == original
    assert (game / "GK3.ini").read_bytes() == ini
    assert generated.is_file()
    assert not (game / STATE_FILENAME).exists()
    with pytest.raises(ValueError, match="not installed"):
        installer.verify(game)


def test_install_can_update_a_verified_existing_set(game: Path) -> None:
    installer = _installer()
    installer.install(game)
    _add_movie(game, "second.avi")
    report = installer.install(game)
    assert report.changed
    assert report.videos == 2
    assert installer.verify(game).videos == 2
    assert not list(report.directory.parent.glob(".previous-*"))
    assert not list(report.directory.parent.glob(".install-*"))


def test_changed_installed_movies_are_not_removed_or_overwritten(game: Path) -> None:
    installer = _installer()
    report = installer.install(game)
    modified = report.directory / "GK3HD-INTRO.AVI"
    modified.write_bytes(b"user's replacement")
    for action in (installer.install, installer.uninstall, installer.verify):
        with pytest.raises(ValueError, match="changed"):
            action(game)
    assert modified.read_bytes() == b"user's replacement"
    assert (game / STATE_FILENAME).is_file()


def test_foreign_files_block_removal_without_deleting_anything(game: Path) -> None:
    installer = _installer()
    report = installer.install(game)
    foreign = report.directory / "keep-me.txt"
    foreign.write_text("user data", encoding="utf-8")
    with pytest.raises(ValueError, match="unowned"):
        installer.uninstall(game)
    assert foreign.read_text(encoding="utf-8") == "user data"
    assert (report.directory / "GK3HD-INTRO.AVI").is_file()


def test_unowned_install_directory_is_preserved(game: Path) -> None:
    directory = game / "gk3hd/videos/installed"
    directory.mkdir()
    (directory / "keep.avi").write_bytes(b"user movie")
    with pytest.raises(ValueError, match="unowned"):
        _installer().install(game)
    assert (directory / "keep.avi").read_bytes() == b"user movie"


def test_an_unowned_target_appearing_during_copy_is_preserved(game: Path) -> None:
    directory = game / "gk3hd/videos/installed"

    def user_writes(_name: str, done: int, total: int) -> None:
        if done == total:
            directory.mkdir(exist_ok=True)
            (directory / "keep.avi").write_bytes(b"late user movie")

    with pytest.raises(ValueError, match="unowned movie directory appeared"):
        _installer().install(game, progress=user_writes)
    assert (directory / "keep.avi").read_bytes() == b"late user movie"
    assert not (game / STATE_FILENAME).exists()
    assert not (game / JOURNAL_FILENAME).exists()


def test_an_owned_target_modified_during_update_is_preserved(game: Path) -> None:
    installer = _installer()
    report = installer.install(game)
    _add_movie(game, "second.avi")
    modified = report.directory / "GK3HD-INTRO.AVI"

    def user_writes(name: str, done: int, total: int) -> None:
        if name.startswith("Installing") and done == total:
            modified.write_bytes(b"late user edit")

    with pytest.raises(ValueError, match="changed"):
        installer.install(game, progress=user_writes)
    assert modified.read_bytes() == b"late user edit"
    assert not (game / JOURNAL_FILENAME).exists()


@pytest.mark.parametrize("changed", ["generated", "original"])
def test_changed_generation_inputs_are_rejected_before_publication(
    game: Path, changed: str
) -> None:
    path = game / ("Data/intro.avi" if changed == "original" else "gk3hd/videos/upscaled/intro.mkv")
    with path.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match=r"changed|matches"):
        _installer().install(game)
    assert not (game / STATE_FILENAME).exists()
    assert not (game / "gk3hd/videos/installed").exists()
    assert not list((game / "gk3hd/videos").glob(".install-*"))


def test_interruption_during_copy_does_not_publish_partial_movies(game: Path) -> None:
    def cancel(_name: str, _done: int, _total: int) -> None:
        msg = "interrupted"
        raise KeyboardInterrupt(msg)

    with pytest.raises(KeyboardInterrupt, match="interrupted"):
        _installer().install(game, progress=cancel)
    assert not (game / STATE_FILENAME).exists()
    assert not (game / JOURNAL_FILENAME).exists()
    assert not (game / "gk3hd/videos/installed").exists()


def test_failed_update_restores_the_previous_complete_install(
    game: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = _installer()
    installer.install(game)
    previous = (game / STATE_FILENAME).read_bytes()
    _add_movie(game, "second.avi")
    write = transactions.atomic_write
    fail_once = True

    def disk_full(path: Path, data: bytes) -> None:
        nonlocal fail_once
        if fail_once and path.name == STATE_FILENAME:
            fail_once = False
            msg = "simulated state-write failure"
            raise OSError(msg)
        write(path, data)

    monkeypatch.setattr(transactions, "atomic_write", disk_full)
    with pytest.raises(OSError, match="state-write failure"):
        installer.install(game)
    assert (game / STATE_FILENAME).read_bytes() == previous
    assert installer.verify(game).videos == 1
    assert not (game / JOURNAL_FILENAME).exists()
    assert installer.install(game).videos == 2


@pytest.mark.parametrize("action", ["install", "uninstall"])
def test_live_game_prevents_movie_mutations(game: Path, action: str) -> None:
    installer = MovieInstaller(process_probe=lambda: True)
    invoke: Callable[..., object] = getattr(installer, action)
    with pytest.raises(ValueError, match="close GK3"):
        invoke(game)
    assert not (game / STATE_FILENAME).exists()
