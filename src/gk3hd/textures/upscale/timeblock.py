"""Reconstruct time-transition lettering over one shared upscaled background.

The shipped animation frames are opaque background crops, not transparent text.
Their minimum-coverage foreground is recovered exactly from the original crop,
then resampled in premultiplied form. Unchanged landscape remains identical to
the generated background; opaque white lettering stays white even where AI has
changed the landscape. No model invents or replaces the original characters.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass(frozen=True, slots=True)
class TimeblockOverlay:
    """One native text sequence's background crop and frame range."""

    origin: tuple[int, int]
    size: tuple[int, int]
    frames: int


# Origins agree with TimeBlockLayer's authored placement and exact background
# matches in the first reveal frame. Each sequence retains one crop throughout.
_RECIPES = {
    "D102P": TimeblockOverlay((8, 354), (383, 63), 13),
    "D104P": TimeblockOverlay((14, 347), (366, 70), 13),
    "D106P": TimeblockOverlay((14, 347), (376, 69), 14),
    "D110A": TimeblockOverlay((14, 347), (399, 69), 15),
    "D112P": TimeblockOverlay((14, 347), (398, 70), 14),
    "D202A": TimeblockOverlay((14, 347), (251, 69), 9),
    "D202P": TimeblockOverlay((14, 347), (359, 70), 13),
    "D205P": TimeblockOverlay((14, 346), (382, 70), 14),
    "D207A": TimeblockOverlay((14, 347), (362, 69), 14),
    "D210A": TimeblockOverlay((14, 347), (398, 68), 15),
    "D212P": TimeblockOverlay((14, 346), (374, 70), 14),
    "D303P": TimeblockOverlay((14, 347), (357, 69), 13),
    "D306P": TimeblockOverlay((14, 347), (365, 70), 13),
    "D307A": TimeblockOverlay((14, 347), (369, 69), 14),
    "D309P": TimeblockOverlay((14, 347), (433, 69), 18),
    "D310A": TimeblockOverlay((14, 347), (397, 70), 15),
    "D312P": TimeblockOverlay((13, 347), (373, 69), 13),
}
_BACKGROUND_SIZE = (640, 480)
BACKGROUND_NAMES = frozenset(f"TBT{family[1:]}.BMP" for family in _RECIPES)
_SCALE = 4
_FRAME_DIGITS = 2


def timeblock_overlay_recipe(name: str) -> TimeblockOverlay | None:
    """Recognize only a shipped time-transition frame, not arbitrary D* art."""
    family, separator, frame = Path(name).stem.upper().partition("_")
    recipe = _RECIPES.get(family)
    if (
        recipe is None
        or not separator
        or len(frame) != _FRAME_DIGITS
        or not frame.isascii()
        or not frame.isdigit()
    ):
        return None
    return recipe if 1 <= int(frame) <= recipe.frames else None


def timeblock_background_name(name: str) -> str:
    """Return the matching native TBT background for a validated frame name."""
    if timeblock_overlay_recipe(name) is None:
        msg = f"{name}: no time-transition overlay recipe exists"
        raise ValueError(msg)
    return f"TBT{Path(name).stem.upper().split('_')[0][1:]}.BMP"


def compose_timeblock_overlay(
    overlay: Image.Image, base: Image.Image, base_upscaled: Image.Image, *, name: str
) -> Image.Image:
    """Resample the exact source lettering/glow against the shared dense crop."""
    import numpy as np  # noqa: PLC0415 - generation needs the optional extra.

    recipe = timeblock_overlay_recipe(name)
    if recipe is None:
        msg = f"{name}: no time-transition overlay recipe exists"
        raise ValueError(msg)
    background_size = (
        (640, 481) if timeblock_background_name(name) == "TBT306P.BMP" else _BACKGROUND_SIZE
    )
    if overlay.size != recipe.size or base.size != background_size:
        msg = f"{name}: source dimensions do not match the native time-transition recipe"
        raise ValueError(msg)
    if base_upscaled.size != tuple(value * _SCALE for value in base.size):
        msg = f"{name}: background must be exactly {_SCALE}x"
        raise ValueError(msg)
    x, y = recipe.origin
    width, height = recipe.size
    crop = (x, y, x + width, y + height)
    background = np.asarray(base.convert("RGB").crop(crop), dtype=np.float32)
    foreground = np.asarray(overlay.convert("RGB"), dtype=np.float32)
    delta = foreground - background
    # Per-channel coverage required to represent each change with a foreground
    # in [0,255]. The maximum satisfies all three channels; zero means no change.
    coverage = np.max(
        np.where(
            delta >= 0,
            delta / np.maximum(255 - background, 1),
            -delta / np.maximum(background, 1),
        ),
        axis=2,
    )
    premultiplied = foreground - (1 - coverage[:, :, None]) * background
    target_size = (width * _SCALE, height * _SCALE)
    coverage_hd = np.clip(
        np.asarray(Image.fromarray(coverage).resize(target_size, Image.Resampling.BICUBIC)),
        0,
        1,
    )
    foreground_hd = np.stack(
        [
            np.asarray(
                Image.fromarray(premultiplied[:, :, channel]).resize(
                    target_size, Image.Resampling.BICUBIC
                )
            )
            for channel in range(3)
        ],
        axis=2,
    )
    # Bicubic overshoot must not produce negative light or exceed the coverage.
    foreground_hd = np.clip(foreground_hd, 0, 255 * coverage_hd[:, :, None])
    background_hd = np.asarray(
        base_upscaled.convert("RGB").crop(
            (x * _SCALE, y * _SCALE, (x + width) * _SCALE, (y + height) * _SCALE)
        ),
        dtype=np.float32,
    )
    result = np.clip(
        np.rint(foreground_hd + (1 - coverage_hd[:, :, None]) * background_hd), 0, 255
    ).astype(np.uint8)
    return Image.fromarray(result)
