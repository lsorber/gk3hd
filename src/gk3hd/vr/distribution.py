"""Publish and fetch compatible VR components, never purchased game data."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import urllib.request
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from gk3hd.renderer.distribution import REPOSITORY
from gk3hd.system.download import DownloadError, download_verified
from gk3hd.system.files import cache_directory
from gk3hd.system.locking import ExclusiveFileLock
from gk3hd.vr.android import notices
from gk3hd.vr.artifact import RECIPE, inspect_vr_dll
from gk3hd.vr.artifact import source_hashes as renderer_hashes
from gk3hd.vr.standalone.build import inspect_components, source_hashes
from gk3hd.vr.standalone.paths import APK_FILENAME, BUILD_RECORD
from gk3hd.vr.standalone.sources import MAX_ARCHIVE_BYTES as MAX_SOURCE_ARCHIVE_BYTES

if TYPE_CHECKING:
    from gk3hd.system.download import ProgressCallback
    from gk3hd.vr.standalone.signing import ReleaseSigner

_MAX_ARCHIVE = 320 * 1024**2
_MAX_EXPANDED = 384 * 1024**2
_MAX_RENDERER = 16 * 1024**2
_MAX_INVENTORY = 4 * 1024**2
_PAGE_SIZE = 100
_MAX_PAGES = 100
_SOURCE_DOCUMENTS = tuple(
    Path(__file__).with_name(name) for name in ("SOURCES.txt", "ANDROID-THIRD-PARTY-NOTICES.txt")
)
_STANDALONE_FILES = (
    APK_FILENAME,
    "openxr_wxr32.dll",
    "gk3hd-wine-launcher.exe",
    BUILD_RECORD,
    *notices.COMPONENT_LICENSES,
)


class AssetKind(StrEnum):
    """PC renderer or the complete, tested standalone component set."""

    RENDERER = "renderer"
    STANDALONE = "standalone"


def identity(kind: AssetKind = AssetKind.STANDALONE) -> str:
    """Bind native components to this package's reviewed source and recipes."""
    inputs = {
        "renderer": renderer_hashes(),
        "recipe": (RECIPE / "upstream.json").read_text(encoding="utf-8"),
        "patch": (RECIPE / "renderer.patch").read_text(encoding="utf-8"),
    }
    if kind is AssetKind.STANDALONE:
        inputs["android"] = source_hashes()
        inputs["source_documents"] = {
            path.name: path.read_text(encoding="utf-8") for path in _SOURCE_DOCUMENTS
        }
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def asset_name(kind: AssetKind = AssetKind.STANDALONE) -> str:
    """Reuse compatible native builds across package-only releases."""
    return f"gk3hd-vr-{kind}-{identity(kind)[:16]}.zip"


def source_asset_name() -> str:
    """Name the source companion for the corresponding standalone archive."""
    return f"gk3hd-vr-source-{identity()[:16]}.zip"


def renderer_path(directory: Path) -> Path:
    """Locate the recipe's private VR renderer in a component set."""
    pin = json.loads((RECIPE / "upstream.json").read_text(encoding="utf-8"))
    return directory / f"dxvk-sarek-{pin['version']}-xr-prototype.dll"


def _names(directory: Path, kind: AssetKind) -> tuple[str, ...]:
    renderer = renderer_path(directory)
    names = (renderer.name, renderer.with_suffix(".json").name, renderer.with_suffix(".txt").name)
    return (*names, *_STANDALONE_FILES) if kind is AssetKind.STANDALONE else names


def _files(directory: Path, kind: AssetKind) -> tuple[Path, ...]:
    paths = tuple(directory / name for name in _names(directory, kind))
    if any(not path.is_file() or path.is_symlink() for path in paths):
        msg = "VR component set is missing its binaries or notices"
        raise ValueError(msg)
    inspect_vr_dll(renderer_path(directory))
    if kind is AssetKind.STANDALONE:
        inspect_components(directory)
        notices.verify_component_licenses(directory)
    return paths


def archive(
    build: Path,
    output: Path,
    *,
    kind: AssetKind = AssetKind.STANDALONE,
    signer: ReleaseSigner | None = None,
) -> Path:
    """Package only verified redistributable components for a GitHub release."""
    paths = _files(build, kind)
    expanded = _MAX_EXPANDED if kind is AssetKind.STANDALONE else _MAX_RENDERER
    if sum(path.stat().st_size for path in paths) > expanded:
        msg = "VR components exceed the release size bound"
        raise ValueError(msg)
    output.mkdir(parents=True, exist_ok=True)
    target = output / asset_name(kind)
    if target.exists():
        msg = "VR release archive already exists; choose a fresh output directory"
        raise FileExistsError(msg)
    with TemporaryDirectory(prefix=".gk3hd-vr-", dir=output) as temporary:
        staged = Path(temporary) / target.name
        with ZipFile(staged, "w", compression=ZIP_DEFLATED, compresslevel=1) as bundle:
            for path in paths:
                bundle.write(path, path.name)
            if kind is AssetKind.STANDALONE:
                for path in _SOURCE_DOCUMENTS:
                    bundle.writestr(path.name, path.read_text(encoding="utf-8"))
        _files(build, kind)  # Reject a component replacement while packaging.
        with TemporaryDirectory(dir=temporary) as check:
            extracted = Path(check)
            _extract(staged, extracted, kind=kind)
            if signer is not None:
                signer.verify(extracted / APK_FILENAME)
        staged.replace(target)
    return target


def _extract(
    archive_path: Path, destination: Path, *, kind: AssetKind = AssetKind.STANDALONE
) -> None:
    try:
        _extract_files(archive_path, destination, kind)
    except BadZipFile as error:
        msg = "VR component archive is corrupt; no installation started"
        raise DownloadError(msg) from error


def _extract_files(archive_path: Path, destination: Path, kind: AssetKind) -> None:
    allowed = set(_names(destination, kind))
    if kind is AssetKind.STANDALONE:
        allowed.update(path.name for path in _SOURCE_DOCUMENTS)
    maximum = _MAX_ARCHIVE if kind is AssetKind.STANDALONE else _MAX_RENDERER
    expanded = _MAX_EXPANDED if kind is AssetKind.STANDALONE else _MAX_RENDERER
    if archive_path.stat().st_size > maximum:
        msg = "VR release archive exceeds its size bound"
        raise ValueError(msg)
    with ZipFile(archive_path) as bundle:
        entries = bundle.infolist()
        if (
            len(entries) != len(allowed)
            or {entry.filename for entry in entries} != allowed
            or sum(entry.file_size for entry in entries) > expanded
            or any(entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16) for entry in entries)
        ):
            msg = "VR release must contain only the expected binaries and notices"
            raise ValueError(msg)
        if kind is AssetKind.STANDALONE:
            for path in _SOURCE_DOCUMENTS:
                expected = path.read_text(encoding="utf-8").encode()
                entry = bundle.getinfo(path.name)
                if entry.file_size != len(expected) or bundle.read(entry) != expected:
                    msg = f"Standalone release source document differs from its copy: {path.name}"
                    raise ValueError(msg)
        for entry in entries:
            with bundle.open(entry) as source, (destination / entry.filename).open("xb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
    _files(destination, kind)


def _release_page(page: int) -> list[dict[str, object]]:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/releases?per_page={_PAGE_SIZE}&page={page}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "gk3hd"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed official API.
        payload = response.read(_MAX_INVENTORY + 1)
    if len(payload) > _MAX_INVENTORY:
        msg = "GitHub VR release inventory exceeds its size bound"
        raise DownloadError(msg)
    data = json.loads(payload)
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        msg = "Invalid GitHub VR release inventory"
        raise DownloadError(msg)
    return data


def _candidates(name: str) -> list[tuple[str, object, dict[str, object], list[object]]]:
    candidates: list[tuple[str, object, dict[str, object], list[object]]] = []
    for page in range(1, _MAX_PAGES + 1):
        releases = _release_page(page)
        for release in releases:
            if release.get("draft") is not False or release.get("prerelease") is not False:
                continue
            published, assets = release.get("published_at"), release.get("assets")
            if not isinstance(published, str) or not isinstance(assets, list):
                msg = "Invalid published VR release inventory"
                raise DownloadError(msg)
            matches = [
                item for item in assets if isinstance(item, dict) and item.get("name") == name
            ]
            if matches:
                if len(matches) != 1:
                    msg = "Ambiguous VR release component archive"
                    raise DownloadError(msg)
                candidates.append((published, release.get("tag_name"), matches[0], assets))
        if len(releases) < _PAGE_SIZE:
            break
    else:
        msg = "Too many release pages to discover compatible VR components"
        raise DownloadError(msg)
    return candidates


def published_asset(
    kind: AssetKind = AssetKind.STANDALONE, *, require_source: bool = False
) -> tuple[str, str, int]:
    """Resolve the compatible public archive without downloading it."""
    name = asset_name(kind)
    candidates = _candidates(name)
    if not candidates:
        msg = (
            f"No compatible VR {kind} archive has been published for this package yet. "
            "Check that you are using gk3hd@latest and try again once the VR release is available."
        )
        raise DownloadError(msg)
    _, tag, asset, assets = max(candidates, key=lambda item: item[0])
    maximum = _MAX_ARCHIVE if kind is AssetKind.STANDALONE else _MAX_RENDERER
    binary = _validate_asset(name, tag, asset, maximum)
    if require_source and kind is AssetKind.STANDALONE:
        source_name = source_asset_name()
        sources = [
            item for item in assets if isinstance(item, dict) and item.get("name") == source_name
        ]
        if len(sources) != 1:
            msg = f"The standalone VR release {tag} needs one matching source archive"
            raise DownloadError(msg)
        _validate_asset(source_name, tag, sources[0], MAX_SOURCE_ARCHIVE_BYTES)
    return binary


def _validate_asset(
    name: str, tag: object, asset: dict[str, object], maximum: int
) -> tuple[str, str, int]:
    digest, size = asset.get("digest"), asset.get("size")
    if (
        not isinstance(tag, str)
        or re.fullmatch(r"v[0-9]+(?:\.[0-9]+){1,2}", tag) is None
        or not isinstance(digest, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
        or type(size) is not int
        or not 0 < size <= maximum
        or asset.get("state") != "uploaded"
    ):
        msg = "VR release components have invalid size, digest, tag or upload state"
        raise DownloadError(msg)
    url = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"
    if asset.get("browser_download_url") != url:
        msg = "VR component URL does not belong to its official release"
        raise DownloadError(msg)
    return url, digest[7:], size


def components(
    *, kind: AssetKind = AssetKind.STANDALONE, progress: ProgressCallback | None = None
) -> Path:
    """Download and validate compatible binaries without a compiler or game data."""
    url, digest, size = published_asset(kind)
    root = cache_directory() / "vr" / digest
    # The downloader resumes a shared partial file. Keep its writer and the
    # publisher of the extracted set under one cross-process lock per asset.
    with ExclusiveFileLock(root / ".components.lock"):
        archive_path = download_verified(
            url, root / "components.zip", sha256=digest, size=size, progress=progress
        )
        target = root / "components"
        if target.exists():
            _files(target, kind)
            return target
        with TemporaryDirectory(prefix=".extract-", dir=root) as temporary:
            stage = Path(temporary) / "components"
            stage.mkdir()
            _extract(archive_path, stage, kind=kind)
            stage.replace(target)
        return target
