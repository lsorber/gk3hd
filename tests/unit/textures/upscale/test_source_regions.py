"""Reviewed source details survive an otherwise AI-generated color texture."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.model import PipelineOverride, TextureFeatures
from gk3hd.textures.routing import plan_texture
from gk3hd.textures.upscale.generation import generation_stamp
from gk3hd.textures.upscale.pipeline import preserve_source_regions, upscale_texture


@pytest.mark.parametrize("scale", [2, 4])
@pytest.mark.parametrize("periodic", [False, True])
def test_selected_detail_is_faithful_and_unrelated_ai_pixels_do_not_change(
    scale: int, *, periodic: bool
) -> None:
    original = Image.new("RGB", (8, 8), (20, 40, 60))
    generated = Image.new("RGB", (8 * scale, 8 * scale), (200, 180, 160))
    result = np.asarray(
        preserve_source_regions(original, generated, ((2, 2, 4, 4),), periodic=periodic)
    )
    assert (result[2 * scale : 4 * scale, 2 * scale : 4 * scale] == (20, 40, 60)).all()
    assert (result[:scale] == (200, 180, 160)).all()
    assert (result[:, 5 * scale :] == (200, 180, 160)).all()
    # A feather exists outside the rectangle instead of a hard pasted boundary.
    transition = result[3 * scale, 4 * scale, 0]
    assert 20 < transition < 200


def test_multiple_regions_are_order_independent_and_do_not_double_blend() -> None:
    original = Image.new("RGB", (8, 8), (20, 40, 60))
    generated = Image.new("RGB", (32, 32), (200, 180, 160))
    regions = ((1, 1, 4, 4), (3, 3, 6, 6))
    forward = preserve_source_regions(original, generated, regions, periodic=False)
    reverse = preserve_source_regions(original, generated, regions[::-1], periodic=False)
    assert forward.tobytes() == reverse.tobytes()
    assert forward.getpixel((14, 14)) == (20, 40, 60)


@pytest.mark.parametrize("size", [(31, 32), (32, 31), (0, 0)])
def test_regions_reject_an_incompatible_generated_scale(size: tuple[int, int]) -> None:
    with pytest.raises(ValueError, match="uniform"):
        preserve_source_regions(
            Image.new("RGB", (8, 8)), Image.new("RGB", size), ((1, 1, 4, 4),), periodic=False
        )


def test_regions_reject_bounds_outside_the_source() -> None:
    with pytest.raises(ValueError, match="exceeds original"):
        preserve_source_regions(
            Image.new("RGB", (8, 8)),
            Image.new("RGB", (32, 32)),
            ((1, 1, 9, 4),),
            periodic=False,
        )


def test_policy_regions_survive_serialization_and_affect_normal_ai_processing(
    tmp_path: Path,
) -> None:
    class FlatBackend:
        scale = 4

        def upscale(self, image: Image.Image) -> Image.Image:
            return Image.new("RGB", (image.width * 4, image.height * 4), (200, 180, 160))

    choice = PipelineOverride.from_dict(
        {
            "pipeline": "ai",
            "variant": "color",
            "status": "final",
            "reason": "Keep small structural details faithful.",
            "source_regions": [[2, 2, 4, 4]],
        }
    )
    loaded = PipelineOverride.from_dict(choice.to_dict())
    feature = TextureFeatures("ART.BMP", pipeline_override=loaded)
    original = Image.new("RGB", (8, 8), (20, 40, 60))
    result = upscale_texture(original, feature, upscaler=FlatBackend())
    assert result.getpixel((10, 10)) == (20, 40, 60)
    assert result.getpixel((26, 26)) == (200, 180, 160)
    source = tmp_path / "ART.BMP"
    original.save(source)
    assert generation_stamp(source, plan_texture(feature)) != generation_stamp(
        source, plan_texture(TextureFeatures("ART.BMP"))
    )


@pytest.mark.parametrize(
    "regions",
    [[[-1, 0, 2, 3]], [[0, 0, 0, 3]], [[0, 0, 2]], [[False, 0, 2, 3]], [[0.5, 0, 2, 3]], "bad"],
)
def test_policy_rejects_malformed_region_coordinates(regions: object) -> None:
    with pytest.raises((ValueError, TypeError), match=r"source region|source_regions"):
        PipelineOverride.from_dict(
            {
                "pipeline": "ai",
                "variant": "color",
                "status": "final",
                "reason": "Preserve details.",
                "source_regions": regions,
            }
        )


def test_regions_cannot_change_opacity_or_deterministic_routes() -> None:
    with pytest.raises(ValueError, match="AI color"):
        PipelineOverride(
            "ai", "opacity-guarded", "final", "Preserve details.", source_regions=((0, 0, 2, 2),)
        )


def test_keyed_rgb_regions_do_not_change_key_coverage() -> None:
    class FlatBackend:
        scale = 4

        def upscale(self, image: Image.Image) -> Image.Image:
            return Image.new("RGB", (image.width * 4, image.height * 4), (200, 180, 160))

    original = Image.new("RGB", (16, 16), (255, 0, 255))
    original.paste((20, 40, 60), (2, 2, 14, 14))
    plain = upscale_texture(
        original, TextureFeatures("KEY.BMP", alphatest=True), upscaler=FlatBackend()
    )
    choice = PipelineOverride(
        "ai", "color-key", "final", "Keep authored marks.", source_regions=((4, 4, 8, 8),)
    )
    edited = upscale_texture(
        original,
        TextureFeatures("KEY.BMP", alphatest=True, pipeline_override=choice),
        upscaler=FlatBackend(),
    )
    np.testing.assert_array_equal(
        np.all(np.asarray(edited) == (255, 0, 255), axis=2),
        np.all(np.asarray(plain) == (255, 0, 255), axis=2),
    )
    assert edited.getpixel((20, 20)) == (20, 40, 60)
    assert edited.getpixel((44, 44)) == plain.getpixel((44, 44))
