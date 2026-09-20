from pathlib import Path

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from gk3hd.textures.model import PipelineOverride, TextureFeatures, TextureKind
from gk3hd.textures.review import experimental_features, review_group, write_pair


@pytest.mark.parametrize(
    ("features", "expected"),
    [
        (TextureFeatures("X.BMP", kind=TextureKind.DATA), None),
        (TextureFeatures("X.BMP", exact_raster=True), "retained-vs-ai"),
        (TextureFeatures("X.BMP", constant_color=True), "retained-vs-ai"),
        (TextureFeatures("X.BMP", kind=TextureKind.ALPHA), "bicubic-vs-ai"),
        (
            TextureFeatures(
                "X.BMP", pipeline_override=PipelineOverride("resample", "color", "final", "Test.")
            ),
            "bicubic-vs-ai",
        ),
        (TextureFeatures("X.BMP"), None),
    ],
)
def test_review_scope(features: TextureFeatures, expected: str | None) -> None:
    assert review_group(features) == expected


def test_experiments_keep_key_and_periodic_semantics_without_font_or_retention_rules() -> None:
    features = TextureFeatures("F_GPS_L.BMP", font_atlas=True, tiled=True)
    result = experimental_features(features, Image.new("RGB", (4, 4), (255, 0, 255)))
    assert result == TextureFeatures("REVIEW.BMP", tiled=True, alphatest=True)


def test_pairs_resume_by_source_and_do_not_overwrite_original(tmp_path: Path) -> None:
    class Backend:
        scale = 4
        calls = 0

        def upscale(self, image: Image.Image) -> Image.Image:
            self.calls += 1
            return image.resize((image.width * 4, image.height * 4))

    source = tmp_path / "ART.BMP"
    Image.new("RGB", (8, 4), "green").save(source)
    before = source.read_bytes()
    backend = Backend()
    features = TextureFeatures(source.name, exact_raster=True)
    row = write_pair(source, features, tmp_path / "review", backend)
    assert backend.calls == 1
    assert row["production"] == {"pipeline": "retain", "variant": "pixel-art"}
    write_pair(source, features, tmp_path / "review", backend)
    assert backend.calls == 1
    assert source.read_bytes() == before
    folder = tmp_path / "review/retained-vs-ai"
    with Image.open(folder / "ART--1-retained-native.png") as original:
        assert original.size == (8, 4)
    with Image.open(folder / "ART--2-seedvr2-4x.png") as enlarged:
        assert enlarged.size == (32, 16)
    Image.new("RGB", (8, 4), "blue").save(source)
    write_pair(source, features, tmp_path / "review", backend)
    assert backend.calls == 2


def test_cached_ai_preview_refreshes_mask_without_repeating_inference(tmp_path: Path) -> None:
    class Backend:
        scale = 4
        calls = 0

        def upscale(self, image: Image.Image) -> Image.Image:
            self.calls += 1
            return image.resize((image.width * 4, image.height * 4))

    source = tmp_path / "TREE.BMP"
    image = Image.new("RGB", (8, 8), (255, 0, 255))
    image.paste((40, 80, 20), (2, 3, 6, 8))
    image.save(source)
    backend = Backend()
    feature = TextureFeatures(source.name, exact_raster=True, alphatest=True, tiled=True)
    row = write_pair(source, feature, tmp_path / "review", backend)
    candidate = tmp_path / "review/retained-vs-ai" / str(row["candidate"])
    with Image.open(candidate) as opened:
        dirty = opened.convert("RGB")
        stamp = opened.info["gk3hd-review"]
    dirty.putpixel((4, 0), (0, 0, 0))
    metadata = PngInfo()
    metadata.add_text("gk3hd-review", stamp)
    dirty.save(candidate, pnginfo=metadata)
    write_pair(source, feature, tmp_path / "review", backend)
    assert backend.calls == 1
    with Image.open(candidate) as corrected:
        assert corrected.getpixel((4, 0)) == (255, 0, 255)
