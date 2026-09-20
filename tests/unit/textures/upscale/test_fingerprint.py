"""Fingerprint structure, route precedence, and deterministic output contracts."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image

from gk3hd.patch.definitions.runtime2d.sidney_images import FINGERPRINT_IDS
from gk3hd.textures.model import TextureFeatures, TextureKind
from gk3hd.textures.routing import PipelineKind, plan_texture
from gk3hd.textures.upscale.fingerprint import (
    COMPARISON_FINGERPRINT_NAMES,
    EVIDENCE_FINGERPRINT_NAMES,
    FINGERPRINT_NAMES,
    FINGERPRINT_SIZES,
    INVENTORY_FINGERPRINT_SIZES,
    WORKSTATION_MASK_SIZES,
    WORKSTATION_PRINT_SIZES,
    is_current_fingerprint,
    is_fingerprint,
    regenerate_fingerprint,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("name", [*WORKSTATION_PRINT_SIZES, *WORKSTATION_MASK_SIZES])
def test_workstation_pair_retains_every_reference_sample(tmp_path: Path, name: str) -> None:
    import numpy as np  # noqa: PLC0415

    size = (WORKSTATION_PRINT_SIZES | WORKSTATION_MASK_SIZES)[name]
    mask = name in WORKSTATION_MASK_SIZES
    values = np.arange(size[0] * size[1] * (1 if mask else 3), dtype=np.uint32)
    pixels = (
        (values % 256)
        .astype(np.uint8)
        .reshape((size[1], size[0]) if mask else (size[1], size[0], 3))
    )
    source = tmp_path / name
    Image.fromarray(pixels).save(source)
    features = TextureFeatures(name, kind=TextureKind.ALPHA if mask else TextureKind.COLOR)
    assert plan_texture(features).kind is PipelineKind.FINGERPRINT_SOURCE_4X
    output = regenerate_fingerprint(source)
    assert output.mode == ("L" if mask else "RGB")
    assert output.size == (size[0] * 4, size[1] * 4)
    np.testing.assert_array_equal(np.asarray(output)[2::4, 2::4], pixels)
    assert (
        plan_texture(TextureFeatures(name, kind=TextureKind.DATA)).kind
        is PipelineKind.DATA_UNCHANGED
    )


def test_route_matches_exact_engine_supported_family_and_respects_semantics() -> None:
    assert {
        f"S_{name.decode().upper()}_FPRINT.BMP" for name in FINGERPRINT_IDS
    } == FINGERPRINT_NAMES
    for name in FINGERPRINT_NAMES:
        assert is_fingerprint(name.lower())
        assert plan_texture(TextureFeatures(name)).kind is PipelineKind.FINGERPRINT_SOURCE_4X
    assert not is_fingerprint("S_ABE_FPRINT_EXTRA.BMP")
    assert not is_fingerprint("OTHER_FPRINT.BMP")
    for changes, expected in (
        ({"kind": TextureKind.DATA}, PipelineKind.DATA_UNCHANGED),
        ({"kind": TextureKind.ALPHA}, PipelineKind.ALPHA_SMOOTH),
        ({"native_size": True}, PipelineKind.NATIVE_SIZE_UNCHANGED),
        ({"exact_raster": True}, PipelineKind.EXACT_RASTER_UNCHANGED),
        ({"alphatest": True}, PipelineKind.ALPHA_TEST_AI),
        ({"tiled": True}, PipelineKind.COLOR_AI),
    ):
        assert (
            plan_texture(TextureFeatures("S_ABE_FPRINT.BMP").with_overrides(changes)).kind
            is expected
        )


def test_resampling_uses_source_only_and_rejects_stale_or_ai_pixels(tmp_path: Path) -> None:
    source = tmp_path / "S_ABE_FPRINT.BMP"
    original = Image.new("RGB", (41, 51), (100, 100, 100))
    for x in range(0, 41, 4):
        for y in range(51):
            original.putpixel((x, y), (30, 30, 30))
    original.save(source)
    result = regenerate_fingerprint(source)
    assert result.size == (164, 204)
    assert result.mode == "RGB"
    assert result.tobytes() == original.resize((164, 204), Image.Resampling.BICUBIC).tobytes()
    destination = tmp_path / "result.PNG"
    result.save(destination)
    assert is_current_fingerprint(source, destination)
    result.putpixel((32, 32), (255, 0, 0))
    result.save(destination)
    assert not is_current_fingerprint(source, destination)
    regenerate_fingerprint(source).save(destination)
    original.putpixel((10, 10), (0, 0, 0))
    original.save(source)
    assert not is_current_fingerprint(source, destination)


def test_workstation_black_key_cannot_bleed_into_print_color(tmp_path: Path) -> None:
    source = tmp_path / "FP_LHOMIR_P1.BMP"
    original = Image.new("RGB", (25, 44), (0, 0, 0))
    ink = (100, 120, 140)
    original.paste(ink, (5, 7, 20, 38))
    original.save(source)
    result = regenerate_fingerprint(source)
    colors = result.getcolors(result.width * result.height)
    assert colors is not None
    assert {color for _, color in colors} == {(0, 0, 0), ink}


def test_unexpected_resource_or_geometry_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a recognized"):
        regenerate_fingerprint(tmp_path / "OTHER.BMP")
    source = tmp_path / "S_ABE_FPRINT.BMP"
    Image.new("RGB", (42, 51)).save(source)
    with pytest.raises(ValueError, match="expected a 41x51"):
        regenerate_fingerprint(source)


@pytest.mark.parametrize("name", sorted(INVENTORY_FINGERPRINT_SIZES))
def test_inventory_cards_keep_ridges_labels_and_native_geometry(tmp_path: Path, name: str) -> None:
    size = INVENTORY_FINGERPRINT_SIZES[name]
    source = tmp_path / name
    original = Image.new("RGB", size, (241, 239, 237))
    original.paste((17, 24, 31), (3, 5, 9, 13))
    original.paste((88, 82, 107), (11, 7, 15, 18))
    original.save(source)
    assert plan_texture(TextureFeatures(name)).kind is PipelineKind.FINGERPRINT_SOURCE_4X
    enlarged = regenerate_fingerprint(source)
    expected = original.resize((size[0] * 4, size[1] * 4), Image.Resampling.BICUBIC)
    assert enlarged.tobytes() == expected.tobytes()
    # A scalar companion is opacity, not RGB fingerprint artwork, despite
    # sharing the noun's prefix. Small action-menu variants stay pixel art.
    if name.endswith("9.BMP"):
        assert not is_fingerprint(name.replace("9.BMP", "9_OP.BMP"))
    assert not is_fingerprint("I_ABBEPRINT_STD.BMP")


@pytest.mark.parametrize("name", sorted(EVIDENCE_FINGERPRINT_NAMES))
def test_evidence_prints_preserve_source_color_and_comparison_windows(
    tmp_path: Path, name: str
) -> None:
    comparison = name in COMPARISON_FINGERPRINT_NAMES
    original = Image.new("RGB", (41, 51), (255, 0, 255) if comparison else (200, 100, 50))
    original.paste((180, 40, 0), (3, 4, 17, 25))
    original.paste((60, 10, 0), (20, 30, 40, 50))
    source = tmp_path / name
    original.save(source)
    result = regenerate_fingerprint(source)
    assert result.mode == "RGB"
    assert result.size == (164, 204)
    assert plan_texture(TextureFeatures(name, alphatest=comparison)).kind is (
        PipelineKind.FINGERPRINT_SOURCE_4X
    )
    assert plan_texture(TextureFeatures(name, native_size=True)).kind is (
        PipelineKind.NATIVE_SIZE_UNCHANGED
    )
    if comparison:
        for y in range(204):
            for x in range(164):
                pixel = result.getpixel((x, y))
                if original.getpixel((x // 4, y // 4)) == (255, 0, 255):
                    assert pixel == (255, 0, 255)
                else:
                    # No blue fringe from the magenta key, including directly
                    # beside a rectangular fragment's boundary.
                    assert isinstance(pixel, tuple)
                    assert pixel[2] == 0
    else:
        assert result.tobytes() == original.resize((164, 204), Image.Resampling.BICUBIC).tobytes()
    destination = tmp_path / "output.PNG"
    result.save(destination)
    assert is_current_fingerprint(source, destination)
    result.putpixel((20, 20), (0, 0, 255))
    result.save(destination)
    assert not is_current_fingerprint(source, destination)


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("MOSELYPRINT_3.BMP", (32, 30)),
        ("MOSELYPRINT_6_ALPHA.BMP", (307, 400)),
        ("MOSELYPRINT_9.BMP", (94, 94)),
    ],
)
def test_inventory_card_preserves_ridges_and_handwritten_label(
    tmp_path: Path, name: str, size: tuple[int, int]
) -> None:
    assert FINGERPRINT_SIZES[name] == size
    assert is_fingerprint(name.lower())
    assert plan_texture(TextureFeatures(name)).kind is PipelineKind.FINGERPRINT_SOURCE_4X
    source = tmp_path / name.lower()
    original = Image.new("RGB", size, (238, 238, 238))
    for x in range(0, size[0], 3):
        original.putpixel((x, size[1] - 5), (0, 0, 0))
    original.save(source)
    expected = original.resize((size[0] * 4, size[1] * 4), Image.Resampling.BICUBIC)
    result = regenerate_fingerprint(source)
    assert result.tobytes() == expected.tobytes()
    destination = tmp_path / "card.PNG"
    result.save(destination)
    assert is_current_fingerprint(source, destination)
