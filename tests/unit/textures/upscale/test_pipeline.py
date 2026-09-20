from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image, ImageDraw

from gk3hd.textures.model import TextureFeatures, TextureKind
from gk3hd.textures.routing import PipelineKind, PipelinePlan, plan_texture
from gk3hd.textures.upscale.pipeline import (
    KEY_COLOR,
    alpha_test_mask,
    apply_alpha_test_mask,
    resample_keyed_art,
    resample_monotone_art,
    upscale_key_mask,
    upscale_texture,
)


@pytest.mark.parametrize("turns", [0, 1, 2, 3])
def test_periodic_mask_keeps_empty_edge_gutters(turns: int) -> None:
    mask = np.ones((16, 16), dtype=np.bool_)
    mask[3:, 5:11] = False
    rotated = np.rot90(mask, turns)
    enlarged = np.rot90(upscale_key_mask(rotated, 4, periodic=True), -turns)
    assert enlarged[:4].all()  # No borrowed trunk above the empty treetop.
    assert not enlarged[-1, 24:40].any()  # The real trunk remains opaque.


def test_periodic_mask_still_connects_authored_nonempty_edges() -> None:
    mask = np.ones((16, 16), dtype=np.bool_)
    mask[:, 5:11] = False
    enlarged = upscale_key_mask(mask, 4, periodic=True)
    assert not enlarged[:, 24:40].any()


def test_monotone_art_retains_reference_samples_and_local_color_bounds() -> None:
    pixels = ((np.arange(45).reshape(3, 5, 3) * 37) % 256).astype(np.uint8)
    enlarged = np.asarray(resample_monotone_art(Image.fromarray(pixels)))
    assert enlarged.shape == (12, 20, 3)
    np.testing.assert_array_equal(enlarged[2::4, 2::4], pixels)
    x = np.floor(np.arange(20) / 4 - 0.5).astype(int)
    y = np.floor(np.arange(12) / 4 - 0.5).astype(int)
    corners = [
        pixels[np.clip(y + dy, 0, 2)[:, None], np.clip(x + dx, 0, 4)[None, :]]
        for dy in (0, 1)
        for dx in (0, 1)
    ]
    assert np.all(enlarged >= np.minimum.reduce(corners))
    assert np.all(enlarged <= np.maximum.reduce(corners))


def test_monotone_art_reconstructs_curves_without_edge_ringing() -> None:
    pixels = np.repeat(np.array([[40, 40, 200, 200]], dtype=np.uint8)[..., None], 3, axis=2)
    enlarged = np.asarray(resample_monotone_art(Image.fromarray(pixels)))
    # Zero slopes at the two plateaus give the cubic smoothstep, not a linear
    # blur or duplicated source pixels. The whole transition stays in bounds.
    assert enlarged[2, 7:10, 0].tolist() == [65, 120, 175]
    assert enlarged.min() == 40
    assert enlarged.max() == 200


@pytest.mark.parametrize("size", [(1, 1), (7, 3)])
def test_monotone_art_preserves_constant_colors(size: tuple[int, int]) -> None:
    image = Image.new("RGB", size, (65, 105, 32))
    enlarged = resample_monotone_art(image)
    assert enlarged.size == (size[0] * 4, size[1] * 4)
    assert enlarged.getcolors() == [(size[0] * size[1] * 16, (65, 105, 32))]


class NearestBackend:
    scale = 4

    def upscale(self, image: Image.Image) -> Image.Image:
        return image.resize(
            (image.width * self.scale, image.height * self.scale),
            Image.Resampling.NEAREST,
        )


class FailingBackend:
    scale = 4

    def upscale(self, image: Image.Image) -> Image.Image:
        del image
        msg = "backend should not be called"
        raise AssertionError(msg)


@pytest.mark.parametrize("periodic", [False, True])
def test_alpha_authoring_speck_is_removed_before_inference_and_on_resume(periodic: bool) -> None:
    pixels = np.full((16, 32, 3), KEY_COLOR, dtype=np.uint8)
    pixels[0, 1] = (82, 56, 57)
    pixels[6:12, 12:25] = (100, 120, 140)
    original = pixels.copy()
    expected_source = np.all(pixels == KEY_COLOR, axis=2)
    expected_source[0, 1] = True
    np.testing.assert_array_equal(alpha_test_mask(pixels), expected_source)
    np.testing.assert_array_equal(pixels, original)
    expected = upscale_key_mask(expected_source, 4, periodic=periodic)
    source = Image.fromarray(pixels)
    generated = upscale_texture(
        source,
        TextureFeatures("SCENE.BMP", tiled=periodic, alphatest=True),
        upscaler=NearestBackend(),
    )
    np.testing.assert_array_equal(np.all(np.asarray(generated) == KEY_COLOR, axis=2), expected)
    # Simulate an old inferred PNG whose contour included the authoring pixel.
    candidate_mask = upscale_key_mask(np.all(pixels == KEY_COLOR, axis=2), 4, periodic=periodic)
    legacy = np.full((64, 128, 3), (38, 61, 93), dtype=np.uint8)
    legacy[candidate_mask] = KEY_COLOR
    # The new contour only removes artwork: hidden-color reconstruction would
    # be discarded, so no full-resolution bleed should run on this resume path.
    with patch("gk3hd.textures.upscale.pipeline._bleed_key") as bleed:
        refreshed = np.asarray(
            apply_alpha_test_mask(source, Image.fromarray(legacy), periodic=periodic)
        )
    bleed.assert_not_called()
    np.testing.assert_array_equal(np.all(refreshed == KEY_COLOR, axis=2), expected)
    np.testing.assert_array_equal(refreshed[~expected], legacy[~expected])


@pytest.mark.parametrize("neighbour", [(0, 0), (0, 2), (1, 0), (1, 1), (1, 2)])
def test_alpha_speck_rule_never_erases_connected_art(neighbour: tuple[int, int]) -> None:
    pixels = np.full((8, 8, 3), KEY_COLOR, dtype=np.uint8)
    pixels[0, 1] = (20, 30, 40)
    pixels[neighbour] = (20, 30, 40)
    np.testing.assert_array_equal(alpha_test_mask(pixels), np.all(pixels == KEY_COLOR, axis=2))


def test_alpha_speck_rule_preserves_other_dots_and_single_pixel_images() -> None:
    pixels = np.full((8, 8, 3), KEY_COLOR, dtype=np.uint8)
    pixels[0, 1] = (20, 30, 40)
    np.testing.assert_array_equal(alpha_test_mask(pixels), np.all(pixels == KEY_COLOR, axis=2))
    pixels[0, 5] = (20, 30, 40)
    expected = np.all(pixels == KEY_COLOR, axis=2)
    expected[0, 1] = True
    np.testing.assert_array_equal(alpha_test_mask(pixels), expected)


@pytest.mark.parametrize("key", [(255, 0, 255), (0, 255, 0)])
@pytest.mark.parametrize("shape", ["diagonal", "ring", "opaque", "keyed"])
def test_aligned_geometric_key_resampling_preserves_every_reference_sample(
    key: tuple[int, int, int], shape: str
) -> None:
    original = Image.new("RGB", (13, 11), key)
    color = (255, 40, 0)
    if shape == "opaque":
        original.paste(color, (0, 0, 13, 11))
    elif shape == "diagonal":
        for position in range(11):
            original.putpixel((position, position), color)
    elif shape == "ring":
        ImageDraw.Draw(original).rectangle((2, 2, 10, 8), outline=color)
    output = resample_keyed_art(original, scale=4, key_color=key, sample_aligned=True)
    pixels = np.asarray(output)
    assert output.size == (52, 44)
    assert np.array_equal(pixels[2::4, 2::4], np.asarray(original))
    # Constant visible ink never acquires a blended transparency-color fringe.
    assert np.all(np.all(pixels == key, axis=2) | np.all(pixels == color, axis=2))
    if shape == "ring":
        assert output.getpixel((6 * 4 + 2, 5 * 4 + 2)) == key
    if shape == "diagonal":
        assert not np.array_equal(
            pixels, np.asarray(original.resize(output.size, Image.Resampling.NEAREST))
        )


@pytest.mark.parametrize("scale", [0, -1])
def test_aligned_geometric_key_resampling_rejects_invalid_scale(scale: int) -> None:
    with pytest.raises(ValueError, match="scale must be positive"):
        resample_keyed_art(Image.new("RGB", (2, 2)), scale=scale, sample_aligned=True)


class CapturingBackend(NearestBackend):
    source: Image.Image | None = None

    def upscale(self, image: Image.Image) -> Image.Image:
        self.source = image.copy()
        return super().upscale(image)


class WrongSizeBackend:
    scale = 4

    def upscale(self, image: Image.Image) -> Image.Image:
        return image.copy()


@pytest.mark.parametrize(("tiled", "left_context"), [(True, 240), (False, 20)])
def test_repeating_and_standalone_images_supply_different_edge_context(
    *, tiled: bool, left_context: int
) -> None:
    """Wrapping a standalone image would introduce its unrelated opposite edge."""
    source = np.repeat(np.array([[10, 20, 240]], dtype=np.uint8), 3, axis=0)
    backend = CapturingBackend()
    upscale_texture(
        Image.fromarray(source).convert("RGB"),
        TextureFeatures("EDGE.BMP", tiled=tiled),
        upscaler=backend,
        edge_padding=1,
    )
    assert backend.source is not None
    context = np.asarray(backend.source)
    assert context[1, 0, 0] == left_context
    assert np.array_equal(context[1:-1, 1:-1, 0], source)


@pytest.mark.parametrize(
    ("features", "kind"),
    [
        (TextureFeatures("DATA", kind=TextureKind.DATA), PipelineKind.DATA_UNCHANGED),
        (TextureFeatures("ALPHA", kind=TextureKind.ALPHA), PipelineKind.ALPHA_SMOOTH),
        (
            TextureFeatures("CURSOR", exact_raster=True),
            PipelineKind.EXACT_RASTER_UNCHANGED,
        ),
        (
            TextureFeatures("BUTTON", native_size=True),
            PipelineKind.NATIVE_SIZE_UNCHANGED,
        ),
        (
            TextureFeatures("FONT", font_atlas=True),
            PipelineKind.FONT_ATLAS_UNCHANGED,
        ),
        (
            TextureFeatures("FONT_ALPHA", kind=TextureKind.ALPHA, font_atlas=True),
            PipelineKind.FONT_ATLAS_UNCHANGED,
        ),
        (
            TextureFeatures("F_ARIAL_T8.BMP", font_atlas=True),
            PipelineKind.FONT_ATLAS_SOURCE_4X,
        ),
        (
            TextureFeatures("RC_SO_SAVE_STD.BMP", native_size=True),
            PipelineKind.FONT_BUTTON_SOURCE_4X,
        ),
        (TextureFeatures("KEYED", alphatest=True), PipelineKind.ALPHA_TEST_AI),
        (TextureFeatures("PHOTO"), PipelineKind.COLOR_AI),
        (TextureFeatures("FILL", constant_color=True), PipelineKind.CONSTANT_COLOR_UNCHANGED),
        (
            TextureFeatures("HIDDEN", alphatest=True, constant_color=True),
            PipelineKind.CONSTANT_COLOR_UNCHANGED,
        ),
        (
            TextureFeatures("ALPHA", kind=TextureKind.ALPHA, constant_color=True),
            PipelineKind.ALPHA_SMOOTH,
        ),
        (
            TextureFeatures("HELP_BOX_TOP.BMP", constant_color=True),
            PipelineKind.UI_SOURCE_4X,
        ),
    ],
)
def test_plan_selects_minimal_route(features: TextureFeatures, kind: PipelineKind) -> None:
    assert plan_texture(features).kind is kind


@pytest.mark.parametrize("color", [(10, 20, 30), (255, 0, 255)])
def test_constant_fill_retains_dimensions_and_pixels_without_ai(
    color: tuple[int, int, int],
) -> None:
    source = Image.new("RGB", (13, 7), color)
    features = TextureFeatures(
        "FILL.BMP", constant_color=True, alphatest=color == (255, 0, 255), tiled=True
    )
    result = upscale_texture(source, features, upscaler=FailingBackend())
    assert result is not source
    assert result.size == source.size
    assert result.tobytes() == source.tobytes()


def test_tiled_is_orthogonal_to_every_route() -> None:
    for kind in TextureKind:
        base = TextureFeatures("X", kind=kind)
        tiled = TextureFeatures("X", kind=kind, tiled=True)
        assert plan_texture(base).kind is plan_texture(tiled).kind
        assert not plan_texture(base).periodic
        assert plan_texture(tiled).periodic


@pytest.mark.parametrize("tiled", [False, True])
@pytest.mark.parametrize("alphatest", [False, True])
@pytest.mark.parametrize("exact_raster", [False, True])
@pytest.mark.parametrize("font_atlas", [False, True])
def test_every_valid_color_property_combination_has_one_route(
    tiled: bool,
    alphatest: bool,
    exact_raster: bool,
    font_atlas: bool,
) -> None:
    if exact_raster and font_atlas:
        with pytest.raises(ValueError, match="mutually exclusive"):
            TextureFeatures(
                "COLOR",
                tiled=tiled,
                alphatest=alphatest,
                exact_raster=exact_raster,
                font_atlas=font_atlas,
            )
        return
    features = TextureFeatures(
        "COLOR",
        tiled=tiled,
        alphatest=alphatest,
        exact_raster=exact_raster,
        font_atlas=font_atlas,
    )
    plan = plan_texture(features)
    expected = (
        PipelineKind.EXACT_RASTER_UNCHANGED
        if exact_raster
        else PipelineKind.FONT_ATLAS_UNCHANGED
        if font_atlas
        else PipelineKind.ALPHA_TEST_AI
        if alphatest
        else PipelineKind.COLOR_AI
    )
    assert plan == PipelinePlan(kind=expected, periodic=tiled)


@pytest.mark.parametrize("kind", [TextureKind.ALPHA, TextureKind.DATA])
@pytest.mark.parametrize("tiled", [False, True])
def test_every_valid_noncolor_property_combination_has_one_route(
    kind: TextureKind, tiled: bool
) -> None:
    expected = (
        PipelineKind.ALPHA_SMOOTH if kind is TextureKind.ALPHA else PipelineKind.DATA_UNCHANGED
    )
    assert plan_texture(TextureFeatures("MAP", kind=kind, tiled=tiled)) == PipelinePlan(
        kind=expected,
        periodic=tiled,
    )


def test_data_and_exact_raster_are_left_at_native_size() -> None:
    image = Image.fromarray(np.array([[0, 3], [7, 9]], dtype=np.uint8), mode="P")
    image.putpalette([value for index in range(256) for value in (index, 0, 255 - index)])
    data = upscale_texture(image, TextureFeatures("DATA", kind=TextureKind.DATA))
    exact_raster = upscale_texture(image, TextureFeatures("CURSOR", exact_raster=True))

    assert data.mode == "P"
    assert data.size == image.size
    assert np.array_equal(np.asarray(data), np.asarray(image))
    assert exact_raster.mode == "P"
    assert exact_raster.size == image.size
    assert exact_raster.getpalette() == image.getpalette()
    assert np.array_equal(np.asarray(exact_raster), np.asarray(image))


def test_alpha_stays_paletted_grayscale() -> None:
    image = Image.fromarray(np.array([[0, 255], [255, 0]], dtype=np.uint8), mode="L")
    result = upscale_texture(image, TextureFeatures("OP", kind=TextureKind.ALPHA, tiled=True))
    assert result.mode == "P"
    assert result.size == (8, 8)
    palette = result.getpalette()
    assert palette is not None
    assert palette[:6] == [0, 0, 0, 1, 1, 1]


@pytest.mark.parametrize("tiled", [False, True])
def test_color_combinations_compose_with_edge_handling(tiled: bool) -> None:
    source = np.array(
        [[[1, 2, 3], [4, 5, 6]], [[7, 8, 9], [10, 11, 12]]],
        dtype=np.uint8,
    )
    image = Image.fromarray(source, mode="RGB")
    result = upscale_texture(
        image, TextureFeatures("COLOR", tiled=tiled), upscaler=NearestBackend()
    )
    expected = image.resize((8, 8), Image.Resampling.NEAREST)
    assert np.array_equal(np.asarray(result), np.asarray(expected))


@pytest.mark.parametrize("tiled", [False, True])
def test_alpha_test_restores_only_a_smooth_binary_key(tiled: bool) -> None:
    source = np.array(
        [
            [KEY_COLOR, [20, 30, 40], [50, 60, 70]],
            [[80, 90, 100], KEY_COLOR, [110, 120, 130]],
        ],
        dtype=np.uint8,
    )
    result = upscale_texture(
        Image.fromarray(source, mode="RGB"),
        TextureFeatures("KEYED", tiled=tiled, alphatest=True),
        upscaler=NearestBackend(),
    )
    output = np.asarray(result)
    mask = np.all(output == KEY_COLOR, axis=2)
    expected = upscale_key_mask(
        np.all(source == KEY_COLOR, axis=2),
        4,
        periodic=tiled,
    )
    expected[0, 0] = True
    assert np.array_equal(mask, expected)


def test_signed_distance_key_mask_smooths_diagonal_steps_without_gray_pixels() -> None:
    mask = np.array(
        [
            [True, True, False],
            [True, False, False],
            [False, False, False],
        ],
        dtype=np.bool_,
    )

    result = upscale_key_mask(mask, 4)
    nearest = np.repeat(np.repeat(mask, 4, axis=0), 4, axis=1)

    assert result.dtype == np.bool_
    assert result.shape == (12, 12)
    assert not np.array_equal(result, nearest)
    # The descending contour moves across subpixel rows instead of retaining
    # the source mask's two rectangular 4x staircase blocks.
    assert len(set(result.sum(axis=1)[:8])) > 2


def test_exact_raster_alpha_test_stays_native_without_ai() -> None:
    source = np.array([[KEY_COLOR, [20, 30, 40]]], dtype=np.uint8)
    result = upscale_texture(
        Image.fromarray(source, mode="RGB"),
        TextureFeatures("CURSOR", alphatest=True, exact_raster=True),
        upscaler=FailingBackend(),
    )

    assert result.size == (2, 1)
    assert np.array_equal(np.asarray(result), source)


@pytest.mark.parametrize("name", ["FONT", "F_MONO_T7X12.BMP", "F_STATUS_DEFAULT.BMP"])
def test_font_atlas_is_left_byte_exact_without_ai(name: str) -> None:
    source = np.array(
        [[KEY_COLOR, [255, 255, 255], [0, 0, 0], KEY_COLOR]],
        dtype=np.uint8,
    )
    result = upscale_texture(
        Image.fromarray(source, mode="RGB"),
        TextureFeatures(name, alphatest=True, font_atlas=True),
        upscaler=FailingBackend(),
        edge_padding=0,
    )

    assert result.size == (4, 1)
    assert np.array_equal(np.asarray(result), source)


def test_recognized_font_atlas_requires_file_aware_regeneration() -> None:
    image = Image.new("RGB", (4, 2), tuple(KEY_COLOR))
    with pytest.raises(RuntimeError, match="file-aware font-atlas copier"):
        upscale_texture(
            image,
            TextureFeatures("F_ARIAL_T8.BMP", font_atlas=True),
            upscaler=FailingBackend(),
        )


def test_alpha_test_hides_deep_keyed_interiors_from_ai() -> None:
    source = np.full((80, 80, 3), KEY_COLOR, dtype=np.uint8)
    source[39:41, 39:41] = [20, 40, 60]
    backend = CapturingBackend()

    upscale_texture(
        Image.fromarray(source, mode="RGB"),
        TextureFeatures("DEEP_KEY", alphatest=True),
        upscaler=backend,
    )

    assert backend.source is not None
    assert not np.any(np.all(np.asarray(backend.source) == KEY_COLOR, axis=2))


def test_fully_keyed_texture_does_not_need_ai() -> None:
    image = Image.new("RGB", (2, 3), tuple(KEY_COLOR))
    result = upscale_texture(
        image,
        TextureFeatures("EMPTY", alphatest=True),
        upscaler=FailingBackend(),
    )

    assert result.size == (8, 12)
    assert np.all(np.asarray(result) == KEY_COLOR)


def test_alpha_test_requires_color_key_somewhere() -> None:
    image = Image.new("RGB", (2, 2), (20, 30, 40))
    with pytest.raises(ValueError, match="contains no GK3 color key"):
        upscale_texture(
            image,
            TextureFeatures("INVALID", alphatest=True),
            upscaler=NearestBackend(),
        )


@pytest.mark.parametrize("periodic", [False, True])
def test_interior_key_is_separated_from_ai_and_keeps_opaque_corner(*, periodic: bool) -> None:
    source = np.full((8, 8, 3), [20, 30, 40], dtype=np.uint8)
    source[2:6, 2:6] = KEY_COLOR
    image = Image.fromarray(source)
    backend = CapturingBackend()
    result = upscale_texture(
        image, TextureFeatures("KEYED_PHOTO.BMP", alphatest=True, tiled=periodic), upscaler=backend
    )
    assert backend.source is not None
    assert not np.any(np.all(np.asarray(backend.source) == KEY_COLOR, axis=2))
    expected_mask = upscale_key_mask(np.all(source == KEY_COLOR, axis=2), 4, periodic=periodic)
    output = np.asarray(result)
    assert np.array_equal(np.all(output == KEY_COLOR, axis=2), expected_mask)
    assert np.array_equal(output[0, 0], [20, 30, 40])
    refreshed = apply_alpha_test_mask(image, result, periodic=periodic)
    assert np.array_equal(np.asarray(refreshed), output)


def test_ai_backend_must_return_its_declared_rgb_scale() -> None:
    image = Image.new("RGB", (2, 2))
    with pytest.raises(ValueError, match="AI backend returned"):
        upscale_texture(image, TextureFeatures("PHOTO"), upscaler=WrongSizeBackend())


def test_ai_route_requires_backend() -> None:
    image = Image.new("RGB", (2, 2))
    with pytest.raises(RuntimeError, match="requires SeedVR2"):
        upscale_texture(image, TextureFeatures("PHOTO"))


def test_keyed_geometric_resampling_preserves_contour_color_and_opaque_corners() -> None:
    y, x = np.ogrid[:32, :48]
    mask = (x - 24) ** 2 + (y - 16) ** 2 < 12**2
    rgb = np.full((32, 48, 3), (8, 12, 16), dtype=np.uint8)
    rgb[mask] = KEY_COLOR
    result = np.asarray(resample_keyed_art(Image.fromarray(rgb), scale=4))
    enlarged_mask = np.all(result == KEY_COLOR, axis=2)
    assert np.array_equal(enlarged_mask, upscale_key_mask(mask, 4))
    assert not enlarged_mask[0, 0]
    assert np.all(result[~enlarged_mask] == [8, 12, 16])
    # The contour is not a blockwise replica, but preserves the input's center
    # classification and does not spread magenta into opaque interpolated RGB.
    assert not np.array_equal(enlarged_mask, np.repeat(np.repeat(mask, 4, axis=0), 4, axis=1))
    assert np.array_equal(enlarged_mask[2::4, 2::4], mask)


@pytest.mark.parametrize("color", [(0, 0, 0), (255, 0, 255)])
def test_keyed_resampling_handles_empty_and_solid_masks(color: tuple[int, int, int]) -> None:
    result = resample_keyed_art(Image.new("RGB", (3, 5), color), scale=4)
    assert result.size == (12, 20)
    assert result.getcolors() == [(240, color)]
