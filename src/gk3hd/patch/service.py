"""Application-facing patch orchestration independent of Typer."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from gk3hd.patch.catalog import PATCHES, PLANNER, PROFILES
from gk3hd.patch.install.configuration import GraphicsBackend
from gk3hd.patch.install.transaction import Installer
from gk3hd.patch.manifest import PatchManifest, manifest_path_for_exe
from gk3hd.patch.model import PatchDefinition, PatchId, PatchProfile, ProfileId
from gk3hd.system.discovery import GameTarget, discover_game
from gk3hd.system.display import current_display_mode

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from gk3hd.patch.install.configuration import InstallConfiguration
    from gk3hd.patch.install.transaction import PreparedInstall, VerificationReport


@dataclass(frozen=True, slots=True)
class PatchStatus:
    """Fast patch-state summary that does not rebuild injected bytes."""

    target: GameTarget
    installed: bool


@dataclass(frozen=True, slots=True)
class PatchRequest:
    """Complete target and selection inputs for one patch plan."""

    game_dir: Path | None = None
    exe: Path | None = None
    group: str | None = "recommended"
    patches: tuple[str, ...] = ()
    resolution: tuple[int, int] | None = None
    backend: str = "auto"


class PatchService:
    """Prepare, install, verify, and uninstall executable patches."""

    def __init__(
        self,
        *,
        configuration: InstallConfiguration | None = None,
        process_probe: Callable[[], bool] | None = None,
    ) -> None:
        """Allow deterministic adapters in tests while defaulting to Windows state."""
        if process_probe is None:
            self._installer = Installer(configuration=configuration)
        else:
            self._installer = Installer(
                configuration=configuration,
                process_probe=process_probe,
            )

    @staticmethod
    def catalog() -> tuple[object, object]:
        """Return canonical profile and patch registries."""
        return PROFILES, PATCHES

    def prepare(self, request: PatchRequest) -> PreparedInstall:
        """Compile and verify a complete patch plan without mutating disk."""
        target = discover_game(game_dir=request.game_dir, exe=request.exe)
        if request.group is not None and request.patches:
            msg = "--group and --patch are mutually exclusive"
            raise ValueError(msg)
        if request.group is not None and ProfileId(request.group) not in PROFILES:
            msg = f"unknown patch group: {request.group}"
            raise ValueError(msg)
        selected = tuple(PatchId(value) for value in request.patches)
        unknown = [value for value in selected if value not in PATCHES]
        if unknown:
            msg = f"unknown patch: {unknown[0]}"
            raise ValueError(msg)
        previous_path = manifest_path_for_exe(target.exe)
        previous = PatchManifest.from_path(previous_path) if previous_path.is_file() else None
        if request.resolution is not None:
            width, height = request.resolution
        elif previous is not None:
            width, height = previous.width, previous.height
        else:
            display = current_display_mode()
            width, height = display.width, display.height
        prepared = self._installer.prepare(
            exe=target.exe,
            profile=None if request.group is None else ProfileId(request.group),
            patches=selected,
            width=width,
            height=height,
            graphics_backend=(
                GraphicsBackend.D7VK
                if request.backend == "auto"
                else GraphicsBackend(request.backend)
            ),
        )
        return replace(prepared, preserve_resolution=request.resolution is None)

    def install(self, request: PatchRequest) -> PreparedInstall:
        """Prepare then commit one patch installation."""
        prepared = self.prepare(request)
        self._installer.recover(exe=prepared.target)
        path = manifest_path_for_exe(prepared.target)
        before = path.read_bytes() if path.is_file() else None
        manifest = self._installer.apply(exe=prepared.target, prepared=prepared)
        return replace(prepared, changed=before != manifest.to_json().encode("utf-8"))

    def verify(
        self, *, game_dir: Path | None = None, exe: Path | None = None
    ) -> VerificationReport:
        """Verify the installed version without requiring the same compiler revision."""
        target = discover_game(game_dir=game_dir, exe=exe)
        return self._installer.verify(exe=target.exe)

    def recover(self, *, game_dir: Path | None = None, exe: Path | None = None) -> bool:
        """Recover an interrupted executable transaction when present."""
        target = discover_game(game_dir=game_dir, exe=exe)
        return self._installer.recover(exe=target.exe)

    def uninstall(
        self,
        *,
        game_dir: Path | None = None,
        exe: Path | None = None,
        force: bool = False,
    ) -> Path:
        """Restore the exact supported pristine executable and external state."""
        target = discover_game(game_dir=game_dir, exe=exe)
        return self._installer.restore(exe=target.exe, force=force)

    @staticmethod
    def status(*, game_dir: Path | None = None, exe: Path | None = None) -> PatchStatus:
        """Return whether current patch state exists for the resolved executable."""
        target = discover_game(game_dir=game_dir, exe=exe)
        return PatchStatus(target, manifest_path_for_exe(target.exe).is_file())

    @staticmethod
    def profiles() -> tuple[PatchProfile, ...]:
        """Return deterministic patch groups for display."""
        return PLANNER.profiles

    @staticmethod
    def profile_patch_ids(profile_id: ProfileId) -> tuple[PatchId, ...]:
        """Return the exact group membership, including automatic dependencies."""
        return PLANNER.profile_patch_ids(profile_id)

    @staticmethod
    def patches() -> tuple[PatchDefinition, ...]:
        """Return deterministic patch definitions for display."""
        return PLANNER.patches
