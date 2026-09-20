"""Property-driven texture transformation pipelines.

Only semantic properties choose a route: data textures remain untouched and
are excluded by the service; recognized font atlases use a file-aware,
source-faithful 4x regenerator while unrecognized ones remain untouched; reviewed
exact raster art and constant-color materials keep their native dimensions unless
a coupled resource requires matching density. Continuous alpha uses grayscale
resampling; edge-only silhouettes may use shape-checked AI with resampling fallback.
Ordinary color uses SeedVR2
unless policy explicitly requests source-preserving bicubic; and alpha-test
color separates its binary key mask from RGB inference. ``tiled`` composes
periodic edge handling with the selected route. Verified geometric UI controls
use a file-aware source resampler rather than inferred bevels and corners.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import numpy as np
from PIL import Image

from gk3hd.textures.routing import PipelineKind, PipelinePlan, plan_texture

if TYPE_CHECKING:
    from gk3hd.textures.model import TextureFeatures

KEY_COLOR = np.array([255, 0, 255], dtype=np.uint8)
DEFAULT_EDGE_PADDING = 8
KEY_BLEED_ITERATIONS = 32
KEY_MASK_BIAS = 0.4
RGB_DIMENSIONS = 3
MASK_DIMENSIONS = 2
_AUTHORING_SPECK_NEIGHBORHOOD = (2, 3)
_GRAYSCALE_PALETTE = [value for index in range(256) for value in (index, index, index)]


class ColorUpscaler(Protocol):
    """The small interface required from an RGB reconstruction backend."""

    scale: int

    def upscale(self, image: Image.Image) -> Image.Image:
        """Return an RGB image enlarged by :attr:`scale`."""


def upscale_texture(
    image: Image.Image,
    features: TextureFeatures,
    *,
    upscaler: ColorUpscaler | None = None,
    scale: int = 4,
    edge_padding: int = DEFAULT_EDGE_PADDING,
) -> Image.Image:
    """Apply the property-selected transformation to one texture.

    Args:
        image: Source image. BMP palette modes are retained where exact values
            matter.
        features: Semantic and sampling properties for this texture.
        upscaler: Lazy AI backend. Required only for non-pixel color routes.
        scale: Integer scale for deterministic routes; SeedVR2 supports 4 only.
        edge_padding: Source-pixel context supplied around AI or smooth routes.
    """
    if scale <= 0:
        msg = "scale must be positive"
        raise ValueError(msg)
    if edge_padding < 0:
        msg = "edge_padding must be non-negative"
        raise ValueError(msg)
    plan = plan_texture(features)
    if plan.kind.keeps_native_size:
        return image.copy()
    file_aware_routes = {
        PipelineKind.REVIEWED_REPLACEMENT: "reviewed replacement artwork",
        PipelineKind.FONT_ATLAS_SOURCE_4X: "font-atlas copier",
        PipelineKind.FONT_BUTTON_SOURCE_4X: "font-button copier",
        PipelineKind.FINGERPRINT_SOURCE_4X: "source-faithful fingerprint resampler",
        PipelineKind.UI_SOURCE_4X: "source-faithful UI resampler",
        PipelineKind.THUMBNAIL_SOURCE_4X: "larger-source thumbnail reconstructor",
        PipelineKind.DRIVING_MAP_COMPOSITE: "shared-background composition",
        PipelineKind.TIMEBLOCK_COMPOSITE: "shared-background composition",
    }
    if method := file_aware_routes.get(plan.kind):
        msg = f"{features.name} requires the file-aware {method}"
        raise RuntimeError(msg)
    if plan.kind is PipelineKind.ALPHA_SMOOTH:
        return _upscale_alpha(image, scale, periodic=plan.periodic, padding=edge_padding)
    if plan.kind in {PipelineKind.COLOR_SMOOTH, PipelineKind.ALPHA_TEST_SMOOTH}:
        return upscale_smooth_color(
            image, scale, periodic=plan.periodic, alphatest=features.alphatest
        )
    if upscaler is None:
        msg = f"{features.name} requires SeedVR2; install gk3hd[upscale] and pass a SeedVR2Upscaler"
        raise RuntimeError(msg)
    return _upscale_ai(image, upscaler, features=features, scale=scale, padding=edge_padding)


def _upscale_ai(
    image: Image.Image,
    upscaler: ColorUpscaler,
    *,
    features: TextureFeatures,
    scale: int,
    padding: int,
) -> Image.Image:
    """Dispatch backend-dependent variants after the deterministic routes."""
    if scale != upscaler.scale:
        msg = f"AI backend scale is {upscaler.scale}, not requested scale {scale}"
        raise ValueError(msg)
    plan = plan_texture(features)
    if plan.kind is PipelineKind.ALPHA_AI:
        return _upscale_guarded_alpha(image, upscaler, periodic=plan.periodic, padding=padding)
    if plan.kind is PipelineKind.ALPHA_TEST_AI:
        return _upscale_alpha_test(
            image,
            upscaler,
            name=features.name,
            plan=plan,
            padding=padding,
        )
    return _upscale_color(image, upscaler, periodic=plan.periodic, padding=padding)


@dataclass(slots=True)
class _BicubicUpscaler:
    """Reconstruct source shading inside the shared color-key pipeline."""

    scale: int

    def upscale(self, image: Image.Image) -> Image.Image:
        """Interpolate the filled RGB source without inferring new detail."""
        return image.resize(
            (image.width * self.scale, image.height * self.scale), Image.Resampling.BICUBIC
        )


def upscale_smooth_color(
    image: Image.Image, scale: int = 4, *, periodic: bool, alphatest: bool = False
) -> Image.Image:
    """Reconstruct low-detail color shading without sharpening or inventing detail.

    This explicit analysis choice is not a size-only heuristic. Bicubic's two-
    pixel support receives four source pixels of wrap/reflection context so
    opposite texture edges interpolate continuously when actual UVs repeat.
    Keyed artwork uses the same bleed and edge context as keyed AI, but
    interpolates RGB and uses the unbiased contour to retain authored weight.
    """
    if scale <= 0:
        msg = "scale must be positive"
        raise ValueError(msg)
    if alphatest:
        return _upscale_alpha_test(
            image,
            _BicubicUpscaler(scale),
            name="source-preserving keyed artwork",
            plan=PipelinePlan(PipelineKind.ALPHA_TEST_SMOOTH, periodic),
            padding=DEFAULT_EDGE_PADDING,
        )
    padding = 4
    padded = _pad(np.asarray(image.convert("RGB")), padding, periodic=periodic)
    enlarged = Image.fromarray(padded).resize(
        (padded.shape[1] * scale, padded.shape[0] * scale), Image.Resampling.BICUBIC
    )
    return Image.fromarray(_crop(np.asarray(enlarged), padding * scale))


def _upscale_color(
    image: Image.Image,
    upscaler: ColorUpscaler,
    *,
    periodic: bool,
    padding: int,
) -> Image.Image:
    """Give SeedVR2 periodic or reflected context, then remove that context."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    padded = _pad(rgb, padding, periodic=periodic)
    result = _run_color_backend(padded, upscaler)
    return Image.fromarray(_crop(result, padding * upscaler.scale), mode="RGB")


def alpha_test_mask(rgb: np.ndarray) -> np.ndarray:
    """Read the binary key, correcting GK3's isolated top-edge authoring speck.

    Many shipped scene textures contain one non-magenta pixel at (1, 0),
    disconnected from the actual image. GEngine's scene-texture loader also
    removes this quirk. Do not infer generic denoising: keep every other speck,
    connected diagonal, and image consisting solely of that one pixel.
    Font/pixel-art routes do not use this source preprocessing function.
    """
    mask = np.all(rgb == KEY_COLOR, axis=2)
    if (
        mask.shape[0] >= _AUTHORING_SPECK_NEIGHBORHOOD[0]
        and mask.shape[1] >= _AUTHORING_SPECK_NEIGHBORHOOD[1]
        and not mask[0, 1]
        and mask[0, 0]
        and mask[0, 2]
        and mask[1, :3].all()
        and np.count_nonzero(~mask) > 1
    ):
        mask[0, 1] = True
    return mask


def _upscale_alpha_test(
    image: Image.Image,
    upscaler: ColorUpscaler,
    *,
    name: str,
    plan: PipelinePlan,
    padding: int,
) -> Image.Image:
    """Reconstruct RGB without the color key and restore a smooth binary contour."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    mask = alpha_test_mask(rgb)
    periodic = plan.periodic
    # Source-preserving lettering must not gain stroke weight. The inherited
    # AI contour bias expands the hotel sign's opaque area by roughly 11%.
    mask_bias = 0.0 if plan.kind is PipelineKind.ALPHA_TEST_SMOOTH else KEY_MASK_BIAS
    if not mask.any():
        msg = f"{name}: alphatest is set but the image contains no GK3 color key"
        raise ValueError(msg)
    if mask.all():
        size = (image.width * upscaler.scale, image.height * upscaler.scale)
        return image.convert("RGB").resize(size, Image.Resampling.NEAREST)
    if periodic:
        padded_rgb = _pad(rgb, padding, periodic=True)
        padded_mask = _pad(mask, padding, periodic=True)
        filled = _bleed_key(padded_rgb, padded_mask)
        generated = _run_color_backend(filled, upscaler)
        output = _crop(generated, padding * upscaler.scale)
        output[
            upscale_key_mask(mask, upscaler.scale, periodic=True, padding=padding, bias=mask_bias)
        ] = KEY_COLOR
    else:
        filled = _bleed_key(rgb, mask)
        padded = _pad(filled, padding, periodic=False)
        generated = _run_color_backend(padded, upscaler)
        generated = _crop(generated, padding * upscaler.scale)
        generated[upscale_key_mask(mask, upscaler.scale, bias=mask_bias)] = KEY_COLOR
        output = generated
    # Preserve an originally keyed corner, but never introduce transparency
    # into an opaque corner (e.g. the black frame around BINOCMASK's aperture).
    if mask[0, 0]:
        output[0, 0] = KEY_COLOR
    return Image.fromarray(output, mode="RGB")


def resample_keyed_art(
    image: Image.Image,
    *,
    scale: int,
    key_color: tuple[int, int, int] = (255, 0, 255),
    sample_aligned: bool = False,
) -> Image.Image:
    """Enlarge geometric keyed art without AI or magenta interpolation fringes.

    This is for known geometric overlays, not photographic keyed textures.
    Retain its nonuniform dark edge colors, fill hidden RGB before interpolation,
    and reconstruct the binary aperture with the same contour algorithm as the
    general alpha-test pipeline. Opaque corners must remain opaque. For clue
    overlays, align both RGB and contour to native 4x sampling and omit the
    general silhouette bias: a thin line must hit the same reference pixels.
    """
    if scale <= 0:
        msg = "scale must be positive"
        raise ValueError(msg)
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    key = np.array(key_color, dtype=np.uint8)
    mask = np.all(rgb == key, axis=2)
    enlarged_mask = (
        _upscale_key_mask_field(mask, scale, sample_aligned=True)
        if sample_aligned and mask.any() and not mask.all()
        else upscale_key_mask(mask, scale)
    )
    filled = _bleed_key(rgb, mask)
    size = (image.width * scale, image.height * scale)
    colors = Image.fromarray(filled, mode="RGB")
    enlarged = (
        colors.transform(
            size,
            Image.Transform.AFFINE,
            (1 / scale, 0, -0.5 / scale, 0, 1 / scale, -0.5 / scale),
            Image.Resampling.BICUBIC,
        )
        if sample_aligned
        else colors.resize(size, Image.Resampling.BICUBIC)
    )
    result = np.asarray(enlarged, dtype=np.uint8).copy()
    result[enlarged_mask] = key
    return Image.fromarray(result, mode="RGB")


def resample_monotone_art(image: Image.Image) -> Image.Image:
    """Enlarge opaque lettering/artwork 4x without interpolation color overshoot.

    Separable shape-preserving cubic interpolation retains the source's pixel
    centers and color bounds. Unlike ordinary bicubic it adds no bright/dark
    ringing around narrow strokes. This reconstructs baked artwork, not font
    outlines; it must not resample atlas metadata or binary color-key masks.
    """
    from scipy.interpolate import PchipInterpolator  # noqa: PLC0415

    scale = 4
    padding = 2
    pixels = np.asarray(image.convert("RGB"), dtype=np.float64)
    height, width, _ = pixels.shape
    padded = np.pad(pixels, ((padding, padding), (padding, padding), (0, 0)), mode="edge")
    # Output (4*x+2, 4*y+2) is the native reference-size sample. Padding
    # supplies constant edge slopes without extrapolating the cubic.
    x = np.arange(width * scale) / scale - 0.5 + padding
    y = np.arange(height * scale) / scale - 0.5 + padding
    horizontal = PchipInterpolator(np.arange(width + padding * 2), padded, axis=1)(x)
    enlarged = PchipInterpolator(np.arange(height + padding * 2), horizontal, axis=0)(y)
    return Image.fromarray(np.clip(np.rint(enlarged), 0, 255).astype(np.uint8))


def _upscale_alpha(
    image: Image.Image,
    scale: int,
    *,
    periodic: bool,
    padding: int,
) -> Image.Image:
    """Resample a continuous scalar opacity field without hallucinating RGB."""
    alpha = np.asarray(image.convert("L"), dtype=np.uint8)
    padded = _pad(alpha, padding, periodic=periodic)
    enlarged = Image.fromarray(padded, mode="L").resize(
        (padded.shape[1] * scale, padded.shape[0] * scale),
        Image.Resampling.LANCZOS,
    )
    result = _crop(np.asarray(enlarged, dtype=np.uint8), padding * scale)
    # GK3's standalone alpha textures are 8-bit paletted grayscale BMPs.
    paletted = Image.fromarray(result, mode="P")
    paletted.putpalette(_GRAYSCALE_PALETTE)
    return paletted


def _upscale_guarded_alpha(
    image: Image.Image, upscaler: ColorUpscaler, *, periodic: bool, padding: int
) -> Image.Image:
    """Infer scalar coverage, then use Lanczos if the shape guard rejects it."""
    from gk3hd.textures.upscale.alpha_guard import (  # noqa: PLC0415
        ALPHA_GUARD_VERSION,
        alpha_rejection_reasons,
    )
    from gk3hd.textures.upscale.generation import ALPHA_STAMP  # noqa: PLC0415

    candidate = _upscale_color(
        image.convert("L").convert("RGB"), upscaler, periodic=periodic, padding=padding
    ).convert("L")
    reasons = alpha_rejection_reasons(image, candidate, upscaler.scale)
    if reasons:
        result = _upscale_alpha(image, upscaler.scale, periodic=periodic, padding=padding)
    else:
        result = Image.fromarray(np.asarray(candidate), mode="P")
        result.putpalette(_GRAYSCALE_PALETTE)
    result.info[ALPHA_STAMP] = json.dumps(
        {
            "version": ALPHA_GUARD_VERSION,
            "method": "lanczos" if reasons else "ai",
            "reasons": reasons,
        },
        sort_keys=True,
    )
    return result


def is_current_alpha_output(
    original: Image.Image, candidate: Image.Image, *, periodic: bool
) -> bool:
    """Recheck guarded AI or exact fallback pixels without repeating inference."""
    from gk3hd.textures.upscale.alpha_guard import (  # noqa: PLC0415
        alpha_rejection_reasons,
        alpha_result_method,
    )

    rgb = np.asarray(candidate.convert("RGB"))
    if not np.array_equal(rgb[:, :, 0], rgb[:, :, 1]) or not np.array_equal(
        rgb[:, :, 0], rgb[:, :, 2]
    ):
        return False
    method = alpha_result_method(candidate)
    if method == "ai":
        return not alpha_rejection_reasons(original, candidate, 4)
    if method == "lanczos":
        expected = _upscale_alpha(original, 4, periodic=periodic, padding=DEFAULT_EDGE_PADDING)
        return candidate.convert("RGB").tobytes() == expected.convert("RGB").tobytes()
    return False


def _bleed_key(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Hide the color key from inference using local bleed and a neutral fill."""
    result = rgb.copy()
    remaining = mask.copy()
    opaque = ~mask
    height, width, _ = result.shape
    for _ in range(KEY_BLEED_ITERATIONS):
        if not remaining.any():
            break
        counts = np.zeros((height, width), dtype=np.uint16)
        sums = np.zeros((height, width, 3), dtype=np.uint32)
        for target, source in (
            ((slice(None, -1), slice(None)), (slice(1, None), slice(None))),
            ((slice(1, None), slice(None)), (slice(None, -1), slice(None))),
            ((slice(None), slice(None, -1)), (slice(None), slice(1, None))),
            ((slice(None), slice(1, None)), (slice(None), slice(None, -1))),
        ):
            valid = ~remaining[source]
            sums[target] += result[source] * valid[..., None]
            counts[target] += valid
        fill = remaining & (counts > 0)
        if not fill.any():
            break
        result[fill] = (sums[fill] / counts[fill][:, None]).astype(np.uint8)
        remaining[fill] = False
    if remaining.any() and opaque.any():
        # Local diffusion gives the model plausible edge context. A keyed
        # interior can be hundreds of pixels deep, however, and must not retain
        # magenta merely because the bounded local pass ended. Its exact hidden
        # color is immaterial, so use the opaque image's neutral mean rather
        # than allowing the key to bias global inference and color correction.
        neutral = np.rint(np.mean(rgb[opaque], axis=0)).astype(np.uint8)
        result[remaining] = neutral
    return result


def _run_color_backend(rgb: np.ndarray, upscaler: ColorUpscaler) -> np.ndarray:
    """Run the RGB backend and enforce its exact image-scale contract."""
    source = Image.fromarray(rgb, mode="RGB")
    generated = upscaler.upscale(source)
    expected = (source.width * upscaler.scale, source.height * upscaler.scale)
    if generated.mode != "RGB" or generated.size != expected:
        msg = (
            "AI backend returned "
            f"{generated.mode} {generated.width}x{generated.height}; expected "
            f"RGB {expected[0]}x{expected[1]}"
        )
        raise ValueError(msg)
    return np.asarray(generated, dtype=np.uint8).copy()


def upscale_key_mask(
    mask: np.ndarray,
    scale: int,
    *,
    periodic: bool = False,
    padding: int = DEFAULT_EDGE_PADDING,
    bias: float = KEY_MASK_BIAS,
) -> np.ndarray:
    """Reconstruct a smoother color-key contour while remaining exactly binary.

    A signed Euclidean distance field lets diagonal and curved edges cross the 4x pixel grid at
    subpixel positions. Thresholding the enlarged field produces only opaque
    or keyed pixels: GK3 never receives a semitransparent value.
    This is not topology-preserving for arbitrary one-pixel stipples: those
    belong on the exact-raster route rather than contour reconstruction.
    A zero bias retains the authored boundary; the positive AI bias
    slightly expands the opaque silhouette.
    """
    if mask.ndim != MASK_DIMENSIONS or mask.dtype != np.bool_:
        msg = "color-key mask must be a two-dimensional boolean array"
        raise ValueError(msg)
    if scale <= 0:
        msg = "scale must be positive"
        raise ValueError(msg)
    if padding < 0:
        msg = "padding must be non-negative"
        raise ValueError(msg)
    if not math.isfinite(bias):
        msg = "color-key mask bias must be finite"
        raise ValueError(msg)
    if mask.all() or not mask.any():
        return np.repeat(np.repeat(mask, scale, axis=0), scale, axis=1)

    if periodic and padding:
        padded = _pad_key_mask(mask, padding)
        enlarged = _upscale_key_mask_field(padded, scale, bias=bias)
        return _crop(enlarged, padding * scale)
    return _upscale_key_mask_field(mask, scale, bias=bias)


def _pad_key_mask(mask: np.ndarray, padding: int) -> np.ndarray:
    """Wrap artwork edges without filling a wholly transparent source gutter.

    PINE2 has an empty top row and a trunk at the bottom. Ordinary wrap
    interpolation creates a detached one-output-pixel line above its treetop.
    Periodic context remains unchanged on edges that actually contain artwork.
    """
    padded = _pad(mask, padding, periodic=True)
    if mask[0].all():
        padded[:padding] = True
    if mask[-1].all():
        padded[-padding:] = True
    if mask[:, 0].all():
        padded[:, :padding] = True
    if mask[:, -1].all():
        padded[:, -padding:] = True
    return padded


def apply_alpha_test_mask(
    source: Image.Image,
    generated: Image.Image,
    *,
    periodic: bool = False,
    padding: int = DEFAULT_EDGE_PADDING,
) -> Image.Image:
    """Apply the current keyed contour without repeating RGB inference.

    Existing opaque RGB is preserved exactly. Pixels exposed by a smoother
    contour are filled from adjacent inferred color before the new binary key
    mask is applied, so review candidates never reveal magenta-filled holes.
    """
    source_rgb = np.asarray(source.convert("RGB"), dtype=np.uint8)
    generated_rgb = np.asarray(generated.convert("RGB"), dtype=np.uint8).copy()
    if source.width <= 0 or source.height <= 0:
        msg = "alpha-test source dimensions must be positive"
        raise ValueError(msg)
    scale_x, remainder_x = divmod(generated.width, source.width)
    scale_y, remainder_y = divmod(generated.height, source.height)
    if remainder_x or remainder_y or scale_x != scale_y or scale_x <= 0:
        msg = "generated alpha-test texture must be an integer uniform scale of its source"
        raise ValueError(msg)

    source_mask = alpha_test_mask(source_rgb)
    if not source_mask.any():
        msg = "alpha-test source does not contain the GK3 color key"
        raise ValueError(msg)
    candidate_mask = np.all(generated_rgb == KEY_COLOR, axis=2)
    current_mask = upscale_key_mask(
        source_mask,
        scale_x,
        periodic=periodic,
        padding=padding,
    )
    # Removing an old opaque speck exposes background, not new artwork. Only
    # reconstruct hidden RGB when a formerly keyed pixel becomes opaque;
    # otherwise the full-resolution bleed would immediately be masked away.
    if np.any(candidate_mask & ~current_mask):
        if periodic and padding:
            output_padding = padding * scale_x
            filled = _bleed_key(
                _pad(generated_rgb, output_padding, periodic=True),
                _pad(candidate_mask, output_padding, periodic=True),
            )
            generated_rgb = _crop(filled, output_padding)
        else:
            generated_rgb = _bleed_key(generated_rgb, candidate_mask)
    generated_rgb[current_mask] = KEY_COLOR
    if source_mask[0, 0]:
        generated_rgb[0, 0] = KEY_COLOR
    return Image.fromarray(generated_rgb, mode="RGB")


def _upscale_key_mask_field(
    mask: np.ndarray, scale: int, *, sample_aligned: bool = False, bias: float = KEY_MASK_BIAS
) -> np.ndarray:
    """Enlarge one bounded signed-distance field and threshold it."""
    # SciPy is part of the local-upscaling extra and supplies its exact,
    # linear-time Euclidean distance transform. Keeping this out of the base
    # install preserves the lightweight texture-pack download workflow.
    from scipy.ndimage import distance_transform_edt  # noqa: PLC0415

    signed_distance = distance_transform_edt(mask) - distance_transform_edt(~mask)
    field = Image.fromarray(signed_distance.astype(np.float32), mode="F")
    size = (mask.shape[1] * scale, mask.shape[0] * scale)
    if sample_aligned:
        aligned = field.transform(
            size,
            Image.Transform.AFFINE,
            (1 / scale, 0, -0.5 / scale, 0, 1 / scale, -0.5 / scale),
            Image.Resampling.BILINEAR,
        )
        return np.asarray(aligned, dtype=np.float32) > 0
    enlarged = np.asarray(field.resize(size, Image.Resampling.BILINEAR), dtype=np.float32)
    return enlarged > bias


def _pad(array: np.ndarray, amount: int, *, periodic: bool) -> np.ndarray:
    """Pad spatial axes with wrap or reflection while retaining channels."""
    if amount == 0:
        return array.copy()
    spatial = ((amount, amount), (amount, amount))
    widths = (*spatial, (0, 0)) if array.ndim == RGB_DIMENSIONS else spatial
    return np.pad(array, widths, mode="wrap" if periodic else "reflect")


def _crop(array: np.ndarray, amount: int) -> np.ndarray:
    """Remove equally sized spatial context from all edges."""
    if amount == 0:
        return array.copy()
    return array[amount:-amount, amount:-amount].copy()
