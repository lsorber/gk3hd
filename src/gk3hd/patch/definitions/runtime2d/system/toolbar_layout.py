"""Fit the toolbar's native layout transaction to its presented dimensions."""

from __future__ import annotations

import struct

from gk3hd.patch.binary.x86 import Condition, X86Emitter


def build_toolbar_layout(
    *, wrapper_va: int, physical_width_va: int, input_valid_va: int, target_va: int
) -> bytes:
    """Translate a proposed RECT before native child relocation and invalidation.

    The native SetRect call has already constrained authored extents against the
    framebuffer. Its final commit must also constrain the *presented* extents:
    height-scaled about the 252x75 base centre. Moving both the root and children
    by a physical delta preserves this affine without resizing native controls.
    ECX is the toolbar; the sole argument is its caller-owned temporary RECT.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x60\x8b\x7c\x24\x24\x31\xf6")
    code.raw(b"\x8b\x2d" + struct.pack("<I", physical_width_va + 4))
    code.label("axis")
    code.raw(b"\xbb\x7e\x00\x00\x00\x85\xf6")
    code.jump_short_if(Condition.EQUAL, "anchor")
    code.raw(b"\xbb\x25\x00\x00\x00")
    code.label("anchor")
    code.raw(b"\x03\x1c\x37")
    # Far edge minus the available framebuffer edge (with native 2px margin,
    # scaled by the same reference-height ratio as the panel itself).
    code.raw(b"\x8b\x44\x37\x08\x2b\xc3\x83\xc0\x02\x0f\xaf\xc5")
    code.raw(b"\x99\xb9\x00\x03\x00\x00\xf7\xf9\x03\xc3")
    code.raw(b"\x2b\x86" + struct.pack("<I", physical_width_va))
    code.jump_short_if(Condition.GREATER, "translate")
    # If the far edge fits, constrain the near edge instead. The supported
    # toolbar panels fit within a reference-height canvas, so one translation
    # suffices for both edges; no clipping or shrinking is introduced.
    code.raw(b"\x8b\x04\x37\x2b\xc3\x83\xe8\x02\x0f\xaf\xc5")
    code.raw(b"\x99\xf7\xf9\x03\xc3\x85\xc0")
    code.jump_short_if(Condition.LESS, "translate")
    code.raw(b"\x31\xc0")
    code.label("translate")
    code.raw(b"\x29\x04\x37\x29\x44\x37\x08\x83\xc6\x04\x83\xfe\x08")
    code.jump_short_if(Condition.LESS, "axis")
    # A relocated root has a new anchor. Retire the previous immutable input
    # snapshot so the next composition publishes the matching new inverse.
    code.raw(b"\x8b\x4c\x24\x18\x8b\x07\x3b\x41\x1c")
    code.jump_short_if(Condition.NOT_EQUAL, "invalidate")
    code.raw(b"\x8b\x47\x04\x3b\x41\x20")
    code.jump_short_if(Condition.EQUAL, "done")
    code.label("invalidate")
    code.raw(b"\xc7\x05" + struct.pack("<I", input_valid_va) + bytes(4))
    code.label("done")
    code.raw(b"\x61")
    code.jump_absolute(target_va)
    return code.build()


def build_toolbar_cursor_warp(
    *,
    wrapper_va: int,
    physical_width_va: int,
    input_valid_va: int,
    source_rect_va: int,
    target_va: int,
) -> bytes:
    """Return a released slider's pointer to its presented thumb, not its model.

    Only the toolbar slider release sites call this cdecl POINT* adapter. Keep
    the caller's point untouched; the native cursor setter still owns client
    origin conversion. Use the compositor's base-centre forward transform, not
    a rectangle ratio whose integer-rounded endpoints can drift by a pixel.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x83\x3d" + struct.pack("<I", input_valid_va) + b"\x00")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x55\x8b\xec\x83\xec\x08\x60\x8b\x7d\x08\x31\xf6")
    code.label("axis")
    code.raw(b"\xbb\x7e\x00\x00\x00\x85\xf6")
    code.jump_short_if(Condition.EQUAL, "anchor")
    code.raw(b"\xbb\x25\x00\x00\x00")
    code.label("anchor")
    code.raw(b"\x03\x9e" + struct.pack("<I", source_rect_va))
    code.raw(b"\x8b\x04\x37\x2b\xc3\x0f\xaf\x05")
    code.raw(struct.pack("<I", physical_width_va + 4))
    code.raw(b"\x99\xb9\x00\x03\x00\x00\xf7\xf9\x03\xc3")
    code.raw(b"\x89\x44\x35\xf8\x83\xc6\x04\x83\xfe\x08")
    code.jump_short_if(Condition.LESS, "axis")
    code.raw(b"\x8d\x45\xf8\x89\x44\x24\x1c\x61\x50")
    code.call_absolute(target_va)
    code.raw(b"\x83\xc4\x04\xc9\xc3")
    code.label("native")
    code.jump_absolute(target_va)
    return code.build()
