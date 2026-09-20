"""Use SIDNEY's detailed cartography without changing its puzzle coordinates."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from gk3hd.patch.binary.x86 import Condition

if TYPE_CHECKING:
    from gk3hd.patch.binary.x86 import X86Emitter


def _find_map(code: X86Emitter, *, name: bytes, manager_va: int, source: bool) -> None:
    """Find an exact live resource; reject reused surfaces and name prefixes."""
    loop = name.decode() + "_loop"
    code.raw(b"\x8b\x3d" + struct.pack("<I", manager_va) + b"\x85\xff")
    code.jump_if(Condition.EQUAL, "map_done")
    code.raw(b"\x8b\x8f\x24\x01\x00\x00\x8b\xbf\x20\x01\x00\x00\x85\xff")
    code.jump_if(Condition.EQUAL, "map_done")
    code.label(loop)
    code.raw(b"\x85\xc9")
    code.jump_if(Condition.EQUAL, "map_done")
    code.raw(b"\x8b\x37\x83\xc7\x04\x49\x85\xf6")
    code.jump_short_if(Condition.EQUAL, loop)
    if source:
        code.raw(b"\x39\x56\x30")  # Must own the current source surface in EDX.
        code.jump_short_if(Condition.NOT_EQUAL, loop)
    whole = len(name) // 4 * 4
    for offset in range(0, whole, 4):
        code.raw(b"\x8b\x46" + bytes([8 + offset]) + b"\x0d\x20\x20\x20\x20\x3d")
        code.raw(name[offset : offset + 4])
        code.jump_short_if(Condition.NOT_EQUAL, loop)
    for offset in range(whole, len(name)):
        code.raw(b"\x8a\x46" + bytes([8 + offset]) + b"\x0c\x20\x3c" + name[offset : offset + 1])
        code.jump_short_if(Condition.NOT_EQUAL, loop)
    code.raw(b"\x80\x7e" + bytes([8 + len(name), 0]))
    code.jump_short_if(Condition.NOT_EQUAL, loop)


def emit_overview_source(
    code: X86Emitter, *, scratch_va: int, manager_va: int, dimensions_va: int
) -> None:
    """Select dense BIG for dense LITTLE only on an enlarged physical screen.

    The generic source helper already validated the logical caller and made a
    private 4x RECT. It owns PUSHAD, with EBP pointing at native blit arguments.
    The authored overview and detail carry 1x and 4x information respectively.
    Choose the nearest level in log space: below 2x display scale keep the
    prefiltered overview, otherwise share the detailed original. This avoids
    aliasing the detailed map back down at reference or near-reference sizes.
    There is no extra asset,
    invented labels, persistent pointer cache, or puzzle-coordinate edit.
    """
    code.raw(b"\x81\x3d" + struct.pack("<II", dimensions_va + 4, 1536))
    code.jump_if(Condition.BELOW, "map_done")
    code.raw(b"\x8b\x44\x24\x18")  # Saved ECX: destination surface.
    for offset, address in ((0x38, dimensions_va), (0x3C, dimensions_va + 4)):
        code.raw(b"\x8b\x15" + struct.pack("<I", address) + b"\x39\x50" + bytes([offset]))
        code.jump_if(Condition.NOT_EQUAL, "map_done")
    code.raw(b"\x8b\x55\x04")
    for offset in (0x38, 0x3C):
        code.raw(b"\x81\x7a" + bytes([offset]) + struct.pack("<I", 1368))
        code.jump_if(Condition.NOT_EQUAL, "map_done")
    _find_map(code, name=b"sidneylittlemap", manager_va=manager_va, source=True)
    _find_map(code, name=b"sidneybigmap", manager_va=manager_va, source=False)
    code.raw(b"\x8b\x46\x30\x85\xc0")
    code.jump_if(Condition.EQUAL, "map_done")
    for offset in (0x38, 0x3C):
        code.raw(b"\x81\x78" + bytes([offset]) + struct.pack("<I", 5472))
        code.jump_if(Condition.NOT_EQUAL, "map_done")
    code.raw(b"\x89\x45\x04")
    for offset in range(0, 16, 4):
        code.raw(b"\xc1\x25" + struct.pack("<I", scratch_va + offset) + b"\x02")
    code.label("map_done")
