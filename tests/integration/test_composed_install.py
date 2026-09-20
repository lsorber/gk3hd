"""Composition preserves existing components and rolls back only newly owned state."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import gk3hd.install as installation
from gk3hd.patch.service import PatchRequest
from gk3hd.textures.install.service import STATE_FILENAME, TextureInstallRequest


@pytest.fixture(autouse=True)
def renderer_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Keep composition tests offline and independent of the native registry."""
    renderer = Mock()
    state = tmp_path / installation.RENDERER_STATE_FILENAME
    renderer.install.side_effect = lambda **_kwargs: state.write_text("installed")
    renderer.uninstall.side_effect = lambda **_kwargs: state.unlink(missing_ok=True)
    monkeypatch.setattr(installation, "RendererService", lambda: renderer)
    return renderer


@pytest.mark.parametrize("patch_existed", [False, True])
@pytest.mark.parametrize("textures_existed", [False, True])
@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_composed_failure_restores_only_new_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    patch_existed: bool,
    textures_existed: bool,
    failure: type[BaseException],
) -> None:
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"test")
    texture_state = tmp_path / STATE_FILENAME
    if textures_existed:
        texture_state.write_bytes(b"existing")
    patch = Mock()
    patch.status.return_value.installed = patch_existed

    def install_patch(_request: PatchRequest) -> None:
        patch.status.return_value.installed = True

    patch.install.side_effect = install_patch
    patch.verify.side_effect = failure("verification interrupted")
    monkeypatch.setattr(installation, "PatchService", lambda: patch)
    textures = Mock()

    def install_textures(_request: TextureInstallRequest, **_kwargs: object) -> None:
        texture_state.write_bytes(b"new")

    textures.install.side_effect = install_textures
    textures.uninstall.side_effect = lambda **_kwargs: texture_state.unlink()
    monkeypatch.setattr(installation, "texture_install", textures)

    with pytest.raises(failure, match="verification interrupted"):
        installation.install(PatchRequest(exe=exe), TextureInstallRequest(exe=exe))

    assert patch.install.call_count == int(not patch_existed)
    assert patch.uninstall.call_count == int(not patch_existed)
    assert textures.install.call_count == int(not textures_existed)
    assert textures.uninstall.call_count == int(not textures_existed)
    assert texture_state.exists() == textures_existed
    if textures_existed:
        assert texture_state.read_bytes() == b"existing"
    assert not (tmp_path / installation.COMPOSITE_JOURNAL_FILENAME).exists()


def test_failed_rollback_preserves_intent_and_primary_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"test")
    patch = Mock()
    patch.status.return_value.installed = False
    primary = ValueError("install failed")
    patch.install.side_effect = primary
    monkeypatch.setattr(installation, "PatchService", lambda: patch)
    textures = Mock()
    textures.recover.side_effect = [None, RuntimeError("recovery failed")]
    monkeypatch.setattr(installation, "texture_install", textures)

    with pytest.raises(ValueError, match="install failed") as caught:
        installation.install(PatchRequest(exe=exe), TextureInstallRequest(exe=exe))

    assert caught.value is primary
    assert any("recovery failed" in note for note in primary.__notes__)
    journal = tmp_path / installation.COMPOSITE_JOURNAL_FILENAME
    assert journal.is_file()
    textures.recover.side_effect = None
    assert installation.recover(exe=exe)
    assert not journal.exists()


def test_malformed_composite_journal_cannot_authorize_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"test")
    journal = tmp_path / installation.COMPOSITE_JOURNAL_FILENAME
    payload = json.dumps({"schema_version": 1, "patch_existed": 0, "textures_existed": False})
    journal.write_text(payload)
    patch, textures = Mock(), Mock()
    monkeypatch.setattr(installation, "PatchService", lambda: patch)
    monkeypatch.setattr(installation, "texture_install", textures)

    with pytest.raises(installation.CompositeInstallError, match="malformed"):
        installation.recover(exe=exe)

    assert not patch.mock_calls
    assert not textures.mock_calls
    assert journal.read_text() == payload
