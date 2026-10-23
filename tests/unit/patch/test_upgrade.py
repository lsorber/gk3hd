"""Updates preserve the original backup and recover the previous working version."""

from dataclasses import replace
from pathlib import Path

import pytest

from gk3hd.patch.install.configuration import NoopConfiguration
from gk3hd.patch.install.transaction import InstallError
from gk3hd.patch.install.windows import WindowsInstallConfiguration
from gk3hd.patch.manifest import PatchManifest, manifest_path_for_exe
from gk3hd.system.files import sha256_file
from tests.unit.patch.test_install_transaction import (
    FailingVerificationInstaller,
    InterruptedConfiguration,
    PassingVerificationInstaller,
    _prepared,
)
from tests.unit.patch.test_windows_install_configuration import MemoryRegistry


def test_update_rebuilds_from_original_and_uninstall_restores_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"pristine")
    installer = PassingVerificationInstaller(
        configuration=NoopConfiguration(), process_probe=lambda: False
    )
    original = _prepared(exe, b"pristine", b"first version")
    first = installer.apply(exe=exe, prepared=original)
    second = replace(original, target_sha256=sha256_file(exe), output=b"second version")
    from hashlib import sha256  # noqa: PLC0415 - fixture identity.

    second = replace(second, installed_sha256=sha256(second.output).hexdigest())
    latest = installer.apply(exe=exe, prepared=second)
    assert exe.read_bytes() == b"second version"
    assert second.backup.read_bytes() == b"pristine"
    assert latest.backup_created == first.backup_created
    assert (
        installer.apply(exe=exe, prepared=replace(second, target_sha256=sha256_file(exe))) == latest
    )
    monkeypatch.setattr(
        "gk3hd.patch.install.transaction.profile_for_sha256", lambda _hash: original.profile
    )
    installer.restore(exe=exe)
    assert exe.read_bytes() == b"pristine"
    assert not second.backup.exists()
    assert not manifest_path_for_exe(exe).exists()


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_failed_or_interrupted_update_restores_prior_version(
    tmp_path: Path, failure: type[BaseException]
) -> None:
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"pristine")
    installer = PassingVerificationInstaller(
        configuration=NoopConfiguration(), process_probe=lambda: False
    )
    first_plan = _prepared(exe, b"pristine", b"first version")
    installer.apply(exe=exe, prepared=first_plan)
    manifest = manifest_path_for_exe(exe).read_bytes()
    next_plan = replace(
        _prepared(exe, b"pristine", b"next version"), target_sha256=sha256_file(exe)
    )
    failed = FailingVerificationInstaller(
        configuration=NoopConfiguration(), process_probe=lambda: False
    )
    if failure is KeyboardInterrupt:
        failed = PassingVerificationInstaller(
            configuration=InterruptedConfiguration(), process_probe=lambda: False
        )
    with pytest.raises(failure):
        failed.apply(exe=exe, prepared=next_plan)
    if failure is KeyboardInterrupt:
        failed.recover(exe=exe)
    assert exe.read_bytes() == b"first version"
    assert manifest_path_for_exe(exe).read_bytes() == manifest
    assert first_plan.backup.read_bytes() == b"pristine"


def test_update_does_not_overwrite_unrecognized_executable(tmp_path: Path) -> None:
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"pristine")
    installer = PassingVerificationInstaller(
        configuration=NoopConfiguration(), process_probe=lambda: False
    )
    first_plan = _prepared(exe, b"pristine", b"first version")
    installer.apply(exe=exe, prepared=first_plan)
    exe.write_bytes(b"another modification")
    next_plan = replace(
        _prepared(exe, b"pristine", b"next version"), target_sha256=sha256_file(exe)
    )
    with pytest.raises(InstallError, match="unrecognized bytes"):
        installer.apply(exe=exe, prepared=next_plan)
    assert exe.read_bytes() == b"another modification"
    assert next_plan.backup.read_bytes() == b"pristine"


def test_updates_keep_later_registry_edits_and_deletions_even_after_uninstall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"pristine")
    registry = MemoryRegistry()
    installer = PassingVerificationInstaller(
        configuration=WindowsInstallConfiguration(registry), process_probe=lambda: False
    )
    first_plan = _prepared(exe, b"pristine", b"first version")
    installer.apply(exe=exe, prepared=first_plan)
    registry.values["Game Width"] = '{"type":4,"value":1280}'
    del registry.values["Game Height"]
    second = replace(_prepared(exe, b"pristine", b"second version"), target_sha256=sha256_file(exe))
    installer.apply(exe=exe, prepared=second)
    installer.apply(exe=exe, prepared=replace(second, target_sha256=sha256_file(exe)))
    assert registry.values["Game Width"] == '{"type":4,"value":1280}'
    assert "Game Height" not in registry.values
    manifest = PatchManifest.from_path(manifest_path_for_exe(exe))
    assert manifest.backup_created
    monkeypatch.setattr(
        "gk3hd.patch.install.transaction.profile_for_sha256", lambda _hash: first_plan.profile
    )
    installer.restore(exe=exe)
    assert registry.values == {"Game Width": '{"type":4,"value":1280}'}
