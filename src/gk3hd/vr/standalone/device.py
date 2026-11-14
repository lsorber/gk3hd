"""Read-only Android discovery before choosing a standalone XR backend.

An advertised runtime is not evidence of a working graphics session. Do not
reuse the Windows runtime loader or equate PC-connected Pimax audio with ADB.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from gk3hd.system.files import windows_known_folder
from gk3hd.vr.standalone.adb import download_adb

_PROPERTIES = {
    "manufacturer": "ro.product.manufacturer",
    "model": "ro.product.model",
    "android": "ro.build.version.release",
    "api": "ro.build.version.sdk",
    "abis": "ro.product.cpu.abilist",
}
_SERIAL = re.compile(r"[a-zA-Z0-9_.:-]+")
_DEVICE_COLUMNS = 2
_MIN_ANDROID_API = 26
_DOWNLOADS = UUID("374DE290-123F-4565-9164-39C4925E467B")
USB_RETRY = "Wake the headset, reconnect its USB data cable, and run the same command again."


def usb_problem(detail: str) -> str | None:
    """Turn ADB transport failures into the same advice as initial discovery."""
    detail = detail.casefold()
    if "unauthorized" in detail:
        return "Put on the headset and select Allow USB debugging, then try again."
    if any(
        phrase in detail
        for phrase in ("device offline", "no devices/emulators found", "device disconnected")
    ) or re.search(r"device '[^']+' not found", detail):
        return USB_RETRY
    return None


@dataclass(frozen=True, slots=True)
class Broker:
    """Discovery output, deliberately not a supported-device assertion."""

    authority: str
    status: str
    response: str


@dataclass(frozen=True, slots=True)
class DeviceProbe:
    """Small allowlisted report; no full property or application inventory."""

    device: str
    properties: dict[str, str]
    memory_mib: int | None
    brokers: tuple[Broker, ...]
    pimax_library_paths: tuple[str, ...]


def require_install_platform(headset: DeviceProbe) -> None:
    """Reject platforms the Android player cannot run on."""
    api = headset.properties.get("api", "")
    abis = headset.properties.get("abis", "").split(",")
    if (
        "arm64-v8a" not in abis
        or not re.fullmatch(r"[0-9]{1,3}", api)
        or int(api) < _MIN_ANDROID_API
    ):
        msg = (
            f"This standalone player requires Android API {_MIN_ANDROID_API} or newer "
            "with ARM64 support; no app was installed"
        )
        raise RuntimeError(msg)


def _run(adb: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - separate arguments, never a host shell.
            [adb, *arguments], capture_output=True, text=True, timeout=10, check=False
        )
    except FileNotFoundError as error:
        msg = f"ADB could not start at {adb}. Pass the path to the ADB executable with --adb."
        raise RuntimeError(msg) from error
    except subprocess.TimeoutExpired as error:
        msg = "Android device query timed out; check the USB connection and headset."
        raise RuntimeError(msg) from error


def _select_device(output: str, requested: str | None) -> str:
    devices: dict[str, tuple[str, str]] = {}
    for line in output.splitlines():
        fields = line.split()
        if (
            len(fields) >= _DEVICE_COLUMNS
            and _SERIAL.fullmatch(fields[0])
            and fields[1] in {"device", "unauthorized", "offline"}
        ):
            model = next(
                (
                    field.removeprefix("model:")
                    for field in fields[2:]
                    if field.startswith("model:")
                ),
                "Unknown model",
            )
            devices[fields[0]] = (fields[1], model.replace("_", " "))
    if requested is None:
        if not devices:
            msg = (
                "No Android headset is visible over ADB. Connect a USB data cable directly "
                "to the PC and wake the headset. On Quest, return to Quest Home and check "
                "Developer Mode in the Meta Horizon app. On Crystal, use AIO mode. "
                "Accept Allow USB debugging if prompted."
            )
            raise RuntimeError(msg)
        if len(devices) != 1:
            choices = "\n".join(
                f"  {model} ({state})  --device {serial}"
                for serial, (state, model) in devices.items()
            )
            msg = f"Multiple Android devices are connected. Add one of these options.\n{choices}"
            raise RuntimeError(msg)
        requested = next(iter(devices))
    if not _SERIAL.fullmatch(requested) or requested not in devices:
        msg = "The selected Android device is not connected."
        raise RuntimeError(msg)
    state, _ = devices[requested]
    if state == "unauthorized":
        msg = "USB debugging is unauthorized. Put on the headset and select Allow USB debugging."
        raise RuntimeError(msg)
    if state == "offline":
        msg = f"The headset is offline. {USB_RETRY}"
        raise RuntimeError(msg)
    return requested


def _broker_status(response: str, returncode: int) -> str:
    lower = response.casefold()
    if "permission denial" in lower or "securityexception" in lower:
        return "query denied; runtime availability unknown"
    if returncode == 0 and "package_name=" in response and "so_filename=" in response:
        return "runtime advertised; session not tested"
    return "no accessible runtime row; standalone support not established"


def select_device(adb: str, requested: str | None) -> str:
    """Find one authorized Android device without probing its runtime."""
    listing = _run(adb, "devices", "-l")
    if listing.returncode:
        detail = listing.stderr.strip() or listing.stdout.strip()
        msg = usb_problem(detail) or f"Could not check the USB connection.\n{detail}"
        raise RuntimeError(msg)
    return _select_device(listing.stdout, requested)


def _default_sdk_directory() -> Path:
    home = Path.home()
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        return (Path(local_app_data) if local_app_data else home / "AppData/Local") / "Android/Sdk"
    if sys.platform == "darwin":
        return home / "Library/Android/sdk"
    return home / "Android/Sdk"


def _downloads_directory() -> Path:
    home = Path.home()
    if sys.platform == "win32":
        return windows_known_folder(_DOWNLOADS) or home / "Downloads"
    if sys.platform == "linux" and (xdg := shutil.which("xdg-user-dir")):
        with suppress(OSError, subprocess.SubprocessError):
            directory = Path(
                subprocess.check_output(  # noqa: S603 - known utility and fixed argument.
                    [xdg, "DOWNLOAD"], text=True, timeout=2
                ).strip()
            )
            if directory.is_absolute() and directory != home:
                return directory
    return home / "Downloads"


def resolve_adb(adb: Path | None) -> str:
    """Prefer an existing ADB, downloading a verified copy as needed."""
    if adb is not None:
        return str(adb.expanduser().resolve())
    if executable := shutil.which("adb"):
        return executable
    filename = "adb.exe" if sys.platform == "win32" else "adb"
    sdks = [
        Path(value).expanduser()
        for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT")
        if (value := os.environ.get(key))
    ]
    for sdk in (*sdks, _default_sdk_directory()):
        if (candidate := sdk / "platform-tools" / filename).is_file():
            return str(candidate.resolve())
    downloads = _downloads_directory()
    archive_platform = "windows" if sys.platform == "win32" else sys.platform
    for root in (downloads, downloads / f"platform-tools-latest-{archive_platform}"):
        if (candidate := root / "platform-tools" / filename).is_file():
            return str(candidate.resolve())
    return str(download_adb())


def probe(*, adb: Path | None = None, device: str | None = None) -> DeviceProbe:
    """Inspect one authorized device without changing its apps, settings or runtime."""
    executable = resolve_adb(adb)
    selected = select_device(executable, device)

    def shell(*arguments: str) -> subprocess.CompletedProcess[str]:
        return _run(executable, "-s", selected, "shell", *arguments)

    properties = shell("getprop")
    if properties.returncode:
        msg = "Cannot read the selected headset's Android properties."
        raise RuntimeError(msg)
    parsed = dict(re.findall(r"^\[([^\]]+)\]: \[([^\]]*)\]$", properties.stdout, re.MULTILINE))
    facts = {name: parsed.get(key, "unknown") for name, key in _PROPERTIES.items()}
    memory = shell("cat", "/proc/meminfo")
    match = re.search(r"^MemTotal:\s+(\d+) kB", memory.stdout, re.MULTILINE)
    brokers: list[Broker] = []
    for authority in (
        "org.khronos.openxr.system_runtime_broker",
        "org.khronos.openxr.runtime_broker",
    ):
        uri = f"content://{authority}/openxr/1/abi/arm64-v8a/runtimes/active"
        result = shell("content", "query", "--uri", uri)
        response = (result.stdout + result.stderr).strip()
        brokers.append(Broker(authority, _broker_status(response, result.returncode), response))
    candidates = tuple(
        f"/{partition}/lib64/libpxrunityxrcore.pi.so" for partition in ("system", "vendor")
    )
    libraries = shell("ls", *candidates)
    available = tuple(line for line in libraries.stdout.splitlines() if line in candidates)
    return DeviceProbe(
        selected, facts, int(match[1]) // 1024 if match else None, tuple(brokers), available
    )
