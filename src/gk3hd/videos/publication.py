"""Recover a completed movie if interruption separates AVI and receipt publication."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Self

from gk3hd.system.files import (
    atomic_write,
    is_portable_filename,
    is_sha256,
    json_bytes,
    sha256_file,
)
from gk3hd.videos.manifest import read_json, validate_generation

if TYPE_CHECKING:
    from collections.abc import Mapping


def pending_path(destination: Path) -> Path:
    """One durable intent file beside the output and its generation receipt."""
    return destination.with_suffix(destination.suffix + ".pending.json")


def _hash(path: Path) -> str | None:
    if path.is_symlink():
        msg = f"movie publication must not follow symbolic links: {path.name}"
        raise ValueError(msg)
    return sha256_file(path) if path.exists() else None


def record(destination: Path, value: object) -> Mapping[str, object]:
    """Bind a generation receipt to this filename and a valid content identity."""
    try:
        payload = validate_generation(value)
    except TypeError as exc:
        msg = f"invalid movie generation record: {destination.name}: {exc}"
        raise ValueError(msg) from exc
    name = payload.get("source_name")
    if (
        not isinstance(name, str)
        or not is_portable_filename(name)
        or Path(name).stem.casefold() != destination.stem.casefold()
        or not is_sha256(payload.get("source_sha256"))
        or not is_sha256(payload.get("output_sha256"))
    ):
        msg = f"invalid movie generation identity: {destination.name}"
        raise ValueError(msg)
    return payload


@dataclass(frozen=True, slots=True)
class GenerationSnapshot:
    """The previously owned file pair, captured before expensive inference."""

    movie_sha256: str | None
    record_sha256: str | None

    @classmethod
    def capture(cls, destination: Path) -> Self:
        """Never authorize replacement of a missing receipt or edited output."""
        receipt = destination.with_suffix(destination.suffix + ".json")
        movie_hash, record_hash = _hash(destination), _hash(receipt)
        if record_hash is None:
            if movie_hash is not None:
                msg = f"refusing to replace an unowned movie: {destination}"
                raise ValueError(msg)
        else:
            payload = record(destination, read_json(receipt))
            if movie_hash is not None and movie_hash != payload["output_sha256"]:
                msg = f"generated movie changed after generation: {destination.name}"
                raise ValueError(msg)
        return cls(movie_hash, record_hash)


def publish(
    destination: Path,
    temporary: Path,
    payload: Mapping[str, object],
    before: GenerationSnapshot,
) -> None:
    """Persist intent before changing either visible file of a completed movie."""
    record(destination, payload)
    _temporary(destination, temporary.name)
    intent = {
        "schema_version": 1,
        "destination": destination.name,
        "temporary": temporary.name,
        "before": asdict(before),
        "record": payload,
    }
    atomic_write(pending_path(destination), json_bytes(intent))
    _finish(destination, temporary, payload, before)


def recover_publication(destination: Path, *, source_name: str, source_sha256: str) -> None:
    """Finish only a validated pending result for this exact original source."""
    pending = pending_path(destination)
    if not pending.exists():
        return
    _ = _hash(pending)
    value = read_json(pending)
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or value.get("destination") != destination.name
        or not isinstance(value.get("before"), dict)
    ):
        msg = f"invalid pending movie publication: {pending.name}"
        raise ValueError(msg)
    payload = record(destination, value.get("record"))
    if payload["source_name"] != source_name or payload["source_sha256"] != source_sha256:
        msg = f"original changed; pending movie preserved for review: {destination.name}"
        raise ValueError(msg)
    before = value["before"]
    previous_movie, previous_record = before.get("movie_sha256"), before.get("record_sha256")
    if any(item is not None and not is_sha256(item) for item in (previous_movie, previous_record)):
        msg = "pending movie publication has an invalid previous identity"
        raise ValueError(msg)
    _finish(
        destination,
        _temporary(destination, value.get("temporary")),
        payload,
        GenerationSnapshot(previous_movie, previous_record),
    )


def _temporary(destination: Path, name: object) -> Path:
    if (
        not isinstance(name, str)
        or not is_portable_filename(name)
        or not name.startswith(f".{destination.stem}-")
        or Path(name).suffix != destination.suffix
    ):
        msg = "pending movie publication has an unsafe temporary filename"
        raise ValueError(msg)
    path = destination.parent / name
    if path.is_symlink():
        msg = "pending movie publication must not use symbolic links"
        raise ValueError(msg)
    return path


def _finish(
    destination: Path,
    temporary: Path,
    payload: Mapping[str, object],
    before: GenerationSnapshot,
) -> None:
    receipt = destination.with_suffix(destination.suffix + ".json")
    desired = payload["output_sha256"]
    new_receipt = json_bytes(payload)
    expected_record = hashlib.sha256(new_receipt).hexdigest()
    movie_hash, record_hash = _hash(destination), _hash(receipt)
    if movie_hash != desired:
        if (movie_hash, record_hash) != (before.movie_sha256, before.record_sha256):
            msg = f"movie output changed during publication; files preserved: {destination.name}"
            raise ValueError(msg)
        if _hash(temporary) != desired:
            msg = f"pending movie is incomplete or modified: {temporary.name}"
            raise ValueError(msg)
        temporary.replace(destination)
    elif record_hash not in (before.record_sha256, expected_record):
        msg = f"movie receipt changed during publication: {receipt.name}"
        raise ValueError(msg)
    atomic_write(receipt, new_receipt)
    if temporary.exists():
        if _hash(temporary) != desired:
            msg = f"modified pending movie preserved: {temporary.name}"
            raise ValueError(msg)
        temporary.unlink()
    pending_path(destination).unlink()
