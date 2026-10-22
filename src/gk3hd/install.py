"""Crash-recoverable installation of the renderer, patches, textures and videos."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Self

import gk3hd.textures.install.service as texture_install
from gk3hd.patch.service import PatchRequest, PatchService
from gk3hd.renderer.service import RendererService
from gk3hd.renderer.state import STATE_FILENAME as RENDERER_STATE_FILENAME
from gk3hd.system.discovery import discover_game
from gk3hd.system.files import atomic_write, json_bytes
from gk3hd.textures.install.service import STATE_FILENAME, TextureInstallRequest
from gk3hd.textures.progress import report_install_progress
from gk3hd.videos.install import MovieInstaller
from gk3hd.videos.manifest import STATE_FILENAME as VIDEO_STATE_FILENAME
from gk3hd.videos.pack import PackRequest, install_pack

if TYPE_CHECKING:
    from pathlib import Path

    from gk3hd.textures.progress import TextureInstallProgressCallback

COMPOSITE_JOURNAL_FILENAME = ".gk3hd-install.json"
_SCHEMA = 2
_COMPONENTS = frozenset({"renderer", "patch", "textures", "videos"})


class CompositeInstallError(RuntimeError):
    """Report an unsafe interrupted or composed installation."""


@dataclass(frozen=True, slots=True)
class CompositeReport:
    """Verified component counts for a complete installation."""

    patches: int
    textures: int
    videos: int
    changed: bool


@dataclass(frozen=True, slots=True)
class _CompositeJournal:
    """Record which component states predated a composed invocation."""

    game_dir: Path
    existing: frozenset[str]

    @property
    def path(self) -> Path:
        return self.game_dir / COMPOSITE_JOURNAL_FILENAME

    def write(self) -> None:
        atomic_write(
            self.path, json_bytes({"schema_version": _SCHEMA, "existing": sorted(self.existing)})
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
            and isinstance(payload.get("existing"), list)
            and all(isinstance(name, str) for name in payload["existing"])
            and set(payload["existing"]) <= _COMPONENTS
        )
        if not valid:
            msg = f"composite recovery journal {path.name} is malformed"
            raise CompositeInstallError(msg)
        return cls(root, frozenset(payload["existing"]))


def install(
    patch_request: PatchRequest,
    texture_request: TextureInstallRequest,
    *,
    video_request: PackRequest | None = None,
    progress: TextureInstallProgressCallback | None = None,
) -> CompositeReport:
    """Bring all four components to verified installed state as one operation."""
    target = discover_game(game_dir=patch_request.game_dir, exe=patch_request.exe)
    recover(exe=target.exe)
    patch_service = PatchService()
    existing = {
        name
        for name, filename in (
            ("textures", STATE_FILENAME),
            ("renderer", RENDERER_STATE_FILENAME),
            ("videos", VIDEO_STATE_FILENAME),
        )
        if (target.game_dir / filename).is_file()
    }
    if patch_service.status(exe=target.exe).installed:
        existing.add("patch")
    journal = _CompositeJournal(target.game_dir, frozenset(existing))
    journal.write()
    changed = existing != _COMPONENTS

    def renderer_progress(completed: int, total: int | None) -> None:
        report_install_progress(progress, "Downloading renderer", completed, total, unit="bytes")

    def video_progress(name: str, completed: int, total: int) -> None:
        report_install_progress(progress, name, completed, total, unit="bytes")

    try:
        if "renderer" not in existing:
            report_install_progress(progress, "Installing renderer", 0, 1)
            RendererService().install(exe=target.exe, progress=renderer_progress)
            report_install_progress(progress, "Installing renderer", 1, 1)
        report_install_progress(progress, "Verifying renderer", 0, 1)
        RendererService().verify(exe=target.exe)
        report_install_progress(progress, "Verifying renderer", 1, 1)
        if "patch" not in existing:
            report_install_progress(progress, "Installing patches", 0, 1)
            patch_service.install(replace(patch_request, game_dir=None, exe=target.exe))
            report_install_progress(progress, "Installing patches", 1, 1)
        if "textures" not in existing:
            texture_install.install(
                replace(texture_request, game_dir=None, exe=target.exe),
                progress=progress,
            )
        if "videos" not in existing:
            install_pack(
                target.game_dir,
                video_request
                or PackRequest(cache=texture_request.cache_dir, offline=texture_request.offline),
                progress=video_progress,
            )
        report_install_progress(progress, "Verifying patches", 0, 1)
        patch_report = patch_service.verify(exe=target.exe)
        report_install_progress(progress, "Verifying patches", 1, 1)
        report_install_progress(progress, "Verifying textures", 0, 1)
        texture_report = texture_install.verify(exe=target.exe)
        report_install_progress(progress, "Verifying textures", 1, 1)
        video_report = MovieInstaller.verify(target.game_dir, progress=video_progress)
        journal.path.unlink()
    except BaseException as error:
        try:
            _rollback(journal, exe=target.exe)
        except Exception as rollback_error:  # noqa: BLE001 - preserve primary failure.
            error.add_note(f"composite rollback also failed: {rollback_error}")
        raise
    return CompositeReport(
        len(patch_report.patches), texture_report.textures, video_report.videos, changed
    )


def recover(*, game_dir: Path | None = None, exe: Path | None = None) -> bool:
    """Restore component states recorded before an interrupted composition."""
    target = discover_game(game_dir=game_dir, exe=exe)
    path = target.game_dir / COMPOSITE_JOURNAL_FILENAME
    if not path.is_file():
        RendererService().recover(exe=target.exe)
        PatchService().recover(exe=target.exe)
        texture_install.recover(exe=target.exe)
        MovieInstaller().recover(target.game_dir)
        return False
    journal = _CompositeJournal.load(target.game_dir)
    _rollback(journal, exe=target.exe)
    return True


def _rollback(journal: _CompositeJournal, *, exe: Path) -> None:
    """Remove only components newly introduced by this composition."""
    videos = MovieInstaller()
    videos.recover(journal.game_dir)
    if "videos" not in journal.existing and (journal.game_dir / VIDEO_STATE_FILENAME).is_file():
        videos.uninstall(journal.game_dir)
    texture_install.recover(exe=exe)
    texture_state = journal.game_dir / STATE_FILENAME
    if "textures" not in journal.existing and texture_state.is_file():
        texture_install.uninstall(exe=exe)
    patch_service = PatchService()
    patch_service.recover(exe=exe)
    if "patch" not in journal.existing and patch_service.status(exe=exe).installed:
        patch_service.uninstall(exe=exe)
    renderer = RendererService()
    renderer.recover(exe=exe)
    if (
        "renderer" not in journal.existing
        and (journal.game_dir / RENDERER_STATE_FILENAME).is_file()
    ):
        renderer.uninstall(exe=exe, restoring_composite=True)
    journal.path.unlink()
