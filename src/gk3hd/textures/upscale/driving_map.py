"""Compose GK3's opaque driving-map locations against one shared HD base.

Each ``DM_*`` location bitmap is a crop of ``DM_BASE`` with one location or
highlight painted into it. Upscaling those opaque crops independently makes
unchanged terrain disagree with the separately upscaled base and exposes every
rectangular boundary. This module enlarges the shipped pixel delta instead and
applies it to the matching crop of the one upscaled base. Authored location
artwork suppresses inferred terrain on that shared base, using the union of
both states so hovering never switches between two different detail levels.
Runtime layout fixes
place every overlay at that same origin, including three misaligned originals.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from PIL import Image

from gk3hd.driving_map import MAP_LOCATIONS

SCALE: Final = 4
BASE_NAME: Final = "DM_BASE.BMP"

# Exact terrain origins on DM_BASE's 640x480 grid. The runtime patch corrects
# the three original constructor anchors that disagree with these crops.
_ORIGINS: Final = {name: (x, y) for name, (x, y, _width, _height) in MAP_LOCATIONS.items()}


def _artwork_sources(source: Path) -> tuple[Path, ...]:
    """Read existing authored states, allowing partial extracted test folders."""
    return tuple(
        path
        for location in _ORIGINS
        for suffix in ("", "_UL")
        if (path := source.with_name(f"DM_{location}{suffix}.BMP")).is_file()
    )


def map_artwork_stamp(source: Path) -> str:
    """Bind the shared correction to all available original state artwork."""
    digest = hashlib.sha256(b"map-artwork-1")
    for path in _artwork_sources(source):
        digest.update(path.name.encode("ascii"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def restore_map_artwork(source: Path, generated: Image.Image) -> Image.Image:
    """Keep chosen AI terrain outside the shared authored foreground support."""
    import numpy as np  # noqa: PLC0415
    from scipy.ndimage import maximum_filter  # noqa: PLC0415

    with Image.open(source) as image:
        base = image.convert("RGB")
    if generated.size != (base.width * SCALE, base.height * SCALE):
        msg = f"{BASE_NAME}: upscaled dimensions are not exactly {SCALE}x"
        raise ValueError(msg)
    original = np.asarray(base, dtype=np.int16)
    support = np.zeros(original.shape[:2], dtype=np.float32)
    for path in _artwork_sources(source):
        x, y = driving_map_overlay_origin(path.name) or (0, 0)
        with Image.open(path) as image:
            art = np.asarray(image.convert("RGB"), dtype=np.int16)
        height, width = art.shape[:2]
        crop = original[y : y + height, x : x + width]
        if crop.shape != art.shape:
            msg = f"{path.name}: crop lies outside {BASE_NAME}"
            raise ValueError(msg)
        # Preserve weak glow proportionally, while actual foreground replaces
        # AI detail. One source-pixel dilation covers the interpolation support.
        amount = np.clip(np.max(np.abs(art - crop), axis=2) / 16.0, 0, 1)
        region = support[y : y + height, x : x + width]
        np.maximum(region, amount, out=region)
    support = maximum_filter(support, size=3)
    weight = np.clip(
        np.asarray(Image.fromarray(support).resize(generated.size, Image.Resampling.BICUBIC)),
        0,
        1,
    )
    smooth = np.asarray(base.resize(generated.size, Image.Resampling.BICUBIC), dtype=np.float32)
    high = np.asarray(generated.convert("RGB"), dtype=np.float32)
    corrected = np.clip(np.rint(high + (smooth - high) * weight[:, :, None]), 0, 255)
    result = Image.fromarray(corrected.astype(np.uint8))
    result.info.update(generated.info)
    return result


def driving_map_overlay_origin(name: str) -> tuple[int, int] | None:
    """Return one location's aligned placement in the 640x480 map."""
    stem = Path(name).stem.upper()
    if not stem.startswith("DM_") or stem == "DM_BASE":
        return None
    location = stem[3:].removesuffix("_UL")
    return _ORIGINS.get(location)


def compose_driving_map_overlay(
    overlay: Image.Image,
    base: Image.Image,
    base_upscaled: Image.Image,
    *,
    name: str,
    scale: int = SCALE,
) -> Image.Image:
    """Apply one faithfully enlarged source delta to the shared HD base crop."""
    # Route selection is part of base installation; only pixel generation
    # requires the optional array dependency.
    import numpy as np  # noqa: PLC0415 - optional upscale dependency.

    origin = driving_map_overlay_origin(name)
    if origin is None:
        msg = f"{name}: no driving-map overlay recipe exists"
        raise ValueError(msg)
    if scale != SCALE:
        msg = f"driving-map overlays support {SCALE}x composition, not {scale}x"
        raise ValueError(msg)

    source = np.asarray(overlay.convert("RGB"), dtype=np.int16)
    base_rgb = np.asarray(base.convert("RGB"), dtype=np.int16)
    hd_rgb = np.asarray(base_upscaled.convert("RGB"), dtype=np.int16)
    if hd_rgb.shape[:2] != (base_rgb.shape[0] * scale, base_rgb.shape[1] * scale):
        msg = f"{BASE_NAME}: upscaled dimensions are not exactly {scale}x"
        raise ValueError(msg)
    x, y = origin
    height, width = source.shape[:2]
    base_crop = base_rgb[y : y + height, x : x + width]
    if base_crop.shape != source.shape:
        msg = f"{name}: crop lies outside {BASE_NAME}"
        raise ValueError(msg)

    delta = source - base_crop
    enlarged_delta = np.stack(
        [
            np.asarray(
                Image.fromarray(delta[:, :, channel].astype(np.float32), mode="F").resize(
                    (width * scale, height * scale),
                    Image.Resampling.BICUBIC,
                ),
                dtype=np.float32,
            )
            for channel in range(3)
        ],
        axis=2,
    )
    hd_crop = hd_rgb[
        y * scale : (y + height) * scale,
        x * scale : (x + width) * scale,
    ].astype(np.float32)
    composed = np.clip(np.rint(hd_crop + enlarged_delta), 0, 255).astype(np.uint8)
    return Image.fromarray(composed, mode="RGB")
