"""Bind cached inference and opacity outputs to their source and processing plan."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from gk3hd.textures.routing import PipelineKind

if TYPE_CHECKING:
    from pathlib import Path

    from gk3hd.textures.routing import PipelinePlan

GENERATION_STAMP = "gk3hd-generation"
ALPHA_STAMP = "gk3hd-alpha-result"
# Bump when inference preprocessing, model weights/defaults, or scalar-alpha
# reconstruction changes. Key-mask-only corrections are verified independently
# and may reuse RGB with this exact same source/inference stamp.
GENERATION_REVISION = 1
STAMPED_ROUTES = frozenset(
    {
        PipelineKind.COLOR_AI,
        PipelineKind.FACE_LAYER_AI,
        PipelineKind.ALPHA_TEST_AI,
        PipelineKind.ALPHA_SMOOTH,
        PipelineKind.ALPHA_AI,
    }
)


def generation_stamp(source: Path, plan: PipelinePlan) -> str:
    """Identify source bytes and effective settings without machine-specific paths."""
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    stamp = f"{GENERATION_REVISION}:{plan.kind}:{int(plan.periodic)}:{digest}"
    if plan.source_regions:
        recipe = hashlib.sha256(repr(plan.source_regions).encode("ascii")).hexdigest()
        stamp += f":regions:{recipe}"
    if plan.kind is PipelineKind.FACE_LAYER_AI:
        from gk3hd.textures.upscale.face_layer import face_layer_stamp  # noqa: PLC0415

        stamp += f":{face_layer_stamp(source, detail_sharpening=plan.detail_sharpening)}"
    if source.name.upper() == "DM_BASE.BMP":
        from gk3hd.textures.upscale.driving_map import map_artwork_stamp  # noqa: PLC0415

        stamp += f":map:{map_artwork_stamp(source)}"
    return stamp


def verify_generation_stamp(source: Path, plan: PipelinePlan, expected: str) -> None:
    """Reject a source modified during inference before publishing its output."""
    if generation_stamp(source, plan) != expected:
        msg = "source changed during upscaling; rerun with a stable source folder"
        raise ValueError(msg)
