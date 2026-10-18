"""Build and revalidate opt-in VR prototypes separately from ordinary renderers."""

from __future__ import annotations

import json
from pathlib import Path

from gk3hd.renderer.build import compile_recipe, recipe_digest
from gk3hd.system.discovery import discover_game
from gk3hd.system.files import atomic_write
from gk3hd.vr.artifact import RECIPE, VRRendererAsset, inspect_vr_dll


def workspace(game_dir: Path | None = None) -> Path:
    """Keep prototype builds apart from the game's normal renderer build record."""
    return discover_game(game_dir=game_dir).game_dir / "gk3hd" / "vr" / "renderer"


def local_build(*, game_dir: Path | None = None) -> VRRendererAsset:
    """Require a recorded successful prototype with a still-matching recipe."""
    record = workspace(game_dir) / "latest.json"
    if not record.is_file():
        msg = "no verified local VR renderer build"
        raise ValueError(msg)
    data = json.loads(record.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("dll"), str):
        msg = "invalid local VR renderer build record"
        raise TypeError(msg)
    asset = inspect_vr_dll(Path(data["dll"]))
    if asset.dll_sha256 != data.get("sha256") or data.get("recipe_sha256") != recipe_digest():
        msg = "local VR renderer or recipe changed; rebuild before using it"
        raise ValueError(msg)
    return asset


def build(
    *, game_dir: Path | None = None, output: Path | None = None, jobs: int = 12
) -> VRRendererAsset:
    """Build/test a current prototype without installing, activating or publishing."""
    digest = recipe_digest()
    root = workspace(game_dir)
    target = (output or root / digest[:16]).resolve()
    pin = json.loads((RECIPE / "upstream.json").read_text(encoding="utf-8"))
    if not target.exists():
        compile_recipe(target, jobs=jobs, variant="openxr")
    asset = inspect_vr_dll(target / f"dxvk-sarek-{pin['version']}-xr-prototype.dll")
    if digest != recipe_digest():
        msg = "VR recipe changed during compilation; rebuild before using it"
        raise ValueError(msg)
    atomic_write(
        root / "latest.json",
        (
            json.dumps(
                {
                    "dll": str(asset.path.resolve()),
                    "sha256": asset.dll_sha256,
                    "recipe_sha256": digest,
                },
                indent=2,
            )
            + "\n"
        ).encode(),
    )
    return asset
