"""Crash-recoverable composition of patches, renderer and texture services."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

import gk3hd.textures.install.service as texture_install
from gk3hd.patch.service import PatchRequest, PatchService
from gk3hd.renderer.service import RendererService
from gk3hd.renderer.state import STATE_FILENAME as RENDERER_STATE_FILENAME
from gk3hd.system.discovery import discover_game
from gk3hd.system.files import atomic_write
from gk3hd.textures.install.service import STATE_FILENAME, TextureInstallRequest

if TYPE_CHECKING:
    from pathlib import Path

    from gk3hd.textures.progress import TextureInstallProgressCallback

COMPOSITE_JOURNAL_FILENAME = ".gk3hd-install.json"
_SCHEMA = 1


class CompositeInstallError(RuntimeError):
    """Report an unsafe interrupted or composed installation."""


@dataclass(frozen=True, slots=True)
class CompositeReport:
    """Verified component counts for a complete installation."""

    patches: int
    textures: int
    changed: bool


@dataclass(frozen=True, slots=True)
class _CompositeJournal:
    """Record which component states predated a composed invocation."""

    game_dir: Path
    patch_existed: bool
    textures_existed: bool
    renderer_existed: bool

    @property
    def path(self) -> Path:
        return self.game_dir / COMPOSITE_JOURNAL_FILENAME

    def write(self) -> None:
        payload = {
            "patch_existed": self.patch_existed,
            "schema_version": _SCHEMA,
            "textures_existed": self.textures_existed,
            "renderer_existed": self.renderer_existed,
        }
        atomic_write(
            self.path,
            (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(),
        )

    @classmethod
    def load(cls, game_dir: Path) -> Self:
        root = game_dir.resolve()
        path = root / COMPOSITE_JOURNAL_FILENAME
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            msg = f"cannot read composite recovery journal {path.name}: {exc}"
            raise CompositeInstallError(msg) from exc
        valid = (
            isinstance(payload, dict)
            and payload.get("schema_version") == _SCHEMA
            and isinstance(payload.get("patch_existed"), bool)
            and isinstance(payload.get("textures_existed"), bool)
            and isinstance(payload.get("renderer_existed"), bool)
        )
        if not valid:
            msg = f"composite recovery journal {path.name} is malformed"
            raise CompositeInstallError(msg)
        return cls(
            root, payload["patch_existed"], payload["textures_existed"], payload["renderer_existed"]
        )


def install(
    patch_request: PatchRequest,
    texture_request: TextureInstallRequest,
    *,
    progress: TextureInstallProgressCallback | None = None,
) -> CompositeReport:
    """Bring all three components to verified installed state as one operation."""
    target = discover_game(game_dir=patch_request.game_dir, exe=patch_request.exe)
    recover(exe=target.exe)
    patch_service = PatchService()
    patch_existed = patch_service.status(exe=target.exe).installed
    textures_existed = (target.game_dir / STATE_FILENAME).is_file()
    renderer_existed = (target.game_dir / RENDERER_STATE_FILENAME).is_file()
    journal = _CompositeJournal(target.game_dir, patch_existed, textures_existed, renderer_existed)
    journal.write()
    changed = not patch_existed or not textures_existed or not renderer_existed
    try:
        if not renderer_existed:
            RendererService().install(exe=target.exe)
        RendererService().verify(exe=target.exe)
        if not patch_existed:
            patch_service.install(
                PatchRequest(
                    exe=target.exe,
                    group=patch_request.group,
                    patches=patch_request.patches,
                    resolution=patch_request.resolution,
                    backend=patch_request.backend,
                )
            )
        if not textures_existed:
            texture_install.install(
                TextureInstallRequest(
                    exe=target.exe,
                    pack=texture_request.pack,
                    local=texture_request.local,
                    cache_dir=texture_request.cache_dir,
                    force=texture_request.force,
                    offline=texture_request.offline,
                ),
                progress=progress,
            )
        patch_report = patch_service.verify(exe=target.exe)
        texture_report = texture_install.verify(exe=target.exe)
        journal.path.unlink()
    except BaseException as error:
        try:
            _rollback(journal, exe=target.exe)
        except Exception as rollback_error:  # noqa: BLE001 - preserve primary failure.
            error.add_note(f"composite rollback also failed: {rollback_error}")
        raise
    return CompositeReport(len(patch_report.patches), texture_report.textures, changed)


def recover(*, game_dir: Path | None = None, exe: Path | None = None) -> bool:
    """Restore component states recorded before an interrupted composition."""
    target = discover_game(game_dir=game_dir, exe=exe)
    path = target.game_dir / COMPOSITE_JOURNAL_FILENAME
    if not path.is_file():
        RendererService().recover(exe=target.exe)
        PatchService().recover(exe=target.exe)
        texture_install.recover(exe=target.exe)
        return False
    journal = _CompositeJournal.load(target.game_dir)
    _rollback(journal, exe=target.exe)
    return True


def _rollback(journal: _CompositeJournal, *, exe: Path) -> None:
    """Remove only components newly introduced by this composition."""
    texture_install.recover(exe=exe)
    texture_state = journal.game_dir / STATE_FILENAME
    if not journal.textures_existed and texture_state.is_file():
        texture_install.uninstall(exe=exe)
    patch_service = PatchService()
    patch_service.recover(exe=exe)
    if not journal.patch_existed and patch_service.status(exe=exe).installed:
        patch_service.uninstall(exe=exe)
    renderer = RendererService()
    renderer.recover(exe=exe)
    if not journal.renderer_existed and (journal.game_dir / RENDERER_STATE_FILENAME).is_file():
        renderer.uninstall(exe=exe, restoring_composite=True)
    journal.path.unlink()
