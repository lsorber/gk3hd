"""Start only the owned Windows VR player, activated before game code runs."""

from __future__ import annotations

import ctypes
import os
import subprocess
from enum import StrEnum
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType

    from gk3hd.vr.compiler import VRProgram

_CREATE_SUSPENDED = 0x00000004
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_WAIT_TIMEOUT = 258
_INFINITE = 0xFFFFFFFF
_WM_QUIT = 0x0012
_EXIT_GRACE_SECONDS = 3
# These native arguments size only the desktop mirror and modal source canvas.
# OpenXR selects the independent headset eye extents at session creation.
_MIRROR_ARGUMENTS = ("-window", "-width", "1280", "-height", "800")


class PointingHand(StrEnum):
    """Preferred controller for world, interface and keyboard pointing."""

    LEFT = "left"
    RIGHT = "right"


class _StartupInfo(ctypes.Structure):
    _fields_ = (
        ("cb", ctypes.c_uint32),
        ("reserved", ctypes.c_wchar_p),
        ("desktop", ctypes.c_wchar_p),
        ("title", ctypes.c_wchar_p),
        ("x", ctypes.c_uint32),
        ("y", ctypes.c_uint32),
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("columns", ctypes.c_uint32),
        ("rows", ctypes.c_uint32),
        ("fill", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("show", ctypes.c_uint16),
        ("reserved_size", ctypes.c_uint16),
        ("reserved_bytes", ctypes.c_void_p),
        ("stdin", ctypes.c_void_p),
        ("stdout", ctypes.c_void_p),
        ("stderr", ctypes.c_void_p),
    )


class _ProcessInfo(ctypes.Structure):
    _fields_ = (
        ("process", ctypes.c_void_p),
        ("thread", ctypes.c_void_p),
        ("pid", ctypes.c_uint32),
        ("tid", ctypes.c_uint32),
    )


def _kernel() -> ctypes.CDLL:
    if os.name != "nt":
        msg = "VR launching currently requires Windows"
        raise RuntimeError(msg)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateProcessW.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.POINTER(_StartupInfo),
        ctypes.POINTER(_ProcessInfo),
    )
    kernel.CreateProcessW.restype = ctypes.c_int
    for name in ("ReadProcessMemory", "WriteProcessMemory"):
        function = getattr(kernel, name)
        function.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        )
        function.restype = ctypes.c_int
    kernel.ResumeThread.argtypes = (ctypes.c_void_p,)
    kernel.ResumeThread.restype = ctypes.c_uint32
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel.CloseHandle.restype = ctypes.c_int
    kernel.TerminateProcess.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel.TerminateProcess.restype = ctypes.c_int
    kernel.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    kernel.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))
    kernel.GetExitCodeProcess.restype = ctypes.c_int
    return kernel


def _environment(values: dict[str, str]) -> str:
    if any(not key or "=" in key or "\0" in key + value for key, value in values.items()):
        msg = "invalid VR child environment"
        raise ValueError(msg)
    if len({key.casefold() for key in values}) != len(values):
        msg = "duplicate case-insensitive VR environment names"
        raise ValueError(msg)
    return (
        "\0".join(
            f"{key}={value}"
            for key, value in sorted(values.items(), key=lambda item: item[0].casefold())
        )
        + "\0\0"
    )


def _user() -> ctypes.CDLL:
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.PostThreadMessageW.argtypes = (
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    )
    user.PostThreadMessageW.restype = ctypes.c_int
    return user


class VRProcess:
    """Own child handles, activation and termination without touching other games."""

    def __init__(
        self,
        exe: Path,
        program: VRProgram,
        *,
        environment: dict[str, str],
        pointing_hand: PointingHand = PointingHand.RIGHT,
    ) -> None:
        """Create suspended, validate every dormant switch, activate, then resume."""
        if exe.name != "GK3-VR.exe" or exe.read_bytes() != program.image.to_bytes():
            msg = "VR launch executable differs from the verified isolated player"
            raise ValueError(msg)
        hand = PointingHand(pointing_hand)
        values = _environment(environment)
        kernel = _kernel()
        self._kernel = kernel
        self._info = _ProcessInfo()
        self._resumed = False
        self.returncode: int | None = None
        startup = _StartupInfo()
        startup.cb = ctypes.sizeof(startup)
        command = ctypes.create_unicode_buffer(
            subprocess.list2cmdline([str(exe), *_MIRROR_ARGUMENTS])
        )
        block = ctypes.create_unicode_buffer(values)
        if not kernel.CreateProcessW(
            str(exe),
            command,
            None,
            None,
            0,
            _CREATE_SUSPENDED | _CREATE_UNICODE_ENVIRONMENT,
            block,
            str(exe.parent),
            ctypes.byref(startup),
            ctypes.byref(self._info),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        self.pid = self._info.pid
        try:
            self._activate(program, hand)
        except BaseException as error:
            try:
                self.close()
            except Exception as cleanup_error:  # noqa: BLE001 - preserve the primary activation error.
                error.add_note(f"VR child cleanup also failed: {cleanup_error}")
            raise

    def _activate(self, program: VRProgram, hand: PointingHand) -> None:
        # Validate the complete activation set before writing even one flag.
        pointing_addresses = (program.panel.pointing_hand_va, program.world.hand_va)
        if any(self._read(address) != 0 for address in program.switches) or any(
            self._read(address) != 1 for address in pointing_addresses
        ):
            msg = "VR child activation state differs from its dormant compiled program"
            raise ValueError(msg)
        selected = int(hand is PointingHand.RIGHT)
        for address in pointing_addresses:
            self._write(address, selected)
        for address in program.switches:
            self._write(address, 1)
        if any(self._read(address) != 1 for address in program.switches) or any(
            self._read(address) != selected for address in pointing_addresses
        ):
            msg = "VR child activation could not be verified"
            raise ValueError(msg)
        if self._kernel.ResumeThread(self._info.thread) != 1:
            msg = "VR primary thread did not have the expected single suspension"
            raise RuntimeError(msg)
        self._resumed = True

    def _read(self, address: int) -> int:
        word = ctypes.c_uint32()
        count = ctypes.c_size_t()
        if not self._kernel.ReadProcessMemory(
            self._info.process,
            address,
            ctypes.byref(word),
            ctypes.sizeof(word),
            ctypes.byref(count),
        ) or count.value != ctypes.sizeof(word):
            raise ctypes.WinError(ctypes.get_last_error())
        return word.value

    def _write(self, address: int, value: int) -> None:
        word = ctypes.c_uint32(value)
        count = ctypes.c_size_t()
        if not self._kernel.WriteProcessMemory(
            self._info.process,
            address,
            ctypes.byref(word),
            ctypes.sizeof(word),
            ctypes.byref(count),
        ) or count.value != ctypes.sizeof(word):
            raise ctypes.WinError(ctypes.get_last_error())

    def poll(self) -> int | None:
        """Return a terminal exit code or None while this owned child is active."""
        if self.returncode is not None:
            return self.returncode
        result = self._kernel.WaitForSingleObject(self._info.process, 0)
        if result == _WAIT_TIMEOUT:
            return None
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = ctypes.c_uint32()
        if not self._kernel.GetExitCodeProcess(self._info.process, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.returncode = code.value
        return self.returncode

    def has_submitted_frames(self, program: VRProgram) -> bool:
        """Check native frame counters without treating an exit race as a fault."""
        try:
            return bool(
                self._read(program.scene.submitted_frames_va)
                or self._read(program.panel.submitted_frames_va)
            )
        except OSError:
            if self.poll() is not None:
                return False
            raise

    def render_failure(self, program: VRProgram) -> str | None:
        """Report an explicitly disabled failed bridge, not a frame-time guess.

        Renderer logs can remain buffered. Only a disabled adapter and failing
        HRESULT together establish terminal rendering failure. A hidden runtime,
        an in-progress draw or a slow native load is not this condition. Memory
        can become unreadable during normal teardown before the process signals
        exit; that is an unknown snapshot, not a reported renderer failure.
        """
        try:
            for name, enabled, results in (
                ("world", program.scene.enabled_va, (program.scene.result_va,)),
                (
                    "interface",
                    program.panel.enabled_va,
                    (program.panel.result_va, program.panel.completion_result_va),
                ),
            ):
                if self._read(enabled) != 0:
                    continue
                for address in results:
                    status = self._read(address)
                    if status & 0x80000000:
                        return f"{name} rendering disabled after HRESULT 0x{status:08X}"
        except OSError:
            return None
        return None

    def wait(self, timeout: float | None = None) -> int:
        """Wait for this child, matching the timeout behavior of subprocess.Popen."""
        if self.returncode is not None:
            return self.returncode
        milliseconds = _INFINITE if timeout is None else max(0, round(timeout * 1000))
        result = self._kernel.WaitForSingleObject(self._info.process, milliseconds)
        if result == _WAIT_TIMEOUT:
            if timeout is None:
                msg = "VR infinite process wait unexpectedly timed out"
                raise RuntimeError(msg)
            command = "GK3-VR.exe"
            raise subprocess.TimeoutExpired(command, timeout)
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = self.poll()
        if code is None:
            msg = "VR process wait completed without an exit status"
            raise RuntimeError(msg)
        return code

    def terminate(self) -> None:
        """Stop only the child returned by this object's CreateProcess call."""
        if not self._info.process or self.returncode is not None:
            return
        try:
            code = self.poll()
        except OSError:
            # A failed status read must not bypass termination of our child.
            code = None
        if code is None and not self._kernel.TerminateProcess(self._info.process, 1):
            error = ctypes.WinError(ctypes.get_last_error())
            # Natural exit can race the termination call. Only a confirmed
            # terminal child makes that failure harmless.
            if self.poll() is None:
                raise error

    def kill(self) -> None:
        """Use the same owned-handle stop for subprocess-compatible cleanup."""
        self.terminate()

    def _request_exit(self) -> bool:
        # GK3's native Quit method posts WM_QUIT; its main message pump returns
        # to normal engine/renderer teardown. Post to our retained primary
        # thread, never a window title, another process or a remote thread.
        # No message queue exists before activation or during very early boot.
        if not self._resumed or not self._info.thread or self.poll() is not None:
            return False
        if self._kernel.WaitForSingleObject(self._info.thread, 0) != _WAIT_TIMEOUT:
            return False
        return bool(_user().PostThreadMessageW(self._info.tid, _WM_QUIT, 0, 0))

    def close(self) -> None:
        """Allow native teardown, then stop a hung or suspended owned child."""
        try:
            if self._info.process:
                try:
                    if self._request_exit():
                        self.wait(timeout=_EXIT_GRACE_SECONDS)
                except (OSError, subprocess.TimeoutExpired):
                    # A dead queue, failed runtime or hung game cannot prevent
                    # bounded cleanup. The original context error is preserved.
                    pass
                self.terminate()
                self.wait(timeout=5)
        finally:
            for name in ("thread", "process"):
                handle = getattr(self._info, name)
                if handle:
                    self._kernel.CloseHandle(handle)
                    setattr(self._info, name, None)

    def __enter__(self) -> Self:
        """Keep the running child's handles owned until context exit."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Never leave a suspended or unowned game process after cancellation."""
        try:
            self.close()
        except Exception as error:
            if exc is None:
                raise
            exc.add_note(f"VR child cleanup also failed: {error}")
