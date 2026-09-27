"""Uninstall preserves later type changes, but not unreadable registry failures."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from gk3hd.patch.install import windows
from gk3hd.patch.install.proton import ProtonInstallConfiguration
from gk3hd.patch.manifest import ExternalChange
from gk3hd.system.proton import ProtonContext


def _changes() -> tuple[ExternalChange, ...]:
    surface = "registry:HKCU\\" + windows.ENGINE_KEY
    return (
        ExternalChange(surface, "Game Width", '{"type":4,"value":1024}', '{"type":4,"value":1280}'),
        ExternalChange(surface, "Game Height", '{"type":4,"value":768}', '{"type":4,"value":800}'),
    )


@pytest.mark.parametrize("kind", ["REG_BINARY", "REG_MULTI_SZ", "REG_QWORD"])
def test_proton_uninstall_retains_unsupported_new_type(tmp_path: Path, kind: str) -> None:
    context = Mock(spec=ProtonContext)

    def run(args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if args[1] == "query":
            name = args[-1]
            value = f"{kind}  0001" if name == "Game Width" else "REG_DWORD  0x320"
            return subprocess.CompletedProcess(args, 0, f"    {name}    {value}\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    context.run.side_effect = run
    configuration = ProtonInstallConfiguration(context)
    configuration.restore(exe=tmp_path / "GK3.exe", changes=_changes(), force=False)
    writes = [call.args[0] for call in context.run.call_args_list if call.args[0][1] != "query"]
    assert writes == [
        (
            "reg.exe",
            "add",
            "HKCU\\" + windows.ENGINE_KEY,
            "/v",
            "Game Height",
            "/t",
            "REG_DWORD",
            "/d",
            "768",
            "/f",
        )
    ]


@pytest.mark.parametrize(
    "result",
    [
        subprocess.CompletedProcess([], 1, "access denied", ""),
        subprocess.CompletedProcess([], 0, "malformed registry output", ""),
    ],
)
def test_proton_uninstall_does_not_hide_read_failures(
    tmp_path: Path,
    result: subprocess.CompletedProcess[str],
) -> None:
    context = Mock(spec=ProtonContext)
    context.run.return_value = result
    with pytest.raises(windows.ConfigurationError):
        ProtonInstallConfiguration(context).restore(
            exe=tmp_path / "GK3.exe",
            changes=_changes(),
            force=False,
        )
    assert all(call.args[0][1] == "query" for call in context.run.call_args_list)


def test_windows_uninstall_retains_binary_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = MagicMock()
    registry.QueryValueEx.side_effect = lambda _key, name: (
        (b"\x00\x01", 3) if name == "Game Width" else (800, 4)
    )
    monkeypatch.setattr(windows, "winreg", registry, raising=False)
    configuration = windows.WindowsInstallConfiguration()
    configuration.restore(exe=tmp_path / "GK3.exe", changes=_changes(), force=False)
    registry.SetValueEx.assert_called_once_with(
        registry.CreateKey.return_value.__enter__.return_value,
        "Game Height",
        0,
        4,
        768,
    )
    registry.DeleteValue.assert_not_called()
    # Initial installation must still refuse a value it cannot back up faithfully.
    with pytest.raises(windows.UnsupportedRegistryValueError):
        configuration.registry.read("Game Width")
