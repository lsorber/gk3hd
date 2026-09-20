"""Preserve dense laptop-frame sources without changing SIDNEY's layout."""

from __future__ import annotations

import struct

from gk3hd.patch.binary.x86 import Condition, X86Emitter

FRAME_SIZES = ((1024, 144), (1024, 144), (192, 480), (192, 480), (174, 13))
FRAME_STRIDE = 12
_DWORD_BYTES = 4
FRAME_NAMES = (
    *(f"s_sid_bkgd1024_{side}_a".encode() for side in ("top", "bottom", "left", "right")),
    b"s_sid_bkgd800_lama_a",
)


def build_discovery(*, wrapper_va: int, state_va: int) -> bytes:
    """Recover source ownership when restoring a save bypasses frame resizing.

    ESI is the resolved bitmap resource and EAX its surface at the shared
    dimension getter. Saved 1024 controls already have authored rectangles;
    no resize callback runs, but their reloaded sources can still be dense.
    Match complete resource names and exact density, never display dimensions.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x60")
    for index, (name, (width, height)) in enumerate(zip(FRAME_NAMES, FRAME_SIZES, strict=True)):
        label = f"next_{index}"
        terminated = name + b"\0"
        for offset in range(0, len(terminated), _DWORD_BYTES):
            part = terminated[offset : offset + _DWORD_BYTES]
            mask = int.from_bytes(bytes(0x20 if byte else 0 for byte in part), "little")
            code.raw(b"\x8b\x56" + bytes([8 + offset]))
            if len(part) < _DWORD_BYTES:
                code.raw(b"\x81\xe2" + struct.pack("<I", (1 << (8 * len(part))) - 1))
            code.raw(b"\x81\xca" + struct.pack("<I", mask))
            code.raw(b"\x81\xfa" + struct.pack("<I", int.from_bytes(part, "little") | mask))
            code.jump_if(Condition.NOT_EQUAL, label)
        slot = state_va + index * FRAME_STRIDE
        code.raw(b"\xc7\x05" + struct.pack("<I", slot) + bytes(4))
        for offset, dimension in ((0x38, width * 4), (0x3C, height * 4)):
            code.raw(b"\x81\x78" + bytes([offset]) + struct.pack("<I", dimension))
            code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\xa3" + struct.pack("<I", slot))
        code.jump("done")
        code.label(label)
    code.label("done")
    code.raw(b"\x61\xc3")
    return code.build()


def frame_state() -> bytes:
    """Initialize five exact source slots and their immutable authored sizes."""
    return b"".join(struct.pack("<III", 0, width, height) for width, height in FRAME_SIZES)


def build_resize(*, wrapper_va: int, state_va: int, resolve_va: int, resize_va: int) -> bytes:
    """Intercept only the four frame resize sites, with their slot index in EDX.

    The original side-piece fallback requests an incorrect 192x144 resize.
    Validate against each known source's authored dimensions, not that fallback.
    Native or unexpected-density replacements retain the original resize path.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x60\x6b\xda\x0c\x81\xc3" + struct.pack("<I", state_va))
    code.raw(b"\xc7\x03" + bytes(4))
    code.raw(b"\xff\x74\x24\x24")  # original bitmap handle after PUSHAD
    code.call_absolute(resolve_va)
    code.raw(b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x8b\x40\x30\x85\xc0")
    code.jump_if(Condition.EQUAL, "native")
    for logical_offset, physical_offset in ((4, 0x38), (8, 0x3C)):
        code.raw(b"\x8b\x53" + bytes([logical_offset]) + b"\xc1\xe2\x02")
        code.raw(b"\x39\x50" + bytes([physical_offset]))
        code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(b"\x89\x03\x61\xc2\x0c\x00")
    code.label("native")
    code.raw(b"\x61")
    code.jump_absolute(resize_va)
    return code.build()


def build_resize_thunk(*, wrapper_va: int, resize_va: int, index: int) -> bytes:
    """Bind a verified constructor/rebuild call to one frame resource slot."""
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\xba" + struct.pack("<I", index))
    code.jump_absolute(resize_va)
    return code.build()


def build_dimensions(*, wrapper_va: int, state_va: int) -> bytes:
    """Return EAX=logical pair and CF=1 only for a retained dense frame surface."""
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x53\xb9" + struct.pack("<I", len(FRAME_SIZES)))
    code.raw(b"\xba" + struct.pack("<I", state_va))
    code.label("next")
    code.raw(b"\x3b\x02")
    code.jump_short_if(Condition.EQUAL, "matched")
    code.raw(b"\x83\xc2\x0c\x49")
    code.jump_short_if(Condition.NOT_EQUAL, "next")
    code.label("native")
    code.raw(b"\x5b\xf8\xc3")
    code.label("matched")
    code.raw(b"\x85\xc0")
    code.jump_short_if(Condition.EQUAL, "native")
    for logical_offset, physical_offset in ((4, 0x38), (8, 0x3C)):
        code.raw(b"\x8b\x5a" + bytes([logical_offset]) + b"\xc1\xe3\x02")
        code.raw(b"\x39\x58" + bytes([physical_offset]))
        code.jump_short_if(Condition.NOT_EQUAL, "native")
    code.raw(b"\x8d\x42\x04\x5b\xf9\xc3")
    return code.build()


def build_source(*, wrapper_va: int, dimensions_va: int, scratch_va: int) -> bytes:
    """Expand only a retained frame's clipped source in SIDNEY's final blit."""
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x60\x8d\x6c\x24\x24\x8b\x45\x04")
    code.call_absolute(dimensions_va)
    code.jump_if(Condition.ABOVE_OR_EQUAL, "done")  # CF=0: not a dense frame
    code.raw(b"\x8b\x75\x0c\x85\xf6")
    code.jump_if(Condition.EQUAL, "done")
    for offset in range(0, 16, 4):
        code.raw(b"\x8b\x46" + bytes([offset]) + b"\xc1\xe0\x02")
        code.raw(b"\xa3" + struct.pack("<I", scratch_va + offset))
    code.raw(b"\xc7\x45\x0c" + struct.pack("<I", scratch_va))
    code.label("done")
    code.raw(b"\x61\xc3")
    return code.build()
