"""Discover local pack sets and obtain verified release archives."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from gk3hd.system.download import download_verified
from gk3hd.system.files import cache_directory, is_sha256, sha256_file
from gk3hd.textures.pack.format import TexturePackError, _safe_texture_filename
from gk3hd.textures.progress import TextureInstallProgress, report_install_progress
from gk3hd.textures.workspace import PACK_LOCK_FILENAME, release_base_url

if TYPE_CHECKING:
    from collections.abc import Iterable

    from gk3hd.textures.progress import TextureInstallProgressCallback

_PART_ARCHIVE_PATTERN = re.compile(
    r"^(?P<stem>.+)-part(?P<index>[0-9]+)-of-(?P<count>[0-9]+)\.zip$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class TexturePackAsset:
    """One local or immutable remote part of a logical texture pack."""

    archive_path: Path | None = None
    archive_url: str | None = None
    archive_sha256: str | None = None
    archive_size: int | None = None


@dataclass(frozen=True, slots=True)
class TexturePackSource:
    """A local lock/archive or the immutable assets of one logical pack."""

    assets: tuple[TexturePackAsset, ...] = ()
    lock_path: Path | None = None

    @classmethod
    def local(cls, path: Path) -> TexturePackSource:
        """Select a local lock or every numbered part adjacent to an archive."""
        if path.suffix.casefold() == ".json":
            return cls(lock_path=path)
        return cls(assets=_local_archive_assets(path))

    @classmethod
    def from_lock(cls, payload: object) -> TexturePackSource:
        """Select all immutable remote assets declared by a release lock."""
        return cls(assets=_assets_from_lock(payload, local_base=None))


def discover_local_texture_pack(
    selection: Path | None,
    *,
    search_directories: Iterable[Path] = (),
) -> TexturePackSource:
    """Find one logical local pack by name or from a conventional directory."""
    directories = _local_search_directories(selection, search_directories)
    if selection is None:
        for directory in directories:
            source = _discover_texture_pack_in(directory)
            if source is not None:
                return source
        locations = ", ".join(str(path) for path in directories)
        msg = f"no local texture pack found; searched {locations}"
        raise TexturePackError(msg)

    for candidate in _local_pack_candidates(selection, directories):
        if candidate.is_dir():
            source = _discover_texture_pack_in(candidate)
            if source is not None:
                return source
        if candidate.is_file():
            return TexturePackSource.local(candidate)
        source = _discover_split_pack(candidate)
        if source is not None:
            return source
    locations = ", ".join(str(path) for path in directories)
    msg = f"local texture pack {str(selection)!r} was not found; searched {locations}"
    raise TexturePackError(msg)


def _local_search_directories(
    selection: Path | None,
    search_directories: Iterable[Path],
) -> tuple[Path, ...]:
    """Return ordered, unique directories used for a local pack lookup."""
    paths: list[Path] = []
    expanded = selection.expanduser() if selection is not None else None
    if expanded is None or not expanded.is_absolute():
        paths.append(Path.cwd())
        paths.extend(search_directories)
    else:
        paths.append(expanded.parent)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        resolved = path.expanduser().resolve()
        key = os.path.normcase(str(resolved))
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return tuple(unique)


def _local_pack_candidates(selection: Path, directories: tuple[Path, ...]) -> tuple[Path, ...]:
    """Expand a local name to direct, ZIP, and lock candidates."""
    expanded = selection.expanduser()
    values = [expanded]
    if expanded.suffix.casefold() not in {".json", ".zip"}:
        values.extend(
            (
                expanded.with_name(f"{expanded.name}.zip"),
                expanded.with_name(f"{expanded.name}.json"),
            )
        )
    candidates = (
        values
        if expanded.is_absolute()
        else [root / value for root in directories for value in values]
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        key = os.path.normcase(str(resolved))
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return tuple(unique)


def _discover_texture_pack_in(directory: Path) -> TexturePackSource | None:
    """Select the lock or sole logical pack directly inside a directory."""
    if not directory.is_dir():
        return None
    lock = directory / PACK_LOCK_FILENAME
    if lock.is_file():
        return TexturePackSource.local(lock)
    archives = sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file()
            and path.suffix.casefold() == ".zip"
            and path.name.casefold().startswith("gk3hd-texture-pack-v")
        ),
        key=lambda path: path.name.casefold(),
    )
    logical: dict[tuple[str, int | None], Path] = {}
    for archive in archives:
        identity = _part_archive_identity(archive.name)
        key = (
            (archive.stem.casefold(), None)
            if identity is None
            else (identity[0].casefold(), identity[2])
        )
        logical.setdefault(key, archive)
    if not logical:
        return None
    if len(logical) > 1:
        names = ", ".join(sorted(f"{stem}.zip" for stem, _count in logical))
        msg = f"multiple local texture packs found in {directory}; choose one with --pack: {names}"
        raise TexturePackError(msg)
    return TexturePackSource.local(next(iter(logical.values())))


def _discover_split_pack(logical_path: Path) -> TexturePackSource | None:
    """Resolve a logical ZIP name to its adjacent numbered archive parts."""
    if logical_path.suffix.casefold() != ".zip" or _part_archive_identity(logical_path.name):
        return None
    if not logical_path.parent.is_dir():
        return None
    groups: dict[int, Path] = {}
    for path in logical_path.parent.iterdir():
        identity = _part_archive_identity(path.name)
        if (
            path.is_file()
            and identity is not None
            and identity[0].casefold() == logical_path.stem.casefold()
        ):
            groups.setdefault(identity[2], path)
    if not groups:
        return None
    if len(groups) > 1:
        counts = ", ".join(str(count) for count in sorted(groups))
        msg = (
            f"conflicting numbered texture-pack sets found for {logical_path.name}: {counts} parts"
        )
        raise TexturePackError(msg)
    return TexturePackSource.local(next(iter(groups.values())))


def _local_archive_assets(path: Path) -> tuple[TexturePackAsset, ...]:
    """Expand one numbered archive to all sibling parts of that logical pack."""
    identity = _part_archive_identity(path.name)
    if identity is None or not path.parent.is_dir():
        return (TexturePackAsset(archive_path=path),)
    stem, _index, count = identity
    siblings: list[tuple[int, Path]] = []
    for sibling in path.parent.iterdir():
        sibling_identity = _part_archive_identity(sibling.name)
        if (
            sibling.is_file()
            and sibling_identity is not None
            and sibling_identity[0].casefold() == stem.casefold()
            and sibling_identity[2] == count
        ):
            siblings.append((sibling_identity[1], sibling))
    siblings.sort(key=lambda item: item[0])
    if not siblings:
        return (TexturePackAsset(archive_path=path),)
    return tuple(TexturePackAsset(archive_path=sibling) for _index, sibling in siblings)


def _part_archive_identity(name: str) -> tuple[str, int, int] | None:
    """Parse the logical stem, part index, and part count from an asset name."""
    match = _PART_ARCHIVE_PATTERN.fullmatch(name)
    if match is None:
        return None
    return match["stem"], int(match["index"]), int(match["count"])


def _obtain_archives(
    source: TexturePackSource,
    *,
    cache_dir: Path | None = None,
    offline: bool = False,
    progress: TextureInstallProgressCallback | None = None,
) -> tuple[Path, ...]:
    assets = source.assets
    if source.lock_path is not None:
        lock_path = source.lock_path.resolve()
        try:
            payload = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            msg = f"cannot read texture-pack lock {lock_path}: {exc}"
            raise TexturePackError(msg) from exc
        assets = _assets_from_lock(payload, local_base=lock_path.parent)
    if not assets:
        msg = "no texture pack is configured; pass --pack or publish and lock a pack"
        raise TexturePackError(msg)
    report_install_progress(progress, "Preparing texture pack", 0, len(assets))
    total_size = sum(asset.archive_size or 0 for asset in assets)
    completed_size = 0
    archives: list[Path] = []

    def update(event: TextureInstallProgress) -> None:
        report_install_progress(
            progress,
            event.description,
            completed_size + event.completed,
            total_size or completed_size + (event.total or 0),
            unit="bytes",
        )

    for index, asset in enumerate(assets, start=1):
        archive = _obtain_asset(
            asset,
            cache_dir=cache_dir,
            offline=offline,
            progress=update,
        )
        archives.append(archive)
        completed_size += asset.archive_size or archive.stat().st_size
        report_install_progress(progress, "Preparing texture pack", index, len(assets))
    return tuple(archives)


def _obtain_asset(
    asset: TexturePackAsset,
    *,
    cache_dir: Path | None,
    offline: bool,
    progress: TextureInstallProgressCallback | None,
) -> Path:
    """Resolve and verify one local or remote archive part."""
    if asset.archive_path is not None:
        local_path = asset.archive_path.resolve()
        if not local_path.is_file():
            msg = f"texture pack does not exist: {local_path}"
            raise TexturePackError(msg)
        if asset.archive_size is not None and local_path.stat().st_size != asset.archive_size:
            msg = f"texture pack size mismatch: {local_path}"
            raise TexturePackError(msg)
        if asset.archive_sha256 is not None:

            def update(completed: int, size: int) -> None:
                report_install_progress(
                    progress,
                    "Verifying texture pack",
                    completed,
                    size,
                    unit="bytes",
                )

            if sha256_file(local_path, progress=update) != asset.archive_sha256:
                msg = f"texture pack hash mismatch: {local_path}"
                raise TexturePackError(msg)
        return local_path
    archive_url = asset.archive_url
    archive_sha256 = asset.archive_sha256
    archive_size = asset.archive_size
    if (
        not isinstance(archive_url, str)
        or not isinstance(archive_sha256, str)
        or not is_sha256(archive_sha256)
        or type(archive_size) is not int
        or archive_size <= 0
    ):
        msg = "texture-pack lock contains an invalid archive"
        raise TexturePackError(msg)
    destination = (
        (cache_dir or cache_directory())
        / "textures"
        / archive_sha256
        / PurePosixPath(archive_url).name
    )
    if offline:
        _require_cached(destination, sha256=archive_sha256, size=archive_size)
        report_install_progress(
            progress,
            "Downloading texture pack",
            archive_size,
            archive_size,
            unit="bytes",
        )
        return destination

    def update(completed: int, _size: int | None) -> None:
        report_install_progress(
            progress,
            "Downloading texture pack",
            completed,
            archive_size,
            unit="bytes",
        )

    return download_verified(
        archive_url,
        destination,
        sha256=archive_sha256,
        size=archive_size,
        progress=update,
    )


def _require_cached(path: Path, *, sha256: str, size: int | None = None) -> None:
    """Verify an immutable cached asset without attempting network access."""
    valid = (
        path.is_file()
        and (size is None or path.stat().st_size == size)
        and sha256_file(path) == sha256
    )
    if not valid:
        msg = f"offline asset is absent or invalid in the cache: {path.name}"
        raise TexturePackError(msg)


def _assets_from_lock(
    payload: object,
    *,
    local_base: Path | None,
) -> tuple[TexturePackAsset, ...]:
    """Validate tagged release lock data into ordered immutable assets."""
    if not isinstance(payload, dict):
        msg = "texture-pack lock must be an object"
        raise TexturePackError(msg)
    values = payload.get("archives")
    if not isinstance(values, list):
        msg = "texture-pack lock has an invalid archive list"
        raise TexturePackError(msg)
    if not values:
        return ()
    assets: list[TexturePackAsset] = []
    names: set[str] = set()
    tag = payload.get("tag")
    if not isinstance(tag, str) or re.fullmatch(r"v[0-9][A-Za-z0-9._-]*", tag) is None:
        msg = "texture-pack lock has an invalid release tag"
        raise TexturePackError(msg)
    for value in values:
        filename, asset = _asset_from_lock_value(value, tag=tag, local_base=local_base)
        if filename.casefold() in names:
            msg = f"texture-pack lock repeats an archive: {filename}"
            raise TexturePackError(msg)
        names.add(filename.casefold())
        assets.append(asset)
    return tuple(assets)


def _asset_from_lock_value(
    value: object,
    *,
    tag: str,
    local_base: Path | None,
) -> tuple[str, TexturePackAsset]:
    """Validate one lock archive and resolve its local or remote identity."""
    if not isinstance(value, dict):
        msg = "texture-pack lock archive must be an object"
        raise TexturePackError(msg)
    filename = value.get("filename")
    sha256 = value.get("sha256")
    size = value.get("size")
    if (
        not isinstance(filename, str)
        or _safe_texture_filename(filename) != filename
        or not filename.casefold().endswith(".zip")
        or not is_sha256(sha256)
        or type(size) is not int
        or size <= 0
    ):
        msg = "texture-pack lock contains an invalid archive"
        raise TexturePackError(msg)
    if local_base is not None:
        base = local_base.resolve()
        archive_path = (base / filename).resolve()
        if archive_path.parent != base:
            msg = "texture-pack lock archive escapes its directory"
            raise TexturePackError(msg)
        return filename, TexturePackAsset(
            archive_path=archive_path,
            archive_sha256=sha256,
            archive_size=size,
        )
    # Immutable URLs are known from the release tag before upload.
    return filename, TexturePackAsset(
        archive_url=f"{release_base_url(tag)}/{filename}",
        archive_sha256=sha256,
        archive_size=size,
    )
