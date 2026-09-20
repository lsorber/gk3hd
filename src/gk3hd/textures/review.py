"""Generate explicitly experimental texture alternatives without installing them."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from rich.console import Console
from rich.progress import Progress

from gk3hd.system.discovery import discover_game
from gk3hd.system.files import atomic_write
from gk3hd.textures.analyze.manifest import load_feature_manifest
from gk3hd.textures.model import TextureFeatures, TextureKind
from gk3hd.textures.routing import Pipeline, PipelineKind, plan_texture
from gk3hd.textures.workspace import analysis_file

if TYPE_CHECKING:
    from gk3hd.textures.upscale.pipeline import ColorUpscaler

_STAMP = "gk3hd-review"
_REVISION = 2


class ReviewScope(StrEnum):
    """Select both original review groups or only remaining resampled results."""

    ALL = "all"
    RESAMPLED = "resampled"


def resampling_result(
    source: Path, features: TextureFeatures, upscaled: Path
) -> dict[str, object] | None:
    """Include analysis-selected resampling and validated, cached AI fallbacks.

    Refuse incomplete guarded outputs: otherwise missing inference would silently
    disappear from the review. Run the production upscaler first.
    """
    from gk3hd.textures.upscale.alpha_guard import alpha_result_method  # noqa: PLC0415
    from gk3hd.textures.upscale.generation import (  # noqa: PLC0415
        ALPHA_STAMP,
        GENERATION_STAMP,
        generation_stamp,
    )
    from gk3hd.textures.upscale.pipeline import is_current_alpha_output  # noqa: PLC0415

    plan = plan_texture(features)
    if plan.kind.pipeline is Pipeline.RESAMPLE:
        return {
            "method": "lanczos" if features.kind is TextureKind.ALPHA else "bicubic",
            "reason": "analysis",
        }
    if plan.kind is not PipelineKind.ALPHA_AI:
        return None
    destination = upscaled / source.with_suffix(".PNG").name
    with Image.open(source) as original, Image.open(destination) as candidate:
        if candidate.info.get(GENERATION_STAMP) != generation_stamp(source, plan) or not (
            is_current_alpha_output(original, candidate, periodic=plan.periodic)
        ):
            msg = f"run textures upscale first: guarded output is stale for {source.name}"
            raise ValueError(msg)
        if alpha_result_method(candidate) == "lanczos":
            return dict(json.loads(candidate.info[ALPHA_STAMP]))
    return None


def review_group(features: TextureFeatures) -> str | None:
    """Select all resampling and non-data retention decisions, including opacity."""
    pipeline = plan_texture(features).kind.pipeline
    if pipeline is Pipeline.RESAMPLE:
        return "bicubic-vs-ai"
    if pipeline is Pipeline.RETAIN and features.kind is not TextureKind.DATA:
        return "retained-vs-ai"
    return None


def experimental_features(features: TextureFeatures, image: Image.Image) -> TextureFeatures:
    """Retain edge/key semantics but bypass production retention/recipe decisions.

    Opacity is deliberately shown as an RGB AI experiment, not promoted to a
    valid opacity replacement. Atlas markers and glyph metrics are not repaired.
    """
    key_present = (255, 0, 255) in image.convert("RGB").get_flattened_data()
    return TextureFeatures(name="REVIEW.BMP", tiled=features.tiled, alphatest=key_present)


def _save(image: Image.Image, path: Path, stamp: str) -> None:
    metadata = PngInfo()
    metadata.add_text(_STAMP, stamp)
    buffer = BytesIO()
    image.save(buffer, format="PNG", pnginfo=metadata)
    atomic_write(path, buffer.getvalue())


def _current(path: Path, stamp: str) -> bool:
    if not path.is_file():
        return False
    try:
        with Image.open(path) as image:
            image.load()
            return image.info.get(_STAMP) == stamp
    except OSError:
        return False


def write_pair(
    source: Path,
    features: TextureFeatures,
    output: Path,
    upscaler: ColorUpscaler,
    *,
    result: dict[str, object] | None = None,
) -> dict[str, object]:
    """Write/resume two adjacent PNGs, with source-bound provenance per image."""
    from gk3hd.textures.upscale.pipeline import (  # noqa: PLC0415
        apply_alpha_test_mask,
        upscale_smooth_color,
        upscale_texture,
    )

    group = "remaining-resampling" if result is not None else review_group(features)
    if group is None:
        msg = f"not a review candidate: {features.name}"
        raise ValueError(msg)
    payload = source.read_bytes()
    decision = plan_texture(features).to_dict()
    row: dict[str, object] = {
        "source": features.name,
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "features": features.to_dict(),
        "production": decision,
        "revision": _REVISION,
        "experimental": True,
        "result": result,
    }
    stamp = json.dumps(row, sort_keys=True)
    folder = output / group
    folder.mkdir(parents=True, exist_ok=True)
    retained = group == "retained-vs-ai"
    label = (
        "retained-native"
        if retained
        else ("lanczos-4x" if features.kind is TextureKind.ALPHA else "bicubic-4x")
    )
    baseline = folder / f"{source.stem}--1-{label}.png"
    candidate = folder / f"{source.stem}--2-seedvr2-4x.png"
    with Image.open(BytesIO(payload)) as opened:
        original = opened.convert("RGB")
    preview = experimental_features(features, original)
    if not _current(baseline, stamp) or preview.alphatest:
        if retained:
            image = original
        elif features.kind is TextureKind.ALPHA:
            image = upscale_texture(original, features.with_overrides({"alpha_silhouette": False}))
        else:
            image = upscale_smooth_color(
                original, periodic=features.tiled, alphatest=preview.alphatest
            )
        _save(image, baseline, stamp)
    if not _current(candidate, stamp):
        generated = upscale_texture(original, preview, upscaler=upscaler)
        if features.kind is TextureKind.ALPHA:
            generated = generated.convert("L")
        _save(generated, candidate, stamp)
    elif preview.alphatest:
        # Mask fixes do not invalidate expensive, unchanged RGB inference.
        with Image.open(candidate) as cached:
            refreshed = apply_alpha_test_mask(original, cached, periodic=preview.tiled)
            changed = refreshed.tobytes() != cached.convert("RGB").tobytes()
        if changed:
            _save(refreshed, candidate, stamp)
    row.update(baseline=baseline.name, candidate=candidate.name, original_size=original.size)
    return row


def review(
    game_dir: Annotated[Path | None, typer.Option(help="Discovered automatically.")] = None,
    output: Annotated[Path, typer.Option(help="Review folders are created here.")] = Path(
        "build/texture-review"
    ),
    source: Annotated[Path | None, typer.Option(help="Extracted BMP folder.")] = None,
    scope: Annotated[ReviewScope, typer.Option(help="Resampled includes guarded AI fallbacks.")] = (
        ReviewScope.ALL
    ),
) -> None:
    """Compare bicubic and retained artwork with SeedVR2; never install candidates."""
    from gk3hd.textures.upscale.seedvr2 import SeedVR2Upscaler  # noqa: PLC0415

    if source is None:
        source = discover_game(game_dir=game_dir).game_dir / "gk3hd/textures/original"
    manifest = load_feature_manifest(analysis_file(source))
    selected = []
    for feature in sorted(manifest.values(), key=lambda item: item.name):
        result = (
            resampling_result(source / feature.name, feature, source.parent / "upscaled")
            if scope is ReviewScope.RESAMPLED
            else None
        )
        if result is not None or (scope is ReviewScope.ALL and review_group(feature)):
            selected.append((feature, result))
    upscaler = SeedVR2Upscaler()
    console = Console()
    console.print(f"Review only: {len(selected)} pairs; AI device: {upscaler.device}")
    rows: dict[str, list[dict[str, object]]] = {}
    with Progress(console=console) as progress:
        task = progress.add_task("Generating review pairs", total=len(selected))
        for feature, result in selected:
            group = "remaining-resampling" if result is not None else review_group(feature)
            if group is None:
                continue
            rows.setdefault(group, []).append(
                write_pair(source / feature.name, feature, output, upscaler, result=result)
            )
            atomic_write(
                output / group / "_review.json",
                (json.dumps(rows[group], indent=2) + "\n").encode(),
            )
            progress.update(task, advance=1, description=feature.name)
    console.print(f"Review folders: {output.resolve()}")
