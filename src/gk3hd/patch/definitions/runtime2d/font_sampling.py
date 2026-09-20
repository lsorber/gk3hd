"""Select font artwork from final transfer geometry, not the monitor size.

Native-size/offscreen draws retain source raster artwork. Enlarged draws use
the alternate artwork bank. Scope and temporary rectangles are call-local, so
nested font or unrelated native drawing cannot inherit an outer selection.
"""

from __future__ import annotations

import struct

from gk3hd.patch.binary.x86 import Condition, X86Emitter


def build_font_source_guard(*, base_va: int, active_handle_va: int, manager_va: int) -> bytes:
    """Admit only the scoped atlas surface, not nested alpha scratch transfers.

    ECX points to the final blitter's PUSHAD frame; source surface is at +24h.
    Use the live bitmap table without re-entering resource loading. Clobbers
    EAX/ECX/EDX only; return EAX=1 for the atlas, zero otherwise.
    """
    code = X86Emitter(base_va=base_va)
    reject = "reject"
    code.raw(bytes.fromhex("8b4924 85c9"))
    code.jump_if(Condition.EQUAL, reject)
    code.raw(b"\xa1" + struct.pack("<I", active_handle_va) + bytes.fromhex("85c0"))
    code.jump_if(Condition.EQUAL, reject)
    code.raw(bytes.fromhex("8b15") + struct.pack("<I", manager_va) + bytes.fromhex("85d2"))
    code.jump_if(Condition.EQUAL, reject)
    code.raw(bytes.fromhex("3b8224010000"))
    code.jump_if(Condition.ABOVE_OR_EQUAL, reject)
    for instruction in ("8b9220010000 85d2", "8b1482 85d2"):
        code.raw(bytes.fromhex(instruction))
        code.jump_if(Condition.EQUAL, reject)
    code.raw(bytes.fromhex("394a30"))
    code.jump_if(Condition.NOT_EQUAL, reject)
    code.raw(bytes.fromhex("b801000000 c3"))
    code.label(reject)
    code.raw(bytes.fromhex("31c0 c3"))
    return code.build()


def build_font_source_copy(*, base_va: int) -> bytes:
    """Receive a selected source RECT through the ordinary three-argument ABI.

    ECX is the constructor's private output RECT, not a surface. Reusing the
    same bank selector before alpha composition keeps density, clipping and
    geometry rules identical to opaque transfers. Native blending then uses
    this one rectangle for both color and its separate opacity image.
    """
    code = X86Emitter(base_va=base_va)
    code.raw(bytes.fromhex("8b44240c"))
    for offset in (0, 4, 8, 12):
        code.raw(bytes((0x8B, 0x50, offset, 0x89, 0x51, offset)))
    code.raw(bytes.fromhex("31c0 c20c00"))
    return code.build()


def build_font_scope(*, base_va: int, target_va: int, record_va: int, scope_va: int) -> bytes:
    """Bracket the five-argument font draw with its validated bank-cache entry.

    The resolver's fifth output is the cache entry. Clearing scope even on a
    failed resolution keeps nested non-bank fonts independent. Restore the outer
    scope, native EAX result, flags, registers and callee-cleanup convention.
    """
    code = X86Emitter(base_va=base_va)
    code.raw(bytes.fromhex("ff35") + struct.pack("<I", scope_va) + bytes.fromhex("9c60 83ec14"))
    code.raw(bytes.fromhex("c705") + struct.pack("<II", scope_va, 0))
    code.raw(bytes.fromhex("8b45ec 8d0c24"))
    code.call_absolute(record_va)
    code.raw(bytes.fromhex("85c0"))
    code.jump_if(Condition.EQUAL, "call")
    code.raw(bytes.fromhex("8b442410 a3") + struct.pack("<I", scope_va))
    code.label("call")
    code.raw(bytes.fromhex("83c414 619d") + bytes.fromhex("ff742418") * 5)
    code.call_absolute(target_va)
    code.raw(bytes.fromhex("870424 a3") + struct.pack("<I", scope_va) + bytes.fromhex("58 c21400"))
    return code.build()


def build_font_selector(*, base_va: int, native_va: int, scope_va: int, manager_va: int) -> bytes:
    """Delegate the final three-argument transfer using a stack-local source RECT.

    ECX is the destination surface; arguments are source surface, destination
    RECT and source RECT. Validate the live resource, paired geometry and bank
    bounds. Select alternate artwork only when neither axis shrinks below original size
    and at least one grows. A rejected transfer tail-delegates unchanged,
    including its return PC (needed by the console compositor's entry bridge).
    """
    code = X86Emitter(base_va=base_va)
    # Sixteen local RECT bytes, PUSHAD and flags; original args at 56/60/64.
    code.raw(bytes.fromhex("9c60 83ec10 8b1d") + struct.pack("<I", scope_va))
    code.raw(bytes.fromhex("85db"))
    code.jump_if(Condition.EQUAL, "native")
    for instruction in ("8b742438 85f6", "8b7c243c 85ff", "8b542440 85d2"):
        code.raw(bytes.fromhex(instruction))
        code.jump_if(Condition.EQUAL, "native")
    # Resolve current Resource.surface; never trust a cached surface pointer.
    code.raw(bytes.fromhex("a1") + struct.pack("<I", manager_va) + bytes.fromhex("85c0"))
    code.jump_if(Condition.EQUAL, "native")
    code.raw(bytes.fromhex("8b0b 85c9"))
    code.jump_if(Condition.EQUAL, "native")
    code.raw(bytes.fromhex("3b8824010000"))
    code.jump_if(Condition.ABOVE_OR_EQUAL, "native")
    for instruction in ("8b8020010000 85c0", "8b0488 85c0"):
        code.raw(bytes.fromhex(instruction))
        code.jump_if(Condition.EQUAL, "native")
    code.raw(bytes.fromhex("397030"))
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(bytes.fromhex("8b4304 c1e002 837b7c01"))
    code.jump_if(Condition.NOT_EQUAL, "surface_width")
    code.raw(bytes.fromhex("d1e0"))
    code.label("surface_width")
    code.raw(bytes.fromhex("394638"))
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(bytes.fromhex("8b4370 85c0"))
    code.jump_if(Condition.LESS_OR_EQUAL, "native")
    code.raw(bytes.fromhex("837b7c01"))
    code.jump_if(Condition.EQUAL, "row_surface")
    code.raw(bytes.fromhex("837b7c00"))
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(bytes.fromhex("8b4b08 c1e102 8d0441 39463c"))
    code.jump_if(Condition.NOT_EQUAL, "native")
    # Header or already-outline transfers must never receive another offset.
    code.raw(bytes.fromhex("833a00"))
    code.jump_if(Condition.LESS, "native")
    code.raw(bytes.fromhex("8b4208 3b4638"))
    code.jump_if(Condition.GREATER, "native")
    code.raw(bytes.fromhex("394a04"))
    code.jump_if(Condition.LESS, "native")
    code.raw(bytes.fromhex("034b70 394a0c"))
    code.jump_if(Condition.GREATER, "native")
    code.jump("geometry")
    code.label("row_surface")
    code.raw(bytes.fromhex("8b4378 c1e002 39463c"))
    code.jump_if(Condition.NOT_EQUAL, "native")
    # No padded-glyph translation: both atlas halves share the same row layout.
    code.raw(bytes.fromhex("833a00"))
    code.jump_if(Condition.LESS, "native")
    code.raw(bytes.fromhex("837a0400"))
    code.jump_if(Condition.LESS, "native")
    code.raw(bytes.fromhex("39420c"))
    code.jump_if(Condition.GREATER, "native")
    code.raw(bytes.fromhex("8b4b04 c1e102 394a08"))
    code.jump_if(Condition.GREATER, "native")
    code.raw(bytes.fromhex("394b70"))
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.label("geometry")
    code.raw(bytes.fromhex("31f6"))
    for first, last, axis in ((0, 8, "x"), (4, 12, "y")):
        code.raw(bytes((0x8B, 0x4A, last, 0x2B, 0x4A, first, 0x85, 0xC9)))
        code.jump_if(Condition.LESS_OR_EQUAL, "native")
        code.raw(bytes((0x8B, 0x47, last, 0x2B, 0x47, first, 0x85, 0xC0)))
        code.jump_if(Condition.LESS_OR_EQUAL, "native")
        code.raw(bytes.fromhex("3dffffff1f"))
        code.jump_if(Condition.ABOVE, "native")
        code.raw(bytes.fromhex("c1e002 39c8"))
        code.jump_if(Condition.BELOW, "native")
        code.jump_if(Condition.EQUAL, axis)
        code.raw(bytes.fromhex("be01000000"))
        code.label(axis)
    code.raw(bytes.fromhex("85f6"))
    code.jump_if(Condition.EQUAL, "native")
    for offset in (0, 4, 8, 12):
        code.raw(bytes((0x8B, 0x42, offset)))
        code.raw(bytes.fromhex("837b7c01"))
        code.jump_if(Condition.EQUAL, f"row_axis_{offset}")
        if offset in (4, 12):
            code.raw(bytes.fromhex("034370"))
        code.jump(f"axis_done_{offset}")
        code.label(f"row_axis_{offset}")
        if offset in (0, 8):
            code.raw(bytes.fromhex("034370"))
        code.label(f"axis_done_{offset}")
        code.raw(bytes((0x89, 0x44, 0x24, offset)))
    code.raw(bytes.fromhex("8d0424 50 ff742440 ff742440 8b4c2434"))
    code.call_absolute(native_va)
    code.raw(bytes.fromhex("8944242c 83c410 619d c20c00"))
    code.label("native")
    code.raw(bytes.fromhex("83c410 619d"))
    code.jump_absolute(native_va)
    return code.build()
