"""Conventional local paths for the texture-development workflow."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

WORK_DIRECTORY = "gk3hd"
TEXTURES_DIRECTORY = "textures"
SOURCE_DIRECTORY = "original"
UPSCALE_DIRECTORY = "upscaled"
INSTALL_DIRECTORY = "installed"
COMPARISONS_DIRECTORY = "comparisons"
ANALYSIS_FILENAME = "texture-analysis.json"
PACK_LOCK_FILENAME = "texture-pack-lock.json"
TEXTURE_PACK_REPOSITORY = "https://github.com/lsorber/gk3hd"


def workspace_directory(game_directory: Path) -> Path:
    """Return the conventional workspace beside a GK3 executable."""
    return game_directory.resolve() / WORK_DIRECTORY


def source_directory(game_directory: Path) -> Path:
    """Return the conventional extracted-texture directory."""
    return texture_workspace_directory(game_directory) / SOURCE_DIRECTORY


def texture_workspace_directory(game_directory: Path) -> Path:
    """Return the container for every texture workflow stage."""
    return workspace_directory(game_directory) / TEXTURES_DIRECTORY


def analysis_file(source: Path, output: Path | None = None) -> Path:
    """Resolve an override or the manifest beside all texture stage directories."""
    return (output if output is not None else source.parent / ANALYSIS_FILENAME).resolve()


def adjacent_stage(source: Path, name: str) -> Path:
    """Place a derived stage beside its input directory."""
    return source.resolve().parent / name


def release_base_url(version: str) -> str:
    """Return the predictable future GitHub release URL for a pack version."""
    tag = version if version.startswith("v") else f"v{version}"
    return f"{TEXTURE_PACK_REPOSITORY}/releases/download/{tag}"


def texture_pack_filename(version: str) -> str:
    """Return the versioned texture-pack release asset name."""
    tag = version if version.startswith("v") else f"v{version}"
    return f"gk3hd-texture-pack-{tag}.zip"
