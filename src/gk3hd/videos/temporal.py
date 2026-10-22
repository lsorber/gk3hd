"""Bounded, overlapping temporal inference without intermediate frame files."""

from __future__ import annotations

from itertools import groupby, islice
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from PIL import Image, ImageChops

from gk3hd.videos.shots import tagged_frames

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable, Sequence
    from fractions import Fraction

    from gk3hd.videos.options import MovieUpscaleOptions

TEMPORAL_STRIDE = 4
DEFAULT_CLIP_FRAMES = 5
_REFERENCE_PIXELS = 320 * 240
FRAMEWISE_RECIPE = "seedvr2-framewise-4x-lab-v1"
_MAX_FRAMEWISE_RATE = 16


def framewise_restoration(rate: Fraction) -> bool:
    """Avoid temporal-restoration trails when low-cadence motion spans too far.

    At 15 fps the VAE's four-frame temporal compression spans a quarter second.
    Restore those source pictures independently, then interpolate clean anchors.
    The decision uses the source clock, never a filename or encoded output rate.
    """
    return rate <= _MAX_FRAMEWISE_RATE


@runtime_checkable
class FrameUpscaler(Protocol):
    """The same spatial model without cross-frame VAE compression."""

    def upscale(self, image: Image.Image) -> Image.Image:
        """Return one independently restored 4x picture."""
        ...


def clip_frames_for_size(size: tuple[int, int], maximum: int) -> int:
    """Bound latent-frame area to the requested context at 320x240.

    Keep at least five jointly inferred frames even for larger sources. The
    choice depends only on source geometry and the requested maximum, not on
    transient free GPU memory, and is persisted in each generation receipt.
    """
    if min(size) <= 0 or maximum < DEFAULT_CLIP_FRAMES or (maximum - 1) % TEMPORAL_STRIDE:
        msg = "positive dimensions and a 4n+1 temporal maximum of at least five are required"
        raise ValueError(msg)
    maximum_latents = 1 + (maximum - 1) // TEMPORAL_STRIDE
    area_budget = maximum_latents * _REFERENCE_PIXELS // (size[0] * size[1])
    latent_frames = max(2, min(maximum_latents, area_budget))
    return 1 + (latent_frames - 1) * TEMPORAL_STRIDE


class ClipUpscaler(Protocol):
    """A backend that jointly restores a temporal clip at four times its size."""

    def upscale_clip(self, frames: Sequence[Image.Image]) -> list[Image.Image]:
        """Return exactly one 4x RGB frame per input frame, in temporal order."""
        ...


def restore_frames(
    frames: Iterable[Image.Image],
    backend: ClipUpscaler | None,
    options: MovieUpscaleOptions,
    source_rate: Fraction,
) -> Generator[Image.Image]:
    """Select a reproducible temporal policy before restoring source pictures."""
    if options.restoration_strength > 0 and framewise_restoration(source_rate):
        if not isinstance(backend, FrameUpscaler):
            msg = "low-cadence restoration requires an independent frame upscaler"
            raise ValueError(msg)
        yield from _upscale_framewise(frames, backend, options.restoration_strength)
    else:
        yield from upscale_frames(
            frames,
            backend,
            clip_frames=options.clip_frames,
            restoration_strength=options.restoration_strength,
        )


def upscale_frames(
    frames: Iterable[Image.Image],
    backend: ClipUpscaler | None,
    *,
    clip_frames: int = DEFAULT_CLIP_FRAMES,
    restoration_strength: float = 1.0,
    progress: Callable[[int], None] | None = None,
) -> Generator[Image.Image]:
    """Stream shot-separated 4n+1-frame clips with a shared boundary frame.

    Keep only a clip and its restored boundary in memory. Repeat padding is
    removed, so short clips and final tails retain every original frame once.
    The held boundary is blended only after the next clip in the same detected
    shot has been restored. Frames on opposite sides of a cut are never blended.
    Source anchoring happens once, after decoding and boundary blending, so the
    VAE cannot reinterpret source detail that the caller chose to retain.
    """
    if clip_frames < DEFAULT_CLIP_FRAMES or (clip_frames - 1) % TEMPORAL_STRIDE:
        msg = "clip_frames must be 4n+1 and at least five"
        raise ValueError(msg)
    if not 0 <= restoration_strength <= 1:
        msg = "restoration_strength must be between 0 and 1"
        raise ValueError(msg)
    completed = 0
    if restoration_strength == 0:
        for frame in frames:
            yield _source_anchor(frame, None, 0)
            completed += 1
            if progress is not None:
                progress(completed)
        return
    if backend is None:
        msg = "cinematic movie restoration requires a temporal AI backend"
        raise ValueError(msg)
    for _, shot in groupby(tagged_frames(frames), key=lambda item: item[0]):
        source = (frame for _, frame in shot)
        for restored in _upscale_shot(source, backend, clip_frames, restoration_strength):
            yield restored
            completed += 1
            if progress is not None:
                progress(completed)


def _upscale_framewise(
    frames: Iterable[Image.Image], backend: FrameUpscaler, strength: float
) -> Generator[Image.Image]:
    """Keep memory bounded and reuse exact holds without smoothing moving objects."""
    previous = restored = None
    for frame in frames:
        if previous is None or ImageChops.difference(previous, frame).getbbox() is not None:
            restored = backend.upscale(frame)
            _validate_result([restored], [frame])
            if restored.mode != "RGB":
                msg = "frame upscaler returned a non-RGB picture"
                raise ValueError(msg)
        yield _source_anchor(frame, restored, strength)
        previous = frame


def _upscale_shot(
    frames: Iterable[Image.Image],
    backend: ClipUpscaler,
    clip_frames: int,
    restoration_strength: float,
) -> Generator[Image.Image]:
    """Pad only with frames from this shot, including single-frame shots."""
    source = iter(frames)
    window: list[Image.Image] = []
    boundary: Image.Image | None = None
    while True:
        window.extend(islice(source, clip_frames - len(window)))
        if not window:
            return
        if len(window) == 1 and boundary is not None:
            yield _source_anchor(window[0], boundary, restoration_strength)
            return
        count = len(window)
        padded_count = max(
            DEFAULT_CLIP_FRAMES,
            ((count - 1 + TEMPORAL_STRIDE - 1) // TEMPORAL_STRIDE) * TEMPORAL_STRIDE + 1,
        )
        padded = [*window, *([window[-1]] * (padded_count - count))]
        restored = backend.upscale_clip(padded)
        _validate_result(restored, padded)
        if boundary is not None:
            restored[0] = Image.blend(boundary, restored[0], 0.5)
        final = count < clip_frames
        emitted = count if final else count - 1
        for original, picture in zip(window[:emitted], restored[:emitted], strict=True):
            yield _source_anchor(original, picture, restoration_strength)
        if final:
            return
        boundary = restored[count - 1]
        last_source = window[-1]
        window.clear()
        window.append(last_source)


def _source_anchor(
    source: Image.Image, restored: Image.Image | None, strength: float
) -> Image.Image:
    """Keep source-resolved expressions and artwork without a second AI stage."""
    if strength == 1 and restored is not None:
        return restored
    reference = source.convert("RGB").resize(
        (source.width * 4, source.height * 4), Image.Resampling.BICUBIC
    )
    return reference if restored is None else Image.blend(reference, restored, strength)


def _validate_result(restored: Sequence[Image.Image], source: Sequence[Image.Image]) -> None:
    if len(restored) != len(source) or any(
        frame.size != (source[0].width * 4, source[0].height * 4) for frame in restored
    ):
        msg = "temporal backend returned an invalid frame count or non-4x dimensions"
        raise ValueError(msg)
