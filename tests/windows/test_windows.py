"""Safety checks at the Windows capture boundary; no live game required."""

import ctypes
from pathlib import Path
from unittest.mock import Mock

import pytest

from gk3hd.system.locking import ExclusiveFileLock, LockError
from tests.visual.support import windows


@pytest.mark.parametrize("name", ["C_PLAYACTION", "C_WAIT", "C_POINT", "C_" + "X" * 30, "BAD"])
@pytest.mark.parametrize("invalid", [None, "pointer", "table", "handle", "resource", "words"])
def test_cursor_resource_is_bounded_and_transient_state_is_unknown(
    monkeypatch: pytest.MonkeyPatch, name: str, invalid: str | None
) -> None:
    encoded = name.encode().ljust(32, b"\0")
    memory: dict[int, tuple[int, ...] | None] = {
        0x6FF838: (0x1000,),
        0x1444: (0x2000,),
        0x2044: (0x3000,),
        0x3008: (0x4000,),
        0x4070: (0x5000,),
        0x5020: (0xABCD0002,),  # The handle's high word is not its table index.
        0x70B0D4: (0x6000,),
        0x6120: (0x7000, 3),
        0x7008: (0x8000,),
        0x8008: tuple(int.from_bytes(encoded[i : i + 4], "little") for i in range(0, 32, 4)),
    }
    if invalid:
        address, value = {
            "pointer": (0x3008, (0,)),
            "table": (0x6120, (0, 3)),
            "handle": (0x6120, (0x7000, 2)),
            "resource": (0x7008, None),
            "words": (0x8008, None),
        }[invalid]
        memory[address] = value

    def read(_pid: int, address: int, *, count: int) -> tuple[int, ...] | None:
        value = memory.get(address)
        assert value is None or len(value) == count
        return value

    monkeypatch.setattr(windows, "read_process_words", read)
    expected = name if invalid is None and name in {"C_PLAYACTION", "C_WAIT", "C_POINT"} else None
    assert windows.current_cursor_resource(42) == expected


@pytest.mark.parametrize(
    "invalid", [None, "null", "unreadable", "location", "time", "text", "layer"]
)
@pytest.mark.parametrize("card_time", [None, 0, 15, 18, -1])
def test_scene_identity_uses_native_tables_and_rejects_partial_state(
    monkeypatch: pytest.MonkeyPatch, invalid: str | None, card_time: int | None
) -> None:
    memory: dict[int, tuple[int, ...] | None] = {
        0x6FF838: (0x1000,),
        0x1444: (0x2000,),
        0x2060: (0x3000,),
        0x3010: (5, 7),
        0x6F5F24 + 5 * 4: (0x4000,),
        0x6F5E94 + 7 * 4: (0x5000,),
        0x4000: (int.from_bytes(b"TE4\0", "little"), 0),
        0x5000: (int.from_bytes(b"309P", "little"), 0),
        0x6000: (0x67DF90 if card_time is not None else 0x123456,),
        0x63CC: None if card_time == -1 else (card_time or 0,),
        0x6F5E94 + 15 * 4: (0x7000,),
        0x7000: (int.from_bytes(b"303P", "little"), 0),
    }
    if invalid == "null":
        memory[0x2060] = (0,)
    elif invalid == "unreadable":
        memory[0x3010] = None
    elif invalid == "location":
        memory[0x3010] = (84, 7)
    elif invalid == "time":
        memory[0x3010] = (5, 18)
    elif invalid == "text":
        memory[0x4000] = (int.from_bytes(b"TE4X", "little"), 0)
    elif invalid == "layer":
        memory[0x6000] = None

    def read(_pid: int, address: int, *, count: int) -> tuple[int, ...] | None:
        words = memory[address]
        assert words is None or len(words) == count
        return words

    monkeypatch.setattr(windows, "read_process_words", read)
    monkeypatch.setattr(windows, "current_ui_layer_pointer", lambda _pid: 0x6000)
    valid = invalid is None or (invalid == "time" and card_time == 15)
    expected = ("te4", "303p" if card_time == 15 else "309p")
    assert windows.current_scene_identity(42) == (
        expected if valid and card_time in (None, 15) else None
    )


@pytest.mark.parametrize(
    ("key", "mapped", "expected"),
    [
        (0x25, 0x4B, 0xE04B),
        (0x25, 0xE04B, 0xE04B),
        (0x23, 0x4F, 0xE04F),
        (0xA3, 0xE01D, 0xE01D),
        (0x41, 0x1E, 0x1E),
        (0x64, 0x4B, 0x4B),
        (0x25, 0, 0),
    ],
)
def test_scan_mapping_distinguishes_navigation_from_numpad(
    key: int, mapped: int, expected: int
) -> None:
    api = Mock()
    api.MapVirtualKeyW.return_value = mapped
    assert windows._mapped_scan_code(api, key) == expected
    api.MapVirtualKeyW.assert_called_once_with(key, 4)


@pytest.mark.parametrize("up", [False, True])
def test_navigation_fallback_preserves_extended_identity(*, up: bool) -> None:
    api = Mock()
    api.MapVirtualKeyW.return_value = 0x4B
    api.SendInput.return_value = 0
    windows._send_key_edge(api, 0x25, up=up)
    event = api.SendInput.call_args.args[1]._obj.payload.keyboard
    assert event.scan_code == 0x4B
    assert event.flags == 0x0009 | (0x0002 if up else 0)
    api.keybd_event.assert_called_once_with(0x25, 0x4B, 0x0001 | (0x0002 if up else 0), 0)


def test_posted_navigation_key_includes_extended_message_bit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = Mock()
    api.MapVirtualKeyW.return_value = 0x4B
    monkeypatch.setattr(windows, "_user32", Mock(return_value=api))
    monkeypatch.setattr(windows.time, "sleep", Mock())
    windows.post_key(123, 0x25)
    down = 1 | (0x4B << 16) | (1 << 24)
    assert api.PostMessageW.call_args_list[0].args == (123, 0x100, 0x25, down)
    assert api.PostMessageW.call_args_list[1].args == (123, 0x101, 0x25, down | 0xC0000000)


@pytest.mark.parametrize("process_result", [False, True])
def test_capture_uses_per_monitor_coordinates_even_if_process_policy_is_fixed(
    monkeypatch: pytest.MonkeyPatch, *, process_result: bool
) -> None:
    """A process-level policy refusal must not retain DPI-virtualized input."""
    api = Mock()
    api.SetProcessDpiAwarenessContext.return_value = process_result
    api.SetThreadDpiAwarenessContext.return_value = 1
    monkeypatch.setattr(windows.sys, "platform", "win32")
    monkeypatch.setattr(windows.ctypes, "WinDLL", Mock(return_value=api), raising=False)
    windows.make_dpi_aware()
    context = ctypes.c_void_p(-4).value
    assert api.SetProcessDpiAwarenessContext.call_args.args[0].value == context
    assert api.SetThreadDpiAwarenessContext.call_args.args[0].value == context


def test_capture_rejects_failed_thread_dpi_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Do not silently send clicks in the wrong coordinate system."""
    api = Mock()
    api.SetThreadDpiAwarenessContext.return_value = None
    monkeypatch.setattr(windows.sys, "platform", "win32")
    monkeypatch.setattr(windows.ctypes, "WinDLL", Mock(return_value=api), raising=False)
    with pytest.raises(windows.CaptureError, match="per-monitor DPI awareness"):
        windows.make_dpi_aware()


@pytest.mark.parametrize("running", [False, True])
def test_capture_session_owns_the_lock_and_releases_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, running: bool
) -> None:
    """A refusal or failed experiment cannot strand the shared transaction lock."""
    path = tmp_path / "game.lock"
    monkeypatch.setattr(windows, "executable_lock_path", Mock(return_value=path))
    monkeypatch.setattr(windows, "is_gk3_running", Mock(return_value=running))
    if running:
        with (
            pytest.raises(windows.CaptureError, match="close GK3"),
            windows.capture_session(tmp_path / "GK3.exe"),
        ):
            pytest.fail("must not touch a live game")
    else:

        def fail_capture() -> None:
            with windows.capture_session(tmp_path / "GK3.exe"):
                with pytest.raises(LockError), ExclusiveFileLock(path):
                    pytest.fail("another capture must not overlap")
                message = "failed experiment"
                raise RuntimeError(message)

        with pytest.raises(RuntimeError, match="failed experiment"):
            fail_capture()
    with ExclusiveFileLock(path):
        pass


def test_capture_session_does_not_probe_when_an_installer_owns_the_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exclusion happens before reading mutable engine state."""
    path = tmp_path / "game.lock"
    monkeypatch.setattr(windows, "executable_lock_path", Mock(return_value=path))
    probe = Mock()
    monkeypatch.setattr(windows, "is_gk3_running", probe)
    with (
        ExclusiveFileLock(path),
        pytest.raises(LockError),
        windows.capture_session(tmp_path / "GK3.exe"),
    ):
        pytest.fail("capture must not start")
    probe.assert_not_called()
