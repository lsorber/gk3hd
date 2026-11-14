"""Native toolbar/list coverage, without inferring opacity from pixel colors."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.binary.x86 import Condition, X86Emitter

if TYPE_CHECKING:
    from gk3hd.patch.definitions.runtime2d.system.menu_exports import NativeMenuHooksABI

BODY_RECT = 0x190
POPUP_RECT = 0x1A0
POPUP_ROOT = 0x1B0
COVERAGE_READY = 0x1B4
RAW_ROOT = 0x1C0
RAW_POPUP = 0x1D0
SAVED_BOTTOM = 0x1E0


@dataclass(frozen=True, slots=True)
class MenuCoverageABI:
    """Qualified physical crops sharing one current native menu surface."""

    body_rect_va: int
    popup_rect_va: int
    popup_root_va: int
    ready_va: int
    capture_va: int
    validate_va: int


def build_menu_coverage_capture(
    *,
    wrapper_va: int,
    state_va: int,
    hooks: NativeMenuHooksABI,
    dropdown_vtable: int,
    readable_iat_va: int,
) -> bytes:
    """Snapshot the exact final native footprint after a complete isolated draw.

    A visible list enlarges the parent's union bounds but does not fill the
    gaps beside its lower rows. Retain the preceding body bottom and the live
    popup separately, transformed by the native toolbar affine. The root/list
    geometry and identity are snapshotted for validation before consumption.
    Return boolean EAX, preserving other registers and flags.
    """
    e = X86Emitter(base_va=wrapper_va)

    def absolute(opcode: bytes, address: int, suffix: bytes = b"") -> None:
        e.raw(opcode + struct.pack("<I", address) + suffix)

    def state(opcode: bytes, offset: int, suffix: bytes = b"") -> None:
        absolute(opcode, state_va + offset, suffix)

    def copy(source: int, destination: int) -> None:
        state(b"\xbe", source)
        state(b"\xbf", destination)
        e.raw(bytes.fromhex("b9 04 00 00 00 fc f3 a5"))

    def readable(register: bytes, size: int) -> None:
        e.push_imm32(size)
        e.raw(register)
        absolute(b"\xff\x15", readable_iat_va)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "failed")

    def bounded_rectangle(offset: int) -> None:
        # Bounds keep signed affine multiplication below INT32_MAX at every
        # cache-supported height. Reject damaged geometry instead of wrapping.
        for edge in range(0, 16, 4):
            state(b"\xa1", offset + edge)
            e.raw(bytes.fromhex("3d 00 80 ff ff"))
            e.jump_if(Condition.LESS, "failed")
            e.raw(bytes.fromhex("3d 00 80 00 00"))
            e.jump_if(Condition.GREATER, "failed")
        for low, high in ((0, 8), (4, 12)):
            state(b"\xa1", offset + high)
            state(b"\x3b\x05", offset + low)
            e.jump_if(Condition.LESS_OR_EQUAL, "failed")

    e.raw(bytes.fromhex("9c 60"))
    for offset in (COVERAGE_READY, POPUP_ROOT):
        state(b"\xc7\x05", offset, bytes(4))
    state(b"\x8b\x35", 32)
    e.raw(bytes.fromhex("85 f6"))
    e.jump_if(Condition.EQUAL, "failed")
    readable(b"\x56", 0x2C)
    e.raw(b"\x81\x3e" + struct.pack("<I", hooks.toolbar.vtable_va))
    e.jump_if(Condition.NOT_EQUAL, "failed")
    e.raw(bytes.fromhex("80 7e 18 00"))
    e.jump_if(Condition.EQUAL, "failed")
    e.raw(bytes.fromhex("83 c6 1c"))
    state(b"\xbf", RAW_ROOT)
    e.raw(bytes.fromhex("b9 04 00 00 00 fc f3 a5"))
    bounded_rectangle(RAW_ROOT)
    absolute(b"\x8b\x1d", hooks.dropdown_pending_va)
    e.raw(bytes.fromhex("85 db"))
    e.jump_if(Condition.NOT_EQUAL, "popup")
    copy(0x180, BODY_RECT)
    e.jump("accepted")
    e.label("popup")
    readable(b"\x53", 0x178)
    e.raw(b"\x81\x3b" + struct.pack("<I", dropdown_vtable))
    e.jump_if(Condition.NOT_EQUAL, "failed")
    e.raw(bytes.fromhex("80 7b 18 00"))
    e.jump_if(Condition.EQUAL, "failed")
    absolute(b"\x83\x3d", hooks.dropdown_bottom_valid_va, b"\x01")
    e.jump_if(Condition.NOT_EQUAL, "failed")
    state(b"\x89\x1d", POPUP_ROOT)
    e.raw(bytes.fromhex("8d 73 1c"))
    state(b"\xbf", RAW_POPUP)
    e.raw(bytes.fromhex("b9 04 00 00 00 fc f3 a5"))
    bounded_rectangle(RAW_POPUP)
    copy(RAW_ROOT, BODY_RECT)
    copy(RAW_POPUP, POPUP_RECT)
    absolute(b"\xa1", hooks.dropdown_saved_bottom_va)
    state(b"\x3b\x05", RAW_ROOT + 4)
    e.jump_if(Condition.LESS_OR_EQUAL, "failed")
    state(b"\x3b\x05", RAW_ROOT + 12)
    e.jump_if(Condition.GREATER, "failed")
    state(b"\xa3", SAVED_BOTTOM)
    state(b"\xa3", BODY_RECT + 12)
    for first, center in ((0, 126), (4, 37)):
        state(b"\x8b\x1d", RAW_ROOT + first)
        e.raw(b"\x83\xc3" + bytes((center,)))
        for rectangle in (BODY_RECT, POPUP_RECT):
            for edge in (first, first + 8):
                state(b"\xa1", rectangle + edge)
                e.raw(bytes.fromhex("2b c3"))
                state(b"\x0f\xaf\x05", 12)
                e.raw(bytes.fromhex("99 b9 00 03 00 00 f7 f9 03 c3"))
                state(b"\xa3", rectangle + edge)
    # The ordinary body's other edges must still describe the captured root.
    for edge in (0, 4, 8):
        state(b"\xa1", BODY_RECT + edge)
        state(b"\x3b\x05", 0x180 + edge)
        e.jump_if(Condition.NOT_EQUAL, "failed")
    state(b"\xa1", BODY_RECT + 12)
    state(b"\x3b\x05", 0x180 + 12)
    e.jump_if(Condition.GREATER, "failed")
    e.label("accepted")
    state(b"\xc7\x05", COVERAGE_READY, struct.pack("<I", 1))
    e.raw(bytes.fromhex("c7 44 24 1c 01 00 00 00"))
    e.jump("return")
    e.label("failed")
    e.raw(bytes.fromhex("c7 44 24 1c 00 00 00 00"))
    e.label("return")
    e.raw(bytes.fromhex("61 9d c3"))
    return e.build()


def build_menu_coverage_validate(
    *,
    wrapper_va: int,
    state_va: int,
    hooks: NativeMenuHooksABI,
    dropdown_vtable: int,
    readable_iat_va: int,
) -> bytes:
    """Reject a footprint changed since its successful native capture.

    The caller first qualifies cache surface, root lifetime and native page
    generation. This additionally checks retained popup identity, visibility,
    both raw geometries and pre-union bottom. Failure withdraws coverage;
    another successful native capture is required before retrying publication.
    """
    e = X86Emitter(base_va=wrapper_va)

    def absolute(opcode: bytes, address: int, suffix: bytes = b"") -> None:
        e.raw(opcode + struct.pack("<I", address) + suffix)

    def state(opcode: bytes, offset: int, suffix: bytes = b"") -> None:
        absolute(opcode, state_va + offset, suffix)

    def readable(register: bytes, size: int) -> None:
        e.push_imm32(size)
        e.raw(register)
        absolute(b"\xff\x15", readable_iat_va)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "failed")

    def compare_rectangle(offset: int) -> None:
        for edge in range(0, 16, 4):
            e.raw(b"\x8b\x46" + bytes((0x1C + edge,)))
            state(b"\x3b\x05", offset + edge)
            e.jump_if(Condition.NOT_EQUAL, "failed")

    e.raw(bytes.fromhex("9c 60"))
    state(b"\x83\x3d", COVERAGE_READY, b"\x01")
    e.jump_if(Condition.NOT_EQUAL, "failed")
    state(b"\x8b\x35", 32)
    e.raw(bytes.fromhex("85 f6"))
    e.jump_if(Condition.EQUAL, "failed")
    readable(b"\x56", 0x2C)
    compare_rectangle(RAW_ROOT)
    absolute(b"\x8b\x35", hooks.dropdown_pending_va)
    state(b"\x3b\x35", POPUP_ROOT)
    e.jump_if(Condition.NOT_EQUAL, "failed")
    e.raw(bytes.fromhex("85 f6"))
    e.jump_if(Condition.EQUAL, "accepted")
    readable(b"\x56", 0x178)
    e.raw(b"\x81\x3e" + struct.pack("<I", dropdown_vtable))
    e.jump_if(Condition.NOT_EQUAL, "failed")
    e.raw(bytes.fromhex("80 7e 18 00"))
    e.jump_if(Condition.EQUAL, "failed")
    absolute(b"\x83\x3d", hooks.dropdown_bottom_valid_va, b"\x01")
    e.jump_if(Condition.NOT_EQUAL, "failed")
    absolute(b"\xa1", hooks.dropdown_saved_bottom_va)
    state(b"\x3b\x05", SAVED_BOTTOM)
    e.jump_if(Condition.NOT_EQUAL, "failed")
    compare_rectangle(RAW_POPUP)
    e.label("accepted")
    e.raw(bytes.fromhex("c7 44 24 1c 01 00 00 00"))
    e.jump("return")
    e.label("failed")
    state(b"\xc7\x05", COVERAGE_READY, bytes(4))
    e.raw(bytes.fromhex("c7 44 24 1c 00 00 00 00"))
    e.label("return")
    e.raw(bytes.fromhex("61 9d c3"))
    return e.build()
