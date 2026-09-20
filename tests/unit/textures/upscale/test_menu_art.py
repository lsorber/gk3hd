"""Preserve original opaque menu samples through the game's RGB565 transport."""

from __future__ import annotations

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
from gk3hd.textures.upscale.menu_art import (
    CONSERVATIVE_MENU_SIZES,
    MENU_CONTROL_ART_SIZES,
    TOOLBAR_ART_SIZES,
    resample_menu_art,
)
from gk3hd.textures.upscale.ui_art import is_current_ui_art, regenerate_ui_art

if TYPE_CHECKING:
    from pathlib import Path


def _decode(image: Image.Image) -> np.ndarray:
    words = np.frombuffer(encode_rgb565(image), dtype="<u2", offset=8).reshape(
        image.height, image.width
    )
    return np.stack((words >> 11, (words >> 5) & 63, words & 31), axis=2).astype(np.int64)


@pytest.mark.parametrize("seed", range(12))
def test_preserves_native_quantized_area_samples_and_range(seed: int) -> None:
    source = np.random.default_rng(seed).integers(0, 256, (32, 32, 3), dtype=np.uint8)
    original = Image.fromarray(source)
    dense = resample_menu_art(original)
    assert dense.size == (128, 128)
    native = _decode(original)
    pixels = _decode(dense)
    reduced = (pixels.reshape(32, 4, 32, 4, 3).sum(axis=(1, 3)) + 8) // 16
    np.testing.assert_array_equal(reduced, native)
    assert np.all(pixels.min(axis=(0, 1)) >= native.min(axis=(0, 1)))
    assert np.all(pixels.max(axis=(0, 1)) <= native.max(axis=(0, 1)))


def test_interpolates_shading_without_blurring_constant_bevels() -> None:
    ramp = np.repeat(np.arange(32, dtype=np.uint8)[None, :, None] * 8, 32, axis=0)
    source = np.repeat(ramp, 3, axis=2)
    source[:3] = 0
    dense = _decode(resample_menu_art(Image.fromarray(source)))
    native = _decode(Image.fromarray(source))
    assert np.any(dense != native.repeat(4, axis=0).repeat(4, axis=1))
    assert not dense[:12].any()


@pytest.mark.parametrize("color", [(0, 0, 0), (255, 255, 255), (97, 131, 173)])
def test_constant_art_remains_exactly_constant(color: tuple[int, int, int]) -> None:
    original = Image.new("RGB", (32, 32), color)
    result = _decode(resample_menu_art(original))
    assert np.all(result == _decode(original)[0, 0])


@pytest.mark.parametrize("mode", ["P", "L", "RGBA"])
def test_does_not_silently_discard_other_image_semantics(mode: str) -> None:
    with pytest.raises(ValueError, match="opaque RGB"):
        resample_menu_art(Image.new(mode, (32, 32)))


def test_catalog_contains_complete_reviewed_families_only() -> None:
    assert len(CONSERVATIVE_MENU_SIZES) == 249
    actions = (
        CONSERVATIVE_MENU_SIZES.keys()
        - TOOLBAR_ART_SIZES.keys()
        - MENU_CONTROL_ART_SIZES.keys()
        - {
            "I_MACHINE.BMP",
            "I_MOSE_ROOM_KEY.BMP",
            "I_HOSE_STD.BMP",
            "I_HOSE_DWN.BMP",
            "I_UNCOIL.BMP",
            "I_UNCOILD.BMP",
        }
    )
    families = {name.rsplit("_", 1)[0] for name in actions}
    assert len(families) == 53
    # Both room-key families preserve their authored ring/shaft artwork;
    # their larger inventory render is not a faithful replacement source.
    assert {"I_GRARM", "I_ROOMKEY"} <= families
    assert actions == {
        f"{family}_{state}.BMP" for family in families for state in ("STD", "HOV", "DWN")
    }
    assert set(CONSERVATIVE_MENU_SIZES.values()) == {(32, 32)}
    assert "I_VAMPIRES_STD.BMP" not in CONSERVATIVE_MENU_SIZES
    assert {"I_HANDSHAKE", "I_PET"} <= families
    assert "I_MACHINE.BMP" in CONSERVATIVE_MENU_SIZES
    assert "I_MOSE_ROOM_KEY.BMP" in CONSERVATIVE_MENU_SIZES
    assert "I_MACHINE_STD.BMP" not in CONSERVATIVE_MENU_SIZES
    assert "I_HOSE_HOV.BMP" not in CONSERVATIVE_MENU_SIZES
    assert "I_UNCOIL_STD.BMP" not in CONSERVATIVE_MENU_SIZES


def test_controls_keep_authored_states_without_inventing_alternate_names() -> None:
    assert len(MENU_CONTROL_ART_SIZES) == 33
    assert set(MENU_CONTROL_ART_SIZES) == {
        f"{family}_{state}.BMP"
        for family in ("I_CANCEL", "I_CASE", "I_OPERATE", "I_RLC", "I_SION", "I_WAKEUPCALL")
        for state in ("STD", "HOV", "DWN")
    } | {
        f"{family}_{state}.BMP"
        for family in ("I_INSPECT", "I_ZOOMOUT")
        for state in ("STD", "HOV", "DWN", "DIS")
    } | {
        "I_EXIT_STD.BMP",
        "I_EXIT_HOV.BMP",
        "I_EXIT_DOWN.BMP",
        "I_BLANKBTN_U.BMP",
        "I_BLANKBTN_D.BMP",
        "I_TURN_PAGE_BACK.BMP",
        "I_TURN_PAGE_FWD.BMP",
    }


def test_toolbar_keeps_original_disabled_states_and_legacy_names() -> None:
    assert len(TOOLBAR_ART_SIZES) == 51
    standard = {name for name in TOOLBAR_ART_SIZES if name.endswith("_STD.BMP")}
    assert len(standard) == 12
    assert set(TOOLBAR_ART_SIZES) == {
        name.removesuffix("STD.BMP") + state + ".BMP"
        for name in standard
        for state in ("STD", "HOV", "DWN", "DIS")
    } | {"RC_INVENTORY_EXIT.BMP", "RC_INVENTORY_EXIT_HOV.BMP", "RC_INVENTORY_EXITD.BMP"}


@pytest.mark.parametrize("name", [min(CONSERVATIVE_MENU_SIZES), max(CONSERVATIVE_MENU_SIZES)])
def test_complete_source_analysis_reconstruction_cache_and_transport(
    tmp_path: Path, name: str
) -> None:
    source = tmp_path / name
    original = Image.new("RGB", (32, 32), (97, 131, 173))
    original.paste((0, 0, 0), (0, 0, 32, 3))
    original.save(source)
    info = inspect_bmp(source)
    features = classify_texture(name, info, {name: info}, action_button=True)
    features = load_policy().apply(features, info)
    assert not features.exact_raster
    assert plan_texture(features).kind is PipelineKind.UI_SOURCE_4X
    result = regenerate_ui_art(source)
    assert result.tobytes() == resample_menu_art(original).tobytes()
    output = tmp_path / "dense.png"
    result.save(output)
    assert is_current_ui_art(source, output)
    destination = tmp_path / "installed" / name
    destination.parent.mkdir()
    with Image.open(output) as portable:
        _save_bmp(portable, destination, mode="RGB")
    assert destination.read_bytes() == encode_rgb565(result)
    original.putpixel((7, 7), (0, 0, 0))
    original.save(source)
    assert not is_current_ui_art(source, output)
    original.putpixel((4, 4), (255, 0, 255))
    original.save(source)
    keyed = inspect_bmp(source)
    assert (
        load_policy()
        .apply(classify_texture(name, keyed, {name: keyed}, action_button=True), keyed)
        .exact_raster
    )


def test_menu_names_do_not_override_other_semantics() -> None:
    for properties in (
        {"kind": TextureKind.DATA},
        {"kind": TextureKind.ALPHA},
        {"exact_raster": True},
        {"native_size": True},
        {"font_atlas": True},
        {"alphatest": True},
        {"tiled": True},
    ):
        feature = TextureFeatures(name="I_GABE_STD.BMP").with_overrides(properties)
        assert plan_texture(feature).kind is not PipelineKind.UI_SOURCE_4X
