"""Own one per-user Windows shortcut to the persistent VR launcher."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
from base64 import b64encode
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from gk3hd.system.discovery import discover_game
from gk3hd.system.files import atomic_write, cache_directory, is_sha256, json_bytes, sha256_file
from gk3hd.system.locking import ExclusiveFileLock

_NAME = "GK3HD VR.lnk"
_RECEIPT = "gk3hd/vr/shortcut.json"
_MAX_BYTES = 64 * 1024
_MAX_IDENTITIES = 2
_PROGRAMS = UUID("A77F5D77-2E2B-44C3-A6A2-ABA601054A51")
_CREATE_LINK = """
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($env:GK3HD_SHORTCUT_PATH)
$link.TargetPath = $env:GK3HD_SHORTCUT_TARGET
$link.Arguments = $env:GK3HD_SHORTCUT_ARGUMENTS
$link.WorkingDirectory = $env:GK3HD_SHORTCUT_GAME
$link.IconLocation = "$env:GK3HD_SHORTCUT_GAME\\GK3-VR.exe,0"
$link.Description = 'Start Gabriel Knight 3 in VR'
$link.Save()
"""


def _persistent_launcher() -> Path | None:
    """Use an executable from a persistent uv install on Windows."""
    uv = shutil.which("uv") if os.name == "nt" else None
    if uv is None:
        return None

    def tool_dir(*options: str) -> Path:
        try:
            report = subprocess.run(  # noqa: S603 - uv on PATH, fixed arguments.
                [uv, "tool", "dir", *options],
                check=True,
                capture_output=True,
                encoding="utf-8",
                timeout=10,
            )
        except subprocess.SubprocessError as exc:
            msg = "Could not locate the persistent uv tool installation"
            raise ValueError(msg) from exc
        return Path(report.stdout.strip()).resolve()

    if Path(sys.prefix).resolve() != (tool_dir() / "gk3hd").resolve():
        return None
    launcher = tool_dir("--bin") / "gk3hd.exe"
    return launcher if launcher.is_file() else None


def _programs() -> Path:
    shell = ctypes.WinDLL("shell32")
    ole = ctypes.WinDLL("ole32")
    programs = (ctypes.c_ubyte * 16).from_buffer_copy(_PROGRAMS.bytes_le)
    result = ctypes.c_wchar_p()
    try:
        status = shell.SHGetKnownFolderPath(ctypes.byref(programs), 0, None, ctypes.byref(result))
        if status != 0 or not result.value:
            msg = "Windows could not resolve the per-user Start menu folder"
            raise ValueError(msg)
        return Path(result.value)
    finally:
        ole.CoTaskMemFree(ctypes.cast(result, ctypes.c_void_p))


def _create(path: Path, launcher: Path, game: Path) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        msg = "Windows PowerShell is required to create the Start menu shortcut"
        raise ValueError(msg)
    environment = os.environ | {
        "GK3HD_SHORTCUT_PATH": str(path),
        "GK3HD_SHORTCUT_TARGET": str(launcher),
        "GK3HD_SHORTCUT_ARGUMENTS": subprocess.list2cmdline(
            ["vr", "launch", "--start-menu", "--game-dir", str(game)]
        ),
        "GK3HD_SHORTCUT_GAME": str(game),
    }
    encoded = b64encode(_CREATE_LINK.encode("utf-16le")).decode("ascii")
    try:
        subprocess.run(  # noqa: S603 - fixed script and separate path inputs.
            [powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            env=environment,
            check=True,
            capture_output=True,
            timeout=20,
        )
    except subprocess.SubprocessError as exc:
        msg = "Windows could not create the GK3HD VR Start menu shortcut"
        raise ValueError(msg) from exc


def show_launch_error(message: str) -> None:
    """Keep a Start menu failure visible until the player dismisses it."""
    if os.name == "nt":
        dialog = ctypes.WinDLL("user32", use_last_error=True).MessageBoxW
        dialog.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
        dialog.restype = ctypes.c_int
        dialog(None, message, "GK3HD VR", 0x10)


def _owned(receipt: Path) -> list[str]:
    if not receipt.exists() and not receipt.is_symlink():
        return []
    if receipt.is_file() and not receipt.is_symlink() and receipt.stat().st_size <= _MAX_BYTES:
        values = json.loads(receipt.read_bytes())
        if (
            isinstance(values, list)
            and 1 <= len(values) <= _MAX_IDENTITIES
            and all(map(is_sha256, values))
        ):
            return values
    msg = "Invalid shortcut ownership record. Existing files were preserved."
    raise ValueError(msg)


def _existing(link: Path, owned: list[str]) -> str | None:
    if not link.exists() and not link.is_symlink():
        return None
    if link.is_file() and not link.is_symlink() and link.stat().st_size <= _MAX_BYTES:
        digest = sha256_file(link)
        if digest in owned:
            return digest
    msg = "The existing GK3HD VR Start menu shortcut is user-edited or owned by another install."
    raise ValueError(msg)


def install(game_dir: Path | None) -> bool:
    """Create or refresh an owned shortcut after the player has been installed."""
    launcher = _persistent_launcher()
    if launcher is None:
        return False
    game = discover_game(game_dir=game_dir).game_dir
    receipt = game / _RECEIPT
    link = _programs() / _NAME
    with ExclusiveFileLock(cache_directory() / "vr/start-menu.lock"):
        owned = _owned(receipt)
        previous = _existing(link, owned)
        with TemporaryDirectory(prefix=".gk3hd-", dir=link.parent) as temporary:
            staged = Path(temporary) / _NAME
            _create(staged, launcher, game)
            if _existing(link, owned) != previous:
                msg = "The Start menu shortcut changed during installation."
                raise ValueError(msg)
            digest = sha256_file(staged)
            # Either known identity is safe to recover if publication is interrupted.
            atomic_write(receipt, json_bytes([digest, previous] if previous else [digest]))
            if previous:
                staged.replace(link)
            else:
                staged.rename(link)
    return True


def uninstall(game: Path) -> None:
    """Remove the unchanged shortcut owned by this installation."""
    receipt = game / _RECEIPT
    if os.name != "nt" or not receipt.exists():
        return
    link = _programs() / _NAME
    with ExclusiveFileLock(cache_directory() / "vr/start-menu.lock"):
        if _existing(link, _owned(receipt)) is not None:
            link.unlink()
        receipt.unlink()
