"""Discover, describe, and select save games for visual test runs."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, BinaryIO, Final

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_SAVE_COUNT: Final = 10
SAVE_DIRECTORY_NAME: Final = "Save Games"

_SAVE_MAGIC: Final = b"GK3!Save"
_CATALOG_OFFSET: Final = 0xF8
_LENGTH_BYTES: Final = 4
_MAX_FIELD_LENGTH: Final = 1024
_NATURAL_PARTS: Final = re.compile(r"(\d+)")
_NATIVE_SAVE_SLOT: Final = re.compile(r"(?i)^save\d{4}\.gk3$")


class SaveGameError(ValueError):
    """Raised when save-game discovery or selection cannot continue."""


@dataclass(frozen=True, slots=True)
class SaveGame:
    """A GK3 save and the catalog metadata stored in its header."""

    path: Path
    description: str
    room: str
    timeblock: str
    capture_stem: str = ""

    @property
    def output_stem(self) -> str:
        """Keep archived slots distinct without embedding machine-specific paths."""
        return self.capture_stem or self.path.stem


def find_save_directory(game_directory: Path, override: Path | None = None) -> Path:
    """Resolve an explicit folder or the populated default save location."""
    if override is not None:
        directory = override.expanduser().resolve()
        if not directory.is_dir():
            message = f"Save-game directory does not exist: {directory}"
            raise SaveGameError(message)
        return directory

    game_directory = game_directory.expanduser().resolve()
    matches = tuple(
        child
        for child in game_directory.iterdir()
        if child.is_dir() and child.name.casefold() == SAVE_DIRECTORY_NAME.casefold()
    )
    root_has_saves = _contains_save_games(game_directory)
    if not matches:
        if root_has_saves:
            return game_directory
        message = (
            f"Could not find '{SAVE_DIRECTORY_NAME}' in {game_directory}. "
            "Pass the save-game directory explicitly."
        )
        raise SaveGameError(message)
    if len(matches) > 1:
        message = (
            f"Found multiple '{SAVE_DIRECTORY_NAME}' folders in {game_directory}. "
            "Pass the save-game directory explicitly."
        )
        raise SaveGameError(message)
    save_directory = matches[0]
    if not _contains_save_games(save_directory) and root_has_saves:
        return game_directory
    return save_directory


def _contains_save_games(directory: Path) -> bool:
    return any(path.is_file() and path.suffix.casefold() == ".gk3" for path in directory.iterdir())


def catalog_save_games(directory: Path, *, recursive: bool = False) -> tuple[SaveGame, ...]:
    """Read saves in natural order, optionally including archived subfolders."""
    directory = directory.expanduser().resolve()
    paths = sorted(
        (
            path
            for path in (directory.rglob("*") if recursive else directory.iterdir())
            if path.is_file() and path.suffix.casefold() == ".gk3"
        ),
        key=lambda path: _natural_key(path.relative_to(directory).as_posix()),
    )
    if not paths:
        message = f"No .gk3 save games found in {directory}"
        raise SaveGameError(message)
    saves = []
    for path in paths:
        save = read_save_game(path)
        if path.parent != directory:
            relative = path.relative_to(directory)
            identity = hashlib.sha256(relative.as_posix().encode()).hexdigest()[:16]
            save = replace(
                save,
                capture_stem=f"archive-{identity}-{path.stem}",
                description=f"{relative.parent.as_posix()}: {save.description}",
            )
        saves.append(save)
    if len({save.output_stem.casefold() for save in saves}) != len(saves):
        message = "Save-game capture names collide; rename the conflicting slots"
        raise SaveGameError(message)
    return tuple(saves)


def select_save_games(
    saves: tuple[SaveGame, ...],
    *,
    count: int | None = None,
    all_saves: bool = False,
) -> tuple[SaveGame, ...]:
    """Select evenly distributed saves, defaulting to ten, or return every save."""
    if not saves:
        message = "No save games are available for selection"
        raise SaveGameError(message)
    if all_saves and count is not None:
        message = "--count and --all cannot be used together"
        raise SaveGameError(message)
    if all_saves:
        return saves

    requested = DEFAULT_SAVE_COUNT if count is None else count
    if requested < 1:
        message = "--count must be at least 1"
        raise SaveGameError(message)
    if requested >= len(saves):
        return saves
    if requested == 1:
        return (saves[len(saves) // 2],)

    span = len(saves) - 1
    intervals = requested - 1
    indices = tuple((index * span + intervals // 2) // intervals for index in range(requested))
    return tuple(saves[index] for index in indices)


def prefer_native_save_slots(saves: tuple[SaveGame, ...]) -> tuple[SaveGame, ...]:
    """Prefer GK3's numbered player slots over quick saves and developer fixtures."""
    native = tuple(save for save in saves if _NATIVE_SAVE_SLOT.fullmatch(save.path.name))
    return native or saves


def read_save_game(path: Path) -> SaveGame:
    """Read and validate one native save's description, room, and time block."""
    try:
        with path.open("rb") as handle:
            if handle.read(len(_SAVE_MAGIC)) != _SAVE_MAGIC:
                message = f"Not a GK3 save game: {path}"
                raise SaveGameError(message)
            handle.seek(_CATALOG_OFFSET)
            description, room, timeblock = (_read_catalog_field(handle, path) for _ in range(3))
    except OSError as error:
        message = f"Could not read save game {path}: {error}"
        raise SaveGameError(message) from error

    return SaveGame(path=path, description=description, room=room, timeblock=timeblock)


def _read_catalog_field(handle: BinaryIO, path: Path) -> str:
    raw_length = handle.read(_LENGTH_BYTES)
    if len(raw_length) != _LENGTH_BYTES:
        message = f"Truncated save-game catalog in {path}"
        raise SaveGameError(message)
    length = int.from_bytes(raw_length, "little")
    if length > _MAX_FIELD_LENGTH:
        message = f"Invalid save-game catalog in {path}"
        raise SaveGameError(message)
    payload = handle.read(length)
    terminator = handle.read(1)
    if len(payload) != length or terminator != b"\0":
        message = f"Truncated save-game catalog in {path}"
        raise SaveGameError(message)
    try:
        return payload.decode("ascii")
    except UnicodeDecodeError as error:
        message = f"Invalid save-game catalog text in {path}"
        raise SaveGameError(message) from error


def _natural_key(value: str) -> tuple[tuple[int, int, str], ...]:
    return tuple(
        (0, int(part), "") if part.isdigit() else (1, 0, part.casefold())
        for part in _NATURAL_PARTS.split(value)
        if part
    )
