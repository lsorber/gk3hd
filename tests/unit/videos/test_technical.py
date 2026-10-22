"""Technical diagrams retain their original bytes, palette, geometry and audio."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest

from gk3hd.videos.service import MovieUpscaleOptions, upscale_movies
from gk3hd.videos.video import convert, restoration_pipeline
from tests.unit.videos.test_temporal import RecordingBackend
from tests.unit.videos.test_video import _make_movie

if TYPE_CHECKING:
    from pathlib import Path


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return kind + struct.pack("<I", len(payload)) + payload + bytes(len(payload) % 2)


def _make_rle_movie(path: Path, *, colors: dict[int, tuple[int, int, int]] | None = None) -> None:
    """Write a tiny original RLE8 AVI, not a copyrighted game fixture."""
    width, height, count = 4, 2, 5
    header = struct.pack("<14I", 66667, 1000, 0, 0, count, 0, 1, 10, width, height, 0, 0, 0, 0)
    stream = struct.pack(
        "<4s4sIHH8I4h",
        b"vids",
        b"MRLE",
        0,
        0,
        0,
        0,
        1,
        15,
        0,
        count,
        10,
        0xFFFFFFFF,
        0,
        0,
        0,
        width,
        height,
    )
    bitmap = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 8, 1, 10, 0, 0, 256, 0)
    palette = bytearray(
        b"".join(bytes((index, 255 - index, index // 2, 0)) for index in range(256))
    )
    for index, rgb in (colors or {}).items():
        palette[index * 4 : index * 4 + 4] = bytes((*reversed(rgb), 0))
    streams = _chunk(b"LIST", b"strl" + _chunk(b"strh", stream) + _chunk(b"strf", bitmap + palette))
    headers = _chunk(b"LIST", b"hdrl" + _chunk(b"avih", header) + streams)
    frames = b"".join(
        _chunk(b"00dc", bytes((width, index * 40, 0, 0, width, 200 - index * 30, 0, 0, 0, 1)))
        for index in range(count)
    )
    path.write_bytes(_chunk(b"RIFF", b"AVI " + headers + _chunk(b"LIST", b"movi" + frames)))


def test_technical_animations_are_retained_without_creating_replacements(tmp_path: Path) -> None:
    source, output = tmp_path / "diagram.avi", tmp_path / "upscaled"
    _make_rle_movie(source)
    original = source.read_bytes()
    assert restoration_pipeline(source) == "retain"
    backend = RecordingBackend()
    report = upscale_movies([source], output, backend, options=MovieUpscaleOptions())
    assert (report.generated, report.skipped, report.retained) == (0, 0, 1)
    assert not list(output.iterdir())
    assert not backend.clips
    assert source.read_bytes() == original


def test_technical_generation_is_independent_of_ai_settings(tmp_path: Path) -> None:
    source, output = tmp_path / "diagram.avi", tmp_path / "upscaled"
    _make_rle_movie(source)
    assert upscale_movies([source], output).retained == 1
    assert (
        upscale_movies([source], output, options=MovieUpscaleOptions(clip_frames=5)).retained == 1
    )


def test_direct_conversion_cannot_accidentally_upscale_a_technical_animation(
    tmp_path: Path,
) -> None:
    source, output = tmp_path / "keys.avi", tmp_path / "enlarged.avi"
    _make_rle_movie(source, colors={0: (3, 251, 3), 40: (3, 250, 3)})
    original = source.read_bytes()
    with pytest.raises(ValueError, match="retained at their original size"):
        convert(source, output, options=MovieUpscaleOptions())
    assert not output.exists()
    assert source.read_bytes() == original


def test_mixed_movie_batch_only_restores_cinematics(tmp_path: Path) -> None:
    diagram, cinematic, output = (
        tmp_path / "diagram.avi",
        tmp_path / "intro.avi",
        tmp_path / "output",
    )
    _make_rle_movie(diagram)
    _make_movie(cinematic, audio=False)
    report = upscale_movies([diagram, cinematic], output, RecordingBackend())
    assert (report.generated, report.retained) == (1, 1)
    assert (output / "intro.mkv").exists()
    assert not (output / "diagram.mkv").exists()


def test_retaining_original_does_not_delete_or_replace_previous_review_output(
    tmp_path: Path,
) -> None:
    source, output = tmp_path / "diagram.avi", tmp_path / "output"
    _make_rle_movie(source)
    output.mkdir()
    previous = output / "diagram.mkv"
    previous.write_bytes(b"previous review output, not disposable")
    report = upscale_movies([source], output)
    assert report.retained == 1
    assert previous.read_bytes() == b"previous review output, not disposable"
