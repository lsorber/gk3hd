"""Renderer ownership, replacement and interruption contracts without a real game."""

import hashlib
import json
import struct
from pathlib import Path
from unittest.mock import Mock

import pytest

from gk3hd.patch.install.windows import ConfigurationError, WindowsInstallConfiguration
from gk3hd.patch.manifest import manifest_path_for_exe
from gk3hd.renderer import distribution, service
from gk3hd.renderer.service import RendererService
from gk3hd.renderer.state import JOURNAL_FILENAME, STATE_FILENAME, RendererState
from tests.unit.patch.test_windows_install_configuration import MemoryRegistry


def _dll(label: bytes) -> bytes:
    header = bytearray(256)
    header[:2] = b"MZ"
    struct.pack_into("<I", header, 0x3C, 64)
    header[64:68] = b"PE\0\0"
    struct.pack_into("<H", header, 68, 0x14C)
    struct.pack_into("<H", header, 86, 0x2000)
    struct.pack_into("<H", header, 88, 0x10B)
    return bytes(header) + label


@pytest.fixture
def environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, RendererService, MemoryRegistry]:
    exe = tmp_path / "game" / "GK3.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"private fixture")
    candidate = tmp_path / "candidate.dll"
    candidate.write_bytes(_dll(b"tested candidate"))
    monkeypatch.setattr(distribution, "cache_directory", lambda: tmp_path / "cache")
    monkeypatch.setattr(service, "download", lambda **_kwargs: candidate)
    registry = MemoryRegistry()
    renderer = RendererService(
        configuration=WindowsInstallConfiguration(registry), process_probe=lambda: False
    )
    return exe, renderer, registry


def test_install_replace_verify_and_restore_original_state(
    environment: tuple[Path, RendererService, MemoryRegistry],
    tmp_path: Path,
) -> None:
    exe, renderer, registry = environment
    config = exe.with_name("dxvk.conf")
    original = b"# unrelated settings\r\n[other.exe]\r\nd3d9.presentInterval = 1\r\n"
    config.write_bytes(original)
    first = renderer.install(exe=exe)
    assert renderer.verify(exe=exe) == first
    assert "16BITCOLOR" in registry.values[str(exe.resolve())]
    assert exe.read_bytes() == b"private fixture"
    (tmp_path / "candidate.dll").write_bytes(_dll(b"newer tested candidate"))
    second = renderer.install(exe=exe)
    assert second.digest != first.digest
    assert [c.previous for c in second.changes] == [c.previous for c in first.changes]
    renderer.uninstall(exe=exe)
    assert config.read_bytes() == original
    assert not exe.with_name("ddraw.dll").exists()
    assert not exe.with_name(STATE_FILENAME).exists()
    assert not exe.with_name(JOURNAL_FILENAME).exists()
    assert registry.values == {}


def test_install_preserves_unmanaged_renderer(
    environment: tuple[Path, RendererService, MemoryRegistry],
) -> None:
    exe, renderer, _registry = environment
    dll = exe.with_name("ddraw.dll")
    dll.write_bytes(b"user renderer")
    with pytest.raises(ValueError, match="unmanaged graphics"):
        renderer.install(exe=exe)
    assert dll.read_bytes() == b"user renderer"


def test_local_install_selects_the_target_games_build(
    environment: tuple[Path, RendererService, MemoryRegistry],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    exe, renderer, _registry = environment
    candidate = tmp_path / "candidate.dll"
    asset = Mock(path=candidate, dll_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest())
    lookup = Mock(return_value=asset)
    monkeypatch.setattr(service, "local_build", lookup)
    renderer.install(exe=exe, local=True)
    lookup.assert_called_once_with(game_dir=exe.resolve().parent)
    assert exe.with_name("ddraw.dll").read_bytes() == candidate.read_bytes()


def test_later_user_edit_blocks_replace_and_uninstall(
    environment: tuple[Path, RendererService, MemoryRegistry],
) -> None:
    exe, renderer, _registry = environment
    renderer.install(exe=exe)
    config = exe.with_name("dxvk.conf")
    config.write_bytes(b"user changed settings")
    for operation in (renderer.install, renderer.uninstall):
        with pytest.raises(ConfigurationError, match="no longer matches"):
            operation(exe=exe)
    assert config.read_bytes() == b"user changed settings"


def test_renderer_removal_guards_dependent_patches(
    environment: tuple[Path, RendererService, MemoryRegistry],
) -> None:
    exe, renderer, _registry = environment
    renderer.install(exe=exe)
    manifest_path_for_exe(exe).write_text("patch ownership")
    with pytest.raises(ValueError, match="remove executable patches"):
        renderer.uninstall(exe=exe)
    assert exe.with_name("ddraw.dll").is_file()


def test_failed_replace_restores_previous_installed_renderer(
    environment: tuple[Path, RendererService, MemoryRegistry],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exe, renderer, _registry = environment
    first = renderer.install(exe=exe)
    before = exe.with_name("ddraw.dll").read_bytes()
    (tmp_path / "candidate.dll").write_bytes(_dll(b"second candidate"))
    write = renderer._write_state
    failed = False

    def fail_once(target: Path, state: RendererState | None) -> None:
        nonlocal failed
        if not failed:
            failed = True
            message = "interrupted state publication"
            raise OSError(message)
        write(target, state)

    monkeypatch.setattr(renderer, "_write_state", fail_once)
    with pytest.raises(OSError, match="interrupted state"):
        renderer.install(exe=exe)
    assert renderer.verify(exe=exe) == first
    assert exe.with_name("ddraw.dll").read_bytes() == before


def test_recovery_finishes_interrupted_uninstall(
    environment: tuple[Path, RendererService, MemoryRegistry],
) -> None:
    exe, renderer, registry = environment
    state = renderer.install(exe=exe)
    renderer._journal(exe, "uninstall", state, state)
    exe.with_name("ddraw.dll").unlink()
    renderer.recover(exe=exe)
    assert not exe.with_name(STATE_FILENAME).exists()
    assert registry.values == {}


def test_running_game_is_rejected_before_downloading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"fixture")
    download = Mock()
    monkeypatch.setattr(service, "download", download)
    with pytest.raises(RuntimeError, match="close GK3"):
        RendererService(process_probe=lambda: True).install(exe=exe)
    download.assert_not_called()


def test_corrupt_state_cannot_authorize_unrelated_changes(
    environment: tuple[Path, RendererService, MemoryRegistry],
) -> None:
    exe, renderer, _registry = environment
    state = renderer.install(exe=exe)
    data = state.to_dict()
    assert isinstance(data["changes"], list)
    data["changes"][0]["key"] = "GK3.exe"
    exe.with_name(STATE_FILENAME).write_text(json.dumps(data))
    with pytest.raises(ValueError, match="unsupported"):
        renderer.uninstall(exe=exe)
    assert hashlib.sha256(exe.read_bytes()).digest() == hashlib.sha256(b"private fixture").digest()
