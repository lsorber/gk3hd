"""Fetch and cache the ADB files published by the Android Open Source Project."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from base64 import b64decode
from pathlib import Path
from typing import TypedDict, cast

from gk3hd.system.download import DownloadError, download_verified
from gk3hd.system.files import atomic_write, cache_directory, sha256_file
from gk3hd.system.locking import ExclusiveFileLock

_UPSTREAM = (
    "https://android.googlesource.com/platform/prebuilts/android-emulator-build/system-images"
)
_PIN = Path(__file__).with_name("adb-prebuilts.json")


class _Blob(TypedDict):
    size: int
    sha256: str
    decoded_sha256: str


class _Release(TypedDict):
    commit: str
    hosts: dict[str, dict[str, _Blob]]


def _matches(path: Path, pin: _Blob) -> bool:
    return (
        not path.is_symlink()
        and path.is_file()
        and 0 < path.stat().st_size <= pin["size"]
        and sha256_file(path) == pin["decoded_sha256"]
    )


def download_adb() -> Path:
    """Reuse a verified cache or fetch ADB and its required libraries and notices."""
    release = cast("_Release", json.loads(_PIN.read_bytes()))
    host = "windows" if sys.platform == "win32" else sys.platform
    files = release["hosts"].get(host)
    if files is None or (host == "linux" and platform.machine() != "x86_64"):
        msg = "Automatic ADB setup is unavailable on this platform. Install ADB or pass --adb."
        raise RuntimeError(msg)
    commit = release["commit"]
    root = cache_directory() / "adb" / commit / host
    executable = root / ("adb.exe" if host == "windows" else "adb")
    if os.access(executable, os.X_OK) and all(
        _matches(root / name, pin) for name, pin in files.items()
    ):
        return executable

    with ExclusiveFileLock(root / ".download.lock"):
        for name, pin in files.items():
            target = root / name
            if _matches(target, pin):
                continue
            encoded = download_verified(
                f"{_UPSTREAM}/+/{commit}/{host}/platform-tools/{name}?format=TEXT",
                target.with_name(target.name + ".base64"),
                sha256=pin["sha256"],
                size=pin["size"],
            )
            # Gitiles serves each pinned file as base64, independently of its archive format.
            data = b64decode(encoded.read_bytes(), validate=True)
            if hashlib.sha256(data).hexdigest() != pin["decoded_sha256"]:
                msg = f"Downloaded ADB file failed verification: {name}"
                raise DownloadError(msg)
            atomic_write(target, data)
            encoded.unlink()
        if not os.access(executable, os.X_OK):
            executable.chmod(0o755)
    return executable
