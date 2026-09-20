"""Atomic rebuild-from-original installation, verification, and restore."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from gk3hd import __version__
from gk3hd.patch.binary.executor import OperationExecutor
from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.binary.normalize import normalize_source
from gk3hd.patch.builds import BuildProfile, profile_for_sha256
from gk3hd.patch.catalog import PLANNER
from gk3hd.patch.install.configuration import GraphicsBackend
from gk3hd.patch.install.journal import ApplyJournal, install_journal_path
from gk3hd.patch.install.platform import default_configuration
from gk3hd.patch.install.windows import is_gk3_running, local_graphics_proxy_dlls
from gk3hd.patch.manifest import ManifestIdentity, PatchManifest, manifest_path_for_exe
from gk3hd.patch.model import BuildContext, DisplayMode, PatchId, PatchPlan, ProfileId
from gk3hd.system.files import atomic_write
from gk3hd.system.locking import ExclusiveFileLock, executable_lock_path

if TYPE_CHECKING:
    from collections.abc import Callable

    from gk3hd.patch.install.configuration import InstallConfiguration


class InstallError(Exception):
    """Report a rejected, failed, or unverifiable installation transaction."""


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """Hashes and canonical identities proven by installed verification."""

    build_id: str
    profile: str | None
    patches: tuple[str, ...]
    original_sha256: str
    installed_sha256: str
    plan_digest: str


@dataclass(frozen=True, slots=True)
class PreparedInstall:
    """Fully built and verified in-memory output ready for disk commit."""

    target: Path
    target_sha256: str
    profile: BuildProfile
    plan: PatchPlan
    display_mode: DisplayMode
    plan_digest: str
    output: bytes
    installed_sha256: str
    backup: Path
    graphics_backend: GraphicsBackend


class Installer:
    """Own exact planning, backup policy, atomic commit, verify, and restore."""

    def __init__(
        self,
        *,
        configuration: InstallConfiguration | None = None,
        process_probe: Callable[[], bool] = is_gk3_running,
    ) -> None:
        """Use native Windows state management unless an adapter is injected."""
        self._configuration = configuration
        self._process_probe = process_probe

    def _configuration_for(self, exe: Path) -> InstallConfiguration:
        """Bind platform configuration only after the target is known."""
        return self._configuration or default_configuration(exe)

    def prepare(  # noqa: PLR0913 - the transaction binds every independent install input.
        self,
        *,
        exe: Path,
        profile: ProfileId | None,
        patches: tuple[PatchId, ...],
        width: int,
        height: int,
        graphics_backend: GraphicsBackend = GraphicsBackend.NATIVE,
    ) -> PreparedInstall:
        """Build and postcheck the complete output without changing disk state."""
        exe = exe.resolve()
        self._validate_target(exe)
        target_sha256 = _sha256(exe)
        backup = exe.with_suffix(f"{exe.suffix}.bak")
        source_path = backup if backup.is_file() else exe
        original_sha256 = _sha256(source_path)
        build_profile = profile_for_sha256(original_sha256)
        display_mode = DisplayMode(width=width, height=height)
        context = BuildContext(build_id=build_profile.id)
        plan = (
            PLANNER.plan_profile(profile, context)
            if profile is not None
            else PLANNER.plan_explicit(patches, context)
        )
        plan_digest = _plan_digest(plan)
        source = PEFile(normalize_source(source_path.read_bytes()))
        output_image = OperationExecutor().execute(source, plan.compile_operations())
        output = output_image.to_bytes()
        return PreparedInstall(
            target=exe,
            target_sha256=target_sha256,
            profile=build_profile,
            plan=plan,
            display_mode=display_mode,
            plan_digest=plan_digest,
            output=output,
            installed_sha256=_sha256_bytes(output),
            backup=backup,
            graphics_backend=graphics_backend,
        )

    def apply(self, *, exe: Path, prepared: PreparedInstall) -> PatchManifest:
        """Commit backup, executable, and manifest together or roll all back."""
        exe = exe.resolve()
        with ExclusiveFileLock(executable_lock_path(exe)):
            return self._apply_unlocked(exe=exe, prepared=prepared)

    def _apply_unlocked(self, *, exe: Path, prepared: PreparedInstall) -> PatchManifest:
        """Commit one prepared plan while owning the executable lock."""
        self._recover_unlocked(exe=exe)
        self._validate_target(exe)
        self._refuse_running_game()
        manifest_path = manifest_path_for_exe(exe)
        if manifest_path.exists():
            detail = "a current installation already exists; restore before applying a new plan"
            raise InstallError(detail)
        self._validate_prepared_commit(exe, prepared)

        original_exe = exe.read_bytes()
        backup_existed = prepared.backup.exists()
        external_changes = self._configuration_for(exe).prepare(
            exe=exe,
            width=prepared.display_mode.width,
            height=prepared.display_mode.height,
            patches=prepared.plan.patch_ids,
            graphics_backend=prepared.graphics_backend,
        )
        manifest = PatchManifest.create(
            identity=ManifestIdentity(
                package_version=__version__,
                source_commit=_source_commit(),
                build_id=prepared.profile.id,
                original_sha256=prepared.profile.original_sha256,
                profile=prepared.plan.profile,
                patches=prepared.plan.patch_ids,
                width=prepared.display_mode.width,
                height=prepared.display_mode.height,
                plan_digest=prepared.plan_digest,
                backup_path=prepared.backup.name,
            ),
            installed_sha256=prepared.installed_sha256,
            backup_created=not backup_existed,
            external_changes=external_changes,
        )
        journal = ApplyJournal.create(
            exe=exe,
            backup=prepared.backup,
            backup_existed=backup_existed,
            manifest=manifest,
        )
        try:
            # Publish rollback intent before the first owned mutation. The
            # journal recognizes both sides of every following atomic replace.
            journal.write()
            if not backup_existed:
                atomic_write(prepared.backup, original_exe)
            _validate_backup(prepared.backup, prepared.profile.original_sha256)
            atomic_write(exe, prepared.output)
            atomic_write(manifest_path, manifest.to_json().encode("utf-8"))
            self._configuration_for(exe).apply(exe=exe, changes=external_changes)
            self._verify_unlocked(exe=exe)
            # A killed process after this boundary must retain the verified
            # installation rather than undoing a completed commit.
            journal.committed().write()
            journal.path.unlink()
        except Exception as error:
            try:
                if journal.path.is_file():
                    self._recover_unlocked(exe=exe)
            # Preserve the primary operation error regardless of which
            # adapter or filesystem step blocks the best-effort rollback.
            except Exception as recovery_error:  # noqa: BLE001
                error.add_note(
                    "automatic installation rollback also failed; retain the journal "
                    f"for a later recovery attempt: {recovery_error}"
                )
            raise
        return manifest

    def recover(self, *, exe: Path) -> bool:
        """Finish or undo an interrupted production apply, when one exists."""
        exe = exe.resolve()
        with ExclusiveFileLock(executable_lock_path(exe)):
            return self._recover_unlocked(exe=exe)

    def _recover_unlocked(self, *, exe: Path) -> bool:
        """Recover strict journal states while owning the executable lock."""
        journal_path = install_journal_path(exe)
        if not journal_path.is_file():
            return False
        journal = ApplyJournal.from_path(exe=exe)
        manifest_path = manifest_path_for_exe(exe)
        intended_manifest = journal.manifest_json.encode("utf-8")

        if journal.phase == "committed":
            if not manifest_path.is_file() or manifest_path.read_bytes() != intended_manifest:
                detail = "verified installation journal no longer matches its manifest"
                raise InstallError(detail)
            self._verify_unlocked(exe=exe)
            journal_path.unlink()
            return True

        self._require_target(exe)
        current_sha256 = _sha256(exe)
        if current_sha256 not in {journal.original_sha256, journal.installed_sha256}:
            detail = (
                "executable changed outside the interrupted installation; "
                f"refusing to replace unrecognized hash {current_sha256}"
            )
            raise InstallError(detail)

        backup_exists = journal.backup.is_file()
        if backup_exists:
            _validate_backup(journal.backup, journal.original_sha256)
        elif journal.backup_existed or current_sha256 != journal.original_sha256:
            detail = f"interrupted installation backup is missing: {journal.backup}"
            raise InstallError(detail)

        if manifest_path.is_file() and manifest_path.read_bytes() != intended_manifest:
            detail = "manifest changed outside the interrupted installation; refusing recovery"
            raise InstallError(detail)

        # Validate every external value before changing any of them. The
        # adapter accepts only captured-prior or intended-installed states.
        self._configuration_for(exe).recover_interrupted_apply(
            exe=exe,
            changes=journal.manifest.external_changes,
        )
        if current_sha256 != journal.original_sha256:
            atomic_write(exe, journal.backup.read_bytes())
        _validate_restored_executable(exe, journal.original_sha256)
        manifest_path.unlink(missing_ok=True)
        if not journal.backup_existed:
            journal.backup.unlink(missing_ok=True)
        journal_path.unlink()
        return True

    def verify(self, *, exe: Path) -> VerificationReport:
        """Rebuild the declared plan from backup and compare all installed bytes."""
        exe = exe.resolve()
        with ExclusiveFileLock(executable_lock_path(exe)):
            self._recover_unlocked(exe=exe)
            return self._verify_unlocked(exe=exe)

    def _verify_unlocked(self, *, exe: Path) -> VerificationReport:
        """Verify one installation while owning the executable lock."""
        manifest_path = manifest_path_for_exe(exe)
        manifest = PatchManifest.from_path(manifest_path)
        self._validate_target(exe)
        backup = _resolve_backup(exe, manifest.backup_path)
        if not backup.is_file():
            detail = f"backup is missing: {backup}"
            raise InstallError(detail)
        backup_sha256 = _sha256(backup)
        if backup_sha256 != manifest.backup_sha256:
            detail = f"backup hash mismatch: expected {manifest.backup_sha256}, got {backup_sha256}"
            raise InstallError(detail)
        build_profile = profile_for_sha256(backup_sha256)
        context = BuildContext(build_id=build_profile.id)
        # Profiles are installation-time shortcuts and can grow in later
        # releases. Rebuild the recorded selection, retaining its original
        # profile label for identity checks, rather than silently adding patches.
        plan = replace(PLANNER.plan_explicit(manifest.patches, context), profile=manifest.profile)
        if plan.patch_ids != manifest.patches:
            detail = "manifest patch order does not match the current canonical plan"
            raise InstallError(detail)
        digest = _plan_digest(plan)
        if digest != manifest.plan_digest:
            detail = f"plan digest mismatch: expected {manifest.plan_digest}, got {digest}"
            raise InstallError(detail)
        rebuilt = OperationExecutor().execute(
            PEFile(normalize_source(backup.read_bytes())), plan.compile_operations()
        )
        expected = rebuilt.to_bytes()
        installed = exe.read_bytes()
        installed_sha256 = _sha256_bytes(installed)
        if expected != installed or installed_sha256 != manifest.installed_sha256:
            detail = "installed executable does not match the fully rebuilt verified plan"
            raise InstallError(detail)
        self._configuration_for(exe).verify(exe=exe, changes=manifest.external_changes)
        return VerificationReport(
            build_id=str(build_profile.id),
            profile=None if manifest.profile is None else str(manifest.profile),
            patches=tuple(str(value) for value in plan.patch_ids),
            original_sha256=backup_sha256,
            installed_sha256=installed_sha256,
            plan_digest=digest,
        )

    def restore(self, *, exe: Path, force: bool = False) -> Path:
        """Restore a hash-verified original using current installation evidence."""
        exe = exe.resolve()
        with ExclusiveFileLock(executable_lock_path(exe)):
            self._recover_unlocked(exe=exe)
            return self._restore_unlocked(exe=exe, force=force)

    def _restore_unlocked(self, *, exe: Path, force: bool) -> Path:
        """Restore one installation while owning the executable lock."""
        self._require_target(exe)
        self._refuse_running_game()
        manifest_path = manifest_path_for_exe(exe)
        metadata = PatchManifest.from_path(manifest_path)
        backup = _resolve_backup(exe, metadata.backup_path)
        if not backup.is_file():
            detail = f"backup is missing: {backup}"
            raise InstallError(detail)
        backup_sha256 = _sha256(backup)
        profile_for_sha256(backup_sha256)
        if backup_sha256 != metadata.original_sha256:
            detail = (
                f"backup hash mismatch: expected {metadata.original_sha256}, got {backup_sha256}"
            )
            raise InstallError(detail)
        current = exe.read_bytes()
        configuration_restored = False
        try:
            self._configuration_for(exe).restore(
                exe=exe,
                changes=metadata.external_changes,
                force=force,
            )
            configuration_restored = True
            atomic_write(exe, backup.read_bytes())
            _validate_restored_executable(exe, backup_sha256)
            manifest_path.unlink()
        except Exception:
            try:
                atomic_write(exe, current)
            finally:
                if configuration_restored:
                    self._configuration_for(exe).reinstall(
                        exe=exe, changes=metadata.external_changes
                    )
            raise
        if metadata.backup_created:
            try:
                backup.unlink()
            except OSError as exc:
                detail = f"restored successfully but could not remove owned backup: {backup}"
                raise InstallError(detail) from exc
        return backup

    @staticmethod
    def _require_target(exe: Path) -> None:
        if not exe.is_file():
            detail = f"executable does not exist: {exe}"
            raise InstallError(detail)

    @classmethod
    def _validate_target(cls, exe: Path) -> None:
        cls._require_target(exe)
        proxies = local_graphics_proxy_dlls(
            exe.parent,
            allow_owned_d7vk=True,
        )
        if proxies:
            detail = f"local graphics proxy DLLs are unsupported: {', '.join(proxies)}"
            raise InstallError(detail)

    @staticmethod
    def _validate_prepared_commit(exe: Path, prepared: PreparedInstall) -> None:
        """Bind one mutation to the exact pristine target observed by prepare."""
        if prepared.target != exe:
            detail = f"prepared plan belongs to {prepared.target}, not {exe}"
            raise InstallError(detail)
        expected_backup = exe.with_suffix(f"{exe.suffix}.bak")
        if prepared.backup.resolve() != expected_backup.resolve():
            detail = f"prepared backup is not adjacent to its target: {prepared.backup}"
            raise InstallError(detail)
        output_sha256 = _sha256_bytes(prepared.output)
        if output_sha256 != prepared.installed_sha256:
            detail = (
                "prepared output hash mismatch: "
                f"expected {prepared.installed_sha256}, got {output_sha256}"
            )
            raise InstallError(detail)
        current_sha256 = _sha256(exe)
        if current_sha256 != prepared.target_sha256:
            detail = (
                "target changed after plan preparation: "
                f"expected {prepared.target_sha256}, got {current_sha256}"
            )
            raise InstallError(detail)
        if current_sha256 != prepared.profile.original_sha256:
            detail = (
                "target is not the supported pristine executable; restore the verified "
                "backup before applying"
            )
            raise InstallError(detail)

    def _refuse_running_game(self) -> None:
        if self._process_probe():
            detail = "GK3.exe is running; exit the game before changing its installation"
            raise InstallError(detail)


def _resolve_backup(exe: Path, stored: str) -> Path:
    backup = Path(stored)
    return backup if backup.is_absolute() else exe.with_name(backup.name)


def _validate_backup(backup: Path, expected_sha256: str) -> None:
    if _sha256(backup) != expected_sha256:
        detail = f"backup {backup} does not match the supported original"
        raise InstallError(detail)


def _validate_restored_executable(exe: Path, expected_sha256: str) -> None:
    if _sha256(exe) != expected_sha256:
        detail = "restored executable failed its original hash check"
        raise InstallError(detail)


def _plan_digest(plan: PatchPlan) -> str:
    """Identify executable mutations independently of external display state."""
    payload = {
        "build": str(plan.build.build_id),
        "patches": list(plan.patch_ids),
        "profile": None if plan.profile is None else str(plan.profile),
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _source_commit() -> str | None:
    """Read the checkout commit without spawning Git, when metadata is present."""
    repository = Path(__file__).resolve().parents[3]
    git_dir = repository / ".git"
    head = git_dir / "HEAD"
    if not head.is_file():
        return None
    value = head.read_text(encoding="ascii").strip()
    if not value.startswith("ref: "):
        return value or None
    reference = value.removeprefix("ref: ")
    loose = git_dir / reference
    if loose.is_file():
        return loose.read_text(encoding="ascii").strip() or None
    packed = git_dir / "packed-refs"
    if not packed.is_file():
        return None
    suffix = f" {reference}"
    for line in packed.read_text(encoding="ascii").splitlines():
        if line.endswith(suffix):
            return line.split(" ", maxsplit=1)[0]
    return None
