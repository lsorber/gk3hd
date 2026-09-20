"""Project the TimeBlock's exact animated text child before native clipping."""

from __future__ import annotations

import struct
from typing import Literal

from gk3hd.patch.binary.x86 import Condition, X86Emitter

# Exact physical dimensions of the shipped text-animation frames at 4x.
_DENSE_SIZES = (
    (1532, 252),
    (1464, 280),
    (1504, 276),
    (1596, 276),
    (1592, 280),
    (1004, 276),
    (1436, 280),
    (1528, 280),
    (1448, 276),
    (1592, 272),
    (1496, 280),
    (1428, 276),
    (1460, 280),
    (1476, 276),
    (1732, 276),
    (1588, 280),
    (1492, 276),
)


def emit_card_height(
    code: X86Emitter,
    *,
    raw_height_va: int,
    screen_size_va: int,
    destination: Literal["ebx", "esi", "edi"],
    purpose: Literal["extent", "centering"] = "extent",
) -> None:
    """Fit the actual authored height: TBT306P is 481 rows, all others 480."""
    code.raw(b"\x60\x8b\x3d" + struct.pack("<I", raw_height_va) + b"\xc1\xef\x02")
    if purpose == "centering":
        # Native centering truncates the half-height before positioning. The
        # exceptional 481st row extends downward; it does not move the card up.
        code.raw(b"\x83\xe7\xfe")
    code.raw(b"\x8b\x0d" + struct.pack("<I", screen_size_va))
    code.raw(b"\x8b\x35" + struct.pack("<I", screen_size_va + 4))
    code.raw(b"\x6b\xc1\x03\x8d\x14\xb5\x00\x00\x00\x00\x3b\xc2")
    code.jump_short_if(Condition.LESS, f"card_height_{destination}_width_limited")
    code.raw(b"\x8b\xc6\x0f\xaf\xc7\x99\xb9\x00\x03\x00\x00\xf7\xf9")
    code.jump_short(f"card_height_{destination}_ready")
    code.label(f"card_height_{destination}_width_limited")
    code.raw(b"\x8b\xc1\x0f\xaf\xc7\xc1\xf8\x0a")
    code.label(f"card_height_{destination}_ready")
    stack_offset = {"ebx": 16, "esi": 4, "edi": 0}[destination]
    code.raw(b"\x89\x44\x24" + bytes([stack_offset]) + b"\x61")


def build_overlay_draw(
    *,
    wrapper_va: int,
    native_draw_va: int,
    sequence_vtable_va: int,
    surface_va: int,
    manager_va: int,
    resolve_va: int,
) -> bytes:
    """Tag the exact current animation frame for logical dimensions and sampling.

    Called only inside the validated TimeBlock root Draw scope. The animated
    child is embedded at +0x2A8; its sequence at +0x2C owns the bitmap-handle
    vector. The shared getter quarters only this surface, so Game::blit clips
    in authored coordinates. The final blitter expands source sampling again.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x60\x31\xc0\xa3" + struct.pack("<I", surface_va))
    code.raw(b"\x8b\xf1\x8b\xbe\xd4\x02\x00\x00\x85\xff")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x81\x3f" + struct.pack("<I", sequence_vtable_va))
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(b"\x8b\x86\xe0\x02\x00\x00\x8b\x57\x24\x85\xd2")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x8b\x4f\x28\x2b\xca\xc1\xe9\x02\x3b\xc1")
    code.jump_if(Condition.ABOVE_OR_EQUAL, "native")
    code.raw(b"\xff\x34\x82\x8b\x0d" + struct.pack("<I", manager_va))
    code.call_absolute(resolve_va)
    code.raw(b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x8b\x78\x30\x85\xff")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x8b\x47\x38\x8b\x57\x3c")
    for index, (width, height) in enumerate(_DENSE_SIZES):
        code.raw(b"\x3d" + struct.pack("<I", width))
        code.jump_short_if(Condition.NOT_EQUAL, f"size_{index}")
        code.raw(b"\x81\xfa" + struct.pack("<I", height))
        if index >= len(_DENSE_SIZES) - 6:
            code.jump_short_if(Condition.EQUAL, "dense")
        else:
            code.jump_if(Condition.EQUAL, "dense")
        code.label(f"size_{index}")
    code.jump("native")
    code.label("dense")
    code.raw(b"\x89\x3d" + struct.pack("<I", surface_va))
    code.label("native")
    code.raw(b"\x61\x51\xff\x74\x24\x0c\xff\x74\x24\x0c")
    code.call_absolute(native_draw_va)
    code.raw(b"\xc7\x05" + struct.pack("<I", surface_va) + bytes(4))
    code.raw(b"\x59\xc2\x08\x00")
    return code.build()


def build_border_draw(
    *,
    wrapper_va: int,
    native_draw_va: int,
    screen_size_va: int,
    target_rect_va: int,
    raw_height_va: int,
) -> bytes:
    """Keep the four native black surround rectangles outside the fitted card.

    Root centering translates descendants, including these physical-screen
    clears. Rebuild their rectangles for this traversal and restore their
    exact model state afterward, before the root's inverse translation.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x60\x8b\xd9\x83\xec\x40\x8b\xfc")
    for offset in (0x30C, 0x340, 0x374, 0x3A8):
        code.raw(b"\x8d\xb3" + struct.pack("<I", offset))
        code.raw(b"\x6a\x04\x59\xf3\xa5")
    code.raw(b"\x8b\x0d" + struct.pack("<I", screen_size_va))
    code.raw(b"\x8b\x15" + struct.pack("<I", screen_size_va + 4))
    code.raw(b"\x6b\xc1\x03\x8d\x34\x95\x00\x00\x00\x00\x3b\xc6")
    code.jump_short_if(Condition.LESS, "width_limited")
    code.raw(b"\x6b\xf2\x05\x8b\xc6\xc1\xfe\x03\x99\x6a\x06\x5f\xf7\xff")
    code.jump_short("size_ready")
    code.label("width_limited")
    code.raw(b"\x6b\xc1\x05\xc1\xf8\x03\x6b\xf1\x0f\xc1\xfe\x05")
    code.label("size_ready")
    emit_card_height(
        code, raw_height_va=raw_height_va, screen_size_va=screen_size_va, destination="esi"
    )
    emit_card_height(
        code,
        raw_height_va=raw_height_va,
        screen_size_va=screen_size_va,
        destination="edi",
        purpose="centering",
    )
    # EAX fitted width, ESI fitted height; ECX physical width.
    code.raw(b"\x2b\xc8\xd1\xf9\x03\xc1")
    code.raw(b"\x89\x0d" + struct.pack("<I", target_rect_va))
    code.raw(b"\xa3" + struct.pack("<I", target_rect_va + 8))
    code.raw(b"\x8b\x15" + struct.pack("<I", screen_size_va + 4))
    code.raw(b"\x2b\xd7\xd1\xfa\x03\xf2")
    code.raw(b"\x89\x15" + struct.pack("<I", target_rect_va + 4))
    code.raw(b"\x89\x35" + struct.pack("<I", target_rect_va + 12))
    # Rectangle sources: None means zero; otherwise read the given live edge.
    rectangles = (
        (0x30C, (None, None, target_rect_va, screen_size_va + 4)),
        (0x340, (target_rect_va + 8, None, screen_size_va, screen_size_va + 4)),
        (0x374, (target_rect_va, None, target_rect_va + 8, target_rect_va + 4)),
        (0x3A8, (target_rect_va, target_rect_va + 12, target_rect_va + 8, screen_size_va + 4)),
    )
    for offset, edges in rectangles:
        for index, address in enumerate(edges):
            code.raw(b"\x31\xc0" if address is None else b"\xa1" + struct.pack("<I", address))
            code.raw(b"\x89\x83" + struct.pack("<I", offset + index * 4))
    code.raw(b"\x8b\xcb\xff\x74\x24\x68\xff\x74\x24\x68")
    code.call_absolute(native_draw_va)
    code.raw(b"\x8b\xf4")
    for offset in (0x30C, 0x340, 0x374, 0x3A8):
        code.raw(b"\x8d\xbb" + struct.pack("<I", offset))
        code.raw(b"\x6a\x04\x59\xf3\xa5")
    code.raw(b"\x83\xc4\x40\x61\xc2\x08\x00")
    return code.build()
