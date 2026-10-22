"""Crash-recoverable installation of the renderer, patches, textures and videos."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Self

import gk3hd.textures.install.service as texture_install
from gk3hd.patch.manifest import PatchManifest, manifest_path_for_exe
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
from gk3hd.videos.pack import prefetch as prefetch_videos

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
        # Published pre-video installers recorded three booleans. They never
        # owned videos, so their recovery must leave any video installation alone.
        if isinstance(payload, dict) and payload.get("schema_version") == 1:
            names = ("renderer", "patch", "textures")
            if all(isinstance(payload.get(f"{name}_existed"), bool) for name in names):
                return cls(
                    root,
                    frozenset({"videos", *(name for name in names if payload[f"{name}_existed"])}),
                )
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
    patch_request = _select_patches(patch_request, target.exe)
    texture_request = replace(texture_request, game_dir=None, exe=target.exe)
    video_request = video_request or PackRequest(
        cache=texture_request.cache_dir, offline=texture_request.offline
    )
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
    changed = existing != _COMPONENTS

    def video_progress(name: str, completed: int, total: int) -> None:
        report_install_progress(progress, name, completed, total, unit="bytes")

    # Resolve all required downloads and compile the patch plan before changing
    # installed components. Each replacement has its own recovery boundary;
    # already completed updates survive later failures and are reused on retry.
    renderer = RendererService()
    renderer_dll = _prefetch(patch_request, texture_request, video_request, progress=progress)
    renderer_path = target.game_dir / RENDERER_STATE_FILENAME
    renderer_before = renderer_path.read_bytes() if renderer_path.is_file() else None
    journal.write()

    try:
        report_install_progress(progress, "Installing renderer", 0, 1)
        renderer.install(exe=target.exe, dll=renderer_dll)
        changed |= renderer_before != renderer_path.read_bytes()
        report_install_progress(progress, "Installing renderer", 1, 1)
        report_install_progress(progress, "Verifying renderer", 0, 1)
        RendererService().verify(exe=target.exe)
        report_install_progress(progress, "Verifying renderer", 1, 1)
        report_install_progress(progress, "Installing patches", 0, 1)
        patch_update = patch_service.install(patch_request)
        changed |= patch_update.changed
        report_install_progress(progress, "Installing patches", 1, 1)
        texture_update = texture_install.install(texture_request, progress=progress)
        changed |= texture_update.changed
        video_update = install_pack(target.game_dir, video_request, progress=video_progress)
        changed |= video_update.changed
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


def _select_patches(request: PatchRequest, exe: Path) -> PatchRequest:
    """Keep a custom selection unless the caller explicitly chooses a group."""
    request = replace(request, game_dir=None, exe=exe)
    if request.group is not None or request.patches:
        return request
    path = manifest_path_for_exe(exe)
    previous = PatchManifest.from_path(path) if path.is_file() else None
    return replace(
        request,
        group=previous.profile if previous else "recommended",
        patches=previous.patches if previous and previous.profile is None else (),
    )


def _prefetch(
    patch: PatchRequest,
    textures: TextureInstallRequest,
    videos: PackRequest,
    *,
    progress: TextureInstallProgressCallback | None,
) -> Path:
    """Fail on unavailable assets or an invalid plan before touching installed files."""
    target = discover_game(game_dir=patch.game_dir, exe=patch.exe)
    PatchService().prepare(patch)
    renderer = RendererService().prefetch(
        exe=target.exe,
        offline=textures.offline,
        progress=lambda completed, total: report_install_progress(
            progress, "Downloading renderer", completed, total, unit="bytes"
        ),
    )
    texture_install.prefetch(textures, progress=progress)
    prefetch_videos(
        target.game_dir,
        videos,
        progress=lambda name, completed, total: report_install_progress(
            progress, name, completed, total, unit="bytes"
        ),
    )
    return renderer


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
