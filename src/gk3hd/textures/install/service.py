"""Reversible texture installation, verification and recovery."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

from gk3hd.system.discovery import discover_game
from gk3hd.system.files import atomic_write, is_sha256, json_bytes, sha256_file
from gk3hd.system.ini import (
    IniChange,
    apply_custom_path,
    installed_ini_matches,
    prepare_custom_path,
    restore_custom_path,
)
from gk3hd.system.locking import ExclusiveFileLock, executable_lock_path
from gk3hd.textures.install.conversion import _convert_archives, _worker_count
from gk3hd.textures.install.journal import (
    JOURNAL_FILENAME,
    JournalFile,
    TextureJournal,
    TextureJournalError,
)
from gk3hd.textures.pack.format import TexturePackError, _load_pack_set
from gk3hd.textures.pack.source import (
    TexturePackSource,
    _obtain_archives,
    discover_local_texture_pack,
)
from gk3hd.textures.progress import report_install_progress
from gk3hd.textures.workspace import (
    INSTALL_DIRECTORY,
    TEXTURES_DIRECTORY,
    WORK_DIRECTORY,
    texture_workspace_directory,
)

if TYPE_CHECKING:
    from gk3hd.textures.progress import TextureInstallProgressCallback

STATE_SCHEMA = 5

TEXTURE_DIRECTORY = f"{WORK_DIRECTORY}/{TEXTURES_DIRECTORY}/{INSTALL_DIRECTORY}"

STATE_FILENAME = ".gk3hd-textures.json"

FACES_FILENAME = "FACES.TXT"


@dataclass(frozen=True, slots=True)
class _InstalledState:
    """Validated ownership evidence; raw JSON never authorizes file removal."""

    directory: str
    pack_version: str
    texture_count: int
    files: tuple[JournalFile, ...]
    ini: IniChange


@dataclass(frozen=True, slots=True)
class TextureInstallReport:
    """Identity and file counts proven by installation or verification."""

    pack_version: str
    textures: int
    directory: Path


@dataclass(frozen=True, slots=True)
class PackInstallOptions:
    """Cache, network, guard, and progress policy for pack installation."""

    cache_dir: Path | None = None
    force: bool = False
    offline: bool = False
    progress: TextureInstallProgressCallback | None = None


def install_texture_pack(
    game_dir: Path,
    source: TexturePackSource,
    options: PackInstallOptions | None = None,
) -> TextureInstallReport:
    """Verify a local or remote pack, convert PNGs to BMPs, and install it."""
    options = options or PackInstallOptions()
    game_dir = game_dir.resolve()
    recover_texture_install(game_dir)
    target = _texture_directory(game_dir)
    state_path = game_dir / STATE_FILENAME
    if state_path.exists():
        if not options.force:
            msg = "a gk3hd texture installation already exists"
            raise TexturePackError(msg)
        uninstall_texture_pack(game_dir, force=True)
    _require_install_target_available(target)

    archives = _obtain_archives(
        source, cache_dir=options.cache_dir, offline=options.offline, progress=options.progress
    )
    manifest, part_manifests, manifest_identity = _load_pack_set(
        archives,
        progress=options.progress,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".install-", dir=target.parent))
    ini_change: IniChange | None = None
    journal: TextureJournal | None = None
    try:
        textures = _convert_archives(
            archives,
            part_manifests,
            manifest,
            staging,
            progress=options.progress,
        )
        installed = [*textures, _install_faces_file(staging)]
        report_install_progress(options.progress, "Installing textures", 0, 1)
        ini_change, ini_payload = prepare_custom_path(game_dir, TEXTURE_DIRECTORY)
        journal = TextureJournal.create(game_dir, staging, ini_change, installed)
        journal.write()
        _commit_staged_bmps(staging, target)
        apply_custom_path(game_dir, ini_change, ini_payload)
        state = {
            "directory": TEXTURE_DIRECTORY,
            "files": sorted(installed, key=lambda item: item["filename"].casefold()),
            "ini": ini_change.to_dict(),
            "manifest_sha256": manifest_identity,
            "pack_version": manifest["pack_version"],
            "schema_version": STATE_SCHEMA,
            "texture_count": manifest["texture_count"],
        }
        atomic_write(state_path, json_bytes(state))
        report_install_progress(options.progress, "Installing textures", 1, 1)
        _verify_texture_pack(
            game_dir,
            progress=options.progress,
            hash_files=False,
            description="Finalizing installation",
        )
        journal.path.unlink()
    except BaseException:
        if journal is not None and journal.path.is_file():
            _rollback_texture_journal(journal, remove_state=True)
        else:
            if ini_change is not None:
                restore_custom_path(game_dir, ini_change, force=True)
            if staging.is_dir():
                shutil.rmtree(staging)
            _prune_empty_install_directories(target, game_dir)
            state_path.unlink(missing_ok=True)
        raise
    return TextureInstallReport(manifest["pack_version"], manifest["texture_count"], target)


def verify_texture_pack(
    game_dir: Path,
    *,
    progress: TextureInstallProgressCallback | None = None,
) -> TextureInstallReport:
    """Verify every installed BMP and the managed INI state."""
    return _verify_texture_pack(
        game_dir,
        progress=progress,
        hash_files=True,
        description="Verifying installed textures",
    )


def _verify_texture_pack(
    game_dir: Path,
    *,
    progress: TextureInstallProgressCallback | None,
    hash_files: bool,
    description: str,
) -> TextureInstallReport:
    """Verify installation structure and optionally rehash every installed BMP."""
    game_dir = game_dir.resolve()
    state = _load_state(game_dir / STATE_FILENAME)
    directory = game_dir / state.directory
    expected_names = {entry.filename.casefold() for entry in state.files}
    if not directory.is_dir():
        actual_names: set[str] = set()
    else:
        actual_names = {path.name.casefold() for path in directory.iterdir()}
    if actual_names != expected_names:
        msg = "installed texture file inventory does not match its state"
        raise TexturePackError(msg)
    entries = state.files
    report_install_progress(progress, description, 0, len(entries))
    if hash_files:
        workers = _worker_count(len(entries))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gk3hd-verify") as pool:
            futures = {
                pool.submit(sha256_file, directory / entry.filename): entry for entry in entries
            }
            for index, future in enumerate(as_completed(futures), start=1):
                entry = futures[future]
                if future.result() != entry.sha256:
                    msg = f"installed texture changed after installation: {entry.filename}"
                    raise TexturePackError(msg)
                report_install_progress(progress, description, index, len(entries))
    else:
        # The hashes were computed from the exact bytes written into the staging
        # tree. Its atomic directory rename cannot alter those bytes, so an
        # immediate second multi-gigabyte read provides no additional guarantee.
        report_install_progress(progress, description, len(entries), len(entries))
    ini = state.ini
    ini_path = game_dir / ini.filename
    if not installed_ini_matches(ini_path, ini):
        msg = f"managed GK3 INI state does not verify: {ini.filename}"
        raise TexturePackError(msg)
    texture_count = state.texture_count
    return TextureInstallReport(state.pack_version, texture_count, directory)


def uninstall_texture_pack(game_dir: Path, *, force: bool = False) -> None:
    """Remove only the verified texture tree and restore exact INI bytes."""
    game_dir = game_dir.resolve()
    recover_texture_install(game_dir)
    state_path = game_dir / STATE_FILENAME
    state = _load_state(state_path)
    directory = (game_dir / state.directory).resolve()
    if directory != _texture_directory(game_dir).resolve():
        msg = f"texture state points outside the owned directory: {directory}"
        raise TexturePackError(msg)
    if not force:
        verify_texture_pack(game_dir)
    restore_custom_path(game_dir, state.ini, force=force)
    for entry in state.files:
        (directory / entry.filename).unlink(missing_ok=force)
    _prune_empty_install_directories(directory, game_dir)
    state_path.unlink()


def recover_texture_install(game_dir: Path) -> None:
    """Finish or roll back one interrupted texture commit deterministically."""
    root = game_dir.resolve()
    journal_path = root / JOURNAL_FILENAME
    if not journal_path.is_file():
        return
    journal = TextureJournal.load(root)
    state_path = root / STATE_FILENAME
    if state_path.is_file():
        verify_texture_pack(root)
        if journal.staging.is_dir():
            shutil.rmtree(journal.staging)
        journal.path.unlink()
        return
    _rollback_texture_journal(journal, remove_state=False)


def _rollback_texture_journal(journal: TextureJournal, *, remove_state: bool) -> None:
    """Restore only surfaces proven newly owned by one intent journal."""
    root = journal.game_dir
    ini_path = root / journal.ini.filename
    previous = journal.ini.previous
    installed_now = ini_path.is_file() and sha256_file(ini_path) == journal.ini.installed_sha256
    previous_now = (previous is None and not ini_path.exists()) or (
        previous is not None
        and ini_path.is_file()
        and hashlib.sha256(previous).hexdigest() == sha256_file(ini_path)
    )
    for identity in journal.files:
        installed_path = journal.target / identity.filename
        if installed_path.exists() and (
            not installed_path.is_file() or sha256_file(installed_path) != identity.sha256
        ):
            msg = f"cannot recover because {identity.filename} changed after interruption"
            raise TexturePackError(msg)
    if installed_now:
        restore_custom_path(root, journal.ini, force=True)
    elif not previous_now:
        msg = f"cannot recover because {journal.ini.filename} changed after interruption"
        raise TexturePackError(msg)
    for identity in journal.files:
        (journal.target / identity.filename).unlink(missing_ok=True)
    if journal.staging.is_dir():
        shutil.rmtree(journal.staging)
    _prune_empty_install_directories(journal.target, root)
    if remove_state:
        (root / STATE_FILENAME).unlink(missing_ok=True)
    journal.path.unlink()


def _texture_directory(game_dir: Path) -> Path:
    """Return the dedicated installed-BMP directory."""
    return game_dir / WORK_DIRECTORY / TEXTURES_DIRECTORY / INSTALL_DIRECTORY


def _require_install_target_available(target: Path) -> None:
    """Reserve the dedicated install directory for transaction-owned BMPs."""
    if target.exists():
        msg = f"texture install directory exists but is not owned by gk3hd: {target}"
        raise TexturePackError(msg)


def _commit_staged_bmps(staging: Path, target: Path) -> None:
    """Atomically publish the complete dedicated BMP directory."""
    _require_install_target_available(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging.replace(target)


def _install_faces_file(staging: Path) -> dict[str, str]:
    """Install face placement in 4x texture pixels, independent of display resolution.

    GK3 composites eyes, eyelids, foreheads and mouths into the face bitmap
    before projecting the actor into the scene. These offsets belong beside
    the replacement textures; scaling them by the screen size would be wrong.
    """
    destination = staging / FACES_FILENAME
    atomic_write(destination, files("gk3hd").joinpath(f"assets/{FACES_FILENAME}").read_bytes())
    return {"filename": destination.name, "sha256": sha256_file(destination)}


def _prune_empty_install_directories(target: Path, game_dir: Path) -> None:
    """Remove only empty generated directories, preserving every local workspace file."""
    workspace = game_dir / WORK_DIRECTORY
    texture_workspace = workspace / TEXTURES_DIRECTORY
    resolved_target = target.resolve()
    resolved_install = (texture_workspace / INSTALL_DIRECTORY).resolve()
    if resolved_target != resolved_install:
        return
    for candidate in (target, texture_workspace, workspace):
        with suppress(OSError):
            candidate.rmdir()


def _load_state(path: Path) -> _InstalledState:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"cannot read texture installation state {path}: {exc}"
        raise TexturePackError(msg) from exc
    if not isinstance(payload, dict):
        msg = f"{path}: expected a texture state object"
        raise TexturePackError(msg)
    schema = payload.get("schema_version")
    directory = payload.get("directory")
    supported_location = schema == STATE_SCHEMA and directory == TEXTURE_DIRECTORY
    if not supported_location or not isinstance(payload.get("files"), list):
        msg = f"{path}: invalid texture installation inventory"
        raise TexturePackError(msg)
    if not isinstance(payload.get("pack_version"), str):
        msg = f"{path}: invalid installed pack version"
        raise TexturePackError(msg)
    if not is_sha256(payload.get("manifest_sha256")):
        msg = f"{path}: invalid installed manifest identity"
        raise TexturePackError(msg)
    entries = payload["files"]
    if not all(isinstance(entry, dict) for entry in entries):
        msg = f"{path}: invalid installed texture entry"
        raise TexturePackError(msg)
    try:
        identities = tuple(JournalFile.from_mapping(entry) for entry in entries)
    except TextureJournalError as exc:
        msg = f"{path}: unsafe installed texture inventory"
        raise TexturePackError(msg) from exc
    names = {entry.filename.casefold() for entry in identities}
    texture_count = payload.get("texture_count")
    if (
        type(texture_count) is not int
        or texture_count <= 0
        or texture_count != len(identities) - 1
        or len(names) != len(identities)
        or FACES_FILENAME.casefold() not in names
    ):
        msg = f"{path}: invalid installed texture count or auxiliary inventory"
        raise TexturePackError(msg)
    return _InstalledState(
        TEXTURE_DIRECTORY,
        payload["pack_version"],
        texture_count,
        identities,
        IniChange.from_dict(payload.get("ini")),
    )


@dataclass(frozen=True, slots=True)
class TextureInstallRequest:
    """Target, source, cache, and guard inputs for one pack installation."""

    game_dir: Path | None = None
    exe: Path | None = None
    pack: Path | None = None
    local: bool = False
    cache_dir: Path | None = None
    force: bool = False
    offline: bool = False


def install(
    request: TextureInstallRequest,
    *,
    progress: TextureInstallProgressCallback | None = None,
) -> TextureInstallReport:
    """Install a local pack or the package's pinned remote pack."""
    target = discover_game(game_dir=request.game_dir, exe=request.exe)
    if request.local and request.pack is not None:
        msg = "--local and --pack are mutually exclusive"
        raise ValueError(msg)
    with ExclusiveFileLock(executable_lock_path(target.exe)):
        if request.local or request.pack is not None:
            source = discover_local_texture_pack(
                request.pack,
                search_directories=(texture_workspace_directory(target.game_dir),),
            )
        else:
            lock = json.loads(
                files("gk3hd").joinpath("assets/texture-pack-lock.json").read_text(encoding="utf-8")
            )
            source = TexturePackSource.from_lock(lock)
            if not source.assets:
                # Only unpinned development checkouts consult ambient packs.
                with suppress(TexturePackError):
                    source = discover_local_texture_pack(
                        None,
                        search_directories=(texture_workspace_directory(target.game_dir),),
                    )
        return install_texture_pack(
            target.game_dir,
            source,
            PackInstallOptions(
                cache_dir=request.cache_dir,
                force=request.force,
                offline=request.offline,
                progress=progress,
            ),
        )


def verify(*, game_dir: Path | None = None, exe: Path | None = None) -> TextureInstallReport:
    """Verify installed texture bytes and the INI edit."""
    target = discover_game(game_dir=game_dir, exe=exe)
    with ExclusiveFileLock(executable_lock_path(target.exe)):
        recover_texture_install(target.game_dir)
        return verify_texture_pack(target.game_dir)


def uninstall(
    *,
    game_dir: Path | None = None,
    exe: Path | None = None,
    force: bool = False,
) -> None:
    """Remove verified installed textures and restore the exact INI."""
    target = discover_game(game_dir=game_dir, exe=exe)
    with ExclusiveFileLock(executable_lock_path(target.exe)):
        uninstall_texture_pack(target.game_dir, force=force)


def recover(*, game_dir: Path | None = None, exe: Path | None = None) -> None:
    """Recover a component transaction under the executable-wide lock."""
    target = discover_game(game_dir=game_dir, exe=exe)
    with ExclusiveFileLock(executable_lock_path(target.exe)):
        recover_texture_install(target.game_dir)
