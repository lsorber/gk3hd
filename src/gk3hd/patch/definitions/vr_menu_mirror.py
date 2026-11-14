"""Mirror qualified native menu crops without a second widget traversal."""

from __future__ import annotations

import struct

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.vr_menu_coverage import BODY_RECT, POPUP_RECT, POPUP_ROOT


def build_menu_cache_mirror(*, wrapper_va: int, state_va: int, toolbar: bool) -> bytes:
    """Copy only authored opaque regions, after native bindings are restored.

    Never copy the canvas or the bounding union's room-visible gaps. A failed
    copy returns false so the caller can redraw normally and withhold XR
    publication. Clip identical source/destination RECTs to the live canvas,
    without translating, scaling, changing colors or inventing transparency.
    Return boolean EAX and preserve all other registers and flags.
    """
    e = X86Emitter(base_va=wrapper_va)

    def state(opcode: bytes, offset: int, suffix: bytes = b"") -> None:
        e.raw(opcode + struct.pack("<I", state_va + offset) + suffix)

    e.raw(bytes.fromhex("9c 60"))
    state(b"\x8b\x35", 28)
    e.raw(bytes.fromhex("8b 5e 2c"))  # Validated original page, not the cache.
    for index, crop in enumerate((BODY_RECT, POPUP_RECT) if toolbar else (0x180,)):
        if index:
            state(b"\x83\x3d", POPUP_ROOT, b"\x00")
            e.jump_if(Condition.EQUAL, "accepted")
        state(b"\xbe", crop)
        state(b"\xbf", 0x1F0)
        e.raw(bytes.fromhex("b9 04 00 00 00 fc f3 a5"))
        for low, high, dimension in ((0, 8, 8), (4, 12, 12)):
            state(b"\xa1", 0x1F0 + low)
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.GREATER_OR_EQUAL, f"low-{index}-{low}")
            state(b"\xc7\x05", 0x1F0 + low, bytes(4))
            e.label(f"low-{index}-{low}")
            state(b"\xa1", 0x1F0 + high)
            state(b"\x3b\x05", dimension)
            e.jump_if(Condition.LESS_OR_EQUAL, f"high-{index}-{low}")
            state(b"\xa1", dimension)
            state(b"\xa3", 0x1F0 + high)
            e.label(f"high-{index}-{low}")
            state(b"\xa1", 0x1F0 + high)
            state(b"\x3b\x05", 0x1F0 + low)
            e.jump_if(Condition.LESS_OR_EQUAL, f"next-{index}")
        e.raw(bytes.fromhex("6a 00 68 00 00 00 01"))  # fx=null, DDBLT_WAIT
        state(b"\x68", 0x1F0)
        state(b"\xff\x35", 4)
        state(b"\x68", 0x1F0)
        e.raw(bytes.fromhex("53 8b 03 ff 50 14 85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "failed")
        e.label(f"next-{index}")
    e.label("accepted")
    e.raw(bytes.fromhex("c7 44 24 1c 01 00 00 00"))
    e.jump("return")
    e.label("failed")
    e.raw(bytes.fromhex("c7 44 24 1c 00 00 00 00"))
    e.label("return")
    e.raw(bytes.fromhex("61 9d c3"))
    return e.build()
