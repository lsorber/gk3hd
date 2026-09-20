"""Exact-source inference sharing without merging different texture contracts."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image

import gk3hd.textures.upscale.service as texture_upscale
from gk3hd.textures.analyze.manifest import write_manifest
from gk3hd.textures.model import TextureFeatures, TextureManifest
from gk3hd.textures.upscale.generation import GENERATION_STAMP
from gk3hd.textures.upscale.service import UpscaleOptions
from gk3hd.textures.upscale.sidney_frame import FRAME_REGIONS

if TYPE_CHECKING:
    from pathlib import Path


class _Backend:
    scale = 4

    def __init__(self) -> None:
        self.calls = 0

    def upscale(self, image: Image.Image) -> Image.Image:
        self.calls += 1
        return image.resize((image.width * 4, image.height * 4), Image.Resampling.NEAREST)


def _sources(directory: Path) -> tuple[Path, Path]:
    directory.mkdir()
    image = Image.new("RGB", (8, 8), (255, 0, 255))
    image.paste((80, 90, 100), (2, 2, 6, 6))
    first, second = directory / "FIRST.BMP", directory / "SECOND.BMP"
    image.save(first)
    second.write_bytes(first.read_bytes())
    return first, second


@pytest.mark.parametrize("periodic", [False, True])
@pytest.mark.parametrize("keyed", [False, True])
def test_identical_ai_sources_share_inference_and_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, periodic: bool, keyed: bool
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    paths = _sources(source)
    pristine = [path.read_bytes() for path in paths]
    features = tmp_path / "features.json"
    write_manifest(
        TextureManifest(
            tuple(TextureFeatures(path.name, tiled=periodic, alphatest=keyed) for path in paths)
        ),
        features,
    )
    backend = _Backend()
    monkeypatch.setattr(texture_upscale, "_create_seedvr2_upscaler", lambda *_args: backend)
    options = UpscaleOptions(features=features)

    report = texture_upscale.upscale(source, output, options=options)

    assert (report.created, report.skipped, report.excluded) == (2, 0, 0)
    assert backend.calls == 1
    assert (output / "FIRST.PNG").read_bytes() == (output / "SECOND.PNG").read_bytes()
    with Image.open(output / "SECOND.PNG") as image:
        assert image.size == (32, 32)
        assert GENERATION_STAMP in image.info
    assert texture_upscale.upscale(source, output, options=options).skipped == 2
    assert backend.calls == 1
    assert [path.read_bytes() for path in paths] == pristine


@pytest.mark.parametrize("difference", ["periodic", "route", "source"])
def test_different_sources_or_contracts_do_not_share_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, difference: str
) -> None:
    source = tmp_path / "original"
    first, second = _sources(source)
    if difference == "source":
        with Image.open(second) as image:
            image.putpixel((3, 3), (7, 8, 9))
            image.save(second)
    features = tmp_path / "features.json"
    write_manifest(
        TextureManifest(
            (
                TextureFeatures(first.name),
                TextureFeatures(
                    second.name, tiled=difference == "periodic", alphatest=difference == "route"
                ),
            )
        ),
        features,
    )
    backend = _Backend()
    monkeypatch.setattr(texture_upscale, "_create_seedvr2_upscaler", lambda *_args: backend)

    report = texture_upscale.upscale(
        source, tmp_path / "upscaled", options=UpscaleOptions(features=features)
    )

    assert report.created == 2
    assert backend.calls == 2


def test_corrupt_reuse_candidate_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    _sources(source)
    backend = _Backend()
    monkeypatch.setattr(texture_upscale, "_create_seedvr2_upscaler", lambda *_args: backend)

    def progress(done: int, _total: int) -> None:
        if done == 1:
            (output / "FIRST.PNG").write_bytes(b"externally damaged cache")

    with pytest.raises(ValueError, match="existing upscale output is invalid"):
        texture_upscale.upscale(source, output, progress=progress)

    assert backend.calls == 1
    assert not (output / "SECOND.PNG").exists()


def test_reuse_rejects_source_changes_before_publishing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    _sources(source)
    backend = _Backend()
    monkeypatch.setattr(texture_upscale, "_create_seedvr2_upscaler", lambda *_args: backend)
    original_check = texture_upscale._is_resumable_png

    def changing_check(path: Path, destination: Path, plan: texture_upscale.PipelinePlan) -> bool:
        result = original_check(path, destination, plan)
        if path.name == "SECOND.BMP" and destination.name == "FIRST.PNG" and result:
            with Image.open(path) as image:
                image.putpixel((3, 3), (7, 8, 9))
                image.save(path)
        return result

    monkeypatch.setattr(texture_upscale, "_is_resumable_png", changing_check)

    with pytest.raises(ValueError, match="source changed during upscaling"):
        texture_upscale.upscale(source, output)
    assert not (output / "SECOND.PNG").exists()


def test_joined_sidney_frames_keep_their_separate_inference_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    for name, (left, top, right, bottom) in FRAME_REGIONS.items():
        image = Image.new("RGB", (right - left, bottom - top), (40, 50, 60))
        image.putpixel((1, 1), (60, 70, 80))
        image.save(source / name)
    (source / "ZZ_DUPLICATE.BMP").write_bytes((source / "S_SID_BKGD1024_TOP_A.BMP").read_bytes())
    joined_calls = []

    def joined(_source: Path, _backend: object) -> dict[str, Image.Image]:
        joined_calls.append(True)
        return {
            name: Image.new("RGB", ((right - left) * 4, (bottom - top) * 4), (1, 2, 3))
            for name, (left, top, right, bottom) in FRAME_REGIONS.items()
        }

    backend = _Backend()
    monkeypatch.setattr(texture_upscale, "_create_seedvr2_upscaler", lambda *_args: backend)
    monkeypatch.setattr(texture_upscale, "upscale_frame", joined)

    report = texture_upscale.upscale(source, output)

    assert report.created == 6
    assert joined_calls == [True]
    assert backend.calls == 1
    with Image.open(output / "ZZ_DUPLICATE.PNG") as image:
        assert image.getpixel((0, 0)) == (40, 50, 60)
