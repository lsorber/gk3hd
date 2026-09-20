"""GPS presentation owns exact scene members, not all shared bitmap controls."""

from __future__ import annotations

import struct

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.runtime2d.gps import (
    AUXILIARY_FIELD,
    DEPTH_OFFSET,
    DRAW_SITES,
    INPUT_SITES,
    MEMBER_FIELDS,
    MEMBER_OFFSET,
    OWNER_OFFSET,
    GPSFeatureCompiler,
    build_draw,
    build_input,
    build_member,
    build_transfer,
)
from gk3hd.patch.definitions.runtime2d.layout import GPS_SEGMENT, GPS_TRANSFER_OFFSET


def _ops(data: bytes, address: int = 0x800000) -> list[tuple[str, str]]:
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(data, address))
    assert sum(i.size for i in instructions) == len(data)
    return [(i.mnemonic, i.op_str) for i in instructions]


def test_gps_payload_bounds_and_native_hooks() -> None:
    payload, _ = GPSFeatureCompiler(profile=GOG_BUILD).build(0x800000)
    assert len(payload) == GPS_SEGMENT.size
    assert payload[:8] == GPS_SEGMENT.magic
    assert payload[OWNER_OFFSET : DEPTH_OFFSET + 4] == bytes(8)
    assert payload[MEMBER_OFFSET : MEMBER_OFFSET + 2] == b"\x50\x52"
    assert payload[GPS_TRANSFER_OFFSET] == 0x60
    assert set(DRAW_SITES) == {
        "gps.bitmap_draw",
        "gps.button_draw",
        "gps.text_draw",
        "gps.auxiliary_draw",
    }
    # Do not map outer Move/Release delegates or keyboard callbacks as POINTs.
    assert [GOG_BUILD.site(name).va for name in INPUT_SITES] == [
        0x668974,
        0x6689C4,
        0x6689FC,
        0x675C78,
    ]
    show = GOG_BUILD.site("gps.show")
    assert show.original in payload[0x100:0x140]
    destroy = GOG_BUILD.site("gps.destroy")
    assert destroy.original in payload[0x140:0x180]


def test_gps_identity_uses_members_and_nullable_auxiliary_pointer() -> None:
    data = build_member(wrapper_va=0x800000, owner_va=0x810000)
    ops = _ops(data)
    assert ops[:3] == [("push", "eax"), ("push", "edx"), ("test", "ecx, ecx")]
    for offset in MEMBER_FIELDS:
        assert b"\x8d\x90" + struct.pack("<I", offset) in data
    assert b"\x3b\x88" + struct.pack("<I", AUXILIARY_FIELD) in data
    assert ops[-4:] == [("pop", "edx"), ("pop", "eax"), ("stc", ""), ("ret", "")]


def test_gps_draw_balances_scope_and_preserves_native_arguments() -> None:
    ops = _ops(
        build_draw(wrapper_va=0x800000, member_va=0x810000, depth_va=0x820000, native_va=0x46709A)
    )
    assert ("inc", "dword ptr [0x820000]") in ops
    assert ops.count(("push", "dword ptr [esp + 8]")) == 2
    assert ("dec", "dword ptr [0x820000]") in ops
    assert ("ret", "8") in ops
    assert ops[-1] == ("jmp", "0x46709a")


def test_gps_point_and_rectangle_use_wide_signed_floor_arithmetic() -> None:
    point = _ops(
        build_input(wrapper_va=0x800000, member_va=0x810000, height_va=0x820004, native_va=0x447403)
    )
    assert point.count(("imul", "ebx")) == 2
    assert point.count(("add", "eax, 0x2ff")) == 2
    assert point.count(("adc", "edx, 0")) == 2
    assert point.count(("idiv", "ebx")) == 2
    assert ("lea", "eax, [ebp - 8]") in point
    assert ("ret", "4") in point
    transfer = _ops(
        build_transfer(
            wrapper_va=0x800000, depth_va=0x810000, dimensions_va=0x820000, rect_va=0x830000
        )
    )
    assert transfer.count(("imul", "dword ptr [0x820004]")) == 4
    assert transfer.count(("idiv", "ebx")) == 4
    assert ("mov", "dword ptr [edi + 0x28], 0x830000") in transfer
    assert ("mov", "dword ptr [esp + 0x1c], 1") in transfer
    assert ("mov", "dword ptr [esp + 0x1c], 0") in transfer
