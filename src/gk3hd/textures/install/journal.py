"""Strict relative-path journal for crash-recoverable texture commits."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Self

from gk3hd.system.files import atomic_write, is_portable_filename, is_sha256
from gk3hd.system.ini import IniChange
from gk3hd.textures.workspace import INSTALL_DIRECTORY, TEXTURES_DIRECTORY, WORK_DIRECTORY

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

JOURNAL_FILENAME = ".gk3hd-textures-install.json"
_SCHEMA = 6
_TARGET_DIRECTORY = f"{WORK_DIRECTORY}/{TEXTURES_DIRECTORY}/{INSTALL_DIRECTORY}"
_STAGING_PARENT = PurePosixPath(WORK_DIRECTORY, TEXTURES_DIRECTORY)
_STAGING_PREFIX = ".install-"
_FACES_FILENAME = "FACES.TXT"


class TextureJournalError(RuntimeError):
    """Report malformed or unsafe texture recovery evidence."""


@dataclass(frozen=True, slots=True)
class JournalFile:
    """One newly created resource that an interrupted install may roll back."""

    filename: str
    sha256: str

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, object],
    ) -> Self:
        """Validate one flat managed filename and its exact installed identity."""
        filename = value.get("filename")
        sha256 = value.get("sha256")
        valid_filename = isinstance(filename, str) and (
            Path(filename).suffix.casefold() == ".bmp"
            or filename.casefold() == _FACES_FILENAME.casefold()
        )
        if (
            not isinstance(filename, str)
            or not is_portable_filename(filename)
            or not valid_filename
            or not isinstance(sha256, str)
            or not is_sha256(sha256)
        ):
            msg = "texture recovery journal has an unsafe file identity"
            raise TextureJournalError(msg)
        return cls(filename, sha256)

    def to_dict(self) -> dict[str, str]:
        """Return the persisted file identity."""
        return {"filename": self.filename, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class TextureJournal:
    """Describe the newly owned surfaces that rollback may remove."""

    game_dir: Path
    staging_directory: str
    target_directory: str
    ini: IniChange
    files: tuple[JournalFile, ...]

    @classmethod
    def create(
        cls,
        game_dir: Path,
        staging: Path,
        ini: IniChange,
        files: Iterable[Mapping[str, object]],
    ) -> Self:
        """Bind a texture-workspace staging directory and prepared INI edit."""
        root = game_dir.resolve()
        candidate = staging.resolve()
        staging_parent = (root / WORK_DIRECTORY / TEXTURES_DIRECTORY).resolve()
        if candidate.parent != staging_parent or not candidate.name.startswith(_STAGING_PREFIX):
            msg = "texture staging directory is outside the selected texture workspace"
            raise TextureJournalError(msg)
        identities = tuple(JournalFile.from_mapping(value) for value in files)
        names = {identity.filename.casefold() for identity in identities}
        if not identities or len(names) != len(identities):
            msg = "texture recovery journal has an empty or duplicate file inventory"
            raise TextureJournalError(msg)
        staging_directory = candidate.relative_to(root).as_posix()
        return cls(root, staging_directory, _TARGET_DIRECTORY, ini, identities)

    @property
    def path(self) -> Path:
        """Return the fixed journal path in the selected game directory."""
        return self.game_dir / JOURNAL_FILENAME

    @property
    def staging(self) -> Path:
        """Resolve the already validated relative staging directory."""
        return self.game_dir.joinpath(*PurePosixPath(self.staging_directory).parts)

    @property
    def target(self) -> Path:
        """Return the schema-validated installed-BMP directory."""
        return self.game_dir / self.target_directory

    def write(self) -> None:
        """Publish rollback intent before committing either owned surface."""
        payload = {
            "directory": self.target_directory,
            "files": [identity.to_dict() for identity in self.files],
            "ini": self.ini.to_dict(),
            "schema_version": _SCHEMA,
            "staging_directory": self.staging_directory,
        }
        atomic_write(
            self.path,
            (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(),
        )

    @classmethod
    def load(cls, game_dir: Path) -> Self:
        """Load and validate target-bound recovery evidence."""
        root = game_dir.resolve()
        path = root / JOURNAL_FILENAME
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            msg = f"cannot read texture recovery journal {path.name}: {exc}"
            raise TextureJournalError(msg) from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != _SCHEMA:
            msg = f"texture recovery journal {path.name} has an unsupported schema"
            raise TextureJournalError(msg)
        target_directory = payload.get("directory")
        if target_directory != _TARGET_DIRECTORY:
            msg = f"texture recovery journal {path.name} has an unsafe target directory"
            raise TextureJournalError(msg)
        staging_directory = _staging_directory(payload, root=root, source=path)
        files = payload.get("files")
        if not isinstance(files, list) or not all(isinstance(value, dict) for value in files):
            msg = f"texture recovery journal {path.name} has an invalid file inventory"
            raise TextureJournalError(msg)
        identities = tuple(JournalFile.from_mapping(value) for value in files)
        names = {identity.filename.casefold() for identity in identities}
        if not identities or len(names) != len(identities):
            msg = f"texture recovery journal {path.name} has an empty or duplicate file inventory"
            raise TextureJournalError(msg)
        return cls(
            root,
            staging_directory,
            target_directory,
            IniChange.from_dict(payload.get("ini")),
            identities,
        )


def _staging_directory(
    payload: Mapping[str, object],
    *,
    root: Path,
    source: Path,
) -> str:
    """Validate staging inside the one current texture workspace."""
    value = payload.get("staging_directory")
    if isinstance(value, str):
        relative = PurePosixPath(value)
        candidate = root.joinpath(*relative.parts).resolve()
        expected_parent = (root / WORK_DIRECTORY / TEXTURES_DIRECTORY).resolve()
        if (
            relative.parent == _STAGING_PARENT
            and relative.name.startswith(_STAGING_PREFIX)
            and candidate.parent == expected_parent
        ):
            return relative.as_posix()
    msg = f"texture recovery journal {source.name} has an unsafe staging directory"
    raise TextureJournalError(msg)
