"""Install verified local movie outputs without modifying originals or GK3.ini."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from gk3hd.patch.install.windows import is_gk3_running
from gk3hd.system.discovery import GameTarget, discover_game
from gk3hd.system.files import sha256_file
from gk3hd.system.locking import ExclusiveFileLock, executable_lock_path
from gk3hd.videos.catalog import movie_format, movie_workspace, replacement_name
from gk3hd.videos.manifest import (
    JOURNAL_FILENAME,
    MovieFile,
    MovieState,
    PlayerResource,
    read_json,
    validate_generation,
)
from gk3hd.videos.runtime import inspect_player, local_player
from gk3hd.videos.transaction import (
    MovieJournal,
    check_tree,
    prune_tree,
    recover,
    state_at,
    workspace,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from gk3hd.videos.transaction import MovieProgress

_COPY_BLOCK = 1024 * 1024


@dataclass(frozen=True, slots=True)
class MovieInstallReport:
    """Describe the complete installed set and whether files changed."""

    videos: int
    directory: Path
    changed: bool


@dataclass(frozen=True, slots=True)
class _MovieSource:
    path: Path
    identity: MovieFile | PlayerResource


class MovieInstaller:
    """Serialize changes with other game components and preserve foreign files."""

    def __init__(self, *, process_probe: Callable[[], bool] | None = None) -> None:
        """Default to native game detection, allowing deterministic unit adapters."""
        self._process_probe = process_probe or is_gk3_running

    def install(
        self,
        game_dir: Path,
        source: Path | None = None,
        *,
        player: Path | None = None,
        progress: MovieProgress | None = None,
    ) -> MovieInstallReport:
        """Install or update a complete verified set through an atomic directory swap."""
        target = discover_game(game_dir=game_dir)
        source = (source or movie_workspace(target.game_dir) / "upscaled").resolve()
        with ExclusiveFileLock(executable_lock_path(target.exe)):
            self._require_stopped()
            recover(target.game_dir)
            parent = workspace(target.game_dir)
            directory = parent / "installed"
            before = state_at(target.game_dir)
            _check_previous(directory, before, progress)
            inputs = _generated_movies(source, target)
            resources = ()
            if any(item.path.suffix.casefold() == ".mkv" for item in inputs):
                directory_player = player or local_player(target.game_dir)
                resources = tuple(
                    _MovieSource(directory_player / name, PlayerResource(name, digest, size))
                    for name, digest, size in inspect_player(directory_player)
                )
            after = MovieState(
                tuple(item.identity for item in inputs if isinstance(item.identity, MovieFile)),
                tuple(
                    item.identity for item in resources if isinstance(item.identity, PlayerResource)
                ),
            )
            if after == before:
                return MovieInstallReport(len(after.files), directory, changed=False)
            staging = _stage((*inputs, *resources), parent, progress)
            journal = MovieJournal(
                target.game_dir, staging.name, f".previous-{uuid4().hex}", before, after
            )
            _commit(journal)
            return MovieInstallReport(len(after.files), directory, changed=True)

    @staticmethod
    def verify(game_dir: Path, *, progress: MovieProgress | None = None) -> MovieInstallReport:
        """Hash every installed movie and validate its original source identity."""
        target = discover_game(game_dir=game_dir)
        with ExclusiveFileLock(executable_lock_path(target.exe)):
            directory = workspace(target.game_dir) / "installed"
            if (target.game_dir / JOURNAL_FILENAME).exists():
                msg = "interrupted movie transaction; rerun videos install or uninstall to recover"
                raise ValueError(msg)
            state = state_at(target.game_dir)
            if state is None:
                msg = "gk3hd videos are not installed"
                raise ValueError(msg)
            check_tree(directory, state, progress=progress)
            _verify_originals(target.data_dir, state.files)
            return MovieInstallReport(len(state.files), directory, changed=False)

    def uninstall(
        self, game_dir: Path, *, progress: MovieProgress | None = None
    ) -> MovieInstallReport:
        """Remove only unchanged, owned replacements, preserving other components."""
        target = discover_game(game_dir=game_dir)
        with ExclusiveFileLock(executable_lock_path(target.exe)):
            self._require_stopped()
            recover(target.game_dir)
            directory = workspace(target.game_dir) / "installed"
            before = state_at(target.game_dir)
            if before is None:
                return MovieInstallReport(0, directory, changed=False)
            check_tree(directory, before, progress=progress)
            journal = MovieJournal(target.game_dir, None, f".previous-{uuid4().hex}", before, None)
            _commit(journal)
            return MovieInstallReport(len(before.files), directory, changed=True)

    def _require_stopped(self) -> None:
        if self._process_probe():
            msg = "close GK3 before installing or uninstalling videos"
            raise ValueError(msg)

    def recover(self, game_dir: Path) -> None:
        """Recover a pending video transaction under the same lock as installation."""
        target = discover_game(game_dir=game_dir)
        with ExclusiveFileLock(executable_lock_path(target.exe)):
            if (target.game_dir / JOURNAL_FILENAME).exists():
                self._require_stopped()
            recover(target.game_dir)


def _check_previous(
    directory: Path, before: MovieState | None, progress: MovieProgress | None
) -> None:
    if before is not None:
        check_tree(directory, before, progress=progress)
    elif directory.exists():
        msg = f"refusing to replace an unowned movie directory: {directory}"
        raise ValueError(msg)


def _originals(directory: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for path in directory.iterdir():
        if path.is_file() and path.suffix.casefold() in {".avi", ".bik"}:
            key = path.name.casefold()
            if key in paths:
                msg = f"ambiguous original movie name: {path.name}"
                raise ValueError(msg)
            paths[key] = path
    return paths


def _verify_originals(directory: Path, entries: Sequence[MovieFile]) -> None:
    originals = _originals(directory)
    for entry in entries:
        path = originals.get(entry.source_name.casefold())
        if path is None or sha256_file(path) != entry.source_sha256:
            msg = f"original movie no longer matches the generated replacement: {entry.source_name}"
            raise ValueError(msg)


def _generated_movies(source: Path, target: GameTarget) -> tuple[_MovieSource, ...]:
    inputs: list[_MovieSource] = []
    for record in sorted(source.glob("*.mkv.json")):
        try:
            payload = validate_generation(read_json(record))
        except TypeError as exc:
            msg = f"invalid movie generation record {record.name}: {exc}"
            raise ValueError(msg) from exc
        if payload.get("pipeline") != "seedvr2":
            msg = "technical animations must use original game files, not generated replacements"
            raise ValueError(msg)
        path = record.with_suffix("")
        if payload.get("codec") != "libaom-av1":
            msg = (
                f"movie encoding is incompatible or unspecified: {path.name}; "
                "regenerate with gk3hd videos upscale"
            )
            raise ValueError(msg)
        name = payload.get("source_name")
        if not isinstance(name, str) or path.stem.casefold() != Path(name).stem.casefold():
            msg = f"movie generation record has an inconsistent name: {record.name}"
            raise ValueError(msg)
        identity = MovieFile.from_dict(
            {
                "filename": replacement_name(name),
                "source_name": name,
                "source_sha256": payload.get("source_sha256"),
                "sha256": payload.get("output_sha256"),
                "size": path.stat().st_size,
            }
        )
        if movie_format(path) != "Matroska":
            msg = f"generated movie has an incorrect media header: {path.name}"
            raise ValueError(msg)
        inputs.append(_MovieSource(path, identity))
    if not inputs:
        msg = f"no generated videos in {source}; run videos upscale first"
        raise ValueError(msg)
    state = MovieState(
        tuple(item.identity for item in inputs if isinstance(item.identity, MovieFile))
    )
    _verify_originals(target.data_dir, state.files)
    return tuple(inputs)


def _stage(inputs: Sequence[_MovieSource], parent: Path, progress: MovieProgress | None) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    total = sum(item.identity.size for item in inputs)
    if shutil.disk_usage(parent).free < total:
        msg = f"not enough free space to install {total:,} bytes of videos"
        raise ValueError(msg)
    staging = parent / f".install-{uuid4().hex}"
    staging.mkdir()
    completed = 0
    try:
        for item in inputs:
            completed = _copy_movie(item, staging, completed, total, progress)
    except BaseException:
        # This live transaction created these paths; incomplete copies are not
        # pre-existing user files. Do not recursively delete other contents.
        for item in inputs:
            (staging / item.identity.filename).unlink(missing_ok=True)
        staging.rmdir()
        raise
    return staging


def _copy_movie(
    item: _MovieSource, staging: Path, completed: int, total: int, progress: MovieProgress | None
) -> int:
    digest = hashlib.sha256()
    copied = 0
    with item.path.open("rb") as original, (staging / item.identity.filename).open("xb") as output:
        while block := original.read(_COPY_BLOCK):
            output.write(block)
            digest.update(block)
            copied += len(block)
            if progress is not None:
                progress(f"Installing {item.identity.filename}", completed + copied, total)
    if digest.hexdigest() != item.identity.sha256 or copied != item.identity.size:
        msg = f"generated movie changed or failed verification: {item.path.name}"
        raise ValueError(msg)
    return completed + copied


def _commit(journal: MovieJournal) -> None:
    try:
        journal.write()
        journal.commit()
    except BaseException as error:
        try:
            if journal.path.exists():
                MovieJournal.load(journal.root).recover()
            elif journal.staging is not None and journal.after is not None:
                prune_tree(journal.parent / journal.staging, journal.after)
        except (OSError, ValueError) as recovery_error:
            error.add_note(f"movie recovery also needs attention: {recovery_error}")
        raise
