"""Read bounded native tracking feedback without mistaking it for session failure."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

TRACKING_FILE = "tracking-status.txt"
_STABLE_SECONDS = 1.0


class TrackingStatus(StrEnum):
    """Observed headset tracking, separate from runtime focus and controller readiness."""

    AVAILABLE = "tracked"
    UNAVAILABLE = "untracked"


def tracking_status(logs: Path) -> TrackingStatus | None:
    """Read only complete native records; an absent/partial file is unknown."""
    try:
        with (logs / TRACKING_FILE).open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            start = max(0, size - 64)
            stream.seek(start)
            data = stream.read(64)
    except OSError:
        return None
    if start:
        # The first bytes may be the tail of a record; never interpret them.
        data = data.partition(b"\n")[2]
    records = data.split(b"\n")[:-1]
    if not records:
        return None
    return {b"tracked": TrackingStatus.AVAILABLE, b"untracked": TrackingStatus.UNAVAILABLE}.get(
        records[-1].rstrip(b"\r")
    )


class TrackingFeedback:
    """Report sustained changes once, not startup jitter or every rendered frame."""

    def __init__(self, logs: Path, notify: Callable[[TrackingStatus], None]) -> None:
        """Retain this launch's unique log directory and CLI-owned output sink."""
        self._logs = logs
        self._notify = notify
        self._pending: TrackingStatus | None = None
        self._since = 0.0
        self._reported: TrackingStatus | None = None

    def poll(self, now: float) -> None:
        """Unknown observations reset debounce; they cannot establish recovery."""
        current = tracking_status(self._logs)
        if current is None or current != self._pending:
            self._pending = current
            self._since = now
            return
        if current != self._reported and now - self._since >= _STABLE_SECONDS:
            self._notify(current)
            self._reported = current
