"""Separate dense UI raster dimensions from authored metrics at the shared getter."""

from __future__ import annotations

import struct

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.system.cursor_density import emit_logical_dimensions
from gk3hd.patch.definitions.runtime2d.system.toolbar_preview import emit_preview_dimensions

# All are exact fourfold dimensions, not thresholds or display-mode guesses.
# BINOCMASK is deliberately outside the BINOCBTN namespace: GK3 already owns
# its fullscreen resampling. The source family includes one 134x31 pressed
# state and a 135x29 zoom-hover state alongside the usual 135x30 labels;
# retain those authored differences.
_DENSE_CONTROL_SIZES = (
    (448, 464),
    (100, 180),
    (180, 100),
    (536, 124),
    (540, 120),
    (536, 120),
    (540, 116),
)


def build_dimensions(
    *,
    wrapper_va: int,
    state_va: int,
    return_va: int,
    preview_surface_va: int,
    root_va: int,
    toolbar_vtable_va: int,
    timeblock_surface_va: int,
    image_dimensions_va: int,
    frame_dimensions_va: int,
    frame_discovery_va: int,
    fingerprint_dimensions_va: int,
    inventory_dimensions_va: int,
    border_dimensions_va: int,
    cursor_match_va: int,
) -> bytes:
    """Return transient logical dimensions without modifying the source surface.

    Entry is BitmapManager::GetDimensions' tail: ESI is the resolved resource.
    The native tail returns a pointer to two integers. Both BitmapObject::Set
    and the clipped sprite renderer consume those integers synchronously. Only
    proven dense UI sources receive logical dimensions: the prepared toolbar
    preview, TimeBlock frames, SIDNEY illustrations/frame, BINOCBTN controls,
    and verified animated cursors.
    Other resources retain the native pointer.
    """
    logical_va = state_va + 4
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x51\x52\x8b\x46\x30")
    code.raw(b"\xc7\x05" + struct.pack("<I", state_va) + bytes(4))
    emit_logical_dimensions(code, logical_va=logical_va, match_va=cursor_match_va)
    code.call_absolute(frame_discovery_va)
    code.call_absolute(frame_dimensions_va)
    code.jump_if(Condition.BELOW, "done")
    code.call_absolute(fingerprint_dimensions_va)
    code.jump_if(Condition.BELOW, "done")
    emit_preview_dimensions(
        code,
        surface_va=preview_surface_va,
        logical_va=logical_va,
        root_va=root_va,
        vtable_va=toolbar_vtable_va,
    )
    code.raw(b"\x3b\x05" + struct.pack("<I", timeblock_surface_va))
    code.jump_if(Condition.EQUAL, "dense")
    code.call_absolute(image_dimensions_va)
    code.jump_if(Condition.BELOW, "done")
    code.call_absolute(inventory_dimensions_va)
    code.jump_if(Condition.BELOW, "done")
    code.call_absolute(border_dimensions_va)
    code.jump_if(Condition.BELOW, "done")
    for offset, part in ((8, b"BINO"), (12, b"CBTN")):
        code.raw(b"\x81\x7e" + bytes([offset]) + part)
        code.jump_if(Condition.NOT_EQUAL, "native")
    for index, (width, height) in enumerate(_DENSE_CONTROL_SIZES):
        code.raw(b"\x81\x78\x38" + struct.pack("<I", width))
        code.jump_if(Condition.NOT_EQUAL, f"next_{index}")
        code.raw(b"\x81\x78\x3c" + struct.pack("<I", height))
        code.jump_if(Condition.EQUAL, "dense")
        code.label(f"next_{index}")
    code.jump("native")
    code.label("dense")
    code.raw(b"\xa3" + struct.pack("<I", state_va))
    for offset, destination in ((0x38, logical_va), (0x3C, logical_va + 4)):
        code.raw(b"\x8b\x50" + bytes([offset]))
        code.raw(b"\xc1\xfa\x02\x89\x15" + struct.pack("<I", destination))
    code.raw(b"\xb8" + struct.pack("<I", logical_va))
    code.jump("done")
    code.label("native")
    code.raw(b"\x83\xc0\x38")
    code.label("done")
    code.raw(b"\x5a\x59")
    code.jump_absolute(return_va)
    return code.build()


def build_source_rect(
    *, wrapper_va: int, state_va: int, root_ptr_va: int, root_vtable_va: int
) -> bytes:
    """Expand only the tagged control's clipped source inside Binocular::Draw.

    Called with the shared dispatcher's PUSHAD frame at ESP+4. Copy the source
    RECT before multiplying: callers may reuse their logical clip rectangles.
    Destination, layout, and input remain authored; the existing binocular
    presentation affine then applies the live display scale exactly once.
    """
    rect_va = state_va + 12
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x60\x8d\x6c\x24\x24")  # EBP = caller PUSHAD frame.
    code.raw(b"\xa1" + struct.pack("<I", root_ptr_va) + b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "done")
    code.raw(b"\x81\x38" + struct.pack("<I", root_vtable_va))
    code.jump_if(Condition.NOT_EQUAL, "done")
    code.raw(b"\x8b\x45\x24\x85\xc0")
    code.jump_if(Condition.EQUAL, "done")
    code.raw(b"\x3b\x05" + struct.pack("<I", state_va))
    code.jump_if(Condition.NOT_EQUAL, "done")
    code.raw(b"\x8b\x75\x2c\x85\xf6")
    code.jump_if(Condition.EQUAL, "done")
    code.raw(b"\xbf" + struct.pack("<I", rect_va))
    code.raw(b"\xb9\x04\x00\x00\x00\xf3\xa5")
    for offset in range(0, 16, 4):
        code.raw(b"\xc1\x25" + struct.pack("<I", rect_va + offset) + b"\x02")
    code.raw(b"\xc7\x45\x2c" + struct.pack("<I", rect_va))
    code.label("done")
    code.raw(b"\x61\xc3")
    return code.build()
