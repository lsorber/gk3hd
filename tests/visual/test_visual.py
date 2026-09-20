"""Visual acceptance artifacts plus deterministic capture-contract assertions.

Passing capture checks is not approval of AI artwork: review the paired WebPs.
"""

import pytest
from PIL import Image

from tests.visual.support.catalog import Scene, scenes
from tests.visual.support.gallery import write_gallery_image

pytestmark = pytest.mark.visual


def test_scene(scene: Scene, request: pytest.FixtureRequest, pytestconfig: pytest.Config) -> None:
    """Each scene must produce fresh, correctly sized original and HD frames."""
    resolution = pytestconfig.getoption("--visual-resolution")
    captures = request.getfixturevalue(
        "interaction_captures" if scene.kind == "special" else "camera_captures"
    )
    for folder, dimensions in (
        ("reference-1024x768", (1024, 768)),
        (f"current-{resolution}", tuple(map(int, resolution.split("x")))),
    ):
        with Image.open(captures / folder / f"{scene.name}.png") as frame:
            assert frame.size == dimensions
            assert frame.convert("RGB").getextrema() != ((0, 0),) * 3
    animation = captures / "comparisons" / f"{scene.name}.webp"
    with Image.open(animation) as frames:
        assert getattr(frames, "n_frames", 1) == 2
    if scene in scenes():
        write_gallery_image(animation, captures / "gallery" / animation.name)
