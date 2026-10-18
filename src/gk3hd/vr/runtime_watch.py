"""Observe SteamVR's exact server lifetime without owning or terminating it."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import TYPE_CHECKING, Self

from gk3hd.vr.runtime import RuntimeUnavailableError

if TYPE_CHECKING:
    from pathlib import Path

    from gk3hd.vr.runtime import RuntimeSelection

_WINDOWS = os.name == "nt"
_NO_MORE_FILES = 18
_WAIT_TIMEOUT = 258
_WAIT_FAILED = 0xFFFFFFFF


class _Entry(ctypes.Structure):
    _fields_ = (
        ("size", wintypes.DWORD),
        ("usage", wintypes.DWORD),
        ("pid", wintypes.DWORD),
        ("heap", ctypes.c_size_t),
        ("module", wintypes.DWORD),
        ("threads", wintypes.DWORD),
        ("parent", wintypes.DWORD),
        ("priority", wintypes.LONG),
        ("flags", wintypes.DWORD),
        ("name", wintypes.WCHAR * 260),
    )


def _kernel() -> ctypes.WinDLL:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        function = getattr(kernel, name)
        function.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Entry))
        function.restype = wintypes.BOOL
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _server(kernel: ctypes.WinDLL, expected: Path) -> int | None:
    """Hold an exact executable handle, never a name-only PID or kill right."""
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    entry = _Entry()
    entry.size = ctypes.sizeof(entry)
    try:
        present = bool(kernel.Process32FirstW(snapshot, ctypes.byref(entry)))
        while present:
            if entry.name.casefold() == "vrserver.exe":
                # Query-limited + synchronize only. A handle retains identity
                # after exit/PID reuse and cannot terminate the runtime.
                handle = kernel.OpenProcess(0x101000, 0, entry.pid)
                if handle:
                    retained = False
                    try:
                        value = ctypes.create_unicode_buffer(32768)
                        length = wintypes.DWORD(len(value))
                        if not kernel.QueryFullProcessImageNameW(
                            handle, 0, value, ctypes.byref(length)
                        ):
                            raise ctypes.WinError(ctypes.get_last_error())
                        if os.path.normcase(value.value) == os.path.normcase(str(expected)):
                            retained = True
                            return int(handle)
                    finally:
                        if not retained:
                            kernel.CloseHandle(handle)
            present = bool(kernel.Process32NextW(snapshot, ctypes.byref(entry)))
        if ctypes.get_last_error() != _NO_MORE_FILES:
            raise ctypes.WinError(ctypes.get_last_error())
        return None
    finally:
        kernel.CloseHandle(snapshot)


class RuntimeWatch:
    """Guard an established SteamVR session even if a native XR call blocks.

    Bind only after submitted frames, allowing the loader to start SteamVR.
    Runtime focus/standby and slow game loads do not imply process failure.
    Other selected runtimes retain their OpenXR lifecycle supervision.
    """

    def __init__(self, runtime: RuntimeSelection, *, logs: Path) -> None:
        """Select a known server layout without starting or probing a process."""
        root = runtime.manifest.parent
        self._expected = (
            root / "bin/win64/vrserver.exe"
            if _WINDOWS
            and runtime.manifest.name.casefold() == "steamxr_win32.json"
            and runtime.library == root / "bin/vrclient.dll"
            else None
        )
        self._kernel: ctypes.WinDLL | None = None
        self._handle: int | None = None
        self._logs = logs

    def __enter__(self) -> Self:
        """Keep lazy binding scoped to this supervised game launch."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """Release the observation handle, leaving SteamVR itself untouched."""
        if self._kernel is not None and self._handle is not None:
            self._kernel.CloseHandle(self._handle)
            self._handle = None

    def check(self) -> None:
        """Fail on exact server termination, never on paused/stalled frames."""
        if self._expected is None:
            return
        if self._kernel is None:
            self._kernel = _kernel()
        if self._handle is None:
            self._handle = _server(self._kernel, self._expected)
        result = (
            self._kernel.WaitForSingleObject(self._handle, 0) if self._handle is not None else 0
        )
        if result == _WAIT_TIMEOUT:
            return
        if result == _WAIT_FAILED:
            raise ctypes.WinError(ctypes.get_last_error())
        msg = (
            "SteamVR stopped; restart SteamVR and launch VR again. "
            f"Unsaved game progress cannot be recovered. Logs: {self._logs}"
        )
        raise RuntimeUnavailableError(msg)
