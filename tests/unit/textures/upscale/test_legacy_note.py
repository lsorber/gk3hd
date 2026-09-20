"""The legacy note states share one page, not AI text or a portrait-note alias."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.analyze.manifest import analyze_directory
from gk3hd.textures.analyze.usage import TextureUsage
from gk3hd.textures.routing import PipelineKind, plan_texture
from gk3hd.textures.upscale.thumbnail import is_current_thumbnail, regenerate_thumbnail
from gk3hd.textures.upscale.thumbnail_recipes import thumbnail_recipe

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("with_usage", [False, True])
def test_note_states_share_original_page_and_preserve_press_transform(
    tmp_path: Path, *, with_usage: bool
) -> None:
    names = ("SNOTE.BMP", "SNOTE_HOV.BMP", "SNOTED.BMP")
    for name in names:
        image = Image.new("RGB", (32, 32), (48, 0, 0))
        image.paste((150, 100, 60), (5, 5, 26, 26))
        image.save(tmp_path / name)
    usage = TextureUsage(action_buttons=frozenset(names)) if with_usage else None
    analysis = analyze_directory(tmp_path, usage=usage)
    assert all(
        plan_texture(texture).kind is PipelineKind.THUMBNAIL_SOURCE_4X
        for texture in analysis.manifest.textures
    )
    recipes = [thumbnail_recipe(name) for name in names]
    assert all(recipe is not None for recipe in recipes)
    normal, hover, pressed = recipes
    assert normal is not None
    assert hover is not None
    assert pressed is not None
    assert normal.source_name == hover.source_name == pressed.source_name == "SNOTE6_ALPHA.BMP"
    assert normal.source_size == (601, 399)
    assert normal.source_scale == hover.source_scale == pressed.source_scale
    assert normal.rotation_degrees == hover.rotation_degrees == pressed.rotation_degrees
    assert normal.offset == hover.offset
    assert pressed.offset == (normal.offset[0] + 1, normal.offset[1] + 1)
    assert pressed.brightness < normal.brightness < hover.brightness
    source = tmp_path / normal.source_name
    with pytest.raises(FileNotFoundError, match="requires original SNOTE6_ALPHA"):
        regenerate_thumbnail(tmp_path / names[0])
    larger = Image.new("RGB", normal.source_size)
    larger.paste((200, 150, 90), (150, 100, 450, 300))
    larger.save(source)
    output = tmp_path / "result.png"
    dense = regenerate_thumbnail(tmp_path / names[0])
    dense.save(output)
    assert dense.size == (128, 128)
    assert is_current_thumbnail(tmp_path / names[0], output)
    larger.paste((80, 50, 20), (150, 100, 450, 300))
    larger.save(source)
    assert not is_current_thumbnail(tmp_path / names[0], output)
    changed = regenerate_thumbnail(tmp_path / names[0])
    assert not np.array_equal(np.asarray(changed), np.asarray(dense))
    larger.resize((600, 399)).save(source)
    with pytest.raises(ValueError, match="unsupported size"):
        regenerate_thumbnail(tmp_path / names[0])
