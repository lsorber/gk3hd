"""Optional exact-binary acceptance for the reversible Steam menu bypass."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.install.launcher import LAUNCHER_NAME, prepare_launcher
from gk3hd.patch.install.windows import WindowsInstallConfiguration


@pytest.mark.acceptance
def test_stock_launcher_entrypoint_and_transaction(tmp_path: Path) -> None:
    supplied = os.environ.get("GK3_TEST_LAUNCHER_EXE")
    if not supplied:
        pytest.skip("set GK3_TEST_LAUNCHER_EXE to a private stock Sierra launcher")
    original = Path(supplied).read_bytes()
    game = tmp_path / "Gämé Ω"
    game.mkdir()
    exe = game / "GK3.exe"
    exe.write_bytes(b"game placeholder; this test does not start it")
    path = tmp_path / LAUNCHER_NAME
    path.write_bytes(original)
    (tmp_path / "SierraLauncher.ini").write_text(
        "[Launcher]\nNumButtons=1\nGame1Prog=other\nGame1Path=Gämé Ω\n"
        "Game1Exe=GK3.exe\nGame1Cmd=\n",
        encoding="utf-8-sig",
    )
    change = prepare_launcher(exe)
    assert change is not None
    configuration = WindowsInstallConfiguration()
    configuration.apply(exe=exe, changes=(change,))
    configuration.verify(exe=exe, changes=(change,))
    patched = PEFile(path.read_bytes())
    section = patched.get_section(".gkstart")
    assert section is not None
    assert section.characteristics == 0x60000020  # Code is readable/executable, not writable.
    assert patched.address_of_entry_point == section.virtual_address
    # Original code, resources and imports are retained byte for byte.
    for original_section in PEFile(original).sections:
        start = original_section.pointer_to_raw_data
        end = start + original_section.size_of_raw_data
        assert patched.data[start:end] == original[start:end]
    configuration.restore(exe=exe, changes=(change,), force=False)
    assert path.read_bytes() == original
