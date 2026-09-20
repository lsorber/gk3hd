"""Render compact still and animated comparisons from visual captures."""

from __future__ import annotations

import math
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import TYPE_CHECKING, Final

from PIL import Image, ImageDraw, ImageFont

from tests.visual.support.runs import merge_captures

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from concurrent.futures import Future
    from pathlib import Path

    from tests.visual.support.saves import SaveGame

_THUMBNAIL_HEIGHT: Final = 360
_LABEL_HEIGHT: Final = 34
_ANIMATION_DURATION_MS: Final = 900
_WEBP_MAX_DIMENSION: Final = 16_383
_MAX_PENDING_FRAMES: Final = 2
_MAX_PENDING_ANIMATIONS: Final = 4
_WEBP_QUALITY: Final = 95


@contextmanager
def frame_writer() -> Iterator[Callable[[Image.Image, Path], None]]:
    """Encode captures off the input path, with bounded memory and joined failures."""
    pending: deque[Future[None]] = deque()
    with ThreadPoolExecutor(max_workers=_MAX_PENDING_FRAMES) as executor:

        def submit(frame: Image.Image, path: Path) -> None:
            if len(pending) >= _MAX_PENDING_FRAMES:
                pending.popleft().result()
            pending.append(executor.submit(frame.save, path, format="PNG", compress_level=1))

        yield submit
        for future in pending:
            future.result()


def write_comparisons(
    captures: tuple[tuple[SaveGame, Path, Path], ...],
    *,
    output: Path,
) -> tuple[Path, tuple[Path, ...]]:
    """Update the combined contact sheet and animations without losing the other suite."""
    output.mkdir(parents=True, exist_ok=True)
    updated = {save.output_stem.casefold() for save, _reference, _current in captures}
    captures = merge_captures(captures, output=output)
    rows: list[Image.Image] = []
    animations: list[Path] = []
    font = ImageFont.load_default(size=18)
    pending: deque[Future[None]] = deque()
    with ThreadPoolExecutor(max_workers=_MAX_PENDING_ANIMATIONS) as executor:
        for save, reference_path, current_path in captures:
            # Bound both encoder memory and outstanding work; surface failures
            # before accepting more frames instead of silently losing a worker.
            if len(pending) >= _MAX_PENDING_ANIMATIONS:
                pending.popleft().result()
            with Image.open(reference_path) as source:
                reference = source.convert("RGB")
            with Image.open(current_path) as source:
                current = source.convert("RGB")
            reference_frame, current_frame = _comparable_frames(reference, current)
            animation = output / f"{save.output_stem}.webp"
            if save.output_stem.casefold() in updated or not animation.is_file():
                pending.append(
                    executor.submit(_write_animation, reference_frame, current_frame, animation)
                )
            animations.append(animation)
            rows.append(_comparison_row(save, reference_frame, current_frame, font=font))
        for future in pending:
            future.result()

    row_width = max(row.width for row in rows)
    row_height = max(row.height for row in rows)
    max_rows = _WEBP_MAX_DIMENSION // row_height
    columns = math.ceil(len(rows) / max_rows)
    grid_rows = math.ceil(len(rows) / columns)
    width = row_width * columns
    height = row_height * grid_rows
    if width > _WEBP_MAX_DIMENSION:
        msg = f"visual matrix requires {width} pixels of WebP width"
        raise ValueError(msg)
    sheet = Image.new("RGB", (width, height), "black")
    for index, row in enumerate(rows):
        column = index % columns
        grid_row = index // columns
        sheet.paste(row, (column * row_width, grid_row * row_height))
    sheet_path = output / "visual-matrix.webp"
    sheet.save(sheet_path, format="WEBP", quality=_WEBP_QUALITY, method=6)
    return sheet_path, tuple(animations)


def _write_animation(reference: Image.Image, current: Image.Image, path: Path) -> None:
    """Keep full-size alternating frames with high-quality lossy compression."""
    reference.save(
        path,
        format="WEBP",
        save_all=True,
        append_images=[current],
        duration=[_ANIMATION_DURATION_MS, _ANIMATION_DURATION_MS],
        loop=0,
        lossless=False,
        quality=_WEBP_QUALITY,
        allow_mixed=False,
        method=6,
    )


def _comparable_frames(
    reference: Image.Image, current: Image.Image
) -> tuple[Image.Image, Image.Image]:
    # Keep every HD pixel. Enlarge the reference with nearest-neighbor so its
    # original pixel colors remain intact, rather than downsampling the HD image.
    height = max(reference.height, current.height)
    reference_width = round(reference.width * height / reference.height)
    current_width = round(current.width * height / current.height)
    canvas_width = max(reference_width, current_width)
    reference_frame = Image.new("RGB", (canvas_width, height), "black")
    reference_frame.paste(
        reference.resize((reference_width, height), Image.Resampling.NEAREST),
        ((canvas_width - reference_width) // 2, 0),
    )
    current_frame = current.resize((current_width, height), Image.Resampling.NEAREST)
    if current_width == canvas_width:
        return reference_frame, current_frame
    current_canvas = Image.new("RGB", reference_frame.size, "black")
    current_canvas.paste(current_frame, ((canvas_width - current_width) // 2, 0))
    return reference_frame, current_canvas


def _comparison_row(
    save: SaveGame,
    reference: Image.Image,
    current: Image.Image,
    *,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
) -> Image.Image:
    scale = _THUMBNAIL_HEIGHT / reference.height
    size = (round(reference.width * scale), _THUMBNAIL_HEIGHT)
    left = reference.resize(size, Image.Resampling.LANCZOS)
    right = current.resize(size, Image.Resampling.LANCZOS)
    row = Image.new("RGB", (size[0] * 2, _THUMBNAIL_HEIGHT + _LABEL_HEIGHT), "black")
    row.paste(left, (0, _LABEL_HEIGHT))
    row.paste(right, (size[0], _LABEL_HEIGHT))
    label = f"{save.path.name} · {save.description} · {save.room}/{save.timeblock}"
    ImageDraw.Draw(row).text((8, 7), label, fill="white", font=font)
    return row
