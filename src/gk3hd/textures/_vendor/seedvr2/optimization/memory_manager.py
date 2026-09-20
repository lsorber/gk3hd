"""Only the OOM retry hooks required by the vendored VAE layers."""

from __future__ import annotations

import gc
from typing import TYPE_CHECKING, Any

import torch

if TYPE_CHECKING:
    from collections.abc import Callable


def is_mps_available() -> bool:
    """Return whether Apple's MPS backend is available."""
    return hasattr(torch.backends, "mps") and torch.backends.mps.is_available()


def retry_on_oom(
    func: Callable[..., Any],
    *args: Any,
    debug: Any = None,
    operation_name: str = "operation",
    **kwargs: Any,
) -> Any:
    """Retry one allocation after clearing accelerator caches.

    This retains numz's useful behavior without its process-monitoring and
    ComfyUI memory-management dependencies.
    """
    del debug, operation_name
    try:
        return func(*args, **kwargs)
    except (torch.cuda.OutOfMemoryError, RuntimeError) as exc:
        message = str(exc).casefold()
        if "out of memory" not in message and "allocation on device" not in message:
            raise
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        if is_mps_available():
            torch.mps.empty_cache()
        return func(*args, **kwargs)
