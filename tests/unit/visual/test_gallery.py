from pathlib import Path

import pytest
from PIL import Image, ImageSequence

from tests.visual.support.gallery import write_gallery_image


@pytest.mark.parametrize("lossless", [True, False])
def test_gallery_preserves_both_comparison_frames_and_timing(
    tmp_path: Path, *, lossless: bool
) -> None:
    source, destination = tmp_path / "comparison.webp", tmp_path / "gallery.webp"
    Image.new("RGB", (40, 30), "red").save(
        source,
        save_all=True,
        append_images=[Image.new("RGB", (40, 30), "blue")],
        duration=[400, 900],
        loop=3,
        lossless=lossless,
    )
    write_gallery_image(source, destination)
    assert destination.read_bytes() == source.read_bytes()
    with Image.open(destination) as result:
        assert getattr(result, "n_frames", 1) == 2
        assert result.info["loop"] == 3
        durations, colors = [], []
        for frame in ImageSequence.Iterator(result):
            frame.load()
            durations.append(frame.info["duration"])
            colors.append(frame.getpixel((10, 10)))
        assert durations == [400, 900]
        assert max(abs(a - b) for a, b in zip(colors[0], (255, 0, 0), strict=True)) <= 3
        assert max(abs(a - b) for a, b in zip(colors[1], (0, 0, 255), strict=True)) <= 3


def test_gallery_preserves_full_resolution_frames(tmp_path: Path) -> None:
    source = tmp_path / "large.webp"
    Image.new("RGB", (3840, 2160), "blue").save(source)
    output = tmp_path / "gallery"
    for name in ("room", "interface", "sidney"):
        write_gallery_image(source, output / f"{name}.webp")
        with Image.open(output / f"{name}.webp") as image:
            assert image.size == (3840, 2160)
            assert getattr(image, "n_frames", 1) == 1


def test_gallery_rejects_unencoded_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="already encoded WebP"):
        write_gallery_image(tmp_path / "source.png", tmp_path / "gallery.webp")
