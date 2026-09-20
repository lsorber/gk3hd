"""Process safety checks without a real game or Windows host."""

import ctypes
from ctypes import wintypes
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from gk3hd.patch.install import windows


def _process_api(
    monkeypatch: pytest.MonkeyPatch, names: tuple[str, ...], *, error: int = 18
) -> Mock:
    """Model one snapshot and its documented end-of-enumeration result."""
    remaining = iter(names)

    def next_process(_snapshot: int, pointer: object) -> bool:
        name = next(remaining, None)
        if name is None:
            return False
        # Use the declared ABI to emulate the native output parameter.
        entry = ctypes.cast(
            cast("ctypes.c_void_p", pointer), kernel.Process32FirstW.argtypes[1]
        ).contents
        entry.szExeFile = name
        return True

    kernel = Mock()
    kernel.CreateToolhelp32Snapshot.return_value = 0x1_0000_0123
    kernel.Process32FirstW.side_effect = next_process
    kernel.Process32NextW.side_effect = next_process
    monkeypatch.setattr(windows, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(ctypes, "WinDLL", Mock(return_value=kernel), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: error, raising=False)
    return kernel


@pytest.mark.parametrize("name", ["GK3.exe", "gk3.EXE", "gk3hd-visual-reference.exe"])
def test_both_game_identities_block_changes(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    kernel = _process_api(monkeypatch, ("unrelated.exe", name))
    assert windows.is_gk3_running()
    kernel.CloseHandle.assert_called_once_with(0x1_0000_0123)
    assert kernel.CreateToolhelp32Snapshot.restype is wintypes.HANDLE
    assert kernel.Process32FirstW.argtypes[0] is wintypes.HANDLE


@pytest.mark.parametrize("names", [(), ("unrelated.exe",), ("GK3.exe.backup",)])
def test_completed_enumeration_allows_changes(
    monkeypatch: pytest.MonkeyPatch, names: tuple[str, ...]
) -> None:
    kernel = _process_api(monkeypatch, names)
    assert not windows.is_gk3_running()
    kernel.CloseHandle.assert_called_once()


def test_snapshot_failure_never_authorizes_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = _process_api(monkeypatch, (), error=5)
    kernel.CreateToolhelp32Snapshot.return_value = ctypes.c_void_p(-1).value
    with pytest.raises(windows.ConfigurationError, match="cannot inspect"):
        windows.is_gk3_running()
    kernel.CloseHandle.assert_not_called()


@pytest.mark.parametrize("names", [(), ("unrelated.exe",)])
def test_enumeration_failure_never_authorizes_changes(
    monkeypatch: pytest.MonkeyPatch, names: tuple[str, ...]
) -> None:
    kernel = _process_api(monkeypatch, names, error=5)
    with pytest.raises(windows.ConfigurationError, match="cannot enumerate"):
        windows.is_gk3_running()
    kernel.CloseHandle.assert_called_once()
