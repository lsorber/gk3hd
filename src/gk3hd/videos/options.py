"""Validated restoration and playback choices shared by generation and encoding."""

from __future__ import annotations

from dataclasses import dataclass

from gk3hd.videos.temporal import DEFAULT_CLIP_FRAMES, TEMPORAL_STRIDE


@dataclass(frozen=True, slots=True)
class MovieUpscaleOptions:
    """Explicit quality choices persisted with every generated movie."""

    clip_frames: int = 17
    restoration_strength: float = 1.0

    def __post_init__(self) -> None:
        """Reject invalid recipes before a decoder or model allocates memory."""
        if not 0.0 <= self.restoration_strength <= 1.0:
            msg = "restoration_strength must be between 0 and 1"
            raise ValueError(msg)
        if self.clip_frames < DEFAULT_CLIP_FRAMES or (self.clip_frames - 1) % TEMPORAL_STRIDE:
            msg = "clip_frames must be 4n+1 and at least five"
            raise ValueError(msg)
