"""Preserve handwritten document samples rather than inventing replacement text."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

import gk3hd.textures.analyze.manifest as texture_analyze
from gk3hd.textures.routing import PipelineKind
from gk3hd.textures.upscale.ui_art import is_current_ui_art, regenerate_ui_art

if TYPE_CHECKING:
    from pathlib import Path


def test_legacy_document_preserves_samples_and_invalidates_changed_sources(tmp_path: Path) -> None:
    source = tmp_path / "BLUEAPPLE.BMP"
    pixels = Image.new("RGB", (640, 480))
    pixels.paste((192, 192, 192), (180, 30, 480, 450))
    pixels.paste((24, 24, 24), (220, 140, 440, 141))
    pixels.save(source)
    assert texture_analyze.analyze(tmp_path).routes == {PipelineKind.UI_SOURCE_4X: 1}
    dense = regenerate_ui_art(source)
    assert dense.size == (2560, 1920)
    np.testing.assert_array_equal(np.asarray(dense)[2::4, 2::4], np.asarray(pixels))
    assert dense.tobytes() != pixels.resize(dense.size, Image.Resampling.NEAREST).tobytes()
    assert np.asarray(dense).min() >= np.asarray(pixels).min()
    assert np.asarray(dense).max() <= np.asarray(pixels).max()
    output = tmp_path / "result.png"
    dense.save(output)
    assert is_current_ui_art(source, output)
    pixels.putpixel((250, 140), (100, 100, 100))
    pixels.save(source)
    assert not is_current_ui_art(source, output)
    pixels.resize((639, 480)).save(source)
    with pytest.raises(ValueError, match="expected a"):
        regenerate_ui_art(source)
