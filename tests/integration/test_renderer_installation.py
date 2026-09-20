"""Opt-in real EXE and pinned renderer lifecycle, with isolated registry state."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest

from gk3hd.patch.install.configuration import GraphicsBackend
from gk3hd.patch.install.windows import WindowsInstallConfiguration
from gk3hd.patch.service import PatchRequest, PatchService
from gk3hd.renderer.distribution import config_bytes
from gk3hd.renderer.service import RendererService
from gk3hd.system.files import sha256_file


@pytest.mark.integration
@pytest.mark.acceptance
def test_default_renderer_install_and_restore_on_a_private_executable_copy(tmp_path: Path) -> None:
    source = os.environ.get("GK3_TEST_EXE")
    if not source or not Path(source).is_file():
        pytest.skip("set GK3_TEST_EXE to a supported original executable")
    exe = tmp_path / "GK3.exe"
    shutil.copyfile(source, exe)
    original_hash = sha256_file(exe)
    original_config = b"# existing user settings\r\n[Other.exe]\r\nd3d9.presentInterval = 1"
    (tmp_path / "dxvk.conf").write_bytes(original_config)
    registry: dict[str, str] = {}

    def write(name: str, value: str | None) -> None:
        if value is None:
            registry.pop(name, None)
        else:
            registry[name] = value

    backend = Mock()
    backend.read.side_effect = registry.get
    backend.write.side_effect = write
    configuration = WindowsInstallConfiguration(backend)
    service = PatchService(configuration=configuration, process_probe=lambda: False)
    renderer = RendererService(configuration=configuration, process_probe=lambda: False)
    renderer.install(exe=exe)
    installed = service.install(PatchRequest(exe=exe, resolution=(1280, 800)))
    assert installed.graphics_backend is GraphicsBackend.D7VK
    manifest = service.verify(exe=exe)
    assert "speed_up_surface_checks" in manifest.patches
    assert (tmp_path / "ddraw.dll").read_bytes().startswith(b"MZ")
    assert (tmp_path / "dxvk.conf").read_bytes() == config_bytes(
        executable_name=exe.name, previous=original_config
    )
    assert "16BITCOLOR" in registry[str(exe.resolve())]
    assert "speed_up_surface_checks" in service.verify(exe=exe).patches
    service.uninstall(exe=exe)
    renderer.uninstall(exe=exe)
    assert sha256_file(exe) == original_hash
    assert not (tmp_path / "ddraw.dll").exists()
    assert (tmp_path / "dxvk.conf").read_bytes() == original_config
    assert registry == {}
