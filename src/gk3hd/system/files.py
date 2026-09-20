"""Small, durable filesystem helpers shared by installers."""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import stat
import tempfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


def sha256_file(
    path: Path,
    *,
    chunk_size: int = 1024 * 1024,
    progress: Callable[[int, int], None] | None = None,
) -> str:
    """Return the lowercase SHA-256 digest of one file."""
    digest = hashlib.sha256()
    total = path.stat().st_size
    completed = 0
    if progress is not None:
        progress(0, total)
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
            completed += len(chunk)
            if progress is not None:
                progress(completed, total)
    return digest.hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    """Durably replace bytes, preserving mode and never truncating on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if existing_mode is not None:
            temporary.chmod(existing_mode)
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def cache_directory() -> Path:
    """Return a platform-appropriate per-user cache root for gk3hd."""
    if local_app_data := os.environ.get("LOCALAPPDATA"):
        return Path(local_app_data) / "gk3hd" / "cache"
    if xdg_cache := os.environ.get("XDG_CACHE_HOME"):
        return Path(xdg_cache) / "gk3hd"
    return Path.home() / ".cache" / "gk3hd"


def json_bytes(payload: object) -> bytes:
    """Encode deterministic, readable JSON for persisted evidence and hashes."""
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def is_sha256(value: object) -> bool:
    """Whether a value is a canonical lowercase SHA-256 identity."""
    return (
        isinstance(value, str)
        and len(value) == hashlib.sha256().digest_size * 2
        and all(character in "0123456789abcdef" for character in value)
    )


def is_portable_filename(value: str) -> bool:
    """Accept one ordinary filename safe on both Windows and POSIX."""
    pure = PurePosixPath(value)
    return (
        bool(value)
        and pure.name == value
        and not pure.is_absolute()
        and ".." not in pure.parts
        and not ntpath.isreserved(value)
        and not any(character in '<>:"/\\|?*' for character in value)
        and not value.endswith((".", " "))
    )
