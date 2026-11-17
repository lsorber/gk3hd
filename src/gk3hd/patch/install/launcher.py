"""Own only the known single-game Steam launcher's reversible handoff."""

from __future__ import annotations

import base64
import configparser
from dataclasses import replace
from typing import TYPE_CHECKING

from gk3hd.patch.definitions.skip_steam_launcher import UnsupportedLauncherError, build_launcher
from gk3hd.patch.manifest import ExternalChange

if TYPE_CHECKING:
    from pathlib import Path

LAUNCHER_SURFACE = "file:steam-launcher"
LAUNCHER_NAME = "SierraLauncher.exe"
_INI_NAME = "SierraLauncher.ini"
_BYTES_PREFIX = "base64:"


def _find(root: Path, name: str) -> Path | None:
    matches = [path for path in root.iterdir() if path.name.casefold() == name.casefold()]
    return matches[0] if len(matches) == 1 else None


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


def prepare_launcher(exe: Path, *, owned: ExternalChange | None = None) -> ExternalChange | None:
    """Capture the launcher only when its INI selects this exact single game."""
    root = exe.parent.parent
    config = configparser.ConfigParser(interpolation=None)
    try:
        candidate = _find(root, LAUNCHER_NAME)
        ini = _find(root, _INI_NAME)
        if (
            candidate is None
            or ini is None
            or candidate.is_symlink()
            or not candidate.is_file()
            or not ini.is_file()
        ):
            return None
        config.read_string(ini.read_text(encoding="utf-8-sig"))
        settings = config["Launcher"]
    except (OSError, UnicodeError, configparser.Error, KeyError):
        return None
    expected = {
        "NumButtons": "1",
        "Game1Prog": "other",
        "Game1Path": exe.parent.name,
        "Game1Exe": exe.name,
    }
    # Custom INI arguments must not silently disappear when bypassing the menu.
    if settings.get("Game1Cmd", "").strip() or any(
        settings.get(key, "").casefold() != value.casefold() for key, value in expected.items()
    ):
        return None
    if owned is not None and owned.key.casefold() == candidate.name.casefold():
        # The installer has verified the prior manifest and the on-disk bytes.
        return replace(owned, previous=owned.installed)
    try:
        original = launcher_path(exe, candidate.name).read_bytes()
        patched = build_launcher(original, game_directory=exe.parent.name, exe_name=exe.name)
    except (OSError, UnsupportedLauncherError):
        return None
    return ExternalChange(
        surface=LAUNCHER_SURFACE,
        key=candidate.name,
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
    if change.previous is None or change.installed is None:
        message = "Steam launcher transaction has no original executable"
        raise ValueError(message)
    first, second = map(decode_launcher, (change.previous, change.installed))
    try:
        expected = build_launcher(first, game_directory=exe.parent.name, exe_name=exe.name)
    except UnsupportedLauncherError:
        # Updating can retire the bypass and restore the stock menu.
        first, second = second, first
        expected = build_launcher(first, game_directory=exe.parent.name, exe_name=exe.name)
    if second != expected:
        message = "Steam launcher transaction does not match the verified handoff"
        raise ValueError(message)
