"""Windows camera-scenario orchestration with mocked game input."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from tests.visual.support import scenario
from tests.visual.support.catalog import Scene


@pytest.mark.parametrize(
    "layer", [scenario._STARTUP_SPLASH_LAYER_VTABLE, scenario._TIMEBLOCK_LAYER_VTABLE]
)
def test_scene_capture_skips_transition_then_intro_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, layer: int
) -> None:
    process = Mock(pid=123)
    process.poll.return_value = None
    grabber = Mock()
    monkeypatch.setattr(scenario, "_launch_restored_save", Mock(return_value=(process, 1, grabber)))
    monkeypatch.setattr(scenario, "_dismiss_restored_console", Mock())
    command = Mock()
    monkeypatch.setattr(scenario, "_run_console_command", command)
    monkeypatch.setattr(scenario, "current_cursor_resource", Mock(return_value="C_POINT"))
    monkeypatch.setattr(
        scenario,
        "current_scene_identity",
        Mock(side_effect=[("r25", "110a"), ("cs2", "212p"), ("cs2", "212p")]),
    )
    monkeypatch.setattr(
        scenario,
        "current_ui_layer_vtable",
        Mock(side_effect=[layer, *([scenario._ROOM_LAYER_VTABLE] * 4)]),
    )
    monkeypatch.setattr(scenario.time, "sleep", Mock())
    key = Mock()
    monkeypatch.setattr(scenario, "press_key", key)
    monkeypatch.setattr(scenario, "FrameGrabber", Mock(return_value=grabber))
    frame = Image.new("RGB", (16, 12), "blue")
    monkeypatch.setattr(scenario, "_grab_frame", Mock(return_value=(1, grabber, frame)))
    stop = Mock()
    monkeypatch.setattr(scenario, "stop", stop)
    path = tmp_path / "scene.png"
    scenario._capture_scene(Mock(), Scene("CS2", "212p", "room", "DESK"), "camera;", path, (16, 12))
    assert key.call_count == 2  # Transition, then the room's scripted intro.
    assert command.call_args_list[0].args[1] == 'SetLocationTime("CS2","212p");'
    assert command.call_args_list[1].args[1] == "camera;"
    assert path.is_file()
    assert path.with_suffix(".json").is_file()
    stop.assert_called_once_with(process, 1)


def test_small_centered_movie_does_not_count_as_world_capture() -> None:
    frame = Image.new("RGB", (3840, 2160), "black")
    frame.paste("white", (1600, 840, 2240, 1320))
    assert not scenario._room_frame_visible(frame)
    assert scenario._room_frame_visible(Image.new("RGB", (3840, 2160), "blue"))
    assert scenario._room_frame_visible(Image.new("RGB", (1024, 768), (2, 2, 2)))
    assert not scenario._room_frame_visible(Image.new("RGB", (1024, 768), "black"))


def test_failed_readiness_saves_evidence_and_still_stops_the_owned_game(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = Mock(pid=123)
    grabber = Mock()
    grabber.grab.return_value = Image.new("RGB", (16, 12), (2, 2, 2))
    monkeypatch.setattr(scenario, "_launch_restored_save", Mock(return_value=(process, 1, grabber)))
    monkeypatch.setattr(scenario, "_dismiss_restored_console", Mock())
    monkeypatch.setattr(scenario, "_run_console_command", Mock())
    monkeypatch.setattr(scenario, "current_scene_identity", Mock(return_value=("te4", "309p")))
    monkeypatch.setattr(
        scenario, "current_ui_layer_vtable", Mock(return_value=scenario._ROOM_LAYER_VTABLE)
    )
    monkeypatch.setattr(scenario, "current_cursor_resource", Mock(return_value="C_ZOOM"))
    monkeypatch.setattr(scenario, "press_key", Mock())
    monkeypatch.setattr(
        scenario, "_wait_for_visible_room", Mock(side_effect=scenario.CaptureError("not ready"))
    )
    stop = Mock()
    monkeypatch.setattr(scenario, "stop", stop)
    path = tmp_path / "scene.png"
    with pytest.raises(scenario.CaptureError, match="not ready"):
        scenario._capture_scene(
            Mock(), Scene("TE4", "309p", "inspect", "WORDS"), "camera;", path, (16, 12)
        )
    report = json.loads((tmp_path / "scene-failure.json").read_bytes())
    assert report["actual"] == ["te4", "309p"]
    assert report["cursor"] == "C_ZOOM"
    assert report["error"] == "not ready"
    assert (tmp_path / "scene-failure.png").is_file()
    assert not path.is_file()
    grabber.close.assert_called_once()
    stop.assert_called_once_with(process, 1)


@pytest.mark.parametrize("cursor", [None, "C_WAIT", "C_PLAYACTION", "C_POINT"])
@pytest.mark.parametrize("room", [False, True])
def test_visible_room_is_not_ready_while_a_script_owns_input(
    monkeypatch: pytest.MonkeyPatch, cursor: str | None, room: bool
) -> None:
    monkeypatch.setattr(scenario, "current_cursor_resource", Mock(return_value=cursor))
    monkeypatch.setattr(
        scenario,
        "current_ui_layer_vtable",
        Mock(
            return_value=scenario._ROOM_LAYER_VTABLE if room else scenario._TIMEBLOCK_LAYER_VTABLE
        ),
    )
    assert scenario._room_ready(1, Image.new("RGB", (16, 12), "blue")) == (
        room and cursor == "C_POINT"
    )


def test_intro_is_skipped_only_until_busy_cursor_releases_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = Image.new("RGB", (16, 12), "blue")
    grabber = Mock()
    monkeypatch.setattr(scenario, "_grab_frame", Mock(return_value=(1, grabber, frame)))
    monkeypatch.setattr(
        scenario, "current_ui_layer_vtable", Mock(return_value=scenario._ROOM_LAYER_VTABLE)
    )
    monkeypatch.setattr(
        scenario, "current_cursor_resource", Mock(side_effect=["C_PLAYACTION", "C_WAIT", "C_POINT"])
    )
    monkeypatch.setattr(
        scenario.time, "monotonic", Mock(side_effect=[0, 0, 0.2, 0.2, 0.2, 0.3, 0.3])
    )
    monkeypatch.setattr(scenario.time, "sleep", Mock())
    key = Mock()
    monkeypatch.setattr(scenario, "press_key", key)
    assert scenario._wait_for_visible_room(Mock(pid=123), 1, grabber, (16, 12)) == (1, grabber)
    key.assert_called_once_with(1, 0x1B, hold_seconds=0.03)


def test_resume_allows_nested_expansion_but_not_changed_inputs() -> None:
    previous = {"fixture": "same", "cameras": {"first": "camera1"}, "size": [3840, 2160]}
    expanded = {
        "fixture": "same",
        "cameras": {"first": "camera1", "second": "camera2"},
        "size": (3840, 2160),
    }
    assert scenario._compatible_inputs(previous, expanded)
    assert not scenario._compatible_inputs(previous, {**expanded, "fixture": "changed"})
    assert not scenario._compatible_inputs(previous, {**expanded, "cameras": {"first": "other"}})


def test_capture_inputs_track_renderer_and_texture_changes(tmp_path: Path) -> None:
    (tmp_path / "ddraw.dll").write_bytes(b"renderer")
    state = tmp_path / ".gk3hd-textures.json"
    state.write_bytes(b"old-pack")
    before = scenario._capture_asset_hashes(tmp_path, b"ini")
    state.write_bytes(b"new-pack")
    after = scenario._capture_asset_hashes(tmp_path, b"ini")
    assert before["ddraw.dll"] == after["ddraw.dll"]
    assert before[".gk3hd-textures.json"] != after[".gk3hd-textures.json"]
    assert before["ini"] == after["ini"]
