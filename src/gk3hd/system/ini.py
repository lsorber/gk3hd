"""Case-preserving, exactly reversible management of GK3 custom paths."""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from gk3hd.system.discovery import find_ini
from gk3hd.system.files import atomic_write, is_sha256

_CUSTOM_PATHS = re.compile(rb"(?im)^[ \t]*CUSTOM PATHS[ \t]*=[ \t]*([^\r\n]*)")
_FIRST_PRINTABLE_ASCII = 32


class IniError(RuntimeError):
    """Report an unsafe or conflicting GK3 INI edit."""


@dataclass(frozen=True, slots=True)
class IniChange:
    """Exact previous and installed bytes for one managed custom-path edit."""

    filename: str
    previous_base64: str | None
    installed_sha256: str

    @property
    def previous(self) -> bytes | None:
        """Decode the exact prior INI bytes."""
        if self.previous_base64 is None:
            return None
        return base64.b64decode(self.previous_base64, validate=True)

    def to_dict(self) -> dict[str, str | None]:
        """Return a strict JSON representation."""
        return {
            "filename": self.filename,
            "previous_base64": self.previous_base64,
            "installed_sha256": self.installed_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> IniChange:
        """Validate and decode a JSON representation."""
        if not isinstance(value, dict):
            msg = "INI state must be an object"
            raise TypeError(msg)
        filename = value.get("filename")
        previous = value.get("previous_base64")
        installed_sha256 = value.get("installed_sha256")
        if not isinstance(filename, str) or filename.casefold() != "gk3.ini":
            msg = "INI state has an invalid filename"
            raise ValueError(msg)
        if previous is not None and not isinstance(previous, str):
            msg = "INI state has invalid previous bytes"
            raise TypeError(msg)
        if not isinstance(installed_sha256, str) or not is_sha256(installed_sha256):
            msg = "INI state has an invalid installed hash"
            raise ValueError(msg)
        change = cls(filename, previous, installed_sha256)
        # Validate recovery bytes before any caller can mutate owned resources.
        _ = change.previous
        return change


def install_custom_path(game_dir: Path, path_name: str = "gk3hd") -> IniChange:
    """Place one relative texture path at the left of GK3's custom paths."""
    change, installed = prepare_custom_path(game_dir, path_name)
    atomic_write(game_dir / change.filename, installed)
    return change


def prepare_custom_path(game_dir: Path, path_name: str = "gk3hd") -> tuple[IniChange, bytes]:
    """Prepare an exactly reversible INI edit without mutating the file."""
    pure = PurePosixPath(path_name)
    if (
        not path_name
        or pure.is_absolute()
        or str(pure) != path_name
        or any(part in {"", ".", ".."} for part in pure.parts)
        or any(char in path_name for char in ';\\:*?"<>|')
        or any(ord(char) < _FIRST_PRINTABLE_ASCII for char in path_name)
    ):
        msg = f"invalid custom path name: {path_name!r}"
        raise IniError(msg)
    ini = find_ini(game_dir) or game_dir / "GK3.ini"
    previous = ini.read_bytes() if ini.is_file() else None
    try:
        encoded_path = path_name.encode("ascii")
    except UnicodeEncodeError as exc:
        msg = f"custom path must contain only ASCII characters: {path_name!r}"
        raise IniError(msg) from exc
    installed = _prepend_custom_path(previous or b"", encoded_path)
    change = IniChange(
        filename=ini.name,
        previous_base64=(None if previous is None else base64.b64encode(previous).decode("ascii")),
        installed_sha256=_sha256_bytes(installed),
    )
    return change, installed


def apply_custom_path(game_dir: Path, change: IniChange, installed: bytes) -> None:
    """Commit INI bytes only when they match the prepared identity."""
    if _sha256_bytes(installed) != change.installed_sha256:
        msg = "prepared GK3 INI bytes do not match their declared identity"
        raise IniError(msg)
    atomic_write(game_dir / change.filename, installed)


def restore_custom_path(game_dir: Path, change: IniChange, *, force: bool = False) -> None:
    """Restore exact previous bytes while protecting later user edits."""
    path = game_dir / change.filename
    if not force and not installed_ini_matches(path, change):
        msg = f"GK3 INI changed after installation: {path.name}"
        raise IniError(msg)
    previous = change.previous
    if previous is None:
        path.unlink(missing_ok=True)
    else:
        atomic_write(path, previous)


def installed_ini_matches(path: Path, change: IniChange) -> bool:
    """Accept the exact install or GK3's equivalent newline rewrite only."""
    if not path.is_file():
        return False
    payload = path.read_bytes()
    normalized = payload.replace(b"\r\n", b"\n")
    candidates = (payload, normalized, normalized.replace(b"\n", b"\r\n"))
    return any(_sha256_bytes(candidate) == change.installed_sha256 for candidate in candidates)


def _prepend_custom_path(payload: bytes, path_name: bytes) -> bytes:
    newline = b"\r\n" if b"\r\n" in payload else b"\n"
    match = _CUSTOM_PATHS.search(payload)
    if match is None:
        prefix = b"CUSTOM PATHS = " + path_name + newline
        return prefix + payload
    values = [value.strip() for value in match.group(1).split(b";") if value.strip()]
    retained = [value for value in values if value.lower() != path_name.lower()]
    replacement = b"CUSTOM PATHS = " + b"; ".join((path_name, *retained))
    return payload[: match.start()] + replacement + payload[match.end() :]


def _sha256_bytes(payload: bytes) -> str:
    """Return the lowercase SHA-256 identity of in-memory INI bytes."""
    return hashlib.sha256(payload).hexdigest()
