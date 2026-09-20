"""Build deterministic, size-bounded texture packs from analyzed replacements."""

from __future__ import annotations

import hashlib
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from gk3hd.system.files import atomic_write, json_bytes, sha256_file
from gk3hd.textures.analyze.manifest import load_feature_manifest
from gk3hd.textures.flat import explicit_dos_name_first
from gk3hd.textures.pack.format import (
    PACK_MANIFEST_FILENAME,
    PACK_SCHEMA,
    PackInventory,
    PackManifest,
    PackTexture,
    TexturePackError,
    _texture_member,
)
from gk3hd.textures.routing import plan_texture
from gk3hd.textures.workspace import PACK_LOCK_FILENAME, analysis_file, texture_pack_filename

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Set as AbstractSet

GITHUB_ASSET_LIMIT = 2_000_000_000

_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True, slots=True)
class PackBuildReport:
    """Release assets, source lock, and count produced by a local pack build."""

    archives: tuple[Path, ...]
    lock: Path
    textures: int


def build_texture_pack(
    source: Path,
    output: Path,
    *,
    version: str,
    included_filenames: AbstractSet[str] | None = None,
) -> PackBuildReport:
    """Create one logical pack as the minimum deterministic release assets."""
    source = source.resolve()
    output = output.resolve()
    if not source.is_dir():
        msg = f"PNG source directory does not exist: {source}"
        raise TexturePackError(msg)
    if output.name != texture_pack_filename(version):
        msg = f"texture pack must be named {texture_pack_filename(version)}"
        raise TexturePackError(msg)
    pngs = sorted(
        (path for path in source.rglob("*") if path.is_file() and path.suffix.casefold() == ".png"),
        key=explicit_dos_name_first,
    )
    _require_unique_basenames(pngs)
    if included_filenames is not None:
        pngs = [path for path in pngs if path.name.casefold() in included_filenames]
    if not pngs:
        msg = f"no PNG textures found under {source}"
        raise TexturePackError(msg)
    output.parent.mkdir(parents=True, exist_ok=True)

    texture_entries: list[PackTexture] = []
    for path in pngs:
        width, height, mode = _image_facts(path)
        texture_entries.append(
            {
                "filename": path.name,
                "height": height,
                "mode": mode,
                "png_sha256": sha256_file(path),
                "width": width,
            }
        )

    inventory_payload: PackInventory = {
        "pack_version": version,
        "scale": 4,
        "texture_count": len(texture_entries),
        "textures": sorted(texture_entries, key=lambda item: item["filename"].casefold()),
    }
    inventory_sha256 = hashlib.sha256(json_bytes(inventory_payload)).hexdigest()
    groups = _partition_pack_paths(pngs, manifest_size=len(json_bytes(inventory_payload)))
    archives = tuple(_part_path(output, index + 1, len(groups)) for index in range(len(groups)))
    written: list[Path] = []
    try:
        for index, (archive, group) in enumerate(zip(archives, groups, strict=True), start=1):
            manifest_payload: PackManifest = {
                **inventory_payload,
                "inventory_sha256": inventory_sha256,
                "part_count": len(groups),
                "part_index": index,
                "part_textures": [path.name for path in group],
                "schema_version": PACK_SCHEMA,
            }
            _write_deterministic_pack(archive, manifest_payload, group)
            written.append(archive)
            _require_release_asset_size(archive)
    except BaseException:
        for archive in written:
            archive.unlink(missing_ok=True)
        raise
    archive_entries = [
        {
            "filename": archive.name,
            "sha256": sha256_file(archive),
            "size": archive.stat().st_size,
        }
        for archive in archives
    ]
    lock_payload = {
        "archives": archive_entries,
        "inventory_sha256": inventory_sha256,
        "tag": version if version.startswith("v") else f"v{version}",
    }
    lock = output.parent / PACK_LOCK_FILENAME
    atomic_write(lock, json_bytes(lock_payload))
    return PackBuildReport(archives, lock, len(texture_entries))


def _partition_pack_paths(
    paths: list[Path],
    *,
    manifest_size: int,
) -> tuple[tuple[Path, ...], ...]:
    """Split sorted PNGs into deterministic parts below the release-asset limit."""
    reserve = min(10_000_000, max(128, GITHUB_ASSET_LIMIT // 20))
    payload_budget = GITHUB_ASSET_LIMIT - reserve - manifest_size
    if payload_budget <= 0:
        msg = "texture-pack manifest leaves no room below the release-asset limit"
        raise TexturePackError(msg)
    groups: list[tuple[Path, ...]] = []
    current: list[Path] = []
    current_size = 0
    for path in paths:
        member = _texture_member(path.name)
        # ZIP local/central headers and the member name occur around the stored
        # payload. A deliberately generous allowance keeps the final file below
        # the hard limit; the written archive is checked as the final authority.
        estimated_size = path.stat().st_size + 256 + 2 * len(member.encode())
        if estimated_size > payload_budget:
            msg = f"texture is too large for one release asset: {path.name}"
            raise TexturePackError(msg)
        if current and current_size + estimated_size > payload_budget:
            groups.append(tuple(current))
            current = []
            current_size = 0
        current.append(path)
        current_size += estimated_size
    if current:
        groups.append(tuple(current))
    return tuple(groups)


def _require_release_asset_size(path: Path) -> None:
    """Reject a written archive at or above GitHub's hard asset limit."""
    if path.stat().st_size >= GITHUB_ASSET_LIMIT:
        msg = f"generated pack part exceeds GitHub's 2 GB asset limit: {path.name}"
        raise TexturePackError(msg)


def _part_path(output: Path, index: int, count: int) -> Path:
    """Name one archive part while retaining the simple one-file pack name."""
    if count == 1:
        return output
    width = max(2, len(str(count)))
    suffix = f"-part{index:0{width}d}-of-{count:0{width}d}"
    return output.with_name(f"{output.stem}{suffix}{output.suffix}")


def _write_deterministic_pack(
    destination: Path,
    manifest: PackManifest,
    paths: Iterable[Path],
) -> None:
    """Atomically write a reproducible manifest-first texture-pack ZIP."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as bundle:
            manifest_info = zipfile.ZipInfo(PACK_MANIFEST_FILENAME, _ZIP_TIMESTAMP)
            manifest_info.compress_type = zipfile.ZIP_DEFLATED
            manifest_info.external_attr = 0o100644 << 16
            bundle.writestr(manifest_info, json_bytes(manifest), compresslevel=9)
            for path in paths:
                info = zipfile.ZipInfo(_texture_member(path.name), _ZIP_TIMESTAMP)
                # PNG payloads are already compressed; storing them avoids a long,
                # effectively redundant deflate pass over the multi-gigabyte pack.
                info.compress_type = zipfile.ZIP_STORED
                info.external_attr = 0o100644 << 16
                bundle.writestr(info, path.read_bytes())
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _require_unique_basenames(paths: Iterable[Path]) -> None:
    names: set[str] = set()
    for path in paths:
        name = path.name.casefold()
        if name in names:
            msg = f"duplicate case-insensitive PNG basename: {path.name}"
            raise TexturePackError(msg)
        names.add(name)


def _image_facts(path: Path) -> tuple[int, int, str]:
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        mode = image.mode
        width, height = image.size
    if mode not in {"RGB", "RGBA", "L", "P"}:
        msg = f"unsupported PNG mode {mode} for {path.name}"
        raise TexturePackError(msg)
    return width, height, mode


def pack(
    source: Path,
    output: Path,
    *,
    version: str,
    features: Path | None = None,
) -> PackBuildReport:
    """Build one logical release pack from safe replacement textures."""
    source = source.resolve()
    features_path = analysis_file(source, features)
    if not features_path.is_file():
        msg = f"texture analysis does not exist: {features_path}; run textures analyze first"
        raise ValueError(msg)
    manifest = load_feature_manifest(features_path)
    available = {
        path.name.casefold()
        for path in source.rglob("*")
        if path.is_file() and path.suffix.casefold() == ".png"
    }
    analyzed = {f"{Path(name).stem}.PNG".casefold() for name in manifest}
    expected = {
        f"{Path(name).stem}.PNG".casefold()
        for name, texture in manifest.items()
        if not plan_texture(texture).kind.keeps_native_size
    }
    unknown = sorted(available - analyzed)
    if unknown:
        msg = f"PNG folder contains a texture absent from the analysis: {unknown[0]}"
        raise ValueError(msg)
    missing = sorted(expected - available)
    if missing:
        msg = f"PNG folder is missing an analyzed texture: {missing[0]}"
        raise ValueError(msg)
    return build_texture_pack(
        source,
        output,
        version=version,
        included_filenames=expected,
    )
