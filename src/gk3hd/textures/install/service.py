"""Reversible texture installation, verification and recovery."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from dataclasses import dataclass, replace
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
    rebase_custom_path,
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
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class TextureInstallReport:
    """Identity and file counts proven by installation or verification."""

    pack_version: str
    textures: int
    directory: Path
    changed: bool = True


@dataclass(frozen=True, slots=True)
class PackInstallOptions:
    """Cache, network, guard, and progress policy for pack installation."""

    cache_dir: Path | None = None
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
    before = None
    if state_path.exists():
        before = _load_state(state_path)
        _verify_texture_pack(
            game_dir,
            progress=options.progress,
            hash_files=True,
            description="Verifying installed textures",
            check_ini=False,
        )
        if _matches_current(before, source.inventory_sha256) and installed_ini_matches(
            game_dir / before.ini.filename, before.ini
        ):
            return TextureInstallReport(
                before.pack_version, before.texture_count, target, changed=False
            )
    else:
        _require_install_target_available(target)

    prepared = _stage_pack(game_dir, source, options, before)
    if prepared is None and before is not None:
        return TextureInstallReport(
            before.pack_version, before.texture_count, target, changed=False
        )
    if prepared is None:
        msg = "texture preparation produced no installation"
        raise TexturePackError(msg)
    staging, installed, pack_version, texture_count, manifest_identity = prepared
    ini_change: IniChange | None = None
    journal: TextureJournal | None = None
    try:
        report_install_progress(options.progress, "Installing textures", 0, 1)
        ini_change, ini_payload = prepare_custom_path(game_dir, TEXTURE_DIRECTORY)
        journal = TextureJournal.create(game_dir, staging, ini_change, installed)
        state = {
            "directory": TEXTURE_DIRECTORY,
            "files": sorted(installed, key=lambda item: item["filename"].casefold()),
            "ini": (
                rebase_custom_path(game_dir, before.ini, ini_change, TEXTURE_DIRECTORY)
                if before
                else ini_change
            ).to_dict(),
            "manifest_sha256": manifest_identity,
            "pack_version": pack_version,
            "schema_version": STATE_SCHEMA,
            "texture_count": texture_count,
        }
        if before:
            journal = replace(
                journal,
                before_state=state_path.read_text(encoding="utf-8"),
                after_state=json_bytes(state).decode("utf-8"),
            )
        journal.write()
        if before:
            target.replace(journal.backup)
        _commit_staged_bmps(staging, target)
        apply_custom_path(game_dir, ini_change, ini_payload)
        atomic_write(state_path, json_bytes(state))
        report_install_progress(options.progress, "Installing textures", 1, 1)
        _verify_texture_pack(
            game_dir,
            progress=options.progress,
            hash_files=False,
            description="Finalizing installation",
        )
        if before:
            _remove_owned_tree(journal.backup, before.files)
        journal.path.unlink()
    except BaseException as error:
        try:
            _recover_failed_install(game_dir, journal, staging, ini_change, before)
        except Exception as recovery_error:  # noqa: BLE001 - retain both failures and recovery intent.
            error.add_note(f"texture recovery also failed: {recovery_error}")
        raise
    return TextureInstallReport(pack_version, texture_count, target)


def _stage_pack(
    game_dir: Path,
    source: TexturePackSource,
    options: PackInstallOptions,
    before: _InstalledState | None,
) -> tuple[Path, list[dict[str, str]], str, int, str] | None:
    """Prepare a complete replacement without changing the active installation."""
    archives = ()
    reuse = before is not None and before.manifest_sha256 == source.inventory_sha256
    if not reuse:
        archives = _obtain_archives(
            source, cache_dir=options.cache_dir, offline=options.offline, progress=options.progress
        )
        manifest, parts, identity = _load_pack_set(archives, progress=options.progress)
        if (
            before is not None
            and _matches_current(before, identity)
            and installed_ini_matches(game_dir / before.ini.filename, before.ini)
        ):
            return None
        reuse = before is not None and before.manifest_sha256 == identity
    parent = _texture_directory(game_dir).parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".install-", dir=parent))
    try:
        if reuse and before is not None:
            textures = []
            for entry in before.files:
                if entry.filename == FACES_FILENAME:
                    continue
                original = _texture_directory(game_dir) / entry.filename
                try:
                    (staging / entry.filename).hardlink_to(original)
                except OSError:
                    shutil.copyfile(original, staging / entry.filename)
                textures.append(entry.to_dict())
            version, count, identity = (
                before.pack_version,
                before.texture_count,
                before.manifest_sha256,
            )
        else:
            textures = _convert_archives(
                archives, parts, manifest, staging, progress=options.progress
            )
            version, count = manifest["pack_version"], manifest["texture_count"]
        return staging, [*textures, _install_faces_file(staging)], version, count, identity
    except BaseException:
        shutil.rmtree(staging)
        raise


def _recover_failed_install(
    game_dir: Path,
    journal: TextureJournal | None,
    staging: Path,
    ini_change: IniChange | None,
    before: _InstalledState | None,
) -> None:
    """Use durable intent when present; otherwise discard only our unpublished stage."""
    if journal is not None and journal.path.is_file():
        if journal.before_state:
            _recover_texture_update(journal)
        else:
            _rollback_texture_journal(journal, remove_state=True)
        return
    if ini_change is not None:
        restore_custom_path(game_dir, ini_change, force=True)
    if staging.is_dir():
        shutil.rmtree(staging)
    _prune_empty_install_directories(_texture_directory(game_dir), game_dir)
    if before is None:
        (game_dir / STATE_FILENAME).unlink(missing_ok=True)


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
    check_ini: bool = True,
) -> TextureInstallReport:
    """Verify installation structure and optionally rehash every installed BMP."""
    game_dir = game_dir.resolve()
    state = _load_state(game_dir / STATE_FILENAME)
    directory = _texture_directory(game_dir)
    if directory.is_symlink() or directory.is_junction():
        msg = f"unsafe texture directory: {directory}"
        raise TexturePackError(msg)
    expected_names = {entry.filename.casefold() for entry in state.files}
    if not directory.is_dir():
        actual_names: set[str] = set()
    else:
        actual_names = {path.name.casefold() for path in directory.iterdir()}
    if actual_names != expected_names:
        msg = "installed texture file inventory does not match its state"
        raise TexturePackError(msg)
    entries = state.files
    for entry in entries:
        path = directory / entry.filename
        if path.is_symlink() or not path.is_file():
            msg = f"unsafe installed texture: {entry.filename}"
            raise TexturePackError(msg)
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
    if check_ini and not installed_ini_matches(ini_path, ini):
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
    if journal.before_state:
        _recover_texture_update(journal)
        return
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
    target = game_dir / WORK_DIRECTORY / TEXTURES_DIRECTORY / INSTALL_DIRECTORY
    if target.resolve() != target:
        msg = f"texture installation path was redirected: {target}"
        raise TexturePackError(msg)
    return target


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
    return _state_from_payload(payload, path)


def _state_from_payload(payload: object, path: Path) -> _InstalledState:
    """Validate persisted and journaled inventories by the same ownership rules."""
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
        payload["manifest_sha256"],
    )


def _check_owned_tree(
    directory: Path, entries: tuple[JournalFile, ...], *, allow_missing: bool = False
) -> None:
    """Prove the complete flat inventory before any rename or removal."""
    if directory.is_symlink() or directory.is_junction() or not directory.is_dir():
        msg = f"unsafe texture directory: {directory}"
        raise TexturePackError(msg)
    actual = {p.name for p in directory.iterdir()}
    expected = {entry.filename for entry in entries}
    if actual - expected or (not allow_missing and actual != expected):
        msg = f"texture directory contains missing or unowned files: {directory}"
        raise TexturePackError(msg)
    for entry in entries:
        path = directory / entry.filename
        if allow_missing and not path.exists():
            continue
        if path.is_symlink() or not path.is_file() or sha256_file(path) != entry.sha256:
            msg = f"texture changed during installation: {entry.filename}"
            raise TexturePackError(msg)


def _remove_owned_tree(directory: Path, entries: tuple[JournalFile, ...]) -> None:
    """Delete only a complete verified prior or staged installation."""
    if not directory.exists():
        return
    _check_owned_tree(directory, entries, allow_missing=True)
    for entry in entries:
        (directory / entry.filename).unlink(missing_ok=True)
    directory.rmdir()


def _recover_texture_update(journal: TextureJournal) -> None:
    """Complete a committed swap or restore the prior tree and exact INI."""
    root = journal.game_dir
    before = _state_from_payload(json.loads(journal.before_state or "null"), journal.path)
    after = _state_from_payload(json.loads(journal.after_state or "null"), journal.path)
    if set(after.files) != set(journal.files):
        msg = "texture update journal contradicts its intended inventory"
        raise TexturePackError(msg)
    state_path = root / STATE_FILENAME
    current = state_path.read_text(encoding="utf-8")
    if current not in {journal.before_state, journal.after_state}:
        msg = "texture state changed outside the interrupted update"
        raise TexturePackError(msg)
    if current == journal.after_state:
        verify_texture_pack(root)
        _remove_owned_tree(journal.backup, before.files)
    else:
        ini_path = root / journal.ini.filename
        if installed_ini_matches(ini_path, journal.ini):
            restore_custom_path(root, journal.ini)
        elif (ini_path.read_bytes() if ini_path.exists() else None) != journal.ini.previous:
            msg = "GK3 INI changed outside the interrupted texture update"
            raise TexturePackError(msg)
        if journal.backup.exists():
            _check_owned_tree(journal.backup, before.files)
            _remove_owned_tree(journal.target, after.files)
            journal.backup.replace(journal.target)
        else:
            _check_owned_tree(journal.target, before.files)
    _remove_owned_tree(journal.staging, after.files)
    journal.path.unlink()


@dataclass(frozen=True, slots=True)
class TextureInstallRequest:
    """Target, source, cache, and guard inputs for one pack installation."""

    game_dir: Path | None = None
    exe: Path | None = None
    pack: Path | None = None
    local: bool = False
    cache_dir: Path | None = None
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
        source = _request_source(request, target.game_dir)
        return install_texture_pack(
            target.game_dir,
            source,
            PackInstallOptions(
                cache_dir=request.cache_dir,
                offline=request.offline,
                progress=progress,
            ),
        )


def _matches_current(state: _InstalledState, inventory_sha256: str | None) -> bool:
    """Reuse a pack only if its logical inventory and bundled face correction match."""
    faces = files("gk3hd").joinpath(f"assets/{FACES_FILENAME}").read_bytes()
    return inventory_sha256 == state.manifest_sha256 and any(
        entry.filename == FACES_FILENAME and entry.sha256 == hashlib.sha256(faces).hexdigest()
        for entry in state.files
    )


def _request_source(request: TextureInstallRequest, game_dir: Path) -> TexturePackSource:
    """Resolve the same explicit, local or pinned source for preparation and install."""
    if request.local or request.pack is not None:
        return discover_local_texture_pack(
            request.pack, search_directories=(texture_workspace_directory(game_dir),)
        )
    lock = json.loads(
        files("gk3hd").joinpath("assets/texture-pack-lock.json").read_text(encoding="utf-8")
    )
    source = TexturePackSource.from_lock(lock)
    if not source.assets:
        with suppress(TexturePackError):
            return discover_local_texture_pack(
                None, search_directories=(texture_workspace_directory(game_dir),)
            )
    return source


def prefetch(
    request: TextureInstallRequest, *, progress: TextureInstallProgressCallback | None = None
) -> None:
    """Cache and validate required archives before a composed update mutates the game."""
    target = discover_game(game_dir=request.game_dir, exe=request.exe)
    source = _request_source(request, target.game_dir)
    state = target.game_dir / STATE_FILENAME
    if state.is_file() and _matches_current(_load_state(state), source.inventory_sha256):
        return
    archives = _obtain_archives(
        source, cache_dir=request.cache_dir, offline=request.offline, progress=progress
    )
    _load_pack_set(archives, progress=progress)


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
