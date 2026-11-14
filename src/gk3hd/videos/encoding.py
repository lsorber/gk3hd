"""Bounded-memory HEVC Main10 generation for desktop and headset playback.

Feed restored RGB frames directly to FFmpeg, without staging a raw movie.
The optional upscale extra supplies a portable FFmpeg executable.
Ten-bit 4:2:0 permits native Android hardware decoding; the registration-free
desktop player handles the same SDR BT.709/FLAC Matroska files.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import replace
from typing import TYPE_CHECKING

import av
from imageio_ffmpeg import get_ffmpeg_exe

from gk3hd.videos.backend import create_interpolator
from gk3hd.videos.catalog import DELIVERY_CODEC
from gk3hd.videos.interpolation import cinematic_rate, interpolate_frames, output_frames
from gk3hd.videos.temporal import restore_frames
from gk3hd.videos.video import MovieInfo, probe, restoration_pipeline

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from PIL import Image

    from gk3hd.videos.options import MovieUpscaleOptions
    from gk3hd.videos.temporal import ClipUpscaler

CRF = 16
_ERROR_LIMIT = 8192


def encoder_executable() -> str:
    """Find a capable local encoder without importing AI or changing the system."""
    executable = get_ffmpeg_exe()
    result = subprocess.run(  # noqa: S603 - resolved executable, no shell.
        [executable, "-hide_banner", "-h", f"encoder={DELIVERY_CODEC}"],
        capture_output=True,
        check=False,
        timeout=15,
    )
    if result.returncode or b"yuv420p10le" not in result.stdout:
        msg = "FFmpeg must include libx265 with yuv420p10le support"
        raise ValueError(msg)
    return executable


def _arguments(executable: str, source: Path, destination: Path, info: MovieInfo) -> list[str]:
    arguments = [
        executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pixel_format",
        "rgb24",
        "-video_size",
        f"{info.width * 4}x{info.height * 4}",
        "-framerate",
        str(info.rate),
        "-i",
        "pipe:0",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0?",
        "-map_metadata",
        "-1",
        "-c:v",
        DELIVERY_CODEC,
        "-preset",
        "medium",
        "-profile:v",
        "main10",
        # Set bitstream VUI as well as container colour metadata. Some FFmpeg/
        # libx265 builds otherwise omit the SDR primaries and transfer function.
        "-x265-params",
        (
            "pools=4:frame-threads=2:log-level=error:"
            "colorprim=bt709:transfer=bt709:colormatrix=bt709:range=limited"
        ),
        "-enc_time_base",
        str(1 / info.rate),
        # Matroska/FFmpeg may advertise a nearby conventional frame rate (e.g.
        # Sierra's 1000000/66667 becomes 15). Retain its precise source clock;
        # probe verifies every decoded timestamp against it before publication.
        "-metadata:s:v:0",
        f"GK3HD_FRAME_RATE={info.rate}",
    ]
    arguments += [
        "-crf",
        str(CRF),
        "-vf",
        "scale=in_range=pc:out_range=tv:out_color_matrix=bt709,format=yuv420p10le",
        "-colorspace",
        "bt709",
        "-color_range",
        "tv",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
    ]
    return [
        *arguments,
        "-c:a",
        "flac",
        "-fps_mode",
        "passthrough",
        "-f",
        "matroska",
        str(destination),
    ]


def _frames(
    source: Path, backend: ClipUpscaler | None, options: MovieUpscaleOptions
) -> Iterator[Image.Image]:
    with av.open(str(source)) as original:
        info = probe(source)
        decoded = (frame.to_image().convert("RGB") for frame in original.decode(video=0))
        restored = restore_frames(decoded, backend, options, info.rate)
        if options.restoration_strength > 0 and cinematic_rate(info.rate) != info.rate:
            yield from interpolate_frames(
                restored, create_interpolator(backend), source_rate=info.rate, count=info.frames
            )
        else:
            yield from restored


def convert_movie(
    source: Path,
    destination: Path,
    backend: ClipUpscaler | None,
    *,
    options: MovieUpscaleOptions,
    progress: Callable[[int, int], None] | None = None,
) -> MovieInfo:
    """Encode restored cinematics and original audio; never convert technical videos."""
    if restoration_pipeline(source) == "retain":
        msg = "technical animations are retained at their original size, without conversion"
        raise ValueError(msg)
    executable = encoder_executable()
    info = probe(source)
    rate = cinematic_rate(info.rate) if options.restoration_strength > 0 else info.rate
    output_info = replace(
        info,
        rate=rate,
        frames=output_frames(info.frames, info.rate, rate),
    )
    arguments = _arguments(executable, source, destination, output_info)
    count = 0
    with (
        tempfile.TemporaryFile() as errors,
        subprocess.Popen(  # noqa: S603 - argv, never a shell.
            arguments,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=errors,
        ) as process,
    ):
        if process.stdin is None:
            process.kill()
            process.wait()
            msg = "FFmpeg input pipe was not created"
            raise RuntimeError(msg)
        try:
            for image in _frames(source, backend, options):
                process.stdin.write(_frame_bytes(image, info))
                count += 1
                if progress is not None:
                    progress(count, output_info.frames)
            process.stdin.close()
            try:
                returncode = process.wait(timeout=120)
            except subprocess.TimeoutExpired as error:
                msg = f"FFmpeg timed out finalizing {source.name}"
                raise RuntimeError(msg) from error
        except BaseException:
            process.kill()
            process.wait()
            raise
        if returncode:
            errors.seek(0, 2)
            errors.seek(max(0, errors.tell() - _ERROR_LIMIT))
            detail = errors.read().decode("utf-8", errors="replace").strip()
            msg = f"HEVC encoding failed (exit {returncode}): {detail}"
            raise ValueError(msg)
    if not count or count != output_info.frames:
        msg = f"incomplete movie conversion: expected {output_info.frames} frames, got {count}"
        raise ValueError(msg)
    return MovieInfo(
        info.width * 4,
        info.height * 4,
        output_info.rate,
        count,
        info.audio_rate,
        info.audio_channels,
    )


def _frame_bytes(image: Image.Image, info: MovieInfo) -> bytes:
    if image.size != (info.width * 4, info.height * 4):
        msg = "restored movie frame is not exactly 4x the source dimensions"
        raise ValueError(msg)
    return image.convert("RGB").tobytes()
