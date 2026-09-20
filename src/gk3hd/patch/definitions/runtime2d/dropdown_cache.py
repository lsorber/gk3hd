"""Adapt SIDNEY dropdown headings to the shared native/dense text cache."""

from __future__ import annotations

from dataclasses import dataclass

from gk3hd.patch.binary.x86 import X86Emitter


@dataclass(frozen=True, slots=True)
class DropdownCacheRuntime:
    """Keep both enabled/disabled native handles authoritative for the widget."""

    base_va: int

    def entry(self) -> bytes:
        """Compose each state through the same bounded ownership/lifetime table."""
        code = X86Emitter(base_va=self.base_va + 0x3500)
        code.raw(bytes.fromhex("56 89ce"))
        for offset in (0x60, 0x64):
            code.raw(bytes((0x6A, offset, 0x8D, 0x46, offset, 0x50)) + bytes.fromhex("89f1"))
            code.call_absolute(self.base_va + 0x3100)
        code.raw(bytes.fromhex("5e c3"))
        return code.build()

    def paint_bridge(self) -> bytes:
        """Temporarily select one backing; restore the native field and result.

        The original painter composes both states at once. Only the selected
        dense handle is in construction scope; its sibling remains native.
        The widget's size, position, enabled state and hit bounds never change.
        """
        code = X86Emitter(base_va=self.base_va + 0x3600)
        code.raw(bytes.fromhex("558bec83ec08 53 8b450c 8d1c01 8b03 8945fc 8b5508 8b02 8903"))
        code.call_absolute(self.base_va + 0x3700)
        code.raw(bytes.fromhex("8945f8 8b45fc 8903 8b45f8 5b c9 c20800"))
        return code.build()
