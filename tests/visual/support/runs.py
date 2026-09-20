"""Shared run selection and portable capture indexes for both visual suites."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

from gk3hd.system.files import atomic_write
from tests.visual.support.saves import SaveGame

if TYPE_CHECKING:
    from collections.abc import Sequence

type Capture = tuple[SaveGame, Path, Path]
_FIELDS = frozenset({"name", "description", "room", "timeblock", "reference", "current"})


def comparison_run(
    output_root: Path | None = None,
    *,
    resume: Path | None = None,
    append_resolution: tuple[int, int] | None = None,
) -> Path:
    """Start a dated run, resume one, or append special scenes to the latest match."""
    if resume is not None:
        run = resume.expanduser().resolve()
        if not run.is_dir():
            msg = f"comparison run does not exist: {run}"
            raise ValueError(msg)
        return run
    parent = output_root or Path(__file__).resolve().parents[3] / "build/visual"
    if append_resolution is not None and parent.is_dir():
        width, height = append_resolution
        candidates = sorted(
            path
            for path in parent.iterdir()
            if re.fullmatch(r"\d{8}-\d{6}", path.name)
            and (path / "reference-1024x768").is_dir()
            and (path / f"current-{width}x{height}").is_dir()
        )
        if candidates:
            return candidates[-1]
    return parent / time.strftime("%Y%m%d-%H%M%S")


def merge_captures(captures: Sequence[Capture], *, output: Path) -> tuple[Capture, ...]:
    """Keep both suites in one index, replacing only explicitly supplied entries.

    Paths are relative to the run folder, so moving a comparison run does not
    break its index. Older unindexed runs retain all paired PNGs, with basename
    labels until their suite supplies the richer catalog metadata again.
    """
    root = output.resolve().parent
    index = output / "captures.json"
    merged = {capture[0].output_stem.casefold(): capture for capture in _read_index(index, root)}
    directories = {
        (reference.parent, current.parent)
        for _save, reference, current in captures
        if reference.parent != current.parent
    }
    for reference_dir, current_dir in directories:
        for path in reference_dir.glob("*.png"):
            peer = current_dir / path.name
            if peer.is_file() and not path.stem.endswith("-failure"):
                key = path.stem.casefold()
                merged.setdefault(key, (SaveGame(Path(path.stem), path.stem, "", ""), path, peer))
    for capture in captures:
        merged[capture[0].output_stem.casefold()] = capture
    if not merged:
        msg = "no paired visual captures are available"
        raise ValueError(msg)
    result = tuple(merged[key] for key in sorted(merged))
    rows = [
        {
            "name": save.path.name,
            "description": save.description,
            "room": save.room,
            "timeblock": save.timeblock,
            "reference": reference.resolve().relative_to(root).as_posix(),
            "current": current.resolve().relative_to(root).as_posix(),
        }
        for save, reference, current in result
    ]
    atomic_write(index, (json.dumps(rows, indent=2) + "\n").encode())
    return result


def _read_index(index: Path, root: Path) -> tuple[Capture, ...]:
    """Validate the small local index before using any recorded file paths."""
    if not index.is_file():
        return ()
    rows: object = json.loads(index.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        msg = f"invalid comparison capture index: {index}"
        raise TypeError(msg)
    captures: list[Capture] = []
    for row in rows:
        if (
            not isinstance(row, dict)
            or row.keys() != _FIELDS
            or not all(isinstance(value, str) for value in row.values())
        ):
            msg = f"invalid comparison capture entry: {index}"
            raise ValueError(msg)
        fields = cast("dict[str, str]", row)
        name = Path(fields["name"])
        reference = (root / fields["reference"]).resolve()
        current = (root / fields["current"]).resolve()
        if name.name != fields["name"] or not all(
            path.is_relative_to(root) for path in (reference, current)
        ):
            msg = f"comparison capture paths must stay inside the run: {index}"
            raise ValueError(msg)
        save = SaveGame(
            name,
            fields["description"],
            fields["room"],
            fields["timeblock"],
            capture_stem=reference.stem if reference.stem != name.stem else "",
        )
        captures.append((save, reference, current))
    return tuple(captures)
