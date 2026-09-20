"""Build pinned native resources in the game workspace without installing them."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from gk3hd.renderer.artifact import RendererAsset, inspect_dll
from gk3hd.system.discovery import discover_game
from gk3hd.system.files import atomic_write

RECIPE = Path(__file__).resolve().parent


def workspace(game_dir: Path | None = None) -> Path:
    """Keep renderer sources and build records in the selected game's workspace."""
    return discover_game(game_dir=game_dir).game_dir / "gk3hd" / "renderer"


def local_build(*, game_dir: Path | None = None) -> RendererAsset:
    """Resolve and revalidate the last successful build, never guess by filename."""
    record = workspace(game_dir) / "latest.json"
    if not record.is_file():
        msg = "no local renderer build; run gk3hd renderer build first"
        raise ValueError(msg)
    data = json.loads(record.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("dll"), str):
        msg = "invalid local renderer build record"
        raise TypeError(msg)
    asset = inspect_dll(Path(data["dll"]))
    if asset.dll_sha256 != data.get("sha256") or data.get("recipe_sha256") != recipe_digest():
        msg = "local renderer or recipe changed; run gk3hd renderer build again"
        raise ValueError(msg)
    return asset


def recipe_digest() -> str:
    """Invalidate reuse when any native recipe, source patch or test changes."""
    inputs = sorted(
        path
        for path in RECIPE.rglob("*")
        if path.is_file() and path.suffix in {".ps1", ".patch", ".json", ".cpp", ".h", ".conf"}
    )
    digest = hashlib.sha256()
    for path in inputs:
        digest.update(path.relative_to(RECIPE).as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def build(
    *, game_dir: Path | None = None, output: Path | None = None, jobs: int = 12
) -> RendererAsset:
    """Reuse verified matching output, or build and test a fresh recipe directory."""
    if sys.platform != "win32":
        msg = "renderer builds require Windows with Visual Studio C++ Build Tools installed"
        raise ValueError(msg)
    shell = shutil.which("pwsh")
    if shell is None:
        msg = "PowerShell 7 (pwsh) is required for renderer builds"
        raise ValueError(msg)
    digest = recipe_digest()
    root = workspace(game_dir)
    target = (output or root / digest[:16]).resolve()
    pin = json.loads((RECIPE / "upstream.json").read_text(encoding="utf-8"))
    dll = target / f"d7vk-{pin['version']}.dll"
    if not target.exists():
        result = subprocess.run(  # noqa: S603 - fixed recipe and separate arguments.
            [
                shell,
                "-NoProfile",
                "-File",
                str(RECIPE / "build.ps1"),
                "-Jobs",
                str(jobs),
                "-OutputRoot",
                str(target),
            ],
            check=False,
        )
        if result.returncode:
            msg = f"renderer build failed (exit {result.returncode}); see build output"
            raise RuntimeError(msg)
    asset = inspect_dll(dll)
    if digest != recipe_digest():
        msg = "renderer recipe changed during compilation; rebuild before installing or releasing"
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
