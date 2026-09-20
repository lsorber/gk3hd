"""Single-device substitutes for SeedVR2's training-time distributed helpers."""

from gk3hd.textures._vendor.seedvr2.common.distributed.basic import (
    get_device,
    get_global_rank,
    get_local_rank,
    get_world_size,
)

__all__ = ["get_device", "get_global_rank", "get_local_rank", "get_world_size"]
