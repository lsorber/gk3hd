"""Shaded-control reconstruction preserves native samples and state geometry."""

import numpy as np
from PIL import Image

from gk3hd.textures.upscale.bevel import reconstruct_bevel


def test_reconstruction_keeps_native_samples_and_directional_shades() -> None:
    source = Image.new("RGB", (23, 17), (40, 35, 30))
    source.paste((90, 85, 80), (1, 1, 22, 16))
    source.paste((140, 130, 120), (2, 2, 21, 15))
    source.paste((180, 175, 160), (3, 3, 20, 14))
    source.putpixel((2, 2), (120, 110, 100))
    before = source.tobytes()
    restored = reconstruct_bevel(source)
    assert restored.size == (92, 68)
    np.testing.assert_array_equal(np.asarray(restored)[2::4, 2::4], np.asarray(source))
    assert restored.getpixel((46, 34)) == (180, 175, 160)
    assert source.tobytes() == before


def test_constant_shading_does_not_acquire_a_bevel() -> None:
    source = Image.new("RGB", (10, 10), (40, 50, 60))
    assert reconstruct_bevel(source).getextrema() == ((40, 40), (50, 50), (60, 60))
