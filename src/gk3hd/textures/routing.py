"""Resolve analyzed texture properties into one transformation route."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from gk3hd.textures.model import TextureFeatures, TextureKind
from gk3hd.textures.upscale.cursor_art import CURSOR_OPACITY_SIZES
from gk3hd.textures.upscale.driving_map import BASE_NAME as DRIVING_MAP_BASE_NAME
from gk3hd.textures.upscale.driving_map import driving_map_overlay_origin
from gk3hd.textures.upscale.fingerprint import (
    COMPARISON_FINGERPRINT_NAMES,
    WORKSTATION_MASK_SIZES,
    is_fingerprint,
)
from gk3hd.textures.upscale.fonts.atlas import font_atlas_recipe
from gk3hd.textures.upscale.fonts.button import font_button_recipe
from gk3hd.textures.upscale.menu_art import CONSERVATIVE_MENU_SIZES
from gk3hd.textures.upscale.replacement import has_replacement
from gk3hd.textures.upscale.sidney_frame import FRAME_REGIONS
from gk3hd.textures.upscale.thumbnail_recipes import thumbnail_recipe
from gk3hd.textures.upscale.timeblock import BACKGROUND_NAMES as TIMEBLOCK_BACKGROUND_NAMES
from gk3hd.textures.upscale.timeblock import timeblock_overlay_recipe
from gk3hd.textures.upscale.ui_art import GPS_MAP_SIZES, is_geometric_ui

_COMPOSITED_COLOR_INPUTS = frozenset(
    (DRIVING_MAP_BASE_NAME, *FRAME_REGIONS, *TIMEBLOCK_BACKGROUND_NAMES)
)


class Pipeline(StrEnum):
    """The four processing methods; resource-specific handling is a variant."""

    AI = "ai"
    RESAMPLE = "resample"
    RECONSTRUCT = "reconstruct"
    RETAIN = "retain"


class PipelineKind(StrEnum):
    """Internal recipe variants, not separate top-level pipelines."""

    DATA_UNCHANGED = "data-unchanged"
    FONT_ATLAS_SOURCE_4X = "font-atlas-source-4x"
    FONT_BUTTON_SOURCE_4X = "font-button-source-4x"
    DRIVING_MAP_COMPOSITE = "driving-map-composite"
    TIMEBLOCK_COMPOSITE = "timeblock-composite"
    FONT_ATLAS_UNCHANGED = "font-atlas-unchanged"
    FINGERPRINT_SOURCE_4X = "fingerprint-source-4x"
    UI_SOURCE_4X = "ui-source-4x"
    NATIVE_SIZE_UNCHANGED = "native-size-unchanged"
    ALPHA_SMOOTH = "alpha-smooth"
    ALPHA_AI = "alpha-ai-guarded"
    EXACT_RASTER_UNCHANGED = "exact-raster-unchanged"
    CONSTANT_COLOR_UNCHANGED = "constant-color-unchanged"
    COLOR_AI = "color-ai"
    COLOR_SMOOTH = "color-smooth"
    REVIEWED_REPLACEMENT = "reviewed-replacement"
    THUMBNAIL_SOURCE_4X = "thumbnail-source-4x"
    ALPHA_TEST_AI = "alpha-test-ai"
    ALPHA_TEST_SMOOTH = "alpha-test-smooth"

    @property
    def pipeline(self) -> Pipeline:
        """Return the single broad method owning this variant."""
        return _VARIANTS[self][0]

    @property
    def variant(self) -> str:
        """Return the concise name within the owning method."""
        return _VARIANTS[self][1]

    @property
    def keeps_native_size(self) -> bool:
        """Whether this route deliberately emits no enlarged replacement."""
        return self.pipeline is Pipeline.RETAIN


_VARIANTS = {
    PipelineKind.COLOR_AI: (Pipeline.AI, "color"),
    PipelineKind.ALPHA_TEST_AI: (Pipeline.AI, "color-key"),
    PipelineKind.ALPHA_SMOOTH: (Pipeline.RESAMPLE, "opacity"),
    PipelineKind.ALPHA_AI: (Pipeline.AI, "opacity-guarded"),
    PipelineKind.COLOR_SMOOTH: (Pipeline.RESAMPLE, "color"),
    PipelineKind.ALPHA_TEST_SMOOTH: (Pipeline.RESAMPLE, "color-key"),
    PipelineKind.FONT_ATLAS_SOURCE_4X: (Pipeline.RECONSTRUCT, "font"),
    PipelineKind.FONT_BUTTON_SOURCE_4X: (Pipeline.RECONSTRUCT, "labelled-button"),
    PipelineKind.FINGERPRINT_SOURCE_4X: (Pipeline.RECONSTRUCT, "fingerprint"),
    PipelineKind.UI_SOURCE_4X: (Pipeline.RECONSTRUCT, "ui-artwork"),
    PipelineKind.THUMBNAIL_SOURCE_4X: (Pipeline.RECONSTRUCT, "larger-source"),
    PipelineKind.REVIEWED_REPLACEMENT: (Pipeline.RECONSTRUCT, "reviewed-artwork"),
    PipelineKind.DRIVING_MAP_COMPOSITE: (Pipeline.RECONSTRUCT, "driving-map"),
    PipelineKind.TIMEBLOCK_COMPOSITE: (Pipeline.RECONSTRUCT, "chapter-card"),
    PipelineKind.DATA_UNCHANGED: (Pipeline.RETAIN, "data"),
    PipelineKind.EXACT_RASTER_UNCHANGED: (Pipeline.RETAIN, "pixel-art"),
    PipelineKind.CONSTANT_COLOR_UNCHANGED: (Pipeline.RETAIN, "constant-color"),
    PipelineKind.FONT_ATLAS_UNCHANGED: (Pipeline.RETAIN, "unresolved-font"),
    PipelineKind.NATIVE_SIZE_UNCHANGED: (Pipeline.RETAIN, "native-size"),
}


@dataclass(frozen=True, slots=True)
class PipelinePlan:
    """Resolved transformation plus orthogonal periodic-edge behavior."""

    kind: PipelineKind
    periodic: bool

    def to_dict(self) -> dict[str, str]:
        """Expose the resolved action without duplicating editable feature flags."""
        return {"pipeline": self.kind.pipeline.value, "variant": self.kind.variant}


def plan_texture(features: TextureFeatures) -> PipelinePlan:
    """Resolve the unique pipeline implied by a texture's minimal properties."""
    default = _default_plan(features)
    if features.pipeline_override is None:
        return default
    choice = features.pipeline_override
    kind = pipeline_kind(choice.pipeline, choice.variant)
    _validate_override(features, kind, default.kind)
    return PipelinePlan(kind, features.tiled)


def pipeline_kind(pipeline: str, variant: str) -> PipelineKind:
    """Resolve the public method/variant pair, rejecting unknown recipes."""
    for kind, (method, name) in _VARIANTS.items():
        if (method.value, name) == (pipeline, variant):
            return kind
    msg = f"unknown texture pipeline/variant: {pipeline}/{variant}"
    raise ValueError(msg)


def _validate_override(
    features: TextureFeatures, kind: PipelineKind, default: PipelineKind
) -> None:
    """Policy cannot bypass data, scalar, font-layout or resource dependency safety."""
    permitted = {default}
    if features.kind is TextureKind.DATA:
        permitted = {PipelineKind.DATA_UNCHANGED}
    elif features.native_size:
        permitted = {PipelineKind.NATIVE_SIZE_UNCHANGED}
    elif features.font_atlas:
        permitted.add(PipelineKind.FONT_ATLAS_UNCHANGED)
        permitted.add(PipelineKind.EXACT_RASTER_UNCHANGED)
    elif default.pipeline is not Pipeline.RECONSTRUCT:
        permitted.add(PipelineKind.NATIVE_SIZE_UNCHANGED)
        if features.kind is TextureKind.ALPHA:
            permitted.add(PipelineKind.ALPHA_SMOOTH)
            if features.alpha_silhouette:
                permitted.add(PipelineKind.ALPHA_AI)
        else:
            permitted.add(PipelineKind.EXACT_RASTER_UNCHANGED)
            permitted.update(
                {PipelineKind.ALPHA_TEST_AI, PipelineKind.ALPHA_TEST_SMOOTH}
                if features.alphatest
                else {PipelineKind.COLOR_AI, PipelineKind.COLOR_SMOOTH}
            )
    else:
        permitted.add(PipelineKind.NATIVE_SIZE_UNCHANGED)
    if features.kind is not TextureKind.DATA and not features.native_size:
        available = _default_plan(replace(features, exact_raster=False))
        if available.kind.pipeline is Pipeline.RECONSTRUCT:
            permitted.add(available.kind)
    permitted.update(_replacement_routes(features))
    if kind not in permitted:
        msg = (
            f"{features.name}: pipeline override {kind} is incompatible with "
            "texture semantics or reconstruction requirements"
        )
        raise ValueError(msg)


def _replacement_routes(features: TextureFeatures) -> set[PipelineKind]:
    """Only reviewed, opaque color artwork admits a replacement."""
    if (
        features.kind is TextureKind.COLOR
        and not any((features.native_size, features.font_atlas, features.alphatest))
        and has_replacement(features.name)
    ):
        return {PipelineKind.REVIEWED_REPLACEMENT}
    return set()


def _default_plan(features: TextureFeatures) -> PipelinePlan:
    """Select the feature-derived method before any explicit policy choice."""
    if features.kind is TextureKind.DATA:
        kind = PipelineKind.DATA_UNCHANGED
    elif font_button_recipe(features.name) is not None:
        kind = PipelineKind.FONT_BUTTON_SOURCE_4X
    elif driving_map_overlay_origin(features.name) is not None:
        kind = PipelineKind.DRIVING_MAP_COMPOSITE
    elif features.font_atlas:
        kind = (
            PipelineKind.FONT_ATLAS_SOURCE_4X
            if font_atlas_recipe(features.name) is not None
            else PipelineKind.FONT_ATLAS_UNCHANGED
        )
    elif features.native_size:
        kind = PipelineKind.NATIVE_SIZE_UNCHANGED
    elif features.exact_raster:
        kind = PipelineKind.EXACT_RASTER_UNCHANGED
    elif (
        features.kind is TextureKind.COLOR
        and not features.alphatest
        and not features.tiled
        and thumbnail_recipe(features.name) is not None
    ):
        kind = PipelineKind.THUMBNAIL_SOURCE_4X
    else:
        kind = _upscale_kind(features)
    return PipelinePlan(kind=kind, periodic=features.tiled)


def _upscale_kind(features: TextureFeatures) -> PipelineKind:
    """Select reconstruction for a resource not protected by an unchanged route."""
    conservative_menu = features.name.upper() in CONSERVATIVE_MENU_SIZES
    if (
        is_geometric_ui(features.name)
        and (
            features.kind is TextureKind.COLOR
            or features.name.upper() in GPS_MAP_SIZES
            or features.name.upper() in CURSOR_OPACITY_SIZES
        )
        and (not conservative_menu or (not features.alphatest and not features.tiled))
    ):
        return PipelineKind.UI_SOURCE_4X
    if (
        is_fingerprint(features.name)
        and (features.kind is TextureKind.COLOR or features.name.upper() in WORKSTATION_MASK_SIZES)
        and (not features.alphatest or features.name.upper() in COMPARISON_FINGERPRINT_NAMES)
        and not features.tiled
    ):
        return PipelineKind.FINGERPRINT_SOURCE_4X
    if timeblock_overlay_recipe(features.name) is not None:
        return PipelineKind.TIMEBLOCK_COMPOSITE
    if features.kind is TextureKind.ALPHA:
        return PipelineKind.ALPHA_AI if features.alpha_silhouette else PipelineKind.ALPHA_SMOOTH
    # Coupled compositions still need every enlarged source, even if one
    # member happens to be a flat fill. Opacity companions likewise retain
    # their matching dimensions through the alpha route above.
    if features.constant_color and features.name.upper() not in _COMPOSITED_COLOR_INPUTS:
        return PipelineKind.CONSTANT_COLOR_UNCHANGED
    return PipelineKind.ALPHA_TEST_AI if features.alphatest else PipelineKind.COLOR_AI
