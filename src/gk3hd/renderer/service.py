"""Recoverable renderer install, replacement, verification and removal."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING

from gk3hd.patch.install.platform import default_configuration
from gk3hd.patch.install.windows import is_gk3_running, local_graphics_proxy_dlls
from gk3hd.patch.manifest import manifest_path_for_exe
from gk3hd.renderer import distribution
from gk3hd.renderer.build import local_build
from gk3hd.renderer.state import JOURNAL_FILENAME, STATE_FILENAME, RendererState
from gk3hd.system.discovery import discover_game
from gk3hd.system.files import atomic_write
from gk3hd.system.locking import ExclusiveFileLock, executable_lock_path

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from gk3hd.patch.install.windows import WindowsInstallConfiguration
    from gk3hd.system.download import ProgressCallback


def download(*, progress: ProgressCallback | None = None) -> Path:
    """Cache the latest published DLL without changing the game."""
    payload = distribution.dll_bytes(progress=progress)
    return distribution.cached_path(hashlib.sha256(payload).hexdigest())


class RendererService:
    """Own renderer state under the same lock used by patch transactions."""

    def __init__(
        self,
        *,
        configuration: WindowsInstallConfiguration | None = None,
        process_probe: Callable[[], bool] = is_gk3_running,
    ) -> None:
        """Permit isolated adapters for transaction tests."""
        self._configuration = configuration
        self._process_probe = process_probe

    def _adapter(self, exe: Path) -> WindowsInstallConfiguration:
        return self._configuration or default_configuration(exe)

    def _require_stopped(self) -> None:
        if self._process_probe():
            msg = "close GK3 before changing the renderer"
            raise RuntimeError(msg)

    def install(
        self,
        *,
        game_dir: Path | None = None,
        exe: Path | None = None,
        dll: Path | None = None,
        local: bool = False,
        progress: ProgressCallback | None = None,
    ) -> RendererState:
        """Replace managed state while preserving its original uninstall baseline."""
        if local and dll is not None:
            msg = "choose --local or --dll, not both"
            raise ValueError(msg)
        target = discover_game(game_dir=game_dir, exe=exe).exe
        self._require_stopped()
        asset = local_build(game_dir=target.parent) if local else None
        path = (
            asset.path
            if asset is not None
            else dll
            if dll is not None
            else download(progress=progress)
        )
        payload = path.read_bytes()
        distribution.validate_dll(payload)
        digest = hashlib.sha256(payload).hexdigest()
        if asset is not None and digest != asset.dll_sha256:
            msg = "local renderer changed after build verification"
            raise ValueError(msg)
        atomic_write(distribution.cached_path(digest), payload)
        with ExclusiveFileLock(executable_lock_path(target)):
            self._require_stopped()
            self._recover(target)
            adapter = self._adapter(target)
            before = RendererState.load(target)
            if before:
                adapter.verify(exe=target, changes=before.changes)
            conflicts = local_graphics_proxy_dlls(target.parent, allow_owned_d7vk=True)
            if conflicts:
                msg = f"unmanaged graphics DLLs conflict with D7VK: {', '.join(conflicts)}"
                raise ValueError(msg)
            transition = RendererState(
                adapter.prepare_renderer(exe=target, digest=digest), target.name
            )
            originals = {(c.surface, c.key): c.previous for c in before.changes} if before else {}
            after = RendererState(
                tuple(
                    replace(c, previous=originals.get((c.surface, c.key), c.previous))
                    for c in transition.changes
                ),
                target.name,
            )
            self._journal(target, "install", before, transition)
            try:
                adapter.apply(exe=target, changes=transition.changes)
                adapter.verify(exe=target, changes=after.changes)
                self._write_state(target, after)
                target.with_name(JOURNAL_FILENAME).unlink()
            except BaseException as error:
                try:
                    self._recover(target)
                except Exception as recovery_error:  # noqa: BLE001 - retain primary failure and journal.
                    error.add_note(f"renderer recovery also failed: {recovery_error}")
                raise
            return after

    def verify(self, *, game_dir: Path | None = None, exe: Path | None = None) -> RendererState:
        """Verify renderer files and launch settings without resolving a newer version."""
        target = discover_game(game_dir=game_dir, exe=exe).exe
        with ExclusiveFileLock(executable_lock_path(target)):
            state = RendererState.load(target)
            if state is None or target.with_name(JOURNAL_FILENAME).exists():
                msg = (
                    "renderer is not installed or has an interrupted transaction; "
                    "run renderer install"
                )
                raise ValueError(msg)
            self._adapter(target).verify(exe=target, changes=state.changes)
            return state

    def recover(self, *, exe: Path) -> None:
        """Finish a pending removal or undo a pending installation."""
        with ExclusiveFileLock(executable_lock_path(exe)):
            self._recover(exe)

    def _recover(self, exe: Path) -> None:
        path = exe.with_name(JOURNAL_FILENAME)
        if not path.exists():
            return
        self._require_stopped()
        payload = json.loads(path.read_bytes())
        if (
            not isinstance(payload, dict)
            or set(payload) != {"action", "before", "transition"}
            or payload["action"] not in {"install", "uninstall"}
        ):
            msg = "invalid renderer recovery journal"
            raise ValueError(msg)
        transition = RendererState.parse(payload["transition"], exe=exe)
        before = (
            RendererState.parse(payload["before"], exe=exe)
            if payload["before"] is not None
            else None
        )
        current = RendererState.load(exe)
        original_values = {(c.surface, c.key): c.previous for c in before.changes} if before else {}
        intended = RendererState(
            tuple(
                replace(c, previous=original_values.get((c.surface, c.key), c.previous))
                for c in transition.changes
            ),
            exe.name,
        )
        allowed = (before, intended) if payload["action"] == "install" else (before, None)
        if current not in allowed:
            msg = "renderer ownership record changed outside the interrupted transaction"
            raise ValueError(msg)
        self._adapter(exe).recover_interrupted_apply(exe=exe, changes=transition.changes)
        self._write_state(exe, before if payload["action"] == "install" else None)
        path.unlink()

    def uninstall(
        self,
        *,
        game_dir: Path | None = None,
        exe: Path | None = None,
        restoring_composite: bool = False,
    ) -> None:
        """Restore renderer state only after dependent executable patches are removed."""
        target = discover_game(game_dir=game_dir, exe=exe).exe
        with ExclusiveFileLock(executable_lock_path(target)):
            self._require_stopped()
            self._recover(target)
            if manifest_path_for_exe(target).is_file() and not restoring_composite:
                msg = (
                    "remove executable patches first with gk3hd patch uninstall, "
                    "or use gk3hd uninstall"
                )
                raise ValueError(msg)
            if restoring_composite:
                self._require_composite_rollback(target)
            state = RendererState.load(target)
            if state is None:
                return
            self._adapter(target).verify(exe=target, changes=state.changes)
            self._journal(target, "uninstall", state, state)
            self._recover(target)

    @staticmethod
    def _require_composite_rollback(exe: Path) -> None:
        """Only a recorded pre-install absence can bypass the dependency guard."""
        journal = json.loads(exe.with_name(".gk3hd-install.json").read_bytes())
        if (
            not isinstance(journal, dict)
            or journal.get("schema_version") != 1
            or journal.get("renderer_existed") is not False
            or not isinstance(journal.get("patch_existed"), bool)
            or not isinstance(journal.get("textures_existed"), bool)
        ):
            msg = "no composite transaction authorizes restoring the absent renderer"
            raise ValueError(msg)

    @staticmethod
    def _write_state(exe: Path, state: RendererState | None) -> None:
        path = exe.with_name(STATE_FILENAME)
        if state is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, (json.dumps(state.to_dict(), indent=2) + "\n").encode())

    @staticmethod
    def _journal(
        exe: Path, action: str, before: RendererState | None, transition: RendererState
    ) -> None:
        atomic_write(
            exe.with_name(JOURNAL_FILENAME),
            json.dumps(
                {
                    "action": action,
                    "before": before.to_dict() if before else None,
                    "transition": transition.to_dict(),
                }
            ).encode(),
        )
