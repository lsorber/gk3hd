"""Verified larger-source inventory reconstruction without AI or glyph reshaping."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.analyze.classify import classify_texture
from gk3hd.textures.analyze.policy import load_policy
from gk3hd.textures.bmp import inspect_bmp
from gk3hd.textures.install.conversion import _save_bmp
from gk3hd.textures.model import TextureFeatures, TextureKind
from gk3hd.textures.native_bmp import encode_rgb565
from gk3hd.textures.routing import PipelineKind, plan_texture
from gk3hd.textures.upscale.pipeline import resample_monotone_art
from gk3hd.textures.upscale.thumbnail import (
    _framed_thumbnail,
    _shared_backdrop,
    is_current_thumbnail,
    regenerate_thumbnail,
)
from gk3hd.textures.upscale.thumbnail_recipes import (
    FRAMED_THUMBNAIL_SIZES,
    RGB565_THUMBNAIL_SIZES,
    ThumbnailRecipe,
    thumbnail_recipe,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("black_level", [0, 8])
@pytest.mark.parametrize("preserve_cutouts", [False, True])
def test_framed_art_distinguishes_black_ink_from_verified_cutouts(
    black_level: int, preserve_cutouts: bool
) -> None:
    background = (120, 20, 5)
    small = Image.new("RGB", (32, 32), background)
    large = Image.new("RGB", (64, 64))
    large.paste((200, 150, 90), (12, 12, 52, 52))
    large.paste((black_level,) * 3, (24, 24, 40, 40))
    recipe = ThumbnailRecipe(
        (32, 32),
        0.25,
        (8, 8),
        source_size=large.size,
        frame_inset=3,
        preserve_cutouts=preserve_cutouts,
    )

    result = _framed_thumbnail(small, large, recipe)

    assert result.getpixel((66, 66)) == (background if preserve_cutouts else (black_level,) * 3)
    assert result.getpixel((50, 66)) == (200, 150, 90)
    assert result.crop((0, 0, 12, 128)).tobytes() == (
        resample_monotone_art(small).crop((0, 0, 12, 128)).tobytes()
    )


@pytest.mark.parametrize("bias", [-250.0, 50.0, 250.0])
def test_state_tone_changes_keep_clear_pixels_and_frame_unchanged(bias: float) -> None:
    backdrop = (20, 70, 120)
    small = Image.new("RGB", (32, 32), backdrop)
    large = Image.new("RGB", (64, 64))
    large.paste((100, 150, 200), (16, 16, 48, 48))
    recipe = ThumbnailRecipe(
        (32, 32),
        0.25,
        (8, 8),
        source_size=large.size,
        frame_inset=3,
        brightness=1.5,
        brightness_offset=bias,
    )
    dense = _framed_thumbnail(small, large, recipe)
    assert dense.getpixel((16, 64)) == backdrop
    assert dense.getpixel((64, 64)) == tuple(
        round(max(0, min(255, value * 1.5 + bias))) for value in (100, 150, 200)
    )
    assert dense.crop((0, 0, 12, 128)).tobytes() == (
        resample_monotone_art(small).crop((0, 0, 12, 128)).tobytes()
    )


def test_only_opacity_verified_object_recipes_preserve_cutouts() -> None:
    cutouts = {
        name
        for name in FRAMED_THUMBNAIL_SIZES
        if (recipe := thumbnail_recipe(name)) is not None and recipe.preserve_cutouts
    }
    assert cutouts == {
        f"{family}_{state}.BMP"
        for family in ("I_MOSROOMKEY", "I_MOPEDKEY", "I_HARLEYKEY", "I_HANGER", "I_MEDALLION")
        for state in ("STD", "HOV", "DWN")
    }


def test_declared_source_key_preserves_holes_and_black_ink_without_magenta_fringe() -> None:
    backdrop = (30, 0, 0)
    small = Image.new("RGB", (32, 32), backdrop)
    large = Image.new("RGB", (64, 64), (255, 0, 255))
    large.paste((0, 180, 0), (12, 12, 52, 52))
    large.paste((0, 0, 0), (16, 16, 24, 24))
    large.paste((255, 0, 255), (32, 32, 40, 40))
    recipe = ThumbnailRecipe(
        (32, 32),
        0.25,
        (8, 8),
        source_size=large.size,
        frame_inset=3,
        source_color_key=(255, 0, 255),
    )
    result = _framed_thumbnail(small, large, recipe)
    assert result.getpixel((53, 53)) == (0, 0, 0)
    assert result.getpixel((69, 69)) == backdrop
    assert result.getchannel("B").getextrema() == (0, 0)


def test_separate_axis_scale_reproduces_authored_whole_object_dimensions() -> None:
    small = Image.new("RGB", (32, 32), (30, 0, 0))
    large = Image.new("RGB", (32, 32))
    large.paste((0, 200, 0), (8, 8, 24, 24))
    recipe = ThumbnailRecipe(
        (32, 32), 0.5, (8, 4), source_size=large.size, frame_inset=3, source_scale_y=1.0
    )
    result = _framed_thumbnail(small, large, recipe)
    bounds = result.getchannel("G").point(lambda value: 255 if value >= 100 else 0).getbbox()
    assert bounds is not None
    left, top, right, bottom = bounds
    assert (right - left, bottom - top) == (32, 64)


@pytest.mark.parametrize(
    "name",
    [
        "SNOTE3.BMP",
        "SNOTE9.BMP",
        "GRANOTEBK3.BMP",
        "GRANOTEBK9.BMP",
        "BLUEAPPLE3.BMP",
        "BLUEAPPLE9.BMP",
        "UNDEFINED9.BMP",
    ],
)
def test_reconstruction_uses_original_large_source_and_refreshes(tmp_path: Path, name: str) -> None:
    recipe = thumbnail_recipe(name)
    assert recipe is not None
    small = tmp_path / name
    large = tmp_path / recipe.source_name.lower()
    Image.new("RGB", recipe.size, (0, 0, 0)).save(small)
    Image.new("RGB", recipe.source_size, (180, 120, 60)).save(large)
    result = regenerate_thumbnail(small)
    assert result.size == tuple(dimension * 4 for dimension in recipe.size)
    assert result.mode == "RGB"
    assert result.getpixel((result.width // 2, result.height // 2)) == (180, 120, 60)
    output = tmp_path / "output.png"
    result.save(output)
    assert is_current_thumbnail(small, output)
    Image.new("RGB", recipe.source_size, (90, 60, 30)).save(large)
    assert not is_current_thumbnail(small, output)
    assert plan_texture(TextureFeatures(name=name)).kind is PipelineKind.THUMBNAIL_SOURCE_4X


def test_recipe_does_not_override_other_semantics() -> None:
    for properties in (
        {"kind": TextureKind.DATA},
        {"kind": TextureKind.ALPHA},
        {"exact_raster": True},
        {"native_size": True},
        {"font_atlas": True},
        {"alphatest": True},
        {"tiled": True},
    ):
        feature = TextureFeatures(name="SNOTE9.BMP").with_overrides(properties)
        assert plan_texture(feature).kind is not PipelineKind.THUMBNAIL_SOURCE_4X
    assert thumbnail_recipe("OTHER9.BMP") is None


@pytest.mark.parametrize("state", ["STD", "HOV", "DWN"])
def test_verified_blood_bank_alias_shares_its_exact_state_recipe(state: str) -> None:
    alias = f"I_GABBBANK_{state}.BMP"
    canonical = f"I_BBANKGAB_{state}.BMP"
    recipe = thumbnail_recipe(canonical)
    assert recipe is not None
    assert thumbnail_recipe(alias) is recipe
    assert recipe.source_name == "BBANK6_ALPHA.BMP"
    assert RGB565_THUMBNAIL_SIZES[alias] == FRAMED_THUMBNAIL_SIZES[alias] == (32, 32)
    assert thumbnail_recipe(f"I_GABBBANKOTHER_{state}.BMP") is None


def test_verified_single_hover_alias_does_not_invent_other_states() -> None:
    alias = "I_ABBEPRNT_HOV.BMP"
    recipe = thumbnail_recipe("I_ABBEPRINT_HOV.BMP")
    assert recipe is not None
    assert thumbnail_recipe(alias) is recipe
    assert recipe.source_name == "ABBEPRNT6_ALPHA.BMP"
    assert RGB565_THUMBNAIL_SIZES[alias] == FRAMED_THUMBNAIL_SIZES[alias] == (32, 32)
    for state in ("STD", "DWN", "DIS"):
        assert thumbnail_recipe(f"I_ABBEPRNT_{state}.BMP") is None


def test_riddle_thumbnails_use_the_matching_page_not_the_different_closeup() -> None:
    for name in ("BLUEAPPLE3.BMP", "BLUEAPPLE9.BMP"):
        recipe = thumbnail_recipe(name)
        assert recipe is not None
        assert recipe.source_name == "BLUEAPPLE.BMP"
        assert recipe.source_size == (640, 480)
    assert thumbnail_recipe("BLUEAPPLE6_ALPHA.BMP") is None


def test_opaque_inventory_fallback_uses_shipped_detail_and_native_format(tmp_path: Path) -> None:
    name = "UNDEFINED9.BMP"
    recipe = thumbnail_recipe(name)
    assert recipe is not None
    assert recipe.source_name == "UNDEFINED6.BMP"
    assert recipe.source_size == (640, 400)
    assert RGB565_THUMBNAIL_SIZES[name] == recipe.size == (94, 94)
    assert name not in FRAMED_THUMBNAIL_SIZES
    image = Image.new("RGB", (376, 376), (97, 131, 173))
    destination = tmp_path / name
    _save_bmp(image, destination, mode="RGB")
    assert destination.read_bytes() == encode_rgb565(image)


def test_missing_or_incompatible_originals_fail_clearly(tmp_path: Path) -> None:
    small = tmp_path / "SNOTE9.BMP"
    Image.new("RGB", (94, 94)).save(small)
    with pytest.raises(FileNotFoundError, match="requires original SNOTE6_ALPHA"):
        regenerate_thumbnail(small)
    Image.new("RGB", (600, 399)).save(tmp_path / "SNOTE6_ALPHA.BMP")
    with pytest.raises(ValueError, match="unsupported size"):
        regenerate_thumbnail(small)
    with pytest.raises(ValueError, match="no verified larger source"):
        regenerate_thumbnail(tmp_path / "OTHER.BMP")


@pytest.mark.parametrize(
    "name",
    [
        "I_MANILACLOSE_HOV.BMP",  # Rotated opaque page with hover tone.
        "I_NOTEARMNE_STD.BMP",  # Rotated color-keyed artwork.
        "I_BLKMOUSTACHE_STD.BMP",  # Independent horizontal/vertical scales.
        "I_GLDBLAZER_HOV.BMP",  # Color key and hover tone.
        "I_HAT_STD.BMP",  # Plain opaque artwork.
        "I_HANGER_STD.BMP",  # Opacity-verified cutouts.
        "I_HARLEYKEY_HOV.BMP",  # Rotated cutouts and tone.
        "I_MOSLICENSE_DWN.BMP",  # Shared backdrop and pressed state.
    ],
)
def test_document_menu_states_use_real_detail_and_native_transport(
    tmp_path: Path, name: str
) -> None:
    recipe = thumbnail_recipe(name)
    assert recipe is not None
    source = tmp_path / name
    original = Image.new("RGB", recipe.size, (120, 0, 0))
    original.save(source)
    # Like the real angled cards, keep background visible around the artwork.
    # A fully opaque source rectangle can cover an entire final background row,
    # correctly triggering the missing-background guard rather than testing ink.
    large = Image.new("RGB", recipe.source_size, recipe.source_color_key or (0, 0, 0))
    margin_x, margin_y = (
        (120, 80) if recipe.source_color_key or recipe.source_size == (640, 400) else (50, 50)
    )
    if recipe.source_color_key:
        # Keyed object renders occupy only part of their wide source canvas.
        # A synthetic page spanning that canvas can hide the whole backdrop.
        margin_x = max(margin_x, large.width // 3)
    large.paste(
        (180, 120, 60),
        (margin_x, margin_y, large.width - margin_x, large.height - margin_y),
    )
    # This black area is ink for solid-art recipes and a hole for cutout recipes.
    # Keep it enclosed even in short card/key sources; touching the page edge
    # makes it background rather than the enclosed ink this test exercises.
    source_ink_y = min(150, large.height // 2)
    source_ink_x = margin_x + 75
    ink_half_height = min(35, (large.height - 100) // 2 - 8)
    large.paste(
        (0, 0, 0),
        (
            source_ink_x - 45,
            source_ink_y - ink_half_height,
            source_ink_x + 45,
            source_ink_y + ink_half_height,
        ),
    )
    large.save(tmp_path / recipe.source_name)
    for background_name in recipe.background_sources or ():
        original.save(tmp_path / background_name.lower())
    result = regenerate_thumbnail(source)
    assert result.size == (128, 128)
    # Track one interior ink point through the whole-image transform, including
    # rotated documents, instead of assuming every recipe puts it at the center.
    angle = math.radians(recipe.rotation_degrees)
    ink_x = recipe.offset[0] + recipe.source_scale * (
        source_ink_x * math.cos(angle) - source_ink_y * math.sin(angle)
    )
    ink_y = recipe.offset[1] + (recipe.source_scale_y or recipe.source_scale) * (
        source_ink_x * math.sin(angle) + source_ink_y * math.cos(angle)
    )
    ink_tone = round(max(0, min(255, recipe.brightness_offset)))
    expected_black_region = (120, 0, 0) if recipe.preserve_cutouts else (ink_tone,) * 3
    assert (
        result.getpixel((round((ink_x + 0.5) * 4 - 0.5), round((ink_y + 0.5) * 4 - 0.5)))
        == expected_black_region
    )
    assert (
        result.crop((0, 0, 12, 128)).tobytes()
        == resample_monotone_art(original).crop((0, 0, 12, 128)).tobytes()
    )
    info = inspect_bmp(source)
    features = classify_texture(name, info, {name: info}, action_button=True)
    features = load_policy().apply(features, info)
    assert not features.exact_raster
    assert plan_texture(features).kind is PipelineKind.THUMBNAIL_SOURCE_4X
    output = tmp_path / "output.png"
    result.save(output)
    assert is_current_thumbnail(source, output)
    destination = tmp_path / "converted" / name
    destination.parent.mkdir()
    _save_bmp(result, destination, mode="RGB")
    assert destination.read_bytes() == encode_rgb565(result)
    # Both the larger detail and the state-specific frame are cache dependencies.
    original.putpixel((0, 0), (248, 248, 248))
    original.save(source)
    assert not is_current_thumbnail(source, output)
    original.putpixel((4, 4), (255, 0, 255))
    original.save(source)
    keyed = inspect_bmp(source)
    assert (
        load_policy()
        .apply(classify_texture(name, keyed, {name: keyed}, action_button=True), keyed)
        .exact_raster
    )


@pytest.mark.parametrize(
    "family",
    sorted(
        {
            name.removesuffix("_STD.BMP")
            for name in FRAMED_THUMBNAIL_SIZES
            if name.endswith("_STD.BMP")
        }
    ),
)
def test_document_states_share_geometry_and_preserve_authored_press_offset(family: str) -> None:
    recipes = [thumbnail_recipe(f"{family}_{state}.BMP") for state in ("STD", "HOV", "DWN")]
    assert all(recipe is not None for recipe in recipes)
    normal, hover, pressed = recipes
    assert normal is not None
    assert hover is not None
    assert pressed is not None
    assert normal.offset == hover.offset
    pressed_shift = (
        0
        if family in {"I_COATNCAP", "I_EGYPTP", "I_PCARDTEMPTATION"}
        or normal.source_scale_y is not None
        else 1
    )
    assert pressed.offset == tuple(value + pressed_shift for value in normal.offset)
    assert normal.source_scale == hover.source_scale == pressed.source_scale
    assert normal.source_scale_y == hover.source_scale_y == pressed.source_scale_y
    assert normal.source_color_key == hover.source_color_key == pressed.source_color_key
    assert normal.rotation_degrees == hover.rotation_degrees == pressed.rotation_degrees
    toned_paper = family in {
        "I_MANILACLOSE",
        "I_POEM",
        "I_BLUEAPPLES",
        "I_EGYPTP",
        "I_GRACEPASS",
        "I_NOTEARMNE",
        "I_PCARDSTANSTP",
        "I_PCARDTEMPTATION",
        "I_WILLETTER",
        "I_WILLICENSE",
        "I_MOSLICENSE",
        "I_MOSPRNT",
        "I_FREELANCEGAB",
        "I_GABWALLET",
        "I_PREPH",
        "I_HARLEYKEY",
        "I_PHOTOEGYPT",
        "I_MANILAOPEN",
    }
    if toned_paper:
        if family == "I_POEM":
            assert normal.rotation_degrees == pytest.approx(-8.85354570985931)
        else:
            assert abs(normal.rotation_degrees) < 6
        if family == "I_PCARDTEMPTATION":
            assert normal == hover == pressed
        else:
            assert pressed.brightness < normal.brightness < hover.brightness
            assert normal.brightness_offset == 0 < hover.brightness_offset
            assert abs(pressed.brightness_offset) < 12
    elif family in {"I_HAT", "I_COATNCAP"} or normal.source_scale_y is not None:
        assert pressed.brightness < normal.brightness < hover.brightness
        assert pressed.brightness_offset < normal.brightness_offset == 0 < hover.brightness_offset
    else:
        assert (normal.brightness, hover.brightness, pressed.brightness) == (1, 4 / 3, 5 / 6)
        assert normal.brightness_offset == hover.brightness_offset == pressed.brightness_offset == 0
    if not toned_paper:
        assert normal.rotation_degrees == (-45 if family == "I_PASSPORTMOS" else 0)


@pytest.mark.parametrize("state", ["STD", "HOV", "DWN"])
def test_paper_variants_use_matching_art_not_generic_inventory_association(state: str) -> None:
    poem = thumbnail_recipe(f"I_POEM_{state}.BMP")
    envelope = thumbnail_recipe(f"I_MANILACLOSE_{state}.BMP")
    assert poem is not None
    assert envelope is not None
    # The icon has no handwritten annotation; the generic POEM association does.
    assert poem.source_name == "POEMWONOTE6_ALPHA.BMP"
    # The closed envelope must not acquire the visible letter in MANILLAO.
    assert envelope.source_name == "MANILLAC6_ALPHA.BMP"


def test_batch_keeps_mismatched_scan_and_unverified_state_names_out() -> None:
    # Montreaux has different card artwork/state placement. Do not infer
    # additional states for legacy files or sources from shared inventory nouns.
    assert thumbnail_recipe("I_MON_STD.BMP") is None
    assert thumbnail_recipe("I_MANU1PRINT_STD.BMP") is None
    assert thumbnail_recipe("I_LSRPRINTGABE_STD.BMP") is None


@pytest.mark.parametrize(
    ("family", "source"),
    [
        ("I_MANU1PRINT", "MANU1PRINT_6_ALPHA.BMP"),
        ("I_MANU2PRINT", "MANU2PRINT_6_ALPHA.BMP"),
        ("I_MANU3PRINT", "MANU3PRINT_6_ALPHA.BMP"),
        ("I_LSRPRINTGABE", "LSRPRINTGRACE_6_ALPHA.BMP"),
        ("I_FAKEID", "FAKEID6_ALPHA.BMP"),
    ],
)
def test_legacy_scan_states_use_their_own_whole_card(family: str, source: str) -> None:
    normal = thumbnail_recipe(f"{family}.BMP")
    hover = thumbnail_recipe(f"{family}_HOV.BMP")
    pressed = thumbnail_recipe(f"{family}D.BMP")
    assert normal is not None
    assert hover is not None
    assert pressed is not None
    assert normal.source_name == hover.source_name == pressed.source_name == source
    assert normal.source_scale == hover.source_scale == pressed.source_scale
    assert normal.rotation_degrees == hover.rotation_degrees == pressed.rotation_degrees
    assert normal.offset == hover.offset
    assert pressed.offset == tuple(value + 1 for value in normal.offset)
    assert pressed.brightness < normal.brightness < hover.brightness
    assert all(recipe.source_scale_y is None for recipe in (normal, hover, pressed))
    assert all(not recipe.preserve_cutouts for recipe in (normal, hover, pressed))


def test_unresolved_gauntlet_view_is_not_approved_with_the_clothing_batch() -> None:
    for state in ("STD", "HOV", "DWN"):
        assert thumbnail_recipe(f"I_GAUNTLET_{state}.BMP") is None


@pytest.mark.parametrize(
    ("family", "source", "pressed_shift"),
    [
        ("I_FINGRPRNTKIT", "FINGRPRNTKIT6_ALPHA.BMP", 1),
        ("I_COATNSTASHNCAP", "COATNSTASHNCAP_6_ALPHA.BMP", 0),
    ],
)
def test_legacy_rendered_items_preserve_authored_state_offsets(
    family: str, source: str, pressed_shift: int
) -> None:
    normal, hover, pressed = (
        thumbnail_recipe(f"{family}{suffix}.BMP") for suffix in ("", "_HOV", "D")
    )
    assert normal is not None
    assert hover is not None
    assert pressed is not None
    assert normal.source_name == hover.source_name == pressed.source_name == source
    assert normal.offset == hover.offset
    assert pressed.offset == tuple(value + pressed_shift for value in normal.offset)
    assert normal.source_scale == hover.source_scale == pressed.source_scale
    assert normal.rotation_degrees == hover.rotation_degrees == pressed.rotation_degrees
    assert pressed.brightness < normal.brightness < hover.brightness


@pytest.mark.parametrize("state", ["STD", "HOV", "DWN"])
def test_wallet_key_is_removed_from_larger_source_not_the_opaque_button(state: str) -> None:
    recipe = thumbnail_recipe(f"I_GABWALLET_{state}.BMP")
    assert recipe is not None
    assert recipe.source_name == "GABEWALLET6_ALPHA.BMP"
    assert recipe.source_color_key == (255, 0, 255)


@pytest.mark.parametrize("state", ["STD", "HOV", "DWN"])
def test_open_envelope_keeps_visible_letter_and_rejected_key_stays_unregistered(state: str) -> None:
    recipe = thumbnail_recipe(f"I_MANILAOPEN_{state}.BMP")
    assert recipe is not None
    assert recipe.source_name == "MANILLAO6_ALPHA.BMP"
    assert not recipe.preserve_cutouts
    assert thumbnail_recipe(f"I_GRARM_{state}.BMP") is None


def test_rotated_paper_keeps_ink_opaque_and_preserves_its_frame() -> None:
    small = Image.new("RGB", (32, 32), (120, 0, 0))
    large = Image.new("RGB", (10, 10), (255, 255, 255))
    large.paste((0, 0, 0), (3, 3, 7, 7))
    recipe = ThumbnailRecipe((32, 32), 1.0, (20, 4), frame_inset=3, rotation_degrees=90)
    result = _framed_thumbnail(small, large, recipe)
    assert result.getpixel((66, 34)) == (0, 0, 0)
    assert result.crop((0, 0, 12, 128)).tobytes() == (
        resample_monotone_art(small).crop((0, 0, 12, 128)).tobytes()
    )


def test_rotated_paper_can_cover_whole_rows_without_contaminating_background() -> None:
    small = Image.new("RGB", (32, 32), (120, 0, 0))
    large = Image.new("RGB", (10, 10), (255, 255, 255))
    recipe = ThumbnailRecipe((32, 32), 3.0, (16, -5), frame_inset=3, rotation_degrees=45)
    result = _framed_thumbnail(small, large, recipe)
    assert result.getpixel((66, 66)) == (255, 255, 255)
    assert result.getpixel((14, 14)) == (120, 0, 0)


def test_missing_background_without_bracketing_evidence_is_rejected() -> None:
    small = Image.new("RGB", (32, 32), (120, 0, 0))
    large = Image.new("RGB", (100, 100), (255, 255, 255))
    recipe = ThumbnailRecipe((32, 32), 1.0, (-30, -30), frame_inset=3)
    with pytest.raises(ValueError, match="no bracketing original background samples"):
        _framed_thumbnail(small, large, recipe)


@pytest.mark.parametrize("fault", [None, "disagree", "target", "ambiguous", "few", "flat", "size"])
def test_shared_backdrop_requires_independent_original_evidence(fault: str | None) -> None:
    pixels = np.zeros((32, 32, 3), dtype=np.uint8)
    pixels[:, :, 0] = np.arange(32, dtype=np.uint8)[:, None] * 4
    background = pixels.astype(float)
    sampled = np.zeros(32, dtype=bool)
    sampled[3:20] = True
    left, right = Image.fromarray(pixels), Image.fromarray(pixels)
    expected = pixels[:, 0].copy()
    if fault == "disagree":
        right.paste((250, 20, 10), (3, 26, 29, 27))
    elif fault == "target":
        background[10, :, 0] += 1
    elif fault == "ambiguous":
        left.paste((255, 255, 255), (3, 26, 16, 27))
    elif fault == "few":
        sampled[6:] = False
    elif fault == "flat":
        background[sampled] = 0
    elif fault == "size":
        right = right.resize((31, 32))
    if fault is not None:
        with pytest.raises(ValueError, match="shared backdrop"):
            _shared_backdrop((left, right), background, sampled, 3)
    else:
        result = _shared_backdrop((left, right), background, sampled, 3)
        np.testing.assert_array_equal(result[3:29], expected[3:29])


def test_shared_originals_fill_unbracketed_rows_without_extrapolating() -> None:
    pixels = np.zeros((32, 32, 3), dtype=np.uint8)
    pixels[:, :, 0] = np.arange(32, dtype=np.uint8)[:, None] * 4
    small = Image.fromarray(pixels)
    large = Image.new("RGB", (100, 100), (240, 240, 240))
    recipe = ThumbnailRecipe((32, 32), 1, (-70.8, 16), frame_inset=3)
    with pytest.raises(ValueError, match="no bracketing"):
        _framed_thumbnail(small, large, recipe)
    result = _framed_thumbnail(small, large, recipe, backdrops=(small, small.copy()))
    assert result.size == (128, 128)
    assert result.getpixel((60, 100)) == (240, 240, 240)
    assert result.crop((0, 0, 12, 128)).tobytes() == (
        resample_monotone_art(small).crop((0, 0, 12, 128)).tobytes()
    )
    conflicting = small.copy()
    conflicting.paste((255, 0, 0), (3, 26, 29, 27))
    with pytest.raises(ValueError, match="originals disagree"):
        _framed_thumbnail(small, large, recipe, backdrops=(small, conflicting))


@pytest.mark.parametrize("state", ["STD", "HOV", "DWN"])
def test_license_uses_real_whole_document_and_only_pressed_background_witnesses(state: str) -> None:
    recipe = thumbnail_recipe(f"I_MOSLICENSE_{state}.BMP")
    assert recipe is not None
    assert recipe.source_name == "MOSLICPLATE6_ALPHA.BMP"
    assert recipe.source_size == (369, 398)
    assert not recipe.preserve_cutouts
    assert recipe.source_scale_y is None
    assert recipe.background_sources == (
        ("I_BLKMARKER_DWN.BMP", "I_DAGGER_DWN.BMP") if state == "DWN" else None
    )
