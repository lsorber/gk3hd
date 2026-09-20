"""Reviewed artwork remains portable, source-bound and safe to resume."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from gk3hd.textures.analyze.policy import load_policy
from gk3hd.textures.bmp import inspect_bmp
from gk3hd.textures.model import TextureFeatures, TextureKind
from gk3hd.textures.routing import PipelineKind, plan_texture
from gk3hd.textures.upscale import replacement
from gk3hd.textures.upscale.service import _is_resumable_png, _upscale_one

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("name", ["LHO_CHST.BMP", "lho_chst.bmp"])
def test_packaged_artwork_is_bound_and_small(name: str) -> None:
    asset = replacement.replacement_asset(name)
    assert asset.name == "LHO_CHST.PNG"
    assert len(asset.read_bytes()) < 100_000
    with asset.open("rb") as stream, Image.open(stream) as image:
        assert image.size == (512, 512)
        assert image.mode == "RGB"
        assert len(str(image.info[replacement.SOURCE_STAMP])) == 64


def test_replacement_policy_resume_and_source_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "LHO_CHST.BMP"
    Image.new("RGB", (8, 8), (40, 60, 80)).save(source)
    asset = tmp_path / "reviewed.png"
    metadata = PngInfo()
    with Image.open(source) as original:
        metadata.add_text(replacement.SOURCE_STAMP, hashlib.sha256(original.tobytes()).hexdigest())
    expected = Image.new("RGB", (32, 32), (41, 61, 81))
    expected.save(asset, pnginfo=metadata)
    monkeypatch.setattr(replacement, "replacement_asset", lambda _name: asset)
    features = load_policy().apply(TextureFeatures(source.name), inspect_bmp(source))
    plan = plan_texture(features)
    assert plan.kind is PipelineKind.REVIEWED_REPLACEMENT
    assert features.pipeline_override is not None
    assert features.pipeline_override.status == "final"
    destination = tmp_path / "output.png"
    Image.new("RGB", (32, 32), "red").save(destination)
    assert not _is_resumable_png(source, destination, plan)
    _upscale_one(source, destination, features, None)
    assert _is_resumable_png(source, destination, plan)
    with Image.open(destination) as actual:
        assert actual.tobytes() == expected.tobytes()
    Image.new("RGB", (8, 8), "blue").save(source)
    with pytest.raises(ValueError, match="does not match original"):
        replacement.regenerate_replacement(source)


def test_replacement_cannot_override_gameplay_data(tmp_path: Path) -> None:
    source = tmp_path / "LHO_CHST.BMP"
    Image.new("RGB", (8, 8)).save(source)
    with pytest.raises(ValueError, match="incompatible"):
        load_policy().apply(
            TextureFeatures(source.name, kind=TextureKind.DATA), inspect_bmp(source)
        )


@pytest.mark.parametrize("name", ["../LHO_CHST.BMP", "dir\\LHO_CHST.BMP", "C:LHO_CHST.BMP"])
def test_resource_names_cannot_escape_package(name: str) -> None:
    with pytest.raises(ValueError, match="invalid replacement"):
        replacement.replacement_asset(name)
