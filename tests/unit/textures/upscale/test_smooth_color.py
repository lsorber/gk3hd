"""Source-preserving color reconstruction, independent of AI inference."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.model import PipelineOverride, TextureFeatures, TextureKind
from gk3hd.textures.routing import PipelineKind, plan_texture
from gk3hd.textures.upscale.pipeline import (
    KEY_COLOR,
    alpha_test_mask,
    upscale_key_mask,
    upscale_texture,
)


def _smooth(name: str, *, tiled: bool = False, alphatest: bool = False) -> TextureFeatures:
    return TextureFeatures(
        name,
        tiled=tiled,
        alphatest=alphatest,
        pipeline_override=PipelineOverride(
            "resample", "color-key" if alphatest else "color", "final", "Test source preservation."
        ),
    )


@pytest.mark.parametrize("periodic", [False, True])
def test_smooth_color_uses_bicubic_source_context(periodic: bool) -> None:
    pixels = np.zeros((8, 8, 3), dtype=np.uint8)
    pixels[:, :, 0] = np.arange(8, dtype=np.uint8) * 30
    pixels[2:6, 2:6, 1] = 70
    image = Image.fromarray(pixels)
    features = _smooth("WAX.BMP", tiled=periodic)
    assert plan_texture(features).kind is PipelineKind.COLOR_SMOOTH
    result = upscale_texture(image, features)
    # A much larger independent context must produce exactly the same center.
    context = np.pad(pixels, ((16, 16), (16, 16), (0, 0)), mode="wrap" if periodic else "reflect")
    expected = Image.fromarray(context).resize((160, 160), Image.Resampling.BICUBIC)
    assert result.mode == "RGB"
    assert result.size == (32, 32)
    assert result.tobytes() == expected.crop((64, 64, 96, 96)).tobytes()
    assert image.tobytes() == pixels.tobytes()


@pytest.mark.parametrize(
    "properties",
    [
        {"kind": TextureKind.DATA},
        {"kind": TextureKind.ALPHA},
        {"font_atlas": True},
    ],
)
def test_smooth_color_rejects_incompatible_properties(properties: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="incompatible"):
        plan_texture(_smooth("SOURCE.BMP").with_overrides(properties))


def test_explicit_smooth_choice_overrides_default_retention_but_not_dependency_guards() -> None:
    features = _smooth("WAX.BMP")
    assert (
        plan_texture(features.with_overrides({"constant_color": True})).kind
        is PipelineKind.COLOR_SMOOTH
    )
    with pytest.raises(ValueError, match="incompatible"):
        plan_texture(features.with_overrides({"native_size": True}))


@pytest.mark.parametrize("periodic", [False, True])
def test_smooth_keyed_color_preserves_shading_and_reconstructs_contour(periodic: bool) -> None:
    pixels = np.full((16, 16, 3), KEY_COLOR, dtype=np.uint8)
    pixels[4:12, 4:12] = (70, 100, 40)
    # The isolated authoring speck must not become an enlarged blob.
    pixels[0, 1] = (82, 56, 57)
    features = _smooth("SCULPTED-SIGN.BMP", alphatest=True, tiled=periodic)
    assert plan_texture(features).kind is PipelineKind.ALPHA_TEST_SMOOTH
    original = Image.fromarray(pixels)
    result = upscale_texture(original, features)
    mask = upscale_key_mask(alpha_test_mask(pixels), 4, periodic=periodic, padding=8, bias=0.0)
    generated = np.asarray(result)
    assert result.size == (64, 64)
    assert result.mode == "RGB"
    assert np.array_equal(np.all(generated == KEY_COLOR, axis=2), mask)
    # The only visible source color remains exact, including reconstructed edges:
    # no magenta halos, new bevels or neutral-fill contamination.
    assert np.all(generated[~mask] == (70, 100, 40))
    assert original.tobytes() == pixels.tobytes()


def test_unbiased_contour_does_not_thicken_straight_strokes() -> None:
    mask = np.ones((16, 16), dtype=np.bool_)
    mask[:, 5:7] = False
    unbiased = upscale_key_mask(mask, 4, bias=0.0)
    assert np.count_nonzero(~unbiased) == np.count_nonzero(~mask) * 16
    assert np.count_nonzero(~upscale_key_mask(mask, 4)) > np.count_nonzero(~unbiased)


@pytest.mark.parametrize("bias", [float("nan"), float("inf"), -float("inf")])
def test_key_contour_rejects_nonfinite_bias(bias: float) -> None:
    with pytest.raises(ValueError, match="bias must be finite"):
        upscale_key_mask(np.ones((2, 2), dtype=np.bool_), 4, bias=bias)


def test_smooth_keyed_color_validates_key_presence() -> None:
    image = Image.new("RGB", (8, 8), "green")
    features = _smooth("SIGN.BMP", alphatest=True)
    with pytest.raises(ValueError, match="contains no GK3 color key"):
        upscale_texture(image, features)


def test_smooth_keyed_color_handles_fully_transparent_source() -> None:
    image = Image.new("RGB", (8, 8), (255, 0, 255))
    features = _smooth("EMPTY.BMP", alphatest=True)
    result = upscale_texture(image, features, scale=2)
    assert result.size == (16, 16)
    assert np.all(np.asarray(result) == KEY_COLOR)
