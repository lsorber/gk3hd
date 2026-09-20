from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.upscale.driving_map import (
    compose_driving_map_overlay,
    driving_map_overlay_origin,
)


def test_catalog_recognizes_both_location_states_only() -> None:
    assert driving_map_overlay_origin("dm_wod.bmp") == (44, 218)
    assert driving_map_overlay_origin("DM_WOD_UL.BMP") == (44, 218)
    assert driving_map_overlay_origin("DM_BASE.BMP") is None
    assert driving_map_overlay_origin("ROOM_DM_WOD.BMP") is None


def test_unchanged_patch_is_exact_shared_hd_base_crop() -> None:
    base = Image.new("RGB", (640, 480), (10, 20, 30))
    base_hd = Image.new("RGB", (2560, 1920), (40, 50, 60))
    overlay = base.crop((44, 218, 142, 293))

    result = compose_driving_map_overlay(
        overlay,
        base,
        base_hd,
        name="DM_WOD_UL.BMP",
    )

    assert result.size == (392, 300)
    assert result.getextrema() == ((40, 40), (50, 50), (60, 60))


def test_location_delta_is_scaled_without_changing_opaque_border() -> None:
    base = Image.new("RGB", (640, 480), (20, 30, 40))
    base_hd = Image.new("RGB", (2560, 1920), (80, 90, 100))
    overlay = base.crop((44, 218, 142, 293))
    overlay.putpixel((49, 37), (120, 130, 140))

    result = compose_driving_map_overlay(
        overlay,
        base,
        base_hd,
        name="DM_WOD.BMP",
    )
    pixels = np.asarray(result)

    assert np.all(pixels[0] == (80, 90, 100))
    assert np.all(pixels[-1] == (80, 90, 100))
    assert np.all(pixels[:, 0] == (80, 90, 100))
    assert np.all(pixels[:, -1] == (80, 90, 100))
    assert tuple(pixels[37 * 4 + 2, 49 * 4 + 2]) > (80, 90, 100)


@pytest.mark.parametrize(
    ("name", "terrain"),
    [
        ("TR1", (57, 131)),
        ("RL1", (487, 174)),
        ("TRE", (506, 89)),
    ],
)
@pytest.mark.parametrize("suffix", ["", "_UL"])
def test_corrected_location_joins_background_without_warping_terrain(
    name: str, terrain: tuple[int, int], suffix: str
) -> None:
    # A varying background distinguishes the overlay's original terrain crop
    # from the place its building is drawn. A uniform fixture hides this bug.
    y, x = np.indices((480, 640))
    pixels = np.stack((x % 100 + 20, y % 100 + 20, (x + y) % 100 + 20), axis=2)
    tx, ty = terrain
    # The base already includes the unlit building. A zero delta must leave
    # the entire background untouched, not just blend the outer border.
    pixels[ty + 10 : ty + 14, tx + 10 : tx + 14] = 200
    base = Image.fromarray(pixels.astype(np.uint8))
    hd = base.resize((2560, 1920), Image.Resampling.NEAREST)
    overlay = base.crop((tx, ty, tx + 24, ty + 24))
    # Small bright building with unchanged terrain around its border.
    art = np.asarray(overlay).copy()
    if not suffix:
        art[10:14, 10:14] += 20
    result = compose_driving_map_overlay(
        Image.fromarray(art), base, hd, name=f"DM_{name}{suffix}.BMP"
    )
    px, py = driving_map_overlay_origin(f"DM_{name}.BMP") or (0, 0)
    background = np.asarray(hd.crop((px * 4, py * 4, (px + 24) * 4, (py + 24) * 4)))
    delta = np.asarray(result).astype(int) - background
    assert not delta[0].any()
    assert not delta[-1].any()
    assert not delta[:, 0].any()
    assert not delta[:, -1].any()
    if suffix:
        assert not delta.any()
    # The foreground keeps its local authored center rather than receiving
    # the terrain correction as a second translation.
    ys, xs = np.nonzero(np.asarray(result).min(axis=2) > 140)
    assert xs.mean() == pytest.approx(47.5)
    assert ys.mean() == pytest.approx(47.5)
