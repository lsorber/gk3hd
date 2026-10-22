"""Portable movie IO and verification, independent of system codec registrations.

AV1/Matroska replacements use the private player, without changing original media.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
from typing import TYPE_CHECKING

import av

from gk3hd.videos.options import MovieUpscaleOptions

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from gk3hd.videos.temporal import ClipUpscaler

_MAX_RATE_METADATA_LENGTH = 64


@dataclass(frozen=True, slots=True)
class MovieInfo:
    """Exact media properties used to verify a generated replacement."""

    width: int
    height: int
    rate: Fraction
    frames: int
    audio_rate: int | None
    audio_channels: int


def _info(container: av.container.InputContainer) -> MovieInfo:
    if len(container.streams.video) != 1 or len(container.streams.audio) > 1:
        msg = "expected one video stream and at most one audio stream"
        raise ValueError(msg)
    video = container.streams.video[0]
    rate = video.average_rate or video.base_rate or video.guessed_rate
    source_rate = video.metadata.get("GK3HD_FRAME_RATE")
    if source_rate is not None:
        rate = _source_rate(source_rate)
    if rate is None or rate <= 0 or video.width <= 0 or video.height <= 0:
        msg = "movie has invalid dimensions or an unknown frame rate"
        raise ValueError(msg)
    audio = container.streams.audio[0] if container.streams.audio else None
    frames = video.frames
    if not frames and video.duration is not None and video.time_base is not None:
        duration_frames = Fraction(video.duration) * video.time_base * rate
        if duration_frames.denominator == 1:
            frames = duration_frames.numerator
    return MovieInfo(
        video.width,
        video.height,
        Fraction(rate.numerator, rate.denominator),
        frames,
        audio.codec_context.sample_rate if audio else None,
        audio.codec_context.channels if audio else 0,
    )


def probe(path: Path) -> MovieInfo:
    """Read media properties, verifying tagged source clocks against decoded frames."""
    with av.open(str(path)) as container:
        info = _info(container)
        if "GK3HD_FRAME_RATE" in container.streams.video[0].metadata:
            info = replace(info, frames=_verify_clock(container, info.rate))
        elif not info.frames:
            info = replace(info, frames=sum(1 for _ in container.decode(video=0)))
        return info


def _source_rate(value: str) -> Fraction:
    """Reject invalid clock metadata rather than silently trusting arbitrary tags."""
    try:
        rate = Fraction(value) if len(value) <= _MAX_RATE_METADATA_LENGTH else Fraction(0)
    except (ValueError, ZeroDivisionError) as exc:
        msg = "invalid source frame-rate metadata"
        raise ValueError(msg) from exc
    if rate <= 0:
        msg = "invalid source frame-rate metadata"
        raise ValueError(msg)
    return rate


def _verify_clock(container: av.container.InputContainer, rate: Fraction) -> int:
    """Allow only timestamp quantization, never dropped frames or accumulated drift."""
    count = 0
    previous = None
    for frame in container.decode(video=0):
        if frame.pts is None or frame.time_base is None:
            msg = "encoded movie is missing presentation timestamps"
            raise ValueError(msg)
        timestamp = Fraction(frame.pts) * frame.time_base
        if abs(timestamp - count / rate) > frame.time_base or (
            previous is not None and timestamp <= previous
        ):
            msg = f"encoded movie timestamp differs from its source clock at frame {count}"
            raise ValueError(msg)
        previous = timestamp
        count += 1
    return count


def restoration_pipeline(path: Path) -> str:
    """Lossless SIDNEY MSRLE animations contain technical detail, not CGI noise."""
    with av.open(str(path)) as container:
        return _pipeline(container)


def _pipeline(container: av.container.InputContainer) -> str:
    return "retain" if container.streams.video[0].codec_context.name == "msrle" else "seedvr2"


def convert(
    source: Path,
    destination: Path,
    backend: ClipUpscaler | None = None,
    *,
    options: MovieUpscaleOptions | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> MovieInfo:
    """Jointly restore video while preserving original audio losslessly."""
    options = options or MovieUpscaleOptions()
    if source.resolve() == destination.resolve():
        msg = "the output must not replace the original movie"
        raise ValueError(msg)
    if restoration_pipeline(source) == "retain":
        msg = "technical animations are retained at their original size, without conversion"
        raise ValueError(msg)
    from gk3hd.videos.av1 import convert_av1  # noqa: PLC0415 - optional encoder process.

    return convert_av1(source, destination, backend, options=options, progress=progress)
