from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

from gk3hd.textures.upscale.fonts.button import (
    font_button_recipe,
    regenerable_font_button_names,
    regenerate_font_button,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_recipe_catalog_covers_every_option_button_state() -> None:
    names = regenerable_font_button_names()
    advanced = font_button_recipe("rc_so_advanced_std.bmp")
    restore_disabled = font_button_recipe("RC_SO_RESTORE_DIS.BMP")

    assert len(names) == 13
    assert advanced is not None
    assert advanced.label == "Advanced Options"
    assert restore_disabled is not None
    assert restore_disabled.label == "Restore"
    assert font_button_recipe("RC_SO_DROPDOWN.BMP") is None


def test_button_chrome_and_embedded_glyphs_are_exact_4x_blocks(tmp_path: Path) -> None:
    source = tmp_path / "RC_SO_SAVE_STD.BMP"
    pixels = np.zeros((17, 60, 3), dtype=np.uint8)
    pixels[:, :] = (131, 133, 131)
    pixels[3:6, 10:20] = (255, 255, 255)
    pixels[5:8, 10:20] = (40, 44, 40)
    Image.fromarray(pixels, mode="RGB").save(source)

    output = regenerate_font_button(source)

    expected = Image.open(source).convert("RGB").resize((240, 68), Image.Resampling.NEAREST)
    assert np.array_equal(np.asarray(output), np.asarray(expected))
