"""Reproducible SIDNEY views reached through the game's own interaction script."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import numpy as np

from gk3hd.system.files import atomic_write
from tests.visual.support.matrix import (
    _ROOM_LAYER_VTABLE,
    _grab_frame,
    _isolated_save,
    _launch_restored_save,
)
from tests.visual.support.phases import EMAIL_NOTICE, green_indicator_visible
from tests.visual.support.scenario import _wait_for_visible_room
from tests.visual.support.special import (
    _INVENTORY_VTABLE,
    _authored_point,
    _dismiss_restored_console,
    _run_console_command,
    _wait_for_layer,
)
from tests.visual.support.windows import (
    CaptureError,
    click_frame_point,
    current_cursor_resource,
    current_scene_identity,
    current_ui_layer_vtable,
    move_frame_point,
    press_key,
    stop,
    type_text,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from PIL import Image

    from tests.visual.support.matrix import _CaptureContext
    from tests.visual.support.saves import SaveGame

_ENTRY_TIMEOUT = 15.0
_PAGE_TIMEOUT = 5.0
_ORANGE_RED_MIN = 110
_ORANGE_GREEN_MIN = 45
_ORANGE_GREEN_MAX = 150
_ORANGE_BLUE_MAX = 90
_ORANGE_RED_GREEN_DELTA = 20
_HOME_ORANGE_FRACTION = 0.06
_PAGE_CHANGE_FRACTION = 0.02
_STABLE_MEAN_DELTA = 0.5
_SETTLED_FRAMES = 3


def capture_sidney(
    context: _CaptureContext,
    save: SaveGame,
    *,
    size: tuple[int, int],
    output: Path,
    selected: frozenset[str] | None = None,
) -> dict[str, Path]:
    """Load the shared save, enter day two, and use the retail Grace entry script."""
    paths: dict[str, Path] = {}
    with _isolated_save(context.game_dir, save.path):
        atomic_write(context.game_dir / "fastsave.gk3", save.path.read_bytes())
        process, window, grabber = _launch_restored_save(
            context=context, size=size, failure_output=output / "sidney-startup-failure.png"
        )
        try:
            _dismiss_restored_console(window, grabber, size=size)
            _run_console_command(window, 'SetLocationTime("R25","205p");')
            deadline = time.monotonic() + _ENTRY_TIMEOUT
            while (
                current_scene_identity(process.pid) != ("r25", "205p")
                or current_ui_layer_vtable(process.pid) != _ROOM_LAYER_VTABLE
            ):
                if time.monotonic() >= deadline:
                    message = "SIDNEY fixture did not enter Gabriel's room on day two"
                    raise CaptureError(message)  # noqa: TRY301 - preserve failure frame below.
                press_key(window, 0x1B, hold_seconds=0.03)
            press_key(window, 0x1B, hold_seconds=0.06)
            window, grabber = _wait_for_visible_room(process, window, grabber, size)
            # R25_23ALL.NVC uses this script for COMPUTER_SCREEN/TYPE. It performs
            # the native camera/actor setup that a bare ShowSidney() would omit.
            _run_console_command(window, 'CallSheep("r25_all","GraceStartSidney");')

            def grab() -> Image.Image:
                nonlocal window, grabber
                window, grabber, frame = _grab_frame(
                    process, window=window, grabber=grabber, size=size
                )
                return frame

            home = wait_for_home(grab)
            if selected is None or "sidney-home" in selected:
                home = _settle_capture(window, grab, size, notice=True)
                paths["sidney-home"] = _save_page(home, output, "sidney-home")
            for name, x in (("search", 232), ("email", 312), ("analyze", 472), ("translate", 552)):
                if selected is not None and f"sidney-{name}" not in selected:
                    continue
                click_frame_point(window, *_authored_point(size, x, 175), frame_size=size)
                frame = wait_for_page(grab, home)
                frame = _page_content(name, window, grab, size, frame)
                frame = _settle_capture(window, grab, size, notice=name in {"search", "email"})
                paths[f"sidney-{name}"] = _save_page(frame, output, f"sidney-{name}")
                click_frame_point(window, *_authored_point(size, 762, 604), frame_size=size)
                home = wait_for_home(grab)
            if selected is None or "sidney-map" in selected:
                frame = _capture_map(window, process.pid, grab, size)
                frame = _settle_capture(window, grab, size, notice=False)
                paths["sidney-map"] = _save_page(frame, output, "sidney-map")
        except CaptureError:
            grabber.grab(width=size[0], height=size[1]).save(output / "sidney-failure.png")
            raise
        finally:
            grabber.close()
            stop(process, window)
    return paths


def _settle_capture(
    window: int, grab: Callable[[], Image.Image], size: tuple[int, int], *, notice: bool
) -> Image.Image:
    """Park one cursor off the controls, then capture a matching native blink phase."""
    move_frame_point(window, *_authored_point(size, 840, 620), frame_size=size)
    deadline = time.monotonic() + _PAGE_TIMEOUT
    ready = 0
    while time.monotonic() < deadline:
        frame = grab()
        ready = ready + 1 if not notice or green_indicator_visible(frame, EMAIL_NOTICE) else 0
        if ready >= _SETTLED_FRAMES:
            return frame
    message = "SIDNEY did not present its lit new-email indicator"
    raise CaptureError(message)


def _save_page(frame: Image.Image, output: Path, name: str) -> Path:
    path = output / f"{name}.png"
    frame.save(path, format="PNG", compress_level=1)
    return path


def _page_content(
    name: str,
    window: int,
    grab: Callable[[], Image.Image],
    size: tuple[int, int],
    frame: Image.Image,
) -> Image.Image:
    """Show real content, rather than several copies of the empty watermark."""
    if name == "search":
        click_frame_point(window, *_authored_point(size, 512, 256), frame_size=size)
        type_text(window, "vampires", key_interval=0.02)
        click_frame_point(window, *_authored_point(size, 718, 256), frame_size=size)
        return wait_for_page(grab, frame)
    if name == "email":
        click_frame_point(window, *_authored_point(size, 420, 406), frame_size=size)
        return wait_for_page(grab, frame)
    # Translation accepts extracted text, not scanned images. Its native file
    # browser is a distinct font/layout comparison; analysis shows parchment.
    return _open_file(window, grab, size, row=None if name == "translate" else 257)


def _open_file(
    window: int, grab: Callable[[], Image.Image], size: tuple[int, int], *, row: int | None = 242
) -> Image.Image:
    """Show the native browser, optionally opening a known fixture file row."""
    click_frame_point(window, *_authored_point(size, 232, 175), frame_size=size)
    for _ in range(3):
        frame = grab()
    click_frame_point(window, *_authored_point(size, 246, 190), frame_size=size)
    frame = wait_for_page(grab, frame)
    if row is None:
        return frame
    click_frame_point(window, *_authored_point(size, 267, row), frame_size=size)
    wait_for_page(grab, frame)
    move_frame_point(window, *_authored_point(size, 840, 620), frame_size=size)
    for _ in range(3):
        frame = grab()
    return frame


def _capture_map(
    window: int,
    process_id: int,
    grab: Callable[[], Image.Image],
    size: tuple[int, int],
) -> Image.Image:
    """Exercise the native scanner with the fixture's map item."""
    click_frame_point(window, *_authored_point(size, 632, 175), frame_size=size)
    _wait_for_layer(process_id, _INVENTORY_VTABLE, timeout=5.0)
    # This is exactly INV_ALL.NVC's MAP/SCANNER action, not a fabricated file.
    _run_console_command(window, 'SetGameVariableInt("SidScanner",20); HideInventory();')
    deadline = time.monotonic() + _ENTRY_TIMEOUT
    while current_cursor_resource(process_id) in {None, "C_WAIT", "C_PLAYACTION"}:
        if time.monotonic() >= deadline:
            message = "SIDNEY's map scanner did not finish"
            raise CaptureError(message)
        grab()
        time.sleep(0.02)
    home = wait_for_home(grab)
    click_frame_point(window, *_authored_point(size, 472, 175), frame_size=size)
    wait_for_page(grab, home)
    frame = _open_file(window, grab, size)
    click_frame_point(window, *_authored_point(size, 650, 604), frame_size=size)
    frame = wait_for_page(grab, frame)
    # Dismiss the recognition explanation so both map panes are unobstructed.
    click_frame_point(window, *_authored_point(size, 512, 448), frame_size=size)
    return wait_for_page(grab, frame)


def _screen_pixels(frame: Image.Image) -> np.ndarray[tuple[int, ...], np.dtype[np.int16]]:
    """Normalize only for readiness checks; never resample the saved screenshot."""
    size = frame.size
    left, top = _authored_point(size, 192, 185)
    right, bottom = _authored_point(size, 832, 595)
    return np.asarray(frame.crop((left, top, right, bottom)).resize((320, 205)), dtype=np.int16)


def wait_for_home(grab: Callable[[], Image.Image]) -> Image.Image:
    """Require the amber logo on the dark application screen, then stable presents."""
    deadline = time.monotonic() + _ENTRY_TIMEOUT
    previous = None
    while time.monotonic() < deadline:
        frame = grab()
        pixels = _screen_pixels(frame)
        red, green, blue = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
        orange = (
            (red > _ORANGE_RED_MIN)
            & (green > _ORANGE_GREEN_MIN)
            & (green < _ORANGE_GREEN_MAX)
            & (blue < _ORANGE_BLUE_MAX)
            & (red - green > _ORANGE_RED_GREEN_DELTA)
        )
        if (
            float(orange.mean()) >= _HOME_ORANGE_FRACTION
            and previous is not None
            and float(np.abs(pixels - previous).mean()) < _STABLE_MEAN_DELTA
        ):
            return frame
        previous = pixels
    message = "SIDNEY did not present its settled home screen"
    raise CaptureError(message)


def wait_for_page(grab: Callable[[], Image.Image], before: Image.Image) -> Image.Image:
    """Require actual application-content change, not just a moved cursor/tab hover."""
    original = _screen_pixels(before)
    previous = original
    deadline = time.monotonic() + _PAGE_TIMEOUT
    while time.monotonic() < deadline:
        frame = grab()
        pixels = _screen_pixels(frame)
        changed = float(np.any(np.abs(pixels - original) > 20, axis=2).mean())
        if (
            changed >= _PAGE_CHANGE_FRACTION
            and float(np.abs(pixels - previous).mean()) < _STABLE_MEAN_DELTA
        ):
            return frame
        previous = pixels
    message = "SIDNEY tab did not change the application content"
    raise CaptureError(message)
