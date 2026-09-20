"""Old native-size thumbnail guards must not survive implicit analysis refresh."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from PIL import Image

import gk3hd.textures.upscale.service as texture_upscale
from gk3hd.textures.model import TEXTURE_MANIFEST_SCHEMA_VERSION
from gk3hd.textures.upscale import service as texture_service
from gk3hd.textures.workspace import ANALYSIS_FILENAME

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.integration
@pytest.mark.parametrize(
    ("names", "sizes", "old_schema"),
    [
        (("BLAZER_3.BMP", "GABEROOMKEY3.BMP", "BLUEAPPLE3.BMP"), ((32, 30), (30, 32), (32, 31)), 6),
        (("GAB_MUGSHOT.BMP", "GRA_MUGSHOT.BMP"), ((67, 78), (67, 78)), 8),
    ],
)
def test_old_thumbnail_guards_are_reanalyzed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    names: tuple[str, ...],
    sizes: tuple[tuple[int, int], ...],
    old_schema: int,
) -> None:
    source = tmp_path / "textures" / "original"
    source.mkdir(parents=True)
    for name, size in zip(names, sizes, strict=True):
        image = Image.new("RGB", size, (12, 34, 56))
        image.putpixel((size[0] - 1, size[1] - 1), (13, 34, 56))
        image.save(source / name)
    if "BLUEAPPLE3.BMP" in names:
        # The preview now reconstructs from this original page rather than AI.
        Image.new("RGB", (640, 480), (12, 34, 56)).save(source / "BLUEAPPLE.BMP")
    analysis = source.parent / ANALYSIS_FILENAME
    analysis.write_text(
        json.dumps(
            {
                "schema_version": old_schema,
                "textures": [
                    {"name": name, "kind": "color", "native_size": True} for name in names
                ],
            }
        ),
        encoding="utf-8",
    )

    class Upscaler:
        scale = 4

        def upscale(self, image: Image.Image) -> Image.Image:
            return image.resize((image.width * 4, image.height * 4))

    monkeypatch.setattr(texture_service, "_create_seedvr2_upscaler", lambda *_args: Upscaler())
    report = texture_upscale.upscale(source, tmp_path / "png")
    # BLUEAPPLE is now a supported source-preserving SIDNEY page itself,
    # not merely an excluded reconstruction dependency for its thumbnail.
    assert report.created == len(names) + int("BLUEAPPLE3.BMP" in names)
    assert report.excluded == 0
    for name, size in zip(names, sizes, strict=True):
        with Image.open(tmp_path / "png" / name.replace(".BMP", ".PNG")) as output:
            assert output.size == (size[0] * 4, size[1] * 4)
    if "BLUEAPPLE3.BMP" in names:
        with Image.open(tmp_path / "png" / "BLUEAPPLE.PNG") as output:
            assert output.size == (2560, 1920)
    refreshed = json.loads(analysis.read_text(encoding="utf-8"))
    assert refreshed["schema_version"] == TEXTURE_MANIFEST_SCHEMA_VERSION
    assert all(
        not entry["native_size"] for entry in refreshed["textures"] if entry["name"] in names
    )
