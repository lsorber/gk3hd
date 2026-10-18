"""Read-only discovery of the runtime selected for GK3's 32-bit OpenXR loader."""

from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path

from gk3hd.system.steam import installed_app, steam_libraries, steam_roots

if os.name == "nt":
    import winreg

_KEY = r"SOFTWARE\Khronos\OpenXR\1"
_MAX_MANIFEST = 1024 * 1024
_DOS_HEADER_BYTES = 64
_PE_HEADER_BYTES = 26
_X86_MACHINE = 0x14C
_PE32_MAGIC = 0x10B


class RuntimeUnavailableError(RuntimeError):
    """Report actionable runtime setup problems, not a silent flat fallback."""


@dataclass(frozen=True, slots=True)
class RuntimeSelection:
    """Valid manifest and x86 library, not yet a headset/session qualification."""

    manifest: Path
    library: Path


def _registered_runtime() -> Path | None:
    if os.name != "nt":
        msg = "the first VR prototype currently supports Windows OpenXR only"
        raise RuntimeUnavailableError(msg)
    try:
        # Open the 32-bit loader's registry view even from 64-bit Python.
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, _KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY
        ) as key:
            value, kind = winreg.QueryValueEx(key, "ActiveRuntime")
    except FileNotFoundError:
        return None
    except OSError as error:
        msg = "cannot read the registered 32-bit OpenXR runtime"
        raise RuntimeUnavailableError(msg) from error
    if kind != winreg.REG_SZ or not isinstance(value, str) or not value:
        msg = "the registered 32-bit OpenXR runtime path is invalid"
        raise RuntimeUnavailableError(msg)
    return Path(value)


def _default_runtime() -> Path:
    registered = _registered_runtime()
    if registered is not None:
        return registered
    # SteamVR can be installed without a 32-bit ActiveRuntime value. Select its
    # own x86 manifest for this child only; never change the user's default.
    for root in steam_roots():
        for library in steam_libraries(root):
            steamvr = installed_app(library, "250820")
            candidate = steamvr / "steamxr_win32.json" if steamvr is not None else None
            if candidate is not None and candidate.is_file():
                return candidate
    msg = "no compatible OpenXR runtime found; install SteamVR or select a 32-bit runtime"
    raise RuntimeUnavailableError(msg)


def _require_x86_library(path: Path) -> None:
    with path.open("rb") as stream:
        header = stream.read(_DOS_HEADER_BYTES)
        if len(header) != _DOS_HEADER_BYTES or header[:2] != b"MZ":
            msg = "OpenXR runtime library is not a Windows PE image"
            raise RuntimeUnavailableError(msg)
        offset = struct.unpack_from("<I", header, 0x3C)[0]
        if offset > _MAX_MANIFEST:
            msg = "OpenXR runtime library has an invalid PE header"
            raise RuntimeUnavailableError(msg)
        stream.seek(offset)
        pe = stream.read(_PE_HEADER_BYTES)
    if (
        len(pe) != _PE_HEADER_BYTES
        or pe[:4] != b"PE\0\0"
        or struct.unpack_from("<H", pe, 4)[0] != _X86_MACHINE
        or struct.unpack_from("<H", pe, 24)[0] != _PE32_MAGIC
        or not struct.unpack_from("<H", pe, 22)[0] & 0x2000
    ):
        msg = "GK3 requires a 32-bit OpenXR runtime DLL; this selection is incompatible"
        raise RuntimeUnavailableError(msg)


def selected_runtime(*, manifest: Path | None = None) -> RuntimeSelection:
    """Validate an explicit override or the loader's ordinary runtime selection.

    This does not create an OpenXR instance or prove a headset is connected.
    No registry or persistent environment setting is changed.
    """
    if os.name != "nt":
        msg = "the first VR prototype currently supports Windows OpenXR only"
        raise RuntimeUnavailableError(msg)
    override = os.environ.get("XR_RUNTIME_JSON")
    selected = manifest or (Path(override) if override else _default_runtime())
    selected = selected.expanduser().resolve()
    try:
        if selected.stat().st_size > _MAX_MANIFEST:
            msg = "OpenXR runtime manifest is too large"
            raise RuntimeUnavailableError(msg)
        data = json.loads(selected.read_text(encoding="utf-8-sig"))
        if (
            not isinstance(data, dict)
            or data.get("file_format_version") != "1.0.0"
            or not isinstance(data.get("runtime"), dict)
            or not isinstance(data["runtime"].get("library_path"), str)
            or not data["runtime"]["library_path"]
        ):
            msg = "OpenXR runtime manifest has an invalid library declaration"
            raise RuntimeUnavailableError(msg)
        library = Path(data["runtime"]["library_path"])
        if not library.is_absolute():
            library = selected.parent / library
        library = library.resolve()
        _require_x86_library(library)
    except (OSError, ValueError) as error:
        msg = f"cannot read the selected OpenXR runtime: {error}"
        raise RuntimeUnavailableError(msg) from error
    return RuntimeSelection(selected, library)
