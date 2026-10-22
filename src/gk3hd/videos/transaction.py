"""Recoverable directory swaps, bounded by strict movie-file ownership evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from gk3hd.system.files import atomic_write, json_bytes, sha256_file
from gk3hd.videos.catalog import MOVIE_INSTALL_PATH
from gk3hd.videos.manifest import JOURNAL_FILENAME, STATE_FILENAME, MovieState, read_json

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

type MovieProgress = Callable[[str, int, int], None]


def workspace(root: Path) -> Path:
    """Reject linked or non-directory surfaces inside the fixed movie workspace."""
    candidate = root
    for part in MOVIE_INSTALL_PATH.split("/"):
        candidate /= part
        if (
            candidate.is_symlink()
            or candidate.is_junction()
            or (candidate.exists() and not candidate.is_dir())
        ):
            msg = f"unsafe movie installation directory: {candidate}"
            raise ValueError(msg)
    return candidate.parent


def state_at(root: Path) -> MovieState | None:
    """Load existing ownership evidence without assuming a missing file is valid."""
    path = root / STATE_FILENAME
    if path.is_symlink():
        msg = "movie state must not be a symbolic link"
        raise ValueError(msg)
    return MovieState.from_dict(read_json(path)) if path.exists() else None


def check_tree(
    directory: Path,
    state: MovieState,
    *,
    allow_missing: bool = False,
    progress: MovieProgress | None = None,
) -> None:
    """Validate all present files before deleting or replacing any of them."""
    if directory.is_symlink() or directory.is_junction():
        msg = f"movie ownership cannot authorize a linked directory: {directory}"
        raise ValueError(msg)
    if not directory.exists() and allow_missing:
        return
    expected = {entry.filename for entry in state.inventory}
    actual = {path.name for path in directory.iterdir()}
    if actual - expected or (not allow_missing and actual != expected):
        msg = f"movie directory contains missing or unowned files: {directory}"
        raise ValueError(msg)
    total = sum(entry.size for entry in state.inventory)
    completed = 0
    for entry in state.inventory:
        path = directory / entry.filename
        if path.is_symlink():
            msg = f"installed movie is a symbolic link: {entry.filename}"
            raise ValueError(msg)
        if path.exists() and (
            not path.is_file()
            or path.stat().st_size != entry.size
            or sha256_file(path) != entry.sha256
        ):
            msg = f"installed movie changed: {entry.filename}"
            raise ValueError(msg)
        completed += entry.size
        if progress is not None:
            progress("Verifying videos", completed, total)


def prune_tree(directory: Path, state: MovieState) -> None:
    """Remove only validated owned files, tolerating already removed recovery files."""
    check_tree(directory, state, allow_missing=True)
    if not directory.exists():
        return
    for entry in state.inventory:
        (directory / entry.filename).unlink(missing_ok=True)
    directory.rmdir()


@dataclass(frozen=True, slots=True)
class MovieJournal:
    """Intent published before atomic directory renames and the state commit point."""

    root: Path
    staging: str | None
    backup: str
    before: MovieState | None
    after: MovieState | None

    @property
    def parent(self) -> Path:
        """Bind every transient directory to the fixed validated workspace."""
        return workspace(self.root)

    @property
    def path(self) -> Path:
        """Use one fixed, recoverable journal per installation."""
        return self.root / JOURNAL_FILENAME

    def write(self) -> None:
        """Persist rollback identities before moving an installed directory."""
        atomic_write(
            self.path,
            json_bytes(
                {
                    "schema_version": 1,
                    "staging": self.staging,
                    "backup": self.backup,
                    "before": self.before.to_dict() if self.before else None,
                    "after": self.after.to_dict() if self.after else None,
                }
            ),
        )

    @classmethod
    def load(cls, root: Path) -> Self:
        """Validate transient names and state before any recovery mutation."""
        value = read_json(root / JOURNAL_FILENAME)
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            msg = "invalid movie recovery journal"
            raise ValueError(msg)
        backup, staging = value.get("backup"), value.get("staging")
        if not isinstance(backup, str) or not re.fullmatch(r"\.previous-[0-9a-f]{32}", backup):
            msg = "unsafe movie backup directory"
            raise ValueError(msg)
        if staging is not None and (
            not isinstance(staging, str) or not re.fullmatch(r"\.install-[0-9a-f]{32}", staging)
        ):
            msg = "unsafe movie staging directory"
            raise ValueError(msg)
        before = MovieState.from_dict(value["before"]) if value.get("before") is not None else None
        after = MovieState.from_dict(value["after"]) if value.get("after") is not None else None
        if (before is None and after is None) or (staging is None) != (after is None):
            msg = "movie recovery journal has an incomplete transaction"
            raise ValueError(msg)
        return cls(root, staging, backup, before, after)

    def commit(self) -> None:
        """Atomically publish the staged movie set, then its ownership state."""
        target, backup = self.parent / "installed", self.parent / self.backup
        if state_at(self.root) != self.before:
            msg = "movie ownership state changed while preparing installation"
            raise ValueError(msg)
        if target.exists():
            if self.before is None:
                msg = "an unowned movie directory appeared while preparing installation"
                raise ValueError(msg)
            check_tree(target, self.before)
            target.replace(backup)
        if self.staging is not None:
            (self.parent / self.staging).replace(target)
        if self.after is None:
            (self.root / STATE_FILENAME).unlink()
        else:
            atomic_write(self.root / STATE_FILENAME, json_bytes(self.after.to_dict()))
        self.finish()

    def finish(self) -> None:
        """Finish committed cleanup, also after a crash midway through removal."""
        if self.before is not None:
            prune_tree(self.parent / self.backup, self.before)
        if self.staging is not None and self.after is not None:
            prune_tree(self.parent / self.staging, self.after)
        self.path.unlink()

    def recover(self) -> None:
        """Complete a recorded commit or restore the previous complete movie set."""
        current = state_at(self.root)
        if current not in (self.before, self.after):
            msg = "movie state changed during interrupted installation"
            raise ValueError(msg)
        target, backup = self.parent / "installed", self.parent / self.backup
        if current == self.after:
            if self.after is not None:
                check_tree(target, self.after)
            elif target.exists():
                msg = "unexpected movie directory after interrupted uninstall"
                raise ValueError(msg)
            self.finish()
            return
        self._rollback(target, backup)

    def _rollback(self, target: Path, backup: Path) -> None:
        if (
            not backup.exists()
            and self.staging is not None
            and self.after is not None
            and (self.parent / self.staging).exists()
        ):
            # No directory swap occurred. Preserve any foreign target or edits
            # made while the long staging copy was in progress.
            prune_tree(self.parent / self.staging, self.after)
            self.path.unlink()
            return
        if backup.exists():
            if self.before is None:
                msg = "unowned movie backup blocks recovery"
                raise ValueError(msg)
            check_tree(backup, self.before)
            if self.after is not None:
                prune_tree(target, self.after)
            backup.replace(target)
        elif self.before is not None:
            check_tree(target, self.before)
        elif self.after is not None:
            prune_tree(target, self.after)
        if self.before is None:
            (self.root / STATE_FILENAME).unlink(missing_ok=True)
        else:
            atomic_write(self.root / STATE_FILENAME, json_bytes(self.before.to_dict()))
        if self.staging is not None and self.after is not None:
            prune_tree(self.parent / self.staging, self.after)
        self.path.unlink()


def recover(root: Path) -> None:
    """Recover a pending movie transaction while the caller holds the game lock."""
    path = root / JOURNAL_FILENAME
    if path.is_symlink():
        msg = "movie recovery journal must not be a symbolic link"
        raise ValueError(msg)
    if path.exists():
        MovieJournal.load(root).recover()
