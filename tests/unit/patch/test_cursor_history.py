"""Cursor history changes require an explicit per-surface renderer capability."""

from __future__ import annotations

import struct

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.runtime2d.cursor_history import (
    HISTORY_OFFSET,
    build_history_adapter,
    emit_history_adapter,
)


def test_history_adapter_preserves_native_count_before_capability_query() -> None:
    code = build_history_adapter(profile=GOG_BUILD, control_va=0x800000)
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(code, 0x800000 + HISTORY_OFFSET))
    assert sum(i.size for i in instructions) == len(code)
    ops = [(i.mnemonic, i.op_str) for i in instructions]
    assert len(code) <= 0x100
    assert ops[:6] == [
        ("push", "ebx"),
        ("push", "esi"),
        ("push", "edi"),
        ("mov", "esi, ecx"),
        ("call", "0x55c670"),
        ("mov", "ebx, eax"),
    ]
    assert ("cmp", "eax, 2") in ops
    assert ("cmp", "eax, 1") in ops
    assert ("push", "dword ptr [esi + 0x18]") in ops
    assert ("mov", "eax, dword ptr [eax + 0x2c]") in ops
    assert ops[-5:] == [
        ("mov", "eax, ebx"),
        ("pop", "edi"),
        ("pop", "esi"),
        ("pop", "ebx"),
        ("ret", ""),
    ]


def test_history_names_and_cache_have_separate_bounded_storage() -> None:
    payload = SegmentPayloadBuilder(owner="test", segment="controls", size=0x6000)
    emit_history_adapter(profile=GOG_BUILD, payload=payload, control_va=0x800000)
    data = payload.build()
    assert data[0x3A00:0x3A10] == b"ddraw.dll\0".ljust(16, b"\0")
    assert data[0x3A10:0x3A29] == b"Gk3hdSurfaceHistoryDepth\0"
    assert data[0x3A40:0x3A44] == bytes(4)
    site = GOG_BUILD.site("cursor.restore_history_query")
    assert site.original == b"\xe8" + struct.pack("<i", 0x55C670 - site.va - 5)
