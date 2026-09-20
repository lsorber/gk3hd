from __future__ import annotations

import struct

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

from gk3hd.patch.definitions.runtime2d.timeblock_overlay import (
    _DENSE_SIZES,
    build_border_draw,
    build_overlay_draw,
)
from gk3hd.textures.upscale.timeblock import _RECIPES


def test_current_frame_proof_covers_every_sequence_size_and_clears_after_draw() -> None:
    assert set(_DENSE_SIZES) == {tuple(v * 4 for v in r.size) for r in _RECIPES.values()}
    payload = build_overlay_draw(
        wrapper_va=0x800000,
        native_draw_va=0x4D4F22,
        sequence_vtable_va=0x666AC4,
        surface_va=0x810000,
        manager_va=0x6FF838,
        resolve_va=0x534560,
    )
    decoded = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in decoded) == len(payload)
    assert len(payload) <= 0x200
    assert b"\x81\x3f" + struct.pack("<I", 0x666AC4) in payload
    assert b"\x8b\x86\xe0\x02\x00\x00" in payload  # current frame index
    assert b"\xc7\x05" + struct.pack("<I", 0x810000) + bytes(4) in payload
    assert payload.endswith(b"\x59\xc2\x08\x00")


def test_border_draw_restores_all_four_physical_clear_objects() -> None:
    payload = build_border_draw(
        wrapper_va=0x800000,
        native_draw_va=0x4D4F22,
        screen_size_va=0x810000,
        target_rect_va=0x810010,
        raw_height_va=0x810020,
    )
    decoded = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in decoded) == len(payload)
    for offset in (0x30C, 0x340, 0x374, 0x3A8):
        assert b"\x8d\xb3" + struct.pack("<I", offset) in payload
        assert b"\x8d\xbb" + struct.pack("<I", offset) in payload
    assert payload.endswith(b"\x83\xc4\x40\x61\xc2\x08\x00")
