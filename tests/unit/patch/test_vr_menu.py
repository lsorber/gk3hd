"""Execute the native menu cache destination scope and original fallback."""

from __future__ import annotations

import struct

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EFLAGS,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.vr_menu import (
    build_menu_cache_blt_result,
    build_menu_destination_scope,
    menu_destination_state,
)

_ENTRY, _TARGET, _RESOLVE, _READABLE, _RETURN = range(0x880000, 0x885000, 0x1000)
_STATE, _ROOT, _RESOURCE, _ORIGINAL, _MANAGER, _GLOBALS, _STACK = range(0x900000, 0x907000, 0x1000)
_CLASS, _PAGE, _CACHE, _DD = 0x12345678, 0x123, 0x456, 0x789
_BLT_THUNK, _FAST_THUNK, _BLT, _FAST = range(0x885000, 0x889000, 0x1000)
_OWNED_CACHE, _CACHE_VTABLE = 0x908000, 0x909000
_COVERAGE = 0x88A000


def _write(cpu: Uc, address: int, *values: int) -> None:
    cpu.mem_write(address, struct.pack(f"<{len(values)}I", *values))


@pytest.mark.parametrize("toolbar", [False, True])
@pytest.mark.parametrize("size", [(1024, 768), (1280, 800), (3840, 2160)])
@pytest.mark.parametrize("rectangle", [(386, 347, 638, 422), (-31, -8, 221, 413)])
def test_owned_menu_uses_a_private_destination_and_restores_native_state(
    *, toolbar: bool, size: tuple[int, int], rectangle: tuple[int, int, int, int]
) -> None:
    cpu, calls, original = _scope(size=size, toolbar=toolbar, rectangle=rectangle)
    cpu.emu_start(_ENTRY, _RETURN, count=2000)
    assert calls == [
        (_ROOT, 1234, 4567, _ORIGINAL),
        (_ROOT, 1234, _STATE + 0x150, _STATE + 0x100),
    ]
    assert struct.unpack("<I", cpu.mem_read(_RESOURCE + 0x30, 4))[0] == _ORIGINAL
    assert cpu.mem_read(_ORIGINAL, 80) == original
    copied = struct.unpack("<20I", cpu.mem_read(_STATE + 0x100, 80))
    assert copied[10:12] == (0, _CACHE), "cache must not borrow the page's lock"
    assert copied[:10] == struct.unpack("<20I", original)[:10]
    assert copied[12:] == struct.unpack("<20I", original)[12:]
    assert struct.unpack("<4I", cpu.mem_read(_STATE + 0x160, 16)) == (0, 0, *size)
    assert struct.unpack("<I", cpu.mem_read(_STATE + 20, 4))[0] == 0
    assert struct.unpack("<I", cpu.mem_read(_STATE + 36, 4))[0] == 1
    expected = list(rectangle)
    if toolbar:
        for first, second, center in ((0, 2, 126), (1, 3, 37)):
            anchor = rectangle[first] + center
            for edge in (first, second):
                numerator = (rectangle[edge] - anchor) * size[1]
                expected[edge] = anchor + (abs(numerator) // 768) * (-1 if numerator < 0 else 1)
    assert struct.unpack("<4i", cpu.mem_read(_STATE + 0x180, 16)) == tuple(expected)
    _assert_return(cpu)


def test_menu_traversal_counter_wraps_without_leaving_the_destination_bound() -> None:
    cpu, calls, _original = _scope()
    _write(cpu, _STATE + 36, 0xFFFFFFFF)
    cpu.emu_start(_ENTRY, _RETURN, count=2000)
    assert len(calls) == 2
    assert struct.unpack("<I", cpu.mem_read(_STATE + 36, 4))[0] == 0
    assert struct.unpack("<I", cpu.mem_read(_RESOURCE + 0x30, 4))[0] == _ORIGINAL
    _assert_return(cpu)


@pytest.mark.parametrize("result", [0, 1, 0x80004005, 0x8876021C])
@pytest.mark.parametrize("fast", [False, True])
def test_native_child_failures_cannot_publish_an_interactive_menu(
    result: int, *, fast: bool
) -> None:
    cpu, calls, original = _scope(qualified=True)
    cpu.mem_write(_FAST if fast else _BLT, b"\xb8" + struct.pack("<I", result) + b"\xc2\x18\x00")
    _write(cpu, _STATE + 0x70, 1, 0xFFFFFFFF)
    table = bytes(cpu.mem_read(_CACHE_VTABLE, 144))
    cpu.emu_start(_ENTRY, _RETURN, count=4000)
    assert len(calls) == 2
    assert cpu.mem_read(_ORIGINAL, 80) == original
    assert _words(cpu, _RESOURCE + 0x30) == _ORIGINAL
    assert _words(cpu, _OWNED_CACHE) == _CACHE_VTABLE
    assert cpu.mem_read(_CACHE_VTABLE, 144) == table
    assert _words(cpu, _STATE + 0x64) == int(result != 0)
    assert _words(cpu, _STATE + 0x68) == 2
    assert _words(cpu, _STATE + 0x70) == int(result == 0)
    assert _words(cpu, _STATE + 0x74) == (0 if result == 0 else 0xFFFFFFFF)
    _assert_return(cpu)


def test_a_menu_traversal_without_child_transfers_cannot_publish() -> None:
    cpu, calls, _original = _scope(qualified=True)
    cpu.mem_write(_TARGET, bytes.fromhex("b8 94 26 00 00 c2 08 00"))
    _write(cpu, _STATE + 0x70, 1, 9)
    cpu.emu_start(_ENTRY, _RETURN, count=4000)
    assert len(calls) == 2
    assert _words(cpu, _STATE + 0x68) == 0
    assert _words(cpu, _STATE + 0x70) == 0
    assert _words(cpu, _STATE + 0x74) == 9
    assert _words(cpu, _OWNED_CACHE) == _CACHE_VTABLE
    _assert_return(cpu)


@pytest.mark.parametrize("generation", [0, 123, 0xFFFFFFFF])
def test_qualified_menu_records_the_native_page_generation(generation: int) -> None:
    cpu, _calls, _original = _scope(qualified=True)
    cpu.mem_write(
        _ENTRY,
        _capture_scope(qualified=True, generation_va=_GLOBALS + 16),
    )
    _write(cpu, _GLOBALS + 16, generation)
    cpu.emu_start(_ENTRY, _RETURN, count=4000)
    assert _words(cpu, _STATE + 0x70) == 1
    assert _words(cpu, _STATE + 0x78) == generation
    _assert_return(cpu)


@pytest.mark.parametrize("accepted", [False, True])
def test_coverage_qualification_runs_after_native_bindings_are_restored(*, accepted: bool) -> None:
    cpu, _calls, _original = _scope(qualified=True)
    cpu.mem_write(_ENTRY, _capture_scope(qualified=True, coverage_va=_COVERAGE))
    cpu.mem_write(_COVERAGE, b"\xb8" + struct.pack("<I", int(accepted)) + b"\xc3")
    observed: list[bool] = []

    def observe(machine: Uc, address: int, _size: int, _context: object) -> None:
        if address == _COVERAGE:
            assert _words(machine, _RESOURCE + 0x30) == _ORIGINAL
            assert _words(machine, _OWNED_CACHE) == _CACHE_VTABLE
            assert _words(machine, _STATE + 20) == 0
            assert _words(machine, _STATE + 0x68) == 2
            assert _words(machine, _STATE + 0x70) == 0
            observed.append(True)

    cpu.hook_add(UC_HOOK_CODE, observe)
    cpu.emu_start(_ENTRY, _RETURN, count=4000)
    assert observed == [True]
    assert _words(cpu, _STATE + 0x70) == int(accepted)
    assert _words(cpu, _STATE + 0x74) == int(accepted)
    _assert_return(cpu)


def test_footprint_cannot_be_qualified_without_child_transfer_results() -> None:
    with pytest.raises(
        ValueError, match="footprint qualification requires qualified child transfers"
    ):
        _capture_scope(coverage_va=_COVERAGE)


@pytest.mark.parametrize(
    "fault",
    ["valid", "disabled", "busy", "hidden", "foreign_class", "cache_missing", "foreign_page"],
)
def test_capture_only_never_draws_into_the_desktop_even_when_capture_is_unavailable(
    fault: str,
) -> None:
    cpu, calls, original = _scope(qualified=True, state=fault)
    cpu.mem_write(_ENTRY, _capture_scope(qualified=True, capture_only=True))
    cpu.emu_start(_ENTRY, _RETURN, count=4000)
    assert len(calls) == (1 if fault == "valid" else 0)
    assert all(call[3] == _STATE + 0x100 for call in calls)
    assert cpu.mem_read(_ORIGINAL, 80) == original
    assert _words(cpu, _RESOURCE + 0x30) == _ORIGINAL
    assert _words(cpu, _STATE + 20) == (1 if fault == "busy" else 0)


def test_capture_only_rejects_a_failed_child_without_native_fallback() -> None:
    cpu, calls, _original = _scope(qualified=True)
    cpu.mem_write(_ENTRY, _capture_scope(qualified=True, capture_only=True))
    cpu.mem_write(_BLT, bytes.fromhex("b8 05 40 00 80 c2 18 00"))
    cpu.emu_start(_ENTRY, _RETURN, count=4000)
    assert len(calls) == 1
    assert calls[0][3] == _STATE + 0x100
    assert _words(cpu, _STATE + 0x70) == 0
    assert _words(cpu, _RESOURCE + 0x30) == _ORIGINAL


def _words(cpu: Uc, address: int) -> int:
    return struct.unpack("<I", cpu.mem_read(address, 4))[0]


@pytest.mark.parametrize(
    "state",
    [
        "disabled",
        "unknown_mode",
        "busy",
        "hidden",
        "foreign_class",
        "cache_missing",
        "dd_missing",
        "wrong_dd",
        "manager_missing",
        "table_missing",
        "resource_missing",
        "wrapper_missing",
        "foreign_page",
        "page_missing",
        "cache_is_page",
        "stale_width",
        "stale_height",
        "negative_width",
        "negative_height",
        "oversized_width",
        "oversized_height",
        "bad_manager",
        "bad_resource",
        "bad_wrapper",
    ],
)
def test_invalid_menu_capture_keeps_the_original_draw_and_destination(state: str) -> None:
    cpu, calls, original = _scope(state=state)
    resource_binding = bytes(cpu.mem_read(_RESOURCE + 0x30, 4))
    cpu.emu_start(_ENTRY, _RETURN, count=2000)
    assert len(calls) == 1
    assert calls[0][:3] == (_ROOT, 1234, 4567)
    assert cpu.mem_read(_RESOURCE + 0x30, 4) == resource_binding
    assert cpu.mem_read(_ORIGINAL, 80) == original
    assert struct.unpack("<I", cpu.mem_read(_STATE + 36, 4))[0] == 0
    _assert_return(cpu)


def _assert_return(cpu: Uc) -> None:
    assert cpu.reg_read(UC_X86_REG_EAX) == 9876
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 12
    assert cpu.reg_read(UC_X86_REG_EFLAGS) == 0x202
    for register, value in (
        (UC_X86_REG_EBP, 17),
        (UC_X86_REG_EBX, 19),
        (UC_X86_REG_ESI, 23),
        (UC_X86_REG_EDI, 29),
        (UC_X86_REG_ECX, _ROOT),
    ):
        assert cpu.reg_read(register) == value


def _capture_scope(
    *,
    toolbar: bool = False,
    qualified: bool = False,
    coverage_va: int | None = None,
    generation_va: int | None = None,
    capture_only: bool = False,
) -> bytes:
    return build_menu_destination_scope(
        wrapper_va=_ENTRY,
        state_va=_STATE,
        target_va=_TARGET,
        class_vtable=_CLASS,
        toolbar=toolbar,
        resolve_resource_va=_RESOLVE,
        resource_manager_va=_GLOBALS,
        back_surface_va=_GLOBALS + 4,
        directdraw_owner_va=_GLOBALS + 8,
        readable_iat_va=_GLOBALS + 12,
        blt_va=_BLT_THUNK if qualified else None,
        blt_fast_va=_FAST_THUNK if qualified else None,
        coverage_va=coverage_va,
        generation_va=generation_va,
        capture_only=capture_only,
    )


def _scope(
    *,
    size: tuple[int, int] = (1280, 800),
    toolbar: bool = False,
    rectangle: tuple[int, int, int, int] = (514, 363, 766, 438),
    state: str = "valid",
    qualified: bool = False,
) -> tuple[Uc, list[tuple[int, int, int, int]], bytes]:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x880000, 0x90000)
    cpu.mem_write(
        _ENTRY,
        _capture_scope(toolbar=toolbar, qualified=qualified),
    )
    cpu.mem_write(_STATE, menu_destination_state(_STATE))
    width = (
        0xFFFFFFFF if state == "negative_width" else 8193 if state == "oversized_width" else size[0]
    )
    height = (
        0xFFFFFFFF
        if state == "negative_height"
        else 8193
        if state == "oversized_height"
        else size[1]
    )
    _write(
        cpu,
        _STATE,
        0 if state == "disabled" else 2 if state == "unknown_mode" else 1,
        0
        if state == "cache_missing"
        else _PAGE
        if state == "cache_is_page"
        else _OWNED_CACHE
        if qualified
        else _CACHE,
        width,
        height,
        _DD + (state == "wrong_dd"),
        int(state == "busy"),
    )
    _write(cpu, _ROOT, _CLASS + (state == "foreign_class"))
    _write(cpu, _ROOT + 0x18, state != "hidden")
    cpu.mem_write(_ROOT + 0x1C, struct.pack("<4i", *rectangle))
    _write(cpu, _RESOURCE + 0x30, 0 if state == "wrapper_missing" else _ORIGINAL)
    _write(cpu, _MANAGER + 0x120, state != "table_missing")
    _write(
        cpu,
        _GLOBALS,
        0 if state == "manager_missing" else _MANAGER,
        0 if state == "page_missing" else _PAGE,
        0 if state == "dd_missing" else _DD,
        _READABLE,
    )
    words = list(range(20))
    words[10:12] = (1, _PAGE + (state == "foreign_page"))
    words[14:16] = (size[0] + (state == "stale_width"), size[1] + (state == "stale_height"))
    original = struct.pack("<20I", *words)
    cpu.mem_write(_ORIGINAL, original)
    cpu.mem_write(_TARGET, bytes.fromhex("b8 94 26 00 00 c2 08 00"))
    if qualified:
        _qualify_child_transfers(cpu)
    cpu.mem_write(
        _RESOLVE,
        b"\xb8"
        + struct.pack("<I", 0 if state == "resource_missing" else _RESOURCE)
        + b"\xc2\x04\x00",
    )
    cpu.mem_write(_READABLE, bytes.fromhex("c2 08 00"))
    calls: list[tuple[int, int, int, int]] = []

    def hook(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address == _TARGET:
            stack = machine.reg_read(UC_X86_REG_ESP)
            handle, damage = struct.unpack("<2I", machine.mem_read(stack + 4, 8))
            binding = struct.unpack("<I", machine.mem_read(_RESOURCE + 0x30, 4))[0]
            calls.append((machine.reg_read(UC_X86_REG_ECX), handle, damage, binding))
        elif address == _READABLE:
            stack = machine.reg_read(UC_X86_REG_ESP)
            pointer = struct.unpack("<I", machine.mem_read(stack + 4, 4))[0]
            bad = {"bad_manager": _MANAGER, "bad_resource": _RESOURCE, "bad_wrapper": _ORIGINAL}
            machine.reg_write(UC_X86_REG_EAX, pointer == bad.get(state))
        elif address == _RESOLVE:
            stack = machine.reg_read(UC_X86_REG_ESP)
            assert struct.unpack("<I", machine.mem_read(stack + 4, 4))[0] == 1234
            assert machine.reg_read(UC_X86_REG_ECX) == _MANAGER
        elif address in (_BLT, _FAST):
            stack = machine.reg_read(UC_X86_REG_ESP)
            assert struct.unpack("<6I", machine.mem_read(stack + 4, 24)) == (
                _OWNED_CACHE,
                1,
                2,
                3,
                4,
                5,
            )
            assert _words(machine, _OWNED_CACHE) == _STATE + 0x380

    cpu.hook_add(UC_HOOK_CODE, hook)
    _write(cpu, _STACK, _RETURN, 1234, 4567)
    for register, value in (
        (UC_X86_REG_EBP, 17),
        (UC_X86_REG_EBX, 19),
        (UC_X86_REG_ESI, 23),
        (UC_X86_REG_EDI, 29),
        (UC_X86_REG_ECX, _ROOT),
        (UC_X86_REG_ESP, _STACK),
        (UC_X86_REG_EFLAGS, 0x202),
    ):
        cpu.reg_write(register, value)
    return cpu, calls, original


def _qualify_child_transfers(cpu: Uc) -> None:
    _write(cpu, _OWNED_CACHE, _CACHE_VTABLE)
    cpu.mem_write(_CACHE_VTABLE, struct.pack("<36I", *range(1, 37)))
    _write(cpu, _CACHE_VTABLE + 0x14, _BLT)
    _write(cpu, _CACHE_VTABLE + 0x1C, _FAST)
    for fast, entry in ((False, _BLT_THUNK), (True, _FAST_THUNK)):
        cpu.mem_write(
            entry, build_menu_cache_blt_result(wrapper_va=entry, state_va=_STATE, fast=fast)
        )
    for entry in (_BLT, _FAST):
        cpu.mem_write(entry, bytes.fromhex("31 c0 c2 18 00"))
    target = X86Emitter(base_va=_TARGET)
    target.raw(bytes.fromhex("9c 60"))
    target.raw(b"\x83\x3d" + struct.pack("<I", _STATE + 20) + b"\x01")
    target.jump_if(Condition.NOT_EQUAL, "return")
    for slot in (0x14, 0x1C):
        for argument in (5, 4, 3, 2, 1, _OWNED_CACHE):
            target.push_imm32(argument)
        target.raw(b"\xa1" + struct.pack("<I", _OWNED_CACHE))
        target.raw(b"\xff\x50" + bytes((slot,)))
    target.label("return")
    target.raw(bytes.fromhex("61 9d b8 94 26 00 00 c2 08 00"))
    cpu.mem_write(_TARGET, target.build())
