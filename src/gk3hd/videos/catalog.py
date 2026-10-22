"""Find the game's loose Bink/AVI originals without modifying or copying them."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from gk3hd.videos.transaction import MovieProgress

from gk3hd.system.files import sha256_file

MOVIE_EXTENSIONS = frozenset({".bik", ".avi"})
MOVIE_INSTALL_PATH = "gk3hd/videos/installed"
MOVIE_ASSET_PREFIX = "GK3HD-"
# Asset::SetName (0x0056CA50) always terminates its 32-byte record at byte 30.
MAX_MOVIE_ASSET_NAME = 30


def replacement_name(filename: str) -> str:
    """Use an unambiguous short alias that survives native asset-name storage."""
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    if (
        not stem
        or stem in {".", ".."}
        or any(character in filename for character in '/\\:*?"<>|')
        or any(not character.isprintable() for character in filename)
    ):
        msg = f"movie name must be a simple filename: {filename!r}"
        raise ValueError(msg)
    alias = f"{MOVIE_ASSET_PREFIX}{stem.upper()}.AVI"
    if not alias.isascii() or len(alias) > MAX_MOVIE_ASSET_NAME:
        msg = (
            f"movie alias must fit the engine's {MAX_MOVIE_ASSET_NAME}-byte asset name: {filename}"
        )
        raise ValueError(msg)
    return alias


def movie_format(path: Path) -> str | None:
    """Recognize actual media headers, not files merely named like videos."""
    with path.open("rb") as stream:
        header = stream.read(12)
    if header[:3] == b"BIK":
        return "Bink"
    if header[:4] == b"\x1a\x45\xdf\xa3":
        return "Matroska"
    if header[:4] == b"RIFF" and header[8:12] == b"AVI ":
        return "AVI"
    return None


def find_movies(directory: Path, selections: Sequence[str] = ()) -> tuple[Path, ...]:
    """Find originals, optionally selected by case-insensitive filename/glob."""
    if not directory.is_dir():
        msg = f"movie source directory does not exist: {directory}"
        raise ValueError(msg)
    videos = sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.casefold() in MOVIE_EXTENSIONS
        ),
        key=lambda path: (path.stem.casefold() != "intro", path.name.casefold()),
    )
    names: set[str] = set()
    for movie in videos:
        key = movie.stem.casefold()
        if key in names:
            msg = f"ambiguous movie output name: {movie.stem}"
            raise ValueError(msg)
        names.add(key)
    for selection in selections:
        if not any(
            fnmatch.fnmatchcase(path.name.casefold(), selection.casefold()) for path in videos
        ):
            msg = f"no original movie matches {selection!r} in {directory}"
            raise ValueError(msg)
    selected = tuple(
        path
        for path in videos
        if not selections
        or any(
            fnmatch.fnmatchcase(path.name.casefold(), selection.casefold())
            for selection in selections
        )
    )
    invalid = [path for path in selected if movie_format(path) is None]
    if selections and invalid:
        msg = f"not recognizable Bink/AVI media: {', '.join(path.name for path in invalid)}"
        raise ValueError(msg)
    selected = tuple(path for path in selected if path not in invalid)
    if not selected:
        msg = f"no Bink or AVI videos found in {directory}"
        raise ValueError(msg)
    return selected


def movie_workspace(game_dir: Path) -> Path:
    """Keep generated video files together, separate from original game media."""
    return game_dir / "gk3hd" / "videos"


def extract(source: Path, output: Path, *, progress: MovieProgress | None = None) -> int:
    """Resume byte-identical copies, never overwrite differing user files."""
    paths = find_movies(source)
    output.mkdir(parents=True, exist_ok=True)
    total = sum(path.stat().st_size for path in paths)
    completed = 0
    for path in paths:
        target = output / path.name
        digest = sha256_file(path)
        if target.exists():
            if sha256_file(target) != digest:
                msg = f"refusing to overwrite a different original video: {target}"
                raise ValueError(msg)
            completed += path.stat().st_size
        else:
            descriptor, name = tempfile.mkstemp(prefix=".extract-", dir=output)
            temporary = type(output)(name)
            try:
                copied_hash = hashlib.sha256()
                with path.open("rb") as original, os.fdopen(descriptor, "wb") as copied:
                    while block := original.read(1024 * 1024):
                        copied.write(block)
                        copied_hash.update(block)
                        completed += len(block)
                        if progress:
                            progress("Extracting videos", completed, total)
                if copied_hash.hexdigest() != digest:
                    msg = f"original video changed during extraction: {path.name}"
                    raise ValueError(msg)
                temporary.rename(target)
            finally:
                temporary.unlink(missing_ok=True)
        if progress:
            progress("Extracting videos", completed, total)
    return len(paths)
