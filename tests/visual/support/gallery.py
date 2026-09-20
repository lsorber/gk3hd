"""Publish reviewed animations without a second lossy encoding generation."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def write_gallery_image(source: Path, destination: Path) -> None:
    """Copy an encoded comparison, preserving its quality, dimensions and timing."""
    if source.suffix.casefold() != ".webp":
        message = "gallery input must be an already encoded WebP comparison"
        raise ValueError(message)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
