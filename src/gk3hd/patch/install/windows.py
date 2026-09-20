"""Windows registry, INI, proxy, and process installation policy."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
from ctypes import wintypes
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from gk3hd.patch.install.configuration import GraphicsBackend
from gk3hd.patch.install.launcher import (
    LAUNCHER_SURFACE,
    decode_launcher,
    encode_launcher,
    launcher_path,
    prepare_launcher,
    validate_launcher_change,
)
from gk3hd.patch.manifest import ExternalChange
from gk3hd.renderer.distribution import CONFIG_NAME as D7VK_CONFIG_NAME
from gk3hd.renderer.distribution import DLL_NAME as D7VK_DLL_NAME
from gk3hd.renderer.distribution import DLL_SHA256 as D7VK_DLL_SHA256
from gk3hd.renderer.distribution import cached_dll_matches, retain_dll
from gk3hd.renderer.distribution import config_bytes as d7vk_config_bytes
from gk3hd.renderer.distribution import dll_bytes as d7vk_dll_bytes
from gk3hd.system.files import atomic_write
from gk3hd.system.proton import is_gk3_running as proton_game_running

if os.name == "nt":
    import winreg

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from gk3hd.patch.model import PatchId

ENGINE_KEY = r"Software\Sierra On-Line\Gabriel Knight 3\Engine"
HARDWARE_KEY = ENGINE_KEY + r"\Hardware"
RESOLUTION_VALUES = (
    "Game Width",
    "Game Height",
    "Screen Width",
    "Screen Height",
    "Full Screen",
)
QUALITY_VALUES = (
    "Incremental Rendering",
    "Mip Mapping",
    "Interpolation",
    "Trilinear Filtering",
    "Lod",
    "Max Anisotropy Level",
    "Gamma",
    "Surface Quality",
)
_REGISTRY_SURFACE = f"registry:HKCU\\{ENGINE_KEY}"
_HARDWARE_REGISTRY_SURFACE = f"registry:HKCU\\{HARDWARE_KEY}"
_APP_COMPAT_LAYERS_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
_APP_COMPAT_SURFACE = f"registry:HKCU\\{_APP_COMPAT_LAYERS_KEY}"
# GK3 needs Microsoft's 16-bit DirectDraw mitigation to initialize, while the
# explicit DPI token keeps its viewport, input, and DirectDraw surfaces in one
# physical-pixel coordinate system on scaled modern desktops.
_GK3_APP_COMPAT_LAYERS = ("DWM8And16BitMitigation", "HIGHDPIAWARE")
_INI_SURFACE = "file"
_D7VK_DLL_SURFACE = "file:d7vk-binary"
_BYTES_PREFIX = "base64:"
_SHA256_PREFIX = "sha256:"
GRAPHICS_PROXY_DLL_NAMES = ("ddraw.dll", "d3dimm.dll", "d3d8.dll", "d3d9.dll")
_SDB_UPDATES_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\SdbUpdates"
_WINDOWS_UPDATE_REBOOT_KEYS = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
    # Feature upgrades can be staged under CommitRequired without creating the
    # older RebootRequired key. An ordinary shutdown.exe restart bypasses that
    # commit; Update Orchestrator must own the restart before AppCompat merging
    # is re-enabled.
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\CommitRequired",
)


@dataclass(frozen=True, slots=True)
class Gk3LaunchCompatibilityState:
    """Read-only Windows state needed by GK3's registered DirectDraw shim."""

    appcompat_merge_disabled: bool
    windows_update_reboot_required: bool

    def blocker(self) -> str | None:
        """Explain a deterministic native-launch failure, when one is active."""
        if not self.appcompat_merge_disabled:
            return None
        if self.windows_update_reboot_required:
            return (
                "native GK3 launch is temporarily unavailable: Windows Update has disabled "
                "merged AppCompat databases and requires a restart, so GK3's registered "
                "16-bit DirectDraw compatibility shim cannot load"
            )
        return (
            "native GK3 launch is unreliable because Windows retained the protected "
            "AppCompat servicing value DisableMergeSdbs=1 after restart; complete Windows "
            "servicing or clear that stale value from an elevated session before launching"
        )


def clean_gk3_launch_environment(
    environment: Mapping[str, str] | None = None,
) -> tuple[dict[str, str], str | None]:
    """Copy an environment without a host-only AppCompat override.

    Codex and compatibility troubleshooters can themselves run under a
    process-local ``__COMPAT_LAYER`` such as ``DetectorsAppHealth``. Ordinary
    children inherit it, overriding GK3's executable-specific registered shim
    and causing a false 16-bit-color failure. Preserve every other value and
    let Windows apply policy registered for the target executable.
    """
    launch_environment = dict(os.environ if environment is None else environment)
    inherited_compat_layer = launch_environment.pop("__COMPAT_LAYER", None)
    return launch_environment, inherited_compat_layer


def read_gk3_launch_compatibility_state() -> Gk3LaunchCompatibilityState:
    """Inspect, but never modify, machine-wide AppCompat/update state.

    Windows Update temporarily sets ``DisableMergeSdbs`` while servicing the
    compatibility database. GK3 can then see the 32-bit desktop directly
    instead of Microsoft's registered ``DWM8And16BitMitigation`` layer and
    abort with its obsolete 16-bit-color dialog. A completing restart normally
    clears the value; if Windows retains it, cached executable bytes may launch
    once while rebuilt identities fail, so the host remains unsuitable for a
    deterministic patch or visual-validation run.
    """
    merge_disabled = False
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _SDB_UPDATES_KEY) as key:
            value, _value_type = winreg.QueryValueEx(key, "DisableMergeSdbs")
            merge_disabled = int(value) == 1
    except (OSError, TypeError, ValueError):
        # Missing/unreadable policy must not become a false blocker. The
        # capture driver's owned-window classifier remains the final oracle.
        merge_disabled = False

    reboot_required = False
    for reboot_key in _WINDOWS_UPDATE_REBOOT_KEYS:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reboot_key):
                reboot_required = True
                break
        except OSError:
            continue

    return Gk3LaunchCompatibilityState(
        appcompat_merge_disabled=merge_disabled,
        windows_update_reboot_required=reboot_required,
    )


class ConfigurationError(Exception):
    """Report conflicting, failed, or unverifiable external configuration."""


class RegistryBackend(Protocol):
    """Read and write serialized values under GK3's engine registry key."""

    def read(self, name: str) -> str | None:
        """Return a typed serialized value, or ``None`` when absent."""
        ...

    def write(self, name: str, value: str | None) -> None:
        """Write a serialized value, or delete it when ``None``."""
        ...


class WindowsRegistryBackend:
    """Access one explicit GK3 per-user registry key through ``winreg``."""

    def __init__(self, key_path: str = ENGINE_KEY) -> None:
        """Bind this adapter to one registry path, without creating it."""
        self.key_path = key_path

    def read(self, name: str) -> str | None:
        """Read one registry value without creating the key."""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key_path) as key:
                value, value_type = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            return None
        return json.dumps(
            {"type": int(value_type), "value": value}, separators=(",", ":"), sort_keys=True
        )

    def write(self, name: str, value: str | None) -> None:
        """Write or remove one registry value."""
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.key_path) as key:
            if value is None:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    return
            else:
                payload = json.loads(value)
                winreg.SetValueEx(key, name, 0, int(payload["type"]), payload["value"])


class WindowsAppCompatRegistryBackend:
    """Access per-executable compatibility layers without machine-wide writes."""

    def read(self, name: str) -> str | None:
        """Read one serialized per-user executable layer value."""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APP_COMPAT_LAYERS_KEY) as key:
                value, value_type = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            return None
        return json.dumps(
            {"type": int(value_type), "value": value}, separators=(",", ":"), sort_keys=True
        )

    def write(self, name: str, value: str | None) -> None:
        """Write or remove one per-user executable layer value."""
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _APP_COMPAT_LAYERS_KEY) as key:
            if value is None:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    return
            else:
                payload = json.loads(value)
                winreg.SetValueEx(key, name, 0, int(payload["type"]), payload["value"])


@dataclass(slots=True)
class WindowsInstallConfiguration:
    """Transactionally manage GK3 resolution, quality, DPI policy, and HD paths."""

    registry: RegistryBackend
    hardware: RegistryBackend
    appcompat: RegistryBackend
    manage_appcompat: bool = True

    def __init__(
        self,
        registry: RegistryBackend | None = None,
        hardware: RegistryBackend | None = None,
        appcompat: RegistryBackend | None = None,
    ) -> None:
        """Use live per-user stores unless deterministic backends are supplied."""
        self.manage_appcompat = True
        self.registry = WindowsRegistryBackend() if registry is None else registry
        if hardware is not None:
            self.hardware = hardware
        elif registry is not None:
            self.hardware = registry
        else:
            self.hardware = WindowsRegistryBackend(HARDWARE_KEY)
        if appcompat is not None:
            self.appcompat = appcompat
        elif registry is not None:
            # A shared generic fake keeps isolated tests concise; production
            # uses the separately rooted Windows implementation below.
            self.appcompat = registry
        else:
            self.appcompat = WindowsAppCompatRegistryBackend()

    def prepare(
        self,
        *,
        exe: Path,
        width: int,
        height: int,
        patches: tuple[PatchId, ...] = (),
        graphics_backend: GraphicsBackend = GraphicsBackend.NATIVE,
    ) -> tuple[ExternalChange, ...]:
        """Capture current values and calculate the exact desired state."""
        del graphics_backend
        desired = {
            "Game Width": width,
            "Game Height": height,
            "Screen Width": width,
            "Screen Height": height,
            "Full Screen": 1,
        }
        changes = [
            ExternalChange(
                surface=_REGISTRY_SURFACE,
                key=name,
                previous=self.registry.read(name),
                installed=_registry_dword(value),
            )
            for name, value in desired.items()
        ]
        if "maximize_graphics_quality" in patches:
            quality = {
                # GK3's retained-damage producer is optional and corrupts 3D
                # models on modern DirectDraw implementations. The modern
                # presentation backend makes authoritative full-frame draws
                # exceed display cadence without relying on that fragile path.
                "Incremental Rendering": _registry_dword(0),
                "Mip Mapping": _registry_dword(1),
                "Interpolation": _registry_dword(1),
                "Trilinear Filtering": _registry_dword(1),
                "Lod": _registry_dword(100),
                # The executable patch resolves DWORD(-1) to the live device
                # ceiling after capability detection rather than freezing a
                # GPU-specific number at installation time.
                "Max Anisotropy Level": _registry_dword(0xFFFFFFFF),
                # The executable patch makes 1.0 a true identity ramp while
                # retaining GK3's native power function for user adjustment.
                # Color policy is therefore independent of presentation.
                "Gamma": _registry_string("1.000000"),
                "Surface Quality": _registry_string("High"),
            }
            changes.extend(
                ExternalChange(
                    surface=_HARDWARE_REGISTRY_SURFACE,
                    key=name,
                    previous=self.hardware.read(name),
                    installed=value,
                )
                for name, value in quality.items()
            )
        launcher = prepare_launcher(exe)
        if launcher is not None:
            changes.append(launcher)
        return tuple(changes)

    def prepare_renderer(self, *, exe: Path, digest: str) -> tuple[ExternalChange, ...]:
        """Own the DLL, presentation configuration and launch compatibility separately."""
        retain_dll(exe.with_name(D7VK_DLL_NAME))
        config_path = exe.with_name(D7VK_CONFIG_NAME)
        previous = config_path.read_bytes() if config_path.is_file() else None
        changes = [
            ExternalChange(
                surface=_D7VK_DLL_SURFACE,
                key=D7VK_DLL_NAME,
                previous=_file_sha256_marker(exe.with_name(D7VK_DLL_NAME)),
                installed=_SHA256_PREFIX + digest,
            ),
            ExternalChange(
                surface=_INI_SURFACE,
                key=D7VK_CONFIG_NAME,
                previous=_encode_bytes(previous) if previous is not None else None,
                installed=_encode_bytes(
                    d7vk_config_bytes(executable_name=exe.name, previous=previous or b"")
                ),
            ),
        ]
        if not self.manage_appcompat:
            return tuple(changes)
        appcompat_key = str(exe.resolve())
        previous_appcompat = self.appcompat.read(appcompat_key)
        changes.append(
            ExternalChange(
                surface=_APP_COMPAT_SURFACE,
                key=appcompat_key,
                previous=previous_appcompat,
                installed=required_gk3_appcompat_layers(
                    previous_appcompat, graphics_backend=GraphicsBackend.D7VK
                ),
            )
        )
        return tuple(changes)

    def apply(self, *, exe: Path, changes: tuple[ExternalChange, ...]) -> None:
        """Apply the prepared state if no value changed since preparation."""
        self._require_values(exe=exe, changes=changes, installed=False)
        self._set_values(exe=exe, changes=changes, installed=True)

    def verify(self, *, exe: Path, changes: tuple[ExternalChange, ...]) -> None:
        """Require every configured value to equal the manifest state."""
        self._require_values(exe=exe, changes=changes, installed=True)

    def rollback(self, *, exe: Path, changes: tuple[ExternalChange, ...]) -> None:
        """Restore pre-install state after a failed application."""
        self._set_values(exe=exe, changes=changes, installed=False)

    def recover_interrupted_apply(
        self,
        *,
        exe: Path,
        changes: tuple[ExternalChange, ...],
    ) -> None:
        """Undo only installer-owned partial values after a killed process.

        Every value must still equal either its captured pre-install state or
        its intended installed state. An unrecognized value is a later user or
        third-party edit, so recovery retains all evidence and refuses to
        overwrite it.
        """
        for change in changes:
            current = self._read_value(exe=exe, change=change)
            if current not in {change.previous, change.installed}:
                msg = (
                    f"{change.surface} value {change.key!r} changed outside the "
                    "interrupted installation; refusing automatic recovery"
                )
                raise ConfigurationError(msg)
        self._set_values(exe=exe, changes=changes, installed=False)

    def restore(
        self,
        *,
        exe: Path,
        changes: tuple[ExternalChange, ...],
        force: bool,
    ) -> None:
        """Restore captured values unless a later user edit must be protected."""
        if not force:
            self._require_values(exe=exe, changes=changes, installed=True)
        self._set_values(exe=exe, changes=changes, installed=False)

    def reinstall(self, *, exe: Path, changes: tuple[ExternalChange, ...]) -> None:
        """Reapply manifest values while rolling back a failed restore."""
        self._set_values(exe=exe, changes=changes, installed=True)

    def _require_values(
        self,
        *,
        exe: Path,
        changes: tuple[ExternalChange, ...],
        installed: bool,
    ) -> None:
        for change in changes:
            expected = change.installed if installed else change.previous
            current = self._read_value(exe=exe, change=change)
            if current != expected:
                state = "installed" if installed else "captured pre-install"
                msg = f"{change.surface} value {change.key!r} no longer matches its {state} state"
                raise ConfigurationError(msg)

    def _set_values(
        self,
        *,
        exe: Path,
        changes: tuple[ExternalChange, ...],
        installed: bool,
    ) -> None:
        snapshots = tuple(self._read_value(exe=exe, change=change) for change in changes)
        completed = 0
        try:
            for change in changes:
                value = change.installed if installed else change.previous
                self._write_value(exe=exe, change=change, value=value)
                completed += 1
        except Exception:
            # Restore the exact entry state rather than assuming every value
            # began at the logical opposite state. This matters for forced
            # restores and for resumable recovery from partially written data.
            for index in range(completed - 1, -1, -1):
                self._write_value(
                    exe=exe,
                    change=changes[index],
                    value=snapshots[index],
                )
            raise

    def _read_value(self, *, exe: Path, change: ExternalChange) -> str | None:
        self._validate_change_target(change, exe=exe)
        if change.surface == _REGISTRY_SURFACE:
            return self.registry.read(change.key)
        if change.surface == _HARDWARE_REGISTRY_SURFACE:
            return self.hardware.read(change.key)
        if change.surface == _APP_COMPAT_SURFACE:
            return self.appcompat.read(change.key)
        if change.surface == _INI_SURFACE:
            path = exe.with_name(change.key)
            return _encode_bytes(path.read_bytes()) if path.is_file() else None
        if change.surface == LAUNCHER_SURFACE:
            path = launcher_path(exe, change.key)
            return encode_launcher(path.read_bytes()) if path.is_file() else None
        if change.surface == _D7VK_DLL_SURFACE:
            return _file_sha256_marker(exe.with_name(change.key))
        raise AssertionError(change.surface)

    def _write_value(self, *, exe: Path, change: ExternalChange, value: str | None) -> None:
        self._validate_change_target(change, exe=exe)
        if change.surface == _REGISTRY_SURFACE:
            self.registry.write(change.key, value)
            return
        if change.surface == _HARDWARE_REGISTRY_SURFACE:
            self.hardware.write(change.key, value)
            return
        if change.surface == _APP_COMPAT_SURFACE:
            self.appcompat.write(change.key, value)
            return
        if change.surface == _INI_SURFACE:
            path = exe.with_name(change.key)
            if value is None:
                path.unlink(missing_ok=True)
            else:
                _atomic_write(path, _decode_bytes(value))
            return
        if change.surface == LAUNCHER_SURFACE:
            if value is None:
                message = "a Steam launcher transaction must retain its original executable"
                raise ConfigurationError(message)
            _atomic_write(launcher_path(exe, change.key), decode_launcher(value))
            return
        if change.surface == _D7VK_DLL_SURFACE:
            self._write_graphics_proxy(exe.with_name(change.key), value)
            return
        raise AssertionError(change.surface)

    @staticmethod
    def _write_graphics_proxy(path: Path, value: str | None) -> None:
        if value is None:
            path.unlink(missing_ok=True)
        elif value.startswith(_SHA256_PREFIX):
            _atomic_write(path, d7vk_dll_bytes(sha256=value[len(_SHA256_PREFIX) :]))
        else:
            message = f"unsupported graphics proxy binary identity: {value}"
            raise ConfigurationError(message)

    @staticmethod
    def _validate_change_target(change: ExternalChange, *, exe: Path | None = None) -> None:
        """Admit only external state explicitly owned by this installer."""
        if change.surface == LAUNCHER_SURFACE and exe is not None:
            validate_launcher_change(exe, change)
            return
        registry_value = change.surface == _REGISTRY_SURFACE and change.key in RESOLUTION_VALUES
        quality_value = (
            change.surface == _HARDWARE_REGISTRY_SURFACE and change.key in QUALITY_VALUES
        )
        appcompat_value = (
            change.surface == _APP_COMPAT_SURFACE
            and exe is not None
            and change.key.casefold() == str(exe.resolve()).casefold()
        )
        managed_file = change.surface == _INI_SURFACE and change.key in {
            "GK3.ini",
            D7VK_CONFIG_NAME,
        }
        d7vk_binary = change.surface == _D7VK_DLL_SURFACE and change.key == D7VK_DLL_NAME
        if (
            not registry_value
            and not quality_value
            and not appcompat_value
            and not managed_file
            and not d7vk_binary
        ):
            msg = f"unsupported external configuration target: {change.surface}:{change.key}"
            raise ConfigurationError(msg)


def is_gk3_running() -> bool:
    """Detect the game or a visual reference process; fail closed on probe errors."""
    if os.name != "nt":
        return proton_game_running()

    snapshot_flag = 0x00000002
    no_more_files = 18
    invalid_handle = ctypes.c_void_p(-1).value
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    # ctypes otherwise assumes c_int returns/arguments, truncating HANDLEs
    # on a 64-bit host and making INVALID_HANDLE_VALUE impossible to detect.
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        function = getattr(kernel32, name)
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        function.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(snapshot_flag, 0)
    if snapshot == invalid_handle:
        msg = f"cannot inspect running processes (Windows error {ctypes.get_last_error()})"
        raise ConfigurationError(msg)
    entry = ProcessEntry()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        present = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
        while present:
            if entry.szExeFile.casefold() in {"gk3.exe", "gk3hd-visual-reference.exe"}:
                return True
            present = bool(kernel32.Process32NextW(snapshot, ctypes.byref(entry)))
        # ERROR_NO_MORE_FILES is the only successful end of enumeration.
        # A failed probe must not authorize changes to a possibly live game.
        if ctypes.get_last_error() != no_more_files:
            msg = f"cannot enumerate running processes (Windows error {ctypes.get_last_error()})"
            raise ConfigurationError(msg)
    finally:
        kernel32.CloseHandle(snapshot)
    return False


def local_graphics_proxy_dlls(
    game_dir: Path,
    *,
    allow_owned_d7vk: bool = False,
) -> tuple[str, ...]:
    """Return unowned graphics proxies beside GK3.

    Only a verified cached, bundled, or journaled D7VK binary is admitted. Other local proxies
    conflict with the requested renderer, including every proxy in native mode.
    """
    conflicts: list[str] = []
    for name in GRAPHICS_PROXY_DLL_NAMES:
        path = game_dir / name
        if not path.is_file():
            continue
        if allow_owned_d7vk and name == D7VK_DLL_NAME and _owned_renderer(path):
            continue
        conflicts.append(name)
    return tuple(conflicts)


def _owned_renderer(path: Path) -> bool:
    marker = _file_sha256_marker(path)
    if marker is None:
        return False
    digest = marker[len(_SHA256_PREFIX) :]
    if digest == D7VK_DLL_SHA256 or cached_dll_matches(digest):
        return True
    from gk3hd.renderer.state import RendererState  # noqa: PLC0415 - avoid adapter import cycles.

    # Installed ownership must survive cache eviction and future renderer releases.
    state = RendererState.owner(path.parent)
    return state is not None and state.digest == digest


def _file_sha256_marker(path: Path) -> str | None:
    """Identify one existing sidecar without embedding binary bytes in JSON."""
    if not path.is_file():
        return None
    return _SHA256_PREFIX + hashlib.sha256(path.read_bytes()).hexdigest()


def _registry_dword(value: int) -> str:
    return json.dumps({"type": 4, "value": value}, separators=(",", ":"), sort_keys=True)


def _registry_string(value: str) -> str:
    return json.dumps({"type": 1, "value": value}, separators=(",", ":"), sort_keys=True)


def required_gk3_appcompat_layers(
    previous: str | None,
    *,
    graphics_backend: GraphicsBackend = GraphicsBackend.NATIVE,
) -> str:
    """Merge GK3's required tokens with an existing serialized layer value.

    Both the durable installer and temporary visual-validation transaction use
    this one policy. Keeping the merge here prevents a capture from silently
    exercising a different DPI/DirectDraw environment than the installed game.
    """
    existing: list[str] = []
    if previous is not None:
        try:
            payload = json.loads(previous)
            value = payload["value"]
            if int(payload["type"]) != 1 or not isinstance(value, str):
                msg = "GK3 AppCompat layer must be a string registry value"
                raise ConfigurationError(msg)
            existing = value.split()
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            msg = "GK3 AppCompat layer has an invalid serialized registry value"
            raise ConfigurationError(msg) from exc
    by_name = {token.casefold(): token for token in existing}
    required_layers = _GK3_APP_COMPAT_LAYERS
    if graphics_backend is GraphicsBackend.D7VK:
        # GK3's CPU blitters write RGB565. D7VK delegates surface creation to
        # Windows DirectDraw, which otherwise supplies X8R8G8B8 despite the
        # DWM mitigation. Reinterpreting those 16-bit writes as 32-bit pixels
        # produces a half-width, pink/green image even in the stock game.
        if "256color" in by_name:
            msg = "D7VK requires 16-bit color; remove GK3's conflicting 256-color setting"
            raise ConfigurationError(msg)
        required_layers += ("16BITCOLOR",)
    for required in required_layers:
        by_name.setdefault(required.casefold(), required)
    installed = " ".join(by_name.values())
    return json.dumps({"type": 1, "value": installed}, separators=(",", ":"), sort_keys=True)


def _encode_bytes(payload: bytes) -> str:
    return _BYTES_PREFIX + base64.b64encode(payload).decode("ascii")


def _decode_bytes(value: str) -> bytes:
    if not value.startswith(_BYTES_PREFIX):
        msg = "manifest file value is not encoded as bytes"
        raise ConfigurationError(msg)
    return base64.b64decode(value.removeprefix(_BYTES_PREFIX), validate=True)


def _atomic_write(path: Path, payload: bytes) -> None:
    atomic_write(path, payload)
