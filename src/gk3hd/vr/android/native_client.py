"""Package source-built ARM64 graphics libraries as bounded, verified APK assets."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

if sys.version_info >= (3, 14):
    from compression import zstd
else:
    zstd = None

MAX_CLIENT_BYTES = 1024 * 1024
MIN_ELF_HEADER_BYTES = 20
CLI_ARGUMENT_COUNT = 4
ELF_ARM64_SHARED = b"\x03\x00\xb7\x00"
ELF_ID = b"\x7fELF\x02\x01"


def _library(source: Path, label: str) -> bytes:
    if (
        not source.is_file()
        or not MIN_ELF_HEADER_BYTES <= source.stat().st_size <= MAX_CLIENT_BYTES
    ):
        msg = f"{label} is missing or exceeds its bound"
        raise ValueError(msg)
    data = source.read_bytes()
    if data[: len(ELF_ID)] != ELF_ID or data[16:20] != ELF_ARM64_SHARED:
        msg = f"{label} must be an ARM64 shared ELF library"
        raise ValueError(msg)
    return data


def build_asset(source: Path, app: Path, *, allocation: Path) -> dict[str, str | int]:
    """Write deterministic assets without overwriting a different build's files."""
    if zstd is None:
        msg = "Standalone client builds require Python 3.14 or newer"
        raise RuntimeError(msg)
    data = _library(source, "Native Vulkan client")
    allocation_data = _library(allocation, "GPU allocation compatibility library")
    memory = io.BytesIO()
    with tarfile.open(fileobj=memory, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        entry = tarfile.TarInfo("./usr/lib/libvulkan_vortek.so")
        entry.size, entry.mode, entry.mtime = len(data), 0o755, 0
        archive.addfile(entry, io.BytesIO(data))
    packed = zstd.compress(memory.getvalue(), level=12)
    if len(packed) > MAX_CLIENT_BYTES:
        msg = "Native Vulkan archive exceeds its bound"
        raise ValueError(msg)
    record = {
        "client_sha256": hashlib.sha256(data).hexdigest(),
        "client_bytes": len(data),
        "archive_sha256": hashlib.sha256(packed).hexdigest(),
        "allocation_sha256": hashlib.sha256(allocation_data).hexdigest(),
        "allocation_bytes": len(allocation_data),
    }
    outputs = {
        app / "src/main/assets/graphics_driver/gk3hd-vortek.tzst": packed,
        app / "src/main/assets/graphics_driver/libgk3hd_kgsl.so": allocation_data,
        app / "gk3hd-vortek.json": (json.dumps(record, indent=2) + "\n").encode(),
    }
    for path, content in outputs.items():
        if path.is_symlink() or (
            path.exists() and (not path.is_file() or path.read_bytes() != content)
        ):
            msg = "Existing native Vulkan build assets differ; use a fresh build directory"
            raise FileExistsError(msg)
    for path, content in outputs.items():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    return record


if __name__ == "__main__":
    if len(sys.argv) != CLI_ARGUMENT_COUNT:
        msg = "Usage: native_client.py SOURCE_LIBRARY APP_DIRECTORY ALLOCATION_LIBRARY"
        raise SystemExit(msg)
    sys.stdout.write(
        json.dumps(build_asset(Path(sys.argv[1]), Path(sys.argv[2]), allocation=Path(sys.argv[3])))
        + "\n"
    )
