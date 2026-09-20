"""Conservative output checks for AI-generated scalar opacity."""

import json

import numpy as np
from PIL import Image
from scipy.ndimage import binary_erosion, binary_fill_holes, distance_transform_edt, label

from gk3hd.textures.upscale.generation import ALPHA_STAMP

_THRESHOLDS = (64, 128, 192)
_AREA_TOLERANCE = 0.02
_CONNECTIVITY = np.ones((3, 3), dtype=bool)
ALPHA_GUARD_VERSION = 1


def alpha_rejection_reasons(
    original: Image.Image, candidate: Image.Image, scale: int
) -> tuple[str, ...]:
    """Compare area, contour displacement, components and holes at three thresholds.

    Distances are in original pixels. Exact tiny parts are deliberately protected;
    a false rejection falls back to resampling, rather than deleting detail.
    """
    native = np.asarray(original.convert("L"))
    generated = np.asarray(candidate.convert("L"))
    if generated.shape != (native.shape[0] * scale, native.shape[1] * scale):
        return ("invalid-dimensions",)
    reasons = set()
    coverage = float(native.sum()) * scale**2
    if abs(float(generated.sum()) - coverage) > _AREA_TOLERANCE * max(1, coverage):
        reasons.add("coverage-change")
    for threshold in _THRESHOLDS:
        reference = np.repeat(np.repeat(native >= threshold, scale, axis=0), scale, axis=1)
        proposed = generated >= threshold
        area = int(reference.sum())
        if abs(int(proposed.sum()) - area) > _AREA_TOLERANCE * max(1, area):
            reasons.add("area-change")
        contour = reference ^ binary_erosion(reference, border_value=0)
        distance = distance_transform_edt(~contour)
        if np.any((reference ^ proposed) & (distance > scale)):
            reasons.add("contour-shift")
        if _topology(reference) != _topology(proposed):
            reasons.add("changed-holes-or-parts")
    return tuple(sorted(reasons))


def _topology(mask: np.ndarray) -> tuple[int, int]:
    """Count eight-connected artwork and four-connected enclosed holes."""
    return int(label(mask, structure=_CONNECTIVITY)[1]), int(
        label(binary_fill_holes(mask) & ~mask)[1]
    )


def alpha_result_method(image: Image.Image) -> str | None:
    """Read only a recognized result; older guard recipes require regeneration."""
    try:
        result = json.loads(str(image.info.get(ALPHA_STAMP, "")))
    except (ValueError, TypeError):
        return None
    if not isinstance(result, dict) or result.get("version") != ALPHA_GUARD_VERSION:
        return None
    method = result.get("method")
    return method if isinstance(method, str) and method in {"ai", "lanczos"} else None
