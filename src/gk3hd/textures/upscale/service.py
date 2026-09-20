"""Execute texture generation with validated resume and coordinated compositions."""

from __future__ import annotations

import os
import tempfile
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from gk3hd.textures.analyze.manifest import FeatureManifestVersionError, load_feature_manifest
from gk3hd.textures.analyze.manifest import analyze as analyze_textures
from gk3hd.textures.flat import (
    actual_files,
    explicit_dos_name_first,
    protect_short_name_alias,
    require_actual_file,
)
from gk3hd.textures.routing import PipelineKind, PipelinePlan, plan_texture
from gk3hd.textures.upscale.fonts.atlas import FONT_OUTLINE_STAMP, font_atlas_output_size
from gk3hd.textures.upscale.generation import (
    ALPHA_STAMP,
    GENERATION_STAMP,
    STAMPED_ROUTES,
    generation_stamp,
    verify_generation_stamp,
)
from gk3hd.textures.upscale.replacement import is_current_replacement, regenerate_replacement
from gk3hd.textures.upscale.sidney_frame import (
    FRAME_BATCH,
    FRAME_REGIONS,
    FRAME_STAMP,
    has_coherent_frame_outputs,
    is_current_frame,
    upscale_frame,
)
from gk3hd.textures.workspace import analysis_file

if TYPE_CHECKING:
    from gk3hd.textures.model import TextureFeatures
    from gk3hd.textures.progress import DownloadProgress
    from gk3hd.textures.upscale.fonts.outline import OutlineAtlas
    from gk3hd.textures.upscale.pipeline import ColorUpscaler
    from gk3hd.textures.upscale.seedvr2 import SeedVR2Upscaler

TextureProgress = Callable[[int, int], None]

BackendProgress = Callable[[str, bool], None]


@dataclass(frozen=True, slots=True)
class UpscaleReport:
    """Created, safely resumed, and deliberately untouched asset counts."""

    textures: int
    created: int
    skipped: int
    excluded: int
    font_outlined_glyphs: int = 0
    font_retained_glyphs: int = 0


@dataclass(frozen=True, slots=True)
class UpscaleOptions:
    """Feature, resume, and compute selections for local upscaling."""

    features: Path | None = None
    overwrite: bool = False
    device: str = "auto"
    fonts: Path | None = None


@dataclass(frozen=True, slots=True)
class UpscaleProgress:
    """Optional item and model-download progress callbacks for local upscaling."""

    textures: TextureProgress | None = None
    downloads: DownloadProgress | None = None
    backend: BackendProgress | None = None


@dataclass(frozen=True, slots=True)
class _UpscaleExecution:
    """Shared state for one independent-plus-grouped transform pass."""

    source: Path
    output: Path
    upscaler: ColorUpscaler | None
    progress: TextureProgress | None
    completed: int
    total: int
    font_outlines: Mapping[str, OutlineAtlas] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _InferenceOutputs:
    """One run's joined frame pixels and verified ordinary-inference paths."""

    frames: dict[str, Image.Image] = field(default_factory=dict)
    textures: dict[str, Path] = field(default_factory=dict)


def _create_seedvr2_upscaler(
    device: str,
    download_progress: DownloadProgress | None,
    backend_progress: BackendProgress | None,
) -> SeedVR2Upscaler:
    """Load the optional backend quietly and report its selected device."""
    # Diffusers imports optional transformer modules eagerly and warns about
    # their CUDA decorators even though SeedVR2 does not use those modules.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"CUDA is not available or torch_xla is imported\. Disabling autocast\.",
            category=UserWarning,
        )
        from gk3hd.textures.upscale.seedvr2 import SeedVR2Config, SeedVR2Upscaler  # noqa: PLC0415

    upscaler = SeedVR2Upscaler(
        SeedVR2Config(device=device),
        download_progress=download_progress,
    )
    if backend_progress is not None:
        backend_progress(upscaler.device_description, upscaler.device.type == "cpu")
    return upscaler


def _partition_upscale_work(
    paths: Sequence[Path],
    plans: Sequence[PipelinePlan],
    output: Path,
    *,
    overwrite: bool,
    font_outlines: Mapping[str, OutlineAtlas] | None = None,
) -> tuple[list[tuple[Path, PipelinePlan, Path]], int, int]:
    """Separate eligible work, resumable PNGs, and untouched semantic assets."""
    pending: list[tuple[Path, PipelinePlan, Path]] = []
    skipped = excluded = 0
    existing = actual_files(output, suffix=".png")
    for path, plan in zip(paths, plans, strict=True):
        if plan.kind.keeps_native_size:
            # Analysis is authoritative. Remove a generated file left by an
            # older manifest so the workspace mirrors the next pack exactly.
            stale = existing.get(f"{path.stem}.png".casefold())
            if stale is not None:
                stale.unlink()
            excluded += 1
            continue
        requested = output / f"{path.stem}.PNG"
        destination = existing.get(requested.name.casefold())
        if destination is not None:
            if not overwrite:
                outline = (font_outlines or {}).get(path.name.upper())
                resumable = (
                    _is_matching_font_outline(destination, outline)
                    if outline is not None
                    else _is_resumable_png(path, destination, plan)
                )
                if resumable:
                    skipped += 1
                    continue
        else:
            # ``requested`` may resolve to another file's Win32 8.3 alias.
            # Only the actual directory-entry map can identify this texture.
            destination = requested
        pending.append((path, plan, destination))
    added = _queue_dependent_outputs(paths, plans, existing, pending)
    return pending, skipped - added, excluded


def _queue_dependent_outputs(
    paths: Sequence[Path],
    plans: Sequence[PipelinePlan],
    existing: Mapping[str, Path],
    pending: list[tuple[Path, PipelinePlan, Path]],
) -> int:
    """Rebuild whole compositions when an input will change in this same run."""
    from gk3hd.textures.upscale.driving_map import BASE_NAME  # noqa: PLC0415
    from gk3hd.textures.upscale.timeblock import timeblock_background_name  # noqa: PLC0415

    changing = {path.name.upper() for path, _plan, _destination in pending}
    frame_changing = any(
        plan.kind is PipelineKind.COLOR_AI and path.name.upper() in FRAME_REGIONS
        for path, plan in zip(paths, plans, strict=True)
    ) and (bool(changing.intersection(FRAME_REGIONS)) or not has_coherent_frame_outputs(existing))
    added = 0
    for path, plan in zip(paths, plans, strict=True):
        name = path.name.upper()
        if name in changing or plan.kind.keeps_native_size:
            continue
        if (
            (frame_changing and plan.kind is PipelineKind.COLOR_AI and name in FRAME_REGIONS)
            or (plan.kind is PipelineKind.DRIVING_MAP_COMPOSITE and BASE_NAME in changing)
            or (
                plan.kind is PipelineKind.TIMEBLOCK_COMPOSITE
                and timeblock_background_name(name) in changing
            )
        ):
            pending.append((path, plan, existing[f"{path.stem}.png".casefold()]))
            added += 1
    return added


def _upscale_one(
    source: Path,
    destination: Path,
    features: TextureFeatures,
    upscaler: ColorUpscaler | None,
) -> None:
    """Write one PNG and translate optional-backend defects at the domain boundary."""
    from gk3hd.textures.upscale.fingerprint import regenerate_fingerprint  # noqa: PLC0415
    from gk3hd.textures.upscale.fonts.atlas import regenerate_font_atlas  # noqa: PLC0415
    from gk3hd.textures.upscale.fonts.button import regenerate_font_button  # noqa: PLC0415
    from gk3hd.textures.upscale.pipeline import upscale_texture  # noqa: PLC0415
    from gk3hd.textures.upscale.thumbnail import regenerate_thumbnail  # noqa: PLC0415
    from gk3hd.textures.upscale.ui_art import regenerate_ui_art  # noqa: PLC0415

    try:
        plan = plan_texture(features)
        route = plan.kind
        stamp = generation_stamp(source, plan) if route in STAMPED_ROUTES else None
        if route is PipelineKind.REVIEWED_REPLACEMENT:
            transformed = regenerate_replacement(source)
        elif route is PipelineKind.FONT_ATLAS_SOURCE_4X:
            transformed = regenerate_font_atlas(source)
        elif route is PipelineKind.FONT_BUTTON_SOURCE_4X:
            transformed = regenerate_font_button(source)
        elif route is PipelineKind.FINGERPRINT_SOURCE_4X:
            transformed = regenerate_fingerprint(source)
        elif route is PipelineKind.UI_SOURCE_4X:
            transformed = regenerate_ui_art(source)
        elif route is PipelineKind.THUMBNAIL_SOURCE_4X:
            transformed = regenerate_thumbnail(source)
        else:
            with Image.open(source) as image:
                transformed = upscale_texture(image, features, upscaler=upscaler)
        if stamp is not None:
            verify_generation_stamp(source, plan, stamp)
            transformed.info[GENERATION_STAMP] = stamp
        _write_png_atomic(transformed, destination)
    except Exception as exc:
        msg = f"could not upscale {source.name}: {exc}"
        raise RuntimeError(msg) from exc


def _execute_pending_upscales(
    pending: Sequence[tuple[Path, PipelinePlan, Path]],
    manifest: Mapping[str, TextureFeatures],
    execution: _UpscaleExecution,
) -> None:
    """Run independent transforms first, then compose dependent map patches."""
    completed = execution.completed
    driving_map: list[tuple[Path, Path]] = []
    timeblock: list[tuple[Path, Path]] = []
    inference = _InferenceOutputs()
    for path, plan, destination in pending:
        if plan.kind is PipelineKind.DRIVING_MAP_COMPOSITE:
            driving_map.append((path, destination))
            continue
        if plan.kind is PipelineKind.TIMEBLOCK_COMPOSITE:
            timeblock.append((path, destination))
            continue
        _write_independent_output(
            path, destination, manifest[path.name.upper()], execution, inference
        )
        completed += 1
        if execution.progress is not None:
            execution.progress(completed, execution.total)
    if driving_map:
        _compose_driving_map(execution.source, execution.output, driving_map)
    for source, destination in timeblock:
        _write_png_atomic(_compose_timeblock(source, destination), destination)
        completed += 1
        if execution.progress is not None:
            execution.progress(completed, execution.total)
    for _path, _destination in driving_map:
        completed += 1
        if execution.progress is not None:
            execution.progress(completed, execution.total)


def _write_independent_output(
    source: Path,
    destination: Path,
    features: TextureFeatures,
    execution: _UpscaleExecution,
    inference: _InferenceOutputs,
) -> None:
    """Select the explicit font variant without changing other independent routes."""
    if atlas := execution.font_outlines.get(source.name.upper()):
        _write_png_atomic(atlas.image, destination)
    else:
        _upscale_independent(source, destination, features, execution.upscaler, inference)


def _reuse_inference(source: Path, destination: Path, plan: PipelinePlan, cached: Path) -> bool:
    """Reuse an exact source/recipe result, never a merely similar texture.

    Only ordinary AI routes enter this cache. Joined SIDNEY inference and
    source-dependent reconstructions keep their own family contracts. Paths,
    rather than decoded images, bound memory use during a complete rebuild.
    """
    if not _is_resumable_png(source, cached, plan):
        return False
    with Image.open(cached) as image:
        transformed = image.copy()
    stamp = transformed.info.get(GENERATION_STAMP)
    if not isinstance(stamp, str):
        return False
    verify_generation_stamp(source, plan, stamp)
    _write_png_atomic(transformed, destination)
    return True


def _upscale_independent(
    source: Path,
    destination: Path,
    features: TextureFeatures,
    upscaler: ColorUpscaler | None,
    inference: _InferenceOutputs,
) -> None:
    """Share joined-frame inference and byte-identical ordinary AI requests."""
    plan = plan_texture(features)
    if plan.kind is PipelineKind.COLOR_AI and source.name.upper() in FRAME_REGIONS:
        if not inference.frames:
            inference.frames.update(upscale_frame(source.parent, upscaler))
        _write_png_atomic(inference.frames[source.name.upper()], destination)
        return
    stamp = (
        generation_stamp(source, plan)
        if plan.kind in {PipelineKind.COLOR_AI, PipelineKind.ALPHA_TEST_AI, PipelineKind.ALPHA_AI}
        else None
    )
    cached = inference.textures.get(stamp) if stamp is not None else None
    if cached is None or not _reuse_inference(source, destination, plan, cached):
        _upscale_one(source, destination, features, upscaler)
    if stamp is not None:
        inference.textures[stamp] = destination


def _write_png_atomic(image: Image.Image, destination: Path) -> None:
    """Replace one PNG atomically without confusing an NTFS short-name alias."""
    with protect_short_name_alias(destination):
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            metadata = PngInfo()
            for key in (
                FRAME_STAMP,
                FRAME_BATCH,
                GENERATION_STAMP,
                FONT_OUTLINE_STAMP,
                ALPHA_STAMP,
            ):
                if isinstance(stamp := image.info.get(key), str):
                    metadata.add_text(key, stamp)
            image.save(temporary, format="PNG", optimize=True, pnginfo=metadata)
            temporary.replace(destination)
            require_actual_file(destination)
        finally:
            temporary.unlink(missing_ok=True)


def _prepare_font_outlines(
    paths: Sequence[Path], plans: Sequence[PipelinePlan], directory: Path | None
) -> dict[str, OutlineAtlas]:
    """Load explicit font inputs only when requested and recheck every glyph."""
    if directory is None:
        return {}
    from gk3hd.textures.upscale.fonts.outline import (  # noqa: PLC0415
        outline_font_digest,
        regenerate_outline_atlas,
        supplied_font_files,
    )

    fonts = supplied_font_files(directory.expanduser())
    result = {}
    for path, plan in zip(paths, plans, strict=True):
        digest = outline_font_digest(path.name)
        if plan.kind is PipelineKind.FONT_ATLAS_SOURCE_4X and digest in fonts:
            result[path.name.upper()] = regenerate_outline_atlas(path, fonts[digest])
    if not result:
        msg = "the supplied fonts do not match any supported atlas in the source directory"
        raise ValueError(msg)
    return result


def _is_matching_font_outline(destination: Path, atlas: OutlineAtlas) -> bool:
    """Resume only matching pixels and provenance, not a filename or metadata alone."""
    try:
        with destination.open("rb") as stream, Image.open(stream) as candidate:
            candidate.load()
            return (
                candidate.format == "PNG"
                and candidate.mode == atlas.image.mode
                and candidate.size == atlas.image.size
                and candidate.info.get(FONT_OUTLINE_STAMP) == atlas.image.info[FONT_OUTLINE_STAMP]
                and candidate.tobytes() == atlas.image.tobytes()
            )
    except (OSError, SyntaxError) as exc:
        msg = f"existing upscale output is invalid; use --overwrite: {destination.name}"
        raise ValueError(msg) from exc


def _is_resumable_png(
    source: Path,
    destination: Path,
    plan: PipelinePlan,
) -> bool:
    """Return whether a complete PNG matches its route, rejecting corruption."""
    from gk3hd.textures.upscale.fingerprint import is_current_fingerprint  # noqa: PLC0415
    from gk3hd.textures.upscale.thumbnail import is_current_thumbnail  # noqa: PLC0415
    from gk3hd.textures.upscale.ui_art import is_current_ui_art  # noqa: PLC0415

    try:
        with Image.open(source) as original, Image.open(destination) as candidate:
            candidate_mode = candidate.mode
            stamp = candidate.info.get(GENERATION_STAMP)
            candidate.verify()
            expected = (original.width * 4, original.height * 4)
            if plan.kind is PipelineKind.FONT_ATLAS_SOURCE_4X:
                expected = font_atlas_output_size(source.name, original.size)
            actual = candidate.size
            image_format = candidate.format
    except (OSError, SyntaxError) as exc:
        msg = f"existing upscale output is invalid; use --overwrite: {destination.name}"
        raise ValueError(msg) from exc
    if image_format != "PNG" or actual != expected:
        msg = (
            f"existing upscale output is not a complete 4x PNG; use --overwrite: {destination.name}"
        )
        raise ValueError(msg)
    expected_mode = _expected_upscale_mode(source, plan)
    if candidate_mode != expected_mode:
        if plan.kind in {
            PipelineKind.ALPHA_SMOOTH,
            PipelineKind.ALPHA_AI,
            PipelineKind.FONT_ATLAS_SOURCE_4X,
            PipelineKind.FONT_BUTTON_SOURCE_4X,
            PipelineKind.FINGERPRINT_SOURCE_4X,
            PipelineKind.UI_SOURCE_4X,
            PipelineKind.COLOR_SMOOTH,
            PipelineKind.ALPHA_TEST_SMOOTH,
            PipelineKind.THUMBNAIL_SOURCE_4X,
        }:
            return False
        msg = (
            f"existing upscale output has mode {candidate_mode}, not {expected_mode}; "
            f"use --overwrite: {destination.name}"
        )
        raise ValueError(msg)
    if (
        plan.kind in STAMPED_ROUTES
        and not (plan.kind is PipelineKind.COLOR_AI and source.name.upper() in FRAME_REGIONS)
        and stamp != generation_stamp(source, plan)
    ):
        return False
    validators = {
        PipelineKind.REVIEWED_REPLACEMENT: is_current_replacement,
        PipelineKind.FONT_ATLAS_SOURCE_4X: _is_vector_font_output,
        PipelineKind.FONT_BUTTON_SOURCE_4X: _is_vector_button_output,
        PipelineKind.DRIVING_MAP_COMPOSITE: _is_current_driving_map_output,
        PipelineKind.TIMEBLOCK_COMPOSITE: _is_current_timeblock_output,
        PipelineKind.FINGERPRINT_SOURCE_4X: is_current_fingerprint,
        PipelineKind.UI_SOURCE_4X: is_current_ui_art,
        PipelineKind.THUMBNAIL_SOURCE_4X: is_current_thumbnail,
        PipelineKind.ALPHA_AI: lambda s, d: _is_current_alpha(s, d, periodic=plan.periodic),
    }
    if validator := validators.get(plan.kind):
        return validator(source, destination)
    if plan.kind in {PipelineKind.COLOR_SMOOTH, PipelineKind.ALPHA_TEST_SMOOTH}:
        from gk3hd.textures.upscale.pipeline import upscale_smooth_color  # noqa: PLC0415

        with Image.open(source) as original, Image.open(destination) as candidate:
            expected = upscale_smooth_color(
                original,
                periodic=plan.periodic,
                alphatest=plan.kind is PipelineKind.ALPHA_TEST_SMOOTH,
            )
            return candidate.tobytes() == expected.tobytes()
    if plan.kind is PipelineKind.ALPHA_TEST_AI:
        return _has_current_key_mask(source, destination, periodic=plan.periodic)
    return (
        is_current_frame(source, destination)
        if plan.kind is PipelineKind.COLOR_AI and source.name.upper() in FRAME_REGIONS
        else True
    )


def _is_current_alpha(source: Path, destination: Path, *, periodic: bool) -> bool:
    """Validate accepted inference or the exact cached deterministic fallback."""
    from gk3hd.textures.upscale.pipeline import is_current_alpha_output  # noqa: PLC0415

    with Image.open(source) as original, Image.open(destination) as candidate:
        return is_current_alpha_output(original, candidate, periodic=periodic)


def _expected_upscale_mode(source: Path, plan: PipelinePlan) -> str:
    """Return the encoded mode owned by one processing route."""
    if plan.kind is PipelineKind.FINGERPRINT_SOURCE_4X:
        from gk3hd.textures.upscale.fingerprint import WORKSTATION_MASK_SIZES  # noqa: PLC0415

        return "L" if source.name.upper() in WORKSTATION_MASK_SIZES else "RGB"
    if plan.kind is PipelineKind.UI_SOURCE_4X:
        from gk3hd.textures.upscale.ui_art import ui_art_output_mode  # noqa: PLC0415

        with Image.open(source) as original:
            return ui_art_output_mode(source.name, original.mode)
    if plan.kind in {PipelineKind.ALPHA_SMOOTH, PipelineKind.ALPHA_AI}:
        return "P"
    if plan.kind is PipelineKind.FONT_ATLAS_SOURCE_4X:
        from gk3hd.textures.upscale.fonts.atlas import font_atlas_recipe  # noqa: PLC0415

        recipe = font_atlas_recipe(source.name)
        if recipe is None:
            msg = f"no faithful font recipe exists for {source.name}"
            raise ValueError(msg)
        return "L" if recipe.alpha else "RGB"
    return "RGB"


def _compose_driving_map(
    source_directory: Path,
    output_directory: Path,
    overlays: Sequence[tuple[Path, Path]],
) -> None:
    """Write a coherent opaque location set from the one generated HD base."""
    from gk3hd.textures.upscale.driving_map import (  # noqa: PLC0415
        BASE_NAME,
        compose_driving_map_overlay,
    )

    base_source = source_directory / BASE_NAME
    base_output = output_directory / f"{Path(BASE_NAME).stem}.PNG"
    if not base_source.is_file() or not base_output.is_file():
        msg = f"driving-map composition requires {BASE_NAME} and {base_output.name}"
        raise ValueError(msg)
    with Image.open(base_source) as base_image, Image.open(base_output) as hd_image:
        base = base_image.convert("RGB")
        base_hd = hd_image.convert("RGB")
    for source, destination in overlays:
        with Image.open(source) as overlay_image:
            transformed = compose_driving_map_overlay(
                overlay_image,
                base,
                base_hd,
                name=source.name,
            )
        _write_png_atomic(transformed, destination)


def _compose_timeblock(source: Path, destination: Path) -> Image.Image:
    """Load a frame's exact original/HD background pair for generation or resume."""
    from gk3hd.textures.upscale.timeblock import (  # noqa: PLC0415
        compose_timeblock_overlay,
        timeblock_background_name,
    )

    name = timeblock_background_name(source.name)
    originals = actual_files(source.parent, suffix=".bmp")
    generated = actual_files(destination.parent, suffix=".png")
    base_source = originals.get(name.casefold())
    base_output = generated.get(f"{Path(name).stem}.png".casefold())
    if base_source is None or base_output is None:
        msg = f"{source.name}: time-transition composition requires {name} and its upscaled PNG"
        raise FileNotFoundError(msg)
    with (
        Image.open(source) as overlay,
        Image.open(base_source) as base,
        Image.open(base_output) as hd,
    ):
        return compose_timeblock_overlay(overlay, base, hd, name=source.name)


def _is_current_timeblock_output(source: Path, destination: Path) -> bool:
    """Refresh independently inferred frames or frames composed with an older base."""
    try:
        expected = _compose_timeblock(source, destination)
    except FileNotFoundError:
        return False
    with Image.open(destination) as candidate:
        return candidate.tobytes() == expected.tobytes()


def _is_current_driving_map_output(source: Path, destination: Path) -> bool:
    """Reject independently generated map patches left by an older pipeline."""
    import numpy as np  # noqa: PLC0415

    from gk3hd.textures.upscale.driving_map import (  # noqa: PLC0415
        BASE_NAME,
        compose_driving_map_overlay,
    )

    base_source = source.with_name(BASE_NAME)
    base_output = destination.with_name(f"{Path(BASE_NAME).stem}.PNG")
    if not base_source.is_file() or not base_output.is_file():
        return False
    with (
        Image.open(source) as overlay,
        Image.open(base_source) as base,
        Image.open(base_output) as base_hd,
        Image.open(destination) as candidate,
    ):
        expected = compose_driving_map_overlay(
            overlay,
            base,
            base_hd,
            name=source.name,
        )
        return bool(np.array_equal(np.asarray(candidate), np.asarray(expected)))


def _is_vector_font_output(source: Path, destination: Path) -> bool:
    """Return whether an atlas is byte-equivalent to current deterministic rendering."""
    import numpy as np  # noqa: PLC0415

    from gk3hd.textures.upscale.fonts.atlas import regenerate_font_atlas  # noqa: PLC0415

    expected = regenerate_font_atlas(source)
    with Image.open(destination) as candidate:
        return bool(np.array_equal(np.asarray(candidate), np.asarray(expected)))


def _is_vector_button_output(source: Path, destination: Path) -> bool:
    """Return whether a button matches the current deterministic reconstruction."""
    import numpy as np  # noqa: PLC0415

    from gk3hd.textures.upscale.fonts.button import regenerate_font_button  # noqa: PLC0415

    expected = regenerate_font_button(source)
    with Image.open(destination) as candidate:
        return bool(np.array_equal(np.asarray(candidate), np.asarray(expected)))


def _has_current_key_mask(source: Path, destination: Path, *, periodic: bool) -> bool:
    """Reject resumable keyed PNGs produced by the former block mask."""
    import numpy as np  # noqa: PLC0415

    from gk3hd.textures.upscale.pipeline import (  # noqa: PLC0415
        KEY_COLOR,
        alpha_test_mask,
        upscale_key_mask,
    )

    with Image.open(source) as original, Image.open(destination) as candidate:
        source_rgb = np.asarray(original.convert("RGB"), dtype=np.uint8)
        candidate_rgb = np.asarray(candidate.convert("RGB"), dtype=np.uint8)
    source_mask = alpha_test_mask(source_rgb)
    expected_mask = upscale_key_mask(source_mask, 4, periodic=periodic)
    if source_mask[0, 0]:
        expected_mask[0, 0] = True
    actual_mask = np.all(candidate_rgb == KEY_COLOR, axis=2)
    return bool(np.array_equal(actual_mask, expected_mask))


def upscale(
    source: Path,
    output: Path,
    *,
    options: UpscaleOptions | None = None,
    progress: TextureProgress | UpscaleProgress | None = None,
) -> UpscaleReport:
    """Apply the property-selected 4x pipeline and write release PNGs."""
    source = source.resolve()
    output = output.resolve()
    options = options or UpscaleOptions()
    texture_progress = progress.textures if isinstance(progress, UpscaleProgress) else progress
    download_progress = progress.downloads if isinstance(progress, UpscaleProgress) else None
    backend_progress = progress.backend if isinstance(progress, UpscaleProgress) else None
    if options.features is None:
        features = analysis_file(source)
        if not features.is_file():
            analyze_textures(source, features)
    else:
        features = options.features.resolve()
    try:
        manifest = load_feature_manifest(features)
    except FeatureManifestVersionError:
        if options.features is not None:
            raise
        # The colocated manifest is generated state. Refresh an older
        # schema automatically so a normal resumable upscale needs no
        # migration command after gk3hd is upgraded.
        analyze_textures(source, features)
        manifest = load_feature_manifest(features)
    paths = sorted(
        (path for path in source.rglob("*") if path.is_file() and path.suffix.casefold() == ".bmp"),
        key=explicit_dos_name_first,
    )
    missing = [path.name for path in paths if path.name.upper() not in manifest]
    if missing:
        msg = f"feature manifest is missing {len(missing)} texture(s): {missing[0]}"
        raise ValueError(msg)
    plans = [plan_texture(manifest[path.name.upper()]) for path in paths]
    font_outlines = _prepare_font_outlines(paths, plans, options.fonts)
    output.mkdir(parents=True, exist_ok=True)
    pending, skipped, excluded = _partition_upscale_work(
        paths,
        plans,
        output,
        overwrite=options.overwrite,
        font_outlines=font_outlines,
    )
    needs_ai = any(
        plan.kind in {PipelineKind.COLOR_AI, PipelineKind.ALPHA_TEST_AI, PipelineKind.ALPHA_AI}
        for _path, plan, _destination in pending
    )
    upscaler = None
    if needs_ai:
        upscaler = _create_seedvr2_upscaler(
            options.device,
            download_progress,
            backend_progress,
        )
    _execute_pending_upscales(
        pending,
        manifest,
        _UpscaleExecution(
            source,
            output,
            upscaler,
            texture_progress,
            skipped + excluded,
            len(paths),
            font_outlines,
        ),
    )
    if texture_progress is not None and not pending:
        texture_progress(len(paths), len(paths))
    return UpscaleReport(
        len(paths),
        len(pending),
        skipped,
        excluded,
        sum(glyph.outlined for atlas in font_outlines.values() for glyph in atlas.glyphs),
        sum(not glyph.outlined for atlas in font_outlines.values() for glyph in atlas.glyphs),
    )
