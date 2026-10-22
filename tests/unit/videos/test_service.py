import json
from pathlib import Path

import pytest

from gk3hd.videos.service import MovieUpscaleOptions, upscale_movies
from tests.unit.videos.test_temporal import RecordingBackend
from tests.unit.videos.test_video import _make_movie


def test_repeated_generation_verifies_and_reuses_the_output(tmp_path: Path) -> None:
    source, output = tmp_path / "original.avi", tmp_path / "upscaled"
    _make_movie(source, audio=True)
    backend = RecordingBackend()
    report = upscale_movies([source], output, backend)
    assert (report.generated, report.skipped) == (1, 0)
    assert backend.clips
    backend.clips.clear()
    resumed = upscale_movies([source], output, backend)
    assert (resumed.generated, resumed.skipped) == (0, 1)
    assert not backend.clips


def test_an_unowned_output_is_never_overwritten(tmp_path: Path) -> None:
    source, output = tmp_path / "original.avi", tmp_path / "upscaled"
    _make_movie(source, audio=False)
    output.mkdir()
    destination = output / "original.mkv"
    destination.write_bytes(b"someone else's movie")
    with pytest.raises(ValueError, match="unowned"):
        upscale_movies([source], output, RecordingBackend())
    assert destination.read_bytes() == b"someone else's movie"


def test_recipe_update_regenerates_owned_outputs_instead_of_rejecting_them(tmp_path: Path) -> None:
    source, output = tmp_path / "original.avi", tmp_path / "upscaled"
    _make_movie(source, audio=True)
    upscale_movies([source], output, RecordingBackend())
    receipt = output / "original.mkv.json"
    previous = json.loads(receipt.read_bytes())
    previous["recipe"] = "previous-content-recipe"
    receipt.write_text(json.dumps(previous), encoding="utf-8")
    backend = RecordingBackend()
    report = upscale_movies([source], output, backend)
    assert (report.generated, report.skipped) == (1, 0)
    assert backend.clips
    assert json.loads(receipt.read_bytes())["recipe"] != previous["recipe"]


def test_mid_movie_failure_does_not_publish_a_partial_video(tmp_path: Path) -> None:
    source, output = tmp_path / "original.avi", tmp_path / "upscaled"
    _make_movie(source, audio=False)

    def fail(_name: str, _done: int, _total: int) -> None:
        message = "interrupted"
        raise RuntimeError(message)

    with pytest.raises(RuntimeError, match="interrupted"):
        upscale_movies([source], output, RecordingBackend(), progress=fail)
    assert not list(output.iterdir())


def test_changed_restoration_strength_regenerates_owned_outputs(tmp_path: Path) -> None:
    source, output = tmp_path / "original.avi", tmp_path / "upscaled"
    _make_movie(source, audio=False)
    upscale_movies([source], output, RecordingBackend())
    backend = RecordingBackend()
    options = MovieUpscaleOptions(restoration_strength=0.6)
    result = upscale_movies([source], output, backend, options=options)
    assert result.generated == 1
    assert backend.clips
    receipt = json.loads((output / "original.mkv.json").read_bytes())
    assert receipt["restoration_strength"] == 0.6
    assert upscale_movies([source], output, backend, options=options).skipped == 1


@pytest.mark.parametrize("strength", [-0.01, 1.01, float("nan"), float("inf")])
def test_invalid_restoration_strength_fails_before_generation(strength: float) -> None:
    with pytest.raises(ValueError, match="restoration_strength"):
        MovieUpscaleOptions(restoration_strength=strength)
