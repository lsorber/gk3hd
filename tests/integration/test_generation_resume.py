"""Resume inference only for matching source bytes and processing recipes."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from PIL import Image

import gk3hd.textures.upscale.service as texture_upscale
from gk3hd.textures.analyze.manifest import write_manifest
from gk3hd.textures.model import TextureFeatures, TextureKind, TextureManifest
from gk3hd.textures.upscale import generation, service
from gk3hd.textures.upscale.generation import GENERATION_STAMP
from gk3hd.textures.upscale.service import UpscaleOptions

if TYPE_CHECKING:
    from pathlib import Path


class _Backend:
    scale = 4

    def upscale(self, image: Image.Image) -> Image.Image:
        return image.resize((image.width * 4, image.height * 4))


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["color", "keyed", "alpha"])
@pytest.mark.parametrize("change", ["source", "periodicity", "recipe", "unstamped"])
def test_changed_generation_is_rebuilt_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, change: str
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    original = source / "ART.BMP"
    pixels = Image.new("RGB", (8, 8), (90, 70, 50))
    pixels.putpixel((0, 0), (255, 0, 255))
    if kind == "alpha":
        pixels = pixels.convert("L")
    pixels.save(original)
    feature = TextureFeatures(
        name=original.name,
        kind=TextureKind.ALPHA if kind == "alpha" else TextureKind.COLOR,
        alphatest=kind == "keyed",
    )
    manifest = tmp_path / "analysis.json"
    write_manifest(TextureManifest((feature,)), manifest)
    monkeypatch.setattr(service, "_create_seedvr2_upscaler", lambda *_args: _Backend())
    options = UpscaleOptions(features=manifest)
    assert texture_upscale.upscale(source, output, options=options).created == 1
    assert texture_upscale.upscale(source, output, options=options).skipped == 1
    destination = output / "ART.PNG"
    with Image.open(destination) as image:
        stamp = image.info[GENERATION_STAMP]
    if change == "source":
        # Keep dimensions and the keyed silhouette unchanged: RGB matters too.
        pixels.putpixel((3, 3), 220 if kind == "alpha" else (220, 180, 130))
        pixels.save(original)
    elif change == "periodicity":
        write_manifest(TextureManifest((replace(feature, tiled=True),)), manifest)
    elif change == "recipe":
        monkeypatch.setattr(generation, "GENERATION_REVISION", generation.GENERATION_REVISION + 1)
    else:
        with Image.open(destination) as image:
            unproven = image.copy()
        unproven.save(destination)
    report = texture_upscale.upscale(source, output, options=options)
    assert (report.created, report.skipped) == (1, 0)
    with Image.open(destination) as image:
        assert (image.info[GENERATION_STAMP] == stamp) == (change == "unstamped")
    assert texture_upscale.upscale(source, output, options=options).skipped == 1


@pytest.mark.integration
def test_route_change_does_not_reuse_old_keyed_rgb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    image = Image.new("RGB", (8, 8), (100, 70, 30))
    image.putpixel((0, 0), (255, 0, 255))
    image.save(source / "ART.BMP")
    manifest = tmp_path / "analysis.json"
    feature = TextureFeatures("ART.BMP")
    write_manifest(TextureManifest((feature,)), manifest)
    monkeypatch.setattr(service, "_create_seedvr2_upscaler", lambda *_args: _Backend())
    options = UpscaleOptions(features=manifest)
    texture_upscale.upscale(source, output, options=options)
    write_manifest(TextureManifest((replace(feature, alphatest=True),)), manifest)
    report = texture_upscale.upscale(source, output, options=options)
    assert (report.created, report.skipped) == (1, 0)
    with Image.open(output / "ART.PNG") as generated:
        assert ":alpha-test-ai:" in generated.info[GENERATION_STAMP]
    assert texture_upscale.upscale(source, output, options=options).skipped == 1


@pytest.mark.integration
def test_source_changed_during_inference_preserves_previous_output(tmp_path: Path) -> None:
    original, destination = tmp_path / "ART.BMP", tmp_path / "ART.PNG"
    Image.new("RGB", (8, 8), (80, 60, 40)).save(original)
    Image.new("RGB", (32, 32), (40, 30, 20)).save(destination)
    previous = destination.read_bytes()

    class MutatingBackend(_Backend):
        def upscale(self, image: Image.Image) -> Image.Image:
            Image.new("RGB", (8, 8), (70, 50, 30)).save(original)
            return super().upscale(image)

    with pytest.raises(RuntimeError, match="source changed during upscaling"):
        service._upscale_one(
            original, destination, TextureFeatures(original.name), MutatingBackend()
        )
    assert destination.read_bytes() == previous


@pytest.mark.integration
@pytest.mark.parametrize(
    ("base_name", "overlay_name", "size"),
    [("DM_BASE.BMP", "DM_WOD_UL.BMP", (98, 75)), ("TBT102P.BMP", "D102P_01.BMP", (383, 63))],
)
def test_new_background_regenerates_previously_current_overlays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    base_name: str,
    overlay_name: str,
    size: tuple[int, int],
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    Image.new("RGB", (640, 480), (40, 30, 20)).save(source / base_name)
    Image.new("RGB", size, (40, 30, 20)).save(source / overlay_name)
    manifest = tmp_path / "analysis.json"
    write_manifest(
        TextureManifest((TextureFeatures(base_name), TextureFeatures(overlay_name))), manifest
    )

    class ChangingBackend(_Backend):
        calls = 0

        def upscale(self, image: Image.Image) -> Image.Image:
            self.calls += 1
            return Image.new("RGB", (image.width * 4, image.height * 4), (self.calls * 40, 30, 20))

    backend = ChangingBackend()
    monkeypatch.setattr(service, "_create_seedvr2_upscaler", lambda *_args: backend)
    options = UpscaleOptions(features=manifest)
    assert texture_upscale.upscale(source, output, options=options).created == 2
    assert texture_upscale.upscale(source, output, options=options).skipped == 2
    # The old overlay still matches the old HD base exactly during partition.
    # Recipe invalidation means that base is about to change later in this run.
    monkeypatch.setattr(generation, "GENERATION_REVISION", generation.GENERATION_REVISION + 1)
    report = texture_upscale.upscale(source, output, options=options)
    assert (report.created, report.skipped, backend.calls) == (2, 0, 2)
    with Image.open(output / f"{overlay_name[:-4]}.PNG") as overlay:
        assert overlay.getextrema() == ((80, 80), (30, 30), (20, 20))
    assert texture_upscale.upscale(source, output, options=options).skipped == 2
