"""Source RGB565 words survive PNG transport and native bitmap installation."""

from __future__ import annotations

import hashlib
import struct
from typing import TYPE_CHECKING

import pytest
from PIL import Image

from gk3hd.textures.install.conversion import _save_bmp
from gk3hd.textures.native_bmp import encode_rgb565
from gk3hd.textures.upscale.fingerprint import INVENTORY_FINGERPRINT_SIZES
from gk3hd.textures.upscale.fonts.atlas import (
    FONT_ATLAS_COLOR_SIZES,
    iter_regenerable_primary_names,
)
from gk3hd.textures.upscale.fonts.button import FONT_BUTTON_SIZES
from gk3hd.textures.upscale.ui_art import STANDARD_BMP_UI_NAMES, UI_ART_SIZES

if TYPE_CHECKING:
    from pathlib import Path


def test_every_rgb565_color_round_trips_exactly() -> None:
    words = struct.pack("<65536H", *range(65536))
    decoded = Image.frombytes("RGB", (256, 256), words, "raw", "BGR;16", 512, 1)
    assert encode_rgb565(decoded) == struct.pack("<4sHH", b"61nM", 256, 256) + words


def test_native_bitmap_rows_are_top_down_and_odd_widths_have_zero_padding() -> None:
    source = Image.new("RGB", (1, 2), (255, 0, 255))
    source.putpixel((0, 1), (0, 255, 0))
    assert encode_rgb565(source) == struct.pack("<4sHH4H", b"61nM", 2, 1, 0xF81F, 0, 0x07E0, 0)


@pytest.mark.parametrize("size", [(0, 2), (2, 0), (65536, 1)])
def test_native_bitmap_rejects_unrepresentable_dimensions(size: tuple[int, int]) -> None:
    with pytest.raises(ValueError, match="out of range"):
        encode_rgb565(Image.new("RGB", size))


@pytest.mark.parametrize(
    "name", ["INV_HIGHLIGHT.BMP", "RC_SO_SAVE_STD.BMP", "F_TOOLTIP.BMP", "S_BOX_SIDE.BMP"]
)
def test_geometric_ui_install_preserves_original_bitmap_encoding(tmp_path: Path, name: str) -> None:
    width, height = (UI_ART_SIZES | FONT_BUTTON_SIZES | FONT_ATLAS_COLOR_SIZES)[name]
    image = Image.new("RGB", (width * 4, height * 4), (66, 66, 66))
    path = tmp_path / name.lower()
    digest = _save_bmp(image, path, mode="RGB")
    data = path.read_bytes()
    assert digest == hashlib.sha256(data).hexdigest()
    if name in STANDARD_BMP_UI_NAMES:
        assert data.startswith(b"BM")
        with Image.open(path) as decoded:
            assert decoded.tobytes() == image.tobytes()
    else:
        assert data == encode_rgb565(image)


def test_pack_install_keeps_verified_geometric_colors_in_original_game_format(
    tmp_path: Path,
) -> None:
    image = Image.new("RGB", (20, 4), (180, 125, 0))
    path = tmp_path / "MSG_BOX_VERT.BMP"
    digest = _save_bmp(image, path, mode="RGB")
    expected = struct.pack("<4sHH", b"61nM", 4, 20) + struct.pack("<H", (22 << 11) | (31 << 5)) * 80
    assert path.read_bytes() == expected
    assert digest == hashlib.sha256(expected).hexdigest()
    for name, size in (("UNRELATED.BMP", (20, 4)), ("MSG_BOX_VERT.BMP", (5, 1))):
        path = tmp_path / name
        _save_bmp(Image.new("RGB", size, (180, 125, 0)), path, mode="RGB")
        assert path.read_bytes().startswith(b"BM")


@pytest.mark.parametrize("name", FONT_BUTTON_SIZES | FONT_ATLAS_COLOR_SIZES)
def test_font_encoding_requires_exact_dense_size(tmp_path: Path, name: str) -> None:
    width, height = (FONT_BUTTON_SIZES | FONT_ATLAS_COLOR_SIZES)[name]
    for size in ((width, height), (width * 4 + 1, height * 4)):
        destination = tmp_path / name
        _save_bmp(Image.new("RGB", size), destination, mode="RGB")
        assert destination.read_bytes().startswith(b"BM")


def test_native_font_catalog_covers_only_recognized_color_atlases() -> None:
    assert set(FONT_ATLAS_COLOR_SIZES) == set(iter_regenerable_primary_names())


@pytest.mark.parametrize("name", ["ABBEPRNT6_ALPHA.BMP", "LHOPRNT6_ALPHA.BMP"])
def test_inventory_fingerprint_pack_preserves_native_color_encoding(
    tmp_path: Path, name: str
) -> None:
    width, height = INVENTORY_FINGERPRINT_SIZES[name]
    image = Image.new("RGB", (width * 4, height * 4), (238, 238, 238))
    destination = tmp_path / name
    _save_bmp(image, destination, mode="RGB")
    assert destination.read_bytes() == encode_rgb565(image)
    # An unrelated opacity plane remains a regular grayscale BMP.
    destination = tmp_path / "MOSELYPRINT_9_OP.BMP"
    _save_bmp(image.convert("L"), destination, mode="L")
    assert destination.read_bytes().startswith(b"BM")
