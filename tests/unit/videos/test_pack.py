"""The same release pack installs locally or from verified downloads, without AI."""

from __future__ import annotations

import json
import shutil
import zipfile
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from gk3hd.cli import app
from gk3hd.system.files import sha256_file
from gk3hd.videos import pack
from gk3hd.videos.catalog import extract, movie_workspace
from gk3hd.videos.install import MovieInstaller
from gk3hd.videos.manifest import STATE_FILENAME
from gk3hd.videos.pack import (
    LOCK_FILENAME,
    MANIFEST_FILENAME,
    PackRequest,
    build_pack,
    install_pack,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def test_local_pack_cli_roundtrip_preserves_originals_and_does_not_rebuild(
    game: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gk3hd.videos import install  # noqa: PLC0415 - process boundary only.

    monkeypatch.setattr(install, "is_gk3_running", lambda: False)
    original = (game / "Data/intro.avi").read_bytes()
    runner = CliRunner()
    for command in ("pack", "install", "verify", "uninstall"):
        arguments = ["videos", command, "--game-dir", str(game)]
        if command == "install":
            arguments.append("--local")
        result = runner.invoke(app, arguments)
        assert result.exit_code == 0, result.output + repr(result.exception)
    assert (game / "Data/intro.avi").read_bytes() == original
    assert not (game / STATE_FILENAME).exists()
    assert (movie_workspace(game) / "upscaled/intro.mkv").is_file()
    assert not list(movie_workspace(game).glob(".unpack-*"))


def test_split_packs_are_deterministic_and_require_all_parts(
    game: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(pack, "_BLOCK", 128)
    monkeypatch.setattr(pack, "MAX_ARCHIVE_BYTES", 6500)
    first = build_pack(game, version="2.0.0")
    assert len(first) > 1
    before = [sha256_file(path) for path in first]
    assert before == [sha256_file(path) for path in build_pack(game, version="2.0.0")]
    destination = tmp_path / "unpacked"
    destination.mkdir()
    with pytest.raises(ValueError, match="incomplete"):
        pack.unpack(first[:-1], destination)
    assert not (game / STATE_FILENAME).exists()


def test_default_install_downloads_pinned_pack_and_reuses_it_offline(
    game: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from gk3hd.videos import install  # noqa: PLC0415 - process boundary only.

    monkeypatch.setattr(install, "is_gk3_running", lambda: False)
    archives = build_pack(game, version="2.0.0")
    lock = json.loads((movie_workspace(game) / LOCK_FILENAME).read_bytes())
    real_read = pack.read_json
    monkeypatch.setattr(
        pack,
        "read_json",
        lambda path: lock if path.parent.name == "assets" else real_read(path),
    )
    requests = []

    def download(
        url: str,
        destination: Path,
        *,
        sha256: str,
        size: int,
        progress: Callable[[int, int | None], None],
    ) -> Path:
        requests.append(url)
        source = next(path for path in archives if path.name == url.rsplit("/", 1)[1])
        assert source.stat().st_size == size
        assert sha256_file(source) == sha256
        destination.parent.mkdir(parents=True)
        shutil.copyfile(source, destination)
        progress(size, size)
        return destination

    monkeypatch.setattr(pack, "download_verified", download)
    events = []
    request = PackRequest(cache=tmp_path / "cache")
    report = install_pack(game, request, progress=lambda *event: events.append(event))
    assert report.videos == 1
    assert requests == [
        "https://github.com/lsorber/gk3hd/releases/download/v2.0.0/" + path.name
        for path in archives
    ]
    assert any(name == "Downloading videos" and done == total > 0 for name, done, total in events)
    assert not install_pack(game, PackRequest(cache=request.cache, offline=True)).changed
    assert len(requests) == len(archives)
    MovieInstaller().uninstall(game)
    cached = next((tmp_path / "cache").rglob("*.zip"))
    cached.write_bytes(b"changed")
    with pytest.raises(ValueError, match="missing or changed"):
        install_pack(game, PackRequest(cache=request.cache, offline=True))
    assert not (game / STATE_FILENAME).exists()


@pytest.mark.parametrize("defect", ["traversal", "extra", "hash", "duplicate", "mixed"])
def test_unsafe_or_inconsistent_archives_never_reach_the_game(
    game: Path,
    tmp_path: Path,
    defect: str,
) -> None:
    (archive,) = build_pack(game, version="2.0.0")
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive) as original:
        members = {name: original.read(name) for name in original.namelist()}
    header = json.loads(members.pop(MANIFEST_FILENAME))
    name = next(name for name in header["files"] if name.endswith("intro.mkv"))
    if defect == "traversal":
        malicious = "gk3hd/videos/upscaled/../../outside"
        header["files"][malicious] = header["files"].pop(name)
        members[malicious] = members.pop(name)
    elif defect == "extra":
        members["unexpected.dll"] = b"not declared"
    elif defect == "hash":
        members[name] = bytes(len(members[name]))
    elif defect == "duplicate":
        duplicate = name.replace("intro", "INTRO")
        members[duplicate] = members[name]
        header["files"][duplicate] = header["files"][name]
    else:
        header["parts"] = 2
    with zipfile.ZipFile(bad, "w") as output:
        for key, value in members.items():
            output.writestr(key, value)
        output.writestr(MANIFEST_FILENAME, json.dumps(header))
    destination = tmp_path / "unpack"
    destination.mkdir()
    with pytest.raises(ValueError, match=r"unsafe|undeclared|verification|identity|incomplete"):
        pack.unpack([bad], destination)
    assert not (game / STATE_FILENAME).exists()
    assert not (tmp_path / "outside").exists()


def test_extraction_resumes_identical_originals_and_preserves_differing_files(
    game: Path,
) -> None:
    output = movie_workspace(game) / "original"
    assert extract(game / "Data", output) == 1
    assert extract(game / "Data", output) == 1
    assert (output / "intro.avi").read_bytes() == (game / "Data/intro.avi").read_bytes()
    (output / "intro.avi").write_bytes(b"user file")
    with pytest.raises(ValueError, match="overwrite"):
        extract(game / "Data", output)
    assert (output / "intro.avi").read_bytes() == b"user file"
