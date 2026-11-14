"""Compile and package a private standalone player without altering flat play."""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.runtime2d.layout import (
    CONSOLE_OWNER_OFFSET,
    CONSOLE_SEGMENT,
    RuntimeImage,
)
from gk3hd.patch.model import ProfileId
from gk3hd.renderer.distribution import config_bytes
from gk3hd.system.discovery import discover_game
from gk3hd.system.files import json_bytes, sha256_file
from gk3hd.vr import GAME_UNITS_PER_METER, items
from gk3hd.vr.android.notices import COMPONENT_LICENSES
from gk3hd.vr.artifact import RECIPE, VRRendererAsset, inspect_vr_dll
from gk3hd.vr.compiler import VRProgram, compile_standalone_vr, verify_standalone_vr
from gk3hd.vr.game import DEFAULT_PROFILE, original_source, prepare_base_game
from gk3hd.vr.standalone.assets import texture_inputs, video_inputs
from gk3hd.vr.standalone.build import inspect_components
from gk3hd.vr.standalone.bundle import BundleReceipt, build_bundle
from gk3hd.vr.standalone.paths import BUNDLE_FILENAME, recorded_build, workspace

if TYPE_CHECKING:
    from collections.abc import Callable

    from gk3hd.patch.builds import BuildProfile
    from gk3hd.system.discovery import GameTarget

_X86 = 0x14C
_DLL = 0x2000
_MAX_COMPONENT = 8 * 1024**2
_MAX_EXPORTS = 4096
_EXPORT_NAME_BYTES = 256


class GraphicsBackend(StrEnum):
    """Standalone driver/presentation routes, independent of the VR renderer."""

    NATIVE_VULKAN = "native-vulkan"
    TURNIP = "turnip"


@dataclass(frozen=True, slots=True)
class PreparationOptions:
    """Private-player feature choices, separate from filesystem/progress inputs."""

    profile: ProfileId = DEFAULT_PROFILE
    textures: bool = True
    videos: bool = True
    backend: GraphicsBackend = GraphicsBackend.TURNIP


def _standalone_cpu_source(source: PEFile, profile: BuildProfile) -> PEFile:
    """Avoid translated rounding-mode switches in the standalone x86 guest.

    The standalone translator supports SSE3 FISTTP. It truncates directly,
    preserving the caller's rounding mode, x87 stack and EDX:EAX result.
    Keep the native waits and integer flag calculation. Only the temporary
    control-word store, two FLDCW instructions and FISTP change. The complete
    original routine is validated before writing to a clone; flat and PC-VR
    preparation do not use this path.
    """
    site = profile.site("engine.float_to_int64")
    plan = ExecutableMutationPlan(owner="standalone_float_conversion")
    plan.replace(
        label=site.symbol,
        va=site.va,
        expected=site.original,
        payload=bytes.fromhex(
            "55 8b ec 83 c4 f4 9b d9 7d fe 9b 66 8b 45 fe 80 cc 0c "
            "dd 4d f4 90 90 90 90 90 90 90 90 90 90 8b 45 f4 8b 55 f8 c9 c3"
        ),
    )
    image = source.clone()
    plan.apply(image)
    return image


def _has_runtime_export(image: PEFile, payload: bytes) -> bool:
    export_rva, size = struct.unpack("<II", image.read_bytes(image.optional_offset + 96, 8))
    if not export_rva or not size:
        return False
    table = image.rva_to_offset(export_rva)
    count = struct.unpack("<I", image.read_bytes(table + 24, 4))[0]
    names = struct.unpack("<I", image.read_bytes(table + 32, 4))[0]
    if count > _MAX_EXPORTS:
        return False
    for index in range(count):
        rva = struct.unpack("<I", image.read_bytes(image.rva_to_offset(names) + index * 4, 4))[0]
        offset = image.rva_to_offset(rva)
        end = payload.find(b"\0", offset, offset + _EXPORT_NAME_BYTES)
        if end != -1 and payload[offset:end] == b"xrNegotiateLoaderRuntimeInterface":
            return True
    return False


def _component(path: Path, *, dll: bool, runtime: bool = False) -> bytes:
    if not path.is_file() or not 0 < path.stat().st_size <= _MAX_COMPONENT:
        msg = f"Missing or oversized standalone component: {path.name}"
        raise ValueError(msg)
    with path.open("rb") as stream:
        payload = stream.read(_MAX_COMPONENT + 1)
    if not payload or len(payload) > _MAX_COMPONENT:
        msg = f"Standalone component changed or exceeds its size bound: {path.name}"
        raise ValueError(msg)
    image = PEFile(payload)
    characteristics = struct.unpack("<H", image.read_bytes(image.coff_offset + 18, 2))[0]
    if image.machine != _X86 or bool(characteristics & _DLL) != dll:
        msg = f"Standalone component has the wrong x86 executable/DLL type: {path.name}"
        raise ValueError(msg)
    if runtime and not _has_runtime_export(image, payload):
        msg = (
            "The supplied runtime is not an OpenXR runtime DLL; never install a Vulkan import stub"
        )
        raise ValueError(msg)
    return payload


def _player_metadata(
    program: VRProgram,
    *,
    renderer: VRRendererAsset,
    original: str,
    build: str,
    options: PreparationOptions,
) -> bytes:
    return (
        json.dumps(
            {
                "schema": 1,
                "kind": "standalone-development",
                "graphics_backend": GraphicsBackend(options.backend).value,
                "game_build": build,
                "game_source_sha256": original,
                "profile": str(options.profile),
                "quality": (
                    "recommended"
                    if options.textures and options.videos and options.profile == "recommended"
                    else "diagnostic"
                ),
                "features": {"hd_textures": options.textures, "hd_videos": options.videos},
                "units_per_meter": GAME_UNITS_PER_METER,
                "renderer": {"version": renderer.version, "sha256": renderer.dll_sha256},
                "output_contract": "stereo-only",
                "launch_switches": list(program.stereo_only_switches),
                "support_validation": "Developer x86 components; not release qualification",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()


def _diagnostics(program: VRProgram, renderer_global: int, *, profile: BuildProfile) -> bytes:
    console = RuntimeImage(program.image).get_section(CONSOLE_SEGMENT.logical_name)
    if console is None:
        msg = "Standalone observation requires the compiled console owner"
        raise ValueError(msg)
    console_scope = program.image.rva_to_va(console.virtual_address) + CONSOLE_OWNER_OFFSET
    points = (
        ("scene_result", program.scene.result_va, 1),
        ("scene_frames", program.scene.submitted_frames_va, 1),
        ("scene_eyes", program.scene.eye_draws_va, 1),
        ("panel_frame", program.panel.frame_va, 47),
        ("last_blt", TransitionFrameCompiler.runtime_abi(program.image).last_blt_state_va, 4),
        ("scene_pending", program.scene.frame_pending_va, 1),
        ("ownership", program.ownership.mode_va, 1),
        ("navigation_moves", program.navigation.movement_count_va, 1),
        ("navigation_turns", program.navigation.turn_count_va, 1),
        ("audio_counts", program.audio.applied_va, 2),
        ("audio_pose", program.audio.pose_va, 12),
    )
    text = "".join(f"{name} {address:x} {words}\n" for name, address, words in points)
    return (
        text
        + f"native_camera_pos {renderer_global:x} 3 1c8 1c\n"
        + f"test_engine_global {profile.address('engine.loop'):x} 1\n"
        + f"test_location_names {profile.address('scene.location_names'):x} 1\n"
        + f"test_time_names {profile.address('scene.timeblock_names'):x} 1\n"
        + f"test_time_type {profile.address('scene.timeblock_vtable'):x} 1\n"
        + f"test_console_scope {console_scope:x} 1\n"
        + f"test_console_type {profile.address('console.vtable'):x} 1\n"
        + f"test_text_state {program.text.focus_va:x} 1\n"
        + f"test_camera_type {profile.address('vr.camera_manager_vtable'):x} 1\n"
        + f"test_save_type {profile.address('savegame.vtable'):x} 1\n"
        + f"test_restore_type {profile.address('restoregame.vtable'):x} 1\n"
        + f"test_panel_state {program.panel.enabled_va:x} 18\n"
        + f"test_input_state {program.inputs.enabled_va:x} 34\n"
    ).encode("ascii")


def _generated_files(
    program: VRProgram,
    renderer: VRRendererAsset,
    *,
    metadata: bytes,
    diagnostics: bytes,
) -> dict[str, bytes]:
    return {
        "GK3-VR.exe": program.image.to_bytes(),
        "ddraw.dll": renderer.path.read_bytes(),
        "renderer-provenance.json": renderer.path.with_suffix(".json").read_bytes(),
        "renderer-notices.txt": renderer.path.with_suffix(".txt").read_bytes(),
        "gk3hd-player.json": metadata,
        "dxvk.conf": config_bytes(executable_name="GK3-VR.exe"),
        # WXR's default Index ranking maps Menu to the left face button, but
        # our canonical wire layout carries that button and Menu separately.
        "conf.txt": b"controller_profile=/oculus/touch_controller\n",
        "openxr.json": json.dumps(
            {
                "file_format_version": "1.0.0",
                "runtime": {
                    "library_path": "C:\\gk3hd-vr\\openxr_wxr32.dll",
                },
            }
        ).encode(),
        "launch-switches.txt": (
            f"{len(program.stereo_only_switches)}\n"
            + "".join(f"{va:x}\n" for va in program.stereo_only_switches)
        ).encode("ascii"),
        "desktop-input-switch.txt": f"{program.inputs.enabled_va:x}\n".encode("ascii"),
        "diagnostic-points.txt": diagnostics,
    }


def _support_files(components: Path, frozen: dict[str, bytes]) -> dict[str, bytes]:
    """Carry optional current-build provenance, never downgrade a stale record."""
    if not (components / "standalone-components.json").exists():
        return {}
    record = inspect_components(components)
    files = {"support-provenance.json": record.read_bytes()}
    recorded_outputs = json.loads(files["support-provenance.json"])["outputs"]
    for name, payload in frozen.items():
        if hashlib.sha256(payload).hexdigest() != recorded_outputs[name]:
            msg = "Standalone component changed while freezing its prepared payload"
            raise ValueError(msg)
    for name in COMPONENT_LICENSES:
        notice = components / name
        if not notice.is_file() or notice.stat().st_size > 128 * 1024:
            msg = f"Missing or oversized standalone build notice: {name}"
            raise ValueError(msg)
        files[name] = notice.read_bytes()
    return files


def _game_data(directory: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in sorted(directory.iterdir()):
        if path.suffix.casefold() in {".brn", ".bik", ".avi"}:
            if path.is_symlink():
                msg = f"Linked game data cannot be packed for standalone VR: {path.name}"
                raise ValueError(msg)
            if path.is_file():
                files[f"Data/{path.name}"] = path
    return files


@dataclass(frozen=True, slots=True)
class PlayerPayload:
    """Frozen generated files and identities of the original and HD resources."""

    generated: dict[str, bytes]
    files: dict[str, Path]
    hashes: dict[str, str]
    verify_unchanged: Callable[[], None]

    @property
    def identity(self) -> str:
        """Identify the files players receive independently of the CLI version."""
        identities = self.hashes | {
            name: hashlib.sha256(content).hexdigest() for name, content in self.generated.items()
        }
        return hashlib.sha256(json_bytes(identities)).hexdigest()

    def write(
        self, output: Path, *, progress: Callable[[int, int], None] | None = None
    ) -> BundleReceipt:
        """Archive and verify the exact files used to decide bundle reuse."""
        output.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".gk3hd-player-", dir=output.parent) as directory:
            files = dict(self.files)
            for name, payload in self.generated.items():
                path = Path(directory) / name
                path.write_bytes(payload)
                files[name] = path
            return build_bundle(
                files,
                output,
                progress=progress,
                before_publish=self.verify_unchanged,
                expected_sha256=self.hashes,
            )


def pack(
    *,
    game_dir: Path | None = None,
    build_dir: Path | None = None,
    output: Path | None = None,
    options: PreparationOptions | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> BundleReceipt:
    """Rebuild a dormant player and bundle original data with explicit components.

    Renderer provenance/native/GPU tests are mandatory. The caller's local
    runtime and helper are structurally checked, not described as qualified
    release binaries. Default bundles retain all movies and include the verified
    HD texture/video packs. Reduced controls require explicit developer options.
    """
    options = options or PreparationOptions()
    GraphicsBackend(options.backend)  # Validate before discovering or reading game files.
    if options.profile not in {ProfileId("recommended"), ProfileId("testing")}:
        msg = "Standalone preparation requires recommended or explicit testing patches"
        raise ValueError(msg)
    game = discover_game(game_dir=game_dir)
    directory = workspace(game.game_dir)
    components = (build_dir or recorded_build(directory)).resolve()
    destination = (output or directory / BUNDLE_FILENAME).resolve()
    if destination.exists():
        msg = "Standalone output already exists; choose a new --output path"
        raise FileExistsError(msg)
    return prepare_payload(game, components, options).write(destination, progress=on_progress)


def prepare_payload(
    game: GameTarget, components: Path, options: PreparationOptions
) -> PlayerPayload:
    """Resolve the current private player without writing the large archive."""
    data = _game_data(game.data_dir)
    data_hashes = {name: sha256_file(path) for name, path in data.items()}
    pin = json.loads((RECIPE / "upstream.json").read_text(encoding="utf-8"))
    renderer = inspect_vr_dll(components / f"dxvk-sarek-{pin['version']}-xr-prototype.dll")
    runtime = _component(components / "openxr_wxr32.dll", dll=True, runtime=True)
    helper = _component(components / "gk3hd-wine-launcher.exe", dll=False)
    support = _support_files(
        components, {"openxr_wxr32.dll": runtime, "gk3hd-wine-launcher.exe": helper}
    )
    bink = _component(game.game_dir / "binkw32.dll", dll=True)
    textures = texture_inputs(game.game_dir, enabled=options.textures)
    videos = video_inputs(game.game_dir, enabled=options.videos)
    source = original_source(game.exe)
    raw = source.read_bytes()
    original = hashlib.sha256(raw).hexdigest()
    flat, profile = prepare_base_game(raw, profile_id=options.profile)
    flat = _standalone_cpu_source(flat, profile)
    program = compile_standalone_vr(
        flat,
        profile=profile,
        units_per_meter=GAME_UNITS_PER_METER,
        item_visuals=items.load_catalog(game.data_dir),
    )
    verify_standalone_vr(
        flat,
        program.image,
        profile=profile,
        units_per_meter=GAME_UNITS_PER_METER,
    )
    generated = _generated_files(
        program,
        renderer,
        metadata=_player_metadata(
            program,
            renderer=renderer,
            original=original,
            build=str(profile.id),
            options=options,
        ),
        diagnostics=_diagnostics(program, profile.address("vr.renderer_global"), profile=profile),
    )
    generated.update(
        {
            "openxr_wxr32.dll": runtime,
            "gk3hd-wine-launcher.exe": helper,
            "binkw32.dll": bink,
            "GK3.ini": textures.ini,
            "gk3hd-textures.json": textures.metadata,
            "gk3hd-videos.json": videos.metadata,
        }
    )
    generated.update(support)

    def unchanged() -> None:
        renderer.verify_unchanged()
        textures.verify_unchanged()
        videos.verify_unchanged()
        if support:
            record = inspect_components(components)
            if record.read_bytes() != support["support-provenance.json"]:
                msg = "Standalone build record changed during preparation"
                raise ValueError(msg)
        if sha256_file(source) != original:
            msg = "The original executable changed during preparation; no bundle was published"
            raise ValueError(msg)
        if _game_data(game.data_dir) != data or any(
            sha256_file(path) != data_hashes[name] for name, path in data.items()
        ):
            msg = "Game data changed during standalone preparation. Run the same command again."
            raise ValueError(msg)

    return PlayerPayload(
        generated,
        data | textures.files | videos.files,
        data_hashes | textures.hashes | videos.hashes,
        unchanged,
    )
