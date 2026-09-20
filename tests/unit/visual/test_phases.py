"""Blink phases are observed in native pixels, not inferred from elapsed time."""

import pytest
from PIL import Image, ImageDraw

from tests.visual.support.phases import EMAIL_NOTICE, LOCATION_MARKER, green_indicator_visible


@pytest.mark.parametrize("size", [(1024, 768), (1280, 800), (3840, 2160)])
@pytest.mark.parametrize("region", [EMAIL_NOTICE, LOCATION_MARKER])
def test_native_indicator_phase_uses_the_fitted_viewport(
    size: tuple[int, int], region: tuple[int, int, int, int]
) -> None:
    frame = Image.new("RGB", size, "black")
    draw = ImageDraw.Draw(frame)
    draw.rectangle((0, 0, 50, 50), fill="lime")
    assert not green_indicator_visible(frame, region)
    left, top, right, bottom = region
    scale = size[1] / 768
    offset = (size[0] - 1024 * scale) / 2
    box = (
        round(offset + left * scale),
        round(top * scale),
        round(offset + (right - 1) * scale),
        round((bottom - 1) * scale),
    )
    draw.rectangle(box, fill="white")
    assert not green_indicator_visible(frame, region)
    draw.rectangle(box, fill="lime")
    assert green_indicator_visible(frame, region)
