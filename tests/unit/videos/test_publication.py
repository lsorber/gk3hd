"""An interrupted receipt write must not discard completed AI work or user edits."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gk3hd.system.locking import ExclusiveFileLock, LockError, executable_lock_path
from gk3hd.videos import publication
from gk3hd.videos.service import upscale_movies
from tests.unit.videos.test_temporal import RecordingBackend
from tests.unit.videos.test_video import _make_movie


def test_completed_movie_is_recovered_without_repeating_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original.avi", tmp_path / "upscaled"
    _make_movie(source, audio=True)
    real_write = publication.atomic_write

    def fail_receipt(path: Path, payload: bytes) -> None:
        if path.name == "original.mkv.json":
            msg = "receipt write interrupted"
            raise OSError(msg)
        real_write(path, payload)

    monkeypatch.setattr(publication, "atomic_write", fail_receipt)
    with pytest.raises(OSError, match="receipt write interrupted"):
        upscale_movies([source], output, RecordingBackend())
    destination = output / "original.mkv"
    assert destination.is_file()
    assert publication.pending_path(destination).is_file()
    monkeypatch.setattr(publication, "atomic_write", real_write)
    backend = RecordingBackend()
    report = upscale_movies([source], output, backend)
    assert report.skipped == 1
    assert not backend.clips
    assert not publication.pending_path(destination).exists()
    assert destination.with_suffix(".mkv.json").is_file()


def test_file_busy_before_publication_preserves_the_complete_temporary_movie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original.avi", tmp_path / "upscaled"
    _make_movie(source, audio=False)
    real_replace = Path.replace

    def file_busy(path: Path, target: Path) -> Path:
        if path.suffix == ".mkv" and target == output / "original.mkv":
            msg = "output is busy"
            raise PermissionError(msg)
        return real_replace(path, target)

    monkeypatch.setattr(Path, "replace", file_busy)
    with pytest.raises(PermissionError, match="output is busy"):
        upscale_movies([source], output, RecordingBackend())
    destination = output / "original.mkv"
    value = json.loads(publication.pending_path(destination).read_bytes())
    temporary = output / value["temporary"]
    assert temporary.is_file()
    monkeypatch.setattr(Path, "replace", real_replace)
    backend = RecordingBackend()
    assert upscale_movies([source], output, backend).skipped == 1
    assert not backend.clips
    assert not temporary.exists()


def test_a_manually_edited_generated_movie_is_preserved(tmp_path: Path) -> None:
    source, output = tmp_path / "original.avi", tmp_path / "upscaled"
    _make_movie(source, audio=False)
    upscale_movies([source], output, RecordingBackend())
    destination = output / "original.mkv"
    destination.write_bytes(b"manual movie edit")
    with pytest.raises(ValueError, match="changed after generation"):
        upscale_movies([source], output, RecordingBackend())
    assert destination.read_bytes() == b"manual movie edit"


def test_a_second_writer_is_rejected_before_decoding(tmp_path: Path) -> None:
    source, output = tmp_path / "original.avi", tmp_path / "upscaled"
    _make_movie(source, audio=False)
    backend = RecordingBackend()
    with (
        ExclusiveFileLock(executable_lock_path(output / ".movie-generation")),
        pytest.raises(LockError, match="another gk3hd transaction"),
    ):
        upscale_movies([source], output, backend)
    assert not backend.clips
    assert not list(output.iterdir())
