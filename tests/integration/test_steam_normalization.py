"""Optional private-binary acceptance for stock Steam normalization."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.binary.normalize import normalize_source
from gk3hd.patch.builds import PROTECTED_STEAM_SHA256, STEAM_NORMALIZED_BUILD
from gk3hd.patch.install.configuration import NoopConfiguration
from gk3hd.patch.install.transaction import Installer
from gk3hd.patch.model import ProfileId


def test_normalization_does_not_guess_from_untrusted_container_markers() -> None:
    payload = b"MZ" + bytes(62) + b"VLV\0.bind"
    assert normalize_source(payload) == payload


@pytest.mark.acceptance
def test_stock_steam_installs_verifies_and_restores_byte_exactly(tmp_path: Path) -> None:
    supplied = os.environ.get("GK3_TEST_STEAM_EXE")
    if not supplied:
        pytest.skip("set GK3_TEST_STEAM_EXE to a private stock Steam executable")
    original = Path(supplied).read_bytes()
    assert hashlib.sha256(original).hexdigest() == PROTECTED_STEAM_SHA256
    normalized = PEFile(normalize_source(original))
    assert hashlib.sha256(normalized.data).hexdigest() == STEAM_NORMALIZED_BUILD.original_sha256
    assert normalized.get_section(".bind") is None
    assert normalized.address_of_entry_point == 0x1C4B8B
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(original)
    installer = Installer(configuration=NoopConfiguration(), process_probe=lambda: False)
    prepared = installer.prepare(
        exe=exe, profile=ProfileId("recommended"), patches=(), width=1280, height=800
    )
    assert prepared.profile.id == "steam"
    manifest = installer.apply(exe=exe, prepared=prepared)
    assert manifest.original_sha256 == PROTECTED_STEAM_SHA256
    assert prepared.backup.read_bytes() == original
    verified = installer.verify(exe=exe)
    assert verified.build_id == "steam"
    assert verified.installed_sha256 == hashlib.sha256(exe.read_bytes()).hexdigest()
    installer.restore(exe=exe)
    assert exe.read_bytes() == original
