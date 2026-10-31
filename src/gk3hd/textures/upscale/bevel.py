"""Reconstruct flat shaded controls without inferred bevels or shifted corners."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image


def reconstruct_bevel(image: Image) -> Image:
    """Smooth the authored shade-region contours and retain every native sample.

    The four dominant colors describe the face, two bevel sides and surround.
    Signed distances give their diagonal boundaries smooth coverage at 4x.
    A registered residual preserves authored minor shades and source samples,
    rather than replacing the original directional shadow with a generic bevel.
    """
    import numpy as np  # noqa: PLC0415
    from PIL import Image as PillowImage  # noqa: PLC0415
    from scipy.ndimage import distance_transform_edt  # noqa: PLC0415

    from gk3hd.textures.upscale.pipeline import resample_monotone_art  # noqa: PLC0415

    scale = 4
    pixels = np.asarray(image.convert("RGB"), dtype=np.float64)
    height, width, _ = pixels.shape
    palette, counts = np.unique(pixels.reshape(-1, 3), axis=0, return_counts=True)
    palette = palette[np.argsort(counts)[-4:]]
    if len(palette) < scale:
        return resample_monotone_art(image)
    labels = np.argmin(np.sum((pixels[:, :, None] - palette) ** 2, axis=3), axis=2)
    size = (width * scale, height * scale)

    def enlarge(field: np.ndarray) -> np.ndarray:
        # The game's native-size sample lands at output (4*x+2, 4*y+2).
        return np.asarray(
            PillowImage.fromarray(field.astype(np.float32)).transform(
                size,
                PillowImage.Transform.AFFINE,
                (1 / scale, 0, -0.5 / scale, 0, 1 / scale, -0.5 / scale),
                PillowImage.Resampling.BICUBIC,
            )
        )

    weights = []
    for index in range(len(palette)):
        mask = labels == index
        field = distance_transform_edt(mask) - distance_transform_edt(~mask)
        field -= 0.5 * np.sign(field)
        weights.append(1 / (1 + np.exp(np.clip(-enlarge(field) * 8, -50, 50))))
    coverage = np.stack(weights, axis=2)
    coverage /= np.maximum(coverage.sum(axis=2, keepdims=True), 1e-12)
    result = coverage @ palette
    residual = pixels - result[2::scale, 2::scale]
    result += np.stack([enlarge(residual[:, :, c]) for c in range(3)], axis=2)
    return PillowImage.fromarray(np.clip(np.rint(result), 0, 255).astype("uint8"))
