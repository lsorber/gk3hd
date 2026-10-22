"""Tiny generated movie installations, independent of real game data and AI weights."""

from __future__ import annotations

import json
import shutil
import zipfile
from typing import TYPE_CHECKING

import pytest

from gk3hd.system.files import sha256_file
from gk3hd.videos import runtime
from gk3hd.videos.runtime import recipe_digest
from gk3hd.videos.service import upscale_movies
from tests.unit.videos.test_interpolation import LinearInterpolator
from tests.unit.videos.test_player_install import _player
from tests.unit.videos.test_temporal import RecordingBackend
from tests.unit.videos.test_video import _make_movie


@pytest.fixture
def interpolator(monkeypatch: pytest.MonkeyPatch) -> LinearInterpolator:
    from gk3hd.videos import av1  # noqa: PLC0415 - replace only the inference boundary.

    backend = LinearInterpolator()
    monkeypatch.setattr(av1, "create_interpolator", lambda _backend: backend)
    return backend


if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def game(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "Game With Spaces"
    (root / "Data").mkdir(parents=True)
    (root / "GK3.exe").write_bytes(b"fixture executable")
    (root / "GK3.ini").write_bytes(b"CUSTOM PATHS = gk3hd/textures/installed\r\nOther = 3\r\n")
    original = root / "Data/intro.avi"
    _make_movie(original, audio=True)
    upscale_movies(
        [original],
        root / "gk3hd/videos/upscaled",
        RecordingBackend(),
    )
    _player(root / "gk3hd/videos/player" / recipe_digest()[:16] / "runtime")
    pin = json.loads((runtime.RECIPE / "upstream.json").read_bytes())
    archive = tmp_path / "upstream-codecs.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for name in pin["files"]:
            bundle.writestr(name, b"bounded player test fixture: " + name.encode())
    pin.update(sha256=sha256_file(archive), size=archive.stat().st_size)
    (tmp_path / "codec-pin.json").write_text(json.dumps(pin))
    monkeypatch.setattr(runtime, "_pin", lambda: pin)
    monkeypatch.setattr(runtime, "cache_directory", lambda: tmp_path / "codec-cache")
    cached = runtime.codec_cache()
    cached.parent.mkdir(parents=True)
    shutil.copyfile(archive, cached)

    def download(_url: str, destination: Path, **options: object) -> Path:
        assert options["sha256"] == pin["sha256"]
        assert options["size"] == pin["size"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(archive, destination)
        return destination

    monkeypatch.setattr(runtime, "download_verified", download)
    return root
