"""Install and remove an isolated VR player without changing ordinary GK3 play."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.binary.executor import OperationExecutor
from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.binary.normalize import normalize_source
from gk3hd.patch.builds import profile_for_sha256
from gk3hd.patch.catalog import PLANNER
from gk3hd.patch.install.windows import is_gk3_running
from gk3hd.patch.manifest import PatchManifest, manifest_path_for_exe
from gk3hd.patch.model import BuildContext, ProfileId
from gk3hd.renderer.distribution import config_bytes
from gk3hd.system.discovery import discover_game
from gk3hd.system.files import sha256_file
from gk3hd.vr import GAME_UNITS_PER_METER
from gk3hd.vr.artifact import VRRendererAsset, inspect_installed_vr_dll, inspect_vr_dll
from gk3hd.vr.build import local_build
from gk3hd.vr.compiler import VRProgram, compile_vr, verify_vr
from gk3hd.vr.state import OWNED_FILES, VRState, validate_scale
from gk3hd.vr.transaction import FILES, PLAYER, STATE, VRTransaction

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from gk3hd.patch.builds import BuildProfile


@dataclass(frozen=True, slots=True)
class PreparedVR:
    """Verified bytes and captured identities, with no published game changes."""

    target: Path
    renderer: VRRendererAsset
    files: tuple[tuple[str, bytes], ...]
    expected: tuple[tuple[str, str | None], ...]
    guards: tuple[tuple[Path, str | None], ...]


def _identity(path: Path) -> str | None:
    return sha256_file(path) if path.exists() else None


def _flat(raw: bytes) -> tuple[PEFile, BuildProfile]:
    """Build recommended flat dependencies from a supported pristine executable."""
    profile = profile_for_sha256(hashlib.sha256(raw).hexdigest())
    plan = PLANNER.plan_profile(ProfileId("recommended"), BuildContext(build_id=profile.id))
    flat = OperationExecutor().execute(PEFile(normalize_source(raw)), plan.compile_operations())
    return flat, profile


class VRService:
    """Own only an alternate executable, its private files and VR state."""

    def __init__(self, *, process_probe: Callable[[], bool] = is_gk3_running) -> None:
        """Inject process detection for deterministic non-game tests."""
        self._process_probe = process_probe

    def _transaction(self, exe: Path) -> VRTransaction:
        return VRTransaction(exe, process_probe=self._process_probe)

    @staticmethod
    def _source(exe: Path) -> Path:
        """Use a recognized original, never another mod's unknown executable."""
        manifest_path = manifest_path_for_exe(exe)
        if not manifest_path.exists():
            profile_for_sha256(sha256_file(exe))
            return exe
        manifest = PatchManifest.from_path(manifest_path)
        backup = exe.parent / manifest.backup_path
        digest = sha256_file(backup)
        profile = profile_for_sha256(digest)
        if digest != manifest.original_sha256 or profile.id != manifest.build_id:
            msg = "flat backup differs from its supported original; cannot prepare VR"
            raise ValueError(msg)
        return backup

    @staticmethod
    def _ownership(exe: Path, snapshot: dict[str, str | None]) -> VRState | None:
        if snapshot[STATE] is not None:
            state = VRState.read(exe.parent / STATE)
            state.require_owned(snapshot)
            return state
        if any(snapshot[name] is not None for name in OWNED_FILES):
            msg = "unmanaged files occupy the VR player location; preserve or move them first"
            raise ValueError(msg)
        return None

    def prepare(
        self,
        *,
        game_dir: Path | None = None,
        dll: Path | None = None,
        units_per_meter: float = GAME_UNITS_PER_METER,
    ) -> PreparedVR:
        """Compile a dormant alternate player and verify its private renderer."""
        target = discover_game(game_dir=game_dir)
        owner = self._transaction(target.exe)
        snapshot = owner.snapshot()
        self._ownership(target.exe, snapshot)
        # Validate calibration before compiling or inspecting expensive assets.
        validate_scale(units_per_meter)
        source = self._source(target.exe)
        guard_paths = (target.exe, manifest_path_for_exe(target.exe), source)
        guards = tuple((path, _identity(path)) for path in dict.fromkeys(guard_paths))
        renderer = (
            inspect_vr_dll(dll.resolve()) if dll is not None else local_build(game_dir=game_dir)
        )
        raw = source.read_bytes()
        flat, profile = _flat(raw)
        program = compile_vr(
            flat, profile=profile, units_per_meter=units_per_meter, renderer_location="isolated"
        )
        verify_vr(
            flat,
            program.image,
            profile=profile,
            units_per_meter=units_per_meter,
            renderer_location="isolated",
        )
        files = {
            "GK3-VR.exe": program.image.to_bytes(),
            f"{PLAYER}/original.exe": raw,
            f"{PLAYER}/ddraw.dll": renderer.path.read_bytes(),
            f"{PLAYER}/ddraw.json": renderer.path.with_suffix(".json").read_bytes(),
            f"{PLAYER}/ddraw.txt": renderer.path.with_suffix(".txt").read_bytes(),
            f"{PLAYER}/dxvk.conf": config_bytes(executable_name="GK3-VR.exe"),
        }
        state = VRState(
            units_per_meter,
            tuple((name, hashlib.sha256(payload).hexdigest()) for name, payload in files.items()),
        )
        files[STATE] = state.to_bytes()
        renderer.verify_unchanged()
        self._require_guards(guards)
        return PreparedVR(
            target.exe, renderer, tuple(files.items()), tuple(snapshot.items()), guards
        )

    @staticmethod
    def _require_guards(guards: tuple[tuple[Path, str | None], ...]) -> None:
        if any(_identity(path) != digest for path, digest in guards):
            msg = "flat installation changed during VR preparation; prepare again"
            raise ValueError(msg)

    def apply(self, prepared: PreparedVR) -> VRProgram:
        """Publish atomically recoverable files, then verify the actual disk player."""

        def preflight() -> None:
            prepared.renderer.verify_unchanged()
            self._require_guards(prepared.guards)

        result: list[VRProgram] = []
        self._transaction(prepared.target).commit(
            dict(prepared.files),
            expected=dict(prepared.expected),
            preflight=preflight,
            validate=lambda: result.append(self.verify(game_dir=prepared.target.parent)),
        )
        return result[0]

    def install(
        self,
        *,
        game_dir: Path | None = None,
        dll: Path | None = None,
        units_per_meter: float = GAME_UNITS_PER_METER,
    ) -> VRProgram:
        """Recover an interrupted operation, prepare and install an opt-in player."""
        target = discover_game(game_dir=game_dir)
        self._transaction(target.exe).recover()
        return self.apply(self.prepare(game_dir=game_dir, dll=dll, units_per_meter=units_per_meter))

    def verify(self, *, game_dir: Path | None = None) -> VRProgram:
        """Rebuild every player byte and recheck installed renderer provenance."""
        target = discover_game(game_dir=game_dir)
        snapshot = self._transaction(target.exe).snapshot()
        state = self._ownership(target.exe, snapshot)
        if state is None:
            msg = "no managed VR player is installed"
            raise ValueError(msg)
        player = target.game_dir / PLAYER
        inspect_installed_vr_dll(player / "ddraw.dll")
        if (player / "dxvk.conf").read_bytes() != config_bytes(executable_name="GK3-VR.exe"):
            msg = "VR player renderer configuration differs from the supported policy"
            raise ValueError(msg)
        raw = (player / "original.exe").read_bytes()
        flat, profile = _flat(raw)
        return verify_vr(
            flat,
            PEFile.from_path(target.game_dir / "GK3-VR.exe"),
            profile=profile,
            units_per_meter=state.units_per_meter,
            renderer_location="isolated",
        )

    def uninstall(self, *, game_dir: Path | None = None) -> Path:
        """Remove only verified VR-owned files, leaving flat play and saves alone."""
        target = discover_game(game_dir=game_dir)
        owner = self._transaction(target.exe)
        owner.recover()
        snapshot = owner.snapshot()
        if self._ownership(target.exe, snapshot) is None:
            return target.game_dir

        def validate() -> None:
            if any(owner.snapshot().values()):
                msg = "VR removal left owned files behind"
                raise ValueError(msg)

        owner.commit(dict.fromkeys(FILES), expected=snapshot, validate=validate)
        return target.game_dir
