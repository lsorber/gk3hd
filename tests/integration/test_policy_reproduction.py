"""Policy and generated decisions reproduce outside a particular working directory."""

import json
from pathlib import Path

from PIL import Image

import gk3hd.textures.analyze.manifest as texture_analyze
import gk3hd.textures.upscale.service as texture_upscale
from gk3hd.textures.analyze.manifest import load_feature_manifest
from gk3hd.textures.pack.build import build_texture_pack
from gk3hd.textures.upscale.service import UpscaleOptions


def test_independent_policy_rebuilds_have_identical_analysis_pngs_and_pack(tmp_path: Path) -> None:
    policy = {
        "schema_version": 9,
        "feature_overrides": [
            {"textures": ["ART.BMP"], "set": {"tiled": True}, "reason": "Repeating surface."}
        ],
        "pipeline_overrides": [
            {
                "textures": ["ART.BMP"],
                "pipeline": "resample",
                "variant": "color",
                "status": "final",
                "reason": "Shared-purpose shading without invented detail.",
            },
            {
                "textures": ["F_UNKNOWN.BMP"],
                "pipeline": "retain",
                "variant": "unresolved-font",
                "status": "todo",
                "reason": "No verified glyph layout.",
                "todo": "Identify glyph cells before replacing the atlas.",
            },
        ],
    }
    images = {
        "ART.BMP": Image.new("RGB", (16, 16), (60, 70, 80)),
        "SOFT_OP.BMP": Image.new("L", (16, 16), 100),
        "ROOMWLKBNDS.BMP": Image.new("L", (16, 16)),
        "F_UNKNOWN.BMP": Image.new("RGB", (16, 16), (255, 0, 255)),
    }
    images["ART.BMP"].putpixel((4, 4), (200, 100, 50))
    images["SOFT_OP.BMP"].paste(220, (4, 4, 12, 12))
    inventories = []
    for index, names in enumerate((tuple(images), tuple(reversed(images)))):
        root = tmp_path / str(index)
        source, output = root / "original", root / "upscaled"
        source.mkdir(parents=True)
        for name in names:
            images[name].save(source / name)
        path = root / "policy.json"
        path.write_text(json.dumps(policy))
        manifest = root / "texture-analysis.json"
        report = texture_analyze.analyze(source, manifest, overrides=path)
        assert len(report.todos) == 1
        feature = load_feature_manifest(manifest)["ART.BMP"]
        assert feature.pipeline_override is not None
        assert feature.tiled
        options = UpscaleOptions(features=manifest)
        result = texture_upscale.upscale(source, output, options=options)
        assert (result.created, result.excluded) == (2, 2)
        assert texture_upscale.upscale(source, output, options=options).skipped == 2
        pack = build_texture_pack(output, root / "gk3hd-texture-pack-v1.0.zip", version="1.0")
        artifacts = [manifest, pack.archives[0], *sorted(output.glob("*.PNG"))]
        inventories.append({p.name: p.read_bytes() for p in artifacts})
    assert inventories[0] == inventories[1]
