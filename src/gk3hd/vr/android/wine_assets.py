"""Package the source-built registry server and its source/license provenance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

RECIPE = Path(__file__).resolve().parent / "wine"
FILES = {"wineserver", "registry-save.patch", "private-temp.patch", "upstream.json", "COPYING.LIB"}
MAX_BYTES = 2 * 1024**2
MAX_RECORD = 65536
ELF_HEADER = 64


def build_asset(source: Path, app: Path) -> dict[str, str]:
    """Verify all inputs before publishing APK assets into a fresh app build."""
    record_path = source / "server-build.json"
    if not record_path.is_file() or record_path.stat().st_size > MAX_RECORD:
        msg = "Missing or oversized source Wine server build record"
        raise ValueError(msg)
    record = json.loads(record_path.read_text())
    pin = json.loads((RECIPE / "upstream.json").read_text())
    patches = {
        name: hashlib.sha256((RECIPE / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for name in ("registry-save.patch", "private-temp.patch")
    }
    if (
        record.get("schema") != 1
        or record.get("kind") != "standalone-wine-registry-server"
        or record.get("upstream") != pin
        or record.get("patches") != patches
        or record.get("protocol_sha256") != pin["protocol_sha256"]
        or record.get("default_async_registry") is not True
        or record.get("default_versioned_dirty_tracking") is not True
        or not isinstance(record.get("files"), dict)
        or set(record["files"]) != FILES
    ):
        msg = "Wine server does not match the compatible source recipe"
        raise ValueError(msg)
    payload = {}
    for name in sorted(FILES):
        path = source / name
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
            msg = "Missing, redirected or oversized Wine server payload"
            raise ValueError(msg)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != record["files"][name]:
            msg = "Source Wine server payload failed verification"
            raise ValueError(msg)
        payload[name] = data
    image = payload.pop("wineserver")
    if len(image) < ELF_HEADER or image[:6] != b"\x7fELF\x02\x01" or image[18:20] != b"\x3e\x00":
        msg = "Source Wine server must be an x86-64 ELF"
        raise ValueError(msg)
    identity = hashlib.sha256(image).hexdigest()
    assets = app / "src/main/assets/gk3hd"
    outputs = {
        assets / "wine-server.elf": image,
        assets / "wine-server.sha256": (identity + "\n").encode(),
        assets / "wine/server-build.json": record_path.read_bytes(),
    }
    outputs.update({assets / "wine" / name: data for name, data in payload.items()})
    for path, data in outputs.items():
        if path.is_symlink() or (
            path.exists() and (not path.is_file() or path.read_bytes() != data)
        ):
            msg = "Existing Wine server assets differ; choose a fresh app build"
            raise FileExistsError(msg)
    for path, data in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return {
        "server_sha256": identity,
        "record_sha256": hashlib.sha256(record_path.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    build_asset(Path(sys.argv[1]), Path(sys.argv[2]))
