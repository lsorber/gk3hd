"""Upscale SIDNEY's adjoining frame and postcard pieces as one RGB image."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING
from uuid import uuid4

from PIL import Image

from gk3hd.textures.flat import actual_files

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from gk3hd.textures.upscale.pipeline import ColorUpscaler

FRAME_REGIONS = {
    "S_SID_BKGD1024_TOP_A.BMP": (0, 0, 1024, 144),
    "S_SID_BKGD1024_BOTTOM_A.BMP": (0, 624, 1024, 768),
    "S_SID_BKGD1024_LEFT_A.BMP": (0, 144, 192, 624),
    "S_SID_BKGD1024_RIGHT_A.BMP": (832, 144, 1024, 624),
    # The postcard protrudes 13 pixels into the display. Its remaining pixels
    # belong to the left/bottom frame; independent inference splits the photo.
    "S_SID_BKGD800_LAMA_A.BMP": (192, 611, 366, 624),
}
FRAME_STAMP = "gk3hd.sidney-frame"
FRAME_BATCH = "gk3hd.sidney-frame-batch"


def frame_fingerprint(directory: Path) -> str:
    """Bind every piece to the same source family and joined-inference recipe."""
    from gk3hd.textures.upscale.generation import GENERATION_REVISION  # noqa: PLC0415

    paths = actual_files(directory, suffix=".bmp")
    digest = hashlib.sha256(b"sidney-frame-joined-rgb-v2-postcard")
    digest.update(str(GENERATION_REVISION).encode("ascii"))
    for name in FRAME_REGIONS:
        path = paths.get(name.casefold())
        if path is None:
            msg = f"SIDNEY frame requires all five source pieces; missing {name}"
            raise ValueError(msg)
        digest.update(name.encode("ascii"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def upscale_frame(directory: Path, upscaler: ColorUpscaler | None) -> dict[str, Image.Image]:
    """Join before inference and crop afterward, sharing pixels across every seam.

    The central 640x480 region is SIDNEY's separate display, except for the
    postcard protrusion. Black supplies the remaining boundary context and is
    never exported. No extra image or cache is placed in the pack's PNG directory.
    """
    from gk3hd.textures.model import TextureFeatures  # noqa: PLC0415
    from gk3hd.textures.upscale.pipeline import upscale_texture  # noqa: PLC0415

    fingerprint = frame_fingerprint(directory)
    paths = actual_files(directory, suffix=".bmp")
    joined = Image.new("RGB", (1024, 768))
    for name, (left, top, right, bottom) in FRAME_REGIONS.items():
        with Image.open(paths[name.casefold()]) as piece:
            if piece.size != (right - left, bottom - top):
                msg = f"unexpected SIDNEY frame source dimensions: {name}: {piece.size}"
                raise ValueError(msg)
            joined.paste(piece.convert("RGB"), (left, top))
    dense = upscale_texture(joined, TextureFeatures(name="SIDNEY_FRAME"), upscaler=upscaler)
    if frame_fingerprint(directory) != fingerprint:
        msg = "SIDNEY frame source changed during upscaling; rerun with a stable source folder"
        raise ValueError(msg)
    batch = uuid4().hex
    result = {}
    for name, (left, top, right, bottom) in FRAME_REGIONS.items():
        piece = dense.crop((left * 4, top * 4, right * 4, bottom * 4))
        piece.info[FRAME_STAMP] = fingerprint
        piece.info[FRAME_BATCH] = batch
        result[name] = piece
    return result


def is_current_frame(source: Path, destination: Path) -> bool:
    """Reject independent inference and results from changed companion sources."""
    with Image.open(destination) as candidate:
        return candidate.info.get(FRAME_STAMP) == frame_fingerprint(source.parent)


def has_coherent_frame_outputs(paths: Mapping[str, Path]) -> bool:
    """Detect missing pieces or interrupted writes mixing distinct AI runs."""
    batches = set()
    for name in FRAME_REGIONS:
        path = paths.get(f"{name[:-4]}.png".casefold())
        if path is None:
            return False
        with Image.open(path) as image:
            batch = image.info.get(FRAME_BATCH)
        if not isinstance(batch, str) or not batch:
            return False
        batches.add(batch)
    return len(batches) == 1
