"""Shared native capture, state restoration and game-readiness helpers."""

from __future__ import annotations

import contextlib
import json
import re
import time
import winreg
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import typer
from PIL import Image as PILImage
from rich.console import Console

from gk3hd.patch.install.configuration import GraphicsBackend
from gk3hd.patch.install.windows import required_gk3_appcompat_layers
from gk3hd.patch.service import PatchRequest, PatchService
from gk3hd.renderer.distribution import CONFIG_NAME, DLL_NAME, config_bytes
from gk3hd.system.files import atomic_write
from tests.visual.support.readiness import (
    frame_mean_absolute_difference,
    restore_browser_visible,
    restore_dialog_visible,
    startup_escape_safe,
    title_ready,
    title_restore_center,
)
from tests.visual.support.reference import aligned_map_reference, renderer_compatibility
from tests.visual.support.windows import (
    CaptureError,
    FrameGrabber,
    click_frame_point,
    current_scene_identity,
    current_ui_layer_pointer,
    current_ui_layer_vtable,
    launch,
    post_key,
    press_key,
    process_error_dialog,
    read_process_words,
    stop,
    wait_for_window,
)

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from PIL.Image import Image

    from tests.visual.support.saves import SaveGame

console = Console()

_ENGINE_KEY: Final = r"Software\Sierra On-Line\Gabriel Knight 3\Engine"
_HARDWARE_KEY: Final = _ENGINE_KEY + r"\Hardware"
_APP_COMPAT_KEY: Final = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
_RESOLUTION_VALUES: Final = (
    "Game Width",
    "Game Height",
    "Screen Width",
    "Screen Height",
    "Full Screen",
)
_REFERENCE_QUALITY: Final = (
    ("Incremental Rendering", 0, winreg.REG_DWORD),
    ("Mip Mapping", 1, winreg.REG_DWORD),
    ("Interpolation", 1, winreg.REG_DWORD),
    ("Trilinear Filtering", 1, winreg.REG_DWORD),
    ("Lod", 100, winreg.REG_DWORD),
    ("Max Anisotropy Level", 0xFFFFFFFF, winreg.REG_DWORD),
    ("Gamma", "1.000000", winreg.REG_SZ),
    ("Surface Quality", "High", winreg.REG_SZ),
)
_CUSTOM_PATHS: Final = re.compile(rb"(?im)^[ \t]*CUSTOM PATHS[ \t]*=[^\r\n]*")
_VK_ESCAPE: Final = 0x1B
_VK_RETURN: Final = 0x0D
_VK_RESTORE: Final = ord("R")
_VK_QUICK_LOAD: Final = 0x75
_REFERENCE_SIZE: Final = (1024, 768)
_RESTORE_WAIT_SECONDS: Final = 0.5
_RESTORE_BROWSER_TIMEOUT_SECONDS: Final = 12.0
_ROOM_WAIT_SECONDS: Final = 0.5
_ROOM_TRANSITION_TIMEOUT_SECONDS: Final = 4.0
_ROOM_TRANSITION_MINIMUM_MAD: Final = 8.0
_TITLE_TIMEOUT_SECONDS: Final = 30.0
_STARTUP_ESCAPE_INTERVAL_SECONDS: Final = 0.15
_RESOLUTION_PARTS: Final = 2
_FRAME_CAPTURE_ATTEMPTS: Final = 3
_MAX_STARTUP_ESCAPES: Final = 4
_TITLE_LAYER_VTABLE: Final = 0x0069238C
_STARTUP_SPLASH_LAYER_VTABLE: Final = 0x0067E550
_RESTORE_LAYER_VTABLE: Final = 0x0067CD40
_ROOM_LAYER_VTABLE: Final = 0x0067A248
_TIMEBLOCK_LAYER_VTABLE: Final = 0x0067DF90
_ANIMATION_SEQUENCE_VTABLE: Final = 0x00666AC4
_RESTORED_LAYER_VTABLES: Final = frozenset({_ROOM_LAYER_VTABLE, _TIMEBLOCK_LAYER_VTABLE})
_RESTORE_OPEN_ATTEMPTS: Final = 8
_RESTORE_ACTIVATE_ATTEMPTS: Final = 5


@dataclass(frozen=True, slots=True)
class _RegistryValue:
    name: str
    value: int
    kind: int


@dataclass(frozen=True, slots=True)
class _OptionalRegistryValue:
    name: str
    value: int | str | None
    kind: int | None


@dataclass(frozen=True, slots=True)
class _CaptureContext:
    executable: Path
    game_dir: Path
    ini_path: Path
    use_wgc: bool
    ini_bytes: bytes | None


@dataclass(frozen=True, slots=True)
class _ModeCapture:
    context: _CaptureContext
    saves: tuple[SaveGame, ...]
    output_directory: Path
    size: tuple[int, int]
    resume: bool


@dataclass(frozen=True, slots=True)
class _FrameState:
    process: subprocess.Popen[bytes]
    window: int
    grabber: FrameGrabber
    size: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _SceneFrame:
    save: SaveGame
    frame: Image


@dataclass(frozen=True, slots=True)
class _SaveFrameRequest:
    context: _CaptureContext
    save: SaveGame
    payload: bytes
    output: Path
    size: tuple[int, int]
    previous: _SceneFrame | None
    first: bool


@contextlib.contextmanager
def _reference_capture_context(executable: Path) -> Iterator[Path]:
    """Keep the installed renderer; compare authored geometry and original assets."""
    with (
        _reference_executable(executable) as reference_executable,
        _temporary_reference_quality(original=True),
    ):
        yield reference_executable


def _capture_is_valid(path: Path, size: tuple[int, int]) -> bool:
    if not path.is_file():
        return False
    try:
        with PILImage.open(path) as image:
            image.verify()
        with PILImage.open(path) as image:
            return (
                image.size == size
                and image.convert("L").getextrema() != (0, 0)
                and not restore_dialog_visible(image)
                and not restore_browser_visible(image)
            )
    except OSError:
        return False


def _save_scene_changed(previous: SaveGame, current: SaveGame) -> bool:
    """Require evidence of a new frame when loading a different save slot.

    Saves in the same room and time block can have different cameras, scores,
    and puzzle state. A visually identical result is ambiguous: the caller
    retries from a fresh process rather than accepting a stale quick-load.
    """
    return previous != current


def _capture_save_frame(
    state: _FrameState,
    request: _SaveFrameRequest,
) -> tuple[_FrameState, Image]:
    """Load one save, retrying directly when F6 was consumed by another transition."""
    if not request.first:
        state = _quick_load_or_restart(state, request)
    state, frame = _grab_settled_frame(state, use_wgc=request.context.use_wgc)
    try:
        window, grabber, frame = _wait_for_scene_transition(
            state,
            previous=request.previous if request.context.use_wgc else None,
            current=_SceneFrame(request.save, frame),
        )
    except CaptureError:
        state.grabber.close()
        stop(state.process, state.window)
        state = _restart_at_save(request)
        state, frame = _grab_settled_frame(state, use_wgc=request.context.use_wgc)
        try:
            window, grabber, frame = _wait_for_scene_transition(
                state,
                # A fresh process cannot retain the previous save's frame.
                # Different time blocks can legitimately share the same view.
                previous=None,
                current=_SceneFrame(request.save, frame),
            )
        except CaptureError:
            state.grabber.close()
            stop(state.process, state.window)
            raise
    return _FrameState(state.process, window, grabber, state.size), frame


def _quick_load_or_restart(
    state: _FrameState,
    request: _SaveFrameRequest,
) -> _FrameState:
    if not request.context.use_wgc:
        # GDI can return the preceding DirectDraw room after IsCurrentLocation
        # already changes (retail TE3 -> TE4 -> TE5 reproduces this). Animated
        # old pixels also pass image-difference checks. A fresh reference
        # process cannot contain another save's frame; do not trust F6 here.
        state.grabber.close()
        stop(state.process, state.window)
        return _restart_at_save(request)
    atomic_write(request.context.game_dir / "fastsave.gk3", request.payload)
    try:
        window = _quick_load(state.process, window=state.window, save=request.save.path)
    except CaptureError:
        state.grabber.close()
        stop(state.process, state.window)
        return _restart_at_save(request)
    return _FrameState(state.process, window, state.grabber, state.size)


def _restart_at_save(request: _SaveFrameRequest) -> _FrameState:
    atomic_write(request.context.game_dir / "save0001.gk3", request.payload)
    atomic_write(request.context.game_dir / "fastsave.gk3", request.payload)
    process, window, grabber = _launch_restored_save(
        context=request.context,
        size=request.size,
        failure_output=request.output,
    )
    return _FrameState(process, window, grabber, request.size)


def _grab_settled_frame(
    state: _FrameState,
    *,
    use_wgc: bool,
) -> tuple[_FrameState, Image]:
    time.sleep(_ROOM_WAIT_SECONDS)
    window = wait_for_window(state.process.pid)
    grabber = state.grabber
    if use_wgc:
        # DirectDraw replaces its presentation surface after every restore.
        grabber.close()
        grabber = FrameGrabber(window)
    window, grabber, frame = _grab_frame(
        state.process,
        window=window,
        grabber=grabber,
        size=state.size,
    )
    return _FrameState(state.process, window, grabber, state.size), frame


def _wait_for_scene_transition(
    state: _FrameState,
    *,
    previous: _SceneFrame | None,
    current: _SceneFrame,
) -> tuple[int, FrameGrabber, Image]:
    """Reject a restored RoomLayer until its scene is visible without progress UI."""
    window, grabber, frame = state.window, state.grabber, current.frame
    deadline = time.monotonic() + _ROOM_TRANSITION_TIMEOUT_SECONDS
    while (
        not _scene_identity_matches(state.process.pid, current.save)
        or _frame_blocks_capture(previous, current.save, frame)
        or not _timeblock_reveal_complete(state.process.pid)
    ):
        if time.monotonic() >= deadline:
            message = f"GK3 did not settle after loading {current.save.path.name}"
            raise CaptureError(message)
        time.sleep(0.05)
        window, grabber, frame = _grab_frame(
            state.process,
            window=window,
            grabber=grabber,
            size=state.size,
        )
    # Identity/reveal can become current after the previous screenshot was
    # acquired. Read a new presentation, then recheck the scene; a moving old
    # room can pass image-difference thresholds but is not the requested save.
    window, grabber, frame = _grab_frame(
        state.process, window=window, grabber=grabber, size=state.size
    )
    if (
        not _scene_identity_matches(state.process.pid, current.save)
        or _frame_blocks_capture(previous, current.save, frame)
        or not _timeblock_reveal_complete(state.process.pid)
    ):
        message = f"GK3 scene changed while capturing {current.save.path.name}"
        raise CaptureError(message)
    return window, grabber, frame


def _scene_identity_matches(process_id: int, save: SaveGame) -> bool:
    """Reject an old or unreadable scene even when its animation looks fresh."""
    return current_scene_identity(process_id) == (save.room.casefold(), save.timeblock.casefold())


def _timeblock_reveal_complete(process_id: int) -> bool:
    """Wait for actual lettering completion, not a resolution-dependent delay."""
    if current_ui_layer_vtable(process_id) != _TIMEBLOCK_LAYER_VTABLE:
        return True
    root = current_ui_layer_pointer(process_id)
    if root is None:
        return False
    # TimeBlock's animated child owns an AnimSequence pointer and current index.
    # The sequence's begin/end vector stores four-byte bitmap handles.
    child = read_process_words(process_id, root + 0x2D4, count=4)
    if not child or not child[0]:
        return False
    sequence = read_process_words(process_id, child[0], count=11)
    if not sequence or sequence[0] != _ANIMATION_SEQUENCE_VTABLE:
        return False
    begin, end = sequence[9:11]
    if not begin or end <= begin or (end - begin) % 4:
        return False
    return child[3] == (end - begin) // 4 - 1


def _frame_blocks_capture(
    previous: _SceneFrame | None,
    save: SaveGame,
    frame: Image,
) -> bool:
    if restore_dialog_visible(frame) or restore_browser_visible(frame):
        return True
    return bool(
        previous is not None
        and _save_scene_changed(previous.save, save)
        and frame_mean_absolute_difference(previous.frame, frame) < _ROOM_TRANSITION_MINIMUM_MAD
    )


def _record_capture(
    save: SaveGame,
    *,
    frame: Image,
    output: Path,
    on_captured: Callable[[SaveGame, Path], None],
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.save(output, format="PNG", compress_level=1)
    on_captured(save, output)


def _launch_restored_save(
    *,
    context: _CaptureContext,
    size: tuple[int, int],
    failure_output: Path,
) -> tuple[subprocess.Popen[bytes], int, FrameGrabber]:
    """Launch GK3 and activate the sole staged Restore entry."""
    process = launch(context.executable)
    window: int | None = None
    grabber: FrameGrabber | None = None
    try:
        window = wait_for_window(process.pid)
        # Startup swaps DirectDraw surfaces. GDI observes those swaps directly;
        # binding WGC here can spend whole frame timeouts on a retired surface.
        grabber = FrameGrabber(window, wgc=False)
        window, grabber = _wait_for_title(
            process,
            window=window,
            grabber=grabber,
            size=size,
            failure_output=failure_output,
        )
        window, grabber, _restore_frame = _open_restore(
            process,
            window=window,
            grabber=grabber,
            size=size,
            failure_output=failure_output,
        )
        window, grabber = _activate_restore(
            process,
            window=window,
            grabber=grabber,
            size=size,
            failure_output=failure_output,
        )
    except Exception:
        if grabber is not None:
            grabber.close()
        stop(process, window)
        raise
    return process, window, grabber


def _quick_load(
    process: subprocess.Popen[bytes],
    *,
    window: int,
    save: Path,
) -> int:
    """Load the newly staged ``fastsave.gk3`` and wait for its durable owner."""
    initial_layer = current_ui_layer_vtable(process.pid)
    press_key(window, _VK_QUICK_LOAD, hold_seconds=0.06)
    deadline = time.monotonic() + _TITLE_TIMEOUT_SECONDS
    departure_deadline = time.monotonic() + 2.0
    departed = False
    while time.monotonic() < deadline:
        if process.poll() is not None:
            message = f"GK3 exited while quick-loading {save.name}"
            raise CaptureError(message)
        layer = current_ui_layer_vtable(process.pid)
        if layer != initial_layer:
            departed = True
        if departed and layer in _RESTORED_LAYER_VTABLES:
            return wait_for_window(process.pid, timeout=3.0)
        if not departed and time.monotonic() >= departure_deadline:
            message = f"GK3 declined quick-load while {save.name} was staged"
            raise CaptureError(message)
        time.sleep(0.05)
    message = f"GK3 did not finish quick-loading {save.name}"
    raise CaptureError(message)


def _wait_for_title(
    process: subprocess.Popen[bytes],
    *,
    window: int,
    grabber: FrameGrabber,
    size: tuple[int, int],
    failure_output: Path,
) -> tuple[int, FrameGrabber]:
    deadline = time.monotonic() + _TITLE_TIMEOUT_SECONDS
    last_escape = float("-inf")
    escape_count = 0
    last_frame: Image | None = None
    last_layer_vtable: int | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            message = f"GK3 exited during startup with status {process.returncode}"
            raise CaptureError(message)
        window, grabber, frame = _grab_frame(
            process,
            window=window,
            grabber=grabber,
            size=size,
        )
        last_frame = frame
        now = time.monotonic()
        layer_vtable = current_ui_layer_vtable(process.pid)
        last_layer_vtable = layer_vtable
        if layer_vtable == _TITLE_LAYER_VTABLE and grabber.uses_wgc:
            # DirectDraw may replace the startup surface without rebinding WGC.
            # Read the live title before gating input on its presented controls.
            grabber.close()
            grabber = FrameGrabber(window, wgc=False)
            frame = grabber.grab(width=size[0], height=size[1])
        if layer_vtable == _TITLE_LAYER_VTABLE and title_ready(frame):
            return window, grabber
        # The splash owns Escape even before its logo has faded into view.
        # Waiting for bright artwork unnecessarily plays part of the movie.
        # Loading cannot consume Escape; unknown owners still need visual proof.
        native_movie_wait = layer_vtable == _STARTUP_SPLASH_LAYER_VTABLE
        if (
            escape_count < _MAX_STARTUP_ESCAPES
            and (native_movie_wait or (layer_vtable is None and startup_escape_safe(frame)))
            and now - last_escape >= _STARTUP_ESCAPE_INTERVAL_SECONDS
        ):
            press_key(window, _VK_ESCAPE, hold_seconds=0.03)
            last_escape = now
            escape_count += 1
        time.sleep(0.016)
    artifact = failure_output.with_name(f"{failure_output.stem}-startup-failure.png")
    if last_frame is not None:
        last_frame.save(artifact, format="PNG", compress_level=1)
    message = (
        f"GK3 title screen was not ready within {_TITLE_TIMEOUT_SECONDS:g} seconds; "
        f"startup Escapes={escape_count}, last layer={last_layer_vtable!r}; "
        f"last frame: {artifact}"
    )
    raise CaptureError(message)


def _open_restore(
    process: subprocess.Popen[bytes],
    *,
    window: int,
    grabber: FrameGrabber,
    size: tuple[int, int],
    failure_output: Path,
) -> tuple[int, FrameGrabber, Image]:
    # The title readiness gate checks both ownership and presented controls.
    # Retry an ignored input below instead of delaying every successful launch.
    window, grabber, title_frame = _grab_frame(
        process,
        window=window,
        grabber=grabber,
        size=size,
    )
    for attempt in range(_RESTORE_OPEN_ATTEMPTS):
        restore_center = title_restore_center(title_frame)
        layer_before = current_ui_layer_vtable(process.pid)
        if layer_before == _RESTORE_LAYER_VTABLE:
            frame = title_frame
        else:
            if layer_before is not None and layer_before != _TITLE_LAYER_VTABLE:
                press_key(window, _VK_ESCAPE, hold_seconds=0.03)
            elif restore_center is not None:
                click_frame_point(window, *restore_center, frame_size=size)
            elif attempt == 0:
                post_key(window, _VK_RESTORE)
            else:
                press_key(window, _VK_RESTORE, hold_seconds=0.06)
            _wait_for_layer_departure(process.pid, layer_before, timeout=0.4)
            window = wait_for_window(process.pid)
            window, grabber, frame = _grab_frame(
                process,
                window=window,
                grabber=grabber,
                size=size,
            )
        layer_vtable = current_ui_layer_vtable(process.pid)
        restore_layer_owned = layer_vtable == _RESTORE_LAYER_VTABLE
        if restore_layer_owned or (layer_vtable is None and not title_ready(frame)):
            # DirectDraw replaces the presented surface while Title hands off
            # to Restore. A WGC session bound before that transition can keep
            # returning its now-black old surface even while the new page is
            # visibly populated and flipping. Rebind through GDI for this
            # short modal boundary; callers may start a fresh WGC session once
            # the restored room owns the window.
            if restore_layer_owned and grabber.uses_wgc:
                grabber.close()
                grabber = FrameGrabber(window, wgc=False)
                frame = grabber.grab(width=size[0], height=size[1])
            deadline = time.monotonic() + _RESTORE_BROWSER_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if restore_browser_visible(frame):
                    return window, grabber, frame
                time.sleep(0.02)
                window, grabber, frame = _grab_frame(
                    process,
                    window=window,
                    grabber=grabber,
                    size=size,
                )
            title_frame = frame
        title_frame = frame
    artifact = failure_output.with_name(f"{failure_output.stem}-restore-failure.png")
    artifact.parent.mkdir(parents=True, exist_ok=True)
    title_frame.save(artifact, format="PNG", compress_level=1)
    center = title_restore_center(title_frame)
    layer_vtable = current_ui_layer_vtable(process.pid)
    message = (
        f"Restore did not leave the title screen after {_RESTORE_OPEN_ATTEMPTS} verified inputs; "
        f"Restore center={center!r}, layer={layer_vtable!r}; last frame: {artifact}"
    )
    raise CaptureError(message)


def _wait_for_layer_departure(process_id: int, layer: int | None, *, timeout: float) -> None:
    """Return immediately on a UI transition, or let the caller retry its input."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and current_ui_layer_vtable(process_id) == layer:
        time.sleep(0.02)


def _activate_restore(
    process: subprocess.Popen[bytes],
    *,
    window: int,
    grabber: FrameGrabber,
    size: tuple[int, int],
    failure_output: Path,
) -> tuple[int, FrameGrabber]:
    deadline = time.monotonic() + _TITLE_TIMEOUT_SECONDS
    next_input = float("-inf")
    attempts = 0
    activation_started = False
    while time.monotonic() < deadline:
        if process.poll() is not None:
            message = f"GK3 exited while activating Restore with status {process.returncode}"
            raise CaptureError(message)
        window = wait_for_window(process.pid, timeout=3.0)
        layer_vtable = current_ui_layer_vtable(process.pid)
        if layer_vtable in _RESTORED_LAYER_VTABLES:
            return window, grabber
        if layer_vtable != _RESTORE_LAYER_VTABLE:
            activation_started = True
        now = time.monotonic()
        if not activation_started and attempts < _RESTORE_ACTIVATE_ATTEMPTS and now >= next_input:
            if attempts % 2 == 0:
                post_key(window, _VK_RETURN)
            else:
                press_key(window, _VK_RETURN, hold_seconds=0.06)
            attempts += 1
            next_input = now + 0.8
        time.sleep(0.05)
    artifact = failure_output.with_name(f"{failure_output.stem}-activation-failure.png")
    artifact.parent.mkdir(parents=True, exist_ok=True)
    try:
        window = wait_for_window(process.pid, timeout=1.0)
        diagnostic = FrameGrabber(window, wgc=False)
        frame = diagnostic.grab(width=size[0], height=size[1])
        frame.save(artifact, format="PNG", compress_level=1)
    except CaptureError:
        artifact_description = "unavailable (window closed)"
    else:
        artifact_description = str(artifact)
    layer_vtable = current_ui_layer_vtable(process.pid)
    message = (
        "Restore did not reach the loaded room after "
        f"{attempts} verified inputs; layer={layer_vtable!r}; "
        f"last frame: {artifact_description}"
    )
    raise CaptureError(message)


def _grab_frame(
    process: subprocess.Popen[bytes],
    *,
    window: int,
    grabber: FrameGrabber,
    size: tuple[int, int],
) -> tuple[int, FrameGrabber, Image]:
    last_error: CaptureError | None = None
    for attempt in range(_FRAME_CAPTURE_ATTEMPTS):
        _raise_for_error_dialog(process.pid)
        try:
            frame = grabber.grab(width=size[0], height=size[1])
        except CaptureError as error:
            last_error = error
            grabber.close()
            if process.poll() is not None or attempt == _FRAME_CAPTURE_ATTEMPTS - 1:
                break
            window = wait_for_window(process.pid, timeout=3.0)
            grabber = FrameGrabber(window, wgc=grabber.uses_wgc)
        else:
            _raise_for_error_dialog(process.pid)
            return window, grabber, frame
    message = f"could not obtain a live GK3 frame: {last_error}"
    raise CaptureError(message) from last_error


def _raise_for_error_dialog(process_id: int) -> None:
    """Do not accept a modal crash dialog as a rendered game frame."""
    fatal = process_error_dialog(process_id)
    if fatal is not None:
        message = f"GK3 reported an error: {fatal}"
        raise CaptureError(message)


@contextlib.contextmanager
def _reference_executable(installed: Path) -> Iterator[Path]:
    backup = installed.with_name(installed.name + ".bak")
    if not backup.is_file():
        message = (
            f"pristine executable backup does not exist: {backup}; "
            "install the gk3hd patch before generating comparisons"
        )
        raise CaptureError(message)
    reference = installed.with_name("gk3hd-visual-reference.exe")
    if reference.exists():
        message = f"temporary visual reference executable already exists: {reference}"
        raise CaptureError(message)
    uses_d7vk = installed.with_name(DLL_NAME).is_file()
    backend = GraphicsBackend.D7VK if uses_d7vk else GraphicsBackend.NATIVE
    installed_config = installed.with_name(CONFIG_NAME)
    config_before = installed_config.read_bytes() if installed_config.is_file() else None
    try:
        atomic_write(reference, backup.read_bytes())
        prepared = PatchService().prepare(
            PatchRequest(
                exe=reference,
                group=None,
                patches=(
                    "remove_disc_requirement",
                    "skip_all_movies",
                    "prevent_save_warning_dialogs",
                ),
                resolution=_REFERENCE_SIZE,
                backend=backend.value,
            )
        )
        output = (
            renderer_compatibility(prepared.output, prepared.profile)
            if uses_d7vk
            else prepared.output
        )
        atomic_write(reference, aligned_map_reference(output, prepared.profile))
        if uses_d7vk:
            # D7VK configuration sections match exact executable basenames.
            atomic_write(
                installed_config,
                config_bytes(executable_name=reference.name, previous=config_before or b""),
            )
        with _temporary_appcompat(reference, graphics_backend=backend):
            yield reference
    finally:
        reference.unlink(missing_ok=True)
        if uses_d7vk:
            _restore_ini(installed_config, config_before)


@contextlib.contextmanager
def _temporary_reference_quality(*, original: bool = False) -> Iterator[None]:
    """Use maximum quality and default gamma during a comparison, then restore."""
    previous: list[_OptionalRegistryValue] = []
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _HARDWARE_KEY) as key:
        for name, value, kind in _REFERENCE_QUALITY:
            configured = 1 if original and name == "Max Anisotropy Level" else value
            try:
                old_value, old_kind = winreg.QueryValueEx(key, name)
            except FileNotFoundError:
                previous.append(_OptionalRegistryValue(name, None, None))
            else:
                if not isinstance(old_value, (int, str)):
                    message = f"unexpected registry value for {name}"
                    raise CaptureError(message)
                previous.append(_OptionalRegistryValue(name, old_value, old_kind))
            winreg.SetValueEx(key, name, 0, kind, configured)
    try:
        yield
    finally:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _HARDWARE_KEY) as key:
            for item in previous:
                if item.kind is None:
                    with contextlib.suppress(FileNotFoundError):
                        winreg.DeleteValue(key, item.name)
                else:
                    winreg.SetValueEx(key, item.name, 0, item.kind, item.value)


@contextlib.contextmanager
def _temporary_appcompat(executable: Path, *, graphics_backend: GraphicsBackend) -> Iterator[None]:
    name = str(executable.resolve())
    previous: tuple[str, int] | None = None
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _APP_COMPAT_KEY) as key:
        try:
            value, kind = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            pass
        else:
            if not isinstance(value, str):
                message = f"unexpected AppCompat value for {name}"
                raise CaptureError(message)
            previous = value, kind
        encoded_previous = (
            json.dumps({"type": previous[1], "value": previous[0]})
            if previous is not None
            else None
        )
        policy = required_gk3_appcompat_layers(encoded_previous, graphics_backend=graphics_backend)
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, json.loads(policy)["value"])
    try:
        yield
    finally:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _APP_COMPAT_KEY) as key:
            if previous is None:
                with contextlib.suppress(FileNotFoundError):
                    winreg.DeleteValue(key, name)
            else:
                winreg.SetValueEx(key, name, 0, previous[1], previous[0])


@contextlib.contextmanager
def _isolated_save(game_dir: Path, source: Path) -> Iterator[None]:
    staged: list[tuple[Path, Path]] = []
    # The original executable only restores numbered native save slots even
    # though patched builds can enumerate arbitrary ``*.gk3`` names.
    capture_save = game_dir / "save0001.gk3"
    staging_directory = game_dir / ".gk3hd-visual-save-staging"
    source_payload = source.read_bytes()
    if staging_directory.exists():
        message = f"stale visual save staging directory requires attention: {staging_directory}"
        raise CaptureError(message)
    # Do not enter cleanup until this run owns the staging directory. If mkdir
    # fails (permissions, a concurrent run), the native save slot is untouched.
    staging_directory.mkdir()
    capture_created = False
    try:
        for existing in sorted(game_dir.glob("*.gk3")):
            backup = staging_directory / existing.name
            existing.replace(backup)
            staged.append((backup, existing))
        if capture_save.exists():
            message = f"could not isolate visual capture save: {capture_save}"
            raise CaptureError(message)
        atomic_write(capture_save, source_payload)
        capture_created = True
        # Own the quick-load slot too. Initializing it here makes cleanup
        # safe even if a caller fails before launching its first game session.
        atomic_write(game_dir / "fastsave.gk3", source_payload)
        yield
    finally:
        if capture_created:
            capture_save.unlink(missing_ok=True)
            (game_dir / "fastsave.gk3").unlink(missing_ok=True)
        for backup, original in reversed(staged):
            if backup.exists():
                backup.replace(original)
        with contextlib.suppress(OSError):
            staging_directory.rmdir()


def _parse_resolution(value: str) -> tuple[int, int]:
    parts = value.lower().split("x", maxsplit=1)
    if len(parts) != _RESOLUTION_PARTS:
        message = "resolution must use WIDTHxHEIGHT"
        raise typer.BadParameter(message)
    try:
        width, height = (int(part) for part in parts)
    except ValueError as error:
        message = "resolution must use WIDTHxHEIGHT"
        raise typer.BadParameter(message) from error
    if width < _REFERENCE_SIZE[0] or height < _REFERENCE_SIZE[1]:
        message = "resolution must be at least 1024x768"
        raise typer.BadParameter(message)
    return width, height


def _snapshot_resolution() -> tuple[_RegistryValue, ...]:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _ENGINE_KEY) as key:
        values: list[_RegistryValue] = []
        for name in _RESOLUTION_VALUES:
            value, kind = winreg.QueryValueEx(key, name)
            if not isinstance(value, int) or kind != winreg.REG_DWORD:
                message = f"unexpected registry value for {name}"
                raise CaptureError(message)
            values.append(_RegistryValue(name, value, kind))
        return tuple(values)


def _set_resolution(size: tuple[int, int]) -> None:
    width, height = size
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _ENGINE_KEY) as key:
        for name, value in (
            ("Game Width", width),
            ("Game Height", height),
            ("Screen Width", width),
            ("Screen Height", height),
            ("Full Screen", 1),
        ):
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)


def _restore_resolution(values: tuple[_RegistryValue, ...]) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _ENGINE_KEY) as key:
        for value in values:
            winreg.SetValueEx(key, value.name, 0, value.kind, value.value)


def _without_custom_paths(payload: bytes | None) -> bytes:
    if payload is None:
        return b"CUSTOM PATHS = \r\n"
    if _CUSTOM_PATHS.search(payload):
        return _CUSTOM_PATHS.sub(b"CUSTOM PATHS = ", payload, count=1)
    newline = b"\r\n" if b"\r\n" in payload else b"\n"
    return b"CUSTOM PATHS = " + newline + payload


def _restore_ini(path: Path, payload: bytes | None) -> None:
    if payload is None:
        path.unlink(missing_ok=True)
    else:
        atomic_write(path, payload)
