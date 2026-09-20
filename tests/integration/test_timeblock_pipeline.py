"""Time-transition dependency ordering, faithful composition, and safe resume."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from PIL import Image

import gk3hd.textures.analyze.manifest as texture_analyze
import gk3hd.textures.upscale.service as texture_upscale
from gk3hd.textures.analyze.manifest import write_manifest
from gk3hd.textures.model import TEXTURE_MANIFEST_SCHEMA_VERSION, TextureFeatures, TextureManifest
from gk3hd.textures.routing import PipelineKind
from gk3hd.textures.upscale import service
from gk3hd.textures.upscale.generation import GENERATION_STAMP
from gk3hd.textures.upscale.service import UpscaleOptions
from gk3hd.textures.workspace import ANALYSIS_FILENAME

if TYPE_CHECKING:
    from pathlib import Path


class _CountingBackend:
    scale = 4

    def __init__(self) -> None:
        self.calls = 0

    def upscale(self, image: Image.Image) -> Image.Image:
        self.calls += 1
        return Image.new("RGB", (image.width * 4, image.height * 4), (60, 80, 100))


@pytest.mark.integration
def test_cached_native_guard_refreshes_to_shared_background_composition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "textures" / "original"
    source.mkdir(parents=True)
    names = ("TBT102P.BMP", "D102P_01.BMP")
    for name, size in zip(names, ((640, 480), (383, 63)), strict=True):
        Image.new("RGB", size, (30, 40, 50)).save(source / name)
    analysis = source.parent / ANALYSIS_FILENAME
    analysis.write_text(
        json.dumps(
            {
                "schema_version": 7,
                "textures": [
                    {"name": name, "kind": "color", "native_size": name.startswith("D")}
                    for name in names
                ],
            }
        ),
        encoding="utf-8",
    )
    backend = _CountingBackend()
    monkeypatch.setattr(service, "_create_seedvr2_upscaler", lambda *_a, **_kw: backend)
    report = texture_upscale.upscale(source, tmp_path / "upscaled")
    assert (report.created, report.excluded, backend.calls) == (2, 0, 1)
    refreshed = json.loads(analysis.read_text(encoding="utf-8"))
    assert refreshed["schema_version"] == TEXTURE_MANIFEST_SCHEMA_VERSION
    assert all(not entry["native_size"] for entry in refreshed["textures"])
    assert texture_analyze.analyze(source, analysis).routes == {
        PipelineKind.COLOR_AI: 1,
        PipelineKind.TIMEBLOCK_COMPOSITE: 1,
    }


@pytest.mark.integration
def test_base_is_generated_before_frames_and_stale_composites_are_refreshed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "original"
    output = tmp_path / "upscaled"
    source.mkdir()
    Image.new("RGB", (640, 480), (30, 40, 50)).save(source / "tbt102p.bmp")
    Image.new("RGB", (383, 63), (30, 40, 50)).save(source / "d102p_01.bmp")
    manifest = tmp_path / "analysis.json"
    write_manifest(
        TextureManifest((TextureFeatures("TBT102P.BMP"), TextureFeatures("D102P_01.BMP"))),
        manifest,
    )
    backend = _CountingBackend()
    monkeypatch.setattr(service, "_create_seedvr2_upscaler", lambda *_a, **_kw: backend)
    options = UpscaleOptions(features=manifest)
    progress: list[int] = []
    report = texture_upscale.upscale(
        source, output, options=options, progress=lambda n, _total: progress.append(n)
    )
    assert (report.created, report.excluded, backend.calls) == (2, 0, 1)
    assert progress == [1, 2]
    with Image.open(output / "d102p_01.PNG") as frame:
        assert frame.size == (1532, 252)
        assert frame.getextrema() == ((60, 60), (80, 80), (100, 100))
    assert texture_upscale.upscale(source, output, options=options).skipped == 2
    with Image.open(output / "tbt102p.PNG") as generated:
        stamp = generated.info[GENERATION_STAMP]
    replacement = Image.new("RGB", (2560, 1920), (90, 70, 50))
    replacement.info[GENERATION_STAMP] = stamp
    service._write_png_atomic(replacement, output / "tbt102p.PNG")
    refreshed = texture_upscale.upscale(source, output, options=options)
    assert (refreshed.created, refreshed.skipped, backend.calls) == (1, 1, 1)
    with Image.open(output / "d102p_01.PNG") as frame:
        assert frame.getextrema() == ((90, 90), (70, 70), (50, 50))


@pytest.mark.integration
def test_missing_background_fails_with_the_required_resource_name(tmp_path: Path) -> None:
    source = tmp_path / "original"
    source.mkdir()
    Image.new("RGB", (383, 63)).save(source / "D102P_01.BMP")
    manifest = tmp_path / "analysis.json"
    write_manifest(TextureManifest((TextureFeatures("D102P_01.BMP"),)), manifest)
    with pytest.raises(FileNotFoundError, match=r"requires TBT102P\.BMP"):
        texture_upscale.upscale(
            source, tmp_path / "upscaled", options=UpscaleOptions(features=manifest)
        )
