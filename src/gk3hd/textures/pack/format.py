"""Validate texture-pack inventories, member names, integrity and split-part identity."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

from gk3hd.system.files import is_portable_filename, is_sha256, json_bytes
from gk3hd.textures.progress import TextureInstallProgressCallback, report_install_progress
from gk3hd.textures.workspace import UPSCALE_DIRECTORY

if TYPE_CHECKING:
    from collections.abc import Mapping


PACK_SCHEMA = 2
PACK_SCALE = 4

PACK_MANIFEST_FILENAME = "texture-pack-manifest.json"


class TexturePackError(RuntimeError):
    """Report an invalid pack or unsafe texture installation state."""


class PackTexture(TypedDict):
    """Validated image identity shared by pack creation and conversion."""

    filename: str
    width: int
    height: int
    mode: str
    png_sha256: str


class PackInventory(TypedDict):
    """Stable logical inventory hashed independently of archive partitioning."""

    pack_version: str
    scale: int
    texture_count: int
    textures: list[PackTexture]


class PackManifest(PackInventory):
    """Current archive header plus its physical slice of the logical pack."""

    schema_version: int
    inventory_sha256: str
    part_count: int
    part_index: int
    part_textures: list[str]


def _load_pack_manifest(path: Path) -> PackManifest:
    payload, folded = _read_pack_manifest(path)
    _validate_manifest_header(path, payload)
    textures = cast("list[object]", payload["textures"])
    texture_names = [_texture_identity(value) for value in textures]
    if len({name.casefold() for name in texture_names}) != len(texture_names):
        msg = f"{path}: duplicate texture inventory entry"
        raise TexturePackError(msg)
    part_names = _part_texture_names(payload)
    _validate_part_members(path, folded, texture_names, part_names)
    inventory_sha256 = payload.get("inventory_sha256")
    if not is_sha256(inventory_sha256) or inventory_sha256 != _inventory_sha256(payload):
        msg = f"{path}: logical texture inventory hash does not match"
        raise TexturePackError(msg)
    return cast("PackManifest", payload)


def _read_pack_manifest(path: Path) -> tuple[dict[str, object], list[str]]:
    """Read one archive manifest and its case-folded member list."""
    try:
        with zipfile.ZipFile(path) as bundle:
            infos = bundle.infolist()
            names = [info.filename for info in infos]
            folded = [name.casefold() for name in names]
            if len(folded) != len(set(folded)) or PACK_MANIFEST_FILENAME not in names:
                msg = f"{path}: texture pack has a missing or duplicate member"
                raise TexturePackError(msg)
            manifest_bytes = bundle.read(PACK_MANIFEST_FILENAME)
        payload = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        msg = f"cannot read texture-pack manifest from {path}: {exc}"
        raise TexturePackError(msg) from exc
    if not isinstance(payload, dict):
        msg = f"{path}: texture-pack manifest must be an object"
        raise TexturePackError(msg)
    return payload, folded


def _validate_manifest_header(path: Path, payload: Mapping[str, object]) -> None:
    """Validate one manifest's schema and shared inventory header."""
    if payload.get("schema_version") != PACK_SCHEMA:
        msg = f"{path}: expected texture-pack schema {PACK_SCHEMA}"
        raise TexturePackError(msg)
    if not isinstance(payload.get("pack_version"), str) or not payload["pack_version"]:
        msg = f"{path}: invalid pack version"
        raise TexturePackError(msg)
    textures = payload.get("textures")
    count = payload.get("texture_count")
    if (
        not isinstance(textures, list)
        or type(count) is not int
        or count != len(textures)
        or not textures
        or type(payload.get("scale")) is not int
        or payload["scale"] != PACK_SCALE
    ):
        msg = f"{path}: invalid texture inventory"
        raise TexturePackError(msg)


def _validate_part_members(
    path: Path,
    folded: list[str],
    texture_names: list[str],
    part_names: tuple[str, ...],
) -> None:
    """Require the physical members to exactly match their declared part."""
    known = {name.casefold() for name in texture_names}
    if any(name.casefold() not in known for name in part_names):
        msg = f"{path}: part inventory is absent from the logical texture inventory"
        raise TexturePackError(msg)
    expected_members = {PACK_MANIFEST_FILENAME.casefold()}
    expected_members.update(_texture_member(name).casefold() for name in part_names)
    if set(folded) != expected_members:
        msg = f"{path}: archive members do not match the texture inventory"
        raise TexturePackError(msg)


def _load_pack_set(
    archives: tuple[Path, ...],
    *,
    progress: TextureInstallProgressCallback | None = None,
) -> tuple[PackManifest, tuple[PackManifest, ...], str]:
    """Validate a complete ordered set and return its shared logical inventory."""
    if not archives:
        msg = "texture pack has no archive parts"
        raise TexturePackError(msg)
    loaded_items: list[PackManifest] = []
    report_install_progress(progress, "Validating texture pack", 0, len(archives))
    for index, archive in enumerate(archives, start=1):
        loaded_items.append(_load_pack_manifest(archive))
        report_install_progress(progress, "Validating texture pack", index, len(archives))
    manifests = tuple(loaded_items)
    first = manifests[0]

    part_count = first["part_count"]
    inventory_sha256 = first["inventory_sha256"]
    if part_count != len(manifests):
        msg = f"texture pack requires {part_count} archive parts; received {len(manifests)}"
        raise TexturePackError(msg)
    _require_shared_inventory(manifests, first, inventory_sha256, part_count)
    seen_textures = _ordered_part_inventory(manifests, part_count)
    expected = {item["filename"].casefold() for item in first["textures"]}
    if seen_textures != expected:
        msg = "texture-pack parts do not cover the complete logical inventory"
        raise TexturePackError(msg)
    return first, manifests, inventory_sha256


def _require_shared_inventory(
    manifests: tuple[PackManifest, ...],
    first: PackManifest,
    inventory_sha256: str,
    part_count: int,
) -> None:
    """Require every part to identify the same version and full inventory."""
    for manifest in manifests:
        if (
            manifest["inventory_sha256"] != inventory_sha256
            or manifest["pack_version"] != first["pack_version"]
            or manifest["part_count"] != part_count
            or manifest["textures"] != first["textures"]
        ):
            msg = "texture-pack parts do not describe the same logical inventory"
            raise TexturePackError(msg)


def _ordered_part_inventory(
    manifests: tuple[PackManifest, ...],
    part_count: int,
) -> set[str]:
    """Validate part numbering and return each uniquely assigned texture."""
    ordered: list[PackManifest | None] = [None] * part_count
    seen_textures: set[str] = set()
    for manifest in manifests:
        part_index = manifest["part_index"]
        if ordered[part_index - 1] is not None:
            msg = f"texture-pack part {part_index} occurs more than once"
            raise TexturePackError(msg)
        ordered[part_index - 1] = manifest
        for name in manifest["part_textures"]:
            key = name.casefold()
            if key in seen_textures:
                msg = f"texture occurs in multiple pack parts: {name}"
                raise TexturePackError(msg)
            seen_textures.add(key)
    if any(item is None for item in ordered):
        msg = "texture-pack parts have an incomplete part sequence"
        raise TexturePackError(msg)
    return seen_textures


def _inventory_sha256(manifest: Mapping[str, object]) -> str:
    """Return the stable identity shared by every part of a logical pack."""
    payload = {
        "pack_version": manifest.get("pack_version"),
        "scale": manifest.get("scale"),
        "texture_count": manifest.get("texture_count"),
        "textures": manifest.get("textures"),
    }
    return hashlib.sha256(json_bytes(payload)).hexdigest()


def _part_texture_names(manifest: Mapping[str, object]) -> tuple[str, ...]:
    """Validate and return the PNG inventory physically held by one part."""
    part_count = manifest.get("part_count")
    part_index = manifest.get("part_index")
    values = manifest.get("part_textures")
    if (
        type(part_count) is not int
        or part_count <= 0
        or type(part_index) is not int
        or not 1 <= part_index <= part_count
        or not isinstance(values, list)
        or not values
    ):
        msg = "texture-pack part has an invalid physical inventory"
        raise TexturePackError(msg)
    names: list[str] = []
    for value in values:
        if not isinstance(value, str) or _safe_texture_filename(value) != value:
            msg = "texture-pack part has an unsafe texture filename"
            raise TexturePackError(msg)
        if Path(value).suffix.casefold() != ".png":
            msg = "texture-pack part member must be a PNG"
            raise TexturePackError(msg)
        names.append(value)
    if len({name.casefold() for name in names}) != len(names):
        msg = "texture-pack part contains a duplicate texture"
        raise TexturePackError(msg)
    return tuple(names)


def _texture_identity(value: object) -> str:
    """Validate and return one flat texture filename."""
    if not isinstance(value, dict):
        msg = "texture manifest texture must be an object"
        raise TexturePackError(msg)
    filename = value.get("filename")
    if not isinstance(filename, str) or _safe_texture_filename(filename) != filename:
        msg = "texture manifest has an unsafe texture filename"
        raise TexturePackError(msg)
    if Path(filename).suffix.casefold() != ".png":
        msg = "texture manifest member must be a PNG"
        raise TexturePackError(msg)
    width = value.get("width")
    height = value.get("height")
    valid_dimensions = type(width) is int and width > 0 and type(height) is int and height > 0
    if (
        not is_sha256(value.get("png_sha256"))
        or not isinstance(value.get("mode"), str)
        or value.get("mode") not in {"RGB", "RGBA", "L", "P"}
        or not valid_dimensions
    ):
        msg = f"texture manifest has invalid image facts: {filename}"
        raise TexturePackError(msg)
    return filename


def _safe_texture_filename(value: str) -> str:
    if not is_portable_filename(value):
        msg = f"unsafe texture filename: {value!r}"
        raise TexturePackError(msg)
    return value


def _texture_member(filename: str) -> str:
    """Return the one canonical archive member for a flat PNG filename."""
    return f"{UPSCALE_DIRECTORY}/{_safe_texture_filename(filename)}"
