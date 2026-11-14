"""Package a verified source driver through the host's built-in version mechanism."""

from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import tarfile
from pathlib import Path, PurePosixPath

if sys.version_info >= (3, 14):
    from compression import zstd
else:
    zstd = None

RECIPE = Path(__file__).resolve().parent / "turnip"
PATCHES = (
    "winlator-native-import.patch",
    "vertex-storage-loads.patch",
    "kgsl-waits.patch",
    "queue-failure.patch",
    "compressed-x11.patch",
)
ELF_ARM64_SHARED = b"\x03\x00\xb7\x00"
ELF_ID = b"\x7fELF\x02\x01"
LIBRARIES = (
    "libvulkan_freedreno.so",
    "libxcb-xfixes.so.0",
    "libxcb-shape.so.0",
    "libxshmfence.so.1",
)
COMPRESSED_X11_OPTION = b"MESA_GK3HD_COMPRESSED_X11\0"
MAX_BYTES = 32 * 1024**2
MAX_FILES = 64
MIN_ELF_BYTES = 20
CLI_ARGUMENTS = 3
NOTICES = {
    "licenses/Mesa-license.rst",
    "licenses/Mesa/MIT",
    "licenses/libxcb-xfixes0-copyright.txt",
    "licenses/libxcb-shape0-copyright.txt",
    "licenses/libxshmfence1-copyright.txt",
}


def _payload(source: Path) -> dict[str, bytes]:
    """Verify source identities and collect bounded library/license payloads."""
    record = json.loads((source / "driver-build.json").read_text(encoding="utf-8"))
    pin = json.loads((RECIPE / "upstream.json").read_text(encoding="utf-8"))
    patches = {
        name: hashlib.sha256((RECIPE / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for name in PATCHES
    }
    if (
        record.get("kind") != "standalone-private-source-driver"
        or record.get("mesa") != pin["mesa"]["version"]
        or record.get("archive_sha256") != pin["mesa"]["sha256"]
        or record.get("patches") != patches
        or record.get("minimum_transport") != "four-row-padded-stereo"
        or not isinstance(record.get("files"), dict)
        or not len(LIBRARIES) <= len(record["files"]) <= MAX_FILES
        or not NOTICES.issubset(record["files"])
    ):
        msg = "Driver does not match the pinned source recipe"
        raise ValueError(msg)
    payload: dict[str, bytes] = {}
    total = 0
    for name, expected in record["files"].items():
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"(?:usr/lib|licenses)/[A-Za-z0-9_./-]+", name)
            or ".." in name.split("/")
        ):
            msg = "Unexpected source-driver payload path"
            raise ValueError(msg)
        path = source / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            msg = "Missing, redirected or oversized driver payload"
            raise ValueError(msg)
        data = path.read_bytes()
        total += len(data)
        if total > MAX_BYTES or hashlib.sha256(data).hexdigest() != expected:
            msg = "Source-driver payload failed verification"
            raise ValueError(msg)
        payload[name] = data
    if COMPRESSED_X11_OPTION not in payload.get("usr/lib/libvulkan_freedreno.so", b""):
        msg = "Driver binary lacks the compressed X11 transport from the pinned recipe"
        raise ValueError(msg)
    payload["share/gk3hd/turnip/driver-build.json"] = (json.dumps(record, indent=2) + "\n").encode()
    payload["share/gk3hd/turnip/source-inputs.json"] = (
        (RECIPE / "upstream.json").read_bytes().replace(b"\r\n", b"\n")
    )
    return payload


def build_asset(source: Path, app: Path) -> dict[str, object]:
    """Verify before publishing a versioned archive, descriptor and built-in ID."""
    if zstd is None:
        msg = "Standalone driver packaging requires Python 3.14 or newer"
        raise RuntimeError(msg)
    payload = _payload(source)
    pin = json.loads((RECIPE / "upstream.json").read_text(encoding="utf-8"))
    identities = {}
    for name in LIBRARIES:
        data = payload.get("usr/lib/" + name, b"")
        if (
            len(data) < MIN_ELF_BYTES
            or data[: len(ELF_ID)] != ELF_ID
            or data[16:20] != ELF_ARM64_SHARED
        ):
            msg = "Driver library must be a complete ARM64 shared ELF"
            raise ValueError(msg)
        identities[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    version = pin["mesa"]["version"] + "-gk3hd-" + identities[LIBRARIES[0]]["sha256"][:12]
    icd = {
        "file_format_version": "1.0.0",
        "ICD": {
            "api_version": "1.3.0",
            "library_arch": "64",
            "library_path": "/data/data/com.winlator/files/rootfs/usr/lib/libvulkan_freedreno.so",
        },
    }
    payload["usr/share/vulkan/icd.d/freedreno_icd.aarch64.json"] = (json.dumps(icd) + "\n").encode()
    memory = io.BytesIO()
    with tarfile.open(fileobj=memory, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        directories = {
            parent.as_posix()
            for name in payload
            for parent in PurePosixPath(name).parents
            if parent != PurePosixPath(".")
        }
        for name in sorted(directories):
            entry = tarfile.TarInfo("./" + name + "/")
            entry.type, entry.mode, entry.mtime = tarfile.DIRTYPE, 0o755, 0
            archive.addfile(entry)
        for name, data in sorted(payload.items()):
            entry = tarfile.TarInfo("./" + name)
            entry.size, entry.mode, entry.mtime = len(data), 0o644, 0
            archive.addfile(entry, io.BytesIO(data))
    packed = zstd.compress(memory.getvalue(), level=12)
    descriptor = {
        "version": version,
        "archive_sha256": hashlib.sha256(packed).hexdigest(),
        "compressed_x11": True,
        "files": identities,
    }
    version_file = app / "src/main/java/com/winlator/core/DefaultVersion.java"
    original = version_file.read_text(encoding="utf-8")
    pattern = r'(public static final String TURNIP = ")[^"]+(";)'
    if len(re.findall(pattern, original)) != 1:
        msg = "Cannot identify the built-in driver version"
        raise ValueError(msg)
    updated = re.sub(pattern, lambda match: match[1] + version + match[2], original)
    outputs = {
        app / f"src/main/assets/graphics_driver/turnip-{version}.tzst": packed,
        app / "src/main/assets/gk3hd-turnip.json": (
            json.dumps(descriptor, indent=2) + "\n"
        ).encode(),
    }
    for path, content in outputs.items():
        if path.is_symlink() or (path.exists() and path.read_bytes() != content):
            msg = "Existing source-driver assets differ; use a fresh component build"
            raise FileExistsError(msg)
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    version_file.write_text(updated, encoding="utf-8", newline="\n")
    return descriptor


if __name__ == "__main__":
    if len(sys.argv) != CLI_ARGUMENTS:
        msg = "Usage: turnip_assets.py DRIVER_PACKAGE APP_DIRECTORY"
        raise SystemExit(msg)
    sys.stdout.write(json.dumps(build_asset(Path(sys.argv[1]), Path(sys.argv[2]))) + "\n")
