"""Source-constrained glyph coverage reconstruction, independent of font layout.

This operator does not identify a typeface or approve an atlas recipe. It keeps
every original coverage pixel as the exact mean of its 4x4 replacement, while
estimating subpixel edges. An optional larger-source hint supplies compatible
edge directions only, never glyph positions, advances or replacement coverage.
Recipe registration and native visual acceptance remain separate requirements.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import numpy as np
from scipy.ndimage import gaussian_filter, sobel

if TYPE_CHECKING:
    from numpy.typing import NDArray

_SCALE: Final = 4
_EPSILON: Final = 1e-10
_DIMENSIONS: Final = 2
_AXIS_EPSILON: Final = 1e-7
_GRADIENT_EPSILON: Final = 1e-8
_MINIMUM_DIRECTION_AGREEMENT: Final = 0.75


def reconstruct_font_coverage(
    coverage: NDArray[np.uint8],
    *,
    edge_hint: NDArray[np.float64] | None = None,
    bit_depth: int = 5,
) -> NDArray[np.uint8]:
    """Return 4x coverage without changing any original block average.

    Use five bits for decoded RGB565 font coverage, eight for separate opacity
    images. Inputs are a nonempty 2D array of integers and, optionally, a finite
    4x field of coverage 0..1 aligned by a separately verified atlas recipe.
    Zero/full source pixels stay entirely zero/full. Do not use RGB brightness
    as coverage for a color font or feed parser-marker pixels to this function.
    """
    if bit_depth not in (5, 8):
        msg = "font coverage supports only five-bit or eight-bit precision"
        raise ValueError(msg)
    maximum = (1 << bit_depth) - 1
    if (
        coverage.dtype != np.uint8
        or coverage.ndim != _DIMENSIONS
        or not coverage.size
        or not np.all(coverage <= maximum)
    ):
        msg = f"font coverage requires a nonempty 2D uint8 array with values 0..{maximum}"
        raise ValueError(msg)
    source = coverage.astype(np.float64) / maximum
    shape = (source.shape[0] * _SCALE, source.shape[1] * _SCALE)
    if edge_hint is not None and (
        edge_hint.shape != shape
        or not np.all(np.isfinite(edge_hint))
        or not np.all((edge_hint >= 0) & (edge_hint <= 1))
    ):
        msg = "font edge hint requires finite 0..1 coverage at exactly 4x source dimensions"
        raise ValueError(msg)
    result = _edge_coverage(source, edge_hint)
    for _ in range(6):
        result = _project(source, gaussian_filter(result, 0.6, mode="constant"))
    return _quantize(coverage, result, maximum)


def conserve_font_channel(
    source: NDArray[np.uint8], proposed: NDArray[np.float64], *, maximum: int
) -> NDArray[np.uint8]:
    """Bound a proposed 4x channel and preserve every original integer block sum.

    Proposals use channel units (not normalized coverage) and may overshoot.
    This projection is shared by grayscale coverage and verified color fonts;
    callers remain responsible for color-key and source-palette constraints.
    """
    if (
        maximum not in (31, 63, 255)
        or source.dtype != np.uint8
        or source.ndim != _DIMENSIONS
        or not source.size
        or np.any(source > maximum)
        or proposed.shape != tuple(dimension * _SCALE for dimension in source.shape)
        or not np.all(np.isfinite(proposed))
    ):
        msg = "font channel requires bounded uint8 source and finite 4x proposal"
        raise ValueError(msg)
    projected = _project(source.astype(np.float64) / maximum, proposed / maximum)
    return _quantize(source, projected, maximum)


def _square_area(
    distance: NDArray[np.float64], nx: NDArray[np.float64], ny: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Area of the unit square on one side of an oriented straight edge."""
    large, small = np.maximum(np.abs(nx), np.abs(ny)), np.minimum(np.abs(nx), np.abs(ny))
    position = distance + (large + small) / 2
    value = (
        np.maximum(position, 0) ** 2
        - np.maximum(position - large, 0) ** 2
        - np.maximum(position - small, 0) ** 2
        + np.maximum(position - large - small, 0) ** 2
    ) / (2 * np.maximum(large * small, _EPSILON))
    linear = np.clip(distance / np.maximum(large, _EPSILON) + 0.5, 0, 1)
    return np.clip(np.where(small > _AXIS_EPSILON, value, linear), 0, 1)


def _directions(
    source: NDArray[np.float64], hint: NDArray[np.float64] | None
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.bool_]]:
    """Use hinted normals only where they agree with the source gradient."""
    gy, gx = (sobel(source, axis=axis, mode="constant") for axis in (0, 1))
    length = np.hypot(gx, gy)
    nx, ny = -gx / np.maximum(length, _EPSILON), -gy / np.maximum(length, _EPSILON)
    flat = length < _GRADIENT_EPSILON
    if hint is not None:
        py, px = (
            _blocks(sobel(hint, axis=axis, mode="constant")).mean(axis=(2, 3)) for axis in (0, 1)
        )
        magnitude = np.hypot(px, py)
        px, py = -px / np.maximum(magnitude, _EPSILON), -py / np.maximum(magnitude, _EPSILON)
        compatible = (
            (nx * px + ny * py >= _MINIMUM_DIRECTION_AGREEMENT)
            & (magnitude > _GRADIENT_EPSILON)
            & ~flat
        )
        nx, ny = np.where(compatible, px, nx), np.where(compatible, py, ny)
    return nx, ny, flat


def _edge_coverage(
    source: NDArray[np.float64], hint: NDArray[np.float64] | None
) -> NDArray[np.float64]:
    """Solve each edge offset from original area, not a guessed intensity curve."""
    nx, ny, flat = _directions(source, hint)
    low = -(np.abs(nx) + np.abs(ny)) / 2
    high = -low
    for _ in range(45):
        middle = (low + high) / 2
        below = _square_area(middle, nx, ny) < source
        low, high = np.where(below, middle, low), np.where(below, high, middle)
    distance = (low + high) / 2
    result = np.empty((source.shape[0] * _SCALE, source.shape[1] * _SCALE))
    for y in range(_SCALE):
        for x in range(_SCALE):
            offset = nx * ((x + 0.5) / _SCALE - 0.5) + ny * ((y + 0.5) / _SCALE - 0.5)
            area = _square_area(_SCALE * (distance - offset), nx, ny)
            area = np.where(flat, source, area)
            result[y::_SCALE, x::_SCALE] = np.where(source <= 0, 0, np.where(source >= 1, 1, area))
    return result


def _blocks(image: NDArray[np.float64]) -> NDArray[np.float64]:
    return image.reshape(
        image.shape[0] // _SCALE, _SCALE, image.shape[1] // _SCALE, _SCALE
    ).transpose(0, 2, 1, 3)


def _project(source: NDArray[np.float64], image: NDArray[np.float64]) -> NDArray[np.float64]:
    """Bounded least-squares projection onto each original coverage average."""
    blocks = _blocks(image)
    low = np.minimum(-1.0, -blocks.max(axis=(2, 3)))
    high = np.maximum(1.0, 1.0 - blocks.min(axis=(2, 3)))
    for _ in range(34):
        middle = (low + high) / 2
        below = np.clip(blocks + middle[:, :, None, None], 0, 1).mean(axis=(2, 3)) < source
        low, high = np.where(below, middle, low), np.where(below, high, middle)
    blocks = np.clip(blocks + ((low + high) / 2)[:, :, None, None], 0, 1)
    return blocks.transpose(0, 2, 1, 3).reshape(image.shape)


def _quantize(
    source: NDArray[np.uint8], image: NDArray[np.float64], maximum: int
) -> NDArray[np.uint8]:
    """Stable largest-remainder quantization keeps integer block sums exact."""
    samples = _blocks(image).reshape(*source.shape, _SCALE**2) * maximum
    integers = np.floor(samples).astype(np.int16)
    target = source.astype(np.int16) * _SCALE**2
    remainder = target - integers.sum(axis=2)
    if not np.all((remainder >= 0) & (remainder <= _SCALE**2)):
        msg = "font coverage projection failed its integer conservation constraint"
        raise ValueError(msg)
    order = np.argsort(-(samples - integers), axis=2, kind="stable")
    ranks = np.argsort(order, axis=2)
    integers += ranks < remainder[:, :, None]
    return (
        integers.reshape(*source.shape, _SCALE, _SCALE)
        .transpose(0, 2, 1, 3)
        .reshape(image.shape)
        .astype(np.uint8)
    )
