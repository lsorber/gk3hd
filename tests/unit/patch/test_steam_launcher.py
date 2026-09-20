"""Portable launcher ownership and transaction tests; no commercial binary required."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from gk3hd.patch.definitions.skip_steam_launcher import API_NAMES, _entrypoint, build_launcher
from gk3hd.patch.install import launcher
from gk3hd.patch.install.windows import ConfigurationError, WindowsInstallConfiguration

if TYPE_CHECKING:
    from pathlib import Path

    from gk3hd.patch.manifest import ExternalChange

_INI = "[Launcher]\nNumButtons=1\nGame1Prog=other\nGame1Path=gk3\nGame1Exe=GK3.exe\nGame1Cmd=\n"
_ORIGINAL = b"synthetic stock launcher"


def _layout(tmp_path: Path, ini: str = _INI) -> Path:
    game = tmp_path / "GK3"
    game.mkdir()
    exe = game / "GK3.exe"
    exe.write_bytes(b"game executable")
    (tmp_path / launcher.LAUNCHER_NAME).write_bytes(_ORIGINAL)
    (tmp_path / "SierraLauncher.ini").write_text(ini, encoding="utf-8")
    return exe


def _fake_build(payload: bytes, *, game_directory: str, exe_name: str) -> bytes:
    if payload != _ORIGINAL:
        message = "unsupported synthetic launcher"
        raise ValueError(message)
    return payload + (game_directory + "/" + exe_name).encode()


@pytest.fixture
def owned_launcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, ExternalChange]:
    monkeypatch.setattr(launcher, "build_launcher", _fake_build)
    exe = _layout(tmp_path)
    change = launcher.prepare_launcher(exe)
    assert change is not None
    return exe, change


def test_preparation_is_read_only_and_transaction_restores_exact_original(
    owned_launcher: tuple[Path, ExternalChange],
) -> None:
    exe, change = owned_launcher
    path = launcher.launcher_path(exe, change.key)
    assert path.read_bytes() == _ORIGINAL
    configuration = WindowsInstallConfiguration()
    configuration.apply(exe=exe, changes=(change,))
    configuration.verify(exe=exe, changes=(change,))
    assert path.read_bytes() == launcher.decode_launcher(change.installed)
    configuration.restore(exe=exe, changes=(change,), force=False)
    assert path.read_bytes() == _ORIGINAL
    assert exe.read_bytes() == b"game executable"


def test_post_install_launcher_edits_are_preserved_unless_force_is_explicit(
    owned_launcher: tuple[Path, ExternalChange],
) -> None:
    exe, change = owned_launcher
    path = launcher.launcher_path(exe, change.key)
    configuration = WindowsInstallConfiguration()
    configuration.apply(exe=exe, changes=(change,))
    path.write_bytes(b"user edit")
    with pytest.raises(ConfigurationError, match="no longer matches"):
        configuration.restore(exe=exe, changes=(change,), force=False)
    assert path.read_bytes() == b"user edit"
    configuration.restore(exe=exe, changes=(change,), force=True)
    assert path.read_bytes() == _ORIGINAL


def test_interrupted_launcher_write_is_recovered(
    owned_launcher: tuple[Path, ExternalChange],
) -> None:
    exe, change = owned_launcher
    configuration = WindowsInstallConfiguration()
    configuration.apply(exe=exe, changes=(change,))
    configuration.recover_interrupted_apply(exe=exe, changes=(change,))
    assert launcher.launcher_path(exe, change.key).read_bytes() == _ORIGINAL


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("NumButtons", "2"),
        ("Game1Path", "another-game"),
        ("Game1Exe", "another.exe"),
        ("Game1Prog", "dosbox"),
        ("Game1Cmd", "--custom-argument"),
    ],
)
def test_unrelated_or_custom_launchers_are_not_modified(
    tmp_path: Path, key: str, value: str
) -> None:
    original_line = next(line for line in _INI.splitlines() if line.startswith(key + "="))
    exe = _layout(tmp_path, _INI.replace(original_line, key + "=" + value))
    assert launcher.prepare_launcher(exe) is None
    assert (tmp_path / launcher.LAUNCHER_NAME).read_bytes() == _ORIGINAL


def test_discovery_matches_case_insensitively(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exe = _layout(tmp_path)
    path = tmp_path / launcher.LAUNCHER_NAME
    path.rename(tmp_path / "sierralauncher.exe")
    monkeypatch.setattr(launcher, "build_launcher", _fake_build)
    change = launcher.prepare_launcher(exe)
    assert change is not None
    assert change.key == "sierralauncher.exe"


@pytest.mark.parametrize("key", ["../SierraLauncher.exe", "GK3.exe", "sub/SierraLauncher.exe"])
def test_manifest_cannot_redirect_the_binary_write(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError, match="unsupported Steam launcher filename"):
        launcher.launcher_path(tmp_path / "GK3" / "GK3.exe", key)


def test_directory_cannot_be_replaced_with_a_launcher(tmp_path: Path) -> None:
    (tmp_path / launcher.LAUNCHER_NAME).mkdir()
    with pytest.raises(ValueError, match="non-file"):
        launcher.launcher_path(tmp_path / "GK3" / "GK3.exe", launcher.LAUNCHER_NAME)


@pytest.mark.parametrize("field", ["previous", "installed"])
def test_manifest_cannot_supply_arbitrary_executable_bytes(
    owned_launcher: tuple[Path, ExternalChange],
    field: str,
) -> None:
    exe, change = owned_launcher
    tampered = replace(change, **{field: launcher.encode_launcher(b"arbitrary code")})
    with pytest.raises(ValueError, match=r"unsupported synthetic|verified handoff"):
        WindowsInstallConfiguration().restore(exe=exe, changes=(tampered,), force=True)
    assert launcher.launcher_path(exe, change.key).read_bytes() == _ORIGINAL


@pytest.mark.parametrize("value", ["untagged", "base64:!not-base64!"])
def test_binary_metadata_must_be_explicit_and_valid(value: str) -> None:
    with pytest.raises(ValueError, match=r"invalid encoded|Only base64"):
        launcher.decode_launcher(value)


def test_builder_requires_exact_supported_original() -> None:
    with pytest.raises(ValueError, match="unsupported Sierra launcher executable"):
        build_launcher(b"MZ" + bytes(4096), game_directory="GK3", exe_name="GK3.exe")


def test_emitter_is_bounded_relocatable_and_uses_wide_process_apis() -> None:
    names = (
        "VirtualAlloc",
        "GetModuleHandleA",
        "GetProcAddress",
        "CloseHandle",
        "WaitForSingleObject",
        "ExitProcess",
        "GetLastError",
        "MessageBoxA",
    )
    imports = {name: 0x419000 + index * 4 for index, name in enumerate(names)}
    first = _entrypoint(0x430000, imports, game_directory="Gämé Ω", exe_name="GK3.exe")
    second = _entrypoint(0x450000, imports, game_directory="Gämé Ω", exe_name="GK3.exe")
    assert first != second
    assert len(first) == len(second) < 2048
    assert first.startswith(b"\xfc")  # No inherited direction flag in string copies.
    assert "Gämé Ω\\".encode("utf-16le") in first
    assert "GK3.exe\0".encode("utf-16le") in first
    assert all(name.encode() + b"\0" in first for name in API_NAMES)
