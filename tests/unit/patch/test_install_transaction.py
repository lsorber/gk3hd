"""Hermetic fault-injection tests for the installer commit boundary."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest

from gk3hd.patch.builds import BuildProfile
from gk3hd.patch.install import transaction
from gk3hd.patch.install.configuration import GraphicsBackend
from gk3hd.patch.install.journal import ApplyJournal, install_journal_path
from gk3hd.patch.install.transaction import (
    Installer,
    InstallError,
    PreparedInstall,
    VerificationReport,
)
from gk3hd.patch.install.windows import WindowsInstallConfiguration
from gk3hd.patch.manifest import ExternalChange, manifest_path_for_exe
from gk3hd.patch.model import BuildContext, BuildId, DisplayMode, PatchId, PatchPlan
from gk3hd.system.locking import ExclusiveFileLock, LockError, executable_lock_path
from tests.unit.patch.test_windows_install_configuration import MemoryRegistry

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(slots=True)
class TransactionConfiguration:
    """Expose one external value whose rollback is directly observable."""

    value: str = "before"
    rollback_count: int = 0

    def prepare(
        self,
        *,
        exe: Path,
        width: int,
        height: int,
        patches: tuple[PatchId, ...],
        graphics_backend: GraphicsBackend = GraphicsBackend.NATIVE,
    ) -> tuple[ExternalChange, ...]:
        del exe, width, height, patches, graphics_backend
        return (ExternalChange("test", "setting", "before", "after"),)

    def apply(self, *, exe: Path, changes: tuple[ExternalChange, ...]) -> None:
        del exe, changes
        self.value = "after"

    def verify(self, *, exe: Path, changes: tuple[ExternalChange, ...]) -> None:
        del exe, changes

    def rollback(self, *, exe: Path, changes: tuple[ExternalChange, ...]) -> None:
        del exe, changes
        self.value = "before"
        self.rollback_count += 1

    def recover_interrupted_apply(
        self,
        *,
        exe: Path,
        changes: tuple[ExternalChange, ...],
    ) -> None:
        del exe, changes
        self.value = "before"
        self.rollback_count += 1

    def prepare_restore(
        self, *, exe: Path, changes: tuple[ExternalChange, ...], force: bool = False
    ) -> tuple[ExternalChange, ...]:
        del exe, force
        return changes

    def restore(
        self,
        *,
        exe: Path,
        changes: tuple[ExternalChange, ...],
        force: bool,
    ) -> None:
        del exe, changes, force

    def reinstall(self, *, exe: Path, changes: tuple[ExternalChange, ...]) -> None:
        del exe, changes


class FailingVerificationInstaller(Installer):
    """Inject a failure after every disk and configuration write has succeeded."""

    def _verify_unlocked(self, *, exe: Path) -> VerificationReport:
        del exe
        msg = "injected installed-verification failure"
        raise RuntimeError(msg)


class PassingVerificationInstaller(Installer):
    """Isolate journal boundary tests from commercial executable fixtures."""

    def _verify_unlocked(self, *, exe: Path) -> VerificationReport:
        return VerificationReport(
            build_id="synthetic",
            profile=None,
            patches=(),
            original_sha256="0" * 64,
            installed_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
            plan_digest="d" * 64,
        )


class InterruptedConfiguration(TransactionConfiguration):
    """Simulate process termination after external state was written."""

    def apply(self, *, exe: Path, changes: tuple[ExternalChange, ...]) -> None:
        del exe, changes
        self.value = "after"
        raise KeyboardInterrupt


def _prepared(exe: Path, original: bytes, output: bytes) -> PreparedInstall:
    original_sha256 = hashlib.sha256(original).hexdigest()
    build_id = BuildId("synthetic")
    build = BuildContext(build_id=build_id)
    return PreparedInstall(
        target=exe.resolve(),
        target_sha256=original_sha256,
        profile=BuildProfile(
            id=build_id,
            label="Synthetic installer fixture",
            original_sha256=original_sha256,
            sites=MappingProxyType({}),
            symbols=MappingProxyType({}),
        ),
        plan=PatchPlan(build=build, profile=None, definitions=()),
        display_mode=DisplayMode(width=1920, height=1080),
        plan_digest="d" * 64,
        output=output,
        installed_sha256=hashlib.sha256(output).hexdigest(),
        backup=exe.with_suffix(f"{exe.suffix}.bak"),
        graphics_backend=GraphicsBackend.NATIVE,
    )


def test_apply_rolls_back_every_surface_when_installed_verification_fails(
    tmp_path: Path,
) -> None:
    """No executable, manifest, backup, or external partial state survives failure."""
    exe = tmp_path / "GK3.exe"
    original = b"synthetic pristine executable"
    exe.write_bytes(original)
    configuration = TransactionConfiguration()
    installer = FailingVerificationInstaller(
        configuration=configuration,
        process_probe=lambda: False,
    )

    with pytest.raises(RuntimeError, match="installed-verification failure"):
        installer.apply(
            exe=exe,
            prepared=_prepared(exe, original, b"synthetic patched executable"),
        )

    assert exe.read_bytes() == original
    assert not manifest_path_for_exe(exe).exists()
    assert not exe.with_suffix(f"{exe.suffix}.bak").exists()
    assert configuration.value == "before"
    assert configuration.rollback_count == 1


def test_failed_uninstall_preserves_newer_registry_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rollback reapplies only removed values, never the retained user edit."""
    exe = tmp_path / "GK3.exe"
    original, patched = b"pristine fixture", b"patched fixture"
    exe.write_bytes(original)
    registry = MemoryRegistry()
    configuration = WindowsInstallConfiguration(registry)
    installer = PassingVerificationInstaller(
        configuration=configuration, process_probe=lambda: False
    )
    prepared = _prepared(exe, original, patched)
    installer.apply(exe=exe, prepared=prepared)
    registry.values["Game Width"] = '{"type":4,"value":1280}'
    expected = dict(registry.values)
    monkeypatch.setattr(transaction, "profile_for_sha256", lambda _digest: prepared.profile)
    path_type = type(exe)
    unlink = path_type.unlink

    def fail_cleanup(path: Path, *, missing_ok: bool = False) -> None:
        if path == manifest_path_for_exe(exe):
            msg = "injected uninstall failure"
            raise OSError(msg)
        unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(path_type, "unlink", fail_cleanup)
    with pytest.raises(OSError, match="injected uninstall failure"):
        installer.restore(exe=exe)
    assert registry.values == expected
    assert exe.read_bytes() == patched
    assert manifest_path_for_exe(exe).is_file()
    monkeypatch.setattr(path_type, "unlink", unlink)
    installer.restore(exe=exe)
    assert exe.read_bytes() == original
    assert registry.values == {"Game Width": expected["Game Width"]}


def test_apply_refuses_a_plan_prepared_for_another_target(tmp_path: Path) -> None:
    original = b"synthetic pristine executable"
    source = tmp_path / "source" / "GK3.exe"
    target = tmp_path / "target" / "GK3.exe"
    source.parent.mkdir()
    target.parent.mkdir()
    source.write_bytes(original)
    target.write_bytes(original)
    installer = Installer(
        configuration=TransactionConfiguration(),
        process_probe=lambda: False,
    )

    with pytest.raises(InstallError, match="belongs to"):
        installer.apply(
            exe=target,
            prepared=_prepared(source, original, b"synthetic patched executable"),
        )

    assert target.read_bytes() == original
    assert not target.with_suffix(".exe.bak").exists()


def test_apply_refuses_target_changed_after_preparation(tmp_path: Path) -> None:
    exe = tmp_path / "GK3.exe"
    original = b"synthetic pristine executable"
    exe.write_bytes(original)
    prepared = _prepared(exe, original, b"synthetic patched executable")
    exe.write_bytes(b"external edit after preparation")
    installer = Installer(
        configuration=TransactionConfiguration(),
        process_probe=lambda: False,
    )

    with pytest.raises(InstallError, match="changed after plan preparation"):
        installer.apply(exe=exe, prepared=prepared)

    assert exe.read_bytes() == b"external edit after preparation"
    assert not exe.with_suffix(".exe.bak").exists()


def test_apply_refuses_ambiguous_nonpristine_target_even_with_valid_backup(
    tmp_path: Path,
) -> None:
    exe = tmp_path / "GK3.exe"
    original = b"synthetic pristine executable"
    orphan = b"orphaned patched executable without truthful metadata"
    exe.write_bytes(orphan)
    exe.with_suffix(".exe.bak").write_bytes(original)
    prepared = replace(
        _prepared(exe, original, b"synthetic patched executable"),
        target_sha256=hashlib.sha256(orphan).hexdigest(),
    )
    installer = Installer(
        configuration=TransactionConfiguration(),
        process_probe=lambda: False,
    )

    with pytest.raises(InstallError, match="not the supported pristine executable"):
        installer.apply(exe=exe, prepared=prepared)

    assert exe.read_bytes() == orphan
    assert exe.with_suffix(".exe.bak").read_bytes() == original


def test_apply_refuses_prepared_output_with_inconsistent_hash(tmp_path: Path) -> None:
    exe = tmp_path / "GK3.exe"
    original = b"synthetic pristine executable"
    exe.write_bytes(original)
    prepared = replace(
        _prepared(exe, original, b"synthetic patched executable"),
        installed_sha256="0" * 64,
    )
    installer = Installer(
        configuration=TransactionConfiguration(),
        process_probe=lambda: False,
    )

    with pytest.raises(InstallError, match="prepared output hash mismatch"):
        installer.apply(exe=exe, prepared=prepared)

    assert exe.read_bytes() == original
    assert not exe.with_suffix(".exe.bak").exists()


def test_apply_refuses_a_target_owned_by_another_transaction(tmp_path: Path) -> None:
    """Production commits share ownership with validation executable swaps."""
    exe = tmp_path / "GK3.exe"
    original = b"synthetic pristine executable"
    exe.write_bytes(original)
    installer = Installer(
        configuration=TransactionConfiguration(),
        process_probe=lambda: False,
    )

    with (
        ExclusiveFileLock(executable_lock_path(exe)),
        pytest.raises(LockError, match="another gk3hd transaction"),
    ):
        installer.apply(
            exe=exe,
            prepared=_prepared(exe, original, b"synthetic patched executable"),
        )

    assert exe.read_bytes() == original
    assert not exe.with_suffix(".exe.bak").exists()


def test_recover_undoes_an_apply_interrupted_after_every_owned_write(tmp_path: Path) -> None:
    """A killed process leaves enough durable evidence for exact recovery."""
    exe = tmp_path / "GK3.exe"
    original = b"synthetic pristine executable"
    output = b"synthetic patched executable"
    exe.write_bytes(original)
    configuration = InterruptedConfiguration()
    installer = Installer(configuration=configuration, process_probe=lambda: False)

    with pytest.raises(KeyboardInterrupt):
        installer.apply(exe=exe, prepared=_prepared(exe, original, output))

    assert exe.read_bytes() == output
    assert manifest_path_for_exe(exe).is_file()
    assert exe.with_suffix(".exe.bak").is_file()
    assert install_journal_path(exe).is_file()
    assert configuration.value == "after"

    assert installer.recover(exe=exe)
    assert exe.read_bytes() == original
    assert not manifest_path_for_exe(exe).exists()
    assert not exe.with_suffix(".exe.bak").exists()
    assert not install_journal_path(exe).exists()
    assert configuration.value == "before"


def test_recover_refuses_unrecognized_executable_and_retains_evidence(tmp_path: Path) -> None:
    """Recovery never overwrites a later executable edit just to clean up."""
    exe = tmp_path / "GK3.exe"
    original = b"synthetic pristine executable"
    exe.write_bytes(original)
    installer = Installer(
        configuration=InterruptedConfiguration(),
        process_probe=lambda: False,
    )
    with pytest.raises(KeyboardInterrupt):
        installer.apply(
            exe=exe,
            prepared=_prepared(exe, original, b"synthetic patched executable"),
        )
    exe.write_bytes(b"unrelated later edit")

    with pytest.raises(InstallError, match="changed outside"):
        installer.recover(exe=exe)

    assert exe.read_bytes() == b"unrelated later edit"
    assert install_journal_path(exe).is_file()
    assert manifest_path_for_exe(exe).is_file()


def test_recover_finalizes_a_verified_commit_with_interrupted_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The committed boundary keeps a verified install instead of undoing it."""
    exe = tmp_path / "GK3.exe"
    original = b"synthetic pristine executable"
    output = b"synthetic patched executable"
    exe.write_bytes(original)
    installer = PassingVerificationInstaller(
        configuration=TransactionConfiguration(),
        process_probe=lambda: False,
    )
    journal_path = install_journal_path(exe)
    path_type = type(exe)
    original_unlink = path_type.unlink

    def interrupt_journal_cleanup(path: Path, *, missing_ok: bool = False) -> None:
        if path.resolve() == journal_path:
            msg = "injected committed-journal cleanup interruption"
            raise OSError(msg)
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(path_type, "unlink", interrupt_journal_cleanup)
    with pytest.raises(OSError, match="cleanup interruption"):
        installer.apply(exe=exe, prepared=_prepared(exe, original, output))
    monkeypatch.undo()

    assert ApplyJournal.from_path(exe=exe).phase == "committed"
    assert exe.read_bytes() == output
    assert manifest_path_for_exe(exe).is_file()
    assert installer.recover(exe=exe)
    assert not journal_path.exists()
    assert exe.read_bytes() == output
    assert manifest_path_for_exe(exe).is_file()
