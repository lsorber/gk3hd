"""Timestamp-aware cinematic interpolation without retiming audio or technical clips."""

from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING, Protocol

from PIL import ImageChops

from gk3hd.videos.shots import tagged_frames

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from PIL import Image

INTERPOLATION_RECIPE = "rife-4.25-fp32-flow-half-above-1080p-v1"
_ANCHOR_TOLERANCE = 0.001


class FrameInterpolator(Protocol):
    """Generate an intermediate picture without altering its two anchors."""

    def interpolate(self, left: Image.Image, right: Image.Image, time: float) -> Image.Image:
        """Return the picture at a fractional position between the anchors."""
        ...


def cinematic_rate(source_rate: Fraction) -> Fraction:
    """Smooth approximately 15 fps cinematics; preserve all other source clocks.

    Technical animations are excluded before this stage. The narrow rate band
    covers the source logo's rounded AVI clock without filename exceptions.
    """
    return Fraction(60) if Fraction(14) <= source_rate <= Fraction(16) else source_rate


def output_frames(count: int, source_rate: Fraction, target_rate: Fraction) -> int:
    """Keep the original duration to within half an output frame."""
    return round(count * target_rate / source_rate)


def interpolate_frames(
    frames: Iterable[Image.Image],
    backend: FrameInterpolator,
    *,
    source_rate: Fraction,
    count: int,
) -> Iterator[Image.Image]:
    """Stream 60 fps pictures with two anchors, respecting cuts and final holds."""
    target_rate = cinematic_rate(source_rate)
    total = output_frames(count, source_rate, target_rate)
    output_index = consumed = 0
    previous = None
    previous_shot = -1
    for index, (shot, current) in enumerate(tagged_frames(frames)):
        consumed += 1
        if previous is not None:
            static = ImageChops.difference(previous, current).getbbox() is None
            while output_index < total:
                position = output_index * source_rate / target_rate
                if position >= index:
                    break
                time = float(position - (index - 1))
                yield _between(
                    previous, current, time, backend, hold=static or shot != previous_shot
                )
                output_index += 1
        previous, previous_shot = current, shot
    if consumed != count or previous is None:
        msg = f"incomplete interpolation input: expected {count} frames, got {consumed}"
        raise ValueError(msg)
    while output_index < total:
        yield previous
        output_index += 1


def _between(
    left: Image.Image, right: Image.Image, time: float, backend: FrameInterpolator, *, hold: bool
) -> Image.Image:
    """Preserve anchors and cuts; infer only genuinely intermediate motion."""
    if time < _ANCHOR_TOLERANCE:
        return left
    if time > 1 - _ANCHOR_TOLERANCE:
        # AVI's clock rounding differs from 15 Hz by only 80 us over the logo.
        return right
    if hold:
        return left
    result = backend.interpolate(left, right, time)
    if result.size != left.size or result.mode != "RGB":
        msg = "interpolator changed frame dimensions or RGB format"
        raise ValueError(msg)
    return result
