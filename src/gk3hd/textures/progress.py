"""Small progress values and adapters shared by texture workflows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Self

DownloadProgress = Callable[[str, int, int | None], None]


@dataclass(frozen=True, slots=True)
class TextureInstallProgress:
    """One phase-aware update from texture-pack installation."""

    description: str
    completed: int
    total: int | None
    unit: Literal["bytes", "items"] = "items"


TextureInstallProgressCallback = Callable[[TextureInstallProgress], None]


def report_install_progress(
    callback: TextureInstallProgressCallback | None,
    description: str,
    completed: int,
    total: int | None,
    *,
    unit: Literal["bytes", "items"] = "items",
) -> None:
    """Publish one install phase without coupling services to Rich."""
    if callback is not None:
        callback(TextureInstallProgress(description, completed, total, unit))


class _RichDownloadBridge:
    """Silent tqdm protocol for both HTTP and Xet model downloads."""

    def __init__(
        self, callback: DownloadProgress, description: str, total: int | None, initial: int
    ) -> None:
        self._callback = callback
        self.description = description
        self.total = total
        self.completed = initial
        self.transferred = 0
        self.closed = False
        self.refresh()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exception_type: object,
        _exception: object,
        _traceback: object,
    ) -> None:
        self.close()

    def update(self, amount: float | None = 1) -> None:
        """Forward an incremental byte count without rendering tqdm output."""
        if self.closed or amount is None:
            return
        self.completed += int(amount)
        self.refresh()

    @property
    def n(self) -> int:
        """Expose the tqdm counter used by Hub's Xet progress reporter."""
        return self.completed

    def update_transfer(self, amount: int) -> None:
        """Keep network bytes separate from reconstructed file progress.

        Xet may deduplicate or compress network traffic. Adding these bytes
        to file completion would count the same download twice.
        """
        self.transferred += amount

    def set_postfix_str(self, *_args: object, **_kwargs: object) -> None:
        """Ignore tqdm's speed label because Rich owns visible output."""

    def set_transfer_postfix_str(self, *_args: object, **_kwargs: object) -> None:
        """Ignore Xet's secondary speed label without printing it."""

    def refresh(self) -> None:
        """Forward a revised total without writing to the terminal."""
        if not self.closed:
            self._callback(self.description, self.completed, self.total)

    def close(self) -> None:
        """Mark the bridge closed; Rich owns the visible progress lifecycle."""
        self.closed = True


def hugging_face_progress_class(callback: DownloadProgress) -> type[Any]:
    """Return a silent tqdm-compatible class that forwards Hub byte counts."""

    class RichDownloadBridge(_RichDownloadBridge):
        """Bind one caller's progress callback without global logging state."""

        def __init__(
            self,
            *_args: object,
            desc: str | None = None,
            total: int | None = None,
            initial: int = 0,
            **_kwargs: object,
        ) -> None:
            super().__init__(callback, desc or "model file", total, initial)

    return RichDownloadBridge
