"""Versioned video packs containing AV1 replacements and their private player."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from gk3hd.system.download import download_verified
from gk3hd.system.files import (
    atomic_write,
    cache_directory,
    is_portable_filename,
    is_sha256,
    json_bytes,
    sha256_file,
)
from gk3hd.videos.catalog import movie_format, movie_workspace
from gk3hd.videos.manifest import read_json, validate_generation
from gk3hd.videos.runtime import (
    PLAYER_DLL,
    codec_cache,
    download_codecs,
    extract_codecs,
    inspect_player,
    local_player,
    recipe_digest,
    verify_codecs,
)
from gk3hd.videos.transaction import state_at

if TYPE_CHECKING:
    from collections.abc import Sequence

    from gk3hd.videos.install import MovieInstallReport
    from gk3hd.videos.transaction import MovieProgress

LOCK_FILENAME = "video-pack-lock.json"
MANIFEST_FILENAME = "video-pack-manifest.json"
MAX_ARCHIVE_BYTES = 1900 * 1024 * 1024
_BLOCK = 1024 * 1024
_MANIFEST_LIMIT = 1024 * 1024
_ROOT = "gk3hd/videos/"
_MEMBER_COMPONENTS = 4
_RELEASE = "https://github.com/lsorber/gk3hd/releases/download"
_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){1,2}")


@dataclass(frozen=True)
class Archive:
    """Immutable release-part identity, usable before the release exists."""

    filename: str
    sha256: str
    size: int

    @classmethod
    def parse(cls, value: object) -> Archive:
        """Reject unsafe paths and incomplete download pins."""
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("filename"), str)
            or not is_portable_filename(value["filename"])
            or not value["filename"].endswith(".zip")
            or not is_sha256(value.get("sha256"))
            or type(value.get("size")) is not int
            or not 0 < value["size"] <= MAX_ARCHIVE_BYTES
        ):
            msg = "invalid video-pack archive identity"
            raise ValueError(msg)
        return cls(value["filename"], value["sha256"], value["size"])


def release_archives(lock: object) -> tuple[str, tuple[Archive, ...]]:
    """Validate the tag and all parts without network access."""
    if isinstance(lock, dict) and lock.get("archives") == []:
        msg = "no video pack is configured; prepare the first release with package draft --videos"
        raise ValueError(msg)
    if (
        not isinstance(lock, dict)
        or lock.get("schema_version") != 1
        or not isinstance(lock.get("tag"), str)
        or _VERSION.fullmatch(lock["tag"].removeprefix("v")) is None
        or not lock["tag"].startswith("v")
        or not isinstance(lock.get("archives"), list)
    ):
        msg = "invalid video-pack lock"
        raise ValueError(msg)
    archives = tuple(Archive.parse(item) for item in lock["archives"])
    if not archives or len({item.filename.casefold() for item in archives}) != len(archives):
        msg = "no video pack is configured; prepare the first release with package draft --videos"
        raise ValueError(msg)
    return lock["tag"], archives


def pack_filename(version: str) -> str:
    """Use the same package version and naming convention as texture packs."""
    if _VERSION.fullmatch(version) is None:
        msg = "invalid video-pack version"
        raise ValueError(msg)
    return f"gk3hd-video-pack-v{version}.zip"


def _inputs(source: Path, player: Path) -> tuple[tuple[str, Path], ...]:
    inputs: list[tuple[str, Path]] = []
    for receipt in sorted(source.glob("*.mkv.json")):
        record = validate_generation(read_json(receipt))
        video = receipt.with_suffix("")
        if (
            record.get("pipeline") != "seedvr2"
            or record.get("codec") != "libaom-av1"
            or movie_format(video) != "Matroska"
            or sha256_file(video) != record.get("output_sha256")
            or video.stem.casefold() != Path(str(record.get("source_name"))).stem.casefold()
        ):
            msg = f"unverified video output: {video.name}"
            raise ValueError(msg)
        inputs.extend((_ROOT + "upscaled/" + path.name, path) for path in (video, receipt))
    if not inputs:
        msg = f"no verified videos in {source}; run gk3hd videos upscale first"
        raise ValueError(msg)
    inspect_player(player)
    inputs.extend((_ROOT + "player/" + name, player / name) for name in (PLAYER_DLL, "player.json"))
    if len({name.casefold() for name, _ in inputs}) != len(inputs):
        msg = "duplicate video-pack filename"
        raise ValueError(msg)
    return tuple(inputs)


def _groups(inputs: Sequence[tuple[str, Path]]) -> list[list[tuple[str, Path]]]:
    """Split members below the release limit without splitting a video stream."""
    groups: list[list[tuple[str, Path]]] = [[]]
    size = 0
    for name, path in inputs:
        required = path.stat().st_size + len(name) * 4 + 1024
        if required > MAX_ARCHIVE_BYTES - _BLOCK:
            msg = f"video is too large for one release asset: {path.name}"
            raise ValueError(msg)
        if size + required > MAX_ARCHIVE_BYTES - _BLOCK:
            groups.append([])
            size = 0
        groups[-1].append((name, path))
        size += required
    return groups


def build_pack(
    game_dir: Path,
    *,
    version: str,
    source: Path | None = None,
    output: Path | None = None,
    progress: MovieProgress | None = None,
) -> tuple[Path, ...]:
    """Write independently readable ZIP parts below GitHub's 2 GiB asset limit."""
    root = movie_workspace(game_dir)
    output = output or root / pack_filename(version)
    pack_filename(version)
    inputs = _inputs(source or root / "upscaled", local_player(game_dir))
    groups = _groups(inputs)
    output.parent.mkdir(parents=True, exist_ok=True)
    total = sum(path.stat().st_size for _name, path in inputs)
    if shutil.disk_usage(output.parent).free < total + _BLOCK:
        msg = "not enough disk space to create the video pack"
        raise ValueError(msg)
    completed = 0
    archives = []
    for index, group in enumerate(groups, 1):
        name = (
            output.name
            if len(groups) == 1
            else (f"{output.stem}-part{index:02d}-of-{len(groups):02d}.zip")
        )
        target = output.with_name(name)
        temporary = target.with_suffix(".zip.tmp")
        try:
            inventory = {}
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as bundle:
                for member, path in group:
                    digest = hashlib.sha256()
                    length = 0
                    info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
                    with (
                        path.open("rb") as original,
                        bundle.open(info, "w", force_zip64=True) as zipped,
                    ):
                        while block := original.read(_BLOCK):
                            zipped.write(block)
                            digest.update(block)
                            length += len(block)
                            completed += len(block)
                            if progress:
                                progress("Packing videos", completed, total)
                    inventory[member] = {"sha256": digest.hexdigest(), "size": length}
                bundle.writestr(
                    zipfile.ZipInfo(MANIFEST_FILENAME, date_time=(1980, 1, 1, 0, 0, 0)),
                    json_bytes(
                        {
                            "version": version,
                            "part": index,
                            "parts": len(groups),
                            "files": inventory,
                        }
                    ),
                )
            if temporary.stat().st_size > MAX_ARCHIVE_BYTES:
                msg = "video-pack part exceeds the release asset limit"
                raise ValueError(msg)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        archives.append(target)
    atomic_write(
        output.parent / LOCK_FILENAME,
        json_bytes(
            {
                "schema_version": 1,
                "tag": f"v{version}",
                "archives": [
                    asdict(Archive(path.name, sha256_file(path), path.stat().st_size))
                    for path in archives
                ],
            }
        ),
    )
    return tuple(archives)


@dataclass(frozen=True)
class PackRequest:
    """Shared local/download choices for the public video installer."""

    local: bool = False
    selection: Path | None = None
    cache: Path | None = None
    offline: bool = False


def _local_lock(game_dir: Path, selection: Path | None) -> Path:
    for directory in (Path.cwd(), movie_workspace(game_dir)):
        candidate = directory / (selection or Path(LOCK_FILENAME))
        if candidate.is_dir():
            candidate /= LOCK_FILENAME
        if candidate.is_file():
            return candidate
    msg = "no local video-pack lock found; run gk3hd videos pack first or pass --pack PATH"
    raise ValueError(msg)


def obtain_pack(
    game_dir: Path,
    request: PackRequest | None = None,
    *,
    progress: MovieProgress | None = None,
) -> tuple[Path, ...]:
    """Resolve a complete local set or download every pinned release part."""
    request = request or PackRequest()
    lock = _local_lock(game_dir, request.selection) if request.local or request.selection else None
    payload = read_json(lock or Path(__file__).parents[1] / "assets" / LOCK_FILENAME)
    tag, archives = release_archives(payload)
    results = []
    total = sum(item.size for item in archives)
    completed = 0
    for item in archives:
        path = (
            (lock.parent / item.filename)
            if lock
            else ((request.cache or cache_directory()) / "videos" / item.sha256 / item.filename)
        )
        if lock or request.offline:
            if (
                not path.is_file()
                or path.stat().st_size != item.size
                or sha256_file(path) != item.sha256
            ):
                msg = f"video-pack archive is missing or changed: {path}"
                raise ValueError(msg)
        else:

            def update(done: int, _total: int | None, offset: int = completed) -> None:
                if progress:
                    progress("Downloading videos", offset + done, total)

            download_verified(
                f"{_RELEASE}/{tag}/{item.filename}",
                path,
                sha256=item.sha256,
                size=item.size,
                progress=update,
            )
        results.append(path)
        completed += item.size
        if progress:
            progress("Verified video pack", completed, total)
    return tuple(results)


def _identity(game_dir: Path, request: PackRequest) -> str:
    """Identify the required pack and player without downloading video archives."""
    lock = _local_lock(game_dir, request.selection) if request.local or request.selection else None
    tag, archives = release_archives(
        read_json(lock or Path(__file__).parents[1] / "assets" / LOCK_FILENAME)
    )
    return hashlib.sha256(
        json_bytes(
            {
                "tag": tag,
                "archives": [asdict(item) for item in archives],
                "player": recipe_digest(),
            }
        )
    ).hexdigest()


def prefetch(
    game_dir: Path, request: PackRequest, *, progress: MovieProgress | None = None
) -> None:
    """Validate downloads before a composed installation changes other components."""
    before = state_at(game_dir)
    if before is not None and before.pack_identity == _identity(game_dir, request):
        return
    obtain_pack(game_dir, request, progress=progress)
    if request.offline:
        verify_codecs(codec_cache(request.cache))
    else:
        download_codecs(
            request.cache,
            progress=(
                lambda done, total: progress("Downloading playback codecs", done, total or done)
            )
            if progress
            else None,
        )


def _member_name(name: str) -> str:
    path = PurePosixPath(name)
    if (
        str(path) != name
        or not name.startswith(_ROOT)
        or len(path.parts) != _MEMBER_COMPONENTS
        or path.parts[2] not in {"upscaled", "player"}
        or not is_portable_filename(path.name)
        or (path.parts[2] == "upscaled" and not name.endswith((".mkv", ".mkv.json")))
        or (path.parts[2] == "player" and path.name not in {PLAYER_DLL, "player.json"})
    ):
        msg = f"unsafe video-pack member: {name}"
        raise ValueError(msg)
    return name.removeprefix(_ROOT)


def _read_part(
    bundle: zipfile.ZipFile, index: int, count: int, version: str | None
) -> tuple[str, dict[str, object]]:
    """Validate part order, version and member inventory before extraction."""
    header = bundle.getinfo(MANIFEST_FILENAME)
    if header.file_size > _MANIFEST_LIMIT:
        msg = "oversized video-pack manifest"
        raise ValueError(msg)
    manifest = json.loads(bundle.read(header))
    if (
        not isinstance(manifest, dict)
        or manifest.get("part") != index
        or manifest.get("parts") != count
        or not isinstance(manifest.get("version"), str)
        or _VERSION.fullmatch(manifest["version"]) is None
        or (version is not None and manifest["version"] != version)
        or not isinstance(manifest.get("files"), dict)
        or not manifest["files"]
    ):
        msg = "incomplete or mixed video-pack parts"
        raise ValueError(msg)
    names = [entry.filename for entry in bundle.infolist()]
    if len(names) != len(set(names)) or set(names) != {
        *manifest["files"],
        MANIFEST_FILENAME,
    }:
        msg = "video-pack has undeclared or duplicate members"
        raise ValueError(msg)
    return manifest["version"], manifest["files"]


def unpack(
    archives: Sequence[Path],
    destination: Path,
    *,
    progress: MovieProgress | None = None,
) -> None:
    """Stream only bounded, declared members into a disposable private directory."""
    seen: set[str] = set()
    version = None
    for index, archive in enumerate(archives, 1):
        with zipfile.ZipFile(archive) as bundle:
            version, files = _read_part(bundle, index, len(archives), version)
            total = sum(entry.file_size for entry in bundle.infolist())
            if total > MAX_ARCHIVE_BYTES or shutil.disk_usage(destination).free < total:
                msg = "video-pack expansion exceeds its space limit"
                raise ValueError(msg)
            completed = 0
            for name, identity in files.items():
                member = bundle.getinfo(name)
                relative = _member_name(name)
                if (
                    name.casefold() in seen
                    or stat.S_ISLNK(member.external_attr >> 16)
                    or not isinstance(identity, dict)
                    or not is_sha256(identity.get("sha256"))
                    or type(identity.get("size")) is not int
                    or identity["size"] != member.file_size
                ):
                    msg = f"invalid video-pack member identity: {name}"
                    raise ValueError(msg)
                seen.add(name.casefold())
                output = destination / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with bundle.open(member) as original, output.open("xb") as target:
                    while block := original.read(_BLOCK):
                        target.write(block)
                        digest.update(block)
                        completed += len(block)
                        if progress:
                            progress(
                                f"Extracting video pack {index}/{len(archives)}", completed, total
                            )
                if digest.hexdigest() != identity["sha256"]:
                    msg = f"video-pack member failed verification: {name}"
                    raise ValueError(msg)


def install_pack(
    game_dir: Path,
    request: PackRequest | None = None,
    *,
    progress: MovieProgress | None = None,
) -> MovieInstallReport:
    """Install the same verified pack on Windows or Linux, without build tools."""
    from gk3hd.videos.install import MovieInstaller  # noqa: PLC0415 - avoid installer cycle.

    request = request or PackRequest()
    identity = _identity(game_dir, request)
    before = state_at(game_dir)
    if before is not None and before.pack_identity == identity:
        return MovieInstaller.verify(game_dir, progress=progress)
    archives = obtain_pack(game_dir, request, progress=progress)
    root = movie_workspace(game_dir)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".unpack-", dir=root) as temporary:
        directory = Path(temporary)
        try:
            unpack(archives, directory, progress=progress)
        except (zipfile.BadZipFile, KeyError) as exc:
            msg = f"invalid video pack: {exc}"
            raise ValueError(msg) from exc
        codecs = (
            codec_cache(request.cache)
            if request.offline
            else download_codecs(
                request.cache,
                progress=(
                    lambda done, total: progress("Downloading playback codecs", done, total or done)
                )
                if progress
                else None,
            )
        )
        extract_codecs(codecs, directory / "player")
        inspect_player(directory / "player")
        return MovieInstaller().install(
            game_dir,
            directory / "upscaled",
            player=directory / "player",
            progress=progress,
            pack_identity=identity,
        )
