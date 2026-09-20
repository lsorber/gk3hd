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


def hugging_face_progress_class(callback: DownloadProgress) -> type[Any]:
    """Return a silent tqdm-compatible class that forwards Hub byte counts."""

    class RichDownloadBridge:
        """Minimal context-managed progress object used by ``hf_hub_download``."""

        def __init__(
            self,
            *_args: object,
            desc: str | None = None,
            total: int | None = None,
            initial: int = 0,
            **_kwargs: object,
        ) -> None:
            self.description = desc or "model file"
            self.total = total
            self.completed = initial
            self.closed = False
            callback(self.description, self.completed, self.total)

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
            callback(self.description, self.completed, self.total)

        def close(self) -> None:
            """Mark the bridge closed; Rich owns the visible progress lifecycle."""
            self.closed = True

    return RichDownloadBridge
