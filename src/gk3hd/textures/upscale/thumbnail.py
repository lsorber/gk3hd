"""Reconstruct inventory thumbnails from verified larger original artwork."""

from __future__ import annotations

from typing import TYPE_CHECKING

from gk3hd.textures.flat import actual_files
from gk3hd.textures.upscale.thumbnail_recipes import ThumbnailRecipe, thumbnail_recipe

if TYPE_CHECKING:
    from pathlib import Path

    import numpy as np
    from numpy.typing import NDArray
    from PIL.Image import Image

_BACKGROUND_BLACK_THRESHOLD = 8
_CLEAR_COVERAGE = 0.01
_MINIMUM_BACKGROUND_ROWS = 2
_BACKDROP_WITNESS_COUNT = 2
_MINIMUM_SHARED_ROWS = 8
_MINIMUM_SHARED_COLORS = 4


def regenerate_thumbnail(source: Path) -> Image:
    """Sample real higher-resolution content in the original thumbnail's frame.

    The small images and larger original were registered using a single uniform
    scale, translation and (for framed artwork) rotation, never per-glyph fitting.
    Minification is prefiltered; destination centers use the original texture
    coordinate phase. The normal alpha pipeline must enlarge any paired opacity.
    """
    import numpy as np  # noqa: PLC0415
    from PIL import Image as PillowImage  # noqa: PLC0415
    from scipy.ndimage import gaussian_filter, map_coordinates  # noqa: PLC0415

    recipe = thumbnail_recipe(source.name)
    if recipe is None:
        msg = f"no verified larger source for thumbnail {source.name}"
        raise ValueError(msg)
    sibling = actual_files(source.parent, suffix=".bmp").get(recipe.source_name.casefold())
    if sibling is None:
        msg = f"{source.name} requires original {recipe.source_name} alongside it"
        raise FileNotFoundError(msg)
    with PillowImage.open(source) as small, PillowImage.open(sibling) as large:
        if small.size != recipe.size or large.size != recipe.source_size:
            msg = f"{source.name}: thumbnail or larger source has an unsupported size"
            raise ValueError(msg)
        if recipe.frame_inset:
            return _framed_thumbnail(
                small.convert("RGB"),
                large.convert("RGB"),
                recipe,
                backdrops=_load_backdrops(source, recipe),
            )
        pixels = np.asarray(large.convert("RGB"), dtype=float)
    width, height = recipe.size
    scale = 4
    y, x = np.mgrid[: height * scale, : width * scale]
    factor = recipe.source_scale
    offset_x, offset_y = recipe.offset
    pixels = gaussian_filter(pixels, (0.35 / (factor * scale), 0.35 / (factor * scale), 0))
    coordinates = np.array(
        [
            ((y + 0.5) / scale - 0.5 - offset_y) / factor,
            ((x + 0.5) / scale - 0.5 - offset_x) / factor,
        ]
    )
    result = np.stack(
        [
            map_coordinates(pixels[:, :, channel], coordinates, order=1, mode="constant", cval=0)
            for channel in range(3)
        ],
        axis=2,
    )
    return PillowImage.fromarray(np.clip(np.rint(result), 0, 255).astype("uint8"))


def _project_thumbnail_art(
    large: Image,
    recipe: ThumbnailRecipe,
    logical_x: NDArray[np.float64],
    logical_y: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Project premultiplied original color and coverage using its registered geometry."""
    import numpy as np  # noqa: PLC0415
    from scipy.ndimage import binary_fill_holes, gaussian_filter, map_coordinates  # noqa: PLC0415

    factor = recipe.source_scale
    factor_y = recipe.source_scale_y if recipe.source_scale_y is not None else factor
    offset_x, offset_y = recipe.offset
    coordinates = np.array([(logical_y - offset_y) / factor_y, (logical_x - offset_x) / factor])
    if recipe.rotation_degrees:
        angle = np.deg2rad(recipe.rotation_degrees)
        cosine, sine = np.cos(angle), np.sin(angle)
        source_y, source_x = coordinates
        coordinates = np.array(
            [-sine * source_x + cosine * source_y, cosine * source_x + sine * source_y]
        )
    sigma, sigma_y = 0.35 / (factor * 4), 0.35 / (factor_y * 4)
    pixels = np.asarray(large, dtype=float)
    if recipe.source_color_key is not None:
        # A declared color key is explicit transparency, including closed holes.
        # Remove its RGB before filtering so magenta cannot fringe the artwork.
        coverage = ~np.all(pixels == recipe.source_color_key, axis=2)
        pixels = np.where(coverage[:, :, None], pixels, 0)
    else:
        coverage = np.any(pixels > _BACKGROUND_BLACK_THRESHOLD, axis=2)
        if not recipe.preserve_cutouts:
            coverage = binary_fill_holes(coverage)
        else:
            # Preserve confirmed openings without adding near-black residue.
            pixels = np.where(coverage[:, :, None], pixels, 0)
    coverage = coverage.astype(float)
    pixels = gaussian_filter(pixels, (sigma_y, sigma, 0))
    projected = (
        np.stack(
            [
                map_coordinates(
                    pixels[:, :, channel], coordinates, order=1, mode="constant", cval=0
                )
                for channel in range(3)
            ],
            axis=2,
        )
        * recipe.brightness
    )
    coverage = map_coordinates(
        gaussian_filter(coverage, (sigma_y, sigma)), coordinates, order=1, mode="constant", cval=0
    )
    if recipe.brightness_offset:
        # Offset premultiplied color only where artwork covers the pixel. Clamp
        # before compositing so neither dark nor bright tones contaminate edges.
        projected = np.clip(
            projected + recipe.brightness_offset * coverage[:, :, None],
            0,
            255 * coverage[:, :, None],
        )
    return projected, coverage


def _load_backdrops(source: Path, recipe: ThumbnailRecipe) -> tuple[Image, ...]:
    """Load explicit original background witnesses, never generated replacements."""
    from PIL import Image as PillowImage  # noqa: PLC0415

    if recipe.background_sources is None:
        return ()
    files = actual_files(source.parent, suffix=".bmp")
    result = []
    for name in recipe.background_sources:
        sibling = files.get(name.casefold())
        if sibling is None:
            msg = f"{source.name} requires original {name} alongside it"
            raise FileNotFoundError(msg)
        with PillowImage.open(sibling) as image:
            result.append(image.convert("RGB"))
    return tuple(result)


def _shared_backdrop(
    backdrops: tuple[Image, ...],
    background: NDArray[np.float64],
    sampled: NDArray[np.bool_],
    inset: int,
) -> NDArray[np.float64]:
    """Require independent row-color consensus and exact visible-target agreement."""
    import numpy as np  # noqa: PLC0415

    height, width, _ = background.shape
    if len(backdrops) != _BACKDROP_WITNESS_COUNT or any(
        image.size != (width, height) for image in backdrops
    ):
        msg = "shared backdrop requires two original images of the target size"
        raise ValueError(msg)
    if (
        sampled.sum() < _MINIMUM_SHARED_ROWS
        or len(np.unique(background[sampled, 0], axis=0)) < _MINIMUM_SHARED_COLORS
    ):
        msg = "shared backdrop lacks enough distinct visible target rows"
        raise ValueError(msg)
    witnesses = []
    for image in backdrops:
        pixels = np.asarray(image.convert("RGB"))
        rows = np.zeros((height, 3), dtype=float)
        for row in range(inset, height - inset):
            colors, counts = np.unique(
                pixels[row, inset : width - inset], axis=0, return_counts=True
            )
            most = counts.max()
            if most < (width - 2 * inset) / 4 or np.count_nonzero(counts == most) != 1:
                msg = "shared backdrop has an ambiguous row color"
                raise ValueError(msg)
            rows[row] = colors[counts.argmax()]
        witnesses.append(rows)
    if not np.array_equal(witnesses[0], witnesses[1]):
        msg = "shared backdrop originals disagree"
        raise ValueError(msg)
    if not np.array_equal(witnesses[0][sampled], background[sampled, 0]):
        msg = "shared backdrop differs from visible target rows"
        raise ValueError(msg)
    return witnesses[0]


def _framed_thumbnail(
    small: Image,
    large: Image,
    recipe: ThumbnailRecipe,
    *,
    backdrops: tuple[Image, ...] = (),
) -> Image:
    """Composite registered original artwork into the state's own backdrop and bevel.

    Solid-art recipes keep enclosed ink opaque; explicit cutout/key recipes
    preserve genuine openings. No letters or portrait regions are individually
    warped. Dense output uses scoped area minification in the game renderer.
    """
    import numpy as np  # noqa: PLC0415
    from PIL import Image as PillowImage  # noqa: PLC0415
    from scipy.ndimage import map_coordinates  # noqa: PLC0415

    from gk3hd.textures.upscale.pipeline import resample_monotone_art  # noqa: PLC0415

    scale = 4
    width, height = recipe.size
    y, x = np.mgrid[: height * scale, : width * scale]
    logical_x, logical_y = (x + 0.5) / scale - 0.5, (y + 0.5) / scale - 0.5
    original = np.asarray(small, dtype=float)
    projected, coverage = _project_thumbnail_art(large, recipe, logical_x, logical_y)
    small_coverage = coverage.reshape(height, scale, width, scale).mean(axis=(1, 3))
    inset = recipe.frame_inset
    background = np.zeros_like(original)
    columns = (np.arange(width) >= inset) & (np.arange(width) < width - inset)
    sampled = np.zeros(height, dtype=bool)
    for row in range(inset, height - inset):
        clear = (small_coverage[row] < _CLEAR_COVERAGE) & columns
        if clear.any():
            background[row] = np.median(original[row, clear], axis=0)
            sampled[row] = True
    missing = np.flatnonzero(~sampled[inset : height - inset]) + inset
    if missing.size and backdrops:
        shared = _shared_backdrop(backdrops, background, sampled, inset)
        background[missing] = shared[missing, None, :]
        sampled[missing] = True
        missing = np.array([], dtype=int)
    if missing.size:
        known = np.flatnonzero(sampled)
        if (
            known.size < _MINIMUM_BACKGROUND_ROWS
            or missing[0] < known[0]
            or missing[-1] > known[-1]
        ):
            msg = "framed document leaves no bracketing original background samples"
            raise ValueError(msg)
        # Rotated paper can hide an entire row of the smooth button backdrop.
        # Interpolate only between visible rows, without sampling the paper or
        # inventing an extrapolated color beyond the available original field.
        for channel in range(3):
            background[missing, :, channel] = np.interp(
                missing, known, background[known, 0, channel]
            )[:, None]
    background = np.stack(
        [
            map_coordinates(
                background[:, :, channel], [logical_y, logical_x], order=1, mode="nearest"
            )
            for channel in range(3)
        ],
        axis=2,
    )
    interior = (
        (logical_x >= inset - 0.5)
        & (logical_x < width - inset - 0.5)
        & (logical_y >= inset - 0.5)
        & (logical_y < height - inset - 0.5)
    )
    result = np.where(
        interior[:, :, None],
        projected + background * (1 - coverage[:, :, None]),
        np.asarray(resample_monotone_art(small), dtype=float),
    )
    return PillowImage.fromarray(np.clip(np.rint(result), 0, 255).astype("uint8"))


def is_current_thumbnail(source: Path, destination: Path) -> bool:
    """Invalidate old AI and replacements made from an older large source."""
    from PIL import Image as PillowImage  # noqa: PLC0415

    expected = regenerate_thumbnail(source)
    with PillowImage.open(destination) as candidate:
        return candidate.mode == expected.mode and candidate.tobytes() == expected.tobytes()
