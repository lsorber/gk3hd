"""Fit SIDNEY's software-blended draws through the shared native compositor."""

from __future__ import annotations

import struct

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.geometry import AUTHORED_FRAME_HEIGHT, AUTHORED_FRAME_WIDTH


def build_alpha_wrapper(
    *,
    wrapper_va: int,
    target_va: int,
    active_depth_va: int,
    hud_font_active_va: int,
    physical_width_va: int,
    cursor_classifier_va: int,
) -> bytes:
    """Map a framebuffer-owned effect without changing its blend or source.

    Software effects bypass the final DirectDraw blitter. Their constructor
    therefore needs the same fitted anchor as SIDNEY's ordinary bitmap path.
    The existing compositor scales the extent and delegates pixels to GK3's
    native blend callback. Keep the RECT stack-local and preserve its source,
    options, constructor result, and the caller's glyph scope. Offscreen work,
    cursor transactions and already-mapped HUD glyphs must remain untouched.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x83\x3d" + struct.pack("<I", active_depth_va) + b"\x00")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x83\x3d" + struct.pack("<I", hud_font_active_va) + b"\x00")
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(b"\x81\x3d" + struct.pack("<I", physical_width_va + 4))
    code.raw(struct.pack("<I", AUTHORED_FRAME_HEIGHT))
    code.jump_if(Condition.BELOW, "native")
    code.jump_if(Condition.NOT_EQUAL, "fit")
    code.raw(b"\x81\x3d" + struct.pack("<I", physical_width_va))
    code.raw(struct.pack("<I", AUTHORED_FRAME_WIDTH))
    code.jump_if(Condition.EQUAL, "native")
    code.label("fit")
    # Locals:16-byte output RECT. PUSHAD preserves constructor ECX and all
    # nonvolatile registers while validating the original five arguments.
    code.raw(b"\x83\xec\x10\x60\x8b\x4c\x24\x34\x85\xc9")
    code.jump_if(Condition.EQUAL, "unwind")
    for offset, address in ((0x38, physical_width_va), (0x3C, physical_width_va + 4)):
        code.raw(b"\x8b\x41" + bytes([offset]) + b"\x3b\x05" + struct.pack("<I", address))
        code.jump_if(Condition.NOT_EQUAL, "unwind")
    code.raw(b"\x8b\x54\x24\x38\x8b\x74\x24\x3c\x85\xf6")
    code.jump_if(Condition.EQUAL, "unwind")
    code.call_absolute(cursor_classifier_va)
    code.raw(b"\x85\xc0")
    code.jump_if(Condition.NOT_EQUAL, "unwind")
    # The classifier may clobber every register; reload the source RECT.
    code.raw(b"\x8b\x74\x24\x3c\x8d\x7c\x24\x20\xfc")
    code.raw(b"\xb9\x04\x00\x00\x00\xf3\xa5")
    for horizontal, first, last in ((True, 0x20, 0x28), (False, 0x24, 0x2C)):
        code.raw(b"\x8b\x44\x24" + bytes([first]) + b"\x8b\xf0\x0f\xaf\x05")
        code.raw(struct.pack("<I", physical_width_va + 4))
        code.raw(b"\x99\xb9" + struct.pack("<I", AUTHORED_FRAME_HEIGHT) + b"\xf7\xf9")
        if horizontal:
            code.raw(b"\x50\xa1" + struct.pack("<I", physical_width_va + 4))
            code.raw(b"\xc1\xe0\x0a\x99\xf7\xf9\x8b\x15")
            code.raw(struct.pack("<I", physical_width_va))
            code.raw(b"\x2b\xd0\xd1\xfa\x58\x03\xc2")
        code.raw(b"\x2b\xc6\x01\x44\x24" + bytes([first]))
        code.raw(b"\x01\x44\x24" + bytes([last]))
    # The anchor above is already fitted. Mode 2 scales only local extents;
    # mode 1 belongs to room-status glyphs and requires their authored point.
    # Reusing that mode here consumes a stale HUD point and can invert RECTs.
    code.raw(b"\x61\xc7\x05" + struct.pack("<I", hud_font_active_va) + b"\x02\x00\x00\x00")
    # Retain EAX while using it to address the local RECT. The target consumes
    # only the five copied arguments; its returned EAX is the live effect.
    code.raw(b"\x50\x8d\x44\x24\x04\xff\x74\x24\x28\xff\x74\x24\x28\x50")
    code.raw(b"\xff\x74\x24\x28\xff\x74\x24\x28")
    code.call_absolute(target_va)
    code.raw(b"\x83\xc4\x04\xc7\x05" + struct.pack("<I", hud_font_active_va) + bytes(4))
    code.raw(b"\x83\xc4\x10\xc2\x14\x00")
    code.label("unwind")
    code.raw(b"\x61\x83\xc4\x10")
    code.label("native")
    code.jump_absolute(target_va)
    return code.build()


def build_caret_wrapper(
    *,
    wrapper_va: int,
    target_va: int,
    resolve_bitmap_va: int,
    active_depth_va: int,
    physical_width_va: int,
    save_text_active_va: int = 0,
    save_edit_vtable_va: int = 0,
    save_point_helper_va: int = 0,
) -> bytes:
    """Fit the native EditBox caret's GDI RECT, which also bypasses Blt."""
    code = X86Emitter(base_va=wrapper_va)
    if save_text_active_va:
        # SaveGame's editor has a physical anchor and native local metrics.
        # It must not use SIDNEY's authored full-screen affine.
        code.raw(b"\x50\xa1" + struct.pack("<I", save_text_active_va) + b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "not_save")
        code.raw(b"\x81\x38" + struct.pack("<I", save_edit_vtable_va))
        code.jump_if(Condition.NOT_EQUAL, "not_save")
        code.raw(b"\x58\x83\xec\x10\x60\x8b\x74\x24\x40\x85\xf6")
        code.jump_if(Condition.EQUAL, "unwind")
        code.raw(b"\x8d\x7c\x24\x20\xfc\xb9\x04\x00\x00\x00\xf3\xa5")
        code.raw(b"\x8d\x4c\x24\x20")
        code.call_absolute(save_point_helper_va)
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "unwind")
        code.raw(b"\x8d\x4c\x24\x28")
        code.call_absolute(save_point_helper_va)
        code.jump("submit")
        code.label("not_save")
        code.raw(b"\x58")
    code.raw(b"\x83\x3d" + struct.pack("<I", active_depth_va) + b"\x00")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x81\x3d" + struct.pack("<I", physical_width_va + 4))
    code.raw(struct.pack("<I", AUTHORED_FRAME_HEIGHT))
    code.jump_if(Condition.BELOW, "native")
    code.raw(b"\x83\xec\x10\x60\x8b\x74\x24\x40\x85\xf6")
    code.jump_if(Condition.EQUAL, "unwind")
    # Resolve the encoded destination with the same BitmapManager used by
    # native FillRectangle. Only the actual physical framebuffer is fitted.
    code.raw(b"\xff\x74\x24\x34")
    code.call_absolute(resolve_bitmap_va)
    code.raw(b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "unwind")
    code.raw(b"\x8b\x40\x30\x85\xc0")
    code.jump_if(Condition.EQUAL, "unwind")
    for offset, address in ((0x38, physical_width_va), (0x3C, physical_width_va + 4)):
        code.raw(b"\x8b\x50" + bytes([offset]) + b"\x3b\x15" + struct.pack("<I", address))
        code.jump_if(Condition.NOT_EQUAL, "unwind")
    # Compute horizontal letterbox offset once. All four RECT edges use the
    # same integer affine; preserve both original color arguments verbatim.
    code.raw(b"\xa1" + struct.pack("<I", physical_width_va + 4))
    code.raw(b"\xc1\xe0\x0a\x99\xb9" + struct.pack("<I", AUTHORED_FRAME_HEIGHT))
    code.raw(b"\xf7\xf9\x8b\x1d" + struct.pack("<I", physical_width_va))
    code.raw(b"\x2b\xd8\xd1\xfb\x8b\x74\x24\x40")
    for offset in range(0, 16, 4):
        code.raw(b"\x8b\x46" + bytes([offset]) + b"\x0f\xaf\x05")
        code.raw(struct.pack("<I", physical_width_va + 4) + b"\x99\xf7\xf9")
        if offset % 8 == 0:
            code.raw(b"\x03\xc3")
        code.raw(b"\x89\x44\x24" + bytes([0x20 + offset]))
    code.label("submit")
    code.raw(b"\x61\x50\x8d\x44\x24\x04\x50")
    code.raw(b"\xff\x74\x24\x24" * 3)
    code.call_absolute(target_va)
    code.raw(b"\x83\xc4\x14\xc2\x10\x00")
    code.label("unwind")
    code.raw(b"\x61\x83\xc4\x10")
    code.label("native")
    code.jump_absolute(target_va)
    return code.build()


def build_solid_fill_wrapper(
    *, wrapper_va: int, target_va: int, active_depth_va: int, physical_width_va: int
) -> bytes:
    """Fit SIDNEY framebuffer fills without changing color or blend options.

    Frame headers and footers fill directly through Bitmap::Fill, bypassing
    the fitted bitmap blitter. Only their framebuffer-owned RECT is authored;
    offscreen backgrounds and scrollbar textures keep native coordinates.
    A null RECT still means a complete native clear. The three-argument thiscall
    receives color, RECT*, and blend options; all caller storage is preserved.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x83\x3d" + struct.pack("<I", active_depth_va) + b"\x00")
    code.jump_if(Condition.EQUAL, "native")
    for offset, address in ((0x38, physical_width_va), (0x3C, physical_width_va + 4)):
        code.raw(b"\xa1" + struct.pack("<I", address) + b"\x39\x41" + bytes([offset]))
        code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(b"\x83\x7c\x24\x08\x00")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x83\xec\x10\x60\x8b\x74\x24\x38\x8d\x7c\x24\x20")
    code.raw(b"\xfc\xb9\x04\x00\x00\x00\xf3\xa5\x8d\x74\x24\x20")
    # Same edge rounding and integer pillar offset as the final SIDNEY Blt.
    code.raw(b"\x8b\x1d" + struct.pack("<I", physical_width_va + 4))
    code.raw(b"\x8b\xc3\xc1\xe0\x02\x99\xbf\x03\x00\x00\x00\xf7\xff")
    code.raw(b"\x8b\x2d" + struct.pack("<I", physical_width_va) + b"\x2b\xe8\xd1\xfd")
    code.raw(b"\xb9\x00\x03\x00\x00\xbf\x04\x00\x00\x00")
    code.label("edge")
    code.raw(b"\x8b\x06\x0f\xaf\xc3\x99\xf7\xf9\xf7\xc7\x01\x00\x00\x00")
    code.jump_short_if(Condition.NOT_EQUAL, "vertical")
    code.raw(b"\x03\xc5")
    code.label("vertical")
    code.raw(b"\x89\x06\x83\xc6\x04\x4f")
    code.jump_short_if(Condition.NOT_EQUAL, "edge")
    code.raw(b"\x61\xff\x74\x24\x1c\x8d\x44\x24\x04\x50\xff\x74\x24\x1c")
    code.call_absolute(target_va)
    code.raw(b"\x83\xc4\x10\xc2\x0c\x00")
    code.label("native")
    code.jump_absolute(target_va)
    return code.build()
