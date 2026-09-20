"""Preserve literal GK3 names in flat directories on Windows filesystems."""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


class FlatNameError(RuntimeError):
    """Report a literal filename hidden by a different file's 8.3 alias."""


def explicit_dos_name_first(value: str | Path) -> tuple[bool, str]:
    """Sort explicit tilde names before long names that may claim their alias."""
    name = value.name if isinstance(value, Path) else value
    return "~" not in name, name.casefold()


def actual_files(directory: Path, *, suffix: str) -> dict[str, Path]:
    """Index actual directory entries, never paths resolved through 8.3 aliases."""
    if not directory.is_dir():
        return {}
    files: dict[str, Path] = {}
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.casefold() != suffix.casefold():
            continue
        key = path.name.casefold()
        if key in files:
            msg = f"duplicate case-insensitive filename: {files[key].name} and {path.name}"
            raise FlatNameError(msg)
        files[key] = path
    return files


@contextmanager
def protect_short_name_alias(destination: Path) -> Iterator[None]:
    """Temporarily move an alias owner while creating one literal GK3 name."""
    # An alias resolves to an existing file. Fresh names therefore cannot hide
    # an owner, and need no full directory scan (important for complete packs).
    if not destination.exists():
        yield
        return
    entries = actual_files(destination.parent, suffix=destination.suffix)
    if destination.name.casefold() in entries:
        yield
        return

    try:
        alias_stat = destination.stat()
    except OSError as exc:
        msg = f"cannot inspect filesystem alias for {destination.name}: {exc}"
        raise FlatNameError(msg) from exc
    identity = alias_stat.st_dev, alias_stat.st_ino
    owner = next(
        (path for path in entries.values() if (path.stat().st_dev, path.stat().st_ino) == identity),
        None,
    )
    if owner is None:
        msg = f"{destination.name} exists without a matching directory entry"
        raise FlatNameError(msg)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{owner.name}.", suffix=".alias-owner", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        owner.replace(temporary)
        yield
    finally:
        if temporary.exists():
            if owner.exists():
                msg = f"cannot restore the 8.3 alias owner {owner.name}"
                raise FlatNameError(msg)
            temporary.replace(owner)


def require_actual_file(path: Path) -> Path:
    """Return the matching real directory entry or reject an alias-only path."""
    actual = actual_files(path.parent, suffix=path.suffix).get(path.name.casefold())
    if actual is None:
        msg = f"file was not created with its literal name: {path.name}"
        raise FlatNameError(msg)
    return actual
