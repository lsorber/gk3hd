from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.model import TextureFeatures, TextureKind
from gk3hd.textures.routing import PipelineKind, plan_texture
from gk3hd.textures.upscale.timeblock import (
    _RECIPES,
    compose_timeblock_overlay,
    timeblock_background_name,
    timeblock_overlay_recipe,
)


def test_catalog_and_routes_preserve_semantic_exclusions() -> None:
    assert sum(recipe.frames for recipe in _RECIPES.values()) == 234
    assert timeblock_background_name("d102p_13.bmp") == "TBT102P.BMP"
    for name in ("D102P_00.BMP", "D102P_14.BMP", "D102P_1.BMP", "D102P_01_MORE.BMP"):
        assert timeblock_overlay_recipe(name) is None
    assert plan_texture(TextureFeatures("D102P_13.BMP")).kind is PipelineKind.TIMEBLOCK_COMPOSITE
    assert (
        plan_texture(TextureFeatures("D102P_13.BMP", kind=TextureKind.DATA)).kind
        is PipelineKind.DATA_UNCHANGED
    )
    assert (
        plan_texture(TextureFeatures("D102P_13.BMP", exact_raster=True)).kind
        is PipelineKind.EXACT_RASTER_UNCHANGED
    )


def test_unchanged_crop_is_identical_to_shared_background() -> None:
    original = Image.new("RGB", (640, 480), (100, 80, 60))
    hd = Image.new("RGB", (2560, 1920), (55, 130, 160))
    frame = Image.new("RGB", (383, 63), (100, 80, 60))
    result = compose_timeblock_overlay(frame, original, hd, name="D102P_01.BMP")
    assert result.size == (1532, 252)
    assert result.getextrema() == ((55, 55), (130, 130), (160, 160))


def test_opaque_white_and_black_survive_changed_ai_landscape() -> None:
    original = Image.new("RGB", (640, 480), (100, 80, 60))
    hd = Image.new("RGB", (2560, 1920), (55, 130, 160))
    frame = Image.new("RGB", (383, 63), (100, 80, 60))
    frame.paste("white", (20, 20, 40, 40))
    frame.paste("black", (60, 20, 80, 40))
    result = np.asarray(compose_timeblock_overlay(frame, original, hd, name="D102P_01.BMP"))
    assert np.all(result[90:150, 90:150] == 255)
    assert np.all(result[90:150, 250:310] == 0)
    assert np.all(result[0] == (55, 130, 160))
    assert np.all(result[-1] == (55, 130, 160))


def test_recipe_dimensions_fail_closed() -> None:
    original = Image.new("RGB", (640, 480))
    hd = Image.new("RGB", (2560, 1920))
    with pytest.raises(ValueError, match="source dimensions"):
        compose_timeblock_overlay(Image.new("RGB", (10, 10)), original, hd, name="D102P_01.BMP")
    with pytest.raises(ValueError, match="exactly 4x"):
        compose_timeblock_overlay(
            Image.new("RGB", (383, 63)), original, original, name="D102P_01.BMP"
        )


@pytest.mark.parametrize("family", tuple(_RECIPES))
def test_every_sequence_retains_its_native_crop_and_background_height(family: str) -> None:
    recipe = _RECIPES[family]
    height = 481 if family == "D306P" else 480
    base = Image.new("RGB", (640, height), (10, 20, 30))
    hd = Image.new("RGB", (2560, height * 4), (40, 50, 60))
    frame = Image.new("RGB", recipe.size, (10, 20, 30))
    result = compose_timeblock_overlay(frame, base, hd, name=f"{family}_{recipe.frames:02}.BMP")
    assert result.size == tuple(value * 4 for value in recipe.size)
    assert result.getextrema() == ((40, 40), (50, 50), (60, 60))
