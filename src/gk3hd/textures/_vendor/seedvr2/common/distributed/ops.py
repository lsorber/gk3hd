"""Identity implementations of SeedVR2 sequence-parallel tensor operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import torch


def slice_inputs(x: torch.Tensor, dim: int, padding: bool = True) -> torch.Tensor:
    """Return the complete tensor for single-device inference."""
    del dim, padding
    return x


def gather_outputs(x: torch.Tensor, **kwargs: Any) -> torch.Tensor:
    """Return the complete tensor for single-device inference."""
    del kwargs
    return x


def gather_heads_scatter_seq(
    x: torch.Tensor,
    head_dim: int,
    seq_dim: int,
) -> torch.Tensor:
    """Return attention output unchanged on one device."""
    del head_dim, seq_dim
    return x


def gather_seq_scatter_heads_qkv(
    qkv_tensor: torch.Tensor,
    **kwargs: Any,
) -> torch.Tensor:
    """Return QKV projections unchanged on one device."""
    del kwargs
    return qkv_tensor
