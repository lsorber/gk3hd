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
        PipelineKind.ALPHA_TEST_AI,
        PipelineKind.ALPHA_SMOOTH,
        PipelineKind.ALPHA_AI,
    }
)


def generation_stamp(source: Path, plan: PipelinePlan) -> str:
    """Identify source bytes and effective settings without machine-specific paths."""
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return f"{GENERATION_REVISION}:{plan.kind}:{int(plan.periodic)}:{digest}"


def verify_generation_stamp(source: Path, plan: PipelinePlan, expected: str) -> None:
    """Reject a source modified during inference before publishing its output."""
    if generation_stamp(source, plan) != expected:
        msg = "source changed during upscaling; rerun with a stable source folder"
        raise ValueError(msg)
