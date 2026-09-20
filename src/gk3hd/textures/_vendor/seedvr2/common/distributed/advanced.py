"""No-op sequence-parallel API for single-device inference."""

from __future__ import annotations

from typing import Any


def get_sequence_parallel_group() -> None:
    """Return no process group; distributed inference is deliberately unsupported."""
    return None


def get_sequence_parallel_rank() -> int:
    """Return the sole sequence-parallel rank."""
    return 0


def get_sequence_parallel_world_size() -> int:
    """Return the sole sequence-parallel world size."""
    return 1


def __getattr__(name: str) -> Any:
    """Fail clearly if future vendored code asks for a distributed operation."""
    msg = f"distributed SeedVR2 operation is unavailable: {name}"
    raise AttributeError(msg)
