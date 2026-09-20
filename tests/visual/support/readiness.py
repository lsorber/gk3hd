"""Visual readiness gates for deterministic GK3 startup automation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import numpy as np
from PIL import Image as PILImage

if TYPE_CHECKING:
    from PIL.Image import Image

_MIN_FRAME_WIDTH: Final = 300
_MIN_FRAME_HEIGHT: Final = 200
_TITLE_SAMPLE_WIDTH: Final = 1024
_BUTTON_BAND_TOP: Final = 0.87
_BUTTON_Y_MIN: Final = 0.86
_BUTTON_Y_SPAN_MAX: Final = 0.035
_MIN_BUTTON_WIDTH: Final = 0.03
_BUTTON_COUNT: Final = 4
_WARM_RED_RANGE: Final = (150, 230)
_WARM_GREEN_RANGE: Final = (80, 160)
_WARM_BLUE_RANGE: Final = (10, 100)
_WARM_RED_GREEN_GAP: Final = 30
_GREEN_MINIMUM: Final = 80
_GREEN_RED_MINIMUM: Final = 25
_GREEN_BLUE_MINIMUM: Final = 20
_GREEN_CHANNEL_GAP: Final = 6
_STARTUP_MATERIAL_LUMA: Final = 40
_STARTUP_MATERIAL_RATIO: Final = 0.008
_RESTORE_BUTTON_INDEX: Final = 2
_REFERENCE_SIZE: Final = (1024, 768)
_RESTORE_FILL_LUMA: Final = 24
_RESTORE_GOLD_RED_MIN: Final = 70
_RESTORE_GOLD_GREEN_MIN: Final = 25
_RESTORE_GOLD_GREEN_MAX: Final = 160
_RESTORE_GOLD_BLUE_MAX: Final = 90
_RESTORE_GOLD_CHANNEL_GAP: Final = 15
_RESTORE_DARK_LUMA: Final = 40
_RESTORE_DARK_RATIO: Final = 0.60
_RESTORE_BORDER_COVERAGE: Final = 0.50
_RESTORE_GOLD_RATIO: Final = 0.065
_RESTORE_FILL_RATIO: Final = 0.12
_RESTORE_FADED_GOLD_RATIO: Final = 0.025
_RESTORE_FADED_FILL_RATIO: Final = 0.50
_BROWSER_DARK_RATIO: Final = 0.70
_BROWSER_GOLD_RATIO: Final = 0.03
_BROWSER_MATERIAL_RATIO: Final = 0.07
_BROWSER_MATERIAL_RATIO_MAX: Final = 0.40
_CONSOLE_BAND_BOTTOM: Final = 0.15
_CONSOLE_CHANNEL_GAP: Final = 40
_CONSOLE_GREEN_MAX: Final = 40
_CONSOLE_ROW_COVERAGE: Final = 0.45
_CONSOLE_MIN_ROWS: Final = 3


def developer_console_visible(image: Image) -> bool:
    """Recognize the wide purple console strip, not isolated purple artwork."""
    sample = image.resize((512, 384), PILImage.Resampling.NEAREST).convert("RGB")
    band = np.asarray(sample, dtype=np.int16)[: round(384 * _CONSOLE_BAND_BOTTOM)]
    red, green, blue = (band[:, :, channel] for channel in range(3))
    purple = (red > green + _CONSOLE_CHANNEL_GAP) & (blue > red) & (green < _CONSOLE_GREEN_MAX)
    rows = np.flatnonzero(purple.mean(axis=1) >= _CONSOLE_ROW_COVERAGE)
    return bool(
        rows.size
        and any(end - start + 1 >= _CONSOLE_MIN_ROWS for start, end in _contiguous_spans(rows))
    )


def title_ready(image: Image) -> bool:
    """Recognize GK3's four aligned warm or green title controls."""
    return _title_button_centers(image) is not None


def title_restore_center(image: Image) -> tuple[int, int] | None:
    """Return the exact detected center of the title's Restore control."""
    centers = _title_button_centers(image)
    return None if centers is None else centers[_RESTORE_BUTTON_INDEX]


def title_play_center(image: Image) -> tuple[int, int] | None:
    """Return the detected Play control without assuming an output resolution."""
    centers = _title_button_centers(image)
    return None if centers is None else centers[1]


def _title_button_centers(image: Image) -> tuple[tuple[int, int], ...] | None:
    # Keep per-frame readiness work bounded at 4K/8K. Return coordinates in
    # the original capture, not the sample, so input remains resolution-aware.
    if image.width > _TITLE_SAMPLE_WIDTH:
        sample_height = round(image.height * _TITLE_SAMPLE_WIDTH / image.width)
        sample = image.resize((_TITLE_SAMPLE_WIDTH, sample_height), PILImage.Resampling.NEAREST)
        centers = _sample_title_button_centers(sample)
        if centers is None:
            return None
        return tuple(
            (round(x * image.width / sample.width), round(y * image.height / sample.height))
            for x, y in centers
        )
    return _sample_title_button_centers(image)


def _sample_title_button_centers(image: Image) -> tuple[tuple[int, int], ...] | None:
    """Locate aligned button centers in a bounded-resolution sample."""
    frame = np.asarray(image.convert("RGB"), dtype=np.uint8)
    height, width, _channels = frame.shape
    if height < _MIN_FRAME_HEIGHT or width < _MIN_FRAME_WIDTH:
        return None

    band_top = int(height * _BUTTON_BAND_TOP)
    band = frame[band_top:, :, :3].astype(np.int16)
    red, green, blue = (band[:, :, channel] for channel in range(3))
    warm = (
        (red > _WARM_RED_RANGE[0])
        & (red < _WARM_RED_RANGE[1])
        & (green > _WARM_GREEN_RANGE[0])
        & (green < _WARM_GREEN_RANGE[1])
        & (blue > _WARM_BLUE_RANGE[0])
        & (blue < _WARM_BLUE_RANGE[1])
        & ((red - green) > _WARM_RED_GREEN_GAP)
    )
    shifted_green = (
        (green > _GREEN_MINIMUM)
        & (red > _GREEN_RED_MINIMUM)
        & (blue > _GREEN_BLUE_MINIMUM)
        & (green > red + _GREEN_CHANNEL_GAP)
        & (green > blue + _GREEN_CHANNEL_GAP)
    )
    mask = warm | shifted_green
    columns = mask.sum(axis=0)
    maximum = int(columns.max(initial=0))
    active = np.flatnonzero(columns > max(5, int(maximum * 0.25)))
    if maximum <= 0 or active.size == 0:
        return None

    spans = _contiguous_spans(active)
    minimum_width = max(10, int(width * _MIN_BUTTON_WIDTH))
    spans = [span for span in spans if span[1] - span[0] + 1 >= minimum_width]
    if len(spans) < _BUTTON_COUNT:
        return None
    strongest = sorted(
        spans,
        key=lambda span: int(columns[span[0] : span[1] + 1].sum()),
        reverse=True,
    )[:_BUTTON_COUNT]
    strongest.sort()

    centers: list[tuple[int, int]] = []
    for left, right in strongest:
        rows, _columns = np.nonzero(mask[:, left : right + 1])
        if rows.size == 0:
            return None
        centers.append(((left + right) // 2, round(band_top + float(rows.mean()))))
    centers_y = [center[1] for center in centers]
    mean_y = sum(centers_y) / len(centers_y)
    if (
        mean_y < height * _BUTTON_Y_MIN
        or max(centers_y) - min(centers_y) > height * _BUTTON_Y_SPAN_MAX
    ):
        return None
    return tuple(centers)


def startup_escape_safe(image: Image) -> bool:
    """Allow movie dismissal only while material startup artwork owns the frame."""
    # A coarse occupancy sample distinguishes a logo from a tiny cursor;
    # scanning every 4K pixel here delays the very transition being detected.
    sample = image.resize((160, 90), PILImage.Resampling.NEAREST).convert("RGB")
    frame = np.asarray(sample, dtype=np.uint8)
    material = frame[:, :, :3].max(axis=2) > _STARTUP_MATERIAL_LUMA
    return bool(float(material.mean()) >= _STARTUP_MATERIAL_RATIO)


def frame_mean_absolute_difference(first: Image, second: Image) -> float:
    """Measure a normalized per-channel visual transition between equal frames."""
    if first.size != second.size:
        return float("inf")
    first_rgb = np.asarray(first.convert("RGB"), dtype=np.float32)
    second_rgb = np.asarray(second.convert("RGB"), dtype=np.float32)
    return float(np.abs(first_rgb - second_rgb).mean())


def restore_dialog_visible(image: Image) -> bool:
    """Recognize GK3's centered Restoring panel at any capture resolution."""
    normalized = _normalize_4_3(image)
    bar = normalized[383:434, 256:770, :]
    panel = normalized[280:488, 210:814, :]
    if bar.size == 0 or panel.size == 0:
        return False
    fill_ratio = float((bar.max(axis=2) > _RESTORE_FILL_LUMA).mean())
    red = panel[:, :, 0].astype(np.int16)
    green = panel[:, :, 1].astype(np.int16)
    blue = panel[:, :, 2].astype(np.int16)
    gold = (
        (red > _RESTORE_GOLD_RED_MIN)
        & (green > _RESTORE_GOLD_GREEN_MIN)
        & (green < _RESTORE_GOLD_GREEN_MAX)
        & (blue < _RESTORE_GOLD_BLUE_MAX)
        & ((red - green) > _RESTORE_GOLD_CHANNEL_GAP)
    )
    gold_ratio = float(gold.mean())
    dark_ratio = float((panel.max(axis=2) < _RESTORE_DARK_LUMA).mean())
    top = max(float(gold[y, 6:599].mean()) for y in range(10))
    bottom = max(float(gold[y, 6:599].mean()) for y in range(198, 208))
    left = max(float(gold[4:205, x].mean()) for x in range(2, 12))
    right = max(float(gold[4:205, x].mean()) for x in range(593, 604))
    border = min(top, bottom, left, right)
    return bool(
        dark_ratio >= _RESTORE_DARK_RATIO
        and border >= _RESTORE_BORDER_COVERAGE
        and (
            (gold_ratio >= _RESTORE_GOLD_RATIO and fill_ratio >= _RESTORE_FILL_RATIO)
            or (gold_ratio >= _RESTORE_FADED_GOLD_RATIO and fill_ratio >= _RESTORE_FADED_FILL_RATIO)
        )
    )


def restore_browser_visible(image: Image) -> bool:
    """Recognize the settled Restore browser, excluding black and Title frames."""
    normalized = _normalize_4_3(image)
    panel = normalized[150:700, 180:850, :]
    if panel.size == 0:
        return False
    red = panel[:, :, 0].astype(np.int16)
    green = panel[:, :, 1].astype(np.int16)
    blue = panel[:, :, 2].astype(np.int16)
    maximum = panel.max(axis=2)
    gold = (
        (red > _RESTORE_GOLD_RED_MIN)
        & (green > _RESTORE_GOLD_GREEN_MIN)
        & (green < _RESTORE_GOLD_GREEN_MAX)
        & (blue < _RESTORE_GOLD_BLUE_MAX)
        & ((red - green) > _RESTORE_GOLD_CHANNEL_GAP)
    )
    material_ratio = float((maximum > _RESTORE_FILL_LUMA).mean())
    return bool(
        float((maximum < _RESTORE_DARK_LUMA).mean()) >= _BROWSER_DARK_RATIO
        and float(gold.mean()) >= _BROWSER_GOLD_RATIO
        and _BROWSER_MATERIAL_RATIO <= material_ratio <= _BROWSER_MATERIAL_RATIO_MAX
    )


def timeblock_complete(image: Image) -> bool:
    """Require the finished white time label and amber Continue/Save row.

    Layer creation precedes the letter-by-letter title animation. These two
    broad horizontal anchors reject its partial text and transient artwork.
    Only readiness is normalized; the saved image stays at native resolution.
    """
    rgb = _normalize_4_3(image).astype(np.int16)
    panel = rgb[430:680, 150:875]
    white = (panel.min(axis=2) > 170) & (np.ptp(panel, axis=2) < 30)
    red, green, blue = (panel[:, :, channel] for channel in range(3))
    amber = (red > 80) & (red > green * 1.15) & (green > blue * 1.20)
    label, controls = white[10:140], amber[110:210]
    return bool(
        white.sum() >= 1000
        and amber.sum() >= 1000
        and (rgb.mean(axis=2) < 20).mean() >= 0.68
        and label.sum(axis=1).max() >= 90
        and label.any(axis=0).sum() >= 180
        and controls.sum(axis=1).max() >= 120
    )


def _normalize_4_3(image: Image) -> np.ndarray:
    source = image.convert("RGB")
    target_ratio = 4.0 / 3.0
    source_ratio = source.width / source.height
    if source_ratio > target_ratio:
        width = round(source.height * target_ratio)
        left = (source.width - width) // 2
        source = source.crop((left, 0, left + width, source.height))
    elif source_ratio < target_ratio:
        height = round(source.width / target_ratio)
        top = (source.height - height) // 2
        source = source.crop((0, top, source.width, top + height))
    resized = source.resize(_REFERENCE_SIZE, PILImage.Resampling.BILINEAR)
    return np.asarray(resized, dtype=np.uint8)


def _contiguous_spans(values: np.ndarray) -> list[tuple[int, int]]:
    start = previous = int(values[0])
    spans: list[tuple[int, int]] = []
    for raw_value in values[1:]:
        value = int(raw_value)
        if value == previous + 1:
            previous = value
            continue
        spans.append((start, previous))
        start = previous = value
    spans.append((start, previous))
    return spans
