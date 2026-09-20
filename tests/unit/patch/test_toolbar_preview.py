"""Selected-item preview ownership, logical bounds, and dense source contracts."""

from __future__ import annotations

import struct

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

from gk3hd.patch.binary.x86 import X86Emitter
from gk3hd.patch.definitions.runtime2d.system.toolbar_preview import (
    build_preview_prepare,
    emit_preview_dimensions,
    emit_preview_source,
)


def test_preview_prepare_resolves_embedded_control_and_preserves_physical_surface() -> None:
    payload = build_preview_prepare(
        wrapper_va=0x800000, surface_va=0x810000, manager_va=0x6FF838, resolve_va=0x5343A0
    )
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in instructions) == len(payload)
    assert len(payload) <= 0xE0
    assert b"\x8d\xb1\xc8\x0a\x00\x00\x8b\x46\x2c" in payload
    assert b"\x8b\x40\x30" in payload
    # Both 32x30 and 30x32 orientations are accepted only at exactly 4x.
    assert b"\x81\xf9\x80\x00\x00\x00" in payload
    assert b"\x81\xfa\x80\x00\x00\x00" in payload
    assert b"\x83\xf9\x78" in payload
    assert b"\x83\xfa\x78" in payload
    assert b"\x83\xfa\x7c" in payload  # blue apple keeps its native 31px height
    assert b"\x03\x4e\x1c\x03\x56\x20\x89\x4e\x24\x89\x56\x28" in payload
    assert payload.endswith(b"\x61\xc3")


def test_preview_dimensions_require_exact_surface_and_toolbar_owner() -> None:
    code = X86Emitter(base_va=0x800000)
    emit_preview_dimensions(
        code,
        surface_va=0x810000,
        logical_va=0x810010,
        root_va=0x810020,
        vtable_va=0x684FA4,
    )
    code.label("done")
    code.raw(b"\xc3")
    payload = code.build()
    assert payload.startswith(b"\x3b\x05" + struct.pack("<I", 0x810000))
    assert b"\x81\x39" + struct.pack("<I", 0x684FA4) in payload
    for offset, target in ((0x38, 0x810010), (0x3C, 0x810014)):
        assert (
            b"\x8b\x50" + bytes([offset]) + b"\xc1\xfa\x02\x89\x15" + struct.pack("<I", target)
            in payload
        )


def test_preview_source_scales_every_clipped_edge_without_changing_destination() -> None:
    code = X86Emitter(base_va=0x800000)
    emit_preview_source(code, surface_va=0x810000, scratch_va=0x810010)
    payload = code.build()
    assert b"\x3b\x45\x24" in payload  # exact resolved source wrapper
    assert b"\x8b\x7d\x2c\x85\xff" in payload  # null means full physical image
    for offset in range(0, 16, 4):
        assert b"\x8b\x47" + bytes([offset]) + b"\xc1\xe0\x02" in payload
    assert b"\xc7\x45\x2c" + struct.pack("<I", 0x810010) in payload
    assert b"\xc7\x45\x28" not in payload  # destination pointer is never replaced
