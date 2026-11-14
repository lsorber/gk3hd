"""Pin and stage stock Winlator archives fetched separately from GK3HD."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING
from zipfile import ZIP_STORED, ZipFile

from gk3hd.system.download import download_verified
from gk3hd.system.files import cache_directory, sha256_file
from gk3hd.system.locking import ExclusiveFileLock

if TYPE_CHECKING:
    from gk3hd.system.download import ProgressCallback

_RECIPE = Path(__file__).resolve().parent
_MANIFEST = "gk3hd-runtime.json"
_BUILT_ARCHIVES = re.compile(
    r"assets/graphics_driver/(?:gk3hd-vortek|turnip-[0-9.]+-gk3hd-[0-9a-f]+)\.tzst"
)


def _manifest() -> bytes:
    return (_RECIPE / "winlator-runtime.json").read_bytes().replace(b"\r\n", b"\n")


def omit_from_release(assets: Path) -> None:
    """Replace the stock archives with their exact upstream identities."""
    manifest = _manifest()
    files = json.loads(manifest)
    for name, entry in files.items():
        path = assets / name
        if path.stat().st_size != entry["size"] or sha256_file(path) != entry["sha256"]:
            msg = f"Winlator archive differs from its runtime pin: {name}"
            raise ValueError(msg)
    for name in files:
        (assets / name).unlink()
    (assets / _MANIFEST).write_bytes(manifest)


def apk_runtime(apk: Path, *, required: bool = False) -> str | None:
    """Match the APK's runtime manifest to this package before installing it."""
    with ZipFile(apk) as archive:
        entries = [entry for entry in archive.infolist() if entry.filename == f"assets/{_MANIFEST}"]
        if not entries and not required:
            return None
        expected = _manifest()
        if (
            len(entries) != 1
            or entries[0].file_size != len(expected)
            or archive.read(entries[0]) != expected
        ):
            msg = "Standalone APK does not match this GK3HD release's Winlator runtime manifest"
            raise ValueError(msg)
        if any(f"assets/{name}" in archive.namelist() for name in json.loads(expected)):
            msg = "Standalone APK includes stock archives that must be downloaded from Winlator"
            raise ValueError(msg)
        if any(
            name.startswith("assets/")
            and name.endswith((".tzst", ".sf2"))
            and not _BUILT_ARCHIVES.fullmatch(name)
            for name in archive.namelist()
        ):
            msg = "Standalone APK includes a binary archive without a runtime pin"
            raise ValueError(msg)
    return hashlib.sha256(expected).hexdigest()


def prepare_transfer(destination: Path, *, progress: ProgressCallback) -> Path:
    """Download upstream bytes once and package them for the verified USB import."""
    commit = json.loads((_RECIPE / "upstream.json").read_bytes())["winlator"]["commit"]
    base = f"https://raw.githubusercontent.com/brunodev85/winlator-app/{commit}/app/src/main/assets"
    manifest = _manifest()
    files = json.loads(manifest)
    total = sum(entry["size"] for entry in files.values())
    root = cache_directory() / "vr" / "winlator"
    with (
        ExclusiveFileLock(root / ".download.lock"),
        TemporaryDirectory(prefix=".runtime-", dir=destination.parent) as temporary,
    ):
        staged = Path(temporary) / "runtime.zip"
        completed = 0
        with ZipFile(staged, "w", compression=ZIP_STORED) as archive:
            for name, entry in files.items():
                offset = completed
                path = download_verified(
                    f"{base}/{name}",
                    root / entry["sha256"] / Path(name).name,
                    sha256=entry["sha256"],
                    size=entry["size"],
                    progress=lambda done, _total, offset=offset: progress(offset + done, total),
                )
                with path.open("rb") as source, archive.open(name, "w") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
                completed += entry["size"]
        staged.replace(destination)
    return destination
