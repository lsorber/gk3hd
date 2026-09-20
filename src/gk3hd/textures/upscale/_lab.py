"""Torch-only LAB color correction matching numz's recommended SeedVR2 path.

The correction first combines generated detail with the low-frequency color of
the resized source, then histogram-matches CIELAB channels.  Keeping this here
avoids the torchvision and OpenCV dependencies of general-purpose color tools.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import torch
import torch.nn.functional

if TYPE_CHECKING:
    from torch import Tensor

SRGB_LINEAR_THRESHOLD = 0.04045
SRGB_GAMMA_THRESHOLD = 0.0031308


def _resize(image: Tensor, size: tuple[int, int]) -> Tensor:
    """Resize in float32 when a backend lacks half-precision interpolation."""
    try:
        return torch.nn.functional.interpolate(
            image, size=size, mode="bilinear", align_corners=False
        )
    except RuntimeError as exc:
        if "not implemented" not in str(exc) and "compute_indices_weights" not in str(exc):
            raise
        return torch.nn.functional.interpolate(
            image.float(), size=size, mode="bilinear", align_corners=False
        ).to(image.dtype)


def _blur(image: Tensor, radius: int) -> Tensor:
    """Apply numz's small dilated Gaussian kernel for one wavelet level."""
    radius = min(radius, max(1, min(image.shape[-2:]) // 8))
    values = [[0.0625, 0.125, 0.0625], [0.125, 0.25, 0.125], [0.0625, 0.125, 0.0625]]
    kernel = torch.tensor(values, dtype=image.dtype, device=image.device)
    kernel = kernel[None, None].repeat(image.shape[1], 1, 1, 1)
    try:
        padded = torch.nn.functional.pad(image, (radius,) * 4, mode="replicate")
    except RuntimeError as exc:
        if "not implemented" not in str(exc):
            raise
        padded = torch.nn.functional.pad(image.float(), (radius,) * 4, mode="replicate").to(
            image.dtype
        )
    return torch.nn.functional.conv2d(padded, kernel, groups=image.shape[1], dilation=radius)


def _wavelet_parts(image: Tensor, levels: int = 5) -> tuple[Tensor, Tensor]:
    """Split an image into accumulated high and low spatial frequencies."""
    high = torch.zeros_like(image)
    for level in range(levels):
        low = _blur(image, 2**level)
        high.add_(image).sub_(low)
        image = low
    return high, low


def _wavelet_reconstruct(content: Tensor, reference: Tensor) -> Tensor:
    """Preserve generated detail while restoring source low-frequency color."""
    if content.shape != reference.shape:
        reference = _resize(reference, (content.shape[-2], content.shape[-1]))
    content_high, _ = _wavelet_parts(content)
    _, reference_low = _wavelet_parts(reference)
    return content_high.add_(reference_low).clamp_(-1.0, 1.0)


def _rgb_to_lab(rgb: Tensor, matrix: Tensor, epsilon: float, kappa: float) -> Tensor:
    """Convert a batch of sRGB tensors in [0, 1] to D65 CIELAB."""
    linear = torch.where(
        rgb > SRGB_LINEAR_THRESHOLD,
        torch.pow((rgb + 0.055) / 1.055, 2.4),
        rgb / 12.92,
    )
    batch, _, height, width = linear.shape
    flat = linear.permute(0, 2, 3, 1).reshape(-1, 3).to(matrix.dtype)
    xyz = torch.matmul(flat, matrix.T).reshape(batch, height, width, 3).permute(0, 3, 1, 2)
    xyz[:, 0].div_(0.95047)
    xyz[:, 2].div_(1.08883)
    f_xyz = torch.where(
        xyz > epsilon**3,
        torch.pow(xyz, 1.0 / 3.0),
        xyz.mul(kappa).add_(16.0).div_(116.0),
    )
    lightness = f_xyz[:, 1].mul(116.0).sub_(16.0)
    green_red = (f_xyz[:, 0] - f_xyz[:, 1]).mul_(500.0)
    blue_yellow = (f_xyz[:, 1] - f_xyz[:, 2]).mul_(200.0)
    return torch.stack([lightness, green_red, blue_yellow], dim=1)


def _lab_to_rgb(lab: Tensor, matrix: Tensor, epsilon: float, kappa: float) -> Tensor:
    """Convert a D65 CIELAB batch back to sRGB in [0, 1]."""
    lightness, green_red, blue_yellow = lab[:, 0], lab[:, 1], lab[:, 2]
    fy = (lightness + 16.0) / 116.0
    fx = green_red.div(500.0).add_(fy)
    fz = fy - blue_yellow / 200.0

    def invert(channel: Tensor) -> Tensor:
        return torch.where(
            channel > epsilon,
            torch.pow(channel, 3.0),
            channel.mul(116.0).sub_(16.0).div_(kappa),
        )

    x, y, z = invert(fx), invert(fy), invert(fz)
    x.mul_(0.95047)
    z.mul_(1.08883)
    xyz = torch.stack([x, y, z], dim=1)
    batch, _, height, width = xyz.shape
    flat = xyz.permute(0, 2, 3, 1).reshape(-1, 3).to(matrix.dtype)
    linear = torch.matmul(flat, matrix.T).reshape(batch, height, width, 3).permute(0, 3, 1, 2)
    rgb = torch.where(
        linear > SRGB_GAMMA_THRESHOLD,
        torch.pow(linear.clamp_min(0.0), 1.0 / 2.4).mul_(1.055).sub_(0.055),
        linear * 12.92,
    )
    return rgb.clamp_(0.0, 1.0)


def _match_histogram(source: Tensor, reference: Tensor) -> Tensor:
    """Map one flattened channel to the reference channel's quantiles."""
    shape = source.shape
    source_sorted, indices = torch.sort(source.flatten())
    reference_sorted, _ = torch.sort(reference.flatten())
    if len(source_sorted) == len(reference_sorted):
        matched = reference_sorted
    else:
        quantiles = torch.linspace(0, 1, len(source_sorted), device=source.device)
        reference_indices = (quantiles * (len(reference_sorted) - 1)).long()
        matched = reference_sorted[reference_indices.clamp_(0, len(reference_sorted) - 1)]
    return matched[torch.argsort(indices)].reshape(shape)


def lab_color_transfer(
    content: Tensor,
    reference: Tensor,
    *,
    luminance_weight: float = 0.8,
) -> Tensor:
    """Apply the LAB correction used by numz's recommended upscaling path.

    Args:
        content: Generated RGB batch in ``[-1, 1]`` and ``BCHW`` layout.
        reference: Resized source RGB batch with the same conventions.
        luminance_weight: Fraction of generated luminance to retain. Numz uses
            ``0.8``, which corrects color while preserving most new detail.
    """
    if not 0.0 <= luminance_weight <= 1.0:
        msg = "luminance_weight must be between 0 and 1"
        raise ValueError(msg)
    content = _wavelet_reconstruct(content, reference)
    if content.shape != reference.shape:
        reference = _resize(reference, (content.shape[-2], content.shape[-1]))
    original_dtype = content.dtype
    content = content.float().add_(1.0).mul_(0.5).clamp_(0.0, 1.0)
    reference = reference.float().add_(1.0).mul_(0.5).clamp_(0.0, 1.0)
    device = content.device
    rgb_to_xyz = torch.tensor(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ],
        dtype=torch.float32,
        device=device,
    )
    xyz_to_rgb = torch.tensor(
        [
            [3.2404542, -1.5371385, -0.4985314],
            [-0.9692660, 1.8760108, 0.0415560],
            [0.0556434, -0.2040259, 1.0572252],
        ],
        dtype=torch.float32,
        device=device,
    )
    epsilon = 6.0 / 29.0
    kappa = (29.0 / 3.0) ** 3
    content_lab = _rgb_to_lab(content, rgb_to_xyz, epsilon, kappa)
    reference_lab = _rgb_to_lab(reference, rgb_to_xyz, epsilon, kappa)
    matched_lightness = _match_histogram(content_lab[:, 0], reference_lab[:, 0])
    lightness = content_lab[:, 0] * luminance_weight + matched_lightness * (1.0 - luminance_weight)
    result_lab = torch.stack(
        [
            lightness,
            _match_histogram(content_lab[:, 1], reference_lab[:, 1]),
            _match_histogram(content_lab[:, 2], reference_lab[:, 2]),
        ],
        dim=1,
    )
    result = _lab_to_rgb(result_lab, xyz_to_rgb, epsilon, kappa).mul_(2.0).sub_(1.0)
    return result.to(original_dtype)
