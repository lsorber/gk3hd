"""Only verified, fully activated owned children may start game code."""

from __future__ import annotations

import ctypes
import subprocess
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pytest

from gk3hd.vr import process

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Mock, Mock, dict[int, int]]:
    exe = tmp_path / "GK3-VR.exe"
    exe.write_bytes(b"verified player")
    program = Mock(
        image=Mock(to_bytes=lambda: b"verified player"),
        switches=tuple(range(8)),
        panel=Mock(pointing_hand_va=8),
        world=Mock(hand_va=9),
    )
    words = dict.fromkeys(program.switches, 0)
    words.update({8: 1, 9: 1})
    kernel = Mock()
    active = [True]

    def create(*args: object) -> int:
        info = ctypes.cast(cast("ctypes.c_void_p", args[-1]), ctypes.POINTER(process._ProcessInfo))
        info.contents.process = 0x1_0000_0101
        info.contents.thread = 0x1_0000_0102
        info.contents.pid = 123
        info.contents.tid = 456
        return 1

    def memory(_handle: int, address: int, pointer: object, size: int, count: object) -> int:
        value = ctypes.cast(cast("ctypes.c_void_p", pointer), ctypes.POINTER(ctypes.c_uint32))
        value.contents.value = words[address]
        ctypes.cast(
            cast("ctypes.c_void_p", count), ctypes.POINTER(ctypes.c_size_t)
        ).contents.value = size
        return 1

    def write(_handle: int, address: int, pointer: object, size: int, count: object) -> int:
        words[address] = ctypes.cast(
            cast("ctypes.c_void_p", pointer), ctypes.POINTER(ctypes.c_uint32)
        ).contents.value
        ctypes.cast(
            cast("ctypes.c_void_p", count), ctypes.POINTER(ctypes.c_size_t)
        ).contents.value = size
        return 1

    def terminate(_handle: int, _code: int) -> int:
        active[0] = False
        return 1

    def exit_code(_handle: int, pointer: object) -> int:
        ctypes.cast(
            cast("ctypes.c_void_p", pointer), ctypes.POINTER(ctypes.c_uint32)
        ).contents.value = 0
        return 1

    kernel.CreateProcessW.side_effect = create
    kernel.ReadProcessMemory.side_effect = memory
    kernel.WriteProcessMemory.side_effect = write
    kernel.ResumeThread.return_value = 1
    kernel.WaitForSingleObject.side_effect = lambda _handle, _time: 258 if active[0] else 0
    kernel.TerminateProcess.side_effect = terminate
    kernel.GetExitCodeProcess.side_effect = exit_code
    monkeypatch.setattr(process, "_kernel", lambda: kernel)
    monkeypatch.setattr(process, "_user", lambda: Mock(PostThreadMessageW=Mock(return_value=0)))
    monkeypatch.setattr(ctypes, "WinError", lambda _code: OSError("native failure"), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
    return exe, program, kernel, words


def test_activation_precedes_resume_and_disk_bytes_remain_dormant(
    child: tuple[Path, Mock, Mock, dict[int, int]],
) -> None:
    exe, program, kernel, words = child

    def resume(_thread: int) -> int:
        assert all(value == 1 for value in words.values())
        return 1

    kernel.ResumeThread.side_effect = resume
    with process.VRProcess(exe, program, environment={"PATH": "private"}) as owned:
        assert owned.pid == 123
        assert owned.poll() is None
        args = kernel.CreateProcessW.call_args.args
        assert args[0] == str(exe)
        assert (
            args[1][:]
            == subprocess.list2cmdline([str(exe), "-window", "-width", "1280", "-height", "800"])
            + "\0"
        )
        assert args[7] == str(exe.parent)
        assert args[4] == 0
        assert args[5] == 0x404
        assert "PATH=private\0\0" in args[6][:]
    assert exe.read_bytes() == b"verified player"
    assert kernel.TerminateProcess.call_args.args[0] == 0x1_0000_0101
    assert sorted(call.args[0] for call in kernel.CloseHandle.call_args_list) == [
        0x1_0000_0101,
        0x1_0000_0102,
    ]


@pytest.mark.parametrize("hand", list(process.PointingHand))
def test_pointing_preference_reaches_world_and_panels_before_resume(
    child: tuple[Path, Mock, Mock, dict[int, int]], hand: process.PointingHand
) -> None:
    exe, program, kernel, words = child

    def resume(_thread: int) -> int:
        expected = int(hand is process.PointingHand.RIGHT)
        assert words[program.panel.pointing_hand_va] == expected
        assert words[program.world.hand_va] == expected
        assert all(words[address] == 1 for address in program.switches)
        return 1

    kernel.ResumeThread.side_effect = resume
    with process.VRProcess(exe, program, environment={}, pointing_hand=hand):
        assert exe.read_bytes() == b"verified player"


@pytest.mark.parametrize("address", [8, 9])
def test_changed_pointer_defaults_block_all_activation_writes(
    child: tuple[Path, Mock, Mock, dict[int, int]], address: int
) -> None:
    exe, program, kernel, words = child
    words[address] = 0
    with pytest.raises(ValueError, match="dormant"):
        process.VRProcess(exe, program, environment={})
    kernel.WriteProcessMemory.assert_not_called()
    kernel.ResumeThread.assert_not_called()
    kernel.TerminateProcess.assert_called_once()


def test_unapplied_pointing_preference_never_resumes_game(
    child: tuple[Path, Mock, Mock, dict[int, int]],
) -> None:
    exe, program, kernel, _words = child
    original_write = kernel.WriteProcessMemory.side_effect

    def write(handle: int, address: int, pointer: object, size: int, count: object) -> int:
        if address == program.world.hand_va:
            ctypes.cast(
                cast("ctypes.c_void_p", count), ctypes.POINTER(ctypes.c_size_t)
            ).contents.value = size
            return 1
        return original_write(handle, address, pointer, size, count)

    kernel.WriteProcessMemory.side_effect = write
    with pytest.raises(ValueError, match="could not be verified"):
        process.VRProcess(exe, program, environment={}, pointing_hand=process.PointingHand.LEFT)
    kernel.ResumeThread.assert_not_called()
    kernel.TerminateProcess.assert_called_once()


def test_one_non_dormant_flag_blocks_every_write_and_resume(
    child: tuple[Path, Mock, Mock, dict[int, int]],
) -> None:
    exe, program, kernel, words = child
    words[7] = 1
    with pytest.raises(ValueError, match="dormant"):
        process.VRProcess(exe, program, environment={})
    kernel.WriteProcessMemory.assert_not_called()
    kernel.ResumeThread.assert_not_called()
    kernel.TerminateProcess.assert_called_once()
    assert kernel.CloseHandle.call_count == 2


@pytest.mark.parametrize("failure", ["read", "write", "resume", "cancel"])
def test_failed_activation_never_leaves_a_suspended_child(
    child: tuple[Path, Mock, Mock, dict[int, int]], failure: str
) -> None:
    exe, program, kernel, _words = child
    if failure == "read":
        kernel.ReadProcessMemory.side_effect = None
        kernel.ReadProcessMemory.return_value = 0
    elif failure == "write":
        kernel.WriteProcessMemory.side_effect = None
        kernel.WriteProcessMemory.return_value = 0
    elif failure == "resume":
        kernel.ResumeThread.return_value = 0
    else:
        kernel.WriteProcessMemory.side_effect = KeyboardInterrupt
    expected = (
        KeyboardInterrupt
        if failure == "cancel"
        else RuntimeError
        if failure == "resume"
        else OSError
    )
    with pytest.raises(expected):
        process.VRProcess(exe, program, environment={})
    kernel.TerminateProcess.assert_called_once()
    assert kernel.CloseHandle.call_count == 2
    if failure != "resume":
        kernel.ResumeThread.assert_not_called()


def test_process_creation_failure_has_no_child_to_release(
    child: tuple[Path, Mock, Mock, dict[int, int]],
) -> None:
    exe, program, kernel, _words = child
    kernel.CreateProcessW.side_effect = None
    kernel.CreateProcessW.return_value = 0
    with pytest.raises(OSError, match="native failure"):
        process.VRProcess(exe, program, environment={})
    kernel.TerminateProcess.assert_not_called()
    kernel.CloseHandle.assert_not_called()


def test_timeout_and_normal_exit_preserve_handle_ownership(
    child: tuple[Path, Mock, Mock, dict[int, int]],
) -> None:
    exe, program, kernel, _words = child
    with process.VRProcess(exe, program, environment={}) as owned:
        with pytest.raises(subprocess.TimeoutExpired):
            owned.wait(timeout=0.1)
        kernel.WaitForSingleObject.side_effect = None
        kernel.WaitForSingleObject.return_value = 0
        assert owned.wait(timeout=0.1) == 0
        assert owned.poll() == 0
    kernel.TerminateProcess.assert_not_called()
    assert kernel.CloseHandle.call_count == 2


def test_cancellation_allows_native_quit_without_force_termination(
    child: tuple[Path, Mock, Mock, dict[int, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    exe, program, kernel, _words = child
    user = Mock()

    def quit_game(thread: int, message: int, wparam: int, lparam: int) -> int:
        assert (thread, message, wparam, lparam) == (456, 0x12, 0, 0)
        kernel.WaitForSingleObject.side_effect = None
        kernel.WaitForSingleObject.return_value = 0
        return 1

    user.PostThreadMessageW.side_effect = quit_game
    monkeypatch.setattr(process, "_user", lambda: user)
    with pytest.raises(KeyboardInterrupt), process.VRProcess(exe, program, environment={}):
        raise KeyboardInterrupt
    kernel.TerminateProcess.assert_not_called()
    user.PostThreadMessageW.assert_called_once()
    assert kernel.CloseHandle.call_count == 2


@pytest.mark.parametrize("posted", [0, 1])
def test_unresponsive_or_missing_queue_still_releases_owned_child(
    child: tuple[Path, Mock, Mock, dict[int, int]],
    monkeypatch: pytest.MonkeyPatch,
    posted: int,
) -> None:
    exe, program, kernel, _words = child
    user = Mock(PostThreadMessageW=Mock(return_value=posted))
    monkeypatch.setattr(process, "_user", lambda: user)
    with process.VRProcess(exe, program, environment={}):
        pass
    user.PostThreadMessageW.assert_called_once_with(456, 0x12, 0, 0)
    kernel.TerminateProcess.assert_called_once_with(0x1_0000_0101, 1)
    assert kernel.CloseHandle.call_count == 2
    waits = [call.args[1] for call in kernel.WaitForSingleObject.call_args_list]
    assert (process._EXIT_GRACE_SECONDS * 1000 in waits) == bool(posted)


def test_failed_activation_never_posts_quit_to_a_suspended_thread(
    child: tuple[Path, Mock, Mock, dict[int, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    exe, program, kernel, words = child
    words[0] = 1
    user = Mock()
    monkeypatch.setattr(process, "_user", lambda: user)
    with pytest.raises(ValueError, match="dormant"):
        process.VRProcess(exe, program, environment={})
    user.PostThreadMessageW.assert_not_called()
    kernel.TerminateProcess.assert_called_once()


def test_finished_primary_thread_is_never_sent_a_quit_request(
    child: tuple[Path, Mock, Mock, dict[int, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    exe, program, kernel, _words = child
    user = Mock()
    monkeypatch.setattr(process, "_user", lambda: user)
    original_wait = kernel.WaitForSingleObject.side_effect
    kernel.WaitForSingleObject.side_effect = lambda handle, timeout: (
        0 if handle == 0x1_0000_0102 else original_wait(handle, timeout)
    )
    with process.VRProcess(exe, program, environment={}):
        pass
    user.PostThreadMessageW.assert_not_called()
    kernel.TerminateProcess.assert_called_once()


def test_failed_quit_request_still_uses_owned_handle_cleanup(
    child: tuple[Path, Mock, Mock, dict[int, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    exe, program, kernel, _words = child
    user = Mock(PostThreadMessageW=Mock(side_effect=OSError("queue unavailable")))
    monkeypatch.setattr(process, "_user", lambda: user)
    with process.VRProcess(exe, program, environment={}):
        pass
    kernel.TerminateProcess.assert_called_once_with(0x1_0000_0101, 1)
    assert kernel.CloseHandle.call_count == 2


def test_changed_executable_is_rejected_before_process_creation(
    child: tuple[Path, Mock, Mock, dict[int, int]],
) -> None:
    exe, program, kernel, _words = child
    exe.write_bytes(b"substituted")
    with pytest.raises(ValueError, match="verified isolated player"):
        process.VRProcess(exe, program, environment={})
    kernel.CreateProcessW.assert_not_called()


@pytest.mark.parametrize("values", [{"A": "x\0y"}, {"": "x"}, {"A=B": "x"}, {"a": "1", "A": "2"}])
def test_invalid_environment_is_rejected_before_process_creation(
    child: tuple[Path, Mock, Mock, dict[int, int]], values: dict[str, str]
) -> None:
    exe, program, kernel, _words = child
    with pytest.raises(ValueError, match="environment"):
        process.VRProcess(exe, program, environment=values)
    kernel.CreateProcessW.assert_not_called()


def test_status_read_failure_does_not_skip_child_termination(
    child: tuple[Path, Mock, Mock, dict[int, int]],
) -> None:
    exe, program, kernel, _words = child
    owned = process.VRProcess(exe, program, environment={})
    wait = kernel.WaitForSingleObject.side_effect
    calls = [0]

    def transient_failure(handle: int, milliseconds: int) -> int:
        calls[0] += 1
        return 0xFFFFFFFF if calls[0] == 1 else wait(handle, milliseconds)

    kernel.WaitForSingleObject.side_effect = transient_failure
    owned.close()
    kernel.TerminateProcess.assert_called_once()
    assert owned.poll() == 0


def test_cleanup_does_not_replace_primary_cancellation(
    child: tuple[Path, Mock, Mock, dict[int, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    exe, program, _kernel, _words = child
    owned = process.VRProcess(exe, program, environment={})
    close = owned.close
    monkeypatch.setattr(owned, "close", Mock(side_effect=OSError("cleanup failure")))
    try:
        with pytest.raises(KeyboardInterrupt) as caught, owned:
            raise KeyboardInterrupt
        assert any("cleanup failure" in note for note in caught.value.__notes__)
    finally:
        close()


@pytest.mark.parametrize("bridge", ["world", "interface", "completion"])
@pytest.mark.parametrize("enabled", [0, 1])
@pytest.mark.parametrize("status", [0, 1, 0x80004005])
def test_only_disabled_failed_render_adapters_are_terminal(
    child: tuple[Path, Mock, Mock, dict[int, int]], bridge: str, enabled: int, status: int
) -> None:
    exe, program, _kernel, words = child
    program.scene = Mock(enabled_va=10, result_va=11)
    program.panel.enabled_va = 12
    program.panel.result_va = 13
    program.panel.completion_result_va = 14
    words.update({10: 1, 11: 0, 12: 1, 13: 0, 14: 0})
    words[10 if bridge == "world" else 12] = enabled
    words[{"world": 11, "interface": 13, "completion": 14}[bridge]] = status
    with process.VRProcess(exe, program, environment={}) as owned:
        failure = owned.render_failure(program)
        if enabled == 0 and status & 0x80000000:
            assert failure is not None
            assert "0x80004005" in failure
        else:
            assert failure is None


def test_unreadable_render_status_during_teardown_is_not_a_confirmed_failure(
    child: tuple[Path, Mock, Mock, dict[int, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    exe, program, _kernel, _words = child
    with process.VRProcess(exe, program, environment={}) as owned:
        monkeypatch.setattr(owned, "_read", Mock(side_effect=OSError("teardown memory gone")))
        assert owned.render_failure(program) is None
        assert owned.poll() is None
