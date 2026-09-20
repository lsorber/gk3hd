from __future__ import annotations

import struct

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

from gk3hd.patch.definitions.runtime2d.layout import (
    BINOCULAR_SIZE_HELPER_OFFSET,
    BINOCULAR_SOURCE_HELPER_OFFSET,
)
from gk3hd.patch.definitions.runtime2d.system.resource_dimensions import (
    build_dimensions,
    build_source_rect,
)


def test_dimension_helper_matches_identity_and_preserves_native_tail() -> None:
    payload = build_dimensions(
        wrapper_va=0x800000,
        state_va=0x810000,
        return_va=0x5344FB,
        preview_surface_va=0x820000,
        root_va=0x820010,
        toolbar_vtable_va=0x684FA4,
        timeblock_surface_va=0x830000,
        image_dimensions_va=0x840000,
        frame_dimensions_va=0x850000,
        frame_discovery_va=0x860000,
        fingerprint_dimensions_va=0x870000,
        inventory_dimensions_va=0x880000,
        border_dimensions_va=0x890000,
        cursor_match_va=0x8A0000,
    )
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in instructions) == len(payload)
    assert len(payload) <= BINOCULAR_SOURCE_HELPER_OFFSET - BINOCULAR_SIZE_HELPER_OFFSET
    assert payload.startswith(bytes.fromhex("51 52 8b 46 30"))
    calls = [i.op_str for i in instructions if i.mnemonic == "call"]
    assert calls[:3] == ["0x8a0000", "0x860000", "0x850000"]
    assert "0x840000" in calls  # SIDNEY owns its extensible image dimension helper
    assert "0x890000" in calls  # Exact dense borders retain native panel metrics.
    assert b"\x81\x7e\x08BINO" in payload
    assert b"\x81\x7e\x0cCBTN" in payload
    # 134x31 pressed, 135x30 normal and 135x29 hover have distinct native extents.
    for value in (536, 124, 540, 120, 116):
        assert struct.pack("<I", value) in payload
    assert instructions[-1].mnemonic == "jmp"
    assert instructions[-1].op_str == "0x5344fb"
    assert b"\x5a\x59\xe9" in payload


def test_source_helper_is_scoped_and_changes_only_a_private_source_rect() -> None:
    payload = build_source_rect(
        wrapper_va=0x800000, state_va=0x810000, root_ptr_va=0x820000, root_vtable_va=0x668428
    )
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in instructions) == len(payload)
    assert payload.startswith(bytes.fromhex("60 8d 6c 24 24"))
    assert b"\x81\x38" + struct.pack("<I", 0x668428) in payload
    assert b"\x3b\x05" + struct.pack("<I", 0x810000) in payload
    for offset in range(0, 16, 4):
        assert b"\xc1\x25" + struct.pack("<I", 0x81000C + offset) + b"\x02" in payload
    assert b"\xc7\x45\x2c" + struct.pack("<I", 0x81000C) in payload
    assert payload.endswith(b"\x61\xc3")
