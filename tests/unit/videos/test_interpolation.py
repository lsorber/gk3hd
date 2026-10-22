from fractions import Fraction

import numpy as np
import pytest
from PIL import Image, ImageDraw

from gk3hd.videos.interpolation import (
    INTERPOLATION_RECIPE,
    cinematic_rate,
    interpolate_frames,
    output_frames,
)
from gk3hd.videos.manifest import validate_generation


class LinearInterpolator:
    """Cheap deterministic stand-in to exercise timing, not AI quality."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def interpolate(self, left: Image.Image, right: Image.Image, time: float) -> Image.Image:
        self.calls.append(time)
        return Image.blend(left, right, time)


@pytest.mark.parametrize("rate", [Fraction(15), Fraction(1000000, 66667)])
def test_low_cadence_is_60fps_without_speeding_up_or_slowing_down(rate: Fraction) -> None:
    assert cinematic_rate(rate) == 60
    count = output_frames(240, rate, cinematic_rate(rate))
    assert count == 960
    assert abs(count / 60 - float(240 / rate)) < 1 / 120


@pytest.mark.parametrize(
    "rate", [Fraction(26570, 919), Fraction(6389, 215), Fraction(118200, 3937)]
)
def test_unusual_cinematic_rates_are_not_normalized(rate: Fraction) -> None:
    assert cinematic_rate(rate) == rate
    assert output_frames(100, rate, cinematic_rate(rate)) == 100


def test_quarter_frames_preserve_anchors_and_hold_the_final_frame() -> None:
    frames = []
    for position in (10, 14, 18):
        frame = Image.new("RGB", (64, 48))
        ImageDraw.Draw(frame).rectangle((position, 10, position + 8, 20), fill="white")
        frames.append(frame)
    backend = LinearInterpolator()
    result = list(interpolate_frames(frames, backend, source_rate=Fraction(15), count=3))
    assert len(result) == 12
    for before, after in zip(frames, result[::4], strict=True):
        np.testing.assert_array_equal(before, after)
    assert backend.calls == [0.25, 0.5, 0.75] * 2
    assert all(image is frames[-1] for image in result[-4:])


def test_hard_cuts_and_static_frames_are_not_morphed() -> None:
    frames = [Image.new("RGB", (64, 48), color) for color in ("black", "black", "white")]
    backend = LinearInterpolator()
    result = list(interpolate_frames(frames, backend, source_rate=Fraction(15), count=3))
    assert len(result) == 12
    assert not backend.calls
    assert all(image.getpixel((0, 0)) == (0, 0, 0) for image in result[:8])
    assert all(image.getpixel((0, 0)) == (255, 255, 255) for image in result[8:])


@pytest.mark.parametrize("count", [0, 1, 3])
def test_truncated_or_excess_input_is_not_published_as_complete(count: int) -> None:
    frames = [Image.new("RGB", (64, 48))] * 2
    with pytest.raises(ValueError, match="incomplete interpolation"):
        list(
            interpolate_frames(frames, LinearInterpolator(), source_rate=Fraction(15), count=count)
        )


@pytest.mark.parametrize("change", ["unrecorded", "speedup", "frames", "normal-rate"])
def test_changed_timing_requires_duration_preserving_interpolation(change: str) -> None:
    original = {
        "width": 640,
        "height": 480,
        "frames": 240,
        "rate": [1000000, 66667],
        "audio_rate": 22050,
        "audio_channels": 2,
    }
    generated = {**original, "width": 2560, "height": 1920, "frames": 960, "rate": [60, 1]}
    value = {
        "schema_version": 1,
        "recipe": "test",
        "codec": "libaom-av1",
        "source_media": original,
        "media": generated,
        "interpolation": {"recipe": INTERPOLATION_RECIPE, "rate": [60, 1]},
    }
    assert validate_generation(value) == value
    if change == "unrecorded":
        value.pop("interpolation")
    elif change == "speedup":
        generated["rate"] = [120, 1]
    elif change == "frames":
        generated["frames"] = 240
    else:
        original["rate"] = [30, 1]
    with pytest.raises(ValueError, match="timing"):
        validate_generation(value)
