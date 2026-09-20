"""Validated installation evidence shared by verification and restore."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from gk3hd.patch.model import BuildId, PatchId, ProfileId

MANIFEST_SCHEMA = 2
RUNTIME_ABI = 1
STATE_FILENAME = ".gk3hd-patch.json"
_SHA256_LENGTH = 64


class ManifestError(Exception):
    """Report malformed, unsupported, or inconsistent manifest data."""

    @classmethod
    def invalid(cls, detail: str) -> ManifestError:
        """Build a consistent invalid-manifest diagnostic."""
        return cls(f"invalid manifest: {detail}")


@dataclass(frozen=True, slots=True)
class ExternalChange:
    """One installer-owned external value and its restorable prior state."""

    surface: str
    key: str
    previous: str | None
    installed: str

    def __post_init__(self) -> None:
        """Require one fully identified string-valued external mutation."""
        if (
            not isinstance(self.surface, str)
            or not self.surface
            or not isinstance(self.key, str)
            or not self.key
            or (self.previous is not None and not isinstance(self.previous, str))
            or not isinstance(self.installed, str)
        ):
            detail = "external manifest change has invalid string fields"
            raise ManifestError(detail)


@dataclass(frozen=True, slots=True)
class ManifestIdentity:
    """Plan and source identity captured before installed bytes are committed."""

    package_version: str
    source_commit: str | None
    build_id: BuildId
    original_sha256: str
    profile: ProfileId | None
    patches: tuple[PatchId, ...]
    width: int
    height: int
    plan_digest: str
    backup_path: str

    def __post_init__(self) -> None:
        """Reject invalid installation identity before manifest creation."""
        _validate_plan_identity(self)


@dataclass(frozen=True, slots=True)
class PatchManifest:
    """Evidence and restore metadata for one current gk3hd installation."""

    schema: int
    package_version: str
    source_commit: str | None
    build_id: BuildId
    original_sha256: str
    profile: ProfileId | None
    patches: tuple[PatchId, ...]
    width: int
    height: int
    plan_digest: str
    installed_sha256: str
    backup_path: str
    backup_sha256: str
    backup_created: bool
    runtime_abi: int
    external_changes: tuple[ExternalChange, ...]
    applied_at_utc: str

    def __post_init__(self) -> None:
        """Make every current-manifest trust invariant explicit."""
        if self.schema != MANIFEST_SCHEMA:
            detail = f"manifest schema {self.schema!r} is unsupported"
            raise ManifestError(detail)
        _validate_plan_identity(self)
        _require_sha256(self.installed_sha256, field="installed_sha256")
        _require_sha256(self.backup_sha256, field="backup_sha256")
        if self.backup_sha256 != self.original_sha256:
            detail = "manifest backup hash does not match its original hash"
            raise ManifestError(detail)
        if type(self.backup_created) is not bool:
            detail = "manifest backup ownership must be boolean"
            raise ManifestError(detail)
        if self.runtime_abi != RUNTIME_ABI:
            detail = f"runtime ABI {self.runtime_abi!r} is unsupported"
            raise ManifestError(detail)
        if not isinstance(self.external_changes, tuple) or len(
            {(change.surface, change.key) for change in self.external_changes}
        ) != len(self.external_changes):
            detail = "manifest external changes must be a unique tuple"
            raise ManifestError(detail)
        _require_utc_timestamp(self.applied_at_utc)

    @classmethod
    def create(
        cls,
        *,
        identity: ManifestIdentity,
        installed_sha256: str,
        backup_created: bool = False,
        external_changes: tuple[ExternalChange, ...] = (),
    ) -> PatchManifest:
        """Create current-schema metadata with one canonical UTC timestamp."""
        return cls(
            schema=MANIFEST_SCHEMA,
            package_version=identity.package_version,
            source_commit=identity.source_commit,
            build_id=identity.build_id,
            original_sha256=identity.original_sha256,
            profile=identity.profile,
            patches=identity.patches,
            width=identity.width,
            height=identity.height,
            plan_digest=identity.plan_digest,
            installed_sha256=installed_sha256,
            backup_path=identity.backup_path,
            backup_sha256=identity.original_sha256,
            backup_created=backup_created,
            runtime_abi=RUNTIME_ABI,
            external_changes=external_changes,
            applied_at_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

    def to_json(self) -> str:
        """Serialize deterministically for atomic installation."""
        payload = asdict(self)
        payload["build_id"] = str(self.build_id)
        payload["profile"] = None if self.profile is None else str(self.profile)
        payload["patches"] = list(self.patches)
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_path(cls, path: Path) -> PatchManifest:
        """Read and validate exactly the current manifest schema."""
        try:
            value = path.read_text(encoding="utf-8")
        except OSError as exc:
            detail = f"cannot read manifest {path}: {exc}"
            raise ManifestError(detail) from exc
        return cls.from_json(value, source=str(path))

    @classmethod
    def from_json(cls, value: str, *, source: str = "manifest payload") -> PatchManifest:
        """Parse current-schema metadata from an in-memory JSON document."""
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            detail = f"cannot read manifest {source}: {exc}"
            raise ManifestError(detail) from exc
        if not isinstance(payload, dict):
            detail = f"manifest {source} is not a JSON object"
            raise ManifestError(detail)
        schema = payload.get("schema")
        if schema != MANIFEST_SCHEMA:
            detail = (
                f"manifest schema {schema!r} is an unsupported development layout; "
                "restore the verified backup and apply a current plan"
            )
            raise ManifestError(detail)
        try:
            external_payload = payload["external_changes"]
            patches_payload = payload["patches"]
            _require_json_lists(
                external_payload,
                patches_payload,
            )
            external = tuple(
                ExternalChange(
                    surface=item["surface"],
                    key=item["key"],
                    previous=item["previous"],
                    installed=item["installed"],
                )
                for item in external_payload
            )
            manifest = cls(
                schema=payload["schema"],
                package_version=payload["package_version"],
                source_commit=payload["source_commit"],
                build_id=BuildId(payload["build_id"]),
                original_sha256=payload["original_sha256"],
                profile=(None if payload["profile"] is None else ProfileId(payload["profile"])),
                patches=tuple(PatchId(value) for value in patches_payload),
                width=payload["width"],
                height=payload["height"],
                plan_digest=payload["plan_digest"],
                installed_sha256=payload["installed_sha256"],
                backup_path=payload["backup_path"],
                backup_sha256=payload["backup_sha256"],
                backup_created=payload["backup_created"],
                runtime_abi=payload["runtime_abi"],
                external_changes=external,
                applied_at_utc=payload["applied_at_utc"],
            )
        except (KeyError, TypeError, ValueError, ManifestError) as exc:
            detail = f"manifest {source} is missing or mis-types a required field"
            raise ManifestError(detail) from exc
        return manifest


def _validate_plan_identity(identity: ManifestIdentity | PatchManifest) -> None:
    """Validate fields shared by prepared and serialized identities."""
    if not isinstance(identity.package_version, str) or not identity.package_version:
        detail = "package version must be a nonempty string"
        raise ManifestError.invalid(detail)
    if identity.source_commit is not None and (
        not isinstance(identity.source_commit, str) or not identity.source_commit
    ):
        detail = "source commit must be null or a nonempty string"
        raise ManifestError.invalid(detail)
    if not isinstance(identity.build_id, str) or not identity.build_id:
        detail = "build ID must be a nonempty string"
        raise ManifestError.invalid(detail)
    if identity.profile is not None and (
        not isinstance(identity.profile, str) or not identity.profile
    ):
        detail = "profile must be null or a nonempty string"
        raise ManifestError.invalid(detail)
    if (
        not isinstance(identity.patches, tuple)
        or any(not isinstance(patch, str) or not patch for patch in identity.patches)
        or len(set(identity.patches)) != len(identity.patches)
    ):
        detail = "patches must be a unique tuple of nonempty IDs"
        raise ManifestError.invalid(detail)
    if (
        type(identity.width) is not int
        or type(identity.height) is not int
        or identity.width <= 0
        or identity.height <= 0
    ):
        detail = "display dimensions must be positive integers"
        raise ManifestError.invalid(detail)
    _require_sha256(identity.original_sha256, field="original_sha256")
    _require_sha256(identity.plan_digest, field="plan_digest")
    _require_backup_name(identity.backup_path)


def _require_json_lists(external: object, patches: object) -> None:
    """Reject JSON containers that iteration would otherwise coerce."""
    if not isinstance(external, list) or not isinstance(patches, list):
        detail = "patches and external changes must be arrays"
        raise ManifestError.invalid(detail)


def _require_sha256(value: str, *, field: str) -> None:
    """Require one canonical lowercase SHA-256 string."""
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        detail = f"{field} must be a lowercase SHA-256"
        raise ManifestError.invalid(detail)


def _require_backup_name(value: str) -> None:
    """Keep current backups adjacent to the executable they authenticate."""
    if not isinstance(value, str) or not value or value in {".", ".."}:
        detail = "backup path must be an adjacent file name"
        raise ManifestError.invalid(detail)

    path = Path(value)
    if path.is_absolute() or path.name != value:
        detail = "backup path must be an adjacent file name"
        raise ManifestError.invalid(detail)


def _require_utc_timestamp(value: str) -> None:
    """Require the canonical UTC timestamp emitted by manifest creation."""
    if not isinstance(value, str) or not value.endswith("Z"):
        detail = "application timestamp must be UTC"
        raise ManifestError.invalid(detail)
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        detail = "application timestamp is invalid"
        raise ManifestError.invalid(detail) from exc
    if parsed.tzinfo != UTC:
        detail = "application timestamp must be UTC"
        raise ManifestError.invalid(detail)


def manifest_path_for_exe(exe: Path) -> Path:
    """Return the patch component's state file beside the game executable."""
    return exe.with_name(STATE_FILENAME)
