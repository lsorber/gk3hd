"""SIDNEY illustration identity, logical size, and physical sampling contracts."""

from __future__ import annotations

import struct

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

from gk3hd.patch.binary.x86 import X86Emitter
from gk3hd.patch.definitions.runtime2d.sidney_images import (
    FINGERPRINT_IDS,
    FINGERPRINT_SURFACES_SIZE,
    IMAGES,
    SURFACES_SIZE,
    build_fingerprint_dimensions,
    build_image_dimensions,
    build_source,
    emit_dimensions,
)


def test_paintings_keep_authored_extents_and_use_separate_logical_scratch() -> None:
    assert IMAGES[3:] == ((b"poussin", 407, 271), (b"teniers", 464, 309))
    payload = build_image_dimensions(wrapper_va=0x800000, surfaces_va=0x810000)
    decoded = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in decoded) == len(payload)
    assert len(payload) <= 0x300
    # These last chunks include the exact NUL: a zoom or similarly named
    # resource must never inherit the parent painting's logical dimensions.
    for suffix in (b"sin\0", b"ers\0"):
        assert b"\x81\xfa" + suffix in payload
    source = build_source(
        wrapper_va=0x820000,
        surfaces_va=0x810000,
        scratch_va=0x810000 + SURFACES_SIZE,
        fingerprint_surfaces_va=0x830000,
    )
    for index, (_, width, height) in enumerate(IMAGES):
        slot = 0x810000 + index * 4
        assert b"\xc7\x05" + struct.pack("<I", slot) + bytes(4) in payload
        assert b"\xa3" + struct.pack("<I", slot) in payload
        assert b"\x3b\x05" + struct.pack("<I", slot) in source
        for offset, value in ((0x38, width * 4), (0x3C, height * 4)):
            check = b"\x81\x78" + bytes([offset]) + struct.pack("<I", value)
            assert check in payload
            assert check in source
    logical = 0x810000 + SURFACES_SIZE + 16
    assert b"\xb8" + struct.pack("<I", logical) + b"\xf9\xc3\xf8\xc3" in payload
    assert b"\x89\x15" + struct.pack("<I", logical + 4) in payload
    assert len(source) <= 0x180


def test_fingerprint_helper_requires_complete_names_and_exact_fourfold_dimensions() -> None:
    payload = build_fingerprint_dimensions(wrapper_va=0x800000, surfaces_va=0x810000)
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in instructions) == len(payload)
    assert len(payload) <= 0x200
    assert FINGERPRINT_SURFACES_SIZE == 40
    assert b"\x81\xfa\x73\x7f\x00\x00" in payload  # exact folded S_
    assert b"\x81\xfaint\0" in payload  # exact suffix includes terminator
    for index, name in enumerate(FINGERPRINT_IDS):
        assert b"\x81\xfa" + name + b"\0" in payload
        assert b"\xbb" + struct.pack("<I", 0x810000 + index * 4) in payload
    assert b"\xc7\x03" + bytes(4) in payload  # clear stale named-source identity
    for offset, dimension in ((0x38, 164), (0x3C, 204)):
        assert b"\x81\x78" + bytes([offset]) + struct.pack("<I", dimension) in payload
    assert b"\x89\x03\xb8" + struct.pack("<I", 0x810028) in payload
    assert payload.endswith(b"\x5b\xf9\xc3\x5b\xf8\xc3")


def test_fingerprint_source_uses_retained_identity_and_keeps_native_destination() -> None:
    payload = build_source(
        wrapper_va=0x800000,
        surfaces_va=0x810000,
        fingerprint_surfaces_va=0x820000,
        scratch_va=0x81000C,
    )
    assert b"\xba" + struct.pack("<I", 0x820000) in payload
    assert b"\xb9\x0a\x00\x00\x00" in payload
    assert b"\x3b\x02" in payload
    assert b"\xc7\x45\x08" not in payload
    assert len(payload) <= 0x180


def test_mugshot_dimensions_require_both_complete_names_and_exact_density() -> None:
    code = X86Emitter(base_va=0x800000)
    emit_dimensions(code, surfaces_va=0x810000)
    code.label("dense")
    code.raw(b"\xc3")
    code.label("native")
    code.raw(b"\xc3")
    payload = code.build()
    decoded = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(instruction.size for instruction in decoded) == len(payload)
    for prefix in (b"gab\x7f", b"gra\x7f"):
        assert b"\x81\xfa" + prefix in payload
    # The NUL remains exact: case-folding must not turn it into a wildcard.
    assert payload.count(b"\x81\xca\x20\x20\x20\x00") == 4
    assert payload.count(b"\x81\xfa" + b"hot\x00") == 2
    for offset, size in ((0x38, 268), (0x3C, 312)):
        assert payload.count(b"\x81\x78" + bytes([offset]) + struct.pack("<I", size)) == 2
    for slot in (0x810000, 0x810004):
        assert b"\xc7\x05" + struct.pack("<I", slot) + bytes(4) in payload
        assert b"\xa3" + struct.pack("<I", slot) in payload


def test_mugshot_sampling_keeps_caller_destination_and_source_rect_immutable() -> None:
    payload = build_source(
        wrapper_va=0x800000,
        surfaces_va=0x810000,
        scratch_va=0x810008,
        fingerprint_surfaces_va=0x820000,
    )
    decoded = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(instruction.size for instruction in decoded) == len(payload)
    assert payload.startswith(b"\x60\x8d\x6c\x24\x24")
    for slot in (0x810000, 0x810004):
        assert b"\x3b\x05" + struct.pack("<I", slot) in payload
    for offset in range(0, 16, 4):
        assert b"\x8b\x46" + bytes([offset]) + b"\xc1\xe0\x02" in payload
        assert b"\xa3" + struct.pack("<I", 0x810008 + offset) in payload
    assert b"\xc7\x45\x0c" + struct.pack("<I", 0x810008) in payload
    assert b"\xc7\x45\x08" not in payload
    assert payload.endswith(b"\x61\xc3")


def test_email_crest_matches_complete_name_and_retains_its_own_aspect() -> None:
    assert IMAGES[2] == (b"s_schat_logo", 77, 76)
    assert SURFACES_SIZE == 20
    code = X86Emitter(base_va=0x800000)
    emit_dimensions(code, surfaces_va=0x810000)
    for label in ("dense", "native"):
        code.label(label)
        code.raw(b"\xc3")
    dimensions = code.build()
    # Thirteen-byte terminated name: the last chunk compares only the NUL,
    # independently of whatever bytes follow it in the native resource object.
    assert b"\x8b\x56\x14\x81\xe2\xff\x00\x00\x00" in dimensions
    assert b"\xa3" + struct.pack("<I", 0x810008) in dimensions
    source = build_source(
        wrapper_va=0x800000,
        surfaces_va=0x810000,
        scratch_va=0x81000C,
        fingerprint_surfaces_va=0x820000,
    )
    assert len(source) <= 0x180
    assert b"\x3b\x05" + struct.pack("<I", 0x810008) in source
    for payload in (dimensions, source):
        decoded = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
        assert sum(instruction.size for instruction in decoded) == len(payload)
        for offset, size in ((0x38, 308), (0x3C, 304)):
            assert b"\x81\x78" + bytes([offset]) + struct.pack("<I", size) in payload
