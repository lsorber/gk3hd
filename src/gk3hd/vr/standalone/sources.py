"""Keep corresponding source next to each signed standalone release."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from gk3hd.system.files import atomic_write, is_sha256, json_bytes, sha256_file
from gk3hd.vr.standalone.paths import BUILD_RECORD

_ARCHIVE = "gk3hd-vr-sources.zip"
MAX_ARCHIVE_BYTES = 128 * 1024**2
_BINARY_SUFFIXES = ("dll", "exe", "pyc", "sf2", "so", "tzst")
_SOURCE_TREES = {"winlator": "winlator-source", "vortek": "vortek-source", "wxr": "wxr-source"}
_GUIDE = Path(__file__).resolve().parents[1] / "SOURCES.txt"


def stage(build_inputs: Path, components: Path) -> None:
    """Capture the inputs before the successful native build workspace is removed."""
    record = components / BUILD_RECORD
    data = json.loads(record.read_bytes())
    data.pop("source_archive_sha256", None)
    recipes = build_inputs / "adapters"
    wine = json.loads((recipes / "wine/upstream.json").read_bytes())
    with TemporaryDirectory(prefix=".gk3hd-source-", dir=components) as temporary:
        work = Path(temporary)
        archive = work / _ARCHIVE
        with ZipFile(archive, "x", compression=ZIP_DEFLATED) as bundle:
            for key, folder in _SOURCE_TREES.items():
                target = work / f"{key}.zip"
                command = [
                    "git",
                    "-C",
                    str(build_inputs / folder),
                    "archive",
                    "--format=zip",
                    "--output",
                    str(target),
                    data["upstream"][key]["commit"],
                    "--",
                    ".",
                    *(f":(exclude,glob)**/*.{suffix}" for suffix in _BINARY_SUFFIXES),
                ]
                try:
                    subprocess.run(  # noqa: S603 - pinned Git objects in the native build checkout.
                        command, check=True, timeout=60
                    )
                except (OSError, subprocess.SubprocessError) as error:
                    msg = f"Could not archive the pinned {key} source"
                    raise RuntimeError(msg) from error
                bundle.write(target, f"upstream/{target.name}", compress_type=ZIP_STORED)
            for key in ("wine", "staging"):
                source = build_inputs / "wine-server-build" / f"{key}.tar.gz"
                if sha256_file(source) != wine[key]["sha256"]:
                    msg = f"The archived {key} source differs from the verified build input"
                    raise ValueError(msg)
                bundle.write(source, f"upstream/{source.name}", compress_type=ZIP_STORED)
            for name, digest in data["inputs"].items():
                payload = (recipes / name).read_bytes().replace(b"\r\n", b"\n")
                if hashlib.sha256(payload).hexdigest() != digest:
                    msg = f"Standalone build source changed before archiving: {name}"
                    raise ValueError(msg)
                bundle.writestr(f"gk3hd/src/gk3hd/vr/android/{name}", payload)
            bundle.writestr(BUILD_RECORD, json_bytes(data))
            bundle.writestr(_GUIDE.name, _GUIDE.read_text(encoding="utf-8"))
        if archive.stat().st_size > MAX_ARCHIVE_BYTES:
            msg = "Standalone corresponding source exceeds the release archive size bound"
            raise ValueError(msg)
        _verify_source(archive, json_bytes(data))
        data["source_archive_sha256"] = sha256_file(archive)
        archive.replace(components / _ARCHIVE)
    atomic_write(record, json_bytes(data))


def _source_digest(archive: ZipFile, name: str) -> str:
    digest = hashlib.sha256()
    with archive.open(name) as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_source(source: Path, receipt: bytes) -> None:
    """Check the actual source inventory and its identities before upload."""
    msg = "Standalone source archive does not match the signed component build"
    data = json.loads(receipt)
    prefix = "gk3hd/src/gk3hd/vr/android/"
    recipes = {f"{prefix}{name}": digest for name, digest in data["inputs"].items()}
    snapshots = {f"upstream/{key}.zip": data["upstream"][key]["commit"] for key in _SOURCE_TREES}
    wine = {"upstream/wine.tar.gz": "wine", "upstream/staging.tar.gz": "staging"}
    expected = {BUILD_RECORD, _GUIDE.name, *recipes, *snapshots, *wine}
    guide = _GUIDE.read_text(encoding="utf-8").encode()
    try:
        with ZipFile(source) as archive:
            entries = archive.infolist()
            if (
                len(entries) != len(expected)
                or {entry.filename for entry in entries} != expected
                or sum(entry.file_size for entry in entries) > MAX_ARCHIVE_BYTES
                or archive.getinfo(BUILD_RECORD).file_size != len(receipt)
                or archive.read(BUILD_RECORD) != receipt
                or archive.getinfo(_GUIDE.name).file_size != len(guide)
                or archive.read(_GUIDE.name) != guide
            ):
                raise ValueError(msg)
            if any(_source_digest(archive, name) != digest for name, digest in recipes.items()):
                raise ValueError(msg)
            for name, commit in snapshots.items():
                with archive.open(name) as snapshot, ZipFile(snapshot) as tree:
                    if (
                        tree.comment != commit.encode("ascii")
                        or not tree.namelist()
                        or sum(entry.file_size for entry in tree.infolist()) > MAX_ARCHIVE_BYTES
                        or tree.testzip() is not None
                    ):
                        raise ValueError(msg)
            wine_pins = json.loads(archive.read(f"{prefix}wine/upstream.json"))
            for name, key in wine.items():
                if _source_digest(archive, name) != wine_pins[key]["sha256"]:
                    raise ValueError(msg)
    except (BadZipFile, KeyError) as error:
        raise ValueError(msg) from error


def attachment(build: Path, standalone: Path, *, name: str) -> Path:
    """Stage the matching build's source for upload without affecting player downloads."""
    with ZipFile(standalone) as binaries:
        data = json.loads(binaries.read(BUILD_RECORD))
    digest = data.pop("source_archive_sha256", None)
    source = build / _ARCHIVE
    if (
        not is_sha256(digest)
        or source.is_symlink()
        or not source.is_file()
        or not 0 < source.stat().st_size <= MAX_ARCHIVE_BYTES
        or sha256_file(source) != digest
    ):
        msg = (
            "Standalone build source is missing or changed. "
            "Run gk3hd vr standalone build --release."
        )
        raise ValueError(msg)
    _verify_source(source, json_bytes(data))
    target = standalone.with_name(name)
    with source.open("rb") as incoming, target.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing)
    if sha256_file(target) != digest:
        msg = "Standalone build source changed during release preparation"
        raise ValueError(msg)
    return target
