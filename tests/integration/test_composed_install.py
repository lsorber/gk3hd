"""Composition preserves existing components and rolls back only newly owned state."""

import json
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import gk3hd.install as installation
from gk3hd.patch.service import PatchRequest
from gk3hd.textures.install.service import STATE_FILENAME, TextureInstallRequest
from gk3hd.textures.progress import TextureInstallProgress
from gk3hd.videos.pack import PackRequest


@pytest.fixture(autouse=True)
def renderer_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Keep composition tests offline and independent of the native registry."""
    renderer = Mock()
    state = tmp_path / installation.RENDERER_STATE_FILENAME
    renderer.install.side_effect = lambda **_kwargs: state.write_text("installed")
    renderer.uninstall.side_effect = lambda **_kwargs: state.unlink(missing_ok=True)
    monkeypatch.setattr(installation, "RendererService", lambda: renderer)
    return renderer


@pytest.fixture(autouse=True)
def video_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Exercise composition ownership without downloading or decoding real videos."""
    videos = Mock()
    state = tmp_path / installation.VIDEO_STATE_FILENAME
    videos.install.side_effect = lambda *_args, **_kwargs: state.write_text("installed")
    videos.uninstall.side_effect = lambda *_args, **_kwargs: state.unlink(missing_ok=True)

    def verify(_game_dir: Path, **options: object) -> SimpleNamespace:
        progress = options.get("progress")
        if callable(progress):
            progress("Verifying videos", 10, 10)
        return SimpleNamespace(videos=1)

    videos.verify.side_effect = verify
    monkeypatch.setattr(installation, "install_pack", videos.install)
    monkeypatch.setattr(
        installation, "MovieInstaller", Mock(return_value=videos, verify=videos.verify)
    )
    return videos


@pytest.mark.parametrize("existing", list(product((False, True), repeat=3)))
@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_composed_failure_restores_only_new_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    video_adapter: Mock,
    *,
    existing: tuple[bool, bool, bool],
    failure: type[BaseException],
) -> None:
    patch_existed, textures_existed, videos_existed = existing
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"test")
    texture_state = tmp_path / STATE_FILENAME
    if textures_existed:
        texture_state.write_bytes(b"existing")
    video_state = tmp_path / installation.VIDEO_STATE_FILENAME
    if videos_existed:
        video_state.write_bytes(b"existing")
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
    assert video_adapter.install.call_count == int(not videos_existed)
    assert video_adapter.uninstall.call_count == int(not videos_existed)
    assert video_state.exists() == videos_existed
    if videos_existed:
        assert video_state.read_bytes() == b"existing"
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
    payload = json.dumps({"schema_version": 2, "existing": ["unknown-component"]})
    journal.write_text(payload)
    patch, textures = Mock(), Mock()
    monkeypatch.setattr(installation, "PatchService", lambda: patch)
    monkeypatch.setattr(installation, "texture_install", textures)

    with pytest.raises(installation.CompositeInstallError, match="malformed"):
        installation.recover(exe=exe)

    assert not patch.mock_calls
    assert not textures.mock_calls
    assert journal.read_text() == payload


def test_composed_install_reports_work_before_texture_conversion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    renderer_adapter: Mock,
    video_adapter: Mock,
) -> None:
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"test")
    renderer_state = tmp_path / installation.RENDERER_STATE_FILENAME
    texture_state = tmp_path / STATE_FILENAME
    updates: list[TextureInstallProgress] = []

    def install_renderer(**kwargs: object) -> None:
        renderer_state.write_text("installed")
        callback = kwargs["progress"]
        assert callable(callback)
        callback(5, 10)

    renderer_adapter.install.side_effect = install_renderer
    patch = Mock()
    patch.status.return_value.installed = False
    patch.verify.return_value.patches = ("example",)
    patch.install.side_effect = lambda _request: setattr(
        patch.status.return_value, "installed", True
    )
    monkeypatch.setattr(installation, "PatchService", lambda: patch)
    textures = Mock()
    textures.install.side_effect = lambda *_args, **_kwargs: texture_state.write_text("installed")
    textures.verify.return_value.textures = 1
    monkeypatch.setattr(installation, "texture_install", textures)

    report = installation.install(
        PatchRequest(exe=exe),
        TextureInstallRequest(exe=exe, cache_dir=tmp_path / "cache", offline=True),
        progress=updates.append,
    )

    assert report.changed
    assert report.patches == report.textures == report.videos == 1
    assert video_adapter.install.call_args.args[1] == PackRequest(
        cache=tmp_path / "cache", offline=True
    )
    assert TextureInstallProgress("Downloading renderer", 5, 10, "bytes") in updates
    assert TextureInstallProgress("Installing patches", 0, 1) in updates
    assert TextureInstallProgress("Verifying textures", 1, 1) in updates
    assert TextureInstallProgress("Verifying videos", 10, 10, "bytes") == updates[-1]
    repeated = installation.install(PatchRequest(exe=exe), TextureInstallRequest(exe=exe))
    assert not repeated.changed
    assert renderer_adapter.install.call_count == 1
    assert patch.install.call_count == 1
    assert textures.install.call_count == 1
    assert video_adapter.install.call_count == 1


def test_recovery_keeps_existing_components_and_removes_new_videos(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    video_adapter: Mock,
) -> None:
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"test")
    (tmp_path / STATE_FILENAME).write_bytes(b"previous textures")
    (tmp_path / installation.VIDEO_STATE_FILENAME).write_bytes(b"new videos")
    (tmp_path / installation.RENDERER_STATE_FILENAME).write_bytes(b"previous renderer")
    journal = tmp_path / installation.COMPOSITE_JOURNAL_FILENAME
    journal.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "existing": ["renderer", "patch", "textures"],
            }
        )
    )
    patch, textures = Mock(), Mock()
    monkeypatch.setattr(installation, "PatchService", lambda: patch)
    monkeypatch.setattr(installation, "texture_install", textures)
    assert installation.recover(exe=exe)
    assert not (tmp_path / installation.VIDEO_STATE_FILENAME).exists()
    assert (tmp_path / STATE_FILENAME).read_bytes() == b"previous textures"
    assert (tmp_path / installation.RENDERER_STATE_FILENAME).read_bytes() == b"previous renderer"
    patch.uninstall.assert_not_called()
    textures.uninstall.assert_not_called()
    video_adapter.uninstall.assert_called_once()
    assert not journal.exists()


def test_video_failure_preserves_error_and_restores_new_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    video_adapter: Mock,
    renderer_adapter: Mock,
) -> None:
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"test")
    patch, textures = Mock(), Mock()
    patch.status.return_value.installed = False
    patch.install.side_effect = lambda _request: setattr(
        patch.status.return_value, "installed", True
    )
    state = tmp_path / STATE_FILENAME
    textures.install.side_effect = lambda *_args, **_kwargs: state.write_bytes(b"new textures")
    textures.uninstall.side_effect = lambda **_kwargs: state.unlink()
    monkeypatch.setattr(installation, "PatchService", lambda: patch)
    monkeypatch.setattr(installation, "texture_install", textures)

    def fail(*_args: object, **_kwargs: object) -> None:
        (tmp_path / installation.VIDEO_STATE_FILENAME).write_bytes(b"new videos")
        msg = "video installation failed"
        raise RuntimeError(msg)

    video_adapter.install.side_effect = fail
    with pytest.raises(RuntimeError, match="video installation failed"):
        installation.install(PatchRequest(exe=exe), TextureInstallRequest(exe=exe))
    video_adapter.uninstall.assert_called_once()
    textures.uninstall.assert_called_once()
    patch.uninstall.assert_called_once()
    renderer_adapter.uninstall.assert_called_once()
    assert not (tmp_path / installation.COMPOSITE_JOURNAL_FILENAME).exists()
