"""Frame-isolated reconstruction for verified shaded software cursors."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image

# Shared by analysis, reconstruction, installation and the native density matcher.
# Static shaded art uses the same ordinary color-key renderer as C_PLAYACTION;
# its one-frame layout retains each original CUR hotspot (or the native default).
# The wait animation uses a paired scalar-opacity strip and native additive
# blending; its two layers must always have matching frame layouts and density.
CURSOR_ART_FRAMES = {
    "C_PLAYACTION.BMP": (40, 40, 30),
    "C_WAIT.BMP": (40, 40, 15),
    "C_BELL.BMP": (32, 25, 1),
    "C_INSPECT.BMP": (32, 32, 1),
    "C_LOOK.BMP": (32, 32, 1),
    "C_SIT.BMP": (21, 32, 1),
    "C_TALK.BMP": (32, 24, 1),
    "C_THINK.BMP": (32, 32, 1),
    "C_UNINSPECT.BMP": (32, 32, 1),
    "C_WALK.BMP": (25, 33, 1),
    "C_WALLET.BMP": (30, 22, 1),
}
CURSOR_OPACITY_PAIRS = {"C_WAIT.BMP": "C_WAIT_ALPHA.BMP"}
CURSOR_OPACITY_FRAMES = {
    opacity: CURSOR_ART_FRAMES[color] for color, opacity in CURSOR_OPACITY_PAIRS.items()
}
CURSOR_OPACITY_SIZES = {
    name: (width * frames, height)
    for name, (width, height, frames) in CURSOR_OPACITY_FRAMES.items()
}
CURSOR_ART_SIZES = {
    name: (width * frames, height) for name, (width, height, frames) in CURSOR_ART_FRAMES.items()
}


def regenerate_cursor_art(image: Image, name: str) -> Image:
    """Enlarge each frame independently, preserving native samples and the key.

    Interpolating the whole strip would let one frame bleed into its neighbor.
    Authored frame count, timing and hotspot stay in the original CUR resource;
    the renderer separates logical frame metrics from these dense pixels.
    """
    from PIL import Image as PillowImage  # noqa: PLC0415

    from gk3hd.textures.upscale.pipeline import (  # noqa: PLC0415
        resample_keyed_art,
        resample_monotone_art,
    )

    normalized = name.upper()
    layouts = CURSOR_ART_FRAMES | CURSOR_OPACITY_FRAMES
    sizes = CURSOR_ART_SIZES | CURSOR_OPACITY_SIZES
    if sizes.get(normalized) != image.size:
        msg = f"{name}: no verified cursor frame layout for {image.size}"
        raise ValueError(msg)
    width, height, frames = layouts[normalized]
    opacity = normalized in CURSOR_OPACITY_FRAMES
    result = PillowImage.new("L" if opacity else "RGB", (image.width * 4, image.height * 4))
    for frame in range(frames):
        original = image.crop((frame * width, 0, (frame + 1) * width, height))
        enlarged = (
            resample_monotone_art(original.convert("RGB")).convert("L")
            if opacity
            else resample_keyed_art(original, scale=4, sample_aligned=True)
        )
        result.paste(enlarged, (frame * width * 4, 0))
    return result
