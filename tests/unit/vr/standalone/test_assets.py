"""Private resource selection preserves desktop bytes and portable pack identity."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import pytest

from gk3hd.system.ini import prepare_custom_path
from gk3hd.textures.install.service import STATE_FILENAME, STATE_SCHEMA, TEXTURE_DIRECTORY
from gk3hd.textures.pack.format import TexturePackError
from gk3hd.videos.catalog import MOVIE_INSTALL_PATH
from gk3hd.videos.manifest import STATE_FILENAME as VIDEO_STATE_FILENAME
from gk3hd.videos.manifest import MovieFile, MovieState, PlayerResource
from gk3hd.vr.standalone.assets import texture_inputs, video_inputs

if TYPE_CHECKING:
    from pathlib import Path


def installed_pack_fixture(game: Path) -> Path:
    """Two owned payloads, no real game binaries or copyrighted texture data."""
    directory = game / TEXTURE_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKIN.BMP").write_bytes(b"BM synthetic pixel fixture")
    (directory / "FACES.TXT").write_bytes(b"synthetic corrected resource")
    (game / "GK3.ini").write_bytes(b"Private desktop setting = do-not-copy\n")
    change, installed = prepare_custom_path(game, TEXTURE_DIRECTORY)
    (game / "GK3.ini").write_bytes(installed)
    (game / STATE_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": STATE_SCHEMA,
                "directory": TEXTURE_DIRECTORY,
                "pack_version": "1.1.1",
                "manifest_sha256": "0" * 64,
                "texture_count": 1,
                "files": [
                    {"filename": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                    for path in sorted(directory.iterdir())
                ],
                "ini": change.to_dict(),
            }
        ),
        encoding="utf-8",
    )
    return directory


def test_installed_hd_and_corrected_resources_are_selected_without_preferences(
    tmp_path: Path,
) -> None:
    game = tmp_path / "game"
    directory = installed_pack_fixture(game)
    original = (game / "GK3.ini").read_bytes()
    textures = texture_inputs(game, enabled=True)
    assert set(textures.files.values()) == set(directory.iterdir())
    assert set(textures.hashes) == set(textures.files)
    for name, path in textures.files.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == textures.hashes[name]
    assert textures.ini == f"CUSTOM PATHS = {TEXTURE_DIRECTORY}\n".encode()
    metadata = json.loads(textures.metadata)
    assert metadata["texture_count"] == 1
    assert metadata["mode"] == "installed-hd"
    assert b"do-not-copy" not in textures.ini + textures.metadata
    assert str(game).encode() not in textures.metadata
    assert (game / "GK3.ini").read_bytes() == original
    textures.verify_unchanged()


def test_original_archives_require_an_explicit_control(tmp_path: Path) -> None:
    textures = texture_inputs(tmp_path, enabled=False)
    assert not textures.files
    assert not textures.hashes
    assert textures.ini == b""
    assert json.loads(textures.metadata)["mode"] == "original"
    with pytest.raises(ValueError, match="HD textures are not installed"):
        texture_inputs(tmp_path, enabled=True)


def test_explicit_baseline_does_not_read_or_change_installed_textures(tmp_path: Path) -> None:
    directory = installed_pack_fixture(tmp_path)
    (directory / "SKIN.BMP").write_bytes(b"modified source")
    assert not texture_inputs(tmp_path, enabled=False).files
    assert (directory / "SKIN.BMP").read_bytes() == b"modified source"


def test_modified_installed_payload_is_not_silently_copied(tmp_path: Path) -> None:
    directory = installed_pack_fixture(tmp_path)
    (directory / "SKIN.BMP").write_bytes(b"externally replaced")
    with pytest.raises(TexturePackError, match="changed after installation"):
        texture_inputs(tmp_path, enabled=True)


def test_pack_replacement_invalidates_frozen_resource_selection(tmp_path: Path) -> None:
    installed_pack_fixture(tmp_path)
    textures = texture_inputs(tmp_path, enabled=True)
    (tmp_path / STATE_FILENAME).write_bytes(b"replaced ownership")
    with pytest.raises(ValueError, match="ownership changed"):
        textures.verify_unchanged()


def installed_video_fixture(game: Path) -> Path:
    """Owned synthetic replacement/player bytes; no codecs or videos are executed."""
    directory = game / MOVIE_INSTALL_PATH
    directory.mkdir(parents=True, exist_ok=True)
    source = game / "Data/intro.bik"
    source.parent.mkdir(exist_ok=True)
    source.write_bytes(b"movie data")
    movie = directory / "GK3HD-INTRO.AVI"
    movie.write_bytes(b"synthetic encoded movie")
    resources = []
    for name in ("gk3hd-videos.dll", "LAVVideo.ax"):
        resource = directory / name
        resource.write_bytes(b"synthetic player resource " + name.encode())
        resources.append(
            PlayerResource(
                name, hashlib.sha256(resource.read_bytes()).hexdigest(), resource.stat().st_size
            )
        )
    state = MovieState(
        (
            MovieFile(
                movie.name,
                source.name,
                hashlib.sha256(source.read_bytes()).hexdigest(),
                hashlib.sha256(movie.read_bytes()).hexdigest(),
                movie.stat().st_size,
            ),
        ),
        tuple(resources),
        "a" * 64,
    )
    (game / VIDEO_STATE_FILENAME).write_text(json.dumps(state.to_dict()), encoding="utf-8")
    return directory


def test_video_selection_includes_replacements_player_and_codecs_without_desktop_paths(
    tmp_path: Path,
) -> None:
    game = tmp_path / "game"
    directory = installed_video_fixture(game)
    (game / "GK3.exe").write_bytes(b"game fixture")
    (game / "GK3.ini").write_bytes(b"private desktop preferences")
    before = (game / "GK3.ini").read_bytes()
    videos = video_inputs(game, enabled=True)
    assert set(videos.files.values()) == set(directory.iterdir())
    assert set(videos.hashes) == set(videos.files)
    assert not videos.ini
    metadata = json.loads(videos.metadata)
    assert metadata["mode"] == "installed-hd"
    assert metadata["video_count"] == 1
    assert metadata["player_resources"] == 2
    assert str(game).encode() not in videos.metadata
    assert (game / "GK3.ini").read_bytes() == before
    videos.verify_unchanged()


def test_missing_videos_cannot_silently_become_the_recommended_baseline(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="HD videos are not installed"):
        video_inputs(tmp_path, enabled=True)
    control = video_inputs(tmp_path, enabled=False)
    assert not control.files
    assert json.loads(control.metadata)["mode"] == "original"


def test_modified_video_payload_is_rejected_and_state_changes_invalidate_selection(
    tmp_path: Path,
) -> None:
    directory = installed_video_fixture(tmp_path)
    (tmp_path / "GK3.exe").write_bytes(b"game fixture")
    videos = video_inputs(tmp_path, enabled=True)
    (tmp_path / VIDEO_STATE_FILENAME).write_bytes(b"changed ownership")
    with pytest.raises(ValueError, match="ownership changed"):
        videos.verify_unchanged()
    installed_video_fixture(tmp_path)
    (directory / "GK3HD-INTRO.AVI").write_bytes(b"foreign video")
    with pytest.raises(ValueError, match="changed"):
        video_inputs(tmp_path, enabled=True)
