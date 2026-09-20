"""Windows orchestration for interaction-heavy visual scenarios."""

from pathlib import Path
from unittest.mock import MagicMock, Mock, call

import pytest
from PIL import Image, ImageDraw

from tests.visual.support import special
from tests.visual.support.catalog import SuiteSize, scenes
from tests.visual.support.saves import SaveGame
from tests.visual.support.special import SPECIAL_SCENES, _authored_point


@pytest.mark.parametrize("fails", [False, True])
def test_special_capture_scopes_quality_inside_ownership_and_restores_on_failure(
    monkeypatch: pytest.MonkeyPatch, fails: bool
) -> None:
    target = Mock(exe=Path("game/GK3.exe"))
    monkeypatch.setattr(special, "discover_game", Mock(return_value=target))
    monkeypatch.setattr(special, "make_dpi_aware", Mock())
    events = Mock()
    ownership, quality = MagicMock(), MagicMock()
    events.attach_mock(ownership, "ownership")
    events.attach_mock(quality, "quality")
    runner = Mock(side_effect=RuntimeError("capture failed") if fails else None)
    events.attach_mock(runner, "run")
    monkeypatch.setattr(special, "capture_session", Mock(return_value=ownership))
    monkeypatch.setattr(special, "_temporary_reference_quality", Mock(return_value=quality))
    monkeypatch.setattr(special, "_run_capture", runner)
    if fails:
        with pytest.raises(RuntimeError, match="capture failed"):
            special.capture(game_dir=None, resolution="3840x2160", resume=None)
    else:
        special.capture(game_dir=None, resolution="3840x2160", resume=None)
    assert [entry[0] for entry in events.mock_calls] == [
        "ownership.__enter__",
        "quality.__enter__",
        "run",
        "quality.__exit__",
        "ownership.__exit__",
    ]
    runner.assert_called_once_with(target, current_size=(3840, 2160), resume=None, selected=None)


def test_special_scene_names_are_unique() -> None:
    """Every output owns one stable animation basename."""
    names = [scene.name for scene in SPECIAL_SCENES]
    assert len(names) == len(set(names))


def test_catalog_interfaces_all_have_capture_recipes() -> None:
    names = tuple(scene.name for scene in scenes(SuiteSize.LARGE) if scene.kind == "special")
    assert tuple(scene.name for scene in special._selected_scenes(names)) == names


@pytest.mark.parametrize("names", [(), ("not-a-scene",)])
def test_unknown_or_empty_special_selection_is_rejected(names: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="invalid special-scene selection"):
        special._selected_scenes(names)


def test_inventory_selection_does_not_visit_settings_or_museum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, room = Mock(), Mock()
    monkeypatch.setattr(special, "_capture_inventory_scenes", inventory)
    monkeypatch.setattr(special, "_capture_system_scenes", Mock(side_effect=AssertionError))
    monkeypatch.setattr(special, "_capture_requested_room_scenes", room)
    special._capture_interaction_sequences(
        1, process_id=2, size=(1024, 768), record=Mock(), selected=frozenset({"inventory"})
    )
    inventory.assert_called_once()
    # The room dispatcher receives the selection and therefore performs no
    # native interactions for an inventory-only request.
    assert room.call_args.kwargs["selected"] == frozenset({"inventory"})


def test_layout_readiness_waits_for_changed_and_stable_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before, after = ((1, 0, 0, 10, 10),), ((1, 0, 0, 10, 20),)
    reads = Mock(side_effect=[before, after, after])
    monkeypatch.setattr(special, "_visible_ui_rectangles", reads)
    monkeypatch.setattr(special.time, "sleep", Mock())
    special._wait_for_ui_layout_change(1, before)
    assert reads.call_count == 3


@pytest.mark.parametrize("size", [(1024, 768), (3840, 2160)])
def test_driving_hover_requires_location_art_not_just_cursor(size: tuple[int, int]) -> None:
    idle = Image.new("RGB", size, "gray")
    current = idle.copy()
    draw = ImageDraw.Draw(current)
    point = (350, 228)
    region = (309, 190, 392, 266)
    draw.rectangle(
        (*_authored_point(size, 350, 228), *_authored_point(size, 370, 248)), fill="white"
    )
    # Neither the cursor nor changes at a different destination prove this hover.
    draw.rectangle(
        (*_authored_point(size, 800, 280), *_authored_point(size, 850, 320)), fill="white"
    )
    assert not special._driving_hover_changed(idle, current, point, region)
    draw.rectangle(
        (*_authored_point(size, 315, 195), *_authored_point(size, 335, 210)), fill="white"
    )
    assert not special._driving_hover_changed(idle, current, point, region)
    draw.rectangle(
        (*_authored_point(size, 350, 252), *_authored_point(size, 450, 268)), fill="white"
    )
    assert special._driving_hover_changed(idle, current, point, region)


def test_driving_hover_advances_immediately_when_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = Image.new("RGB", (1024, 768))
    grab = Mock(return_value=frame)
    sleep = Mock()
    monkeypatch.setattr(special.time, "sleep", sleep)
    monkeypatch.setattr(special, "_driving_hover_changed", Mock(return_value=True))
    monkeypatch.setattr(special, "green_indicator_visible", Mock(return_value=True))
    assert (
        special._wait_for_driving_hover(
            grab, idle=frame, point=(350, 228), region=(309, 190, 392, 266)
        )
        is frame
    )
    grab.assert_called_once_with()
    sleep.assert_not_called()


def test_driving_tooltip_cannot_substitute_for_a_location_highlight() -> None:
    idle = Image.new("RGB", (1024, 768), "gray")
    current = idle.copy()
    ImageDraw.Draw(current).rectangle((830, 337, 918, 353), fill="white")
    assert not special._driving_hover_changed(idle, current, (830, 313), (779, 278, 874, 356))


def test_driving_capture_waits_for_the_visible_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = Image.new("RGB", (1024, 768))
    grab = Mock(return_value=frame)
    monkeypatch.setattr(special, "_driving_hover_changed", Mock(return_value=True))
    monkeypatch.setattr(special, "green_indicator_visible", Mock(side_effect=[False, True]))
    monkeypatch.setattr(special.time, "sleep", Mock())
    assert (
        special._wait_for_driving_hover(
            grab, idle=frame, point=(350, 228), region=(309, 190, 392, 266)
        )
        is frame
    )
    assert grab.call_count == 2


def test_driving_hover_times_out_without_highlight(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = Image.new("RGB", (1024, 768))
    monkeypatch.setattr(special.time, "monotonic", Mock(side_effect=[0.0, 3.0]))
    with pytest.raises(special.CaptureError, match="did not highlight"):
        special._wait_for_driving_hover(
            Mock(return_value=frame), idle=frame, point=(350, 228), region=(309, 190, 392, 266)
        )


def test_restore_regression_repeats_loading_and_moves_the_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "click_frame_point",
        "press_key",
        "_wait_for_layer",
        "_wait_until_layer_changes",
        "_wait_for_toolbar",
    ):
        monkeypatch.setattr(special, name, Mock())
    monkeypatch.setattr(
        special,
        "current_ui_layer_vtable",
        Mock(side_effect=[special._ROOM_LAYER_VTABLE, special._CONFIRM_QUIT_VTABLE]),
    )
    move = Mock()
    monkeypatch.setattr(special, "move_frame_point", move)
    record = Mock()
    restore = Mock()
    special._capture_restore_cycles(
        1, process_id=2, size=(1024, 768), record=record, restore=restore
    )
    assert restore.call_count == 2
    assert record.call_args_list == [
        call("play-quit-yes"),
        call("play-quit-no"),
        call("restore-browser"),
        call("restore-toolbar-first"),
        call("restore-browser-second"),
        call("restore-toolbar-second"),
        call("restore-return-room"),
        call("restore-quit-yes"),
        call("restore-quit-no"),
    ]
    assert [invocation.args[1:] for invocation in move.call_args_list] == [
        (516, 421),
        (673, 421),
        (516, 421),
        (673, 421),
    ]


def test_fixture_reuses_only_the_expected_native_recipe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cached fixtures bypass startup without looking through player save slots."""
    fixture_path = tmp_path / "gk3hd/comparisons/fixtures/interaction.gk3"
    fixture_path.parent.mkdir(parents=True)
    fixture_path.touch()
    fixture = SaveGame(fixture_path, special._FIXTURE_DESCRIPTION, "r25", "110a")
    monkeypatch.setattr(special, "read_save_game", Mock(return_value=fixture))
    start = Mock()
    monkeypatch.setattr(special, "launch", start)
    context = special._CaptureContext(
        executable=tmp_path / "GK3.exe",
        game_dir=tmp_path,
        ini_path=tmp_path / "GK3.ini",
        ini_bytes=None,
        use_wgc=True,
    )
    assert special._ensure_interaction_fixture(context, size=(1024, 768)) == fixture
    start.assert_not_called()


def test_fixture_rejects_an_unrelated_save(monkeypatch: pytest.MonkeyPatch) -> None:
    """A plausible native header is not enough to silently select another scene."""
    path = Path("interaction.gk3")
    monkeypatch.setattr(
        special, "read_save_game", Mock(return_value=SaveGame(path, "Player save", "r25", "110a"))
    )
    with pytest.raises(special.CaptureError, match="unexpected visual fixture"):
        special._validate_interaction_fixture(path)


def test_fixture_creation_uses_play_and_one_inventory_recipe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Generate locally via the native console and always release the game session."""
    context = special._CaptureContext(
        executable=tmp_path / "GK3.exe",
        game_dir=tmp_path,
        ini_path=tmp_path / "GK3.ini",
        ini_bytes=None,
        use_wgc=True,
    )
    process, grabber = Mock(pid=123), Mock()
    monkeypatch.setattr(special, "launch", Mock(return_value=process))
    monkeypatch.setattr(special, "wait_for_window", Mock(return_value=1))
    monkeypatch.setattr(special, "FrameGrabber", Mock(return_value=grabber))
    monkeypatch.setattr(special, "_wait_for_title", Mock(return_value=(1, grabber)))
    monkeypatch.setattr(special, "_grab_frame", Mock(return_value=(1, grabber, Mock())))
    monkeypatch.setattr(special, "title_play_center", Mock(return_value=(400, 700)))
    for name in ("click_frame_point", "_wait_for_layer", "press_key"):
        monkeypatch.setattr(special, name, Mock())
    stop = Mock()
    monkeypatch.setattr(special, "stop", stop)
    path = tmp_path / "build/visual/fixtures/interaction.gk3"
    monkeypatch.setattr(special, "_interaction_fixture_path", Mock(return_value=path))

    def run_command(_window: int, command: str) -> None:
        if command.startswith("SaveGameBinary"):
            path.touch()

    commands = Mock(side_effect=run_command)
    monkeypatch.setattr(special, "_run_console_command", commands)
    fixture = SaveGame(path, special._FIXTURE_DESCRIPTION, "r25", "110a")
    monkeypatch.setattr(special, "read_save_game", Mock(return_value=fixture))
    assert special._ensure_interaction_fixture(context, size=(1024, 768)) == fixture
    assert len(commands.call_args_list) == 2
    recipe = commands.call_args_list[0].args[1]
    assert recipe.count("EgoTakeInvItem") == len(special._FIXTURE_ITEMS)
    assert '"GOLD_COAT"' in recipe
    assert path.as_posix() in commands.call_args_list[1].args[1]
    grabber.close.assert_called_once()
    stop.assert_called_once_with(process, 1)


def test_authored_points_fit_centered_reference_canvas() -> None:
    """Reference coordinates scale uniformly and remain horizontally centered."""
    assert _authored_point((1024, 768), 101, 125) == (101, 125)
    assert _authored_point((3840, 2160), 101, 125) == (764, 352)


def test_inventory_sequence_selects_the_correct_verbs(monkeypatch: pytest.MonkeyPatch) -> None:
    """The notepad has a Use verb; the coat does not, so Select changes index."""
    for name in (
        "click_frame_point",
        "held_click_frame_point",
        "move_frame_point",
        "press_key",
        "_wait_for_layer",
        "_wait_until_layer_changes",
        "_wait_for_action_menu_closed",
    ):
        monkeypatch.setattr(special, name, Mock())
    sleep = Mock()
    monkeypatch.setattr(special.time, "sleep", sleep)
    menu = Mock(return_value=(1, 2))
    monkeypatch.setattr(special, "_wait_for_action_menu", menu)
    events = Mock()
    monkeypatch.setattr(special, "_wait_for_action_menu_closed", events.closed)
    special._capture_inventory_scenes(1, process_id=2, size=(1024, 768), record=events.record)
    assert [invocation.kwargs["button_index"] for invocation in menu.call_args_list] == [0, 2, 1]
    for label in ("inventory-after-selection", "inventory-after-mosely-clothes-selection"):
        position = events.mock_calls.index(call.record(label))
        assert events.mock_calls[position - 1] == call.closed(2, timeout=3.0)
    sleep.assert_not_called()


@pytest.mark.parametrize("scale", [1, 3])
def test_action_menu_uses_live_button_rectangles(
    monkeypatch: pytest.MonkeyPatch,
    scale: int,
) -> None:
    """Native and patched menus need no guessed coordinates or patch telemetry."""
    memory = {
        (0x104C, 2): (0x2000, 1),
        (0x2000, 1): (0x3000,),
        (0x3000, 7): (special._ACTION_MENU_VTABLE, 0, 0, 0, 0, 0, 1),
        (0x304C, 2): (0x4000, 3),
        (0x4000, 3): (0x7000, 0x5000, 0x6000),
    }
    for index, pointer in enumerate((0x5000, 0x6000, 0x7000)):
        memory[pointer + 0x1C, 4] = tuple(
            value * scale for value in (440 + index * 32, 113, 472 + index * 32, 145)
        )
    monkeypatch.setattr(special, "current_ui_layer_pointer", Mock(return_value=0x1000))
    monkeypatch.setattr(
        special,
        "read_process_words",
        Mock(side_effect=lambda _pid, va, *, count: memory.get((va, count))),
    )

    assert special._action_menu_button_center(1, 2) == (520 * scale, 129 * scale)


def test_action_menu_wait_requires_stable_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Construction coordinates must settle before the harness clicks a verb."""
    positions = Mock(side_effect=[None, (1, 2), (3, 4), (3, 4)])
    monkeypatch.setattr(special, "_action_menu_button_center", positions)
    monkeypatch.setattr(special.time, "sleep", Mock())

    assert special._wait_for_action_menu(1, button_index=0, timeout=1) == (3, 4)
    assert positions.call_count == 4


def test_action_menu_handles_retired_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The UI layer may disappear between two asynchronous observations."""
    monkeypatch.setattr(special, "current_ui_layer_pointer", Mock(return_value=None))
    assert special._action_menu_button_center(1, 0) is None


def test_selection_capture_waits_for_the_visible_menu_to_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(special, "current_ui_layer_pointer", Mock(return_value=0x1000))
    monkeypatch.setattr(special, "_ui_children", Mock(return_value=(0x2000,)))
    header = (special._ACTION_MENU_VTABLE, 0, 0, 0, 0, 0)
    reads = Mock(
        side_effect=[
            (special._INVENTORY_VTABLE,),
            (*header, 1),
            (special._INVENTORY_VTABLE,),
            (*header, 0),
        ],
    )
    monkeypatch.setattr(special, "read_process_words", reads)
    sleep = Mock()
    monkeypatch.setattr(special.time, "sleep", sleep)

    special._wait_for_action_menu_closed(1, timeout=1)

    assert reads.call_count == 4
    sleep.assert_called_once_with(0.02)


def test_selection_capture_does_not_accept_unreadable_or_departed_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(special, "current_ui_layer_pointer", Mock(return_value=None))
    monkeypatch.setattr(special.time, "monotonic", Mock(side_effect=[0, 0, 2]))
    monkeypatch.setattr(special.time, "sleep", Mock())
    with pytest.raises(special.CaptureError, match="did not dismiss"):
        special._wait_for_action_menu_closed(1, timeout=1)


def test_system_sequence_opens_museum_without_a_second_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The panel shares the existing room session and waits for its own layer."""
    for name in (
        "click_frame_point",
        "move_frame_point",
        "press_key",
        "_wait_for_layer",
        "_wait_until_layer_changes",
        "_wait_for_toolbar",
    ):
        monkeypatch.setattr(special, name, Mock())
    sleep = Mock()
    monkeypatch.setattr(special.time, "sleep", sleep)
    console_command = Mock()
    monkeypatch.setattr(special, "_run_console_command", console_command)
    record = Mock()

    special._capture_system_scenes(1, process_id=2, size=(1024, 768), record=record)

    assert console_command.call_args_list == [
        call(1, 'InventoryInspect("MS3I_PANEL1");'),
        call(1, "ShowBinocs();"),
        call(1, 'ShowFingerprintInterface("MIRROR");'),
    ]
    assert record.call_args_list.count(call("museum-closeup")) == 1
    sleep.assert_not_called()


def test_toolbar_waits_for_a_visible_stable_child(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(special, "current_ui_layer_pointer", Mock(return_value=0x1000))
    monkeypatch.setattr(special, "_ui_children", Mock(return_value=(0x2000,)))
    header = (special._TOOLBAR_VTABLE, 0, 0, 0, 0, 0)
    memory = Mock(side_effect=[(*header, 0), (*header, 1), (*header, 1)])
    monkeypatch.setattr(special, "read_process_words", memory)
    monkeypatch.setattr(special.time, "sleep", Mock())

    special._wait_for_toolbar(1)

    assert memory.call_count == 3


def test_restored_console_waits_for_a_room_then_closes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A black first capture must not authorize inventory input into a saved console."""
    room = Image.new("RGB", (1024, 768), (80, 100, 120))
    prompt = room.copy()
    ImageDraw.Draw(prompt).rectangle((48, 36, 660, 84), fill=(107, 4, 140))
    grabber = Mock()
    grabber.grab.side_effect = [Image.new("RGB", room.size), prompt, prompt, room]
    chord = Mock()
    monkeypatch.setattr(special, "press_chord", chord)

    special._dismiss_restored_console(1, grabber, size=room.size)

    chord.assert_called_once_with(1, (0x11, 0x10, 0xC0), hold_seconds=0.06)
    assert grabber.grab.call_count == 4


def test_restored_room_does_not_toggle_a_closed_console(monkeypatch: pytest.MonkeyPatch) -> None:
    """Readiness returns immediately without opening an already closed console."""
    room = Image.new("RGB", (1024, 768), (80, 100, 120))
    grabber = Mock()
    grabber.grab.return_value = room
    chord = Mock()
    monkeypatch.setattr(special, "press_chord", chord)

    special._dismiss_restored_console(1, grabber, size=room.size)

    chord.assert_not_called()
    grabber.grab.assert_called_once()


def test_console_command_clears_serialized_input_before_typing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restored SaveGameBinary prompt must never prefix a new scene command."""
    events = Mock()
    for name in ("press_chord", "press_key", "type_text"):
        monkeypatch.setattr(special, name, getattr(events, name))
    monkeypatch.setattr(special.time, "sleep", Mock())

    special._run_console_command(1, "ShowDrivingInterface();")

    assert events.mock_calls == [
        call.press_chord(1, (0x11, 0x10, 0xC0), hold_seconds=0.1),
        call.press_key(1, 0x1B, hold_seconds=0.06),
        call.press_chord(1, (0x11, 0x10, 0xC0), hold_seconds=0.08),
        call.press_chord(1, (0x11, 0x10, 0xC0), hold_seconds=0.08),
        call.type_text(1, "ShowDrivingInterface();", key_interval=0.02),
        call.press_key(1, 0x0D, hold_seconds=0.08),
        call.press_chord(1, (0x11, 0x10, 0xC0), hold_seconds=0.1),
    ]
