"""Capture curated console scenarios from one reproducible, generated save."""

from __future__ import annotations

import hashlib
import json
import time
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.progress import Progress

from gk3hd.system.discovery import discover_game
from gk3hd.system.files import atomic_write
from tests.visual.support.catalog import Scene, SuiteSize, resolve_cameras, scenes
from tests.visual.support.matrix import (
    _ROOM_LAYER_VTABLE,
    _STARTUP_SPLASH_LAYER_VTABLE,
    _TIMEBLOCK_LAYER_VTABLE,
    _capture_is_valid,
    _CaptureContext,
    _grab_frame,
    _isolated_save,
    _launch_restored_save,
    _parse_resolution,
    _reference_capture_context,
    _restore_ini,
    _restore_resolution,
    _set_resolution,
    _snapshot_resolution,
    _temporary_reference_quality,
    _without_custom_paths,
)
from tests.visual.support.render import write_comparisons
from tests.visual.support.runs import comparison_run
from tests.visual.support.saves import SaveGame
from tests.visual.support.special import (
    _dismiss_restored_console,
    _ensure_interaction_fixture,
    _run_console_command,
)
from tests.visual.support.windows import (
    CaptureError,
    FrameGrabber,
    capture_session,
    current_cursor_resource,
    current_scene_identity,
    current_ui_layer_vtable,
    make_dpi_aware,
    press_key,
    stop,
)

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable, Mapping

    from PIL.Image import Image


def capture(
    *,
    game_dir: Path | None,
    size: SuiteSize,
    resolution: str,
    resume: Path | None,
    selected: tuple[Scene, ...] | None = None,
) -> None:
    """Run independent camera recipes; save all artifacts under repo build/visual."""
    target = discover_game(game_dir=game_dir)
    selected = (
        tuple(scene for scene in scenes(size) if scene.kind != "special")
        if selected is None
        else selected
    )
    cameras = resolve_cameras(target.data_dir, selected)
    dimensions = _parse_resolution(resolution)
    run = comparison_run(resume=resume)
    run.mkdir(parents=True, exist_ok=resume is not None)
    ini = target.ini or target.game_dir / "GK3.ini"
    original_ini = ini.read_bytes() if ini.is_file() else None
    assets = _capture_asset_hashes(target.game_dir, original_ini)
    registry = _snapshot_resolution()
    make_dpi_aware()
    with capture_session(target.exe), _temporary_reference_quality():
        try:
            with _reference_capture_context(target.exe) as reference:
                context = _CaptureContext(
                    reference,
                    target.game_dir,
                    ini,
                    use_wgc=False,
                    ini_bytes=_without_custom_paths(original_ini),
                )
                _set_resolution((1024, 768))
                _restore_ini(ini, context.ini_bytes)
                fixture = _ensure_interaction_fixture(context, size=(1024, 768))
                fingerprint = {
                    "capture_protocol": 2,
                    "fixture_sha256": hashlib.sha256(fixture.path.read_bytes()).hexdigest(),
                    "current_exe_sha256": hashlib.sha256(target.exe.read_bytes()).hexdigest(),
                    "current_resolution": dimensions,
                    "cameras": cameras,
                    "assets": assets,
                }
                encoded = (json.dumps(fingerprint, sort_keys=True, indent=2) + "\n").encode()
                identity = run / "scenarios.json"
                if identity.is_file() and not _compatible_inputs(
                    json.loads(identity.read_bytes()), fingerprint
                ):
                    msg = "scenario inputs changed; start a new comparison run"
                    raise ValueError(msg)
                atomic_write(identity, encoded)
                with Progress() as progress:
                    task = progress.add_task("Reference scenarios", total=len(selected))
                    references = _capture_scenes(
                        context,
                        fixture,
                        selected,
                        cameras,
                        output=run / "reference-1024x768",
                        size=(1024, 768),
                        advance=lambda: progress.advance(task),
                    )
            current_context = _CaptureContext(
                target.exe, target.game_dir, ini, use_wgc=False, ini_bytes=original_ini
            )
            with Progress() as progress:
                task = progress.add_task("Upscaled scenarios", total=len(selected))
                current = _capture_scenes(
                    current_context,
                    fixture,
                    selected,
                    cameras,
                    output=run / f"current-{dimensions[0]}x{dimensions[1]}",
                    size=dimensions,
                    advance=lambda: progress.advance(task),
                )
        finally:
            _restore_ini(ini, original_ini)
            _restore_resolution(registry)
    captures = tuple(
        (
            SaveGame(Path(scene.name + ".gk3"), scene.description, scene.room, scene.timeblock),
            references[scene.name],
            current[scene.name],
        )
        for scene in selected
    )
    sheet, _animations = write_comparisons(captures, output=run / "comparisons")
    Console().print(f"{len(selected)} paired scenes: {sheet.parent}")


def _compatible_inputs(previous: object, requested: Mapping[str, object]) -> bool:
    """Permit nested suite expansion, but never reuse a changed camera recipe."""
    if not isinstance(previous, dict):
        return False
    old_cameras, new_cameras = previous.get("cameras"), requested.get("cameras")
    if not isinstance(old_cameras, dict) or not isinstance(new_cameras, dict):
        return False
    old_inputs = {key: value for key, value in previous.items() if key != "cameras"}
    new_inputs = {key: value for key, value in requested.items() if key != "cameras"}
    # JSON serializes tuple dimensions as lists; compare their serialized values.
    return json.dumps(old_inputs, sort_keys=True) == json.dumps(new_inputs, sort_keys=True) and all(
        new_cameras.get(name) == command for name, command in old_cameras.items()
    )


def _capture_asset_hashes(game_dir: Path, ini: bytes | None) -> dict[str, str | None]:
    """Bind resume to renderer settings, texture ownership and the reference EXE."""
    result = {"ini": hashlib.sha256(ini).hexdigest() if ini is not None else None}
    for name in ("ddraw.dll", "dxvk.conf", ".gk3hd-textures.json", "GK3.exe.bak"):
        path = game_dir / name
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return result


def _capture_scenes(  # noqa: PLR0913 - Explicit capture inputs shared by both quality modes.
    context: _CaptureContext,
    fixture: SaveGame,
    selected: tuple[Scene, ...],
    cameras: dict[str, str],
    *,
    output: Path,
    size: tuple[int, int],
    advance: Callable[[], None],
) -> dict[str, Path]:
    output.mkdir(parents=True, exist_ok=True)
    _set_resolution(size)
    _restore_ini(context.ini_path, context.ini_bytes)
    paths = {}
    with _isolated_save(context.game_dir, fixture.path):
        for scene in selected:
            destination = output / f"{scene.name}.png"
            if not _capture_is_valid(destination, size) or not _scene_capture_visible(destination):
                _capture_scene(context, scene, cameras[scene.name], destination, size)
            paths[scene.name] = destination
            advance()
    return paths


def _capture_scene(
    context: _CaptureContext,
    scene: Scene,
    camera: str,
    destination: Path,
    size: tuple[int, int],
) -> None:
    """Start from the same save each time, never a prior scenario's puzzle state."""
    process, window, grabber = _launch_restored_save(
        context=context, size=size, failure_output=destination
    )
    try:
        _dismiss_restored_console(window, grabber, size=size)
        _run_console_command(window, f'SetLocationTime("{scene.room}","{scene.timeblock}");')
        deadline = time.monotonic() + 12
        next_skip = 0.0
        while (
            current_scene_identity(process.pid) != (scene.room.lower(), scene.timeblock)
            or current_ui_layer_vtable(process.pid) != _ROOM_LAYER_VTABLE
        ):
            if process.poll() is not None or time.monotonic() > deadline:
                grabber.grab(width=size[0], height=size[1]).save(
                    destination.with_name(destination.stem + "-failure.png")
                )
                actual = current_scene_identity(process.pid)
                msg = f"scene transition failed: {scene.name}; actual={actual}"
                raise CaptureError(msg)  # noqa: TRY301 - Save diagnostic state before cleanup.
            layer = current_ui_layer_vtable(process.pid)
            if (
                layer
                in {None, _ROOM_LAYER_VTABLE, _TIMEBLOCK_LAYER_VTABLE, _STARTUP_SPLASH_LAYER_VTABLE}
                and time.monotonic() >= next_skip
            ):
                # Full-motion chapter introductions can precede the time card.
                press_key(window, 0x1B, hold_seconds=0.03)
                next_skip = time.monotonic() + 0.25
            time.sleep(0.02)
        # Time changes can start an intro after activating the Room layer; that
        # script owns input and can leave the camera behind its black fade.
        press_key(window, 0x1B, hold_seconds=0.06)
        window, grabber = _wait_for_visible_room(process, window, grabber, size)
        if scene.setup:
            _run_console_command(window, scene.setup)
            window, grabber = _wait_for_visible_room(process, window, grabber, size)
        camera = camera.removeprefix(scene.setup)
        _run_console_command(window, camera)
        # Rebind after scene/console transitions, then discard in-flight frames.
        grabber.close()
        grabber = FrameGrabber(window, wgc=context.use_wgc)
        deadline = time.monotonic() + 5
        for _ in range(3):
            window, grabber, frame = _grab_frame(process, window=window, grabber=grabber, size=size)
        while not _room_ready(process.pid, frame):
            if time.monotonic() > deadline:
                msg = f"scene remained black after loading: {scene.name}"
                raise CaptureError(msg)  # noqa: TRY301 - Save diagnostic state before cleanup.
            press_key(window, 0x1B, hold_seconds=0.03)
            window, grabber = _wait_for_visible_room(process, window, grabber, size)
            _run_console_command(window, camera)
            window, grabber, frame = _grab_frame(process, window=window, grabber=grabber, size=size)
        frame.save(destination, format="PNG", compress_level=1)
        atomic_write(
            destination.with_suffix(".json"),
            json.dumps(
                {
                    "scene": scene.name,
                    "actual": current_scene_identity(process.pid),
                    "camera_command": camera,
                    "setup_command": scene.setup,
                    "cursor": current_cursor_resource(process.pid),
                },
                indent=2,
            ).encode(),
        )
    except CaptureError as error:
        failure = destination.with_name(destination.stem + "-failure")
        with suppress(CaptureError, OSError):
            grabber.grab(width=size[0], height=size[1]).save(failure.with_suffix(".png"))
        atomic_write(
            failure.with_suffix(".json"),
            json.dumps(
                {
                    "scene": scene.name,
                    "error": str(error),
                    "actual": current_scene_identity(process.pid),
                    "layer": current_ui_layer_vtable(process.pid),
                    "cursor": current_cursor_resource(process.pid),
                },
                indent=2,
            ).encode(),
        )
        raise
    finally:
        grabber.close()
        stop(process, window)


def _wait_for_visible_room(
    process: subprocess.Popen[bytes],
    window: int,
    grabber: FrameGrabber,
    size: tuple[int, int],
) -> tuple[int, FrameGrabber]:
    """Let the scripted intro acquire input before skipping its black fade."""
    deadline = time.monotonic() + 5
    next_skip = time.monotonic() + 0.15
    while True:
        window, grabber, frame = _grab_frame(process, window=window, grabber=grabber, size=size)
        if _room_ready(process.pid, frame):
            return window, grabber
        if time.monotonic() > deadline:
            msg = "scene intro did not release the rendered room"
            raise CaptureError(msg)
        if time.monotonic() >= next_skip:
            press_key(window, 0x1B, hold_seconds=0.03)
            next_skip = time.monotonic() + 0.15
        time.sleep(0.02)


def _room_ready(process_id: int, frame: Image) -> bool:
    """Require rendered gameplay with no scripted action owning the cursor."""
    return (
        _room_frame_visible(frame)
        and current_ui_layer_vtable(process_id) == _ROOM_LAYER_VTABLE
        and current_cursor_resource(process_id) not in {None, "C_WAIT", "C_PLAYACTION"}
    )


def _room_frame_visible(frame: Image) -> bool:
    """Reject black fades and small centered movies in the curated world views."""
    histogram = frame.convert("L").histogram()
    # Authored temple close-ups can have almost all their detail at levels 2/3.
    # Brightness is not scene readiness; native layer/cursor state gates input.
    return sum(histogram[1:]) > frame.width * frame.height / 10


def _scene_capture_visible(path: Path) -> bool:
    from PIL import Image as PILImage  # noqa: PLC0415

    with PILImage.open(path) as frame:
        return _room_frame_visible(frame)
