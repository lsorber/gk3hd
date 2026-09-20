"""Only the reviewed shaded legacy buttons use source-preserving reconstruction."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.analyze.manifest import analyze_directory
from gk3hd.textures.analyze.usage import TextureUsage
from gk3hd.textures.routing import PipelineKind
from gk3hd.textures.upscale.ui_art import (
    LEGACY_TOOLBAR_ART_SIZES,
    is_current_ui_art,
    regenerate_ui_art,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(("name", "size"), LEGACY_TOOLBAR_ART_SIZES.items())
@pytest.mark.parametrize("with_usage", [False, True])
def test_shaded_legacy_icons_preserve_samples_and_key(
    tmp_path: Path, name: str, size: tuple[int, int], *, with_usage: bool
) -> None:
    source, output = tmp_path / name, tmp_path / "result.png"
    original = Image.new("RGB", size, (255, 0, 255))
    for y in range(2, size[1] - 2):
        for x in range(2, size[0] - 2):
            original.putpixel((x, y), (20 + x * 4, 10 + y * 3, 20))
    original.save(source)
    usage = TextureUsage(toolbar_buttons=frozenset({name})) if with_usage else None
    assert analyze_directory(tmp_path, usage=usage).routes == {PipelineKind.UI_SOURCE_4X: 1}
    enlarged = regenerate_ui_art(source)
    assert enlarged.size == (size[0] * 4, size[1] * 4)
    pixels = np.asarray(enlarged)
    np.testing.assert_array_equal(pixels[2::4, 2::4], np.asarray(original))
    assert not np.array_equal(pixels, np.repeat(np.repeat(np.asarray(original), 4, 0), 4, 1))
    enlarged.save(output)
    assert is_current_ui_art(source, output)
    original.putpixel((5, 5), (0, 0, 0))
    original.save(source)
    assert not is_current_ui_art(source, output)
    original.resize((size[0] + 1, size[1])).save(source)
    # Named policy corrections do not silently disappear when dimensions change;
    # the reconstruction itself must reject an unsupported source layout.
    assert analyze_directory(tmp_path, usage=usage).routes == {PipelineKind.UI_SOURCE_4X: 1}
    with pytest.raises(ValueError, match=r"expected a .* source"):
        regenerate_ui_art(source)


def test_pixel_defined_toolbar_glyphs_still_follow_metadata_retention(tmp_path: Path) -> None:
    names = (
        "TBBTCINEMATD",
        "TBBTCINEMATU",
        "TBBTHELP___U",
        "TBBTHINTGRAU",
        "TBBTOPTION_U",
        "TBBTRADIO__U",
        "TBBTTAPERECU",
    )
    for name in names:
        image = Image.new("RGB", (22, 22), (255, 0, 255))
        image.paste((255, 255, 0), (3, 3, 10, 10))
        image.save(tmp_path / f"{name}.BMP")
    usage = TextureUsage(toolbar_buttons=frozenset(f"{name}.BMP" for name in names))
    assert analyze_directory(tmp_path, usage=usage).routes == {
        PipelineKind.EXACT_RASTER_UNCHANGED: len(names)
    }
