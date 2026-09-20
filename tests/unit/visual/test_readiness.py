"""Tests for GK3 visual readiness gates."""

import numpy as np
import pytest
from PIL import Image, ImageDraw

from tests.visual.support.readiness import (
    developer_console_visible,
    frame_mean_absolute_difference,
    restore_browser_visible,
    restore_dialog_visible,
    startup_escape_safe,
    timeblock_complete,
    title_play_center,
    title_ready,
    title_restore_center,
)


@pytest.mark.parametrize("size", [(1024, 768), (3840, 2160)])
def test_timeblock_requires_finished_label_and_controls(size: tuple[int, int]) -> None:
    frame = Image.new("RGB", (1024, 768), "black")
    draw = ImageDraw.Draw(frame)
    draw.rectangle((280, 460, 600, 479), fill="white")
    assert not timeblock_complete(frame)
    draw.rectangle((290, 590, 440, 612), fill=(190, 110, 40))
    draw.rectangle((570, 590, 680, 612), fill=(190, 110, 40))
    canvas = Image.new("RGB", size, "black")
    height = size[1]
    width = round(height * 4 / 3)
    canvas.paste(frame.resize((width, height)), ((size[0] - width) // 2, 0))
    assert timeblock_complete(canvas)
    draw.rectangle((280, 460, 600, 479), fill="black")
    draw.rectangle((280, 460, 310, 479), fill="white")
    assert not timeblock_complete(frame)  # Only the first word of the animation.


@pytest.mark.parametrize("size", [(1024, 768), (3840, 2160)])
def test_console_requires_a_wide_purple_band(size: tuple[int, int]) -> None:
    """Console survives resolution changes; isolated purple artwork does not match."""
    frame = Image.new("RGB", (1024, 768), "black")
    draw = ImageDraw.Draw(frame)
    draw.rectangle((48, 36, 660, 84), fill=(107, 4, 140))
    assert developer_console_visible(frame.resize(size))
    for rectangle in ((48, 36, 60, 84), (48, 300, 660, 348), (48, 36, 660, 37)):
        frame = Image.new("RGB", (1024, 768), "black")
        ImageDraw.Draw(frame).rectangle(rectangle, fill=(107, 4, 140))
        assert not developer_console_visible(frame.resize(size))


def test_restore_browser_requires_dark_canvas_gold_frame_and_material() -> None:
    frame = Image.new("RGB", (1024, 768), (0, 0, 0))
    pixels = np.asarray(frame).copy()
    pixels[180:650, 220:800] = (8, 8, 8)
    pixels[190:210, 220:800] = (130, 70, 20)
    pixels[630:650, 220:800] = (130, 70, 20)
    pixels[190:650, 220:240] = (130, 70, 20)
    pixels[190:650, 780:800] = (130, 70, 20)
    pixels[250:560, 260:700] = (20, 20, 20)
    browser = Image.fromarray(pixels, mode="RGB")

    assert restore_browser_visible(browser)
    assert not restore_browser_visible(Image.new("RGB", (3840, 2160), (0, 0, 0)))
    assert not restore_browser_visible(Image.new("RGB", (1024, 768), (120, 80, 20)))


def test_recognizes_four_aligned_title_buttons() -> None:
    frame = Image.new("RGB", (1024, 768), "black")
    draw = ImageDraw.Draw(frame)
    for left in (160, 360, 560, 760):
        draw.rectangle((left, 700, left + 80, 730), fill=(190, 110, 40))

    assert title_ready(frame)
    assert title_restore_center(frame) == (600, 715)
    assert title_play_center(frame) == (400, 715)
    assert title_play_center(Image.new("RGB", (1024, 768), "black")) is None


def test_rejects_logo_like_warm_art_above_title_band() -> None:
    frame = Image.new("RGB", (1024, 768), "black")
    ImageDraw.Draw(frame).rectangle((100, 200, 700, 500), fill=(190, 110, 40))

    assert not title_ready(frame)


def test_large_title_returns_coordinates_in_the_original_frame() -> None:
    frame = Image.new("RGB", (1024, 768), "black")
    draw = ImageDraw.Draw(frame)
    for left in (160, 360, 560, 760):
        draw.rectangle((left, 700, left + 80, 730), fill=(190, 110, 40))
    large = frame.resize((3840, 2160), Image.Resampling.NEAREST)
    center = title_restore_center(large)
    assert center is not None
    assert center[0] == pytest.approx(600 * 3840 / 1024, abs=4)
    assert center[1] == pytest.approx(715 * 2160 / 768, abs=4)


def test_startup_escape_requires_material_artwork() -> None:
    black = Image.new("RGB", (1024, 768), "black")
    cursor_only = black.copy()
    ImageDraw.Draw(cursor_only).rectangle((500, 380, 515, 395), fill="white")
    movie = black.copy()
    ImageDraw.Draw(movie).rectangle((200, 200, 800, 500), fill="white")

    assert not startup_escape_safe(black)
    assert not startup_escape_safe(cursor_only)
    assert startup_escape_safe(movie)


def test_frame_difference_reports_equal_and_changed_frames() -> None:
    black = Image.new("RGB", (8, 8), "black")
    white = Image.new("RGB", (8, 8), "white")

    assert frame_mean_absolute_difference(black, black) == 0.0
    assert frame_mean_absolute_difference(black, white) == 255.0


def test_restore_dialog_is_recognized_in_widescreen_capture() -> None:
    authored = Image.new("RGB", (1024, 768), (70, 90, 110))
    draw = ImageDraw.Draw(authored)
    draw.rectangle((210, 280, 814, 488), fill="black")
    draw.rectangle((216, 284, 808, 484), outline=(150, 80, 20), width=3)
    draw.rectangle((350, 315, 674, 345), fill=(150, 80, 20))
    draw.rectangle((256, 383, 770, 434), fill=(70, 70, 70), outline=(150, 80, 20), width=2)
    widescreen = Image.new("RGB", (1365, 768), "black")
    widescreen.paste(authored, (170, 0))
    uhd = widescreen.resize((3840, 2160), Image.Resampling.NEAREST)

    assert restore_dialog_visible(authored)
    assert restore_dialog_visible(uhd)
    assert not restore_dialog_visible(Image.new("RGB", (3840, 2160), (70, 90, 110)))
