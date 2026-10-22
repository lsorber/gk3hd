"""Exact-weight transformer block offloading for large temporal movie inputs."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import torch
    from torch import nn


def enable_block_offload(model: nn.Module, device: torch.device) -> None:
    """Transfer one block's unchanged weights at a time, not its activations.

    All attention still runs on the complete input on the selected GPU. Post
    hooks run on failure too, so a failed clip cannot strand a block in VRAM.
    Transfers preserve parameter dtype and do not replace forward results.
    """

    def load(block: nn.Module, _inputs: tuple[object, ...]) -> None:
        block.to(device=device)

    def unload(block: nn.Module, _inputs: tuple[object, ...], _output: object) -> None:
        block.to(device="cpu")

    for block in model.get_submodule("blocks").children():
        block.to(device="cpu")
        block.register_forward_pre_hook(load)
        block.register_forward_hook(unload, always_call=True)


def activate_transformer(model: nn.Module, device: torch.device) -> None:
    """Load shared projections while block hooks own block-weight residency."""
    for name, module in model.named_children():
        if name != "blocks":
            module.to(device=device)
