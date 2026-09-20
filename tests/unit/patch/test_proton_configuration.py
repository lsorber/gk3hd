"""Hermetic contracts for per-prefix registry updates and renderer ownership."""

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from gk3hd.patch.install.proton import ProtonInstallConfiguration, ProtonRegistryBackend
from gk3hd.patch.install.windows import ConfigurationError
from gk3hd.patch.model import PatchId
from gk3hd.system.proton import ProtonContext


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("    Gamma    REG_SZ    1.000000\n", {"type": 1, "value": "1.000000"}),
        ("    Gamma    REG_DWORD    0xffffffff\n", {"type": 4, "value": 0xFFFFFFFF}),
    ],
)
def test_registry_reads_typed_values(text: str, expected: dict[str, object]) -> None:
    context = Mock(spec=ProtonContext)
    context.run.return_value = subprocess.CompletedProcess([], 0, text, "")
    backend = ProtonRegistryBackend(context, "Software\\Test")
    assert json.loads(backend.read("Gamma") or "null") == expected
    context.run.assert_called_once_with(("reg.exe", "query", "HKCU\\Software\\Test", "/v", "Gamma"))


def test_registry_distinguishes_absence_from_permission_failure() -> None:
    context = Mock(spec=ProtonContext)
    backend = ProtonRegistryBackend(context, "Software\\Test")
    context.run.return_value = subprocess.CompletedProcess(
        [], 1, "reg: Unable to find the specified registry key", ""
    )
    assert backend.read("Gamma") is None
    context.run.return_value = subprocess.CompletedProcess([], 1, "access denied", "")
    with pytest.raises(ConfigurationError, match="could not read"):
        backend.read("Gamma")


def test_proton_configuration_restores_only_its_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"fixture")
    values = {("other", "keep"): "unrelated"}
    monkeypatch.setattr(
        ProtonRegistryBackend, "read", lambda self, name: values.get((self.key_path, name))
    )

    def write(backend: ProtonRegistryBackend, name: str, value: str | None) -> None:
        if value is None:
            values.pop((backend.key_path, name), None)
        else:
            values[backend.key_path, name] = value

    monkeypatch.setattr(ProtonRegistryBackend, "write", write)
    configuration = ProtonInstallConfiguration(Mock(spec=ProtonContext))
    # A native transaction tests the shared registry lifecycle without a download.
    changes = configuration.prepare(
        exe=exe, width=1280, height=800, patches=(PatchId("maximize_graphics_quality"),)
    )
    assert len(changes) == 13
    assert not any("AppCompatFlags" in change.surface for change in changes)
    configuration.apply(exe=exe, changes=changes)
    configuration.verify(exe=exe, changes=changes)
    configuration.restore(exe=exe, changes=changes, force=False)
    assert values == {("other", "keep"): "unrelated"}
    d7vk = configuration.prepare_renderer(exe=exe, digest="a" * 64)
    override = next(change for change in d7vk if change.key == "ddraw")
    assert override.surface.endswith(r"Software\Wine\AppDefaults\GK3.exe\DllOverrides")
    assert json.loads(override.installed or "null")["value"] == "native,builtin"
