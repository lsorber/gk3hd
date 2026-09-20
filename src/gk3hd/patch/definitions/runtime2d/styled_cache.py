"""Adapt styled text to the shared native/dense cache ownership protocol."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.layout import (
    FONT_BANK_ALPHA_SELECT_OFFSET,
    FONT_BANK_SEGMENT,
    INVENTORY_ALPHA_HEIGHT_OFFSET,
    INVENTORY_ALPHA_OUTPUT_RECT_OFFSET,
    INVENTORY_ALPHA_SOURCE_RECT_OFFSET,
    INVENTORY_ALPHA_WIDTH_OFFSET,
    INVENTORY_FONT_ALPHA_VTABLE_OFFSET,
    INVENTORY_SEGMENT,
)

if TYPE_CHECKING:
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols


def _u(value: int) -> bytes:
    return struct.pack("<I", value)


@dataclass(frozen=True, slots=True)
class StyledTextCacheRuntime:
    """Keep span layout logical while composing its 4x bitmap, including alpha."""

    base_va: int
    active_surface_va: int
    profile: BuildProfile
    symbols: RuntimeSymbols

    def entry(self) -> bytes:
        """Adapt the by-value native handle to an owner-keyed shared cache paint."""
        code = X86Emitter(base_va=self.base_va + 0x40)
        # Native owner + 0x74 is the cache handle. Its dimensions, dirty flag,
        # span layout, clipping and eventual destruction remain game-owned.
        code.raw(bytes.fromhex("6a00 8d4174 50"))
        code.call_absolute(self.base_va + 0x500)
        code.raw(bytes.fromhex("c20400"))
        return code.build()

    def paint_bridge(self) -> bytes:
        """Initialize either backing exactly as the native span painter expects."""
        code = X86Emitter(base_va=self.base_va + 0x2600)
        code.raw(
            bytes.fromhex("558bec 51 8b4508 8b00 680000803f 6a00 6a00 50 8b0d")
            + _u(self.profile.address("engine.loop"))
        )
        code.call_absolute(self.profile.address("runtime2d.fill_rect"))
        code.raw(bytes.fromhex("8b4508 ff30 8b4dfc"))
        code.call_absolute(self.profile.address("sprite_cache.styled_paint"))
        code.raw(bytes.fromhex("c9 c20800"))
        return code.build()

    def alpha_constructor(self) -> bytes:
        """Enlarge cache glyphs before software composition loses source detail.

        The ordinary font dispatcher already made source rectangles physical.
        BitmapManager already scaled destination origins; grow only extents.
        Native atlases need the same destination growth, not a source transform.
        GK3's existing software sampler owns clipping and the actual blend.
        """
        base = self.base_va
        inventory = self.symbols.va(INVENTORY_SEGMENT.logical_name)
        selector = self.symbols.va(FONT_BANK_SEGMENT.logical_name, FONT_BANK_ALPHA_SELECT_OFFSET)
        code = X86Emitter(base_va=base + 0x2200)
        code.raw(bytes.fromhex("9c60 83ec20 a1") + _u(self.active_surface_va))
        code.raw(bytes.fromhex("85c0"))
        code.jump_if(Condition.EQUAL, "native")
        code.raw(bytes.fromhex("3b442448"))
        code.jump_if(Condition.NOT_EQUAL, "native")
        # Two caller-owned RECTs become call-local copies. Nothing outside the
        # currently composed cache is transformed by this adapter.
        for argument in (0x50, 0x54):
            code.raw(bytes((0x83, 0x7C, 0x24, argument, 0)))
            code.jump_if(Condition.EQUAL, "native")
        code.raw(bytes.fromhex("fc 8b742450 8d3c24 b904000000 f3a5"))
        code.raw(bytes.fromhex("8b742454 8d7c2410 b904000000 f3a5"))
        for far, near in ((8, 0), (12, 4)):
            code.raw(bytes((0x8B, 0x44, 0x24, far, 0x2B, 0x44, 0x24, near)))
            code.raw(bytes.fromhex("c1e002"))
            code.raw(bytes((0x03, 0x44, 0x24, near, 0x89, 0x44, 0x24, far)))
        # Re-select the paired artwork now that the final destination is known.
        code.raw(bytes.fromhex("8d4c2410 8d0424 51 50 ff742454"))
        code.call_absolute(selector)
        # The pixel callback must consume precisely these physical extents.
        # Constructor-only changes leave stale dimensions and can overrun its
        # scratch image. This synchronous record is shared with the font path.
        for local, field in (
            (0, INVENTORY_ALPHA_OUTPUT_RECT_OFFSET),
            (16, INVENTORY_ALPHA_SOURCE_RECT_OFFSET),
        ):
            code.raw(bytes((0x8D, 0x74, 0x24, local)) + b"\xbf" + _u(inventory + field))
            code.raw(bytes.fromhex("b904000000 f3a5"))
        for far, near, field in (
            (8, 0, INVENTORY_ALPHA_WIDTH_OFFSET),
            (12, 4, INVENTORY_ALPHA_HEIGHT_OFFSET),
        ):
            code.raw(bytes((0x8B, 0x44, 0x24, far, 0x2B, 0x44, 0x24, near)))
            code.raw(b"\xa3" + _u(inventory + field))
        code.raw(bytes.fromhex("ff742458 8d442414 50 8d442408 50 ff742458 ff742458 8b4c244c"))
        code.call_absolute(base + 0x2880)
        code.raw(
            bytes.fromhex("8b542438 c702") + _u(inventory + INVENTORY_FONT_ALPHA_VTABLE_OFFSET)
        )
        code.raw(bytes.fromhex("8944243c 83c420 619d c21400"))
        code.label("native")
        code.raw(bytes.fromhex("83c420 619d"))
        code.jump_absolute(base + 0x2880)
        return code.build()
