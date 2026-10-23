"""Durable intent records for crash-recoverable production installation."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal, Self

from gk3hd.patch.manifest import PatchManifest, manifest_path_for_exe
from gk3hd.system.files import atomic_write

if TYPE_CHECKING:
    from pathlib import Path

_JOURNAL_SCHEMA = 2
_SHA256_LENGTH = 64
type JournalPhase = Literal["rollback", "committed"]


class JournalError(RuntimeError):
    """Report unsafe or malformed production recovery evidence."""


def install_journal_path(exe: Path) -> Path:
    """Return the durable intent record adjacent to one executable."""
    target = exe.resolve()
    return target.with_name(f"{target.name}.gk3hd-install.json")


@dataclass(frozen=True, slots=True)
class ApplyJournal:
    """Describe every state an interrupted apply is allowed to contain."""

    exe: Path
    backup_name: str
    backup_existed: bool
    original_sha256: str
    installed_sha256: str
    manifest_json: str
    phase: JournalPhase = "rollback"
    previous_manifest: str | None = None
    previous_executable: str | None = None
    transition_json: str | None = None

    @classmethod
    def create(
        cls,
        *,
        exe: Path,
        backup: Path,
        backup_existed: bool,
        manifest: PatchManifest,
        transition: PatchManifest | None = None,
    ) -> Self:
        """Create rollback intent before any installation-owned mutation."""
        target = exe.resolve()
        expected_backup = target.with_suffix(f"{target.suffix}.bak")
        if backup.resolve() != expected_backup:
            message = "installation journal backup is not the target's canonical backup"
            raise JournalError(message)
        path = manifest_path_for_exe(target)
        previous = PatchManifest.from_path(path) if path.is_file() else None
        executable = target.read_bytes() if previous else None
        return cls(
            exe=target,
            backup_name=backup.name,
            backup_existed=backup_existed,
            original_sha256=manifest.original_sha256,
            installed_sha256=manifest.installed_sha256,
            manifest_json=manifest.to_json(),
            previous_manifest=previous.to_json() if previous else None,
            previous_executable=base64.b64encode(executable).decode("ascii")
            if executable
            else None,
            transition_json=transition.to_json() if transition else None,
        )

    @property
    def path(self) -> Path:
        """Return this journal's target-bound file path."""
        return install_journal_path(self.exe)

    @property
    def backup(self) -> Path:
        """Resolve the validated adjacent backup name."""
        return self.exe.with_name(self.backup_name)

    @property
    def manifest(self) -> PatchManifest:
        """Parse and validate the exact intended installation manifest."""
        return PatchManifest.from_json(self.manifest_json, source=str(self.path))

    def committed(self) -> Self:
        """Return evidence that installed verification completed successfully."""
        return replace(self, phase="committed")

    def write(self) -> None:
        """Atomically publish and flush this recovery boundary."""
        payload = {
            "schema": _JOURNAL_SCHEMA,
            "phase": self.phase,
            "exe": str(self.exe),
            "backup_name": self.backup_name,
            "backup_existed": self.backup_existed,
            "original_sha256": self.original_sha256,
            "installed_sha256": self.installed_sha256,
            "manifest_json": self.manifest_json,
            "previous_manifest": self.previous_manifest,
            "previous_executable": self.previous_executable,
            "transition_json": self.transition_json,
        }
        atomic_write(
            self.path,
            (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(),
        )

    @classmethod
    def from_path(cls, *, exe: Path) -> Self:
        """Load strict target-bound evidence without trusting stored paths."""
        target = exe.resolve()
        path = install_journal_path(target)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            message = f"cannot read installation recovery journal {path}: {exc}"
            raise JournalError(message) from exc
        if not isinstance(payload, dict):
            message = f"installation recovery journal {path} is not a JSON object"
            raise JournalError(message)
        phase = payload.get("phase")
        stored_exe = payload.get("exe")
        backup_name = payload.get("backup_name")
        backup_existed = payload.get("backup_existed")
        original_sha256 = payload.get("original_sha256")
        installed_sha256 = payload.get("installed_sha256")
        manifest_json = payload.get("manifest_json")
        expected_backup_name = target.with_suffix(f"{target.suffix}.bak").name
        valid = (
            payload.get("schema") in {1, _JOURNAL_SCHEMA}
            and phase in {"rollback", "committed"}
            and stored_exe == str(target)
            and isinstance(backup_name, str)
            and backup_name == expected_backup_name
            and isinstance(backup_existed, bool)
            and isinstance(original_sha256, str)
            and _is_sha256(original_sha256)
            and isinstance(installed_sha256, str)
            and _is_sha256(installed_sha256)
            and isinstance(manifest_json, str)
            and all(
                payload.get(key) is None or isinstance(payload[key], str)
                for key in ("previous_manifest", "previous_executable", "transition_json")
            )
        )
        if not valid:
            message = f"installation recovery journal {path} is malformed or for another target"
            raise JournalError(message)
        journal = cls(
            exe=target,
            backup_name=backup_name,
            backup_existed=backup_existed,
            original_sha256=original_sha256,
            installed_sha256=installed_sha256,
            manifest_json=manifest_json,
            phase=phase,
            previous_manifest=payload.get("previous_manifest"),
            previous_executable=payload.get("previous_executable"),
            transition_json=payload.get("transition_json"),
        )
        manifest = journal.manifest
        if (
            manifest.original_sha256 != journal.original_sha256
            or manifest.installed_sha256 != journal.installed_sha256
            or manifest.backup_path != journal.backup_name
        ):
            message = f"installation recovery journal {path} contradicts its manifest"
            raise JournalError(message)
        journal._validate_update()
        return journal

    def _validate_update(self) -> None:
        """Bind any prior bytes and transition to the same supported original."""
        journal = self
        manifest = journal.manifest
        if journal.previous_manifest is not None:
            previous = PatchManifest.from_json(journal.previous_manifest)
            if (
                not isinstance(journal.previous_executable, str)
                or previous.original_sha256 != journal.original_sha256
            ):
                msg = "patch update journal has invalid prior installation evidence"
                raise JournalError(msg)
            original = base64.b64decode(journal.previous_executable, validate=True)
            if hashlib.sha256(original).hexdigest() != previous.installed_sha256:
                msg = "patch update journal has an invalid prior executable"
                raise JournalError(msg)
        elif journal.previous_executable is not None:
            msg = "patch update journal has an executable without ownership evidence"
            raise JournalError(msg)
        if journal.transition_json is not None:
            transition = PatchManifest.from_json(journal.transition_json)
            if (
                transition.installed_sha256 != manifest.installed_sha256
                or transition.original_sha256 != manifest.original_sha256
                or transition.backup_path != manifest.backup_path
                or transition.patches != manifest.patches
            ):
                msg = "patch update journal has an inconsistent transition"
                raise JournalError(msg)


def _is_sha256(value: str) -> bool:
    return len(value) == _SHA256_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )
