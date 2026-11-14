"""Native tracking feedback is bounded, debounced and independent of failure handling."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from gk3hd.vr.status import TRACKING_FILE, TrackingFeedback, TrackingStatus, tracking_status

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"", None),
        (b"tracked", None),
        (b"tracked\n", TrackingStatus.AVAILABLE),
        (b"untracked\r\n", TrackingStatus.UNAVAILABLE),
        (b"untracked\ntracked", TrackingStatus.UNAVAILABLE),
        (b"untracked\ntracked\n", TrackingStatus.AVAILABLE),
        (b"x" * 1000 + b"tracked\n", None),
        (b"untracked\n" * 1000 + b"tracked\n", TrackingStatus.AVAILABLE),
        (b"tracked\r\n" * 1000 + b"untracked\r\n", TrackingStatus.UNAVAILABLE),
        (b"tracked\nunknown\n", None),
    ],
)
def test_only_complete_recent_native_records_determine_tracking(
    tmp_path: Path, content: bytes, expected: TrackingStatus | None
) -> None:
    (tmp_path / TRACKING_FILE).write_bytes(content)
    assert tracking_status(tmp_path) is expected


def test_missing_or_unreadable_status_is_unknown(tmp_path: Path) -> None:
    assert tracking_status(tmp_path) is None
    (tmp_path / TRACKING_FILE).mkdir()
    assert tracking_status(tmp_path) is None


def test_stable_tracking_changes_are_reported_once(tmp_path: Path) -> None:
    events: list[TrackingStatus] = []
    feedback = TrackingFeedback(tmp_path, events.append)
    path = tmp_path / TRACKING_FILE
    path.write_bytes(b"untracked\n")
    feedback.poll(0)
    feedback.poll(0.5)
    assert not events
    feedback.poll(1)
    feedback.poll(2)
    assert events == [TrackingStatus.UNAVAILABLE]
    path.write_bytes(b"untracked\ntracked\n")
    feedback.poll(3)
    feedback.poll(4)
    feedback.poll(5)
    assert events == [TrackingStatus.UNAVAILABLE, TrackingStatus.AVAILABLE]


def test_brief_startup_tracking_loss_does_not_flash_a_warning(tmp_path: Path) -> None:
    events: list[TrackingStatus] = []
    feedback = TrackingFeedback(tmp_path, events.append)
    path = tmp_path / TRACKING_FILE
    path.write_bytes(b"untracked\n")
    feedback.poll(0)
    path.write_bytes(b"untracked\ntracked\n")
    feedback.poll(0.1)
    feedback.poll(1.2)
    assert events == [TrackingStatus.AVAILABLE]


def test_unknown_data_cannot_establish_or_replay_recovery(tmp_path: Path) -> None:
    events: list[TrackingStatus] = []
    feedback = TrackingFeedback(tmp_path, events.append)
    path = tmp_path / TRACKING_FILE
    path.write_bytes(b"untracked\n")
    feedback.poll(0)
    feedback.poll(1)
    path.write_bytes(b"tracked")
    feedback.poll(2)
    feedback.poll(100)
    assert events == [TrackingStatus.UNAVAILABLE]
    path.write_bytes(b"tracked\n")
    feedback.poll(101)
    assert events == [TrackingStatus.UNAVAILABLE]
    feedback.poll(102)
    assert events == [TrackingStatus.UNAVAILABLE, TrackingStatus.AVAILABLE]
