"""Dense laptop-frame retention, logical geometry, and source sampling contracts."""

from __future__ import annotations

import struct

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

from gk3hd.patch.binary.x86 import BranchOpcode, decode_rel32_branch
from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.runtime2d.sidney_frame import (
    FRAME_NAMES,
    FRAME_SIZES,
    FRAME_STRIDE,
    build_dimensions,
    build_discovery,
    build_resize,
    build_resize_thunk,
    build_source,
    frame_state,
)


def test_restored_frame_discovery_is_independent_of_resize_callbacks() -> None:
    payload = build_discovery(wrapper_va=0x800000, state_va=0x810000)
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in instructions) == len(payload)
    assert len(payload) <= 0x400
    assert payload.startswith(b"\x60")
    assert payload.endswith(b"\x61\xc3")
    for index, (name, size) in enumerate(zip(FRAME_NAMES, FRAME_SIZES, strict=True)):
        terminated = name + b"\0"
        for offset in range(0, len(terminated), 4):
            part = terminated[offset : offset + 4]
            mask = int.from_bytes(bytes(0x20 if byte else 0 for byte in part), "little")
            value = int.from_bytes(part, "little") | mask
            assert b"\x81\xfa" + struct.pack("<I", value) in payload
            if len(part) < 4:
                assert b"\x81\xe2" + struct.pack("<I", (1 << (8 * len(part))) - 1) in payload
        slot = struct.pack("<I", 0x810000 + index * FRAME_STRIDE)
        assert b"\xc7\x05" + slot + bytes(4) in payload
        assert b"\xa3" + slot in payload
        for offset, dimension in zip((0x38, 0x3C), size, strict=True):
            assert b"\x81\x78" + bytes([offset]) + struct.pack("<I", dimension * 4) in payload


def test_resize_sites_bind_both_lifetimes_to_the_same_four_sources() -> None:
    for index, side in enumerate(("top", "bottom", "left", "right")):
        for phase in ("create", "rebuild"):
            site = GOG_BUILD.site(f"sidney.frame.{phase}_{side}")
            assert (
                decode_rel32_branch(
                    opcode=BranchOpcode.CALL, site_va=site.va, instruction=site.original
                )
                == 0x534620
            )
        thunk = build_resize_thunk(wrapper_va=0x800000, resize_va=0x810000, index=index)
        assert thunk[:5] == b"\xba" + struct.pack("<I", index)
        assert len(thunk) <= 16
    assert struct.unpack("<15I", frame_state()) == (
        0,
        1024,
        144,
        0,
        1024,
        144,
        0,
        192,
        480,
        0,
        192,
        480,
        0,
        174,
        13,
    )


def test_resize_retains_only_exact_fourfold_sources_and_cleans_original_arguments() -> None:
    payload = build_resize(
        wrapper_va=0x800000, state_va=0x810000, resolve_va=0x534560, resize_va=0x534620
    )
    decoded = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in decoded) == len(payload)
    assert len(payload) <= 0x100
    assert b"\xff\x74\x24\x24" in payload  # original handle, not requested size
    assert b"\xc7\x03" + bytes(4) in payload  # clear old slot before resolving
    assert b"\x89\x03\x61\xc2\x0c\x00" in payload
    for logical, physical in ((4, 0x38), (8, 0x3C)):
        assert b"\x8b\x53" + bytes([logical]) + b"\xc1\xe2\x02" in payload
        assert b"\x39\x50" + bytes([physical]) in payload
    assert decoded[-1].mnemonic == "jmp"
    assert decoded[-1].op_str == "0x534620"  # unmatched sources retain native behavior


def test_dimensions_revalidate_density_and_source_mapping_does_not_mutate_destination() -> None:
    dimensions = build_dimensions(wrapper_va=0x800000, state_va=0x810000)
    assert b"\x3b\x02" in dimensions  # retained source identity
    assert b"\x5b\xf8\xc3" in dimensions  # no match, EAX unchanged, carry clear
    assert b"\x8d\x42\x04\x5b\xf9\xc3" in dimensions  # immutable logical pair
    for physical in (0x38, 0x3C):
        assert b"\x39\x58" + bytes([physical]) in dimensions
    payload = build_source(wrapper_va=0x800000, dimensions_va=0x810000, scratch_va=0x820000)
    assert b"\x8b\x75\x0c\x85\xf6" in payload  # NULL already means full source
    for offset in range(0, 16, 4):
        assert b"\x8b\x46" + bytes([offset]) + b"\xc1\xe0\x02" in payload
    assert b"\xc7\x45\x0c" in payload
    assert b"\xc7\x45\x08" not in payload
    assert FRAME_SIZES[2:] == ((192, 480), (192, 480), (174, 13))
    assert b"\xb9\x05\x00\x00\x00" in dimensions
