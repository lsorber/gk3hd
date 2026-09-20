"""Single-process device helpers required by the vendored model code."""

from __future__ import annotations

import torch


def get_global_rank() -> int:
    """Return the only process rank supported by gk3hd.textures."""
    return 0


def get_local_rank() -> int:
    """Return the only local process rank supported by gk3hd.textures."""
    return 0


def get_world_size() -> int:
    """Return one because the inference runtime is intentionally single-device."""
    return 1


def get_device() -> torch.device:
    """Return the best accelerator available to PyTorch."""
    if torch.cuda.is_available():
        return torch.device("cuda", torch.cuda.current_device())
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")
