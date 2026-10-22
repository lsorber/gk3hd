"""Portable, strictly validated movie-generation and installation identities."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING, Self, cast

from gk3hd.system.files import is_portable_filename, is_sha256
from gk3hd.videos.catalog import MOVIE_INSTALL_PATH, replacement_name
from gk3hd.videos.interpolation import INTERPOLATION_RECIPE, cinematic_rate, output_frames

if TYPE_CHECKING:
    from collections.abc import Mapping

GENERATION_RECIPE = "seedvr2-temporal-4x-lab-av1-v10"
GENERATION_SCHEMA = 1
STATE_FILENAME = ".gk3hd-videos.json"
JOURNAL_FILENAME = ".gk3hd-videos-install.json"
_RATIONAL_COMPONENTS = 2


def read_json(path: Path) -> object:
    """Report malformed local state consistently before changing anything."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        msg = f"cannot read movie record {path.name}: {exc}"
        raise ValueError(msg) from exc


@dataclass(frozen=True, slots=True)
class MovieFile:
    """A flat installed alias, its original identity, and the exact owned bytes."""

    filename: str
    source_name: str
    source_sha256: str
    sha256: str
    size: int

    def __post_init__(self) -> None:
        """Reject unsafe names and invalid identities before filesystem access."""
        if (
            not is_portable_filename(self.source_name)
            or Path(self.source_name).suffix.casefold() not in {".avi", ".bik"}
            or self.filename != replacement_name(self.source_name)
            or not is_sha256(self.source_sha256)
            or not is_sha256(self.sha256)
            or self.size <= 0
        ):
            msg = "invalid movie file identity"
            raise ValueError(msg)

    @classmethod
    def from_dict(cls, value: object) -> Self:
        """Accept only typed, target-bound ownership evidence."""
        if not isinstance(value, dict) or set(value) != {
            "filename",
            "source_name",
            "source_sha256",
            "sha256",
            "size",
        }:
            msg = "invalid movie file record"
            raise ValueError(msg)
        filename, source, source_hash, digest, size = (
            value["filename"],
            value["source_name"],
            value["source_sha256"],
            value["sha256"],
            value["size"],
        )
        if not all(isinstance(item, str) for item in (filename, source, source_hash, digest)) or (
            type(size) is not int
        ):
            msg = "invalid movie file record types"
            raise ValueError(msg)
        return cls(filename, source, source_hash, digest, size)


@dataclass(frozen=True, slots=True)
class PlayerResource:
    """One flat, hash-bound player dependency or license owned with the videos."""

    filename: str
    sha256: str
    size: int

    def __post_init__(self) -> None:
        """Keep dependency identities portable and separate from movie aliases."""
        if (
            not is_portable_filename(self.filename)
            or not is_sha256(self.sha256)
            or self.size <= 0
            or Path(self.filename).suffix.casefold() == ".avi"
        ):
            msg = "invalid movie player resource"
            raise ValueError(msg)

    @classmethod
    def from_dict(cls, value: object) -> Self:
        """Reject malformed ownership records before filesystem access."""
        if (
            not isinstance(value, dict)
            or set(value) != {"filename", "sha256", "size"}
            or not isinstance(value["filename"], str)
            or not isinstance(value["sha256"], str)
            or type(value["size"]) is not int
        ):
            msg = "invalid movie player resource record"
            raise ValueError(msg)
        return cls(value["filename"], value["sha256"], value["size"])


@dataclass(frozen=True, slots=True)
class MovieState:
    """One complete installed movie set, independent of other components' INI edits."""

    files: tuple[MovieFile, ...]
    resources: tuple[PlayerResource, ...] = ()
    pack_identity: str | None = None

    @property
    def inventory(self) -> tuple[MovieFile | PlayerResource, ...]:
        """Include playback dependencies in verification, rollback and removal."""
        return (*self.files, *self.resources)

    def __post_init__(self) -> None:
        """Require a nonempty, unambiguous, case-insensitive inventory."""
        if not self.files or len({entry.filename.casefold() for entry in self.inventory}) != len(
            self.inventory
        ):
            msg = "empty or duplicate movie inventory"
            raise ValueError(msg)
        if self.pack_identity is not None and not is_sha256(self.pack_identity):
            msg = "invalid installed video-pack identity"
            raise ValueError(msg)

    def to_dict(self) -> dict[str, object]:
        """Persist only relative names, never local source or cache paths."""
        return {
            "schema_version": 1,
            "directory": MOVIE_INSTALL_PATH,
            "files": [asdict(entry) for entry in self.files],
            "resources": [asdict(entry) for entry in self.resources],
            "pack_identity": self.pack_identity,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        """Validate the fixed installation directory, schema and every file."""
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 1
            or value.get("directory") != MOVIE_INSTALL_PATH
            or not isinstance(value.get("files"), list)
            or not isinstance(value.get("resources", []), list)
        ):
            msg = "invalid movie installation state"
            raise ValueError(msg)
        return cls(
            tuple(MovieFile.from_dict(entry) for entry in value["files"]),
            tuple(PlayerResource.from_dict(entry) for entry in value.get("resources", [])),
            value.get("pack_identity"),
        )


def validate_generation(value: object) -> Mapping[str, object]:
    """Require complete 4x provenance, independently of the content recipe revision.

    A recipe change invalidates cache reuse, not ownership. Otherwise updating
    the pipeline would prevent safely regenerating its own previous outputs.
    """
    if (
        not isinstance(value, dict)
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != GENERATION_SCHEMA
        or not isinstance(value.get("recipe"), str)
        or not value["recipe"]
    ):
        msg = "movie is missing a generation record; run videos upscale first"
        raise ValueError(msg)
    original, generated = value.get("source_media"), value.get("media")
    if not isinstance(original, dict) or not isinstance(generated, dict):
        msg = "movie record is missing source/output media properties"
        raise TypeError(msg)
    for key in ("width", "height"):
        if (
            type(original.get(key)) is not int
            or type(generated.get(key)) is not int
            or original[key] <= 0
            or generated.get(key) != original[key] * 4
        ):
            msg = "movie record does not describe an exact 4x replacement"
            raise ValueError(msg)
    frames, original_frames = generated.get("frames"), original.get("frames")
    if (
        type(frames) is not int
        or frames <= 0
        or type(original_frames) is not int
        or original_frames < 0
    ):
        msg = "movie record changes or omits the original frame count"
        raise ValueError(msg)
    for media in (original, generated):
        _validate_streams(media)
    for key in ("audio_rate", "audio_channels"):
        if original.get(key) != generated.get(key):
            msg = f"movie record changes original {key}"
            raise ValueError(msg)
    _validate_cadence(value, original, generated)
    return value


def _validate_cadence(
    record: Mapping[str, object], original: Mapping[str, object], generated: Mapping[str, object]
) -> None:
    """Authorize only recorded, duration-preserving interpolation, never speed changes."""
    source_rate = Fraction(*cast("list[int]", original["rate"]))
    target_rate = Fraction(*cast("list[int]", generated["rate"]))
    frames, original_frames = generated["frames"], original["frames"]
    interpolation = record.get("interpolation")
    if interpolation is None:
        valid = target_rate == source_rate and (not original_frames or frames == original_frames)
    else:
        valid = (
            interpolation == {"recipe": INTERPOLATION_RECIPE, "rate": [60, 1]}
            and target_rate == cinematic_rate(source_rate)
            and target_rate != source_rate
            and record.get("codec") == "libaom-av1"
            and isinstance(original_frames, int)
            and frames == output_frames(original_frames, source_rate, target_rate)
        )
    if not valid:
        msg = "movie record changes original timing without valid interpolation provenance"
        raise ValueError(msg)


def _validate_streams(media: Mapping[str, object]) -> None:
    rate = media.get("rate")
    if (
        not isinstance(rate, list)
        or len(rate) != _RATIONAL_COMPONENTS
        or any(type(item) is not int or item <= 0 for item in rate)
    ):
        msg = "movie record has an invalid frame rate"
        raise ValueError(msg)
    audio_rate, channels = media.get("audio_rate"), media.get("audio_channels")
    valid_audio = (
        channels == 0
        if audio_rate is None
        else type(audio_rate) is int and audio_rate > 0 and type(channels) is int and channels > 0
    )
    if type(channels) is not int or not valid_audio:
        msg = "movie record has invalid audio properties"
        raise ValueError(msg)
