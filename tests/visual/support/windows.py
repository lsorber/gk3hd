"""Small Windows boundary for deterministic GK3 visual captures."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from ctypes import wintypes
from typing import TYPE_CHECKING, Final

import numpy as np
from PIL import Image, ImageGrab
from windows_capture import CaptureControl, Frame, InternalCaptureControl, WindowsCapture

from gk3hd.patch.install.windows import is_gk3_running
from gk3hd.system.locking import ExclusiveFileLock, executable_lock_path

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_KEY_UP: Final = 0x0002
_DPI_PER_MONITOR_V2: Final = -4
_MAPVK_VK_TO_VSC_EX: Final = 4
# These virtual keys name the navigation cluster, not its numpad aliases.
# Some layouts return only the shared low scan byte even in extended mode.
_EXTENDED_NAVIGATION_KEYS: Final = frozenset((*range(0x21, 0x29), 0x2D, 0x2E))
_KEYEVENTF_EXTENDEDKEY: Final = 0x0001
_KEYEVENTF_SCANCODE: Final = 0x0008
_VK_CONTROL: Final = 0x11
_WM_KEYDOWN: Final = 0x0100
_WM_KEYUP: Final = 0x0101
_WM_MOUSEMOVE: Final = 0x0200
_KEY_MESSAGE_EXTENDED_BIT: Final = 1 << 24
_KEY_MESSAGE_PREVIOUS_BIT: Final = 1 << 30
_KEY_MESSAGE_TRANSITION_BIT: Final = 1 << 31
_MOUSEEVENTF_LEFTDOWN: Final = 0x0002
_MOUSEEVENTF_LEFTUP: Final = 0x0004
_MOUSEEVENTF_RIGHTDOWN: Final = 0x0008
_MOUSEEVENTF_RIGHTUP: Final = 0x0010
_MOUSEEVENTF_MOVE_ABSOLUTE: Final = 0x8001
_INPUT_MOUSE: Final = 0
_INPUT_KEYBOARD: Final = 1
_FRAME_TIMEOUT_SECONDS: Final = 3.0
_PROCESS_QUERY_INFORMATION: Final = 0x0400
_PROCESS_VM_READ: Final = 0x0010
_UI_MANAGER_POINTER: Final = 0x006FF838
_LOCATION_NAMES: Final = 0x006F5F24
_TIMEBLOCK_NAMES: Final = 0x006F5E94
_LOCATION_COUNT: Final = 84
_TIMEBLOCK_COUNT: Final = 18
_TIMEBLOCK_VTABLE: Final = 0x0067DF90
_BITMAP_HANDLE_CAPACITY: Final = 1 << 16
_LAYER_ENTRY_BYTES: Final = 16
_DO_NOT_INHERIT_HANDLE: Final = False
_ENGINE_WINDOW_CLASS: Final = "SierraGEngineWindow"


class CaptureError(RuntimeError):
    """Report a failed process, window, input, or framebuffer operation."""


@contextmanager
def capture_session(executable: Path) -> Iterator[None]:
    """Exclude installers and other captures before touching game state.

    Fail immediately if a game is already running. Captures temporarily
    change shared settings and stage save slots; they must never borrow a
    player's live process or race another transaction in the same directory.
    """
    with ExclusiveFileLock(executable_lock_path(executable)):
        if is_gk3_running():
            message = "close GK3 before starting a visual capture"
            raise CaptureError(message)
        yield


class _Rect(ctypes.Structure):
    _fields_ = (
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    )


class _Point(ctypes.Structure):
    _fields_ = (("x", wintypes.LONG), ("y", wintypes.LONG))


class _MouseInput(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouse_data", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("extra_info", wintypes.WPARAM),
    )


class _KeyboardInput(ctypes.Structure):
    _fields_ = (
        ("virtual_key", wintypes.WORD),
        ("scan_code", wintypes.WORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("extra_info", wintypes.WPARAM),
    )


class _InputPayload(ctypes.Union):
    _fields_ = (("mouse", _MouseInput), ("keyboard", _KeyboardInput))


class _Input(ctypes.Structure):
    _fields_ = (("kind", wintypes.DWORD), ("payload", _InputPayload))


class FrameGrabber:
    """Retain only the newest frame from one persistent WGC session."""

    def __init__(self, window: int, *, wgc: bool = True) -> None:
        """Start capturing the named visible window without the host cursor."""
        self._window = window
        self._wgc = wgc
        self._control: CaptureControl | None = None
        if not wgc:
            return
        title = _window_title(window)
        if not title:
            message = "GK3's visible window has no capturable title"
            raise CaptureError(message)
        self._condition = threading.Condition()
        self._latest: np.ndarray | None = None
        self._sequence = 0
        self._closed = False
        self._capture = WindowsCapture(
            cursor_capture=False,
            dirty_region=False,
            minimum_update_interval=16,
            window_name=title,
        )

        def on_frame_arrived(frame: Frame, _control: InternalCaptureControl) -> None:
            latest = np.asarray(frame.frame_buffer, dtype=np.uint8).copy()
            with self._condition:
                self._latest = latest
                self._sequence += 1
                self._condition.notify_all()

        def on_closed() -> None:
            with self._condition:
                self._closed = True
                self._condition.notify_all()

        self._capture.event(on_frame_arrived)
        self._capture.event(on_closed)
        self._control = self._capture.start_free_threaded()

    @property
    def uses_wgc(self) -> bool:
        """Return whether this source uses Windows Graphics Capture."""
        return self._wgc

    @property
    def closed(self) -> bool:
        """Return whether Windows closed this capture item."""
        if not self._wgc:
            return False
        with self._condition:
            return self._closed

    def grab(self, *, width: int, height: int) -> Image.Image:
        """Return a fresh frame normalized to GK3's requested logical size."""
        if not self._wgc:
            return _capture_gdi(self._window, width=width, height=height)
        with self._condition:
            previous_sequence = self._sequence
            self._condition.wait_for(
                lambda: self._sequence > previous_sequence or self._closed,
                timeout=_FRAME_TIMEOUT_SECONDS,
            )
            if self._latest is None:
                reason = "window closed" if self._closed else "capture timed out"
                message = f"could not capture GK3 through Windows Graphics Capture: {reason}"
                raise CaptureError(message)
            raw = self._latest
        bgr = raw[:, :, :3]
        image = Image.fromarray(bgr[:, :, ::-1], mode="RGB")
        return _normalize_frame(image, width=width, height=height)

    def close(self) -> None:
        """Stop the background capture session exactly once."""
        if self._control is not None:
            if not self._control.is_finished():
                self._control.stop()
            self._control.wait()


def launch(executable: Path) -> subprocess.Popen[bytes]:
    """Launch GK3 in its own game directory without a shell."""
    if sys.platform != "win32":
        message = "visual capture is available only on Windows"
        raise CaptureError(message)
    environment = dict(os.environ)
    environment.pop("__COMPAT_LAYER", None)
    return subprocess.Popen(  # noqa: S603 - exact discovered executable, no shell
        [str(executable)],
        cwd=executable.parent,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def make_dpi_aware() -> None:
    """Keep capture, client rectangles, and injected input in physical pixels."""
    if sys.platform != "win32":
        message = "visual capture is available only on Windows"
        raise CaptureError(message)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    context = ctypes.c_void_p(_DPI_PER_MONITOR_V2)
    user32.SetProcessDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
    user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
    user32.SetProcessDpiAwarenessContext(context)
    # Imports may already have fixed the process-wide policy. The calling
    # capture/input thread still needs physical coordinates after mode/DPI
    # changes; legacy system awareness can report a 1280-wide window as 3840.
    user32.SetThreadDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    if not user32.SetThreadDpiAwarenessContext(context):
        message = "could not enable per-monitor DPI awareness for visual capture"
        raise CaptureError(message)


def current_ui_layer_vtable(process_id: int) -> int | None:
    """Read GK3's current native UI class identity without mutating the process."""
    current_layer = current_ui_layer_pointer(process_id)
    state = read_process_words(process_id, current_layer, count=1) if current_layer else None
    return state[0] if state else None


def current_cursor_resource(process_id: int) -> str | None:
    """Read the active retail cursor, including the scripted-action busy hand.

    A rendered Room layer can still be running an introduction. Its cursor
    drawable points into the bitmap resource table; missing/transient pointers
    are unknown state, never evidence that the game has finished an action.
    """
    pointer = _UI_MANAGER_POINTER
    for offset in (0x444, 0x44, 8, 28 * 4, 32):
        value = read_process_words(process_id, pointer, count=1)
        if not value or not value[0]:
            return None
        pointer = value[0] + offset
    drawable = read_process_words(process_id, pointer, count=1)
    return _bitmap_resource_name(process_id, drawable[0] & 0xFFFF) if drawable else None


def _bitmap_resource_name(process_id: int, handle: int) -> str | None:
    """Resolve a bounded cursor bitmap handle to its terminated asset name."""
    bitmaps = read_process_words(process_id, 0x0070B0D4, count=1)
    if not bitmaps or not bitmaps[0]:
        return None
    table = read_process_words(process_id, bitmaps[0] + 0x120, count=2)
    if not table or not table[0] or not 0 <= handle < table[1] <= _BITMAP_HANDLE_CAPACITY:
        return None
    resource = read_process_words(process_id, table[0] + handle * 4, count=1)
    if not resource or not resource[0]:
        return None
    words = read_process_words(process_id, resource[0] + 8, count=8)
    if not words:
        return None
    encoded = b"".join(word.to_bytes(4, "little") for word in words)
    name, separator, _padding = encoded.partition(b"\0")
    if not separator or not name.startswith(b"C_") or not name.isascii():
        return None
    return name.decode("ascii")


def current_scene_identity(process_id: int) -> tuple[str, str] | None:
    """Read the same location/time identifiers as retail IsCurrentLocation/Time.

    Both queries follow Engine +444 -> gameplay +60 -> current IDs +10/+14.
    Decode through the executable's own name tables instead of maintaining a
    second location enumeration. A visible TimeBlock card owns its target time:
    retail +3CC feeds the time-name lookup at 004D551F, while gameplay can still
    report the previous time. Missing/transient state is not a scene match.
    """
    pointer = _UI_MANAGER_POINTER
    for offset in (0x444, 0x60, 0x10):
        value = read_process_words(process_id, pointer, count=1)
        if not value or not value[0]:
            return None
        pointer = value[0] + offset
    identifiers = read_process_words(process_id, pointer, count=2)
    if not identifiers:
        return None
    layer = current_ui_layer_pointer(process_id)
    layer_type = read_process_words(process_id, layer, count=1) if layer else None
    if not layer_type or layer is None:
        return None
    time_identifier = identifiers[1]
    if layer_type[0] == _TIMEBLOCK_VTABLE:
        target_time = read_process_words(process_id, layer + 0x3CC, count=1)
        if not target_time:
            return None
        time_identifier = target_time[0]
    names: list[str] = []
    for identifier, table, limit, length in (
        (identifiers[0], _LOCATION_NAMES, _LOCATION_COUNT, 3),
        (time_identifier, _TIMEBLOCK_NAMES, _TIMEBLOCK_COUNT, 4),
    ):
        name = _scene_identifier_name(process_id, identifier, table, limit, length)
        if name is None:
            return None
        names.append(name)
    return names[0], names[1]


def _scene_identifier_name(
    process_id: int, identifier: int, table: int, limit: int, length: int
) -> str | None:
    """Decode one bounded, terminated retail identifier without guessing."""
    if not 0 < identifier < limit:
        return None
    entry = read_process_words(process_id, table + identifier * 4, count=1)
    if not entry or not entry[0]:
        return None
    words = read_process_words(process_id, entry[0], count=2)
    if not words:
        return None
    encoded = b"".join(word.to_bytes(4, "little") for word in words)
    try:
        name = encoded[:length].decode("ascii")
    except UnicodeDecodeError:
        return None
    return name.casefold() if encoded[length] == 0 and name.isalnum() else None


def current_ui_layer_pointer(process_id: int) -> int | None:
    """Read GK3's current native UI object pointer without mutating it."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.ReadProcessMemory.argtypes = (
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    )
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(
        _PROCESS_QUERY_INFORMATION | _PROCESS_VM_READ,
        _DO_NOT_INHERIT_HANDLE,
        process_id,
    )
    if not handle:
        return None

    def read_u32(address: int | None) -> int | None:
        if not address:
            return None
        value = ctypes.c_uint32()
        read = ctypes.c_size_t()
        if not kernel32.ReadProcessMemory(
            handle,
            ctypes.c_void_p(address),
            ctypes.byref(value),
            ctypes.sizeof(value),
            ctypes.byref(read),
        ):
            return None
        return int(value.value) if read.value == ctypes.sizeof(value) else None

    try:
        ui_manager = read_u32(_UI_MANAGER_POINTER)
        ui_owner = read_u32(ui_manager + 0x444) if ui_manager else None
        layer_stack = read_u32(ui_owner + 0x44) if ui_owner else None
        current_layer = read_u32(layer_stack + 0x58) if layer_stack else None
        if layer_stack and not current_layer:
            layer_end = read_u32(layer_stack + 0x44)
            if layer_end and layer_end >= _LAYER_ENTRY_BYTES:
                current_layer = read_u32(layer_end - _LAYER_ENTRY_BYTES)
        return current_layer
    finally:
        kernel32.CloseHandle(handle)


def read_process_words(
    process_id: int,
    address: int,
    *,
    count: int,
) -> tuple[int, ...] | None:
    """Read a small published diagnostic state from GK3 in one system call."""
    if count <= 0:
        return ()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.ReadProcessMemory.argtypes = (
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    )
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(
        _PROCESS_QUERY_INFORMATION | _PROCESS_VM_READ,
        _DO_NOT_INHERIT_HANDLE,
        process_id,
    )
    if not handle:
        return None
    values = (ctypes.c_uint32 * count)()
    expected = ctypes.sizeof(values)
    read = ctypes.c_size_t()
    try:
        if not kernel32.ReadProcessMemory(
            handle,
            ctypes.c_void_p(address),
            ctypes.byref(values),
            expected,
            ctypes.byref(read),
        ):
            return None
        return tuple(values) if read.value == expected else None
    finally:
        kernel32.CloseHandle(handle)


def wait_for_window(
    process_id: int,
    *,
    timeout: float = 30.0,
    minimum_size: tuple[int, int] | None = None,
) -> int:
    """Return GK3's engine-input window, preferring it over render peers."""
    user32 = _user32()
    enum_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        fatal = process_error_dialog(process_id)
        if fatal is not None:
            message = f"GK3 reported an error: {fatal}"
            raise CaptureError(message)
        matches: list[tuple[int, int, int, int, int]] = []

        @enum_callback
        def collect(
            window: int,
            _parameter: int,
            _matches: list[tuple[int, int, int, int, int]] = matches,
        ) -> bool:
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
            if owner.value == process_id and user32.IsWindowVisible(window):
                client = _Rect()
                if user32.GetClientRect(window, ctypes.byref(client)):
                    width = max(0, client.right - client.left)
                    height = max(0, client.bottom - client.top)
                    preferred = int(_window_class(window) == _ENGINE_WINDOW_CLASS)
                    _matches.append((preferred, width * height, window, width, height))
            return True

        user32.EnumWindows(collect, 0)
        if minimum_size is not None:
            matches = [
                match
                for match in matches
                if match[3] >= minimum_size[0] and match[4] >= minimum_size[1]
            ]
        if matches:
            return max(matches)[2]
        time.sleep(0.1)
    message = f"GK3 did not create a visible window within {timeout:g} seconds"
    raise CaptureError(message)


def press_key(
    window: int,
    key: int,
    *,
    control: bool = False,
    hold_seconds: float = 0.2,
) -> None:
    """Send one bounded foreground key edge to GK3."""
    user32 = _user32()
    user32.SetForegroundWindow(window)
    time.sleep(0.08)
    if control:
        _send_key_edge(user32, _VK_CONTROL, up=False)
    _send_key_edge(user32, key, up=False)
    time.sleep(hold_seconds)
    _send_key_edge(user32, key, up=True)
    if control:
        _send_key_edge(user32, _VK_CONTROL, up=True)


def post_key(window: int, key: int) -> None:
    """Post one short virtual-key edge to GK3's own window queue."""
    user32 = _user32()
    mapped = _mapped_scan_code(user32, key)
    down = 1 | ((mapped & 0xFF) << 16)
    if mapped & 0xFF00:
        down |= _KEY_MESSAGE_EXTENDED_BIT
    up = down | _KEY_MESSAGE_PREVIOUS_BIT | _KEY_MESSAGE_TRANSITION_BIT
    user32.PostMessageW(window, _WM_KEYDOWN, key, down)
    time.sleep(0.01)
    user32.PostMessageW(window, _WM_KEYUP, key, up)


def process_error_dialog(process_id: int) -> str | None:
    """Return text from a visible GK3 modal error dialog, if one exists."""
    user32 = _user32()
    enum_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    messages: list[str] = []

    @enum_callback
    def collect(window: int, _parameter: int) -> bool:
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if (
            owner.value == process_id
            and user32.IsWindowVisible(window)
            and _window_class(window) == "#32770"
        ):
            text = _dialog_text(window)
            messages.append(text or _window_title(window) or "unknown modal error")
        return True

    user32.EnumWindows(collect, 0)
    return "; ".join(messages) if messages else None


def click_client(
    window: int,
    x: int,
    y: int,
    *,
    button: str = "left",
    hold_seconds: float = 0.04,
) -> None:
    """Click one visually proved client-space control center."""
    user32 = _user32()
    point = _Point(x, y)
    if not user32.ClientToScreen(window, ctypes.byref(point)):
        message = "could not map the title control to screen coordinates"
        raise CaptureError(message)
    user32.SetForegroundWindow(window)
    time.sleep(0.03)
    _move_mouse_absolute(user32, point.x, point.y)
    _post_mouse_move(user32, window, x, y)
    time.sleep(0.12)
    if button == "left":
        down, up = _MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP
    elif button == "right":
        down, up = _MOUSEEVENTF_RIGHTDOWN, _MOUSEEVENTF_RIGHTUP
    else:
        message = f"unsupported mouse button: {button}"
        raise CaptureError(message)
    _send_mouse_edge(user32, down)
    time.sleep(hold_seconds)
    _send_mouse_edge(user32, up)


def click_frame_point(
    window: int,
    x: int,
    y: int,
    *,
    frame_size: tuple[int, int],
    button: str = "left",
) -> None:
    """Map one captured-frame point into the live DPI-logical client."""
    client_x, client_y = _frame_client_point(window, x, y, frame_size=frame_size)
    click_client(window, client_x, client_y, button=button)


def held_click_frame_point(
    window: int,
    x: int,
    y: int,
    *,
    frame_size: tuple[int, int],
    hold_seconds: float,
) -> None:
    """Click long enough for GK3's independent DirectInput poll to see it."""
    client_x, client_y = _frame_client_point(window, x, y, frame_size=frame_size)
    click_client(window, client_x, client_y, hold_seconds=hold_seconds)


def _frame_client_point(
    window: int,
    x: int,
    y: int,
    *,
    frame_size: tuple[int, int],
) -> tuple[int, int]:
    """Map captured-frame coordinates into the live DPI-logical client."""
    user32 = _user32()
    rect = _Rect()
    if not user32.GetClientRect(window, ctypes.byref(rect)):
        message = "could not resolve GK3's client size"
        raise CaptureError(message)
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        message = "GK3's client has no interactive area"
        raise CaptureError(message)
    frame_width, frame_height = frame_size
    client_x = round(x * width / frame_width)
    client_y = round(y * height / frame_height)
    return client_x, client_y


def move_frame_point(
    window: int,
    x: int,
    y: int,
    *,
    frame_size: tuple[int, int],
) -> None:
    """Move the live pointer to one captured-frame point without clicking."""
    user32 = _user32()
    rect = _Rect()
    if not user32.GetClientRect(window, ctypes.byref(rect)):
        message = "could not resolve GK3's client size"
        raise CaptureError(message)
    frame_width, frame_height = frame_size
    client_width = rect.right - rect.left
    client_height = rect.bottom - rect.top
    if min(frame_width, frame_height, client_width, client_height) <= 0:
        message = "GK3's client has no interactive area"
        raise CaptureError(message)
    client_x = round(x * client_width / frame_width)
    client_y = round(y * client_height / frame_height)
    point = _Point(client_x, client_y)
    if not user32.ClientToScreen(window, ctypes.byref(point)):
        message = "could not map the pointer point to screen coordinates"
        raise CaptureError(message)
    user32.SetForegroundWindow(window)
    _move_mouse_absolute(user32, point.x, point.y)
    _post_mouse_move(user32, window, client_x, client_y)


def press_chord(window: int, keys: tuple[int, ...], *, hold_seconds: float = 0.1) -> None:
    """Send one foreground keyboard chord with deterministic edge ordering."""
    if not keys:
        message = "a keyboard chord needs at least one key"
        raise CaptureError(message)
    user32 = _user32()
    user32.SetForegroundWindow(window)
    time.sleep(0.05)
    for key in keys:
        _send_key_edge(user32, key, up=False)
    time.sleep(hold_seconds)
    for key in reversed(keys):
        _send_key_edge(user32, key, up=True)


def type_text(window: int, value: str, *, key_interval: float = 0.05) -> None:
    """Type text through the active Windows keyboard layout."""
    user32 = _user32()
    user32.SetForegroundWindow(window)
    for character in value:
        encoded = int(user32.VkKeyScanW(character))
        if encoded == -1:
            message = f"the active keyboard layout cannot type {character!r}"
            raise CaptureError(message)
        key = encoded & 0xFF
        shift_state = (encoded >> 8) & 0xFF
        modifiers = tuple(
            modifier
            for bit, modifier in ((1, 0x10), (2, _VK_CONTROL), (4, 0x12))
            if shift_state & bit
        )
        for modifier in modifiers:
            _send_key_edge(user32, modifier, up=False)
        _send_key_edge(user32, key, up=False)
        time.sleep(max(0.01, key_interval / 2))
        _send_key_edge(user32, key, up=True)
        for modifier in reversed(modifiers):
            _send_key_edge(user32, modifier, up=True)
        time.sleep(max(0.01, key_interval / 2))


def drag_frame_points(
    window: int,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    frame_size: tuple[int, int],
    steps: int = 8,
) -> None:
    """Drag between two captured-frame points through live client coordinates."""
    if steps < 1:
        message = "a pointer drag needs at least one movement step"
        raise CaptureError(message)
    user32 = _user32()
    rect = _Rect()
    if not user32.GetClientRect(window, ctypes.byref(rect)):
        message = "could not resolve GK3's client size"
        raise CaptureError(message)
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    frame_width, frame_height = frame_size
    if min(width, height, frame_width, frame_height) <= 0:
        message = "GK3's client has no interactive area"
        raise CaptureError(message)

    def screen_point(point: tuple[int, int]) -> _Point:
        mapped = _Point(
            round(point[0] * width / frame_width),
            round(point[1] * height / frame_height),
        )
        if not user32.ClientToScreen(window, ctypes.byref(mapped)):
            message = "could not map the drag point to screen coordinates"
            raise CaptureError(message)
        return mapped

    start_screen = screen_point(start)
    end_screen = screen_point(end)
    user32.SetForegroundWindow(window)
    user32.SetCursorPos(start_screen.x, start_screen.y)
    time.sleep(0.03)
    _send_mouse_edge(user32, _MOUSEEVENTF_LEFTDOWN)
    try:
        # GK3 samples DirectInput independently of cursor injection.  Keep
        # fine-grained diagnostic drags slow enough that its drag threshold
        # observes an early point still inside small controls such as the
        # 23-pixel Load/Save thumb.
        interval = max(0.012, 0.24 / steps)
        for step in range(1, steps + 1):
            x = round(start_screen.x + (end_screen.x - start_screen.x) * step / steps)
            y = round(start_screen.y + (end_screen.y - start_screen.y) * step / steps)
            user32.SetCursorPos(x, y)
            time.sleep(interval)
    finally:
        _send_mouse_edge(user32, _MOUSEEVENTF_LEFTUP)


def stop(process: subprocess.Popen[bytes], window: int | None) -> None:
    """Stop the disposable capture process without invoking GK3's crash-prone quit path."""
    del window
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _user32() -> ctypes.WinDLL:
    """Load USER32 lazily so repository checks remain portable."""
    if sys.platform != "win32":
        message = "visual capture is available only on Windows"
        raise CaptureError(message)
    library = ctypes.WinDLL("user32", use_last_error=True)
    library.EnumWindows.argtypes = (ctypes.c_void_p, wintypes.LPARAM)
    library.EnumWindows.restype = wintypes.BOOL
    library.EnumChildWindows.argtypes = (
        wintypes.HWND,
        ctypes.c_void_p,
        wintypes.LPARAM,
    )
    library.EnumChildWindows.restype = wintypes.BOOL
    library.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    library.GetWindowThreadProcessId.restype = wintypes.DWORD
    library.IsWindowVisible.argtypes = (wintypes.HWND,)
    library.IsWindowVisible.restype = wintypes.BOOL
    library.SetForegroundWindow.argtypes = (wintypes.HWND,)
    library.SetForegroundWindow.restype = wintypes.BOOL
    library.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(_Rect))
    library.GetClientRect.restype = wintypes.BOOL
    library.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(_Point))
    library.ClientToScreen.restype = wintypes.BOOL
    library.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    library.GetWindowTextLengthW.restype = ctypes.c_int
    library.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    library.GetWindowTextW.restype = ctypes.c_int
    library.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    library.GetClassNameW.restype = ctypes.c_int
    library.PostMessageW.argtypes = (
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )
    library.PostMessageW.restype = wintypes.BOOL
    library.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
    library.MapVirtualKeyW.restype = wintypes.UINT
    library.VkKeyScanW.argtypes = (wintypes.WCHAR,)
    library.VkKeyScanW.restype = ctypes.c_short
    library.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    library.SetCursorPos.restype = wintypes.BOOL
    library.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_Input), ctypes.c_int)
    library.SendInput.restype = wintypes.UINT
    library.mouse_event.argtypes = (
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.WPARAM,
    )
    library.keybd_event.argtypes = (
        wintypes.BYTE,
        wintypes.BYTE,
        wintypes.DWORD,
        wintypes.WPARAM,
    )
    return library


def _send_mouse_edge(user32: ctypes.WinDLL, flag: int) -> None:
    event = _Input(
        kind=_INPUT_MOUSE,
        payload=_InputPayload(
            mouse=_MouseInput(
                dx=0,
                dy=0,
                mouse_data=0,
                flags=flag,
                time=0,
                extra_info=0,
            )
        ),
    )
    accepted = user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))
    if accepted != 1:
        user32.mouse_event(flag, 0, 0, 0, 0)


def _move_mouse_absolute(user32: ctypes.WinDLL, x: int, y: int) -> None:
    """Move through the input stream consumed by GK3's legacy DirectInput device."""
    desktop_width = max(1, int(user32.GetSystemMetrics(0)))
    desktop_height = max(1, int(user32.GetSystemMetrics(1)))
    absolute_x = round(x * 65535 / max(1, desktop_width - 1))
    absolute_y = round(y * 65535 / max(1, desktop_height - 1))
    user32.mouse_event(_MOUSEEVENTF_MOVE_ABSOLUTE, absolute_x, absolute_y, 0, 0)


def _post_mouse_move(user32: ctypes.WinDLL, window: int, x: int, y: int) -> None:
    """Publish the client point required by GK3's exclusive fullscreen input path."""
    parameter = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
    user32.PostMessageW(window, _WM_MOUSEMOVE, 0, parameter)


def _mapped_scan_code(user32: ctypes.WinDLL, key: int) -> int:
    """Preserve extended identity so arrows cannot become numpad characters."""
    mapped = int(user32.MapVirtualKeyW(key, _MAPVK_VK_TO_VSC_EX))
    if mapped and key in _EXTENDED_NAVIGATION_KEYS:
        mapped |= 0xE000
    return mapped


def _send_key_edge(user32: ctypes.WinDLL, key: int, *, up: bool) -> None:
    mapped = _mapped_scan_code(user32, key)
    flags = _KEYEVENTF_SCANCODE | (_KEY_UP if up else 0)
    if mapped & 0xFF00:
        flags |= _KEYEVENTF_EXTENDEDKEY
    event = _Input(
        kind=_INPUT_KEYBOARD,
        payload=_InputPayload(
            keyboard=_KeyboardInput(
                virtual_key=0,
                scan_code=mapped & 0xFF,
                flags=flags,
                time=0,
                extra_info=0,
            )
        ),
    )
    accepted = user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))
    if accepted != 1:
        user32.keybd_event(key, mapped & 0xFF, flags & ~_KEYEVENTF_SCANCODE, 0)


def _window_title(window: int) -> str:
    user32 = _user32()
    length = user32.GetWindowTextLengthW(window)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(window, buffer, len(buffer))
    return str(buffer.value).strip()


def _window_class(window: int) -> str:
    user32 = _user32()
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(window, buffer, len(buffer))
    return str(buffer.value)


def _dialog_text(window: int) -> str:
    user32 = _user32()
    enum_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    labels: list[str] = []

    @enum_callback
    def collect(child: int, _parameter: int) -> bool:
        if _window_class(child) == "Static":
            text = _window_title(child)
            if text:
                labels.append(text)
        return True

    user32.EnumChildWindows(window, collect, 0)
    return " ".join(labels)


def _capture_gdi(window: int, *, width: int, height: int) -> Image.Image:
    user32 = _user32()
    origin = _Point()
    if not user32.ClientToScreen(window, ctypes.byref(origin)):
        message = "could not resolve GK3's client origin"
        raise CaptureError(message)
    image = ImageGrab.grab(
        bbox=(origin.x, origin.y, origin.x + width, origin.y + height),
        all_screens=True,
    )
    return _normalize_frame(image.convert("RGB"), width=width, height=height)


def _normalize_frame(image: Image.Image, *, width: int, height: int) -> Image.Image:
    target_aspect = width / height
    source_aspect = image.width / image.height
    if source_aspect > target_aspect:
        crop_width = round(image.height * target_aspect)
        left = (image.width - crop_width) // 2
        image = image.crop((left, 0, left + crop_width, image.height))
    elif source_aspect < target_aspect:
        crop_height = round(image.width / target_aspect)
        top = (image.height - crop_height) // 2
        image = image.crop((0, top, image.width, top + crop_height))
    if image.size != (width, height):
        return image.resize((width, height), Image.Resampling.LANCZOS)
    return image
