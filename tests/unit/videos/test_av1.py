"""One portable encoding with faithful color, audio, timing and technical pixels."""

import json
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pytest
from PIL import Image

from gk3hd.videos.interpolation import cinematic_rate, output_frames
from gk3hd.videos.manifest import GENERATION_RECIPE
from gk3hd.videos.service import upscale_movies
from gk3hd.videos.video import convert, probe
from tests.unit.videos.test_interpolation import LinearInterpolator
from tests.unit.videos.test_temporal import RecordingBackend
from tests.unit.videos.test_video import _make_movie


@pytest.mark.parametrize("audio", [False, True])
@pytest.mark.parametrize("rate", [Fraction(30000, 1001), Fraction(1000000, 66667)])
def test_av1_round_trip_preserves_cadence_audio_and_color(
    tmp_path: Path, audio: bool, rate: Fraction, interpolator: LinearInterpolator
) -> None:
    source, destination = tmp_path / "original.avi", tmp_path / "upscaled.mkv"
    _make_movie(source, audio=audio, rate=rate)
    report = convert(source, destination, RecordingBackend())
    assert probe(destination) == report
    assert report.frames == output_frames(7, rate, cinematic_rate(rate))
    assert report.rate == cinematic_rate(rate)
    assert all(0 < time < 1 for time in interpolator.calls)
    with av.open(str(destination)) as container:
        video = container.streams.video[0]
        assert video.codec_context.name in {"av1", "libdav1d"}
        assert video.codec_context.format is not None
        assert video.codec_context.format.name == "yuv444p10le"
        frames = list(container.decode(video=0))
    with av.open(str(source)) as container:
        originals = list(container.decode(video=0))
    anchors = frames[::4] if report.rate != rate else frames
    for index, (before, after) in enumerate(zip(originals, anchors, strict=True)):
        expected = before.to_image().resize(after.to_image().size, Image.Resampling.BICUBIC)
        delta = np.abs(
            np.asarray(expected, dtype=float) - np.asarray(after.to_image(), dtype=float)
        )
        assert delta.mean() < 2
        assert abs(after.time - index / rate) <= 0.001
    if audio:
        with av.open(str(source)) as container:
            expected_audio = np.concatenate(
                [f.to_ndarray() for f in container.decode(audio=0)], axis=1
            )
        with av.open(str(destination)) as container:
            assert container.streams.audio[0].codec_context.name == "flac"
            actual_audio = np.concatenate(
                [f.to_ndarray() for f in container.decode(audio=0)], axis=1
            )
        np.testing.assert_array_equal(actual_audio, expected_audio)


def test_old_temporal_output_is_not_reused_for_low_cadence_motion(
    tmp_path: Path, interpolator: LinearInterpolator
) -> None:
    del interpolator
    source, output = tmp_path / "logo.avi", tmp_path / "upscaled"
    _make_movie(source, audio=False, rate=Fraction(15))
    backend = RecordingBackend()
    assert upscale_movies([source], output, backend).generated == 1
    state = output / "logo.mkv.json"
    receipt = json.loads(state.read_bytes())
    receipt["recipe"] = GENERATION_RECIPE
    receipt["clip_frames"] = 5
    state.write_text(json.dumps(receipt))
    backend.clips.clear()
    assert upscale_movies([source], output, backend).generated == 1
    assert backend.clips
    backend.clips.clear()
    assert upscale_movies([source], output, backend).skipped == 1
    assert not backend.clips


@pytest.mark.parametrize("clock", ["15/2", "0", "-1", "not-a-rate", "1/0", "9" * 65])
def test_source_clock_metadata_cannot_hide_invalid_or_changed_timing(
    tmp_path: Path, clock: str, interpolator: LinearInterpolator
) -> None:
    source, good, bad = tmp_path / "source.avi", tmp_path / "good.mkv", tmp_path / "bad.mkv"
    _make_movie(source, audio=False, rate=Fraction(1000000, 66667))
    convert(source, good, RecordingBackend())
    assert interpolator.calls
    with av.open(str(good)) as original, av.open(str(bad), "w") as output:
        video = output.add_stream_from_template(original.streams.video[0], opaque=True)
        video.metadata["GK3HD_FRAME_RATE"] = clock
        for packet in original.demux(video=0):
            if packet.size:
                packet.stream = video
                output.mux(packet)
    with pytest.raises(ValueError, match=r"source frame-rate|source clock"):
        probe(bad)


def test_sierra_like_movie_preserves_its_full_duration_and_stereo_audio(
    tmp_path: Path, interpolator: LinearInterpolator
) -> None:
    source, output = tmp_path / "source.avi", tmp_path / "upscaled"
    generated = output / "source.mkv"
    rate = Fraction(1000000, 66667)
    with av.open(str(source), "w") as container:
        video = container.add_stream("ffv1", rate=rate)
        video.width, video.height, video.pix_fmt = 16, 12, "yuv444p"
        audio = container.add_stream("pcm_s16le", rate=22050)
        audio.layout = "stereo"
        for index in range(240):
            frame = av.VideoFrame.from_image(Image.new("RGB", (16, 12), (40, 60, 100)))
            frame.pts, frame.time_base = index, 1 / rate
            container.mux(video.encode(frame))
            samples = np.arange(1470 * 2, dtype=np.int16)[None, :]
            sample = av.AudioFrame.from_ndarray(samples, format="s16", layout="stereo")
            sample.sample_rate = 22050
            sample.pts, sample.time_base = index * 1470, Fraction(1, 22050)
            container.mux(audio.encode(sample))
        container.mux(video.encode(None))
        container.mux(audio.encode(None))
    generation = upscale_movies([source], output, RecordingBackend())
    assert generation.generated == 1
    assert (output / "source.mkv.json").is_file()
    report = probe(generated)
    assert not interpolator.calls  # A static film needs no invented motion.
    assert report.rate == 60
    assert report.frames == 960
    assert report.audio_rate == 22050
    assert report.audio_channels == 2
    with av.open(str(source)) as original, av.open(str(generated)) as restored:
        expected = np.concatenate([f.to_ndarray() for f in original.decode(audio=0)], axis=1)
        actual = np.concatenate([f.to_ndarray() for f in restored.decode(audio=0)], axis=1)
    np.testing.assert_array_equal(actual, expected)
