"""Four methods own every concrete recipe; exported decisions cannot drift."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from gk3hd.textures.analyze.manifest import (
    FeatureManifestVersionError,
    load_feature_manifest,
    write_manifest,
)
from gk3hd.textures.analyze.policy import load_policy
from gk3hd.textures.bmp import BmpInfo
from gk3hd.textures.model import TextureFeatures, TextureKind, TextureManifest
from gk3hd.textures.routing import Pipeline, PipelineKind, PipelinePlan, plan_texture

if TYPE_CHECKING:
    from pathlib import Path


def test_every_recipe_belongs_to_exactly_one_of_four_methods() -> None:
    assert len(Pipeline) == 4
    assert {kind.pipeline for kind in PipelineKind} == set(Pipeline)
    assert len({(kind.pipeline, kind.variant) for kind in PipelineKind}) == len(PipelineKind)
    for kind in PipelineKind:
        assert kind.keeps_native_size == (kind.pipeline is Pipeline.RETAIN)
        assert PipelinePlan(kind, periodic=True).to_dict() == {
            "pipeline": kind.pipeline.value,
            "variant": kind.variant,
        }


def test_written_analysis_explains_and_validates_its_action(tmp_path: Path) -> None:
    output = tmp_path / "analysis.json"
    feature = TextureFeatures("SIGN.BMP", alphatest=True, tiled=True)
    write_manifest(TextureManifest((feature,)), output)
    payload = json.loads(output.read_text())
    entry = payload["textures"][0]
    assert entry["processing"] == {"pipeline": "ai", "variant": "color-key"}
    assert entry["tiled"] is True
    assert load_feature_manifest(output) == {feature.name: feature}
    entry["processing"]["pipeline"] = "retain"
    output.write_text(json.dumps(payload))
    with pytest.raises(FeatureManifestVersionError, match="stale processing decision"):
        load_feature_manifest(output)


@pytest.mark.parametrize("name", ["F_MONO_T7X12.BMP", "f_mono_t7x12.bmp", "F_STATUS_DEFAULT.BMP"])
def test_verified_bitmap_font_is_pixel_art_not_unresolved(name: str) -> None:
    feature = TextureFeatures(name, font_atlas=True, alphatest=True)
    # No filename exception in routing: only the explicit policy establishes
    # that this font is a verified bitmap strike rather than unresolved artwork.
    assert plan_texture(feature).kind is PipelineKind.FONT_ATLAS_UNCHANGED
    feature = load_policy().apply(feature, _bitmap_info())
    assert plan_texture(feature).to_dict() == {"pipeline": "retain", "variant": "pixel-art"}


def test_console_exception_does_not_identify_other_fonts() -> None:
    assert plan_texture(TextureFeatures("F_MONO_OTHER.BMP", font_atlas=True)).kind is (
        PipelineKind.FONT_ATLAS_UNCHANGED
    )
    assert plan_texture(TextureFeatures("F_MONO_T7X12.BMP")).kind is PipelineKind.COLOR_AI
    assert plan_texture(TextureFeatures("F_MONO_T7X12.BMP", kind=TextureKind.DATA)).kind is (
        PipelineKind.DATA_UNCHANGED
    )


def test_bitmap_font_manifest_preserves_font_semantics(tmp_path: Path) -> None:
    feature = TextureFeatures("F_MONO_T7X12.BMP", font_atlas=True, alphatest=True)
    feature = load_policy().apply(feature, _bitmap_info())
    output = tmp_path / "analysis.json"
    write_manifest(TextureManifest((feature,)), output)
    assert load_feature_manifest(output) == {feature.name: feature}
    entry = json.loads(output.read_text())["textures"][0]
    assert entry["font_atlas"] is True
    assert entry["processing"] == {"pipeline": "retain", "variant": "pixel-art"}


def _bitmap_info() -> BmpInfo:
    return BmpInfo(
        width=256,
        height=16,
        bits_per_pixel=24,
        palettized=False,
        top_left_rgb=(255, 0, 255),
        used_palette_is_grayscale=None,
        has_color_key=True,
    )
