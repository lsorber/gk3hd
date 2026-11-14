"""Bounded private transfer archives for an already prepared standalone player.

This is packaging, not renderer qualification or game ownership verification.
Game data stays local and must never be included in a public APK or release.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, TypedDict
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo

from gk3hd.system.files import is_sha256

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

REQUIRED_FILES = frozenset(
    {
        "GK3-VR.exe",
        "gk3hd-wine-launcher.exe",
        "ddraw.dll",
        "openxr_wxr32.dll",
        "openxr.json",
        "launch-switches.txt",
        "binkw32.dll",
        "GK3.ini",
        "dxvk.conf",
    }
)
_MAX_FILE = 512 * 1024**2
MAX_PAYLOAD_BYTES = 16 * 1024**3
# The combined default texture/video pack can exceed 8 GiB in transit.
MAX_ARCHIVE_BYTES = 16 * 1024**3
_MAX_ENTRIES = 20_000
_MAX_PATH = 240
_MAX_MANIFEST = 2 * 1024**2
_MAX_COMPONENT_BYTES = 64 * 1024**2
_MAX_JOURNAL_CHANGES = 32
_COMPONENT_SCHEMA = 2
_VERIFY_SCHEMA = 3
_ADDITIONS_SCHEMA = 4
_BLOCK = 128 * 1024
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", re.IGNORECASE)


class _FileIdentity(TypedDict):
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class BundleReceipt:
    """Identity of the exact bytes to verify on the receiving headset."""

    path: Path
    sha256: str
    files: int
    payload_bytes: int
    component_update: bool = False
    inventory: dict[str, _FileIdentity] = field(default_factory=dict, repr=False, compare=False)
    verification_only: bool = False
    component_additions: bool = False


@dataclass(frozen=True, slots=True)
class BundleManifest:
    """Bounded archive inventory, before choosing which bytes to transfer."""

    path: Path
    inventory: dict[str, _FileIdentity]
    payload_bytes: int
    schema: int

    @property
    def component_update(self) -> bool:
        """Whether the archive depends on an installed inventory."""
        return self.schema != 1

    @property
    def verification_only(self) -> bool:
        """Whether only the installed inventory needs verification."""
        return self.schema == _VERIFY_SCHEMA

    @property
    def component_additions(self) -> bool:
        """Whether the archive uses the bounded additions journal."""
        return self.schema == _ADDITIONS_SCHEMA


def _safe_name(name: str) -> bool:
    return (
        name.startswith("game/")
        and name.casefold() != "game/.gk3hd-standalone.json"
        and len(name) <= _MAX_PATH
        and re.fullmatch(r"[A-Za-z0-9_./ '~-]+", name) is not None
        and all(
            part not in {"", ".", ".."}
            and not part.endswith((".", " "))
            and not _RESERVED.fullmatch(part.split(".", 1)[0])
            for part in name.split("/")
        )
    )


def _plan(files: Mapping[str, Path]) -> tuple[list[tuple[str, Path, int]], int]:
    planned: list[tuple[str, Path, int]] = []
    seen: set[str] = set()
    total = 0
    for relative, source in sorted(files.items()):
        name = f"game/{relative}"
        if not _safe_name(name) or name.casefold() in seen:
            msg = f"Unsafe or duplicate standalone path: {relative}"
            raise ValueError(msg)
        if source.is_symlink() or not source.is_file():
            msg = f"Standalone input must be a regular file: {relative}"
            raise ValueError(msg)
        size = source.stat().st_size
        if size > _MAX_FILE:
            msg = f"Standalone input exceeds the size limit: {relative}"
            raise ValueError(msg)
        seen.add(name.casefold())
        total += size
        planned.append((name, source, size))
    if not REQUIRED_FILES.issubset(files) or not any(
        name.startswith("Data/") and name.casefold().endswith(".brn") for name in files
    ):
        msg = "Standalone bundle requires the prepared player and original Data archives"
        raise ValueError(msg)
    if total > MAX_PAYLOAD_BYTES or len(planned) > _MAX_ENTRIES:
        msg = "Standalone bundle exceeds its storage bound"
        raise ValueError(msg)
    return planned, total


def _write_archive(
    temporary: Path,
    planned: list[tuple[str, Path, int]],
    total: int,
    progress: Callable[[int, int], None] | None,
    expected_sha256: Mapping[str, str],
) -> None:
    inventory: dict[str, dict[str, int | str]] = {}
    complete = 0
    with ZipFile(temporary, "w", compression=ZIP_STORED) as archive:
        for name, source, size in planned:
            digest = hashlib.sha256()
            written = 0
            entry = ZipInfo(name)
            if name.casefold().endswith(".bmp"):
                entry.compress_type = ZIP_DEFLATED
                entry.compress_level = 1
            with source.open("rb") as incoming, archive.open(entry, "w", force_zip64=True) as sink:
                while block := incoming.read(_BLOCK):
                    written += len(block)
                    if written > size:
                        msg = "Standalone input changed during packaging; retry preparation"
                        raise ValueError(msg)
                    sink.write(block)
                    if archive.fp is None or archive.fp.tell() > MAX_ARCHIVE_BYTES:
                        msg = "Standalone archive exceeds its transfer size limit"
                        raise ValueError(msg)
                    digest.update(block)
                    complete += len(block)
                    if progress is not None:
                        progress(complete, total)
            if written != size:
                msg = "Standalone input changed during packaging; retry preparation"
                raise ValueError(msg)
            expected = expected_sha256.get(name[5:])
            if expected is not None and digest.hexdigest() != expected:
                msg = f"Standalone resource differs from its installed identity: {name}"
                raise ValueError(msg)
            inventory[name] = {"size": size, "sha256": digest.hexdigest()}
        metadata = json.dumps({"schema": 1, "files": inventory}, sort_keys=True).encode()
        if len(metadata) > _MAX_MANIFEST:
            msg = "Standalone manifest exceeds its storage bound"
            raise ValueError(msg)
        archive.writestr("bundle.json", metadata)


def build_bundle(
    files: Mapping[str, Path],
    output: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
    before_publish: Callable[[], None] | None = None,
    expected_sha256: Mapping[str, str] | None = None,
) -> BundleReceipt:
    """Archive explicit prepared files, never a recursive copy of a guest prefix.

    Names are relative to the private game directory. Existing output is never
    replaced. Hashes describe the bytes actually archived, not an earlier read.
    """
    planned, total = _plan(files)
    identities = dict(expected_sha256 or {})
    if set(identities) - set(files) or any(not is_sha256(value) for value in identities.values()):
        msg = "Invalid standalone resource identities"
        raise ValueError(msg)
    if output.exists():
        msg = "Standalone bundle output already exists; it was preserved"
        raise FileExistsError(msg)
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=output.parent, prefix=".gk3hd-bundle-", delete=False) as tmp:
        temporary = Path(tmp.name)
    try:
        _write_archive(temporary, planned, total, progress, identities)
        if temporary.stat().st_size > MAX_ARCHIVE_BYTES:
            msg = "Standalone archive exceeds its transfer size limit"
            raise ValueError(msg)
        with temporary.open("rb") as stream:
            digest_hex = hashlib.file_digest(stream, "sha256").hexdigest()
        if before_publish is not None:
            before_publish()
        # Exclusive publication on the same filesystem, including on Windows.
        os.link(temporary, output)
        return BundleReceipt(output, digest_hex, len(planned), total)
    finally:
        temporary.unlink(missing_ok=True)


def _archive_entries(archive: ZipFile) -> list[ZipInfo]:
    contents = archive.infolist()
    names = [entry.filename for entry in contents]
    if any(
        entry.compress_type not in {ZIP_STORED, ZIP_DEFLATED} or entry.flag_bits & 1
        for entry in contents
    ):
        msg = "Unsupported standalone archive compression"
        raise ValueError(msg)
    if len(contents) > _MAX_ENTRIES + 1 or len(set(names)) != len(contents):
        msg = "Duplicate or excessive standalone archive entries"
        raise ValueError(msg)
    return contents


def _inventory(archive: ZipFile) -> tuple[dict[str, _FileIdentity], int, int]:
    names = {entry.filename for entry in _archive_entries(archive)} - {"bundle.json"}
    metadata = archive.getinfo("bundle.json")
    if metadata.file_size > _MAX_MANIFEST:
        msg = "Oversized standalone manifest"
        raise ValueError(msg)
    manifest = json.loads(archive.read(metadata))
    schema = manifest.get("schema") if isinstance(manifest, dict) else None
    if type(schema) is not int or schema not in (
        1,
        _COMPONENT_SCHEMA,
        _VERIFY_SCHEMA,
        _ADDITIONS_SCHEMA,
    ):
        msg = "Unsupported standalone bundle schema"
        raise ValueError(msg)
    inventory = manifest.get("files")
    if (
        not isinstance(inventory, dict)
        or (schema == _VERIFY_SCHEMA and names)
        or (schema != _VERIFY_SCHEMA and not names)
        or not names.issubset(inventory)
        or (schema == 1 and names != inventory.keys())
        or len(inventory) > _MAX_ENTRIES
    ):
        msg = "Standalone archive differs from its file inventory"
        raise ValueError(msg)
    expected = {f"game/{name}" for name in REQUIRED_FILES}
    if not expected.issubset(inventory) or not any(
        name.startswith("game/Data/") and name.casefold().endswith(".brn") for name in inventory
    ):
        msg = "Standalone bundle is missing player files or original game data"
        raise ValueError(msg)
    seen: set[str] = set()
    validated: dict[str, _FileIdentity] = {}
    total = 0
    for name, record in inventory.items():
        if not _safe_name(name) or name.casefold() in seen or not isinstance(record, dict):
            msg = "Unsafe standalone file inventory"
            raise ValueError(msg)
        size, digest = record.get("size"), record.get("sha256")
        if (
            type(size) is not int
            or not 0 <= size <= _MAX_FILE
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or (name in names and archive.getinfo(name).file_size != size)
        ):
            msg = "Invalid standalone file size or digest"
            raise ValueError(msg)
        seen.add(name.casefold())
        validated[name] = {"size": size, "sha256": digest}
        total += size
    if total > MAX_PAYLOAD_BYTES:
        msg = "Standalone payload exceeds its storage bound"
        raise ValueError(msg)
    return validated, total, schema


def read_bundle_manifest(path: Path) -> BundleManifest:
    """Validate the bounded inventory without reading the archive payload."""
    if not path.is_file() or path.stat().st_size > MAX_ARCHIVE_BYTES:
        msg = "Missing or oversized standalone bundle"
        raise ValueError(msg)
    try:
        with ZipFile(path) as archive:
            inventory, total, schema = _inventory(archive)
    except (BadZipFile, KeyError) as error:
        msg = "Invalid standalone archive or missing bundle.json"
        raise ValueError(msg) from error
    return BundleManifest(path, inventory, total, schema)


def inspect_bundle(path: Path) -> BundleReceipt:
    """Hash the exact transfer archive. Android verifies every payload file."""
    manifest = read_bundle_manifest(path)
    with path.open("rb") as incoming:
        digest = hashlib.file_digest(incoming, "sha256").hexdigest()
    return BundleReceipt(
        path,
        digest,
        len(manifest.inventory),
        manifest.payload_bytes,
        manifest.component_update,
        manifest.inventory,
        manifest.verification_only,
        manifest.component_additions,
    )


def _installed_inventory(
    installed_receipt: str, desired: dict[str, _FileIdentity], *, allow_additions: bool
) -> tuple[dict[str, _FileIdentity], str | None] | None:
    try:
        receipt = json.loads(installed_receipt)
    except json.JSONDecodeError:
        return None
    if not isinstance(receipt, dict) or receipt.get("schema") != 1:
        return None
    previous = receipt.get("files")
    if not isinstance(previous, dict) or not previous.keys() <= desired.keys():
        return None
    additions = desired.keys() - previous.keys()
    if additions:
        parents = {name.rpartition("/")[0] for name in previous}
        if not allow_additions or any(
            name.rpartition("/")[0] not in parents
            or name.casefold() in {"game/gk3.ini", "game/conf.txt"}
            for name in additions
        ):
            return None
    if any(
        not isinstance(entry, dict)
        or type(entry.get("size")) is not int
        or not 0 <= entry["size"] <= _MAX_FILE
        or not isinstance(entry.get("sha256"), str)
        or not is_sha256(entry["sha256"])
        for entry in previous.values()
    ):
        return None
    archive = receipt.get("bundle_sha256")
    return previous, archive if isinstance(archive, str) and is_sha256(archive) else None


def _replacements(
    previous: dict[str, _FileIdentity], desired: dict[str, _FileIdentity]
) -> dict[str, _FileIdentity]:
    return {
        name: entry
        for name, entry in desired.items()
        if name not in previous
        or previous[name]["size"] != entry["size"]
        or previous[name]["sha256"] != entry["sha256"]
    }


def _fits_component_journal(
    previous: dict[str, _FileIdentity], changed: dict[str, _FileIdentity]
) -> bool:
    old_bytes = sum(previous[name]["size"] for name in changed if name in previous)
    new_bytes = sum(entry["size"] for entry in changed.values())
    return (
        len(changed) <= _MAX_JOURNAL_CHANGES
        and new_bytes <= _MAX_COMPONENT_BYTES
        and old_bytes + new_bytes <= 2 * _MAX_COMPONENT_BYTES
    )


def require_component_base(update: BundleReceipt, installed_receipt: str) -> None:
    """Reject an explicit delta built against a different installed inventory."""
    base = _installed_inventory(
        installed_receipt, update.inventory, allow_additions=update.component_additions
    )
    if base is not None:
        previous, archive_hash = base
        changed = _replacements(previous, update.inventory)
        if (
            not changed
            and archive_hash is not None
            and (update.verification_only or archive_hash == update.sha256)
        ):
            return  # The same archive is already installed and can be verified again.
        if (
            not update.verification_only
            and archive_hash is not None
            and archive_hash != update.sha256
            and (
                not update.component_additions
                or (
                    len(previous) < len(update.inventory)
                    and _fits_component_journal(previous, changed)
                )
            )
        ):
            try:
                with ZipFile(update.path) as archive:
                    payload = {entry.filename for entry in _archive_entries(archive)} - {
                        "bundle.json"
                    }
            except BadZipFile as error:
                msg = "Standalone component update changed before transfer"
                raise ValueError(msg) from error
            if payload == changed.keys():
                return
    msg = (
        "This standalone component update does not match the installed player. "
        "Use a full bundle or prepare a fresh update."
    )
    raise ValueError(msg)


def staging_payload_bytes(
    bundle: BundleReceipt, installed_receipt: str, *, bounded_components: bool
) -> int:
    """Reserve space for an in-place update only when the target can use its journal."""
    if bundle.verification_only:
        return 0
    if not bundle.component_update or not bounded_components:
        return bundle.payload_bytes
    base = _installed_inventory(
        installed_receipt, bundle.inventory, allow_additions=bundle.component_additions
    )
    if base is None:
        return bundle.payload_bytes
    previous, _archive_hash = base
    changed = _replacements(previous, bundle.inventory)
    if (
        not changed
        or any(name.casefold() in {"game/gk3.ini", "game/conf.txt"} for name in changed)
        or not _fits_component_journal(previous, changed)
    ):
        return bundle.payload_bytes
    # Extracted components and the journal each hold a copy of the replacement
    # files and the ownership receipt.
    return 2 * (sum(entry["size"] for entry in changed.values()) + _MAX_MANIFEST + 512)


def component_bundle(
    full: BundleManifest | BundleReceipt,
    installed_receipt: str,
    output: Path,
    *,
    allow_verification: bool = False,
    allow_additions: bool = False,
) -> BundleReceipt | None:
    """Stage a small delta against a readable managed receipt, or keep the full bundle."""
    base = _installed_inventory(installed_receipt, full.inventory, allow_additions=allow_additions)
    if base is None:
        return None
    previous, archive_hash = base
    changed = _replacements(previous, full.inventory)
    if not changed and not (allow_verification and archive_hash is not None):
        return None
    if sum(entry["size"] for entry in changed.values()) > _MAX_COMPONENT_BYTES:
        return None
    if len(previous) < len(full.inventory):
        # The receiver can publish additions only through the bounded journal.
        if not _fits_component_journal(previous, changed):
            return None
        schema = _ADDITIONS_SCHEMA
    else:
        schema = _COMPONENT_SCHEMA if changed else _VERIFY_SCHEMA
    _write_component_archive(full, output, schema, changed)
    if output.stat().st_size >= full.path.stat().st_size:
        return None
    return inspect_bundle(output)


def _write_component_archive(
    full: BundleManifest | BundleReceipt,
    output: Path,
    schema: int,
    changed: dict[str, _FileIdentity],
) -> None:
    try:
        with ZipFile(full.path) as source, ZipFile(output, "x") as update:
            update.writestr(
                ZipInfo("bundle.json"),
                json.dumps({"schema": schema, "files": full.inventory}, sort_keys=True),
                compress_type=ZIP_DEFLATED,
            )
            for name, entry in sorted(changed.items()):
                if source.getinfo(name).file_size != entry["size"]:
                    msg = f"Standalone bundle changed before transfer: {name}"
                    raise ValueError(msg)
                data = source.read(name)
                if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                    msg = f"Standalone bundle changed before transfer: {name}"
                    raise ValueError(msg)
                update.writestr(ZipInfo(name), data, compress_type=ZIP_DEFLATED)
    except (BadZipFile, KeyError) as error:
        msg = "Standalone bundle changed before transfer"
        raise ValueError(msg) from error
