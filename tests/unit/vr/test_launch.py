"""VR launching owns its child and fails explicitly instead of falling back."""

from __future__ import annotations

import os
from contextlib import nullcontext
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, Mock

import pytest

from gk3hd.vr import launch
from gk3hd.vr.runtime import RuntimeSelection, RuntimeUnavailableError
from gk3hd.vr.status import TRACKING_FILE, TrackingStatus

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Mock:
    logs = tmp_path / "logs"
    logs.mkdir()
    target = Mock(game_dir=tmp_path, exe=tmp_path / "GK3.exe")
    runtime = RuntimeSelection(tmp_path / "runtime.json", tmp_path / "runtime.dll")
    child = MagicMock()
    child.__enter__.return_value = child
    child.poll.side_effect = [None, 0]
    child.wait.return_value = 0
    child.has_submitted_frames.return_value = True
    child.render_failure.return_value = None
    service = Mock()
    factory = Mock(return_value=child)
    clock = [0.0]

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    monkeypatch.setattr(launch, "discover_game", lambda **_kwargs: target)
    monkeypatch.setattr(launch, "ExclusiveFileLock", lambda _path: nullcontext())
    monkeypatch.setattr(launch, "is_gk3_running", lambda: False)
    monkeypatch.setattr(launch, "VRService", lambda: service)
    monkeypatch.setattr(launch, "selected_runtime", lambda **_kwargs: runtime)
    monkeypatch.setattr(launch, "_logs", lambda _path: logs)
    monkeypatch.setattr(launch, "VRProcess", factory)
    monkeypatch.setattr(launch.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(launch.time, "sleep", sleep)
    return Mock(
        target=target, runtime=runtime, child=child, service=service, factory=factory, logs=logs
    )


def test_successful_session_requires_frames_and_clean_exit(setup: Mock) -> None:
    assert launch.launch(game_dir=setup.target.game_dir) == 0
    setup.service.verify.assert_called_once_with(game_dir=setup.target.game_dir)
    assert setup.factory.call_args.args[0] == setup.target.game_dir / "GK3-VR.exe"
    assert setup.factory.call_args.args[1] is setup.service.verify.return_value
    assert setup.factory.call_args.kwargs["pointing_hand"] is launch.PointingHand.RIGHT
    setup.child.__exit__.assert_called_once_with(None, None, None)


def test_left_hand_preference_is_forwarded_to_owned_child(setup: Mock) -> None:
    assert launch.launch(pointing_hand=launch.PointingHand.LEFT) == 0
    assert setup.factory.call_args.kwargs["pointing_hand"] is launch.PointingHand.LEFT


def test_runtime_death_stops_blocked_owned_player(
    setup: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = MagicMock()
    guard.__enter__.return_value = guard
    guard.check.side_effect = RuntimeUnavailableError("SteamVR stopped; restart SteamVR")
    monkeypatch.setattr(launch, "RuntimeWatch", Mock(return_value=guard))
    with pytest.raises(RuntimeUnavailableError, match="restart SteamVR"):
        launch.launch()
    assert setup.child.__exit__.call_args.args[0] is RuntimeUnavailableError
    assert guard.__exit__.call_args.args[0] is RuntimeUnavailableError


@pytest.mark.parametrize("stage", ["running", "verification", "runtime"])
def test_preflight_failure_never_creates_child(
    setup: Mock, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    if stage == "running":
        monkeypatch.setattr(launch, "is_gk3_running", lambda: True)
    elif stage == "verification":
        setup.service.verify.side_effect = RuntimeError("invalid player")
    else:
        monkeypatch.setattr(
            launch, "selected_runtime", Mock(side_effect=RuntimeUnavailableError("missing runtime"))
        )
    with pytest.raises(RuntimeError):
        launch.launch()
    setup.factory.assert_not_called()


def test_runtime_bootstrap_failure_closes_only_owned_child(setup: Mock) -> None:
    (setup.logs / "GK3-VR_ddraw.log").write_text(
        "error: GK3HD OpenXR initialization: headset unavailable\n", encoding="utf-8"
    )
    with pytest.raises(RuntimeUnavailableError, match="headset unavailable"):
        launch.launch()
    assert setup.child.__exit__.call_args.args[0] is RuntimeUnavailableError


def test_registered_runtime_without_submitted_frames_times_out(setup: Mock) -> None:
    setup.child.poll.side_effect = None
    setup.child.poll.return_value = None
    setup.child.has_submitted_frames.return_value = False
    with pytest.raises(RuntimeUnavailableError, match="no VR frames submitted") as caught:
        launch.launch()
    assert str(setup.logs) in str(caught.value)
    assert "relaunch" in str(caught.value)
    assert setup.child.__exit__.call_args.args[0] is RuntimeUnavailableError


@pytest.mark.parametrize(("code", "frames"), [(0, False), (1, True), (3221225781, False)])
def test_early_or_failed_exit_is_not_success(setup: Mock, code: int, frames: bool) -> None:
    setup.child.has_submitted_frames.return_value = frames
    setup.child.wait.return_value = code
    with pytest.raises(RuntimeUnavailableError, match=f"exited with code {code}"):
        launch.launch()
    setup.child.__exit__.assert_called_once()


def test_cancellation_and_frame_read_failures_release_owned_child(setup: Mock) -> None:
    setup.child.has_submitted_frames.side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        launch.launch()
    assert setup.child.__exit__.call_args.args[0] is KeyboardInterrupt


def test_child_settings_are_isolated_and_discard_stale_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (
        "XR_RUNTIME_JSON",
        "GK3HD_XR_TEST_CAPTURE",
        "GK3HD_XR_TEST_INPUT_MAPPING",
        "DXVK_CONFIG_FILE",
        "D7VK_LOG_PATH",
        "__COMPAT_LAYER",
    ):
        monkeypatch.setenv(name, "stale")
    monkeypatch.setenv("PATH", "keep this")
    before = dict(os.environ)
    runtime = RuntimeSelection(tmp_path / "runtime.json", tmp_path / "runtime.dll")
    values = launch.child_environment(tmp_path, runtime, logs=tmp_path / "logs")
    assert dict(os.environ) == before
    assert values["PATH"] == "keep this"
    assert values["XR_RUNTIME_JSON"] == str(runtime.manifest)
    assert values["GK3HD_XR_PROTOTYPE"] == "1"
    assert values["GK3HD_XR_TRACKING_STATUS"] == str(tmp_path / "logs" / TRACKING_FILE)
    assert values["DXVK_CONFIG_FILE"] == str(tmp_path / "gk3hd/vr/player/dxvk.conf")
    assert "stale" not in values.values()
    assert "GK3HD_XR_TEST_CAPTURE" not in values
    assert "GK3HD_XR_TEST_INPUT_MAPPING" not in values


def test_each_launch_gets_a_separate_log_directory(tmp_path: Path) -> None:
    first = launch._logs(tmp_path)
    second = launch._logs(tmp_path)
    assert first != second
    assert first.parent == second.parent == tmp_path / "gk3hd/vr/logs"


def test_unrelated_log_lines_are_not_initialization_failures(tmp_path: Path) -> None:
    assert launch._runtime_error(tmp_path) is None
    (tmp_path / "GK3-VR_ddraw.log").write_text("info: Vulkan initialized\n", encoding="utf-8")
    assert launch._runtime_error(tmp_path) is None


def test_terminal_runtime_loss_after_successful_start_stops_owned_player(setup: Mock) -> None:
    setup.child.poll.side_effect = [None, None]
    original = setup.child.has_submitted_frames

    def submitted(_program: object) -> bool:
        (setup.logs / "GK3-VR_ddraw.log").write_text(
            "error: XR scene bridge: GK3HD OpenXR session ended: runtime requested exit\n",
            encoding="utf-8",
        )
        return True

    original.side_effect = submitted
    with pytest.raises(RuntimeUnavailableError, match="launch VR again"):
        launch.launch()
    setup.child.__exit__.assert_called_once()
    assert setup.child.__exit__.call_args.args[0] is RuntimeUnavailableError


def test_temporary_hidden_or_stopping_state_is_not_a_terminal_error(setup: Mock) -> None:
    (setup.logs / "GK3-VR_ddraw.log").write_text(
        "info: XR_SESSION_STATE_STOPPING\ninfo: XR_SESSION_STATE_VISIBLE\n",
        encoding="utf-8",
    )
    assert launch.launch() == 0


@pytest.mark.parametrize(
    "failure",
    [
        "GK3HD: XR scene bridge: engine eye draw failed",
        "GK3HD: XR panel bridge: image upload failed",
        "GK3HD: XR frame bridge: invalid frame transaction",
        "GK3HD: unknown XR scene bridge failure",
        "GK3HD: unknown XR panel bridge failure",
        "GK3HD: unknown XR frame bridge failure",
        "GK3HD: XR native interface has no render target",
        "GK3HD: XR native interface upload failed: 80004005",
    ],
)
def test_render_failure_after_start_stops_owned_player_with_relaunch_guidance(
    setup: Mock, failure: str
) -> None:
    setup.child.poll.side_effect = [None, None]

    def submitted(_program: object) -> bool:
        (setup.logs / "GK3-VR_ddraw.log").write_text(f"err:  {failure}\n", encoding="utf-8")
        return True

    setup.child.has_submitted_frames.side_effect = submitted
    with pytest.raises(RuntimeUnavailableError, match=r"VR rendering failed:.*Unsaved progress"):
        launch.launch()
    assert setup.child.__exit__.call_args.args[0] is RuntimeUnavailableError
    setup.child.__exit__.assert_called_once()


@pytest.mark.parametrize("level", ["info", "warn"])
def test_non_error_renderer_diagnostics_do_not_stop_play(setup: Mock, level: str) -> None:
    (setup.logs / "GK3-VR_ddraw.log").write_text(
        f"{level}: GK3HD: XR scene bridge: diagnostic only\n", encoding="utf-8"
    )
    assert launch.launch() == 0


def test_failed_render_bridge_stops_player_even_without_a_flushed_log(setup: Mock) -> None:
    setup.child.render_failure.return_value = "world rendering disabled after HRESULT 0x80004005"
    with pytest.raises(RuntimeUnavailableError, match=r"VR rendering failed:.*0x80004005"):
        launch.launch()
    assert setup.child.__exit__.call_args.args[0] is RuntimeUnavailableError
    setup.child.has_submitted_frames.assert_not_called()


def test_terminal_log_at_zero_exit_is_not_healthy_quit(setup: Mock) -> None:
    def exited(*, timeout: float) -> int:
        assert timeout == 0
        (setup.logs / "GK3-VR_ddraw.log").write_text(
            "error: GK3HD OpenXR session ended: headset connection lost\n", encoding="utf-8"
        )
        return 0

    setup.child.wait.side_effect = exited
    with pytest.raises(RuntimeUnavailableError, match="headset connection lost"):
        launch.launch()
    assert setup.child.__exit__.call_args.args[0] is RuntimeUnavailableError


def test_tracking_feedback_does_not_stop_the_session(
    setup: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = setup.logs / TRACKING_FILE
    path.write_bytes(b"untracked\n")
    events: list[TrackingStatus] = []
    setup.child.poll.side_effect = [None] * 70 + [0]
    sleep = launch.time.sleep

    def recover(seconds: float) -> None:
        sleep(seconds)
        if launch.time.monotonic() >= 1.25:
            path.write_bytes(b"untracked\ntracked\n")

    monkeypatch.setattr(launch.time, "sleep", recover)
    assert launch.launch(on_tracking=events.append) == 0
    assert events == [TrackingStatus.UNAVAILABLE, TrackingStatus.AVAILABLE]
    setup.child.__exit__.assert_called_once_with(None, None, None)
