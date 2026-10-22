"""Bounded source-frame cut detection before temporal inference."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import ImageChops, ImageStat

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from PIL import Image

# Mean RGB change on a small thumbnail, in the original 0..255 range.
# The difference-of-differences suppresses sustained camera/object motion.
# Eight catches the reviewed dark cut (10.9), unlike a 10% brightness threshold.
_CUT_SCORE = 8.0
_FLASH_CHANGE = 64.0
_THUMBNAIL_SIZE = (64, 48)


def tagged_frames(frames: Iterable[Image.Image]) -> Iterator[tuple[int, Image.Image]]:
    """Tag likely continuous shots without dropping or retiming any frames.

    This is a conservative cut heuristic, not semantic scene understanding.
    Very large changes also split both sides of a single-frame flash, where
    the difference-of-differences alone would miss the second boundary.
    Only one tiny previous thumbnail is retained. Detection never alters pixels.
    """
    previous = None
    previous_difference = 0.0
    shot = 0
    for frame in frames:
        thumbnail = frame.convert("RGB").resize(_THUMBNAIL_SIZE)
        if previous is not None:
            difference = sum(ImageStat.Stat(ImageChops.difference(thumbnail, previous)).mean) / 3
            score = min(difference, abs(difference - previous_difference))
            if score >= _CUT_SCORE or difference >= _FLASH_CHANGE:
                shot += 1
            previous_difference = difference
        yield shot, frame
        previous = thumbnail
