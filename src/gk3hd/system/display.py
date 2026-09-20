"""Read the active primary-display mode without changing process DPI policy."""

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import subprocess
from ctypes import wintypes
from dataclasses import dataclass

_MINIMUM_REFRESH_HZ = 24
_MAXIMUM_REFRESH_HZ = 1000


@dataclass(frozen=True, slots=True)
class DisplayMode:
    """Physical width, height, and refresh rate of the primary display."""

    width: int
    height: int
    refresh_hz: int


def current_display_mode() -> DisplayMode:
    """Return the active primary-display mode or a safe reference fallback."""
    if os.name != "nt":
        return _linux_display_mode() or DisplayMode(1024, 768, 60)

    class DevModeW(ctypes.Structure):
        _fields_ = (
            ("dmDeviceName", wintypes.WCHAR * 32),
            ("dmSpecVersion", wintypes.WORD),
            ("dmDriverVersion", wintypes.WORD),
            ("dmSize", wintypes.WORD),
            ("dmDriverExtra", wintypes.WORD),
            ("dmFields", wintypes.DWORD),
            ("dmOrientation", wintypes.SHORT),
            ("dmPaperSize", wintypes.SHORT),
            ("dmPaperLength", wintypes.SHORT),
            ("dmPaperWidth", wintypes.SHORT),
            ("dmScale", wintypes.SHORT),
            ("dmCopies", wintypes.SHORT),
            ("dmDefaultSource", wintypes.SHORT),
            ("dmPrintQuality", wintypes.SHORT),
            ("dmColor", wintypes.SHORT),
            ("dmDuplex", wintypes.SHORT),
            ("dmYResolution", wintypes.SHORT),
            ("dmTTOption", wintypes.SHORT),
            ("dmCollate", wintypes.SHORT),
            ("dmFormName", wintypes.WCHAR * 32),
            ("dmLogPixels", wintypes.WORD),
            ("dmBitsPerPel", wintypes.DWORD),
            ("dmPelsWidth", wintypes.DWORD),
            ("dmPelsHeight", wintypes.DWORD),
            ("dmDisplayFlags", wintypes.DWORD),
            ("dmDisplayFrequency", wintypes.DWORD),
            ("dmICMMethod", wintypes.DWORD),
            ("dmICMIntent", wintypes.DWORD),
            ("dmMediaType", wintypes.DWORD),
            ("dmDitherType", wintypes.DWORD),
            ("dmReserved1", wintypes.DWORD),
            ("dmReserved2", wintypes.DWORD),
            ("dmPanningWidth", wintypes.DWORD),
            ("dmPanningHeight", wintypes.DWORD),
        )

    mode = DevModeW()
    mode.dmSize = ctypes.sizeof(DevModeW)
    if not ctypes.windll.user32.EnumDisplaySettingsW(None, -1, ctypes.byref(mode)):
        return DisplayMode(1024, 768, 60)
    width = int(mode.dmPelsWidth)
    height = int(mode.dmPelsHeight)
    refresh = int(mode.dmDisplayFrequency)
    if width <= 0 or height <= 0:
        return DisplayMode(1024, 768, 60)
    valid_refresh = _MINIMUM_REFRESH_HZ <= refresh <= _MAXIMUM_REFRESH_HZ
    return DisplayMode(width, height, refresh if valid_refresh else 60)


def _linux_display_mode() -> DisplayMode | None:
    """Read KDE's physical mode, then X11/XWayland (including Gamescope)."""
    if os.environ.get("WAYLAND_DISPLAY"):
        mode = _kscreen_mode(_display_command("kscreen-doctor", "-j"))
        if mode is not None:
            return mode
    if os.environ.get("DISPLAY"):
        return _xrandr_mode(_display_command("xrandr", "--current"))
    return None


def _display_command(program: str, argument: str) -> str:
    """Query an optional desktop utility quietly, without waiting indefinitely."""
    executable = shutil.which(program)
    if executable is None:
        return ""
    try:
        result = subprocess.run(  # noqa: S603 - fixed read-only desktop commands, no shell.
            [executable, argument],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def _kscreen_mode(text: str) -> DisplayMode | None:
    """Read the active physical mode rather than KDE's scaled logical geometry."""
    try:
        payload = json.loads(text)
    except ValueError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("outputs"), list):
        return None
    candidates = []
    for output in payload["outputs"]:
        if not isinstance(output, dict) or not output.get("enabled") or not output.get("connected"):
            continue
        mode = _kscreen_output_mode(output)
        if mode is not None:
            priority = output.get("priority", 1 if output.get("primary") else 2)
            candidates.append((priority if isinstance(priority, int) else 2, mode))
    return min(candidates, key=lambda candidate: candidate[0])[1] if candidates else None


def _kscreen_output_mode(output: dict[str, object]) -> DisplayMode | None:
    modes = output.get("modes", [])
    if not isinstance(modes, list):
        return None
    for mode in modes:
        if not isinstance(mode, dict) or mode.get("id") != output.get("currentModeId"):
            continue
        size = mode.get("size")
        if not isinstance(size, dict):
            return None
        width, height, refresh = size.get("width"), size.get("height"), mode.get("refreshRate", 60)
        if not isinstance(width, int) or not isinstance(height, int) or min(width, height) <= 0:
            return None
        # KScreen rotation is a bit flag; quarter turns exchange physical axes.
        if output.get("rotation") in {2, 8}:
            width, height = height, width
        hz = round(refresh) if isinstance(refresh, (int, float)) else 60
        return DisplayMode(
            width, height, hz if _MINIMUM_REFRESH_HZ <= hz <= _MAXIMUM_REFRESH_HZ else 60
        )
    return None


def _xrandr_mode(text: str) -> DisplayMode | None:
    """Select the primary active output, not a multi-monitor bounding rectangle."""
    candidates = []
    active: tuple[bool, int, int] | None = None
    for line in text.splitlines():
        if not line.startswith(" "):
            match = re.match(r"\S+ connected (primary )?(\d+)x(\d+)[+-]\d+[+-]\d+", line)
            active = (bool(match[1]), int(match[2]), int(match[3])) if match else None
        elif active is not None and (refresh := re.search(r"(\d+(?:\.\d+)?)\*", line)):
            primary, width, height = active
            hz = round(float(refresh[1]))
            candidates.append((not primary, DisplayMode(width, height, hz)))
            active = None
    return min(candidates, key=lambda candidate: candidate[0])[1] if candidates else None
