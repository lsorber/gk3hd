"""Resource-aware texture analysis and deterministic manifest serialization."""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from gk3hd.textures.analyze.classify import classify_texture
from gk3hd.textures.analyze.policy import load_policy
from gk3hd.textures.analyze.usage import analyze_usage, discover_data_directory
from gk3hd.textures.bmp import BmpInfo, inspect_bmp
from gk3hd.textures.model import (
    TEXTURE_MANIFEST_SCHEMA_VERSION,
    PipelineOverride,
    TextureFeatures,
    TextureKind,
    TextureManifest,
)
from gk3hd.textures.routing import Pipeline, PipelineKind, plan_texture
from gk3hd.textures.upscale.cursor_art import CURSOR_OPACITY_PAIRS
from gk3hd.textures.workspace import analysis_file

if TYPE_CHECKING:
    from gk3hd.textures.analyze.usage import TextureUsage

TextureProgress = Callable[[int, int], None]


class FeatureManifestVersionError(ValueError):
    """Report a manifest created for a different feature schema."""


def load_feature_manifest(path: Path) -> Mapping[str, TextureFeatures]:
    """Load the current feature manifest without importing the optional pipeline."""
    source = path.resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"cannot read feature manifest {source}: {exc}"
        raise ValueError(msg) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != TEXTURE_MANIFEST_SCHEMA_VERSION
    ):
        msg = f"{source}: expected texture schema_version {TEXTURE_MANIFEST_SCHEMA_VERSION}"
        raise FeatureManifestVersionError(msg)
    entries = payload.get("textures")
    if not isinstance(entries, list):
        msg = f"{source}: expected a textures array"
        raise TypeError(msg)
    result: dict[str, TextureFeatures] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            msg = f"{source}: textures[{index}] must contain a string name"
            raise TypeError(msg)
        name = Path(entry["name"]).name.upper()
        if name in result:
            msg = f"{source}: duplicate texture {name}"
            raise ValueError(msg)
        features = TextureFeatures(name=name).with_overrides(entry)
        if "pipeline_override" in entry:
            features = replace(
                features, pipeline_override=PipelineOverride.from_dict(entry["pipeline_override"])
            )
        if "processing" in entry and entry["processing"] != plan_texture(features).to_dict():
            msg = f"{source}: stale processing decision for {name}; run textures analyze again"
            raise FeatureManifestVersionError(msg)
        result[name] = features
    return result


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    """Manifest plus concise counts for CLI reporting."""

    manifest: TextureManifest
    routes: Mapping[PipelineKind, int]
    unused_overrides: tuple[str, ...] = ()

    @property
    def todos(self) -> tuple[TextureFeatures, ...]:
        """Expose temporary choices rather than counting them as settled decisions."""
        return tuple(
            item
            for item in self.manifest.textures
            if item.pipeline_override is not None and item.pipeline_override.status == "todo"
        )

    @property
    def pipelines(self) -> Mapping[Pipeline, int]:
        """Count broad methods without hiding the detailed recipe breakdown."""
        counts: Counter[Pipeline] = Counter()
        for route, count in self.routes.items():
            counts[route.pipeline] += count
        return {pipeline: counts[pipeline] for pipeline in Pipeline}


def analyze_directory(
    directory: Path,
    *,
    overrides: Path | None = None,
    allow_unused_overrides: bool = False,
    progress: Callable[[int, int], None] | None = None,
    usage: TextureUsage | None = None,
) -> AnalysisReport:
    """Analyze every BMP recursively and return a deterministic manifest."""
    root = directory.resolve()
    if not root.is_dir():
        detail = f"BMP directory does not exist: {root}"
        raise ValueError(detail)
    paths = sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.casefold() == ".bmp"),
        key=lambda path: (path.name.casefold(), str(path).casefold()),
    )
    if not paths:
        detail = f"no BMP files found under {root}"
        raise ValueError(detail)

    by_name: dict[str, Path] = {}
    image_info: dict[str, BmpInfo] = {}
    total = len(paths)
    for index, path in enumerate(paths, start=1):
        name = path.name.upper()
        previous = by_name.get(name)
        if previous is not None:
            msg = f"duplicate texture name {name}: {previous} and {path}"
            raise ValueError(msg)
        by_name[name] = path
        image_info[name] = inspect_bmp(path)
        if progress is not None:
            progress(index, total)

    policy = load_policy(overrides)
    unknown = sorted(policy.names - set(image_info))
    if unknown and overrides is not None and not allow_unused_overrides:
        sample = ", ".join(unknown[:5])
        detail = f"overrides contain {len(unknown)} unknown texture(s): {sample}"
        raise ValueError(detail)

    textures = []
    for name, info in sorted(image_info.items()):
        features = classify_texture(
            name,
            info,
            image_info,
            action_button=usage is not None
            and name in usage.action_buttons
            and name not in usage.fonts,
            toolbar_button=usage is not None
            and name in usage.toolbar_buttons
            and name not in usage.fonts,
        )
        if usage is not None:
            features = _apply_usage(features, usage)
        textures.append(policy.apply(features, info))
    if usage is not None:
        textures = _couple_cursor_opacity(textures, image_info, usage)
    textures = _couple_reconstructed_cursors(textures, image_info)
    manifest = TextureManifest(textures=tuple(textures))
    routes = Counter(plan_texture(texture).kind for texture in textures)
    return AnalysisReport(
        manifest=manifest,
        routes=dict(routes),
        unused_overrides=tuple(unknown),
    )


def _apply_usage(features: TextureFeatures, usage: TextureUsage) -> TextureFeatures:
    """Let explicit data bindings supersede appearance-based artwork guesses."""
    if features.name in usage.data:
        features = TextureFeatures(name=features.name, kind=TextureKind.DATA)
    return features.with_overrides(
        {
            "tiled": features.name in usage.tiled,
            "font_atlas": features.kind is not TextureKind.DATA and features.name in usage.fonts,
        }
    )


def _couple_reconstructed_cursors(
    textures: list[TextureFeatures], images: Mapping[str, BmpInfo]
) -> list[TextureFeatures]:
    """Never enlarge only one layer of a verified color/opacity cursor pair.

    This contract also applies to standalone extracted folders without BRNs.
    Missing companions or explicit retention of either layer retain both;
    inconsistent source geometry is an error rather than an unsafe replacement.
    """
    by_name = {texture.name: texture for texture in textures}
    for color_name, opacity_name in CURSOR_OPACITY_PAIRS.items():
        members = [by_name[name] for name in (color_name, opacity_name) if name in by_name]
        complete = color_name in by_name and opacity_name in by_name
        if complete:
            color, opacity = images[color_name], images[opacity_name]
            if (color.width, color.height) != (opacity.width, opacity.height):
                msg = f"cursor {color_name} and opacity {opacity_name}: different source dimensions"
                raise ValueError(msg)
        if not complete or any(plan_texture(member).kind.keeps_native_size for member in members):
            for member in members:
                by_name[member.name] = member.with_overrides({"native_size": True})
    return [by_name[texture.name] for texture in textures]


def _couple_cursor_opacity(
    textures: list[TextureFeatures], images: Mapping[str, BmpInfo], usage: TextureUsage
) -> list[TextureFeatures]:
    """Keep declared opacity at its retained cursor's density, not independently 4x."""
    by_name = {texture.name: texture for texture in textures}
    for color_name, opacity_name in sorted(usage.cursor_opacity_pairs):
        color, opacity = by_name.get(color_name), by_name.get(opacity_name)
        if color is None or opacity is None or opacity.kind is not TextureKind.ALPHA:
            continue
        color_info, opacity_info = images[color_name], images[opacity_name]
        if (color_info.width, color_info.height) != (opacity_info.width, opacity_info.height):
            msg = f"cursor {color_name} and opacity {opacity_name} have different source dimensions"
            raise ValueError(msg)
        if plan_texture(color).kind.keeps_native_size:
            by_name[opacity_name] = opacity.with_overrides({"native_size": True})
    return [by_name[texture.name] for texture in textures]


def write_manifest(manifest: TextureManifest, output: Path) -> None:
    """Atomically write a reproducible UTF-8 JSON manifest."""
    target = output.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    document = manifest.to_dict()
    document["textures"] = [
        {**texture.to_dict(), "processing": plan_texture(texture).to_dict()}
        for texture in manifest.textures
    ]
    payload = json.dumps(document, indent=2, sort_keys=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def analyze(
    source: Path,
    output: Path | None = None,
    *,
    overrides: Path | None = None,
    progress: TextureProgress | None = None,
    data_directory: Path | None = None,
) -> AnalysisReport:
    """Classify extracted BMPs and write their deterministic feature manifest."""
    source = source.resolve()
    destination = analysis_file(source, output)
    metadata_directory = data_directory or discover_data_directory(source)
    usage = (
        analyze_usage(metadata_directory, progress=progress)
        if metadata_directory is not None
        else None
    )
    report = analyze_directory(
        source,
        overrides=overrides,
        progress=progress,
        usage=usage,
    )
    write_manifest(report.manifest, destination)
    return report
