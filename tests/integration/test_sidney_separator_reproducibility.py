"""SIDNEY separator reconstruction needs only originals and the public service."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from PIL import Image

import gk3hd.textures.analyze.manifest as texture_analyze
import gk3hd.textures.upscale.service as texture_upscale
from gk3hd.textures.analyze.manifest import load_feature_manifest
from gk3hd.textures.routing import PipelineKind, plan_texture
from gk3hd.textures.upscale import service
from gk3hd.textures.workspace import analysis_file

if TYPE_CHECKING:
    from pathlib import Path


def test_separator_analysis_and_reconstruction_are_repeatable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_model(*_args: object, **_kwargs: object) -> None:
        pytest.fail("a two-pixel menu rule must not invoke AI")

    monkeypatch.setattr(service, "_create_seedvr2_upscaler", fail_model)
    outputs: list[bytes] = []
    manifests: list[bytes] = []
    for run in range(2):
        root = tmp_path / str(run)
        source, output = root / "original", root / "upscaled"
        source.mkdir(parents=True)
        output.mkdir()
        originals = {
            "S_BIT_SPACE1.BMP": Image.new("RGB", (2, 1), (0, 0, 0)),
            "S_BIT_SPACE2.BMP": Image.new("RGB", (1, 12), (64, 64, 64)),
        }
        originals["S_BIT_SPACE1.BMP"].putpixel((1, 0), (64, 64, 64))
        for name in sorted(originals, reverse=bool(run)):
            originals[name].save(source / name)
        before = {p.name: p.read_bytes() for p in source.iterdir()}
        monkeypatch.chdir(root)
        if run == 0:
            texture_analyze.analyze(source)
        else:
            # Normal resume migrates old analysis and replaces stale AI output.
            analysis_file(source).write_text(json.dumps({"schema_version": 123, "textures": []}))
            Image.new("RGB", (8, 4), (255, 255, 255)).save(output / "S_BIT_SPACE1.PNG")
        result = texture_upscale.upscale(source, output)
        assert (result.created, result.skipped, result.excluded) == (1, 0, 1)
        manifest = load_feature_manifest(analysis_file(source))
        assert plan_texture(manifest["S_BIT_SPACE1.BMP"]).kind is PipelineKind.UI_SOURCE_4X
        assert (
            plan_texture(manifest["S_BIT_SPACE2.BMP"]).kind is PipelineKind.CONSTANT_COLOR_UNCHANGED
        )
        with Image.open(output / "S_BIT_SPACE1.PNG") as enlarged:
            assert (
                enlarged.tobytes()
                == originals["S_BIT_SPACE1.BMP"].resize((8, 4), Image.Resampling.NEAREST).tobytes()
            )
        resumed = texture_upscale.upscale(source, output)
        assert (resumed.created, resumed.skipped, resumed.excluded) == (0, 1, 1)
        outputs.append((output / "S_BIT_SPACE1.PNG").read_bytes())
        manifests.append(analysis_file(source).read_bytes())
        assert not (output / "S_BIT_SPACE2.PNG").exists()
        assert {p.name: p.read_bytes() for p in source.iterdir()} == before
    assert outputs[0] == outputs[1]
    assert manifests[0] == manifests[1]
