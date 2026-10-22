"""Recover observable on-disk crash states without deleting unrelated data."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from gk3hd.system.files import sha256_file
from gk3hd.videos.install import MovieInstaller
from gk3hd.videos.manifest import JOURNAL_FILENAME, STATE_FILENAME, MovieFile, MovieState
from gk3hd.videos.transaction import MovieJournal, recover, state_at
from tests.unit.videos.test_install import _add_movie, _installer

if TYPE_CHECKING:
    from pathlib import Path


def _pending(game: Path) -> MovieJournal:
    """Stage one genuinely generated replacement, just as a killed process would."""
    generated = game / "gk3hd/videos/upscaled/intro.mkv"
    original = game / "Data/intro.avi"
    state = MovieState(
        (
            MovieFile(
                "GK3HD-INTRO.AVI",
                original.name,
                sha256_file(original),
                sha256_file(generated),
                generated.stat().st_size,
            ),
        )
    )
    staging = game / "gk3hd/videos" / f".install-{uuid4().hex}"
    staging.mkdir()
    (staging / "GK3HD-INTRO.AVI").write_bytes(generated.read_bytes())
    journal = MovieJournal(game, staging.name, f".previous-{uuid4().hex}", None, state)
    journal.write()
    return journal


def test_killed_initial_install_rolls_back_on_the_next_uninstall(game: Path) -> None:
    journal = _pending(game)
    assert journal.staging is not None
    (journal.parent / journal.staging).replace(journal.parent / "installed")
    assert not _installer().uninstall(game).changed
    assert not (game / STATE_FILENAME).exists()
    assert not journal.path.exists()
    assert not (journal.parent / "installed").exists()
    assert (game / "gk3hd/videos/upscaled/intro.mkv").is_file()


def test_recovery_preserves_a_user_modified_partial_install(game: Path) -> None:
    journal = _pending(game)
    assert journal.staging is not None
    (journal.parent / journal.staging).replace(journal.parent / "installed")
    modified = journal.parent / "installed/GK3HD-INTRO.AVI"
    modified.write_bytes(b"modified after interruption")
    with pytest.raises(ValueError, match="changed"):
        _installer().uninstall(game)
    assert modified.read_bytes() == b"modified after interruption"
    assert journal.path.is_file()


def test_killed_update_restores_the_previous_complete_set(game: Path) -> None:
    installer = _installer()
    installer.install(game)
    before = state_at(game)
    assert before is not None
    _add_movie(game, "second.avi")
    journal = _pending(game)
    journal = MovieJournal(game, journal.staging, journal.backup, before, journal.after)
    journal.write()
    (journal.parent / "installed").replace(journal.parent / journal.backup)
    assert journal.staging is not None
    (journal.parent / journal.staging).replace(journal.parent / "installed")
    recover(game)
    assert state_at(game) == before
    assert installer.verify(game).videos == 1
    assert not journal.path.exists()


def test_killed_uninstall_finishes_cleanup_after_the_commit_point(game: Path) -> None:
    installer = _installer()
    installer.install(game)
    before = state_at(game)
    assert before is not None
    journal = MovieJournal(game, None, f".previous-{uuid4().hex}", before, None)
    journal.write()
    (journal.parent / "installed").replace(journal.parent / journal.backup)
    (game / STATE_FILENAME).unlink()
    recover(game)
    assert not (journal.parent / journal.backup).exists()
    assert not journal.path.exists()
    assert not installer.uninstall(game).changed


def test_unsafe_journal_paths_never_authorize_removal(game: Path) -> None:
    journal = _pending(game)
    payload = json.loads(journal.path.read_bytes())
    payload["backup"] = "../../Data"
    journal.path.write_text(json.dumps(payload), encoding="utf-8")
    original = (game / "Data/intro.avi").read_bytes()
    with pytest.raises(ValueError, match="unsafe movie backup"):
        _installer().uninstall(game)
    assert (game / "Data/intro.avi").read_bytes() == original
    assert (game / JOURNAL_FILENAME).is_file()


def test_verify_reports_a_pending_transaction_without_changing_it(game: Path) -> None:
    journal = _pending(game)
    previous = journal.path.read_bytes()
    with pytest.raises(ValueError, match="interrupted"):
        MovieInstaller.verify(game)
    assert journal.path.read_bytes() == previous
