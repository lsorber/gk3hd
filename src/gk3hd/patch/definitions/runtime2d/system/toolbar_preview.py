"""Keep the toolbar's selected-item thumbnail logical while sampling dense art."""

from __future__ import annotations

import struct

from gk3hd.patch.binary.x86 import Condition, X86Emitter


def build_preview_prepare(
    *, wrapper_va: int, surface_va: int, manager_va: int, resolve_va: int
) -> bytes:
    """Normalize only the embedded selected-item control before root clipping.

    ECX is InGameToolbar. Its embedded BitmapButton at +0xAC8 keeps an
    encoded bitmap handle at +0x2C. Resolve that exact resource; dimensions
    distinguish native thumbnails from their fourfold replacements, not owner.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x60\x31\xc0\xa3" + struct.pack("<I", surface_va))
    code.raw(b"\x8d\xb1\xc8\x0a\x00\x00")
    code.raw(b"\x8b\x46\x2c\x85\xc0")
    code.jump_if(Condition.EQUAL, "done")
    code.raw(b"\x50\x8b\x0d" + struct.pack("<I", manager_va))
    code.call_absolute(resolve_va)
    code.raw(b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "done")
    code.raw(b"\x8b\x40\x30\x85\xc0")
    code.jump_if(Condition.EQUAL, "done")
    code.raw(b"\x8b\x48\x38\x8b\x50\x3c")
    code.raw(b"\x81\xf9\x80\x00\x00\x00")
    code.jump_short_if(Condition.NOT_EQUAL, "portrait")
    code.raw(b"\x83\xfa\x78")
    code.jump_short_if(Condition.EQUAL, "dense")
    code.raw(b"\x83\xfa\x7c")
    code.jump_short_if(Condition.EQUAL, "dense")
    code.raw(b"\x81\xfa\x80\x00\x00\x00")
    code.jump_short_if(Condition.EQUAL, "dense")
    code.jump_short("done")
    code.label("portrait")
    code.raw(b"\x83\xf9\x78")
    code.jump_short_if(Condition.NOT_EQUAL, "done")
    code.raw(b"\x81\xfa\x80\x00\x00\x00")
    code.jump_short_if(Condition.NOT_EQUAL, "done")
    code.label("dense")
    code.raw(b"\xa3" + struct.pack("<I", surface_va))
    code.raw(b"\xc1\xe9\x02\xc1\xea\x02")
    code.raw(b"\x03\x4e\x1c\x03\x56\x20\x89\x4e\x24\x89\x56\x28")
    code.label("done")
    code.raw(b"\x61\xc3")
    return code.build()


def emit_preview_source(code: X86Emitter, *, surface_va: int, scratch_va: int) -> None:
    """Map clipped source coordinates for the exact prepared preview resource.

    EBP is the outer blitter's PUSHAD frame. The destination is already in
    logical toolbar space; only source sampling becomes fourfold. A null source
    RECT already means the complete physical bitmap and needs no adjustment.
    """
    code.raw(b"\xa1" + struct.pack("<I", surface_va) + b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "preview_source_done")
    code.raw(b"\x3b\x45\x24")
    code.jump_if(Condition.NOT_EQUAL, "preview_source_done")
    code.raw(b"\x8b\x7d\x2c\x85\xff")
    code.jump_if(Condition.EQUAL, "preview_source_done")
    for offset in range(0, 16, 4):
        code.raw(b"\x8b\x47" + bytes([offset]) + b"\xc1\xe0\x02")
        code.raw(b"\xa3" + struct.pack("<I", scratch_va + offset))
    code.raw(b"\xc7\x45\x2c" + struct.pack("<I", scratch_va))
    code.label("preview_source_done")


def emit_preview_dimensions(
    code: X86Emitter, *, surface_va: int, logical_va: int, root_va: int, vtable_va: int
) -> None:
    """Return logical dimensions only for the active toolbar's exact preview.

    EAX is the resolved surface at the shared GetDimensions tail. On a match,
    jump to its register-restoring epilogue with a private dimension pair;
    otherwise leave EAX unchanged for the other resource policies.
    """
    code.raw(b"\x3b\x05" + struct.pack("<I", surface_va))
    code.jump_if(Condition.NOT_EQUAL, "preview_dimensions_done")
    code.raw(b"\x8b\x0d" + struct.pack("<I", root_va) + b"\x85\xc9")
    code.jump_if(Condition.EQUAL, "preview_dimensions_done")
    code.raw(b"\x81\x39" + struct.pack("<I", vtable_va))
    code.jump_if(Condition.NOT_EQUAL, "preview_dimensions_done")
    for offset, destination in ((0x38, logical_va), (0x3C, logical_va + 4)):
        code.raw(b"\x8b\x50" + bytes([offset]))
        code.raw(b"\xc1\xfa\x02\x89\x15" + struct.pack("<I", destination))
    code.raw(b"\xb8" + struct.pack("<I", logical_va))
    code.jump("done")
    code.label("preview_dimensions_done")
