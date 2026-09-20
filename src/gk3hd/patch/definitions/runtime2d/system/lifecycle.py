"""Typed wrapper addresses shared by fixed-screen lifecycle owners."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScreenLifecycleTargets:
    """Wrapper addresses for one Draw/Show/Hide/destructor vtable family."""

    draw_va: int
    show_va: int
    hide_va: int
    destructor_va: int
