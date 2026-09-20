"""Capture GK3's interaction-heavy screens at reference and current quality."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import numpy as np
import typer
from PIL import Image
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.definitions.runtime2d.layout import (
    RESOURCE_DRIVING_MAP_SEEN_OFFSET,
    RESOURCE_SEGMENT,
    RuntimeLayout,
    RuntimeSegment,
)
from gk3hd.system.discovery import discover_game
from gk3hd.system.files import atomic_write
from tests.visual.support.matrix import (
    _RESTORE_LAYER_VTABLE,
    _ROOM_LAYER_VTABLE,
    _TIMEBLOCK_LAYER_VTABLE,
    _activate_restore,
    _capture_is_valid,
    _CaptureContext,
    _grab_frame,
    _isolated_save,
    _launch_restored_save,
    _ModeCapture,
    _parse_resolution,
    _reference_capture_context,
    _restore_ini,
    _restore_resolution,
    _set_resolution,
    _snapshot_resolution,
    _temporary_reference_quality,
    _wait_for_title,
    _without_custom_paths,
)
from tests.visual.support.phases import LOCATION_MARKER, fitted_point, green_indicator_visible
from tests.visual.support.readiness import (
    developer_console_visible,
    restore_browser_visible,
    restore_dialog_visible,
    startup_escape_safe,
    timeblock_complete,
    title_play_center,
)
from tests.visual.support.render import frame_writer, write_comparisons
from tests.visual.support.runs import comparison_run
from tests.visual.support.saves import SaveGame, read_save_game
from tests.visual.support.windows import (
    CaptureError,
    FrameGrabber,
    capture_session,
    click_frame_point,
    current_ui_layer_pointer,
    current_ui_layer_vtable,
    held_click_frame_point,
    launch,
    make_dpi_aware,
    move_frame_point,
    press_chord,
    press_key,
    read_process_words,
    stop,
    type_text,
    wait_for_window,
)

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable

    from gk3hd.system.discovery import GameTarget

console = Console()

_REFERENCE_SIZE: Final = (1024, 768)
_VK_CONTROL: Final = 0x11
_VK_SHIFT: Final = 0x10
_VK_OEM_3: Final = 0xC0
_VK_RETURN: Final = 0x0D
_VK_ESCAPE: Final = 0x1B
_VK_INVENTORY: Final = ord("I")
_FIXTURE_DESCRIPTION: Final = "GK3HD visual inventory"
_FIXTURE_ITEMS: Final = (
    "GOLD_COAT",
    "BINOCULARS",
    "FINGERPRINT_KIT",
    "MOSELYS_PASSPORT",
    "MOSELYS_ROOM_KEY",
    "MOPED_KEYS",
    "MAP",
    "SYRUP_PACKAGE",
    "TAPE_RECORDER",
    "HANGER",
)
_CLOSEUP_VTABLE: Final = 0x00674798
_INVENTORY_VTABLE: Final = 0x0067BE24
_BINOCULAR_VTABLE: Final = 0x00668428
_FINGERPRINT_VTABLE: Final = 0x00678264
_CONFIRM_QUIT_VTABLE: Final = 0x0067DC14
_SAVE_LAYER_VTABLE: Final = 0x0067CE58
_MAP_SKY_FRACTION_MAX: Final = 0.01
_MAP_MEAN_LUMA_MIN: Final = 40.0
_MAP_WIDE_DARK_FRACTION_MIN: Final = 0.15
_MAP_DARK_CHANNEL_MAX: Final = 12
_MAP_GRAY_FRACTION_MAX: Final = 0.10
_MAP_GRAY_RANGE_MAX: Final = 16
_MAP_GRAY_LUMA_MIN: Final = 35
_MAP_HOVER_CHANNEL_DELTA_MIN: Final = 24
_MAP_HOVER_CHANGED_PIXELS_MIN: Final = 32
_MAP_TOOLTIP_WHITE_CHANNEL_MIN: Final = 235
_MAP_TOOLTIP_WHITE_PIXELS_MIN: Final = 40
_MAP_TOOLTIP_ROWS_MIN: Final = 4
_SKY_BLUE_MIN: Final = 120
_ACTION_MENU_MAX_CHILDREN: Final = 8
_ACTION_MENU_VTABLE: Final = 0x00692E9C
_TOOLBAR_VTABLE: Final = 0x00684FA4
_UI_MAX_CHILDREN: Final = 256
_DRIVING_MAP_PROBES: Final = (
    ("driving-map-idle", (512, 740), None),
    # These are initially available destinations, not individual hotel/museum
    # interiors. Rectangles are original DM_* crop bounds converted from 640
    # to the 1024 reference canvas. Verify the highlighted artwork, not a delay.
    ("driving-map-rennes-les-bains-hover", (830, 313), (779, 278, 874, 356)),
    ("driving-map-rennes-le-chateau-hover", (350, 228), (309, 190, 392, 266)),
    ("driving-map-station-hover", (130, 240), (91, 210, 170, 271)),
)


@dataclass(frozen=True, slots=True)
class SpecialScene:
    """One named output captured from an interaction sequence."""

    name: str
    description: str
    room: str


SPECIAL_SCENES: Final = (
    SpecialScene("title", "Main menu", "title"),
    SpecialScene("timeblock", "Day-one noon timeblock", "timeblock"),
    SpecialScene("save-editor", "Save-game name editor", "save"),
    SpecialScene("graphics-options", "Graphics options", "toolbar"),
    SpecialScene("advanced-graphics-options", "Advanced graphics options", "toolbar"),
    SpecialScene("sidney-home", "SIDNEY home screen", "sidney"),
    SpecialScene("sidney-search", "SIDNEY research search", "sidney"),
    SpecialScene("sidney-email", "SIDNEY email", "sidney"),
    SpecialScene("sidney-analyze", "SIDNEY analysis", "sidney"),
    SpecialScene("sidney-map", "SIDNEY map analysis", "sidney"),
    SpecialScene("sidney-translate", "SIDNEY translation", "sidney"),
    SpecialScene("inventory", "Inventory with multiple item rows", "inventory"),
    SpecialScene("inventory-action-menu", "Inventory item's action menu", "inventory"),
    SpecialScene("inventory-action-hover", "Highlighted inventory action", "inventory"),
    SpecialScene(
        "inventory-after-selection",
        "Two-row inventory after selecting a different item",
        "inventory",
    ),
    SpecialScene(
        "inventory-mosely-clothes-menu",
        "Mosely Clothes action menu after another selection",
        "inventory",
    ),
    SpecialScene(
        "inventory-mosely-clothes-hover",
        "Highlighted Mosely Clothes selection action",
        "inventory",
    ),
    SpecialScene(
        "inventory-after-mosely-clothes-selection",
        "Two-row inventory after reselecting Mosely Clothes",
        "inventory",
    ),
    SpecialScene("inventory-closeup", "Inventory item close-up and score", "closeup"),
    SpecialScene("inventory-return-hover", "Inventory hover after closing close-up", "inventory"),
    SpecialScene("right-click-toolbar", "In-room right-click toolbar", "toolbar"),
    SpecialScene("confirm-quit", "First quit confirmation with Yes hover", "confirm"),
    SpecialScene(
        "confirm-quit-after-no",
        "Reopened quit confirmation after clicking No, with Yes hover",
        "confirm",
    ),
    SpecialScene(
        "right-click-toolbar-after-quit",
        "Toolbar reopened after two quit-confirmation cycles",
        "toolbar",
    ),
    SpecialScene("restore-browser", "Restore browser before loading the staged save", "restore"),
    SpecialScene("play-quit-yes", "Fresh Play quit dialog, cursor over Yes", "confirm"),
    SpecialScene("play-quit-no", "Fresh Play quit dialog, cursor over No", "confirm"),
    SpecialScene("restore-browser-second", "Restore browser after a previous Restore", "restore"),
    SpecialScene("restore-toolbar-first", "Toolbar after the first Restore from Play", "toolbar"),
    SpecialScene("restore-toolbar-second", "Toolbar after the second Restore", "toolbar"),
    SpecialScene("restore-quit-yes", "Quit after two Restores, cursor over Yes", "confirm"),
    SpecialScene("restore-quit-no", "Quit after two Restores, cursor over No", "confirm"),
    SpecialScene(
        "restore-return-room",
        "Room immediately after the Restore browser finishes",
        "restore",
    ),
    SpecialScene("binoculars", "Binocular interface", "binoculars"),
    SpecialScene("fingerprint", "Fingerprint interface", "fingerprint"),
    SpecialScene("driving-map-idle", "Driving map without a highlighted location", "driving"),
    SpecialScene(
        "driving-map-rennes-les-bains-hover", "Rennes-les-Bains highlight and tooltip", "driving"
    ),
    SpecialScene(
        "driving-map-rennes-le-chateau-hover",
        "Rennes-le-Chateau highlight and tooltip",
        "driving",
    ),
    SpecialScene("driving-map-station-hover", "Train station highlight and tooltip", "driving"),
    SpecialScene(
        "museum-closeup", "Museum's first panel opened through its native script", "museum"
    ),
)


def capture(
    *,
    game_dir: Path | None,
    resolution: str,
    resume: Path | None,
    selected: tuple[str, ...] | None = None,
) -> None:
    """Capture interaction-heavy screens at 1024 and current quality."""
    current_size = _parse_resolution(resolution)
    make_dpi_aware()
    target = discover_game(game_dir=game_dir)
    with capture_session(target.exe), _temporary_reference_quality():
        _run_capture(target, current_size=current_size, resume=resume, selected=selected)


def _run_capture(
    target: GameTarget,
    *,
    current_size: tuple[int, int],
    resume: Path | None,
    selected: tuple[str, ...] | None = None,
) -> None:
    """Own the settings snapshot, both quality modes, and combined report."""
    chosen = _selected_scenes(selected)
    try:
        run = comparison_run(resume=resume, append_resolution=current_size)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    current_directory = run / f"current-{current_size[0]}x{current_size[1]}"
    reference_directory = run / "reference-1024x768"
    ini_path = target.ini or target.game_dir / "GK3.ini"
    ini_original = ini_path.read_bytes() if ini_path.is_file() else None
    registry = _snapshot_resolution()
    try:
        _set_resolution(current_size)
        # Generate the shared recipe with original geometry/resources, not
        # whichever runtime patch build happens to be under investigation.
        with _reference_capture_context(target.exe) as reference_executable:
            _set_resolution(_REFERENCE_SIZE)
            reference_ini = _without_custom_paths(ini_original)
            _restore_ini(ini_path, reference_ini)
            fixture = _ensure_interaction_fixture(
                _CaptureContext(
                    executable=reference_executable,
                    game_dir=target.game_dir,
                    ini_path=ini_path,
                    use_wgc=False,
                    ini_bytes=reference_ini,
                ),
                size=_REFERENCE_SIZE,
            )
        with Progress(
            SpinnerColumn("line"),
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Capturing special scenes", total=len(chosen) * 2)
            current = _capture_mode(
                _ModeCapture(
                    context=_CaptureContext(
                        executable=target.exe,
                        game_dir=target.game_dir,
                        ini_path=ini_path,
                        use_wgc=True,
                        ini_bytes=ini_original,
                    ),
                    size=current_size,
                    output_directory=current_directory,
                    saves=(fixture,),
                    resume=resume is not None,
                ),
                advance=lambda: progress.advance(task),
                selected=chosen,
            )
            with _reference_capture_context(target.exe) as reference_executable:
                reference = _capture_mode(
                    _ModeCapture(
                        context=_CaptureContext(
                            executable=reference_executable,
                            game_dir=target.game_dir,
                            ini_path=ini_path,
                            use_wgc=False,
                            ini_bytes=_without_custom_paths(ini_original),
                        ),
                        size=_REFERENCE_SIZE,
                        output_directory=reference_directory,
                        saves=(fixture,),
                        resume=resume is not None,
                    ),
                    advance=lambda: progress.advance(task),
                    selected=chosen,
                )
    finally:
        _restore_ini(ini_path, ini_original)
        _restore_resolution(registry)

    descriptions = {
        scene.name: SaveGame(
            path=Path(f"{scene.name}.gk3"),
            description=scene.description,
            room=scene.room,
            timeblock="special",
        )
        for scene in chosen
    }
    captures = tuple(
        (descriptions[scene.name], reference[scene.name], current[scene.name]) for scene in chosen
    )
    sheet, animations = write_comparisons(captures, output=run / "comparisons")
    manifest = {
        "reference": "1024x768",
        "current": f"{current_size[0]}x{current_size[1]}",
        "scenes": [scene.name for scene in chosen],
    }
    atomic_write(run / "special-scenes.json", (json.dumps(manifest, indent=2) + "\n").encode())
    console.print(f"Captured [bold]{len(chosen)}[/] special scenes")
    console.print(f"Combined visual matrix: [cyan]{sheet}[/]")
    console.print(f"Animated comparisons: [cyan]{animations[0].parent}[/]")


def _selected_scenes(names: tuple[str, ...] | None) -> tuple[SpecialScene, ...]:
    """Resolve explicit selections before changing game settings or launching it."""
    if names is None:
        return SPECIAL_SCENES
    catalog = {scene.name: scene for scene in SPECIAL_SCENES}
    unknown = set(names) - catalog.keys()
    if not names or unknown:
        message = f"invalid special-scene selection: {sorted(unknown) if unknown else 'empty'}"
        raise ValueError(message)
    return tuple(catalog[name] for name in dict.fromkeys(names))


def _ensure_interaction_fixture(
    context: _CaptureContext,
    *,
    size: tuple[int, int],
) -> SaveGame:
    """Generate one private native save from Play; never require a player's progress.

    The recipe uses only shipped inventory identifiers. Both quality modes load
    this same fixture, and the game writes it beneath the repo's build directory,
    outside the numbered player save slots. Reuse avoids another startup per run.
    """
    destination = _interaction_fixture_path()
    if destination.is_file():
        return _validate_interaction_fixture(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    process = launch(context.executable)
    window = None
    grabber = None
    try:
        window = wait_for_window(process.pid)
        grabber = FrameGrabber(window, wgc=False)
        window, grabber = _wait_for_title(
            process,
            window=window,
            grabber=grabber,
            size=size,
            failure_output=destination.with_suffix(".png"),
        )
        window, grabber, frame = _grab_frame(process, window=window, grabber=grabber, size=size)
        play = title_play_center(frame)
        if play is None:
            message = "could not locate Play while creating the visual fixture"
            raise CaptureError(message)
        click_frame_point(window, *play, frame_size=size)
        _wait_for_layer(process.pid, _TIMEBLOCK_LAYER_VTABLE, timeout=8.0)
        press_key(window, _VK_ESCAPE, hold_seconds=0.06)
        _wait_for_layer(process.pid, _ROOM_LAYER_VTABLE, timeout=8.0)
        window = wait_for_window(process.pid)
        # Play starts a scripted room intro after the time-block card. Its
        # busy cursor owns input even though the Room layer is already active.
        press_key(window, _VK_ESCAPE, hold_seconds=0.06)
        _run_console_command(
            window,
            " ".join(f'EgoTakeInvItem("{item}");' for item in _FIXTURE_ITEMS),
        )
        _run_console_command(
            window,
            f'SaveGameBinary("{destination.as_posix()}", "{_FIXTURE_DESCRIPTION}");',
        )
        deadline = time.monotonic() + 5.0
        while not destination.is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        return _validate_interaction_fixture(destination)
    finally:
        if grabber is not None:
            grabber.close()
        stop(process, window)


def _interaction_fixture_path() -> Path:
    return Path(__file__).resolve().parents[3] / "build/visual/fixtures/interaction.gk3"


def _validate_interaction_fixture(path: Path) -> SaveGame:
    """Reject a different or stale recipe rather than silently testing wrong scenes."""
    fixture = read_save_game(path)
    if (fixture.description, fixture.room, fixture.timeblock) != (
        _FIXTURE_DESCRIPTION,
        "r25",
        "110a",
    ):
        message = f"unexpected visual fixture metadata: {path}"
        raise CaptureError(message)
    return fixture


def _capture_mode(
    request: _ModeCapture,
    *,
    advance: Callable[[], None],
    selected: tuple[SpecialScene, ...] = SPECIAL_SCENES,
) -> dict[str, Path]:
    """Capture the interaction, Restore, and console-driven map sequences."""
    context, size, output = request.context, request.size, request.output_directory
    (fixture,) = request.saves
    _set_resolution(size)
    _restore_ini(context.ini_path, context.ini_bytes)
    output.mkdir(parents=True, exist_ok=True)
    existing = {
        scene.name: output / f"{scene.name}.png"
        for scene in selected
        if request.resume and _capture_is_valid(output / f"{scene.name}.png", size)
    }
    for _ in existing:
        advance()
    results = dict(existing)
    pending = {scene.name for scene in selected} - existing.keys()
    restore_names = {
        scene.name
        for scene in SPECIAL_SCENES
        if scene.name.startswith(("restore-", "play-"))
        or scene.name in {"title", "timeblock", "save-editor"}
    }
    driving_names = {name for name, _point, _region in _DRIVING_MAP_PROBES}
    sidney_names = {scene.name for scene in SPECIAL_SCENES if scene.room == "sidney"}
    groups = (
        (pending - restore_names - driving_names - sidney_names, _capture_interactions),
        (pending & restore_names, _capture_restore_scenes),
        (pending & driving_names, _capture_driving_scenes),
        (pending & sidney_names, _capture_sidney_scenes),
    )
    for names, runner in groups:
        if not names:
            continue
        captured = runner(context, fixture, size=size, output=output, selected=frozenset(names))
        for name in names:
            results[name] = captured[name]
            advance()
    return results


def _capture_sidney_scenes(
    context: _CaptureContext,
    save: SaveGame,
    *,
    size: tuple[int, int],
    output: Path,
    selected: frozenset[str] | None = None,
) -> dict[str, Path]:
    from tests.visual.support.sidney import capture_sidney  # noqa: PLC0415

    return capture_sidney(context, save, size=size, output=output, selected=selected)


def _capture_interactions(
    context: _CaptureContext,
    save: SaveGame,
    *,
    size: tuple[int, int],
    output: Path,
    selected: frozenset[str] | None = None,
) -> dict[str, Path]:
    payload = save.path.read_bytes()
    failure = output / "interaction-startup-failure.png"
    process = None
    window: int | None = None
    grabber = None
    paths: dict[str, Path] = {}
    with (
        _isolated_save(context.game_dir, save.path),
        frame_writer() as write_frame,
    ):
        try:
            atomic_write(context.game_dir / "fastsave.gk3", payload)
            process, window, grabber = _launch_restored_save(
                context=context,
                size=size,
                failure_output=failure,
            )
            if context.use_wgc:
                grabber.close()
                grabber = FrameGrabber(window)
            _dismiss_restored_console(window, grabber, size=size)

            def record(name: str) -> None:
                nonlocal window, grabber
                if selected is not None and name not in selected:
                    return
                if process is None or window is None or grabber is None:
                    msg = "special-scene process is not available"
                    raise RuntimeError(msg)
                # Discard the frame already in flight when input arrived.
                # Wait on fresh presents, not an arbitrary settle timer.
                for _ in range(2):
                    window, grabber, frame = _grab_frame(
                        process,
                        window=window,
                        grabber=grabber,
                        size=size,
                    )
                path = output / f"{name}.png"
                write_frame(frame, path)
                paths[name] = path

            _capture_interaction_sequences(
                window, process_id=process.pid, size=size, record=record, selected=selected
            )
        except CaptureError as error:
            if process is not None and window is not None and grabber is not None:
                frame = grabber.grab(width=size[0], height=size[1])
                frame.save(failure, format="PNG", compress_level=1)
                message = (
                    f"{error}; layer={current_ui_layer_vtable(process.pid)!r}; "
                    f"last frame: {failure}"
                )
                raise CaptureError(message) from error
            raise
        finally:
            if grabber is not None:
                grabber.close()
            if process is not None:
                stop(process, window)
    return paths


def _capture_interaction_sequences(
    window: int,
    *,
    process_id: int,
    size: tuple[int, int],
    record: Callable[[str], None],
    selected: frozenset[str] | None,
) -> None:
    """Only visit inventory or room interfaces requested by pytest selection."""
    if selected is None or any(name.startswith("inventory") for name in selected):
        _capture_inventory_scenes(window, process_id=process_id, size=size, record=record)
    if selected is None:
        _capture_system_scenes(window, process_id=process_id, size=size, record=record)
    else:
        _capture_requested_room_scenes(
            window, process_id=process_id, size=size, record=record, selected=selected
        )


def _capture_requested_room_scenes(
    window: int,
    *,
    process_id: int,
    size: tuple[int, int],
    record: Callable[[str], None],
    selected: frozenset[str],
) -> None:
    """Keep catalog routes short: do not visit unrelated diagnostic interfaces."""
    if "right-click-toolbar" in selected:
        click_frame_point(window, *_authored_point(size, 700, 500), frame_size=size, button="right")
        _wait_for_toolbar(process_id)
        record("right-click-toolbar")
        press_key(window, _VK_ESCAPE, hold_seconds=0.06)
    if selected & {"graphics-options", "advanced-graphics-options"}:
        _capture_graphics_scenes(window, process_id=process_id, size=size, record=record)
    if "museum-closeup" in selected:
        _run_console_command(window, 'InventoryInspect("MS3I_PANEL1");')
        _wait_for_layer(process_id, _CLOSEUP_VTABLE, timeout=6.0)
        record("museum-closeup")
        press_key(window, _VK_ESCAPE, hold_seconds=0.06)
        _wait_until_layer_changes(process_id, _CLOSEUP_VTABLE, timeout=3.0)


def _capture_graphics_scenes(
    window: int, *, process_id: int, size: tuple[int, int], record: Callable[[str], None]
) -> None:
    """Open the wrench panel and its two settings levels without changing settings."""
    click_frame_point(window, *_authored_point(size, 512, 384), frame_size=size, button="right")
    _wait_for_toolbar(process_id)
    for point, label in (
        ((572, 390), None),
        ((475, 459), None),
        ((512, 489), "graphics-options"),
        ((512, 620), "advanced-graphics-options"),
    ):
        previous = _visible_ui_rectangles(process_id)
        click_frame_point(window, *_authored_point(size, *point), frame_size=size)
        _wait_for_ui_layout_change(process_id, previous)
        if label is not None:
            record(label)
    press_key(window, _VK_ESCAPE, hold_seconds=0.06)


def _visible_ui_rectangles(process_id: int) -> tuple[tuple[int, ...], ...]:
    """Bounded native visible-tree signature, independent of private patch telemetry."""
    pending = [current_ui_layer_pointer(process_id) or 0]
    seen: set[int] = set()
    result = []
    while pending and len(seen) < _UI_MAX_CHILDREN:
        node = pending.pop()
        if not node or node in seen:
            continue
        seen.add(node)
        words = read_process_words(process_id, node, count=11)
        if not words or not words[6] & 0xFF:
            continue
        result.append((words[0], *words[7:11]))
        pending.extend(_ui_children(process_id, node))
    return tuple(sorted(result))


def _wait_for_ui_layout_change(process_id: int, previous: tuple[tuple[int, ...], ...]) -> None:
    """Advance on a changed, settled native control tree, not a fixed sleep."""
    deadline = time.monotonic() + 3.0
    last = previous
    while time.monotonic() < deadline:
        current = _visible_ui_rectangles(process_id)
        if current and current != previous and current == last:
            return
        last = current
        time.sleep(0.02)
    message = "settings click did not change the visible control layout"
    raise CaptureError(message)


def _capture_inventory_scenes(
    window: int,
    *,
    process_id: int,
    size: tuple[int, int],
    record: Callable[..., None],
) -> None:
    """Exercise inventory, ActionMenu, close-up, and return-hover state."""
    press_key(window, _VK_INVENTORY, hold_seconds=0.08)
    _wait_for_layer(process_id, _INVENTORY_VTABLE, timeout=3.0)
    record("inventory")
    click_frame_point(window, *_authored_point(size, 209, 231), frame_size=size)
    magnifier = _wait_for_action_menu(
        process_id,
        button_index=0,
        timeout=3.0,
    )
    record("inventory-action-menu")
    move_frame_point(window, *magnifier, frame_size=size)
    record("inventory-action-hover")

    held_click_frame_point(
        window,
        *magnifier,
        frame_size=size,
        hold_seconds=0.12,
    )
    _wait_for_layer(process_id, _CLOSEUP_VTABLE, timeout=6.0)
    record("inventory-closeup")
    press_key(window, _VK_ESCAPE, hold_seconds=0.06)
    _wait_until_layer_changes(process_id, _CLOSEUP_VTABLE, timeout=3.0)
    move_frame_point(window, *_authored_point(size, 209, 231), frame_size=size)
    record("inventory-return-hover")

    # Select a different item after returning. This forces Inventory::Layout
    # through the state change that historically collapsed a two-row
    # collection into one physical-width row and pushed later items off-screen.
    click_frame_point(window, *_authored_point(size, 209, 231), frame_size=size)
    select_item = _wait_for_action_menu(
        process_id,
        button_index=2,
        timeout=3.0,
    )
    held_click_frame_point(window, *select_item, frame_size=size, hold_seconds=0.12)
    _wait_for_action_menu_closed(process_id, timeout=3.0)
    record("inventory-after-selection")

    # Reselect Mosely Clothes after the notepad changes Inventory's selected
    # object. This is the high-value two-row regression: the clothes sit late
    # in the first row and used to expose both collapsed layout and stale
    # action-menu pointer geometry.
    click_frame_point(window, *_authored_point(size, 509, 131), frame_size=size)
    select_clothes = _wait_for_action_menu(
        process_id,
        # Unlike the notepad, the coat has no Use verb: Select is second.
        button_index=1,
        timeout=3.0,
    )
    record("inventory-mosely-clothes-menu")
    move_frame_point(window, *select_clothes, frame_size=size)
    record("inventory-mosely-clothes-hover")
    held_click_frame_point(window, *select_clothes, frame_size=size, hold_seconds=0.12)
    _wait_for_action_menu_closed(process_id, timeout=3.0)
    record("inventory-after-mosely-clothes-selection")
    press_key(window, _VK_ESCAPE, hold_seconds=0.06)
    _wait_until_layer_changes(process_id, _INVENTORY_VTABLE, timeout=3.0)


def _capture_system_scenes(
    window: int,
    *,
    process_id: int,
    size: tuple[int, int],
    record: Callable[..., None],
) -> None:
    """Exercise toolbar, confirmation, and console-driven close-up screens."""
    click_frame_point(
        window,
        *_authored_point(size, 700, 500),
        frame_size=size,
        button="right",
    )
    _wait_for_toolbar(process_id)
    record("right-click-toolbar")
    press_key(window, _VK_ESCAPE, hold_seconds=0.06)
    press_key(window, ord("Q"), control=True, hold_seconds=0.08)
    _wait_for_layer(process_id, _CONFIRM_QUIT_VTABLE, timeout=3.0)
    move_frame_point(window, *_authored_point(size, 516, 421), frame_size=size)
    record("confirm-quit")
    click_frame_point(window, *_authored_point(size, 673, 421), frame_size=size)
    _wait_until_layer_changes(process_id, _CONFIRM_QUIT_VTABLE, timeout=3.0)
    press_key(window, ord("Q"), control=True, hold_seconds=0.08)
    _wait_for_layer(process_id, _CONFIRM_QUIT_VTABLE, timeout=3.0)
    move_frame_point(window, *_authored_point(size, 516, 421), frame_size=size)
    record("confirm-quit-after-no")
    press_key(window, _VK_ESCAPE, hold_seconds=0.06)
    _wait_until_layer_changes(process_id, _CONFIRM_QUIT_VTABLE, timeout=3.0)
    click_frame_point(
        window,
        *_authored_point(size, 700, 500),
        frame_size=size,
        button="right",
    )
    _wait_for_toolbar(process_id)
    record("right-click-toolbar-after-quit")
    press_key(window, _VK_ESCAPE, hold_seconds=0.06)
    # This is the command in MS3_ALL.NVC for inspecting the first museum
    # panel. It works from an ordinary room, without a camera/save fixture.
    _run_console_command(window, 'InventoryInspect("MS3I_PANEL1");')
    _wait_for_layer(process_id, _CLOSEUP_VTABLE, timeout=6.0)
    record("museum-closeup")
    press_key(window, _VK_ESCAPE, hold_seconds=0.06)
    _wait_until_layer_changes(process_id, _CLOSEUP_VTABLE, timeout=3.0)
    _run_console_command(window, "ShowBinocs();")
    _wait_for_layer(process_id, _BINOCULAR_VTABLE, timeout=6.0)
    record("binoculars")
    # This interface binds its Exit button, not the ordinary Escape hotkey.
    click_frame_point(window, *_authored_point(size, 259, 646), frame_size=size)
    _wait_until_layer_changes(process_id, _BINOCULAR_VTABLE, timeout=3.0)
    _run_console_command(window, 'ShowFingerprintInterface("MIRROR");')
    _wait_for_layer(process_id, _FINGERPRINT_VTABLE, timeout=6.0)
    record("fingerprint")


def _capture_restore_scenes(
    context: _CaptureContext,
    save: SaveGame,
    *,
    size: tuple[int, int],
    output: Path,
    selected: frozenset[str] | None = None,
) -> dict[str, Path]:
    """Exercise Play, moving Quit cursors, and two Restore cycles in one process."""
    process = None
    window: int | None = None
    grabber = None
    paths: dict[str, Path] = {}
    failure = output / "restore-startup-failure.png"
    with _isolated_save(context.game_dir, save.path), frame_writer() as write_frame:
        try:
            atomic_write(context.game_dir / "fastsave.gk3", save.path.read_bytes())
            process = launch(context.executable)
            window = wait_for_window(process.pid)
            grabber = FrameGrabber(window, wgc=False)
            window, grabber = _wait_for_title(
                process,
                window=window,
                grabber=grabber,
                size=size,
                failure_output=failure,
            )

            def record(name: str) -> None:
                nonlocal window, grabber
                if selected is not None and name not in selected:
                    return
                if process is None or window is None or grabber is None:
                    message = "Restore regression process is not available"
                    raise CaptureError(message)
                for _ in range(2):
                    window, grabber, frame = _grab_frame(
                        process, window=window, grabber=grabber, size=size
                    )
                path = output / f"{name}.png"
                write_frame(frame, path)
                paths[name] = path

            record("title")
            window, grabber = _play_from_title(process, window=window, grabber=grabber, size=size)
            press_key(window, _VK_ESCAPE, hold_seconds=0.06)
            _wait_for_layer(process.pid, _ROOM_LAYER_VTABLE, timeout=8.0)
            window = wait_for_window(process.pid)

            def restore() -> None:
                nonlocal window, grabber
                if process is None or window is None or grabber is None:
                    message = "Restore regression process is not available"
                    raise CaptureError(message)
                window, grabber = _activate_restore(
                    process, window=window, grabber=grabber, size=size, failure_output=failure
                )
                _dismiss_restored_console(window, grabber, size=size)

            _capture_restore_cycles(
                window, process_id=process.pid, size=size, record=record, restore=restore
            )
            _capture_save_editor(window, process_id=process.pid, size=size, record=record)
            if selected is None or "timeblock" in selected:
                window, grabber = _show_timeblock(
                    process, window=window, grabber=grabber, size=size, failure=failure
                )
                record("timeblock")
            return paths
        finally:
            if grabber is not None:
                grabber.close()
            if process is not None:
                stop(process, window)


def _play_from_title(
    process: subprocess.Popen[bytes],
    *,
    window: int,
    grabber: FrameGrabber,
    size: tuple[int, int],
) -> tuple[int, FrameGrabber]:
    """Reach Play's transient opening card before skipping to gameplay."""
    window, grabber, title = _grab_frame(process, window=window, grabber=grabber, size=size)
    play = title_play_center(title)
    if play is None:
        message = "could not locate Play for the Restore regression sequence"
        raise CaptureError(message)
    click_frame_point(window, *play, frame_size=size)
    _wait_for_layer(process.pid, _TIMEBLOCK_LAYER_VTABLE, timeout=8.0)
    return window, grabber


def _show_timeblock(
    process: subprocess.Popen[bytes],
    *,
    window: int,
    grabber: FrameGrabber,
    size: tuple[int, int],
    failure: Path,
) -> tuple[int, FrameGrabber]:
    """Use a chapter transition: Play's initial card has no durable controls."""
    _wait_for_layer(process.pid, _ROOM_LAYER_VTABLE, timeout=3.0)
    _run_console_command(window, 'SetTime("112p");')
    deadline = time.monotonic() + 8.0
    while current_ui_layer_vtable(process.pid) != _TIMEBLOCK_LAYER_VTABLE:
        if time.monotonic() >= deadline:
            message = "timeblock transition did not acquire its native layer"
            raise CaptureError(message)
        press_key(window, _VK_ESCAPE, hold_seconds=0.03)
    deadline = time.monotonic() + 8.0
    consecutive = 0
    while time.monotonic() < deadline:
        window, grabber, frame = _grab_frame(process, window=window, grabber=grabber, size=size)
        consecutive = consecutive + 1 if timeblock_complete(frame) else 0
        if consecutive >= 2:
            return window, grabber
    frame.save(failure)
    message = "timeblock card did not finish its title and controls"
    raise CaptureError(message)


def _capture_save_editor(
    window: int, *, process_id: int, size: tuple[int, int], record: Callable[[str], None]
) -> None:
    """Show the name editor and caret without writing a player's save slot."""
    press_key(window, _VK_ESCAPE, hold_seconds=0.06)
    _wait_until_layer_changes(process_id, _CONFIRM_QUIT_VTABLE, timeout=3.0)
    click_frame_point(window, *_authored_point(size, 700, 500), frame_size=size, button="right")
    _wait_for_toolbar(process_id)
    click_frame_point(window, *_authored_point(size, 768, 518), frame_size=size)
    click_frame_point(window, *_authored_point(size, 638, 554), frame_size=size)
    _wait_for_layer(process_id, _SAVE_LAYER_VTABLE, timeout=3.0)
    click_frame_point(window, *_authored_point(size, 300, 256), frame_size=size)
    type_text(window, "GK3HD visual comparison")
    record("save-editor")
    press_key(window, _VK_ESCAPE, hold_seconds=0.06)


def _capture_restore_cycles(
    window: int,
    *,
    process_id: int,
    size: tuple[int, int],
    record: Callable[[str], None],
    restore: Callable[[], None],
) -> None:
    """Retain the lifetime regression without depending on a named player save."""
    # A Room layer exists while Play's intro still owns input. Retry the harmless
    # open-dialog action until its native owner appears, never wait a fixed movie duration.
    deadline = time.monotonic() + 8.0
    while current_ui_layer_vtable(process_id) != _CONFIRM_QUIT_VTABLE:
        if time.monotonic() >= deadline:
            message = "Play did not accept the quit-dialog input"
            raise CaptureError(message)
        press_key(window, ord("Q"), control=True, hold_seconds=0.08)
    for label, point in (("yes", (516, 421)), ("no", (673, 421))):
        move_frame_point(window, *_authored_point(size, *point), frame_size=size)
        record(f"play-quit-{label}")
    press_key(window, _VK_ESCAPE, hold_seconds=0.06)
    _wait_until_layer_changes(process_id, _CONFIRM_QUIT_VTABLE, timeout=3.0)
    press_key(window, _VK_ESCAPE, hold_seconds=0.06)
    for suffix in ("first", "second"):
        click_frame_point(window, *_authored_point(size, 700, 500), frame_size=size, button="right")
        _wait_for_toolbar(process_id)
        click_frame_point(window, *_authored_point(size, 768, 518), frame_size=size)
        click_frame_point(window, *_authored_point(size, 686, 554), frame_size=size)
        _wait_for_layer(process_id, _RESTORE_LAYER_VTABLE, timeout=3.0)
        record("restore-browser" if suffix == "first" else "restore-browser-second")
        restore()
        click_frame_point(window, *_authored_point(size, 700, 500), frame_size=size, button="right")
        _wait_for_toolbar(process_id)
        record(f"restore-toolbar-{suffix}")
        press_key(window, _VK_ESCAPE, hold_seconds=0.06)
    record("restore-return-room")
    press_key(window, ord("Q"), control=True, hold_seconds=0.08)
    _wait_for_layer(process_id, _CONFIRM_QUIT_VTABLE, timeout=3.0)
    for label, point in (("yes", (516, 421)), ("no", (673, 421))):
        move_frame_point(window, *_authored_point(size, *point), frame_size=size)
        record(f"restore-quit-{label}")


def _capture_driving_scenes(
    context: _CaptureContext,
    save: SaveGame,
    *,
    size: tuple[int, int],
    output: Path,
    selected: frozenset[str] | None = None,
) -> dict[str, Path]:
    """Capture stable idle and hover generations from one map lifetime."""
    process = None
    window: int | None = None
    grabber = None
    paths: dict[str, Path] = {}
    failure = output / "driving-map-startup-failure.png"
    with _isolated_save(context.game_dir, save.path):
        try:
            atomic_write(context.game_dir / "fastsave.gk3", save.path.read_bytes())
            process, window, grabber = _launch_restored_save(
                context=context,
                size=size,
                failure_output=failure,
            )
            if context.use_wgc:
                grabber.close()
                grabber = FrameGrabber(window)
            _dismiss_restored_console(window, grabber, size=size)
            _open_driving_map(window, process.pid, size, grabber, context.executable)
            live_window, live_grabber = window, grabber

            def grab() -> Image.Image:
                nonlocal window, grabber, live_window, live_grabber
                live_window, live_grabber, frame = _grab_frame(
                    process, window=live_window, grabber=live_grabber, size=size
                )
                window, grabber = live_window, live_grabber
                return frame

            idle = None
            probes = (
                probe
                for probe in _DRIVING_MAP_PROBES
                if selected is None or probe[0] in selected or probe[2] is None
            )
            for name, point, region in probes:
                move_frame_point(window, *fitted_point(size, *point), frame_size=size)
                frame = _wait_for_driving_hover(grab, idle=idle, point=point, region=region)
                if region is None:
                    idle = frame.copy()
                path = output / f"{name}.png"
                frame.save(path, format="PNG", compress_level=1)
                paths[name] = path
        except CaptureError as error:
            if process is not None and window is not None and grabber is not None:
                window, grabber, frame = _grab_frame(
                    process,
                    window=window,
                    grabber=grabber,
                    size=size,
                )
                artifact = output / "driving-map-interaction-failure.png"
                frame.save(artifact, format="PNG", compress_level=1)
                message = f"{error}; last frame: {artifact}"
                raise CaptureError(message) from error
            raise
        else:
            return paths
        finally:
            if grabber is not None:
                grabber.close()
            if process is not None:
                stop(process, window)


def _wait_for_driving_hover(
    grab: Callable[[], Image.Image],
    *,
    idle: Image.Image | None,
    point: tuple[int, int],
    region: tuple[int, int, int, int] | None,
) -> Image.Image:
    """Advance as soon as the destination highlights, with bounded failure."""
    deadline = time.monotonic() + 3.0
    while True:
        frame = grab()
        if (
            region is None
            or (idle is not None and _driving_hover_changed(idle, frame, point, region))
        ) and green_indicator_visible(frame, LOCATION_MARKER):
            return frame
        if time.monotonic() >= deadline:
            message = f"driving-map location did not highlight at {point}"
            raise CaptureError(message)
        time.sleep(0.02)


def _driving_hover_changed(
    idle: Image.Image,
    current: Image.Image,
    point: tuple[int, int],
    region: tuple[int, int, int, int],
) -> bool:
    """Require highlighted artwork and its delayed tooltip, not cursor movement."""
    frames = []
    for frame in (idle, current):
        first = fitted_point(frame.size, 0, 0)
        last = fitted_point(frame.size, *_REFERENCE_SIZE)
        frames.append(
            np.asarray(
                frame.crop((*first, *last)).resize(_REFERENCE_SIZE, Image.Resampling.BILINEAR),
                dtype=np.int16,
            )
        )
    changed = np.max(np.abs(frames[1] - frames[0]), axis=2) > _MAP_HOVER_CHANNEL_DELTA_MIN
    x, y = point
    # Native tooltips appear below the pointer: the white label background is
    # distinct from the map artwork. Wait for it rather than a fixed hover delay.
    white = np.min(frames[1], axis=2) >= _MAP_TOOLTIP_WHITE_CHANNEL_MIN
    label = (white & changed)[y + 22 : y + 42, x : x + 180]
    tooltip = (
        np.count_nonzero(np.count_nonzero(label, axis=1) >= _MAP_TOOLTIP_WHITE_PIXELS_MIN)
        >= _MAP_TOOLTIP_ROWS_MIN
    )
    changed[y + 22 : y + 42, x : x + 180] = False
    changed[max(0, y - 8) : y + 40, max(0, x - 8) : x + 40] = False
    left, top, right, bottom = region
    return bool(
        tooltip
        and np.count_nonzero(changed[top:bottom, left:right]) >= _MAP_HOVER_CHANGED_PIXELS_MIN
    )


def _open_driving_map(
    window: int,
    process_id: int,
    size: tuple[int, int],
    grabber: FrameGrabber,
    executable: Path,
) -> None:
    """Open the native map directly, without a motorcycle-position save fixture."""
    _run_console_command(window, "ShowDrivingInterface();")
    _wait_for_driving_map(
        grabber,
        process_id=process_id,
        executable=executable,
        size=size,
        timeout=15.0,
    )


def _wait_for_action_menu(
    process_id: int,
    *,
    button_index: int,
    timeout: float,
) -> tuple[int, int]:
    """Read the same live button geometry in native and patched builds."""
    if not 0 <= button_index < _ACTION_MENU_MAX_CHILDREN:
        message = "action-menu button index is out of range"
        raise ValueError(message)
    deadline = time.monotonic() + timeout
    previous: tuple[int, int] | None = None
    while time.monotonic() < deadline:
        point = _action_menu_button_center(process_id, button_index)
        # Do not accept the transient pre-layout rectangles from construction.
        # A second matching observation also avoids guessing a fixed UI delay.
        if point is not None and point == previous:
            return point
        previous = point
        time.sleep(0.04)
    message = f"GK3 did not publish a stable ActionMenu within {timeout:g} seconds"
    raise CaptureError(message)


def _wait_for_action_menu_closed(process_id: int, *, timeout: float) -> None:
    """Require Select to retire its menu before recording or sending more input."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root = current_ui_layer_pointer(process_id)
        owner = read_process_words(process_id, root, count=1) if root else None
        if root is not None and owner == (_INVENTORY_VTABLE,):
            headers = [
                read_process_words(process_id, child, count=7)
                for child in _ui_children(process_id, root)
            ]
            if headers and all(header is not None for header in headers):
                visible = any(
                    header is not None and header[0] == _ACTION_MENU_VTABLE and header[6] & 0xFF
                    for header in headers
                )
                if not visible:
                    return
        time.sleep(0.02)
    message = "GK3 did not dismiss the inventory ActionMenu after Select"
    raise CaptureError(message)


def _ui_children(process_id: int, root: int) -> tuple[int, ...]:
    """Read a bounded native child list; invalid or transient state is empty."""
    state = read_process_words(process_id, root + 0x4C, count=2) if root else None
    if state is None:
        return ()
    pointer, count = state
    if not pointer or not 0 < count <= _UI_MAX_CHILDREN:
        return ()
    return read_process_words(process_id, pointer, count=count) or ()


def _wait_for_toolbar(process_id: int) -> None:
    """Wait for the visible native toolbar child before capturing its labels."""
    deadline = time.monotonic() + 3.0
    previous: int | None = None
    while time.monotonic() < deadline:
        root = current_ui_layer_pointer(process_id)
        current = None
        for child in _ui_children(process_id, root or 0):
            header = read_process_words(process_id, child, count=7) if child else None
            if header and header[0] == _TOOLBAR_VTABLE and header[6] & 0xFF:
                current = child
                break
        if current is not None and current == previous:
            return
        previous = current
        time.sleep(0.02)
    message = "GK3 did not show its in-game toolbar"
    raise CaptureError(message)


def _action_menu_button_center(process_id: int, button_index: int) -> tuple[int, int] | None:
    """Find the visible inventory menu and its actual left-to-right verb cells."""
    root = current_ui_layer_pointer(process_id)
    if root is None:
        return None
    for child in _ui_children(process_id, root):
        header = read_process_words(process_id, child, count=7) if child else None
        if header is None or header[0] != _ACTION_MENU_VTABLE or not header[6] & 0xFF:
            continue
        buttons = _ui_children(process_id, child)
        if not button_index < len(buttons) <= _ACTION_MENU_MAX_CHILDREN:
            continue
        rectangles = [read_process_words(process_id, button + 0x1C, count=4) for button in buttons]
        if any(rect is None or rect[2] <= rect[0] or rect[3] <= rect[1] for rect in rectangles):
            continue
        ordered = sorted(rect for rect in rectangles if rect is not None)
        left, top, right, bottom = ordered[button_index]
        return (left + right) // 2, (top + bottom) // 2
    return None


def _wait_for_layer(process_id: int, vtable: int, *, timeout: float) -> None:
    """Wait for one concrete UI owner instead of guessing at wall-clock time."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if current_ui_layer_vtable(process_id) == vtable:
            return
        time.sleep(0.05)
    message = f"GK3 did not activate UI layer 0x{vtable:08X} within {timeout:g} seconds"
    raise CaptureError(message)


def _wait_for_driving_map(
    grabber: FrameGrabber,
    *,
    process_id: int,
    executable: Path,
    size: tuple[int, int],
    timeout: float,
) -> None:
    """Wait for the earthy road map, rejecting room sky, road, and black fades."""
    seen_va = _runtime_state_va(
        executable,
        segment=RESOURCE_SEGMENT,
        offset=RESOURCE_DRIVING_MAP_SEEN_OFFSET,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        seen = read_process_words(process_id, seen_va, count=1) if seen_va else None
        if seen and seen[0]:
            return
        image = grabber.grab(width=size[0], height=size[1]).resize((160, 90))
        frame = np.asarray(image, dtype=np.int16)
        red, green, blue = frame[:, :, 0], frame[:, :, 1], frame[:, :, 2]
        sky = (blue > red + 25) & (blue > green + 5) & (blue > _SKY_BLUE_MIN)
        dark = frame.max(axis=2) < _MAP_DARK_CHANNEL_MAX
        gray = (frame.max(axis=2) - frame.min(axis=2) < _MAP_GRAY_RANGE_MAX) & (
            frame.mean(axis=2) > _MAP_GRAY_LUMA_MIN
        )
        is_map = (
            float(sky.mean()) < _MAP_SKY_FRACTION_MAX
            and float(frame.mean()) > _MAP_MEAN_LUMA_MIN
            and float(gray.mean()) < _MAP_GRAY_FRACTION_MAX
            and (size == _REFERENCE_SIZE or float(dark.mean()) > _MAP_WIDE_DARK_FRACTION_MIN)
        )
        if is_map:
            return
        time.sleep(0.05)
    message = f"GK3 did not present a stable driving map within {timeout:g} seconds"
    raise CaptureError(message)


def _runtime_state_va(
    executable: Path,
    *,
    segment: RuntimeSegment,
    offset: int,
) -> int | None:
    """Resolve one public generated-runtime state address from the executable."""
    image = PEFile(executable.read_bytes())
    runtime = image.get_section(RuntimeLayout.section_name)
    if runtime is None:
        return None
    return image.rva_to_va(runtime.virtual_address) + segment.offset + offset


def _wait_until_layer_changes(process_id: int, vtable: int, *, timeout: float) -> None:
    """Wait until a modal layer retires before addressing its parent again."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if current_ui_layer_vtable(process_id) != vtable:
            return
        time.sleep(0.05)
    message = f"GK3 did not retire UI layer 0x{vtable:08X} within {timeout:g} seconds"
    raise CaptureError(message)


def _authored_point(size: tuple[int, int], x: int, y: int) -> tuple[int, int]:
    """Project a 1024x768 authored point into a centered current frame."""
    width, height = size
    scale = height / _REFERENCE_SIZE[1]
    left = (width - _REFERENCE_SIZE[0] * scale) / 2
    return round(left + x * scale), round(y * scale)


def _dismiss_restored_console(window: int, grabber: FrameGrabber, *, size: tuple[int, int]) -> None:
    """Saved console visibility must not divert scenario input into its prompt."""
    deadline = time.monotonic() + 3.0
    frame = grabber.grab(width=size[0], height=size[1])
    while (
        not startup_escape_safe(frame)
        or restore_dialog_visible(frame)
        or restore_browser_visible(frame)
    ):
        if time.monotonic() >= deadline:
            message = "GK3 did not present the restored room"
            raise CaptureError(message)
        frame = grabber.grab(width=size[0], height=size[1])
    if not developer_console_visible(frame):
        return
    press_chord(window, (_VK_CONTROL, _VK_SHIFT, _VK_OEM_3), hold_seconds=0.06)
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if not developer_console_visible(grabber.grab(width=size[0], height=size[1])):
            return
    message = "GK3's restored developer console did not close"
    raise CaptureError(message)


def _run_console_command(window: int, command: str) -> None:
    """Run one GK3 debug-console command and close the console overlay."""
    chord = (_VK_CONTROL, _VK_SHIFT, _VK_OEM_3)
    # The console's per-frame input buffer drops bulk submissions. Keep its
    # verified key cadence; page transitions elsewhere are readiness-driven.
    press_chord(window, chord, hold_seconds=0.1)
    time.sleep(0.45)
    # Enter executes without clearing GK3's prompt, and saves serialize it.
    # Escape clears the native input line (Ctrl+A is not supported), but also
    # releases its editor focus. Toggle off/on to focus the now-empty prompt.
    press_key(window, _VK_ESCAPE, hold_seconds=0.06)
    press_chord(window, chord, hold_seconds=0.08)
    press_chord(window, chord, hold_seconds=0.08)
    type_text(window, command, key_interval=0.02)
    press_key(window, _VK_RETURN, hold_seconds=0.08)
    time.sleep(0.65)
    press_chord(window, chord, hold_seconds=0.1)
