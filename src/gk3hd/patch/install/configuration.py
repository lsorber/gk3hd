"""Interfaces for transactional installation configuration."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path

    from gk3hd.patch.manifest import ExternalChange
    from gk3hd.patch.model import PatchId


class GraphicsBackend(StrEnum):
    """Presentation implementation selected independently of executable patches."""

    NATIVE = "native"
    D7VK = "d7vk"


class InstallConfiguration(Protocol):
    """Manage non-executable state changed by a patch installation."""

    def prepare(
        self,
        *,
        exe: Path,
        width: int,
        height: int,
        patches: tuple[PatchId, ...],
        graphics_backend: GraphicsBackend = GraphicsBackend.NATIVE,
    ) -> tuple[ExternalChange, ...]:
        """Describe desired changes without mutating external state."""
        ...

    def apply(self, *, exe: Path, changes: tuple[ExternalChange, ...]) -> None:
        """Apply changes only when their captured prior values still match."""
        ...

    def verify(self, *, exe: Path, changes: tuple[ExternalChange, ...]) -> None:
        """Verify every external value still equals its installed value."""
        ...

    def rollback(self, *, exe: Path, changes: tuple[ExternalChange, ...]) -> None:
        """Restore captured prior values without a user-change guard."""
        ...

    def recover_interrupted_apply(
        self,
        *,
        exe: Path,
        changes: tuple[ExternalChange, ...],
    ) -> None:
        """Restore prior values only from recognizable partial apply states."""
        ...

    def restore(
        self,
        *,
        exe: Path,
        changes: tuple[ExternalChange, ...],
        force: bool,
    ) -> None:
        """Restore prior values, protecting changes made after installation."""
        ...

    def reinstall(self, *, exe: Path, changes: tuple[ExternalChange, ...]) -> None:
        """Reapply installed values while rolling back a failed restore."""
        ...


class NoopConfiguration:
    """Provide a side-effect-free adapter for portable and isolated tests."""

    def prepare(
        self,
        *,
        exe: Path,
        width: int,
        height: int,
        patches: tuple[PatchId, ...],
        graphics_backend: GraphicsBackend = GraphicsBackend.NATIVE,
    ) -> tuple[ExternalChange, ...]:
        """Return no changes."""
        del exe, width, height, patches, graphics_backend
        return ()

    def apply(self, *, exe: Path, changes: tuple[ExternalChange, ...]) -> None:
        """Accept an empty change set."""
        del exe
        self._require_empty(changes)

    def verify(self, *, exe: Path, changes: tuple[ExternalChange, ...]) -> None:
        """Accept an empty change set."""
        del exe
        self._require_empty(changes)

    def rollback(self, *, exe: Path, changes: tuple[ExternalChange, ...]) -> None:
        """Accept an empty change set."""
        del exe
        self._require_empty(changes)

    def recover_interrupted_apply(
        self,
        *,
        exe: Path,
        changes: tuple[ExternalChange, ...],
    ) -> None:
        """Accept an empty interrupted-install change set."""
        del exe
        self._require_empty(changes)

    def restore(
        self,
        *,
        exe: Path,
        changes: tuple[ExternalChange, ...],
        force: bool,
    ) -> None:
        """Accept an empty change set."""
        del exe, force
        self._require_empty(changes)

    def reinstall(self, *, exe: Path, changes: tuple[ExternalChange, ...]) -> None:
        """Accept an empty change set."""
        del exe
        self._require_empty(changes)

    @staticmethod
    def _require_empty(changes: tuple[ExternalChange, ...]) -> None:
        if changes:
            msg = "the no-op configuration adapter cannot manage external changes"
            raise ValueError(msg)
