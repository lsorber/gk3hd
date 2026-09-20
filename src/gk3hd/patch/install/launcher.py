"""Own only the known single-game Steam launcher's reversible handoff."""

from __future__ import annotations

import base64
import configparser
from typing import TYPE_CHECKING

from gk3hd.patch.definitions.skip_steam_launcher import build_launcher
from gk3hd.patch.manifest import ExternalChange

if TYPE_CHECKING:
    from pathlib import Path

LAUNCHER_SURFACE = "file:steam-launcher"
LAUNCHER_NAME = "SierraLauncher.exe"
_INI_NAME = "SierraLauncher.ini"
_BYTES_PREFIX = "base64:"


def _find(root: Path, name: str) -> Path | None:
    matches = [path for path in root.iterdir() if path.name.casefold() == name.casefold()]
    if len(matches) > 1:
        message = f"ambiguous Steam launcher file: {name}"
        raise ValueError(message)
    return matches[0] if matches else None


def launcher_path(exe: Path, name: str) -> Path:
    """Resolve one fixed sibling launcher name, never a manifest-supplied path."""
    if name.casefold() != LAUNCHER_NAME.casefold():
        message = "unsupported Steam launcher filename"
        raise ValueError(message)
    path = exe.parent.parent / name
    if path.is_symlink() or (path.exists() and not path.is_file()):
        message = "refusing to replace a linked or non-file Steam launcher"
        raise ValueError(message)
    return path


def prepare_launcher(exe: Path) -> ExternalChange | None:
    """Capture the launcher only when its INI selects this exact single game."""
    root = exe.parent.parent
    candidate = _find(root, LAUNCHER_NAME)
    ini = _find(root, _INI_NAME)
    if candidate is None or ini is None or not ini.is_file():
        return None
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(ini.read_text(encoding="utf-8-sig"))
    if "Launcher" not in config:
        return None
    settings = config["Launcher"]
    expected = {
        "NumButtons": "1",
        "Game1Prog": "other",
        "Game1Path": exe.parent.name,
        "Game1Exe": exe.name,
    }
    if any(settings.get(key, "").casefold() != value.casefold() for key, value in expected.items()):
        return None
    # Custom INI arguments must not silently disappear when bypassing the menu.
    # The stock GK3 INI has no arguments; a customized launcher stays untouched.
    if settings.get("Game1Cmd", "").strip():
        return None
    path = launcher_path(exe, candidate.name)
    original = path.read_bytes()
    patched = build_launcher(original, game_directory=exe.parent.name, exe_name=exe.name)
    return ExternalChange(
        surface=LAUNCHER_SURFACE,
        key=path.name,
        previous=encode_launcher(original),
        installed=encode_launcher(patched),
    )


def encode_launcher(payload: bytes) -> str:
    """Keep exact original bytes inside the existing transaction journal."""
    return _BYTES_PREFIX + base64.b64encode(payload).decode("ascii")


def decode_launcher(value: str) -> bytes:
    """Decode an explicitly tagged binary value, rejecting malformed metadata."""
    if not value.startswith(_BYTES_PREFIX):
        message = "invalid encoded Steam launcher"
        raise ValueError(message)
    return base64.b64decode(value.removeprefix(_BYTES_PREFIX), validate=True)


def validate_launcher_change(exe: Path, change: ExternalChange) -> None:
    """Reject arbitrary executable bytes or paths supplied through a manifest."""
    launcher_path(exe, change.key)
    if change.previous is None:
        message = "Steam launcher transaction has no original executable"
        raise ValueError(message)
    original = decode_launcher(change.previous)
    expected = build_launcher(original, game_directory=exe.parent.name, exe_name=exe.name)
    if decode_launcher(change.installed) != expected:
        message = "Steam launcher transaction does not match the verified handoff"
        raise ValueError(message)
