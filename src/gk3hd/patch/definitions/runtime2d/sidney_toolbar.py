"""Keep SIDNEY's nested toolbar in its authored canvas, including pointer warps."""

from __future__ import annotations

import struct

from gk3hd.patch.binary.x86 import Condition, X86Emitter


def _owner(code: X86Emitter, *, current_layer_va: int, root_va: int) -> None:
    code.raw(b"\x60")
    code.call_absolute(current_layer_va)
    code.raw(b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "fallback")
    code.raw(b"\x3b\x05" + struct.pack("<I", root_va))
    code.jump_if(Condition.NOT_EQUAL, "fallback")


def build_layout(
    *,
    wrapper_va: int,
    current_layer_va: int,
    root_va: int,
    input_valid_va: int,
    native_va: int,
    fallback_va: int,
) -> bytes:
    """Clamp native child geometry to 1024x768 before native relocation."""
    code = X86Emitter(base_va=wrapper_va)
    _owner(code, current_layer_va=current_layer_va, root_va=root_va)
    code.raw(b"\x8b\x7c\x24\x24")
    for offset, limit in ((0, 1022), (4, 766)):
        code.raw(b"\x8b\x47" + bytes([offset + 8]) + b"\x2d" + struct.pack("<I", limit))
        code.jump_short_if(Condition.GREATER, f"translate_{offset}")
        code.raw(b"\x8b\x47" + bytes([offset]) + b"\x83\xe8\x02")
        code.jump_short_if(Condition.LESS, f"translate_{offset}")
        code.raw(b"\x31\xc0")
        code.label(f"translate_{offset}")
        code.raw(b"\x29\x47" + bytes([offset]) + b"\x29\x47" + bytes([offset + 8]))
    code.raw(b"\xc7\x05" + struct.pack("<I", input_valid_va) + bytes(4))
    code.raw(b"\x61")
    code.jump_absolute(native_va)
    code.label("fallback")
    code.raw(b"\x61")
    code.jump_absolute(fallback_va)
    return code.build()


def build_warp(
    *,
    wrapper_va: int,
    current_layer_va: int,
    root_va: int,
    physical_width_va: int,
    native_va: int,
    fallback_va: int,
) -> bytes:
    """Map a released slider's logical point without modifying its caller."""
    code = X86Emitter(base_va=wrapper_va)
    _owner(code, current_layer_va=current_layer_va, root_va=root_va)
    code.raw(b"\x61\x83\xec\x08\x60\x8b\x74\x24\x2c")
    code.raw(b"\x8b\x1d" + struct.pack("<I", physical_width_va + 4))
    code.raw(b"\x8b\xc3\xc1\xe0\x02\x99\xb9\x03\x00\x00\x00\xf7\xf9")
    code.raw(b"\x8b\x2d" + struct.pack("<I", physical_width_va))
    code.raw(b"\x2b\xe8\xd1\xfd\xb9\x00\x03\x00\x00")
    for offset in (0, 4):
        code.raw(b"\x8b\x46" + bytes([offset]) + b"\x0f\xaf\xc3\x99\xf7\xf9")
        if offset == 0:
            code.raw(b"\x03\xc5")
        code.raw(b"\x89\x44\x24" + bytes([0x20 + offset]))
    code.raw(b"\x61\x8d\x04\x24\x50")
    code.call_absolute(native_va)
    code.raw(b"\x83\xc4\x0c\xc3")
    code.label("fallback")
    code.raw(b"\x61")
    code.jump_absolute(fallback_va)
    return code.build()


def build_draw(
    *,
    wrapper_va: int,
    current_layer_va: int,
    root_va: int,
    depth_va: int,
    native_va: int,
) -> bytes:
    """Include deferred sibling draws in the live SIDNEY canvas scope."""
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\xff\x35" + struct.pack("<I", depth_va))
    _owner(code, current_layer_va=current_layer_va, root_va=root_va)
    code.raw(b"\xff\x05" + struct.pack("<I", depth_va))
    code.label("fallback")
    code.raw(b"\x61\xff\x74\x24\x0c\xff\x74\x24\x0c")
    code.call_absolute(native_va)
    code.raw(b"\x8f\x05" + struct.pack("<I", depth_va) + b"\xc2\x08\x00")
    return code.build()
