"""Windows SIDNEY automation must reject cursor-only changes."""

from unittest.mock import Mock

import pytest
from PIL import Image, ImageDraw

from tests.visual.support import sidney


def test_page_readiness_requires_content_change(monkeypatch: pytest.MonkeyPatch) -> None:
    original = Image.new("RGB", (1024, 768), "black")
    cursor = original.copy()
    ImageDraw.Draw(cursor).rectangle((232, 172, 240, 182), fill="white")
    monkeypatch.setattr(sidney.time, "monotonic", Mock(side_effect=[0, 0, 6]))
    with pytest.raises(sidney.CaptureError, match="application content"):
        sidney.wait_for_page(Mock(return_value=cursor), original)


def test_page_readiness_advances_after_stable_content() -> None:
    original = Image.new("RGB", (1024, 768), "black")
    page = original.copy()
    ImageDraw.Draw(page).rectangle((300, 250, 700, 450), fill="goldenrod")
    grab = Mock(side_effect=[page, page])
    assert sidney.wait_for_page(grab, original) is page
    assert grab.call_count == 2


@pytest.mark.parametrize(("page", "row"), [("analyze", 257), ("translate", None)])
def test_document_views_do_not_open_an_image_in_translation(
    monkeypatch: pytest.MonkeyPatch, page: str, row: int | None
) -> None:
    frame = Image.new("RGB", (1024, 768))
    browser = Mock(return_value=frame)
    grab = Mock()
    monkeypatch.setattr(sidney, "_open_file", browser)
    assert sidney._page_content(page, 123, grab, frame.size, frame) is frame
    browser.assert_called_once_with(123, grab, frame.size, row=row)


def test_capture_parks_cursor_and_waits_for_three_lit_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = Image.new("RGB", (1024, 768))
    move = Mock()
    monkeypatch.setattr(sidney, "move_frame_point", move)
    phase = Mock(side_effect=[False, True, False, True, True, True])
    monkeypatch.setattr(sidney, "green_indicator_visible", phase)
    grab = Mock(return_value=frame)
    assert sidney._settle_capture(1, grab, frame.size, notice=True) is frame
    move.assert_called_once_with(1, 840, 620, frame_size=frame.size)
    assert grab.call_count == 6


def test_missing_email_indicator_fails_instead_of_saving_wrong_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sidney, "move_frame_point", Mock())
    monkeypatch.setattr(sidney.time, "monotonic", Mock(side_effect=[0, 6]))
    with pytest.raises(sidney.CaptureError, match="new-email"):
        sidney._settle_capture(1, Mock(), (1024, 768), notice=True)
