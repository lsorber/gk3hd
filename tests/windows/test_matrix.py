"""Windows capture orchestration; no game is launched by these unit tests."""

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from tests.visual.support import matrix
from tests.visual.support.matrix import _isolated_save, _save_scene_changed
from tests.visual.support.saves import SaveGame


@pytest.mark.parametrize("use_wgc", [False, True])
def test_reference_restores_do_not_reuse_stale_gdi_surfaces(
    monkeypatch: pytest.MonkeyPatch, use_wgc: bool
) -> None:
    state, request, restarted = Mock(), Mock(), Mock()
    request.context.use_wgc = use_wgc
    request.context.game_dir = Path("game")
    restart = Mock(return_value=restarted)
    quick = Mock(return_value=123)
    stop = Mock()
    monkeypatch.setattr(matrix, "_restart_at_save", restart)
    monkeypatch.setattr(matrix, "_quick_load", quick)
    monkeypatch.setattr(matrix, "stop", stop)
    monkeypatch.setattr(matrix, "atomic_write", Mock())
    result = matrix._quick_load_or_restart(state, request)
    if use_wgc:
        quick.assert_called_once()
        restart.assert_not_called()
        stop.assert_not_called()
        assert result.process is state.process
    else:
        quick.assert_not_called()
        state.grabber.close.assert_called_once()
        stop.assert_called_once_with(state.process, state.window)
        restart.assert_called_once_with(request)
        assert result is restarted


@pytest.mark.parametrize(("index", "ready"), [(0, False), (1, False), (12, True), (13, False)])
def test_timeblock_capture_waits_for_the_last_reveal_frame(
    monkeypatch: pytest.MonkeyPatch, index: int, ready: bool
) -> None:
    monkeypatch.setattr(matrix, "current_ui_layer_vtable", Mock(return_value=0x67DF90))
    monkeypatch.setattr(matrix, "current_ui_layer_pointer", Mock(return_value=0x1000))
    sequence = (0x666AC4, *([0] * 8), 0x3000, 0x3034)
    reads = Mock(side_effect=[(0x2000, 0, 0, index), sequence])
    monkeypatch.setattr(matrix, "read_process_words", reads)
    assert matrix._timeblock_reveal_complete(42) is ready
    assert reads.call_args_list[0].args == (42, 0x12D4)


def test_room_capture_does_not_wait_for_a_timeblock_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(matrix, "current_ui_layer_vtable", Mock(return_value=0x67A248))
    reads = Mock()
    monkeypatch.setattr(matrix, "read_process_words", reads)
    assert matrix._timeblock_reveal_complete(42)
    reads.assert_not_called()


def test_timeblock_completion_acquires_a_new_presented_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = Mock()
    old, fresh = Mock(), Mock()
    monkeypatch.setattr(matrix, "_frame_blocks_capture", Mock(return_value=False))
    monkeypatch.setattr(matrix, "_timeblock_reveal_complete", Mock(return_value=True))
    monkeypatch.setattr(matrix, "_scene_identity_matches", Mock(return_value=True))
    monkeypatch.setattr(matrix, "current_ui_layer_vtable", Mock(return_value=0x67DF90))
    grab = Mock(return_value=(state.window, state.grabber, fresh))
    monkeypatch.setattr(matrix, "_grab_frame", grab)
    _, _, captured = matrix._wait_for_scene_transition(
        state, previous=None, current=matrix._SceneFrame(Mock(), old)
    )
    assert captured is fresh
    grab.assert_called_once()


@pytest.mark.parametrize("actual", [None, ("te3", "309p"), ("te4", "312p"), ("te4", "309p")])
def test_scene_identity_requires_both_requested_identifiers(
    monkeypatch: pytest.MonkeyPatch, actual: tuple[str, str] | None
) -> None:
    monkeypatch.setattr(matrix, "current_scene_identity", Mock(return_value=actual))
    save = SaveGame(Path("save0084.gk3"), "Statue", "TE4", "309P")
    assert matrix._scene_identity_matches(42, save) == (actual == ("te4", "309p"))


@pytest.mark.parametrize("changes_during_capture", [False, True])
def test_animated_old_room_cannot_pass_save_capture(
    monkeypatch: pytest.MonkeyPatch, changes_during_capture: bool
) -> None:
    state = Mock()
    old, changed, fresh = Mock(), Mock(), Mock()
    # Image comparisons see substantial change throughout, but the first
    # image belongs to the previous location. Only game identity can reject it.
    monkeypatch.setattr(matrix, "_frame_blocks_capture", Mock(return_value=False))
    monkeypatch.setattr(matrix, "_timeblock_reveal_complete", Mock(return_value=True))
    matches = Mock(side_effect=[False, True, not changes_during_capture])
    monkeypatch.setattr(matrix, "_scene_identity_matches", matches)
    monkeypatch.setattr(matrix.time, "sleep", Mock())
    grab = Mock(side_effect=[(1, state.grabber, changed), (1, state.grabber, fresh)])
    monkeypatch.setattr(matrix, "_grab_frame", grab)
    current = matrix._SceneFrame(SaveGame(Path("save0084.gk3"), "Statue", "te4", "309p"), old)
    if changes_during_capture:
        with pytest.raises(matrix.CaptureError, match="scene changed"):
            matrix._wait_for_scene_transition(state, previous=None, current=current)
    else:
        assert matrix._wait_for_scene_transition(state, previous=None, current=current)[2] is fresh
    assert grab.call_count == 2
    assert matches.call_count == 3


@pytest.mark.parametrize("blocker", ["restore_dialog_visible", "restore_browser_visible"])
def test_resume_and_scene_validation_reject_restore_ui(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, blocker: str
) -> None:
    frame = Image.new("RGB", (1024, 768), "blue")
    path = tmp_path / "save.png"
    frame.save(path)
    monkeypatch.setattr(matrix, "restore_dialog_visible", Mock(return_value=False))
    monkeypatch.setattr(matrix, "restore_browser_visible", Mock(return_value=False))
    assert matrix._capture_is_valid(path, (1024, 768))
    monkeypatch.setattr(matrix, blocker, Mock(return_value=True))
    assert not matrix._capture_is_valid(path, (1024, 768))
    assert matrix._frame_blocks_capture(None, Mock(), frame)


def test_resume_rejects_black_loading_frame(tmp_path: Path) -> None:
    path = tmp_path / "black.png"
    Image.new("RGB", (1024, 768), "black").save(path)
    assert not matrix._capture_is_valid(path, (1024, 768))


@pytest.mark.parametrize("retry_succeeds", [False, True])
def test_restarted_save_must_pass_scene_validation_too(
    monkeypatch: pytest.MonkeyPatch, retry_succeeds: bool
) -> None:
    state, restarted = Mock(), Mock()
    request = Mock(first=True)
    frame = Mock()
    monkeypatch.setattr(
        matrix, "_grab_settled_frame", Mock(side_effect=[(state, frame), (restarted, frame)])
    )
    result = (2, restarted.grabber, frame)
    waits = Mock(
        side_effect=[
            matrix.CaptureError("stale"),
            result if retry_succeeds else matrix.CaptureError("still stale"),
        ]
    )
    monkeypatch.setattr(matrix, "_wait_for_scene_transition", waits)
    monkeypatch.setattr(matrix, "_restart_at_save", Mock(return_value=restarted))
    stop = Mock()
    monkeypatch.setattr(matrix, "stop", stop)
    if retry_succeeds:
        actual, image = matrix._capture_save_frame(state, request)
        assert actual.process is restarted.process
        assert actual.window == 2
        assert image is frame
        restarted.grabber.close.assert_not_called()
    else:
        with pytest.raises(matrix.CaptureError, match="still stale"):
            matrix._capture_save_frame(state, request)
        restarted.grabber.close.assert_called_once()
        stop.assert_any_call(restarted.process, restarted.window)
    assert waits.call_count == 2
    assert waits.call_args.kwargs["previous"] is None
    state.grabber.close.assert_called_once()


@pytest.mark.parametrize("during_capture", [False, True])
def test_frame_rejects_modal_error_without_capture_retry(
    monkeypatch: pytest.MonkeyPatch, during_capture: bool
) -> None:
    process = Mock(pid=123)
    grabber = Mock()
    error = "Unrecognized fatal exception"
    dialogs = [None, error] if during_capture else [error]
    monkeypatch.setattr(matrix, "process_error_dialog", Mock(side_effect=dialogs))
    reacquire = Mock()
    monkeypatch.setattr(matrix, "wait_for_window", reacquire)

    with pytest.raises(matrix.CaptureError, match=error):
        matrix._grab_frame(process, window=1, grabber=grabber, size=(1024, 768))

    assert grabber.grab.call_count == int(during_capture)
    reacquire.assert_not_called()


def test_frame_accepts_healthy_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    process = Mock(pid=123)
    grabber = Mock()
    dialogs = Mock(return_value=None)
    monkeypatch.setattr(matrix, "process_error_dialog", dialogs)

    assert matrix._grab_frame(process, window=1, grabber=grabber, size=(1024, 768)) == (
        1,
        grabber,
        grabber.grab.return_value,
    )
    assert dialogs.call_count == 2


def test_startup_skips_splash_but_not_the_earlier_loading_layer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = Mock()
    process.poll.return_value = None
    grabber = Mock(uses_wgc=False)
    frame = Mock()
    monkeypatch.setattr(matrix, "_grab_frame", Mock(return_value=(1, grabber, frame)))
    monkeypatch.setattr(
        matrix,
        "current_ui_layer_vtable",
        Mock(side_effect=[0x0067B87C, 0x0067B87C, 0x0067E550, 0x0069238C]),
    )
    monkeypatch.setattr(matrix, "title_ready", Mock(return_value=True))
    monkeypatch.setattr(matrix, "startup_escape_safe", Mock(return_value=False))
    monkeypatch.setattr(matrix.time, "sleep", Mock())
    key = Mock()
    monkeypatch.setattr(matrix, "press_key", key)

    assert matrix._wait_for_title(
        process, window=1, grabber=grabber, size=(1024, 768), failure_output=tmp_path / "failed.png"
    ) == (1, grabber)
    key.assert_called_once_with(1, 0x1B, hold_seconds=0.03)


def test_title_opens_restore_with_detected_button_without_shortcut_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = Mock()
    grabber = Mock(uses_wgc=False)
    frame = Mock()
    monkeypatch.setattr(matrix, "_grab_frame", Mock(return_value=(1, grabber, frame)))
    monkeypatch.setattr(matrix, "title_restore_center", Mock(return_value=(620, 700)))
    monkeypatch.setattr(
        matrix,
        "current_ui_layer_vtable",
        Mock(side_effect=[matrix._TITLE_LAYER_VTABLE, matrix._RESTORE_LAYER_VTABLE]),
    )
    monkeypatch.setattr(matrix, "_wait_for_layer_departure", Mock())
    monkeypatch.setattr(matrix, "wait_for_window", Mock(return_value=1))
    monkeypatch.setattr(matrix, "restore_browser_visible", Mock(return_value=True))
    click = Mock()
    key = Mock()
    monkeypatch.setattr(matrix, "click_frame_point", click)
    monkeypatch.setattr(matrix, "post_key", key)

    assert matrix._open_restore(
        process, window=1, grabber=grabber, size=(1024, 768), failure_output=tmp_path / "failed.png"
    ) == (1, grabber, frame)
    click.assert_called_once_with(1, 620, 700, frame_size=(1024, 768))
    key.assert_not_called()


@pytest.mark.parametrize("previous_config", [None, b"presentation policy"])
def test_reference_keeps_renderer_and_cleans_only_owned_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, previous_config: bytes | None
) -> None:
    installed = tmp_path / "GK3.exe"
    installed.write_bytes(b"installed")
    installed.with_name("GK3.exe.bak").write_bytes(b"original")
    proxy = tmp_path / "ddraw.dll"
    proxy.write_bytes(b"renderer")
    config = tmp_path / "dxvk.conf"
    if previous_config is not None:
        config.write_bytes(previous_config)
    service = Mock()
    service.prepare.return_value = Mock(output=b"reference")
    monkeypatch.setattr(matrix, "PatchService", Mock(return_value=service))
    history = Mock(return_value=b"reference")
    monkeypatch.setattr(matrix, "renderer_compatibility", history)
    alignment = Mock(return_value=b"reference")
    monkeypatch.setattr(matrix, "aligned_map_reference", alignment)
    compatibility = Mock(return_value=nullcontext())
    monkeypatch.setattr(matrix, "_temporary_appcompat", compatibility)

    def fail_capture() -> None:
        with matrix._reference_executable(installed) as reference:
            assert reference.read_bytes() == b"reference"
            history.assert_called_once_with(b"reference", service.prepare.return_value.profile)
            alignment.assert_called_once_with(b"reference", service.prepare.return_value.profile)
            assert "maximize_graphics_quality" not in service.prepare.call_args.args[0].patches
            assert config.read_bytes().startswith(previous_config or b"")
            assert b"[gk3hd-visual-reference.exe]" in config.read_bytes()
            assert b"ddraw.forceLegacyPresent = True" in config.read_bytes()
            assert proxy.read_bytes() == b"renderer"
            assert service.prepare.call_args.args[0].backend == "d7vk"
            compatibility.assert_called_once_with(
                reference, graphics_backend=matrix.GraphicsBackend.D7VK
            )
            message = "capture failed"
            raise RuntimeError(message)

    with pytest.raises(RuntimeError, match="capture failed"):
        fail_capture()

    assert proxy.read_bytes() == b"renderer"
    assert (config.read_bytes() if config.exists() else None) == previous_config
    assert installed.read_bytes() == b"installed"
    assert not (tmp_path / "gk3hd-visual-reference.exe").exists()


def test_reference_refuses_preexisting_helper_files(tmp_path: Path) -> None:
    installed = tmp_path / "GK3.exe"
    installed.with_name("GK3.exe.bak").write_bytes(b"original")
    occupied = tmp_path / "gk3hd-visual-reference.exe"
    occupied.write_bytes(b"not owned")

    with (
        pytest.raises(matrix.CaptureError, match="already exists"),
        matrix._reference_executable(installed),
    ):
        pytest.fail("must not enter an unowned reference session")

    assert occupied.read_bytes() == b"not owned"


def test_original_quality_disables_anisotropy_and_restores_it_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = Mock(REG_DWORD=4)
    registry.CreateKey.return_value = nullcontext("key")
    registry.QueryValueEx.return_value = (16, 4)
    monkeypatch.setattr(matrix, "winreg", registry)

    def failed_capture() -> None:
        with matrix._temporary_reference_quality(original=True):
            writes = {call.args[1]: call.args[-1] for call in registry.SetValueEx.call_args_list}
            assert writes["Max Anisotropy Level"] == 1
            assert writes["Lod"] == 100
            assert writes["Gamma"] == "1.000000"
            message = "capture failed"
            raise RuntimeError(message)

    with pytest.raises(RuntimeError, match="capture failed"):
        failed_capture()
    writes = [
        call.args[-1]
        for call in registry.SetValueEx.call_args_list
        if call.args[1] == "Max Anisotropy Level"
    ]
    assert writes == [1, 16]


@pytest.mark.parametrize("previous", [None, "~ HIGHDPIAWARE"])
def test_reference_uses_rgb565_and_restores_appcompat_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, previous: str | None
) -> None:
    registry = Mock(REG_SZ=1)
    registry.CreateKey.return_value = nullcontext("key")
    if previous is None:
        registry.QueryValueEx.side_effect = FileNotFoundError
    else:
        registry.QueryValueEx.return_value = previous, 1
    monkeypatch.setattr(matrix, "winreg", registry)
    exe = tmp_path / "reference.exe"

    def fail_capture() -> None:
        with matrix._temporary_appcompat(exe, graphics_backend=matrix.GraphicsBackend.D7VK):
            policy = registry.SetValueEx.call_args.args[-1]
            assert "16BITCOLOR" in policy.split()
            assert "DWM8And16BitMitigation" in policy.split()
            assert policy.split().count("HIGHDPIAWARE") == 1
            message = "capture failed"
            raise RuntimeError(message)

    with pytest.raises(RuntimeError, match="capture failed"):
        fail_capture()
    if previous is None:
        registry.DeleteValue.assert_called_once_with("key", str(exe.resolve()))
    else:
        registry.SetValueEx.assert_called_with("key", str(exe.resolve()), 0, 1, previous)


def test_save_isolation_preserves_original_when_staging_creation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed setup must never run deletion against the player's save slot."""
    original = tmp_path / "save0001.gk3"
    original.write_bytes(b"player progress")
    source = tmp_path / "fixture.bin"
    source.write_bytes(b"fixture")

    def denied_mkdir(_path: Path) -> None:
        raise PermissionError

    monkeypatch.setattr(Path, "mkdir", denied_mkdir)
    with pytest.raises(PermissionError), _isolated_save(tmp_path, source):
        pytest.fail("capture must not start without owning staging")
    assert original.read_bytes() == b"player progress"


def test_save_isolation_restores_original_after_capture_failure(tmp_path: Path) -> None:
    """All staged saves survive a failed game experiment byte-for-byte."""
    original = tmp_path / "save0001.gk3"
    original.write_bytes(b"player progress")
    source = tmp_path / "fixture.bin"
    source.write_bytes(b"fixture")

    def failed_capture() -> None:
        with _isolated_save(tmp_path, source):
            assert original.read_bytes() == b"fixture"
            raise RuntimeError

    with pytest.raises(RuntimeError):
        failed_capture()
    assert original.read_bytes() == b"player progress"
    assert not (tmp_path / ".gk3hd-visual-save-staging").exists()


@pytest.mark.parametrize("existing_quick_save", [False, True])
def test_save_isolation_restores_or_removes_its_quick_load_slot(
    tmp_path: Path, *, existing_quick_save: bool
) -> None:
    source = tmp_path / "fixture.bin"
    source.write_bytes(b"fixture")
    quick_save = tmp_path / "fastsave.gk3"
    if existing_quick_save:
        quick_save.write_bytes(b"player quick save")
    with _isolated_save(tmp_path, source):
        assert quick_save.read_bytes() == b"fixture"
        quick_save.write_bytes(b"another fixture")
    if existing_quick_save:
        assert quick_save.read_bytes() == b"player quick save"
    else:
        assert not quick_save.exists()


def _save(name: str, *, room: str, timeblock: str) -> SaveGame:
    return SaveGame(Path(name), name, room, timeblock)


def test_scene_identity_includes_the_save_slot() -> None:
    room = _save("room.gk3", room="r25", timeblock="210a")

    assert not _save_scene_changed(room, room)
    assert _save_scene_changed(
        room,
        _save("same-scene.gk3", room="r25", timeblock="210a"),
    )
    assert _save_scene_changed(
        room,
        _save("new-room.gk3", room="hal", timeblock="210a"),
    )
    assert _save_scene_changed(
        room,
        _save("new-timeblock.gk3", room="r25", timeblock="212p"),
    )


def test_same_room_save_rejects_the_previous_camera_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _save("save0025.gk3", room="cd1", timeblock="207a")
    second = _save("save0026.gk3", room="cd1", timeblock="207a")
    frame = Image.new("RGB", (1024, 768), "blue")
    monkeypatch.setattr(matrix, "restore_dialog_visible", Mock(return_value=False))
    monkeypatch.setattr(matrix, "restore_browser_visible", Mock(return_value=False))
    previous = matrix._SceneFrame(first, frame)
    assert matrix._frame_blocks_capture(previous, second, frame)
    assert not matrix._frame_blocks_capture(None, second, frame)
    assert not matrix._frame_blocks_capture(previous, second, Image.new("RGB", frame.size, "red"))
