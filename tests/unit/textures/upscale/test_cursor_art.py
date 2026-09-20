"""Shaded animation frames are reconstructed independently, never as one strip."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.analyze.manifest import analyze_directory
from gk3hd.textures.routing import PipelineKind, plan_texture
from gk3hd.textures.upscale.cursor_art import CURSOR_ART_FRAMES, regenerate_cursor_art
from gk3hd.textures.upscale.ui_art import is_current_ui_art, regenerate_ui_art

if TYPE_CHECKING:
    from pathlib import Path


def _strip() -> Image.Image:
    original = Image.new("RGB", (1200, 40), (255, 0, 255))
    for frame in range(30):
        # Different neighboring shades touch the frame edges deliberately.
        original.paste((frame * 7, 100, 40), (frame * 40, 8, (frame + 1) * 40, 32))
        original.paste((frame * 5, 40, 20), (frame * 40 + 8, 12, frame * 40 + 32, 28))
    return original


def test_every_frame_preserves_original_samples_without_neighbor_bleed(tmp_path: Path) -> None:
    original = _strip()
    source, output = tmp_path / "C_PLAYACTION.BMP", tmp_path / "C_PLAYACTION.PNG"
    original.save(source)
    enlarged = regenerate_ui_art(source)
    assert CURSOR_ART_FRAMES[source.name] == (40, 40, 30)
    assert enlarged.size == (4800, 160)
    np.testing.assert_array_equal(np.asarray(enlarged)[2::4, 2::4], np.asarray(original))
    for frame in range(30):
        region = np.asarray(enlarged.crop((frame * 160, 0, (frame + 1) * 160, 160)))
        np.testing.assert_array_equal(region[60:100, 0, 0], frame * 7)
        np.testing.assert_array_equal(region[60:100, -1, 0], frame * 7)
    enlarged.save(output)
    assert is_current_ui_art(source, output)
    original.paste((240, 240, 240), (40, 0, 80, 40))
    original.save(source)
    assert not is_current_ui_art(source, output)
    changed = regenerate_ui_art(source)
    assert changed.crop((0, 0, 160, 160)).tobytes() == enlarged.crop((0, 0, 160, 160)).tobytes()
    assert (
        changed.crop((320, 0, 4800, 160)).tobytes() == enlarged.crop((320, 0, 4800, 160)).tobytes()
    )


@pytest.mark.parametrize(
    ("name", "size"),
    [("C_WAIT.BMP", (599, 40)), ("C_PLAYACTION.BMP", (1199, 40)), ("C_LOOK.BMP", (31, 32))],
)
def test_unverified_cursor_contracts_are_rejected(name: str, size: tuple[int, int]) -> None:
    with pytest.raises(ValueError, match="no verified cursor frame layout"):
        regenerate_cursor_art(Image.new("RGB", size), name)


@pytest.mark.parametrize(
    "name", [name for name, layout in CURSOR_ART_FRAMES.items() if layout[2] == 1]
)
def test_static_shaded_art_is_analyzed_and_keeps_every_native_sample(
    tmp_path: Path, name: str
) -> None:
    width, height, _ = CURSOR_ART_FRAMES[name]
    original = Image.new("RGB", (width, height), (255, 0, 255))
    original.paste((170, 95, 30), (3, 4, width - 2, height - 3))
    original.paste((80, 40, 20), (6, 6, width - 5, height - 5))
    source = tmp_path / name
    original.save(source)
    report = analyze_directory(tmp_path)
    assert report.routes == {PipelineKind.UI_SOURCE_4X: 1}
    enlarged = regenerate_ui_art(source)
    assert enlarged.size == (width * 4, height * 4)
    np.testing.assert_array_equal(np.asarray(enlarged)[2::4, 2::4], np.asarray(original))
    # Policy identifies the artwork; reconstruction validates its layout.
    original.resize((width + 1, height)).save(source)
    changed = analyze_directory(tmp_path).manifest.textures[0]
    assert plan_texture(changed).kind == PipelineKind.UI_SOURCE_4X
    with pytest.raises(ValueError, match=r"expected a .* source"):
        regenerate_ui_art(source)


def _wait_pair(directory: Path) -> tuple[Image.Image, Image.Image]:
    color = _strip().crop((0, 0, 600, 40))
    opacity = Image.new("L", color.size)
    for frame in range(15):
        opacity.paste(frame * 17, (frame * 40, 0, (frame + 1) * 40, 40))
        opacity.paste(255 - frame * 17, (frame * 40 + 8, 8, frame * 40 + 32, 32))
    color.save(directory / "C_WAIT.BMP")
    opacity.save(directory / "C_WAIT_ALPHA.BMP")
    return color, opacity


def test_wait_layers_rebuild_together_with_exact_samples_and_isolated_frames(
    tmp_path: Path,
) -> None:
    originals = _wait_pair(tmp_path)
    report = analyze_directory(tmp_path)
    assert report.routes == {PipelineKind.UI_SOURCE_4X: 2}
    for name, original in zip(("C_WAIT.BMP", "C_WAIT_ALPHA.BMP"), originals, strict=True):
        enlarged = regenerate_ui_art(tmp_path / name)
        assert enlarged.size == (2400, 160)
        assert enlarged.mode == original.mode
        np.testing.assert_array_equal(np.asarray(enlarged)[2::4, 2::4], np.asarray(original))
        for frame in range(15):
            source = original.crop((frame * 40, 0, (frame + 1) * 40, 40))
            actual = enlarged.crop((frame * 160, 0, (frame + 1) * 160, 160))
            if name.endswith("_ALPHA.BMP"):
                # Constant outer opacity must not inherit the adjacent frame's value.
                np.testing.assert_array_equal(np.asarray(actual)[:, 0], np.asarray(source)[:, 0][0])


@pytest.mark.parametrize("name", ["C_WAIT.BMP", "C_WAIT_ALPHA.BMP"])
def test_missing_wait_companion_retains_present_layer(tmp_path: Path, name: str) -> None:
    _wait_pair(tmp_path)
    (tmp_path / name).unlink()
    assert analyze_directory(tmp_path).routes == {PipelineKind.NATIVE_SIZE_UNCHANGED: 1}


@pytest.mark.parametrize("name", ["C_WAIT.BMP", "C_WAIT_ALPHA.BMP"])
def test_explicit_wait_retention_retains_both_layers(tmp_path: Path, name: str) -> None:
    _wait_pair(tmp_path)
    override = tmp_path / "override.json"
    override.write_text(
        json.dumps(
            {
                "schema_version": 9,
                "feature_overrides": [
                    {
                        "textures": [name],
                        "set": {"native_size": True},
                        "reason": "Test pair retention.",
                    }
                ],
            }
        )
    )
    assert analyze_directory(tmp_path, overrides=override).routes == {
        PipelineKind.NATIVE_SIZE_UNCHANGED: 2
    }


def test_inconsistent_wait_layer_dimensions_are_rejected_without_archives(tmp_path: Path) -> None:
    _wait_pair(tmp_path)
    Image.new("L", (599, 40)).save(tmp_path / "C_WAIT_ALPHA.BMP")
    with pytest.raises(ValueError, match="different source dimensions"):
        analyze_directory(tmp_path)
