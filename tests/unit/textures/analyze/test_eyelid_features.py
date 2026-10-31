"""Analyze layered eyelid geometry independently of arbitrary character names."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image

from gk3hd.textures.analyze.manifest import analyze_directory, load_feature_manifest, write_manifest
from gk3hd.textures.model import PipelineOverride, TextureFeatures, TextureKind, TextureManifest
from gk3hd.textures.routing import PipelineKind, plan_texture
from gk3hd.textures.upscale.pipeline import upscale_texture

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("suffix", ["EYELIDS", "BLINK_01", "BLINK_02", "WINK_12"])
@pytest.mark.parametrize("keyed", [False, True])
def test_eyelid_geometry_uses_source_shading_without_ai(
    tmp_path: Path, suffix: str, keyed: bool
) -> None:
    name = f"CHAR_{suffix}.BMP"
    source = Image.new("RGB", (24, 12), (150, 90, 60))
    source.paste((20, 15, 10), (5, 5, 19, 7))
    if keyed:
        source.putpixel((0, 0), (255, 0, 255))
    source.save(tmp_path / name)
    feature = analyze_directory(tmp_path).manifest.textures[0]
    assert feature.eyelid_overlay
    assert feature.kind is TextureKind.COLOR
    assert plan_texture(feature).kind is (
        PipelineKind.ALPHA_TEST_SMOOTH if keyed else PipelineKind.COLOR_SMOOTH
    )
    # Supplying no AI backend exercises the normal deterministic route.
    result = upscale_texture(source, feature)
    assert result.size == (96, 48)
    assert (result.getpixel((0, 0)) == (255, 0, 255)) is keyed
    manifest = tmp_path / "analysis.json"
    write_manifest(TextureManifest((feature,)), manifest)
    assert load_feature_manifest(manifest)[name] == feature


@pytest.mark.parametrize("suffix", ["MOUTH00", "FOREHEAD", "EYE_BLUE", "BLINKER", "BLINK_01_EXTRA"])
def test_other_artwork_keeps_its_existing_route(tmp_path: Path, suffix: str) -> None:
    name = f"CHAR_{suffix}.BMP"
    source = Image.new("RGB", (24, 12), (150, 90, 60))
    source.putpixel((1, 1), (90, 40, 30))
    source.save(tmp_path / name)
    feature = analyze_directory(tmp_path).manifest.textures[0]
    assert not feature.eyelid_overlay
    assert plan_texture(feature).kind is PipelineKind.COLOR_AI


def test_opacity_companion_keeps_scalar_semantics(tmp_path: Path) -> None:
    source = Image.new("L", (24, 12), 255)
    source.paste(0, (5, 5, 19, 7))
    source.convert("P").save(tmp_path / "CHAR_EYELIDS_ALPHA.BMP")
    feature = analyze_directory(tmp_path).manifest.textures[0]
    assert feature.kind is TextureKind.ALPHA
    assert not feature.eyelid_overlay


def test_reviewed_exception_can_select_ai_without_hiding_the_analyzed_fact() -> None:
    feature = TextureFeatures(
        "CHAR_BLINK_01.BMP",
        eyelid_overlay=True,
        pipeline_override=PipelineOverride(
            "ai", "color", "final", "Reviewed artwork retains its exact blink geometry."
        ),
    )
    assert feature.eyelid_overlay
    assert plan_texture(feature).kind is PipelineKind.COLOR_AI
    assert not feature.with_overrides({"eyelid_overlay": False}).eyelid_overlay
    with pytest.raises(TypeError, match="eyelid_overlay must be true or false"):
        feature.with_overrides({"eyelid_overlay": 1})
