"""Lazy access to the shared, vendored SeedVR2 inference implementation."""

from __future__ import annotations

import sys
import warnings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gk3hd.textures.progress import DownloadProgress
    from gk3hd.textures.upscale.seedvr2 import SeedVR2Upscaler
    from gk3hd.videos.interpolation import FrameInterpolator
    from gk3hd.videos.temporal import ClipUpscaler


def create_interpolator(backend: ClipUpscaler | None) -> FrameInterpolator:
    """Reuse the selected AI device and CLI-owned download progress."""
    from gk3hd.videos.rife import RifeInterpolator  # noqa: PLC0415 - optional AI dependencies.

    return RifeInterpolator(
        str(getattr(backend, "device", "auto")),
        download_progress=getattr(backend, "download_progress", None),
    )


def create_backend(
    device: str,
    progress: DownloadProgress | None = None,
) -> SeedVR2Upscaler:
    """Import optional dependencies only when local movie inference is requested."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="CUDA is not available or torch_xla is imported")
        from gk3hd.textures.upscale.seedvr2 import (  # noqa: PLC0415 - optional AI dependencies.
            SeedVR2Config,
            SeedVR2Upscaler,
        )
    return SeedVR2Upscaler(
        SeedVR2Config(
            device=device,
            vae_spatial_tile_size=256,
            vae_spatial_tile_overlap=32,
            release_phase_memory=True,
            gpu_memory_fraction=0.85 if sys.platform == "win32" else None,
            offload_inactive_models=True,
            edge_antialias_strength=0,
        ),
        download_progress=progress,
    )
