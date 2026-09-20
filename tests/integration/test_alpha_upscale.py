import json
from pathlib import Path

import pytest
from PIL import Image

import gk3hd.textures.analyze.manifest as texture_analyze
import gk3hd.textures.upscale.service as texture_upscale
from gk3hd.textures.analyze.manifest import load_feature_manifest, write_manifest
from gk3hd.textures.install.service import install_texture_pack
from gk3hd.textures.model import TextureFeatures, TextureKind, TextureManifest
from gk3hd.textures.pack.build import build_texture_pack
from gk3hd.textures.pack.source import TexturePackSource
from gk3hd.textures.review import resampling_result, write_pair
from gk3hd.textures.routing import plan_texture
from gk3hd.textures.upscale import service as texture_service
from gk3hd.textures.upscale.generation import ALPHA_STAMP, GENERATION_STAMP, generation_stamp
from gk3hd.textures.upscale.pipeline import upscale_texture
from gk3hd.textures.workspace import analysis_file


class _Backend:
    scale = 4
    calls = 0

    def __init__(self, *, accepted: bool) -> None:
        self.accepted = accepted

    def upscale(self, image: Image.Image) -> Image.Image:
        self.calls += 1
        size = (image.width * 4, image.height * 4)
        return (
            image.resize(size, Image.Resampling.NEAREST)
            if self.accepted
            else Image.new("RGB", size, "white")
        )


@pytest.mark.parametrize("accepted", [True, False])
def test_alpha_analysis_upscale_resume_review_and_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, accepted: bool
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    path = source / "ITEM_OP.BMP"
    original = Image.new("L", (24, 24))
    original.paste(255, (4, 4, 20, 20))
    original.save(path)
    payload = path.read_bytes()
    report = texture_analyze.analyze(source, analysis_file(source))
    feature = report.manifest.textures[0]
    assert feature.alpha_silhouette
    backend = _Backend(accepted=accepted)
    monkeypatch.setattr(texture_service, "_create_seedvr2_upscaler", lambda *_a, **_k: backend)
    assert texture_upscale.upscale(source, output).created == 1
    assert backend.calls == 1
    assert texture_upscale.upscale(source, output).skipped == 1
    assert backend.calls == 1
    destination = output / "ITEM_OP.PNG"
    with Image.open(destination) as image:
        assert image.mode == "P"
        assert image.size == (96, 96)
        assert image.info[GENERATION_STAMP] == generation_stamp(path, plan_texture(feature))
        assert json.loads(image.info[ALPHA_STAMP])["method"] == ("ai" if accepted else "lanczos")
    result = resampling_result(path, feature, output)
    assert (result is None) == accepted
    if not accepted:
        pair = write_pair(path, feature, tmp_path / "review", backend, result=result)
        with (
            Image.open(tmp_path / "review/remaining-resampling" / str(pair["baseline"])) as base,
            Image.open(destination) as generated,
        ):
            assert base.convert("RGB").tobytes() == generated.convert("RGB").tobytes()
    pack = build_texture_pack(output, tmp_path / "gk3hd-texture-pack-v1.0.zip", version="1.0")
    game = tmp_path / "game"
    game.mkdir()
    (game / "GK3.ini").write_bytes(b"[Resource]\r\nCustom Paths=\r\n")
    assert install_texture_pack(game, TexturePackSource.local(pack.archives[0])).textures == 1
    with Image.open(game / "gk3hd/textures/installed/ITEM_OP.BMP") as installed:
        assert installed.size == (96, 96)
        with Image.open(destination) as generated:
            assert installed.convert("RGB").tobytes() == generated.convert("RGB").tobytes()
    assert path.read_bytes() == payload


def test_old_alpha_route_migrates_and_stale_guard_output_is_not_a_review_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    path = source / "ITEM_OP.BMP"
    original = Image.new("L", (24, 24))
    original.paste(255, (4, 4, 20, 20))
    original.save(path)
    old = TextureFeatures(path.name, kind=TextureKind.ALPHA)
    write_manifest(TextureManifest((old,)), analysis_file(source))
    assert texture_upscale.upscale(source, output).created == 1
    texture_analyze.analyze(source, analysis_file(source))
    feature = load_feature_manifest(analysis_file(source))[path.name]
    with pytest.raises(ValueError, match="stale"):
        resampling_result(path, feature, output)
    backend = _Backend(accepted=True)
    monkeypatch.setattr(texture_service, "_create_seedvr2_upscaler", lambda *_a, **_k: backend)
    assert texture_upscale.upscale(source, output).created == 1
    assert backend.calls == 1


def test_alpha_review_baseline_uses_production_lanczos(tmp_path: Path) -> None:
    source = tmp_path / "EYE_OP.BMP"
    original = Image.new("L", (24, 24), 255)
    original.paste(70, (6, 6, 18, 18))
    original.save(source)
    feature = TextureFeatures(source.name, kind=TextureKind.ALPHA)
    result = resampling_result(source, feature, tmp_path / "upscaled")
    pair = write_pair(source, feature, tmp_path / "review", _Backend(accepted=True), result=result)
    assert pair["baseline"] == "EYE_OP--1-lanczos-4x.png"
    expected = upscale_texture(original, feature)
    with Image.open(tmp_path / "review/remaining-resampling" / str(pair["baseline"])) as baseline:
        assert baseline.convert("RGB").tobytes() == expected.convert("RGB").tobytes()
