"""Joined frame inference, source-dependent resume, and legacy guard migration."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from PIL import Image

import gk3hd.textures.upscale.service as texture_upscale
from gk3hd.textures.analyze.manifest import load_feature_manifest, write_manifest
from gk3hd.textures.model import TextureFeatures, TextureManifest
from gk3hd.textures.upscale import service as texture_service
from gk3hd.textures.upscale.service import UpscaleOptions
from gk3hd.textures.upscale.sidney_frame import FRAME_BATCH, FRAME_REGIONS, FRAME_STAMP
from gk3hd.textures.workspace import analysis_file

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.integration
def test_frame_is_joined_once_and_resume_binds_all_five_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    for index, (name, (left, top, right, bottom)) in enumerate(FRAME_REGIONS.items()):
        Image.new("RGB", (right - left, bottom - top), (index * 40, 50, 60)).save(source / name)
    analysis_file(source).write_text(
        json.dumps(
            {
                "schema_version": 9,
                "textures": [{"name": name, "native_size": True} for name in FRAME_REGIONS],
            }
        ),
        encoding="utf-8",
    )
    calls = []

    class Backend:
        scale = 4

        def upscale(self, image: Image.Image) -> Image.Image:
            calls.append(image.copy())
            return image.resize((image.width * 4, image.height * 4), Image.Resampling.NEAREST)

    monkeypatch.setattr(texture_service, "_create_seedvr2_upscaler", lambda *_args: Backend())
    report = texture_upscale.upscale(source, output)
    assert (report.created, report.excluded) == (5, 0)
    assert all(
        not feature.native_size for feature in load_feature_manifest(analysis_file(source)).values()
    )
    assert len(calls) == 1
    assert calls[0].size == (1040, 784)  # one joined canvas with normal edge padding
    assert calls[0].getpixel((512 + 8, 384 + 8)) == (0, 0, 0)
    assert calls[0].getpixel((192 + 8, 611 + 8)) == (160, 50, 60)
    stamps = set()
    for name in FRAME_REGIONS:
        with (
            Image.open(source / name) as original,
            Image.open(output / f"{name[:-4]}.PNG") as dense,
        ):
            assert dense.size == (original.width * 4, original.height * 4)
            assert dense.getpixel((10, 10)) == original.getpixel((2, 2))
            stamps.add(dense.info[FRAME_STAMP])
    assert len(stamps) == 1
    assert len(list(output.iterdir())) == 5  # no artificial full-frame asset in packs
    resumed = texture_upscale.upscale(source, output)
    assert (resumed.created, resumed.skipped, len(calls)) == (0, 5, 1)

    # A changed companion invalidates every crop, not just its own PNG.
    top_name = next(iter(FRAME_REGIONS))
    Image.new("RGB", (1024, 144), (70, 80, 90)).save(source / top_name)
    regenerated = texture_upscale.upscale(source, output)
    assert (regenerated.created, regenerated.skipped, len(calls)) == (5, 0, 2)
    with Image.open(output / f"{top_name[:-4]}.PNG") as result:
        assert result.info[FRAME_STAMP] not in stamps

    # The formerly omitted postcard is part of the same inference transaction.
    Image.new("RGB", (174, 13), (90, 100, 110)).save(source / "S_SID_BKGD800_LAMA_A.BMP")
    postcard_changed = texture_upscale.upscale(source, output)
    assert (postcard_changed.created, postcard_changed.skipped, len(calls)) == (5, 0, 3)
    assert calls[-1].getpixel((192 + 8, 611 + 8)) == (90, 100, 110)

    # A missing crop requires one fresh inference for every sibling, not a
    # mixture of the previous and next (potentially stochastic) generation.
    (output / "S_SID_BKGD800_LAMA_A.PNG").unlink()
    partial = texture_upscale.upscale(source, output)
    assert (partial.created, partial.skipped, len(calls)) == (5, 0, 4)

    # A crash between atomic PNG replacements leaves all paths present, but
    # their batch IDs reveal a mixture of two inferences with identical input.
    top_output = output / f"{top_name[:-4]}.PNG"
    with Image.open(top_output) as image:
        previous_generation = image.copy()
    texture_upscale.upscale(source, output, options=UpscaleOptions(overwrite=True))
    texture_service._write_png_atomic(previous_generation, top_output)
    recovered = texture_upscale.upscale(source, output)
    assert (recovered.created, recovered.skipped, len(calls)) == (5, 0, 6)
    batches = set()
    for name in FRAME_REGIONS:
        with Image.open(output / f"{name[:-4]}.PNG") as image:
            batches.add(image.info[FRAME_BATCH])
    assert len(batches) == 1
    assert texture_upscale.upscale(source, output).skipped == 5


@pytest.mark.integration
def test_independent_frame_output_is_not_silently_resumed(tmp_path: Path) -> None:
    from gk3hd.textures.upscale.sidney_frame import is_current_frame  # noqa: PLC0415

    for name, (left, top, right, bottom) in FRAME_REGIONS.items():
        Image.new("RGB", (right - left, bottom - top)).save(tmp_path / name)
    candidate = tmp_path / "old.PNG"
    Image.new("RGB", (4096, 576)).save(candidate)
    assert not is_current_frame(tmp_path / next(iter(FRAME_REGIONS)), candidate)


@pytest.mark.integration
def test_explicit_native_frame_exclusion_does_not_inspect_removed_outputs(tmp_path: Path) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    output.mkdir()
    for name, (left, top, right, bottom) in FRAME_REGIONS.items():
        Image.new("RGB", (right - left, bottom - top)).save(source / name)
        Image.new("RGB", (1, 1)).save(output / f"{name[:-4]}.PNG")
    manifest = tmp_path / "analysis.json"
    write_manifest(
        TextureManifest(tuple(TextureFeatures(name, native_size=True) for name in FRAME_REGIONS)),
        manifest,
    )
    report = texture_upscale.upscale(source, output, options=UpscaleOptions(features=manifest))
    assert (report.created, report.skipped, report.excluded) == (0, 0, 5)
    assert not list(output.iterdir())


@pytest.mark.integration
def test_changed_frame_source_during_inference_publishes_no_pieces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    for name, (left, top, right, bottom) in FRAME_REGIONS.items():
        Image.new("RGB", (right - left, bottom - top), (40, 30, 20)).save(source / name)

    class Backend:
        scale = 4

        def upscale(self, image: Image.Image) -> Image.Image:
            Image.new("RGB", (174, 13), (80, 60, 40)).save(source / "S_SID_BKGD800_LAMA_A.BMP")
            return image.resize((image.width * 4, image.height * 4))

    monkeypatch.setattr(texture_service, "_create_seedvr2_upscaler", lambda *_args: Backend())
    with pytest.raises(ValueError, match="SIDNEY frame source changed"):
        texture_upscale.upscale(source, output)
    assert not list(output.glob("*.PNG"))
