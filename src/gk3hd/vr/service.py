"""Install and remove an isolated VR player without changing ordinary GK3 play."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.install.windows import is_gk3_running
from gk3hd.patch.manifest import manifest_path_for_exe
from gk3hd.renderer.distribution import config_bytes
from gk3hd.system.discovery import discover_game
from gk3hd.system.files import sha256_file
from gk3hd.vr import GAME_UNITS_PER_METER, items
from gk3hd.vr.artifact import VRRendererAsset, inspect_installed_vr_dll, inspect_vr_dll
from gk3hd.vr.build import local_build
from gk3hd.vr.compiler import VRProgram, compile_vr, verify_vr
from gk3hd.vr.game import original_source, prepare_base_game
from gk3hd.vr.state import OWNED_FILES, VRState, validate_scale
from gk3hd.vr.transaction import FILES, PLAYER, STATE, VRTransaction

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


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


class VRService:
    """Own only an alternate executable, its private files and VR state."""

    def __init__(self, *, process_probe: Callable[[], bool] = is_gk3_running) -> None:
        """Inject process detection for deterministic non-game tests."""
        self._process_probe = process_probe

    def _transaction(self, exe: Path) -> VRTransaction:
        return VRTransaction(exe, process_probe=self._process_probe)

    @staticmethod
    def _ownership(
        exe: Path, snapshot: dict[str, str | None], *, allow_missing: bool = False
    ) -> VRState | None:
        if snapshot[STATE] is not None:
            state = VRState.read(exe.parent / STATE)
            state.require_owned(snapshot, allow_missing=allow_missing)
            return state
        if occupied := [name for name in OWNED_FILES if snapshot[name] is not None]:
            files = "\n".join(occupied)
            msg = f"Move these unmanaged VR files out of {exe.parent}, then retry.\n{files}"
            raise ValueError(msg)
        return None

    def prepare(
        self,
        *,
        game_dir: Path | None = None,
        dll: Path | None = None,
        units_per_meter: float | None = None,
    ) -> PreparedVR:
        """Compile a dormant alternate player and verify its private renderer."""
        target = discover_game(game_dir=game_dir)
        owner = self._transaction(target.exe)
        snapshot = owner.snapshot()
        existing = self._ownership(target.exe, snapshot, allow_missing=True)
        if units_per_meter is None:
            units_per_meter = existing.units_per_meter if existing else GAME_UNITS_PER_METER
        # Validate calibration before compiling or inspecting expensive assets.
        validate_scale(units_per_meter)
        source = original_source(target.exe)
        guard_paths = (target.exe, manifest_path_for_exe(target.exe), source)
        guards = tuple((path, _identity(path)) for path in dict.fromkeys(guard_paths))
        renderer = (
            inspect_vr_dll(dll.resolve()) if dll is not None else local_build(game_dir=game_dir)
        )
        raw = source.read_bytes()
        flat, profile = prepare_base_game(raw)
        program = compile_vr(
            flat,
            profile=profile,
            units_per_meter=units_per_meter,
            renderer_location="isolated",
            item_visuals=items.load_catalog(target.data_dir),
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
        units_per_meter: float | None = None,
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
            msg = "PC VR is not installed. Run gk3hd vr install, then open GK3HD VR again."
            raise ValueError(msg)
        player = target.game_dir / PLAYER
        try:
            inspect_installed_vr_dll(player / "ddraw.dll")
        except ValueError as error:
            msg = f"Run gk3hd vr install to update or repair the PC VR renderer.\n{error}"
            raise ValueError(msg) from error
        if (player / "dxvk.conf").read_bytes() != config_bytes(executable_name="GK3-VR.exe"):
            msg = "VR player renderer configuration differs from the supported policy"
            raise ValueError(msg)
        raw = (player / "original.exe").read_bytes()
        flat, profile = prepare_base_game(raw)
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
        if self._ownership(target.exe, snapshot, allow_missing=True) is None:
            return target.game_dir

        def validate() -> None:
            if any(owner.snapshot().values()):
                msg = "VR removal left owned files behind"
                raise ValueError(msg)

        owner.commit(dict.fromkeys(FILES), expected=snapshot, validate=validate)
        return target.game_dir
