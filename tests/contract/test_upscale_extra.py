"""Contract tests for the optional local-upscaling environment."""

from __future__ import annotations

import tomllib
from pathlib import Path

EXPECTED_UPSCALE_DEPENDENCIES = {
    "diffusers",
    "einops",
    "freetype-py",
    "huggingface-hub",
    "numpy",
    "rotary-embedding-torch",
    "safetensors",
    "scipy",
    "torch",
}


def test_upscale_extra_declares_every_direct_backend_dependency() -> None:
    """The extra covers AI inference and optional supplied-font reconstruction."""
    project = Path(__file__).parents[2] / "pyproject.toml"
    configuration = tomllib.loads(project.read_text(encoding="utf-8"))
    requirements = configuration["project"]["optional-dependencies"]["upscale"]
    names = {
        requirement.split("<", maxsplit=1)[0]
        .split(">", maxsplit=1)[0]
        .split("=", maxsplit=1)[0]
        .strip()
        for requirement in requirements
    }

    assert names == EXPECTED_UPSCALE_DEPENDENCIES
