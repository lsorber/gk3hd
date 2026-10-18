"""Single native traversal, exact opaque mirroring and ordinary-draw recovery."""

from __future__ import annotations

import struct

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_EFLAGS, UC_X86_REG_ESP

from gk3hd.patch.definitions.vr_menu import build_menu_destination_scope
from gk3hd.patch.definitions.vr_menu_coverage import BODY_RECT, POPUP_RECT, POPUP_ROOT
from gk3hd.patch.definitions.vr_menu_mirror import build_menu_cache_mirror
from tests.unit.patch import test_vr_menu as fixtures

_MIRROR = 0x88B000


def _single_scope(*, toolbar: bool = False, coverage: int | None = None) -> bytes:
    return build_menu_destination_scope(
        wrapper_va=fixtures._ENTRY,
        state_va=fixtures._STATE,
        target_va=fixtures._TARGET,
        class_vtable=fixtures._CLASS,
        toolbar=toolbar,
        resolve_resource_va=fixtures._RESOLVE,
        resource_manager_va=fixtures._GLOBALS,
        back_surface_va=fixtures._GLOBALS + 4,
        directdraw_owner_va=fixtures._GLOBALS + 8,
        readable_iat_va=fixtures._GLOBALS + 12,
        blt_va=fixtures._BLT_THUNK,
        blt_fast_va=fixtures._FAST_THUNK,
        mirror_va=_MIRROR,
        coverage_va=coverage,
    )


@pytest.mark.parametrize("toolbar", [False, True])
@pytest.mark.parametrize("size", [(1024, 768), (1280, 800), (3840, 2160)])
def test_one_native_draw_supplies_both_views_without_leaving_bindings_changed(
    *, toolbar: bool, size: tuple[int, int]
) -> None:
    cpu, calls, original = fixtures._scope(qualified=True, toolbar=toolbar, size=size)
    cpu.mem_write(fixtures._ENTRY, _single_scope(toolbar=toolbar))
    cpu.mem_write(_MIRROR, bytes.fromhex("b8 01 00 00 00 c3"))
    observations: list[bool] = []

    def mirror(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address == _MIRROR:
            assert fixtures._words(machine, fixtures._RESOURCE + 0x30) == fixtures._ORIGINAL
            assert fixtures._words(machine, fixtures._OWNED_CACHE) == fixtures._CACHE_VTABLE
            assert fixtures._words(machine, fixtures._STATE + 20) == 0
            assert fixtures._words(machine, fixtures._STATE + 0x70) == 0
            observations.append(True)

    cpu.hook_add(UC_HOOK_CODE, mirror)
    cpu.emu_start(fixtures._ENTRY, fixtures._RETURN, count=4000)
    assert calls == [(fixtures._ROOT, 1234, fixtures._STATE + 0x150, fixtures._STATE + 0x100)]
    assert observations == [True]
    assert cpu.mem_read(fixtures._ORIGINAL, 80) == original
    assert fixtures._words(cpu, fixtures._STATE + 0x70) == 1
    fixtures._assert_return(cpu)


@pytest.mark.parametrize("fault", ["mirror", "child", "footprint"])
def test_failed_capture_or_mirror_redraws_with_the_original_damage_and_withholds_publication(
    fault: str,
) -> None:
    cpu, calls, original = fixtures._scope(qualified=True)
    coverage = fixtures._COVERAGE if fault == "footprint" else None
    cpu.mem_write(fixtures._ENTRY, _single_scope(coverage=coverage))
    cpu.mem_write(_MIRROR, b"\xb8" + struct.pack("<I", int(fault != "mirror")) + b"\xc3")
    cpu.mem_write(fixtures._COVERAGE, bytes.fromhex("31 c0 c3"))
    if fault == "child":
        cpu.mem_write(fixtures._BLT, bytes.fromhex("b8 05 40 00 80 c2 18 00"))
    cpu.emu_start(fixtures._ENTRY, fixtures._RETURN, count=4000)
    assert calls == [
        (fixtures._ROOT, 1234, fixtures._STATE + 0x150, fixtures._STATE + 0x100),
        (fixtures._ROOT, 1234, 4567, fixtures._ORIGINAL),
    ]
    assert fixtures._words(cpu, fixtures._STATE + 0x70) == 0
    assert fixtures._words(cpu, fixtures._RESOURCE + 0x30) == fixtures._ORIGINAL
    assert cpu.mem_read(fixtures._ORIGINAL, 80) == original
    fixtures._assert_return(cpu)


@pytest.mark.parametrize(
    "fault",
    [
        "disabled",
        "busy",
        "hidden",
        "foreign_class",
        "cache_missing",
        "wrong_dd",
        "foreign_page",
        "stale_width",
        "stale_height",
        "bad_wrapper",
        "resource_missing",
    ],
)
def test_ineligible_single_capture_still_draws_normally(fault: str) -> None:
    cpu, calls, _original = fixtures._scope(qualified=fault != "busy", state=fault)
    cpu.mem_write(fixtures._ENTRY, _single_scope())
    cpu.emu_start(fixtures._ENTRY, fixtures._RETURN, count=4000)
    assert calls == [(fixtures._ROOT, 1234, 4567, fixtures._ORIGINAL)]
    assert fixtures._words(cpu, fixtures._STATE + 0x70) == 0
    fixtures._assert_return(cpu)


@pytest.mark.parametrize("result", [0, 9876, 0x80004005, 0xFFFFFFFF])
@pytest.mark.parametrize("flags", [0x202, 0x246, 0xA97])
def test_mirroring_does_not_replace_native_return_registers_or_flags(
    result: int, flags: int
) -> None:
    cpu, calls, _original = fixtures._scope(qualified=True)
    cpu.mem_write(fixtures._ENTRY, _single_scope())
    target = bytes(cpu.mem_read(fixtures._TARGET, 0x100))
    suffix = bytes.fromhex("b8 94 26 00 00 c2 08 00")
    at = target.index(suffix)
    cpu.mem_write(
        fixtures._TARGET + at,
        b"\xb8"
        + struct.pack("<I", result)
        + bytes.fromhex("ba 78 56 34 12 68")
        + struct.pack("<I", flags)
        + bytes.fromhex("9d c2 08 00"),
    )
    cpu.mem_write(_MIRROR, bytes.fromhex("b8 01 00 00 00 31 d2 c3"))
    cpu.emu_start(fixtures._ENTRY, fixtures._RETURN, count=4000)
    assert len(calls) == 1
    assert cpu.reg_read(UC_X86_REG_EAX) == result
    assert cpu.reg_read(UC_X86_REG_EDX) == 0x12345678
    assert cpu.reg_read(UC_X86_REG_EFLAGS) == flags
    assert cpu.reg_read(UC_X86_REG_ESP) == fixtures._STACK + 12


@pytest.mark.parametrize("toolbar", [False, True])
@pytest.mark.parametrize("failure", [0, 1, 2])
def test_mirror_preserves_room_gaps_clips_without_scaling_and_reports_failed_copies(
    *, toolbar: bool, failure: int
) -> None:
    entry, state, wrapper, page, table, blt, stop, stack = range(0x100000, 0x108000, 0x1000)
    cache = 0xABCDEF
    width, height = 20, 10
    body, popup = (-3, -2, 9, 4), (5, 4, 12, 13)
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(entry, 0x10000)
    fixtures._write(cpu, state + 4, cache, width, height)
    fixtures._write(cpu, state + 28, wrapper)
    fixtures._write(cpu, wrapper + 0x2C, page)
    fixtures._write(cpu, page, table)
    fixtures._write(cpu, table + 0x14, blt)
    for offset, rectangle in ((0x180, body), (BODY_RECT, body), (POPUP_RECT, popup)):
        cpu.mem_write(state + offset, struct.pack("<4i", *rectangle))
    fixtures._write(cpu, state + POPUP_ROOT, int(toolbar))
    cpu.mem_write(entry, build_menu_cache_mirror(wrapper_va=entry, state_va=state, toolbar=toolbar))
    cpu.mem_write(blt, bytes.fromhex("c2 18 00"))
    pixels = [[999] * width for _ in range(height)]
    rectangles: list[tuple[int, ...]] = []

    def copy(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address != blt:
            return
        args = struct.unpack("<6I", machine.mem_read(machine.reg_read(UC_X86_REG_ESP) + 4, 24))
        assert args[0] == page
        assert args[2] == cache
        assert args[4:] == (0x1000000, 0)
        rect = struct.unpack("<4i", machine.mem_read(args[1], 16))
        assert rect == struct.unpack("<4i", machine.mem_read(args[3], 16))
        assert 0 <= rect[0] < rect[2] <= width
        assert 0 <= rect[1] < rect[3] <= height
        rectangles.append(rect)
        failed = len(rectangles) == failure
        if not failed:
            for y in range(rect[1], rect[3]):
                for x in range(rect[0], rect[2]):
                    pixels[y][x] = x + y * width
        machine.reg_write(UC_X86_REG_EAX, 0x80004005 if failed else 0)

    cpu.hook_add(UC_HOOK_CODE, copy)
    fixtures._write(cpu, stack, stop)
    cpu.reg_write(UC_X86_REG_ESP, stack)
    cpu.reg_write(UC_X86_REG_EFLAGS, 0x246)
    cpu.emu_start(entry, stop, count=1000)
    expected = [(0, 0, 9, 4)] + ([(5, 4, 12, 10)] if toolbar and failure != 1 else [])
    assert rectangles == expected
    assert cpu.reg_read(UC_X86_REG_EAX) == int(failure == 0 or failure > len(expected))
    assert cpu.reg_read(UC_X86_REG_ESP) == stack + 4
    assert cpu.reg_read(UC_X86_REG_EFLAGS) == 0x246
    for y in range(height):
        for x in range(width):
            covered = any(
                left <= x < right and top <= y < bottom
                for index, (left, top, right, bottom) in enumerate(expected, 1)
                if index != failure
            )
            assert pixels[y][x] == (x + y * width if covered else 999)
