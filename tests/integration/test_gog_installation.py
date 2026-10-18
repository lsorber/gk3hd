"""Optional stock-GOG acceptance without distributing or running the executable."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from gk3hd.patch.builds import GOG_INSTALLER_BUILD
from gk3hd.patch.install.configuration import NoopConfiguration
from gk3hd.patch.install.transaction import Installer
from gk3hd.patch.manifest import manifest_path_for_exe
from gk3hd.patch.model import ProfileId


@pytest.mark.acceptance
def test_stock_gog_installs_verifies_and_restores_byte_exactly(tmp_path: Path) -> None:
    supplied = os.environ.get("GK3_TEST_GOG_EXE")
    if not supplied:
        pytest.skip("set GK3_TEST_GOG_EXE to a private stock GOG executable")
    original = Path(supplied).read_bytes()
    assert hashlib.sha256(original).hexdigest() == GOG_INSTALLER_BUILD.original_sha256
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(original)
    installer = Installer(configuration=NoopConfiguration(), process_probe=lambda: False)
    prepared = installer.prepare(
        exe=exe, profile=ProfileId("recommended"), patches=(), width=1280, height=800
    )
    assert prepared.profile == GOG_INSTALLER_BUILD
    assert exe.read_bytes() == original  # Preparation must not modify the original.
    manifest = installer.apply(exe=exe, prepared=prepared)
    assert manifest.original_sha256 == GOG_INSTALLER_BUILD.original_sha256
    assert prepared.backup.read_bytes() == original
    verified = installer.verify(exe=exe)
    assert verified.build_id == GOG_INSTALLER_BUILD.id
    assert verified.installed_sha256 == hashlib.sha256(exe.read_bytes()).hexdigest()
    installer.restore(exe=exe)
    assert exe.read_bytes() == original
    assert not manifest_path_for_exe(exe).exists()
