"""Tiny real packs exercise replacement, recovery, reuse and the uninstall baseline."""

import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from gk3hd.textures.install import service
from gk3hd.textures.install.journal import JOURNAL_FILENAME
from gk3hd.textures.pack.build import build_texture_pack
from gk3hd.textures.pack.source import TexturePackSource


def _pack(root: Path, version: str, color: str = "red") -> TexturePackSource:
    source = root / f"source-{version}"
    source.mkdir()
    Image.new("RGB", (4, 4), color).save(source / "ROOM.PNG")
    output = root / f"pack-{version}" / f"gk3hd-texture-pack-v{version}.zip"
    report = build_texture_pack(source, output, version=version)
    return TexturePackSource.local(report.archives[0])


def _snapshot(game: Path) -> dict[str, bytes]:
    return {p.relative_to(game).as_posix(): p.read_bytes() for p in game.rglob("*") if p.is_file()}


def test_upgrade_then_uninstall_restores_original_ini(tmp_path: Path) -> None:
    game = tmp_path / "game"
    game.mkdir()
    ini = game / "gk3.ini"
    original = b"CUSTOM PATHS = other-mod\r\nSound = on\r\n"
    ini.write_bytes(original)
    first, second = _pack(tmp_path, "1.0.0"), _pack(tmp_path, "1.1.0", "blue")
    installed = service.install_texture_pack(game, first)
    old_pixels = (installed.directory / "ROOM.BMP").read_bytes()
    updated = service.install_texture_pack(game, second)
    assert updated.changed
    assert updated.pack_version == "1.1.0"
    assert (updated.directory / "ROOM.BMP").read_bytes() != old_pixels
    service.verify_texture_pack(game)
    service.uninstall_texture_pack(game)
    assert ini.read_bytes() == original
    assert not (game / service.STATE_FILENAME).exists()


def test_same_pack_needs_neither_download_nor_conversion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    game = tmp_path / "game"
    game.mkdir()
    source = _pack(tmp_path, "1.0.0")
    service.install_texture_pack(game, source)
    lock = json.loads(next((tmp_path / "pack-1.0.0").glob("*.json")).read_bytes())
    remote = TexturePackSource.from_lock(lock)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("unchanged pack should not be downloaded or converted")

    monkeypatch.setattr(service, "_obtain_archives", forbidden)
    monkeypatch.setattr(service, "_convert_archives", forbidden)
    before = _snapshot(game)
    assert not service.install_texture_pack(game, remote).changed
    assert _snapshot(game) == before


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_failed_swap_restores_prior_pack_and_ini(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: type[BaseException]
) -> None:
    game = tmp_path / "game"
    game.mkdir()
    first, second = _pack(tmp_path, "1.0.0"), _pack(tmp_path, "1.1.0", "blue")
    service.install_texture_pack(game, first)
    before = _snapshot(game)

    def fail(*_args: object, **_kwargs: object) -> None:
        message = "simulated interruption"
        raise failure(message)

    monkeypatch.setattr(service, "apply_custom_path", fail)
    with pytest.raises(failure, match="simulated interruption"):
        service.install_texture_pack(game, second)
    assert _snapshot(game) == before
    assert not (game / JOURNAL_FILENAME).exists()
    service.verify_texture_pack(game)


def test_unrelated_ini_edits_survive_update_and_uninstall(tmp_path: Path) -> None:
    game = tmp_path / "game"
    game.mkdir()
    ini = game / "GK3.ini"
    ini.write_bytes(b"CUSTOM PATHS = other-mod\nSound = on\n")
    first, second = _pack(tmp_path, "1.0.0"), _pack(tmp_path, "1.1.0", "blue")
    service.install_texture_pack(game, first)
    ini.write_bytes(ini.read_bytes().replace(b"Sound = on", b"Sound = off"))
    service.install_texture_pack(game, second)
    assert b"Sound = off" in ini.read_bytes()
    service.uninstall_texture_pack(game)
    assert ini.read_bytes() == b"CUSTOM PATHS = other-mod\nSound = off\n"


def test_recovery_after_process_loss_restores_the_prior_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    game = tmp_path / "game"
    game.mkdir()
    first, second = _pack(tmp_path, "1.0.0"), _pack(tmp_path, "1.1.0", "blue")
    service.install_texture_pack(game, first)
    before = _snapshot(game)
    with monkeypatch.context() as interruption:
        interruption.setattr(service, "_recover_failed_install", lambda *_args: None)
        interruption.setattr(service, "apply_custom_path", Mock(side_effect=KeyboardInterrupt))
        with pytest.raises(KeyboardInterrupt):
            service.install_texture_pack(game, second)
    assert (game / JOURNAL_FILENAME).exists()
    service.recover_texture_install(game)
    assert _snapshot(game) == before
    assert not service.install_texture_pack(game, first).changed


def test_recovery_finishes_cleanup_without_undoing_a_committed_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    game = tmp_path / "game"
    game.mkdir()
    first, second = _pack(tmp_path, "1.0.0"), _pack(tmp_path, "1.1.0", "blue")
    service.install_texture_pack(game, first)
    with monkeypatch.context() as interruption:
        interruption.setattr(service, "_remove_owned_tree", Mock(side_effect=KeyboardInterrupt))
        with pytest.raises(KeyboardInterrupt):
            service.install_texture_pack(game, second)
    backup = next((game / "gk3hd/textures").glob(".previous-*"))
    (backup / "ROOM.BMP").unlink()
    service.recover_texture_install(game)
    assert service.verify_texture_pack(game).pack_version == "1.1.0"
    assert not backup.exists()
    assert not (game / JOURNAL_FILENAME).exists()
    service.uninstall_texture_pack(game)
    assert not (game / "GK3.ini").exists()


def test_faces_only_update_reuses_existing_bmps_without_archives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    game = tmp_path / "game"
    game.mkdir()
    source = _pack(tmp_path, "1.0.0")
    installed = service.install_texture_pack(game, source)
    before = (installed.directory / "ROOM.BMP").read_bytes()
    lock = json.loads(next((tmp_path / "pack-1.0.0").glob("*.json")).read_bytes())
    remote = TexturePackSource.from_lock(lock)
    asset = Mock()
    asset.joinpath.return_value.read_bytes.return_value = b"updated face coordinates"
    monkeypatch.setattr(service, "files", lambda _package: asset)
    monkeypatch.setattr(service, "_obtain_archives", Mock(side_effect=AssertionError))
    monkeypatch.setattr(service, "_convert_archives", Mock(side_effect=AssertionError))
    assert service.install_texture_pack(game, remote).changed
    assert (installed.directory / "ROOM.BMP").read_bytes() == before
    assert (installed.directory / "FACES.TXT").read_bytes() == b"updated face coordinates"
    service.uninstall_texture_pack(game)
    assert not (game / "GK3.ini").exists()


def test_update_preserves_unowned_files_in_the_texture_directory(tmp_path: Path) -> None:
    game = tmp_path / "game"
    game.mkdir()
    first, second = _pack(tmp_path, "1.0.0"), _pack(tmp_path, "1.1.0", "blue")
    installed = service.install_texture_pack(game, first)
    (installed.directory / "personal-note.txt").write_text("keep this")
    before = _snapshot(game)
    with pytest.raises(service.TexturePackError, match="inventory"):
        service.install_texture_pack(game, second)
    assert _snapshot(game) == before


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation requires Windows privileges")
def test_update_rejects_a_redirected_workspace_without_changing_its_contents(
    tmp_path: Path,
) -> None:
    game = tmp_path / "game"
    game.mkdir()
    first, second = _pack(tmp_path, "1.0.0"), _pack(tmp_path, "1.1.0", "blue")
    service.install_texture_pack(game, first)
    workspace = game / "gk3hd"
    moved = game / "moved-workspace"
    workspace.rename(moved)
    workspace.symlink_to(moved, target_is_directory=True)
    before = _snapshot(game)
    with pytest.raises(service.TexturePackError, match="redirected"):
        service.install_texture_pack(game, second)
    assert _snapshot(game) == before


@pytest.mark.parametrize(
    "original", [None, b"Sound = on\r\n", b"CUSTOM PATHS = gk3hd/textures/installed; other\n"]
)
def test_update_keeps_user_ini_edits_with_or_without_an_original_custom_path(
    tmp_path: Path, original: bytes | None
) -> None:
    game = tmp_path / "game"
    game.mkdir()
    ini = game / "GK3.ini"
    if original is not None:
        ini.write_bytes(original)
    source = _pack(tmp_path, "1.0.0")
    service.install_texture_pack(game, source)
    ini.write_bytes(ini.read_bytes() + b"USER = keep\n")
    assert service.install_texture_pack(game, source).changed
    service.uninstall_texture_pack(game)
    expected = (original or b"") + b"USER = keep\n"
    assert ini.read_bytes() == expected
