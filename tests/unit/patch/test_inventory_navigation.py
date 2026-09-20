"""Dense navigation art and inventory-scoped scrollbar layout contracts."""

from __future__ import annotations

import struct

import pytest
from capstone import CS_ARCH_X86, CS_MODE_32, Cs

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.runtime2d.inventory_navigation import (
    IMAGES,
    SURFACES_SIZE,
    build_clear,
    build_input_scope,
    build_loadsave_control_predicate,
    build_scrollbar_dimensions,
    build_scrollbar_height,
    build_scrollbar_page_size,
    build_source,
)
from gk3hd.patch.definitions.runtime2d.sidney_images import build_image_dimensions


def test_navigation_dimensions_retain_only_exact_dense_resources() -> None:
    assert len(IMAGES) == 19
    for direction in (b"dn", b"up"):
        for state_name in (b"dis", b"dwn", b"hov", b"std"):
            assert (b"inv_scroll" + direction + b"_" + state_name, 22, 20) in IMAGES
    assert IMAGES[:2] == ((b"inv_highlight", 99, 98), (b"inv_scrollback", 22, 22))
    state = 0x810000
    payload = build_image_dimensions(wrapper_va=0x800000, surfaces_va=state, images=IMAGES)
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in instructions) == len(payload)
    assert len(payload) <= 0xD00
    for index, (_, width, height) in enumerate(IMAGES):
        slot = struct.pack("<I", state + index * 4)
        assert b"\xc7\x05" + slot + bytes(4) in payload
        assert b"\xa3" + slot in payload
        for offset, value in ((0x38, width * 4), (0x3C, height * 4)):
            assert b"\x81\x78" + bytes([offset]) + struct.pack("<I", value) in payload
    # Source scratch and returned logical dimensions must not overlap identities.
    logical = state + SURFACES_SIZE + 16
    assert b"\xb8" + struct.pack("<I", logical) + b"\xf9\xc3\xf8\xc3" in payload


def test_navigation_sampling_preserves_source_rect_and_checks_inventory_owner() -> None:
    state = 0x810000
    payload = build_source(
        wrapper_va=0x800000,
        state_va=state,
        current_layer_va=0x820000,
        inventory_vtable_va=0x830000,
        loadgame_vtable_va=0x840000,
        savegame_vtable_va=0x850000,
    )
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in instructions) == len(payload)
    assert len(payload) <= 0x500
    assert payload.startswith(b"\x60\x8d\x6c\x24\x24")
    assert payload.endswith(b"\x61\xc3")
    assert b"\x81\x38" + struct.pack("<I", 0x830000) in payload
    assert b"\x81\x38" + struct.pack("<I", 0x840000) in payload
    assert b"\x81\x38" + struct.pack("<I", 0x850000) in payload
    assert any(i.mnemonic == "call" and i.op_str == "0x820000" for i in instructions)
    for index, (_, width, height) in enumerate(IMAGES):
        assert b"\x3b\x05" + struct.pack("<I", state + index * 4) in payload
        for offset, value in ((0x38, width * 4), (0x3C, height * 4)):
            assert b"\x81\x78" + bytes([offset]) + struct.pack("<I", value) in payload
    for offset in range(0, 16, 4):
        assert b"\xa3" + struct.pack("<I", state + SURFACES_SIZE + offset) in payload
    assert b"\xc7\x45\x0c" + struct.pack("<I", state + SURFACES_SIZE) in payload
    assert b"\xc7\x45\x08" not in payload  # never rewrite destination argument
    assert b"\x89\x06" not in payload  # never overwrite caller-owned source RECT


def test_navigation_cleanup_clears_every_retained_surface() -> None:
    payload = build_clear(state_va=0x810000)
    assert len(payload) == len(IMAGES) * 10 + 1
    assert payload.endswith(b"\xc3")
    for offset in range(0, SURFACES_SIZE, 4):
        assert b"\xc7\x05" + struct.pack("<I", 0x810000 + offset) + bytes(4) in payload


def test_loadsave_predicate_rejects_inventory_sources_and_requires_dense_dimensions() -> None:
    state = 0x810000
    payload = build_loadsave_control_predicate(wrapper_va=0x800000, state_va=state)
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in instructions) == len(payload)
    for index, (name, _, _) in enumerate(IMAGES):
        comparison = b"\x3b\x05" + struct.pack("<I", state + index * 4)
        assert (comparison in payload) == name.startswith(b"saveload_")
    assert b"\x83\x78\x38\x58" in payload
    assert b"\x83\x78\x3c\x50" in payload
    assert b"\x83\x78\x3c\x58" in payload
    assert b"\xf8\xc3" in payload
    assert payload.endswith(b"\xf9\xc3")


def test_scrollbar_selector_keeps_small_modes_and_preserves_flags() -> None:
    pointer = GOG_BUILD.address("display.dimension_pointers")
    payload = build_scrollbar_dimensions(
        wrapper_va=0x800000, dimensions_pointer_va=pointer, reference_pair_va=0x810000
    )
    assert payload.startswith(b"\x9c\x8b\x0d" + struct.pack("<I", pointer))
    assert payload.endswith(b"\x9d\xc3")
    assert b"\x81\x39\x00\x04\x00\x00" in payload
    assert b"\x81\x79\x04\x00\x03\x00\x00" in payload
    assert b"\xb9" + struct.pack("<I", 0x810000) in payload
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in instructions) == len(payload)
    assert [i.mnemonic for i in instructions if i.mnemonic.startswith("j")] == ["ja", "jbe"]


def test_scrollbar_height_uses_shared_selector_without_clobbering_output_pointer() -> None:
    payload = build_scrollbar_height(wrapper_va=0x800000, dimensions_va=0x810000)
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert [(i.mnemonic, i.op_str) for i in instructions] == [
        ("call", "0x810000"),
        ("mov", "ecx, dword ptr [ecx + 4]"),
        ("ret", ""),
    ]
    assert GOG_BUILD.site("inventory.scrollbar_width").original == bytes.fromhex(
        "8b 0d cc b0 70 00"
    )
    assert GOG_BUILD.site("inventory.scrollbar_height").original == bytes.fromhex(
        "8b 0d c8 b0 70 00 8b 09"
    )


@pytest.mark.parametrize("argument_count", [1, 3])
def test_inventory_event_scopes_cursor_cache_without_remapping_point(argument_count: int) -> None:
    cursor = 0x810000
    payload = build_input_scope(
        argument_count=argument_count,
        cursor_position_va=cursor,
    )
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in instructions) == len(payload)
    assert len(payload) <= 0x100
    for offset in (0, 4):
        assert payload.count(struct.pack("<I", cursor + offset)) == 3
    assert b"\xff\x75\x08\x8b\x4d\xf8\xff\x55\xfc" in payload
    assert payload.endswith(b"\xc9\xc2" + struct.pack("<H", argument_count * 4))
    assert all(i.mnemonic not in {"idiv", "imul", "shl"} for i in instructions)
    # The callee's EAX result survives cache restoration through EDX.
    after_call = payload.split(b"\xff\x55\xfc", 1)[1]
    assert after_call.startswith(b"\x8b\x55\xf4\x89\x15")


def test_scrollbar_page_size_uses_authored_height_and_native_row_formula() -> None:
    payload = build_scrollbar_page_size(wrapper_va=0x800000, dimensions_va=0x810000)
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert [(i.mnemonic, i.op_str) for i in instructions] == [
        ("call", "0x810000"),
        ("mov", "eax, dword ptr [ecx + 4]"),
        ("push", "0x64"),
        ("pop", "ecx"),
        ("cdq", ""),
        ("idiv", "ecx"),
        ("dec", "eax"),
        ("ret", ""),
    ]
    assert GOG_BUILD.site("inventory.scrollbar_page_size_call").original == bytes.fromhex(
        "e8 78 06 00 00"
    )
