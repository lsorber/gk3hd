"""SIDNEY must not refit CursorManager's already-physical transfers."""

from __future__ import annotations

import struct

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.guard_stale_mouse_move_targets import MouseMoveDispatchABI
from gk3hd.patch.definitions.runtime2d.layout import (
    CONSOLE_OWNER_OFFSET,
    CONSOLE_SEGMENT,
    SPRITE_CACHE_SEGMENT,
    SPRITE_CACHE_TRANSFER_OFFSET,
    RuntimeSegmentAddress,
    RuntimeSymbols,
)
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.sidney_composition import build_blt_wrapper
from gk3hd.patch.definitions.runtime2d.sidney_presentation import SidneyPresentationCompiler


def test_cursor_ownership_precedes_active_and_inactive_sidney_dispatch() -> None:
    compiler = SidneyPresentationCompiler(
        symbols=RuntimeSymbols(
            segments=(
                RuntimeSegmentAddress(segment=CONSOLE_SEGMENT, raw_offset=0, rva=0, va=0x80A000),
                RuntimeSegmentAddress(
                    segment=SPRITE_CACHE_SEGMENT, raw_offset=0, rva=0, va=0x810000
                ),
            )
        ),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=0x790004, height_va=0x790008),
        mouse_move_abi=MouseMoveDispatchABI(ui_dispatch_adapter_slot_va=0x792000),
    )
    base, active, classifier = 0x800000, 0x801000, 0x809000
    payload = build_blt_wrapper(
        compiler,
        wrapper_va=base,
        active_depth_va=active,
        transformed_blit_count_va=0x801004,
        rect_scratch_va=0x801010,
        cursor_blt_trace_helper_va=0x802000,
        extension_surface_ptr_va=0x801008,
        status_trace_count_va=0x801020,
        status_trace_records_va=0x803000,
        system_blt_wrapper_va=0x804000,
        portrait_source_va=0x805000,
        frame_source_va=0x806000,
        cursor_surface_classifier_va=classifier,
    )
    decoded = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, base))
    assert any(
        i.mnemonic == "jmp" and i.op_str == hex(0x810000 + SPRITE_CACHE_TRANSFER_OFFSET)
        for i in decoded
    )
    assert sum(instruction.size for instruction in decoded) == len(payload)
    call = next(i for i in decoded if i.mnemonic == "call" and i.op_str == hex(classifier))
    offset = call.address - base
    assert payload[offset - 13 : offset] == bytes.fromhex("60 8b 4c 24 18 8b 54 24 24 8b 74 24 28")
    assert payload[offset + 5 : offset + 10] == bytes.fromhex("85 c0 61 0f 85")
    active_test = b"\x83\x3d" + struct.pack("<I", active) + b"\x00"
    assert offset < payload.index(active_test)
    console_test = b"\x83\x3d" + struct.pack("<I", 0x80A000 + CONSOLE_OWNER_OFFSET) + b"\x00"
    console_offset = payload.index(console_test)
    assert offset < console_offset < payload.index(active_test)
    # Tail dispatch preserves the alpha compositor's original return PC;
    # the console-owned shared path then uses the canonical native continuation.
    assert any(
        i.mnemonic == "jmp"
        and i.op_str == "0x804000"
        and console_offset < i.address - base < payload.index(active_test)
        for i in decoded
    )
    # No 128x128 guess: the cursor backing is360x360 at4K, and an unrelated
    # interface image could itself be128x128. Identity is the invariant.
    for dimension in (b"\x38", b"\x3c"):
        assert b"\x81\x7a" + dimension + struct.pack("<I", 128) not in payload
