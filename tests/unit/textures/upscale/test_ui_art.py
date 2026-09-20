"""Geometric UI resampling preserves authored borders and avoids invented details."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

from gk3hd.patch.definitions.runtime2d.inventory_navigation import IMAGES
from gk3hd.patch.definitions.runtime2d.system.resource_dimensions import _DENSE_CONTROL_SIZES
from gk3hd.patch.definitions.runtime2d.ui_frames import (
    BORDER_IMAGES,
    CONSOLE_IMAGES,
    DEATH_BUTTON_IMAGES,
    DETAILED_ACTION_IMAGES,
    DIALOG_IMAGES,
    FINGERPRINT_TOOL_IMAGES,
    GPS_CONTROL_IMAGES,
    GPS_MAP_IMAGES,
    HELP_BUTTON_IMAGES,
    LEGACY_DOCUMENT_IMAGES,
    LEGACY_TOOLBAR_IMAGES,
    LOAD_SAVE_BUTTON_IMAGES,
    MESSAGE_BUTTON_IMAGES,
    OPTIONS_ACTION_IMAGES,
    OPTIONS_IMAGES,
    OPTIONS_LABEL_IMAGES,
    OPTIONS_PANEL_IMAGES,
    OPTIONS_TAB_IMAGES,
    PARCHMENT_IMAGES,
    QUIT_BUTTON_IMAGES,
    SIDNEY_CLUE_IMAGES,
    SIDNEY_FRAME_IMAGES,
    SIDNEY_GEOMETRY_IMAGES,
    SIDNEY_ID_IMAGES,
    SIDNEY_MAP_IMAGES,
    SIDNEY_MAP_OVERLAY_IMAGES,
    SIDNEY_NAVIGATION_IMAGES,
    SIDNEY_SEPARATOR_IMAGES,
    SIDNEY_SHAPE_IMAGES,
    SIDNEY_SHARED_CONTROL_IMAGES,
    SIDNEY_TAB_IMAGES,
    TIMEBLOCK_BUTTON_IMAGES,
    TITLE_BUTTON_IMAGES,
    TUTORIAL_IMAGES,
    ZODIAC_IMAGES,
)
from gk3hd.textures.model import TextureFeatures, TextureKind
from gk3hd.textures.routing import PipelineKind, plan_texture
from gk3hd.textures.upscale.cursor_art import CURSOR_ART_SIZES, CURSOR_OPACITY_SIZES
from gk3hd.textures.upscale.menu_art import CONSERVATIVE_MENU_SIZES, resample_menu_art
from gk3hd.textures.upscale.pipeline import resample_monotone_art
from gk3hd.textures.upscale.ui_art import (
    BINOCULAR_CONTROL_SIZES,
    BINOCULAR_LABEL_SIZES,
    BINOCULAR_MASK_NAME,
    DIALOG_ART_SIZES,
    FINGERPRINT_TOOL_SIZES,
    GPS_CONTROL_SIZES,
    GPS_MAP_SIZES,
    LEGACY_DOCUMENT_SIZES,
    MONOTONE_BUTTON_SIZES,
    OPTIONS_LABEL_SIZES,
    OPTIONS_PANEL_SIZES,
    PARCHMENT_SIZES,
    SIDNEY_CLUE_SIZES,
    SIDNEY_GEOMETRY_KEYS,
    SIDNEY_GEOMETRY_SIZES,
    SIDNEY_ID_SIZES,
    SIDNEY_MAP_OVERLAY_SIZES,
    SIDNEY_MAP_SIZES,
    SIDNEY_NAVIGATION_SIZES,
    SIDNEY_SEPARATOR_SIZES,
    SIDNEY_SHAPE_SIZES,
    SIDNEY_SHARED_CONTROL_SIZES,
    UI_ART_SIZES,
    ZODIAC_OVERLAY_SIZES,
    ZODIAC_PAGE_SIZES,
    is_current_ui_art,
    is_geometric_ui,
    regenerate_ui_art,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("name", FINGERPRINT_TOOL_SIZES)
def test_fingerprint_tools_preserve_key_and_reference_samples(tmp_path: Path, name: str) -> None:
    source = tmp_path / name
    width, height = FINGERPRINT_TOOL_SIZES[name]
    pixels = np.full((height, width, 3), (255, 0, 255), dtype=np.uint8)
    for y in range(4, height - 4):
        pixels[y, 6 : width - 6] = (50 + y, 40 + y // 3, 10 + y // 2)
    Image.fromarray(pixels).save(source)
    result = np.asarray(regenerate_ui_art(source))
    np.testing.assert_array_equal(result[2::4, 2::4], pixels)
    assert result.shape == (height * 4, width * 4, 3)
    # Extra contour/color samples genuinely differ from pixel replication.
    assert not np.array_equal(result, np.repeat(np.repeat(pixels, 4, 0), 4, 1))


@pytest.mark.parametrize(("name", "side"), [("MINISNAKY.BMP", 30), ("SNAKY.BMP", 100)])
def test_console_pattern_retains_reference_samples_and_periodic_edges(
    tmp_path: Path, name: str, side: int
) -> None:
    source = tmp_path / name
    values = np.arange(side * side * 3, dtype=np.uint16).reshape(side, side, 3)
    pixels = (values % 256).astype(np.uint8)
    Image.fromarray(pixels).save(source)
    enlarged = np.asarray(regenerate_ui_art(source))
    assert enlarged.shape == (side * 4, side * 4, 3)
    np.testing.assert_array_equal(enlarged[2::4, 2::4], pixels)
    # A one-pixel toroidal translation must be exactly four output pixels,
    # including the corners: clamped/reflected interpolation fails this test.
    shifted = np.roll(pixels, (1, 1), axis=(0, 1))
    Image.fromarray(shifted).save(source)
    np.testing.assert_array_equal(
        np.asarray(regenerate_ui_art(source)), np.roll(enlarged, (4, 4), axis=(0, 1))
    )
    assert (
        plan_texture(TextureFeatures(name=source.name, tiled=True)).kind
        is PipelineKind.UI_SOURCE_4X
    )


def test_verified_ui_family_matches_engine_resources_and_respects_exclusions() -> None:
    assert (
        {
            f"{name.decode().upper()}.BMP": (w, h)
            for name, w, h in (
                *IMAGES,
                *BORDER_IMAGES,
                *CONSOLE_IMAGES,
                *OPTIONS_IMAGES,
                *OPTIONS_PANEL_IMAGES,
                *OPTIONS_ACTION_IMAGES,
                *OPTIONS_LABEL_IMAGES,
                *SIDNEY_TAB_IMAGES,
                *OPTIONS_TAB_IMAGES,
                *DIALOG_IMAGES,
                *FINGERPRINT_TOOL_IMAGES,
                *DEATH_BUTTON_IMAGES,
                *TITLE_BUTTON_IMAGES,
                *TIMEBLOCK_BUTTON_IMAGES,
                *QUIT_BUTTON_IMAGES,
                *HELP_BUTTON_IMAGES,
                *LEGACY_TOOLBAR_IMAGES,
                *LEGACY_DOCUMENT_IMAGES,
                *MESSAGE_BUTTON_IMAGES,
                *LOAD_SAVE_BUTTON_IMAGES,
                *SIDNEY_FRAME_IMAGES,
                *SIDNEY_SEPARATOR_IMAGES,
                *SIDNEY_NAVIGATION_IMAGES,
                *SIDNEY_SHAPE_IMAGES,
                *GPS_CONTROL_IMAGES,
                *GPS_MAP_IMAGES,
                *SIDNEY_MAP_IMAGES,
                *SIDNEY_MAP_OVERLAY_IMAGES,
                *PARCHMENT_IMAGES,
                *SIDNEY_CLUE_IMAGES,
                *SIDNEY_GEOMETRY_IMAGES,
                *SIDNEY_ID_IMAGES,
                *SIDNEY_SHARED_CONTROL_IMAGES,
                *ZODIAC_IMAGES,
            )
        }
        | BINOCULAR_CONTROL_SIZES
        | BINOCULAR_LABEL_SIZES
        | CONSERVATIVE_MENU_SIZES
        | CURSOR_ART_SIZES
        | CURSOR_OPACITY_SIZES
        | {BINOCULAR_MASK_NAME: (640, 480)}
        == UI_ART_SIZES
    )
    assert all(
        (name.removesuffix(".BMP").lower().encode("ascii"), *size) in DETAILED_ACTION_IMAGES
        for name, size in CONSERVATIVE_MENU_SIZES.items()
    )
    # Binocular buttons use their existing owner-specific dimensions adapter;
    # the fullscreen aperture is resampled by the game, not that adapter.
    assert all(
        (w * 4, h * 4) in _DENSE_CONTROL_SIZES
        for w, h in (BINOCULAR_CONTROL_SIZES | BINOCULAR_LABEL_SIZES).values()
    )
    for name in UI_ART_SIZES:
        assert is_geometric_ui(name.lower())
        assert plan_texture(TextureFeatures(name)).kind is PipelineKind.UI_SOURCE_4X
    assert not is_geometric_ui("INV_SCROLLUP_OTHER.BMP")
    # Shared engine geometry does not force rendered diagrams into the geometric
    # resampler: their keyed artwork still follows the analyzed AI pipeline.
    assert all(not is_geometric_ui(f"{name.decode()}.BMP") for name, _, _ in TUTORIAL_IMAGES)
    for changes, route in (
        ({"kind": TextureKind.DATA}, PipelineKind.DATA_UNCHANGED),
        ({"kind": TextureKind.ALPHA}, PipelineKind.ALPHA_SMOOTH),
        ({"native_size": True}, PipelineKind.NATIVE_SIZE_UNCHANGED),
        ({"exact_raster": True}, PipelineKind.EXACT_RASTER_UNCHANGED),
        ({"font_atlas": True}, PipelineKind.FONT_ATLAS_UNCHANGED),
    ):
        assert (
            plan_texture(TextureFeatures("INV_HIGHLIGHT.BMP").with_overrides(changes)).kind is route
        )


@pytest.mark.parametrize(
    "name",
    [
        "INV_HIGHLIGHT.BMP",  # Exact keyed geometry.
        "S_FROM_TO.BMP",  # Shared control with native-grid sampling.
        "MINISNAKY.BMP",  # Periodic border.
        min(SIDNEY_SHAPE_SIZES),  # Fractional-phase artwork.
        min(OPTIONS_LABEL_SIZES),  # Monotone text.
        min(CONSERVATIVE_MENU_SIZES),  # Conservative keyed menu resampling.
    ],
)
@pytest.mark.slow
def test_ui_resampler_preserves_full_source_extent_and_invalidates_changes(
    tmp_path: Path, name: str
) -> None:
    source = tmp_path / name
    size = UI_ART_SIZES[name]
    original = Image.new(
        "RGB", size, (255, 0, 255) if name == "INV_HIGHLIGHT.BMP" else (110, 80, 20)
    )
    for y in range(size[1]):
        original.putpixel((0, y), (180, 0, 0))
    original.save(source)
    result = regenerate_ui_art(source)
    assert result.size == (size[0] * 4, size[1] * 4)
    method = (
        Image.Resampling.NEAREST
        if name.startswith(("HELP_BOX_", "MSG_BOX_", "RC_", "S_BOX_", "S_BUT"))
        or name in SIDNEY_NAVIGATION_SIZES
        or name in SIDNEY_SEPARATOR_SIZES
        or name in BINOCULAR_CONTROL_SIZES
        or (name in GPS_CONTROL_SIZES and not name.startswith("GPSPOWER_"))
        or name
        in {
            "INV_HIGHLIGHT.BMP",
            "INV_SCROLLBACK.BMP",
            "SAVELOAD_SCROLLBACK.BMP",
            "S_FROM_TO.BMP",
            "HORIZONTALRULE.BMP",
        }
        else Image.Resampling.BICUBIC
    )
    expected = (
        original.transform(
            result.size,
            Image.Transform.AFFINE,
            (0.25, 0, -0.125, 0, 0.25, -0.125),
            Image.Resampling.BICUBIC,
        )
        if name in SIDNEY_SHAPE_SIZES
        or (
            name in SIDNEY_SHARED_CONTROL_SIZES
            and name not in {"S_FROM_TO.BMP", "HORIZONTALRULE.BMP"}
        )
        or name in GPS_MAP_SIZES
        or name in SIDNEY_MAP_SIZES
        or name in SIDNEY_MAP_OVERLAY_SIZES
        or name in PARCHMENT_SIZES
        or name in ZODIAC_PAGE_SIZES
        or name in ZODIAC_OVERLAY_SIZES
        or name in SIDNEY_CLUE_SIZES
        or name in SIDNEY_ID_SIZES
        or name in OPTIONS_PANEL_SIZES
        or name in DIALOG_ART_SIZES
        or name in SIDNEY_GEOMETRY_SIZES
        or name in FINGERPRINT_TOOL_SIZES
        or name.startswith("GPSPOWER_")
        else original.resize(result.size, method)
    )
    if name in {"MINISNAKY.BMP", "SNAKY.BMP"}:
        repeated = Image.fromarray(np.tile(np.asarray(original), (3, 3, 1)))
        expected = repeated.transform(
            (size[0] * 12, size[1] * 12),
            Image.Transform.AFFINE,
            (0.25, 0, -0.125, 0, 0.25, -0.125),
            Image.Resampling.BICUBIC,
        ).crop((size[0] * 4, size[1] * 4, size[0] * 8, size[1] * 8))
    if (
        name in MONOTONE_BUTTON_SIZES
        or name in OPTIONS_LABEL_SIZES
        or name in LEGACY_DOCUMENT_SIZES
    ):
        expected = resample_monotone_art(original)
    if name in CONSERVATIVE_MENU_SIZES:
        expected = resample_menu_art(original)
    assert result.tobytes() == expected.tobytes()
    if name == "INV_HIGHLIGHT.BMP":
        assert result.getcolors() == [
            (16 * (size[0] - 1) * size[1], (255, 0, 255)),
            (16 * size[1], (180, 0, 0)),
        ]
    destination = tmp_path / "output.PNG"
    result.save(destination)
    assert is_current_ui_art(source, destination)
    result.putpixel((0, 0), (0, 0, 0))
    result.save(destination)
    assert not is_current_ui_art(source, destination)
    regenerate_ui_art(source).save(destination)
    original.putpixel((0, 0), (0, 0, 0))
    original.save(source)
    assert not is_current_ui_art(source, destination)


@pytest.mark.parametrize("corner", ["BL", "BR", "TL", "TR"])
@pytest.mark.parametrize("family", ["HELP", "RC"])
def test_border_corners_replicate_binary_color_key_without_fringe(
    tmp_path: Path, corner: str, family: str
) -> None:
    source = tmp_path / f"{family}_BOX_CORNER_{corner}.BMP"
    original = Image.new("RGB", (2, 2), (100, 100, 100))
    original.putpixel((0, 0), (255, 0, 255))
    original.save(source)
    result = regenerate_ui_art(source)
    assert result.tobytes() == original.resize((8, 8), Image.Resampling.NEAREST).tobytes()
    assert sorted(result.getcolors() or []) == [(16, (255, 0, 255)), (48, (100, 100, 100))]


def test_unverified_names_and_source_sizes_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a verified"):
        regenerate_ui_art(tmp_path / "OTHER.BMP")
    source = tmp_path / "INV_SCROLLBACK.BMP"
    Image.new("RGB", (88, 88)).save(source)
    with pytest.raises(ValueError, match="expected a"):
        regenerate_ui_art(source)


@pytest.mark.parametrize(
    "name",
    [min(SIDNEY_CLUE_SIZES), min(ZODIAC_OVERLAY_SIZES), min(MONOTONE_BUTTON_SIZES)],
)
def test_clue_letters_lines_and_borders_preserve_every_reference_sample(
    tmp_path: Path, name: str
) -> None:
    width, height = UI_ART_SIZES[name]
    y, x = np.indices((height, width))
    pixels = np.stack(((x * 17) % 256, (y * 29) % 256, ((x + y) * 13) % 256), axis=2)
    pixels = pixels.astype(np.uint8)
    pixels[0, :] = (255, 0, 0)
    pixels[-1, :] = (255, 0, 0)
    pixels[:, 0] = (255, 0, 0)
    pixels[:, -1] = (255, 0, 0)
    source = tmp_path / name
    Image.fromarray(pixels).save(source)
    result = np.asarray(regenerate_ui_art(source))
    assert np.array_equal(result[2::4, 2::4], pixels)
    assert not np.array_equal(result, pixels.repeat(4, axis=0).repeat(4, axis=1))


@pytest.mark.parametrize("name", SIDNEY_MAP_OVERLAY_SIZES)
def test_map_overlays_keep_ink_and_key_at_the_authored_coordinates(
    tmp_path: Path, name: str
) -> None:
    size = SIDNEY_MAP_OVERLAY_SIZES[name]
    original = Image.new("RGB", size, (255, 0, 255))
    for position in range(min(size)):
        original.putpixel((position, position), (8, 12, 8))
    source = tmp_path / name
    original.save(source)
    result = np.asarray(regenerate_ui_art(source))
    assert np.array_equal(result[2::4, 2::4], np.asarray(original))
    opaque = np.any(result != (255, 0, 255), axis=2)
    # Key color must not bleed into reconstructed ink around thin contours.
    assert np.all(result[opaque] == (8, 12, 8))


@pytest.mark.parametrize("name", ["GEOMPARCH1FINAL.BMP", "TENIERGEOB.BMP"])
def test_sidney_geometry_retains_reference_ink_and_transparent_background(
    tmp_path: Path, name: str
) -> None:
    source = tmp_path / name
    key = SIDNEY_GEOMETRY_KEYS[name]
    original = Image.new("RGB", SIDNEY_GEOMETRY_SIZES[name], key)
    for position in range(min(100, original.width - 10, original.height - 20)):
        original.putpixel((position + 10, position + 20), (255, 0, 0))
    original.save(source)
    output = regenerate_ui_art(source)
    assert np.array_equal(np.asarray(output)[2::4, 2::4], np.asarray(original))
    assert {color for _, color in output.getcolors(output.width * output.height) or []} == {
        key,
        (255, 0, 0),
    }
    assert plan_texture(TextureFeatures(name, alphatest=True)).kind is PipelineKind.UI_SOURCE_4X


@pytest.mark.parametrize("state", ["FIN", "LIT"])
def test_zodiac_gemini_holes_preserve_reference_coverage_without_magenta_fringe(
    tmp_path: Path, state: str
) -> None:
    name = f"LSR_PG3_GEM_{state}.BMP"
    width, height = ZODIAC_OVERLAY_SIZES[name]
    y, x = np.indices((height, width))
    hole = (x - width // 2) ** 2 + (y - height // 2) ** 2 < 40**2
    pixels = np.full((height, width, 3), (189, 173, 132), dtype=np.uint8)
    pixels[hole] = (255, 0, 255)
    source = tmp_path / name
    Image.fromarray(pixels).save(source)

    output = np.asarray(regenerate_ui_art(source))

    np.testing.assert_array_equal(output[2::4, 2::4], pixels)
    opaque = np.any(output != (255, 0, 255), axis=2)
    assert np.all(output[opaque] == (189, 173, 132))
    # The reconstructed contour provides additional coverage, not a nearest copy.
    assert not np.array_equal(~opaque, hole.repeat(4, axis=0).repeat(4, axis=1))
    assert plan_texture(TextureFeatures(name, alphatest=True)).kind is PipelineKind.UI_SOURCE_4X


def test_search_rule_preserves_one_authored_row_and_transparent_page_spacing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "HORIZONTALRULE.BMP"
    image = Image.new("RGB", (640, 15), (255, 0, 255))
    for x in range(640):
        image.putpixel((x, 7), (197, 161, 115))
    image.save(source)
    output = np.asarray(regenerate_ui_art(source))
    assert output.shape == (60, 2560, 3)
    assert np.all(output[:28] == (255, 0, 255))
    assert np.all(output[28:32] == (197, 161, 115))
    assert np.all(output[32:] == (255, 0, 255))
    assert np.array_equal(output[2::4, 2::4], np.asarray(image))


@pytest.mark.parametrize(
    "name", [*SIDNEY_SHAPE_SIZES, *(n for n in GPS_CONTROL_SIZES if n.startswith("GPSPOWER_"))]
)
def test_interpolated_controls_anchor_native_reference_pixel_centers(
    tmp_path: Path, name: str
) -> None:
    source = tmp_path / name
    width, height = UI_ART_SIZES[name]
    original = Image.new("RGB", (width, height))
    original.putdata(
        [((x * 17 + y * 9) % 256, x * 4, y * 4) for y in range(height) for x in range(width)]
    )
    original.save(source)
    result = regenerate_ui_art(source)
    assert [
        result.getpixel((4 * x + 2, 4 * y + 2)) for y in range(height) for x in range(width)
    ] == [original.getpixel((x, y)) for y in range(height) for x in range(width)]


@pytest.mark.parametrize("suffix", ["L", "M", "S"])
def test_gps_target_preserves_binary_key_and_line_coverage(tmp_path: Path, suffix: str) -> None:
    name = f"GPSTARGET_{suffix}.BMP"
    original = Image.new("RGB", GPS_CONTROL_SIZES[name], (255, 0, 255))
    for x in range(original.width):
        original.putpixel((x, 0), (0, 137, 172))
    source = tmp_path / name
    original.save(source)
    result = regenerate_ui_art(source)
    assert sorted(result.getcolors() or []) == [
        (16 * original.width, (0, 137, 172)),
        (16 * original.width * (original.height - 1), (255, 0, 255)),
    ]


@pytest.mark.parametrize("name", [n for n in GPS_MAP_SIZES if n.endswith("_ALPHA.BMP")])
def test_gps_map_and_opacity_share_reference_samples_without_ai(tmp_path: Path, name: str) -> None:
    size = GPS_MAP_SIZES[name]
    mask = Image.new("L", size)
    mask.putdata([(x * 17 + y * 9) % 256 for y in range(size[1]) for x in range(size[0])])
    source = tmp_path / name
    mask.save(source)
    result = regenerate_ui_art(source)
    assert result.mode == "L"
    assert result.resize(size, Image.Resampling.NEAREST).tobytes() == mask.tobytes()
    assert (
        plan_texture(TextureFeatures(name, kind=TextureKind.ALPHA)).kind
        is PipelineKind.UI_SOURCE_4X
    )
    color = tmp_path / name.replace("_ALPHA", "")
    mask.convert("RGB").save(color)
    assert regenerate_ui_art(color).convert("L").tobytes() == result.tobytes()
    assert (
        plan_texture(TextureFeatures(name, kind=TextureKind.DATA)).kind
        is PipelineKind.DATA_UNCHANGED
    )
