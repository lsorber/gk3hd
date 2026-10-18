"""Execute scoped HUD glyph-source capture and native-state restoration."""

from __future__ import annotations

import struct

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDX,
    UC_X86_REG_EFLAGS,
    UC_X86_REG_ESP,
    UC_X86_REG_MXCSR,
    UC_X86_REG_XMM0,
)

from gk3hd.patch.definitions.vr_hud import (
    HUD_ABORTED,
    HUD_BACKGROUND_OPACITY,
    HUD_BUSY,
    HUD_CAPTURED_OWNER,
    HUD_COMPLETED,
    HUD_GLYPH_OPACITY,
    HUD_READY,
    HUD_REGISTRATION,
    build_hud_text_scope,
    build_hud_text_unwind,
)

_ENTRY, _UNWIND, _TARGET, _RETURN, _STATE, _OBJECT, _CAPTURE, _STACK = range(
    0x880000, 0x888000, 0x1000
)
_CLASS = 0x675810
_AUTHORED = struct.pack("<I4f", 1, 0.25, 0.75, 0.125, 0.625)
_BACKING = struct.pack("<f", 0.375)
_FONT_SCOPE = _CAPTURE + 4


def _word(cpu: Uc, address: int, value: int | None = None) -> int:
    if value is not None:
        cpu.mem_write(address, struct.pack("<I", value))
    return struct.unpack("<I", cpu.mem_read(address, 4))[0]


def _machine(*, backing: bool = False, font_scope: bool = False) -> Uc:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0, 0x1000)
    cpu.mem_map(_ENTRY, 0x10000)
    cpu.mem_write(
        _ENTRY,
        build_hud_text_scope(
            wrapper_va=_ENTRY,
            state_va=_STATE,
            target_va=_TARGET,
            class_vtable=_CLASS,
            capture_active_va=_CAPTURE,
            unwind_va=_UNWIND,
            backing=backing,
            font_scope_va=_FONT_SCOPE if font_scope else None,
        ),
    )
    cpu.mem_write(
        _UNWIND,
        build_hud_text_unwind(
            wrapper_va=_UNWIND,
            state_va=_STATE,
            font_scope_va=_FONT_SCOPE if font_scope else None,
        ),
    )
    # Deliberately nontrivial native result/flags, not a zero-return mock.
    cpu.mem_write(_TARGET, bytes.fromhex("b8 94 26 00 00 ba 78 56 34 12 f9 c2 08 00"))
    _word(cpu, 0, 0xFFFFFFFF)
    cpu.mem_write(_STATE, struct.pack("<2I", 1, _OBJECT))
    _word(cpu, _CAPTURE, 1)
    _word(cpu, _OBJECT, _CLASS)
    _word(cpu, _OBJECT + 0x18, 1)
    cpu.mem_write(_OBJECT + 0x5C, _AUTHORED)
    cpu.mem_write(_OBJECT + 0x88, _BACKING)
    cpu.mem_write(_STACK, struct.pack("<3I", _RETURN, 1234, 4567))
    for register, value in (
        (UC_X86_REG_ECX, _OBJECT),
        (UC_X86_REG_EBX, 19),
        (UC_X86_REG_EDX, 27),
        (UC_X86_REG_EAX, 37),
        (UC_X86_REG_ESP, _STACK),
        (UC_X86_REG_EFLAGS, 0x202),
        (UC_X86_REG_MXCSR, 0x7F80),
        (UC_X86_REG_XMM0, 0x123456789ABCDEF0123456789ABCDEF0),
    ):
        cpu.reg_write(register, value)
    return cpu


def _assert_return(cpu: Uc) -> None:
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 12
    assert cpu.reg_read(UC_X86_REG_EAX) == 0x2694
    assert cpu.reg_read(UC_X86_REG_EDX) == 0x12345678
    assert cpu.reg_read(UC_X86_REG_EBX) == 19
    assert cpu.reg_read(UC_X86_REG_EFLAGS) == 0x203
    assert _word(cpu, 0) == 0xFFFFFFFF
    assert cpu.reg_read(UC_X86_REG_MXCSR) == 0x7F80
    assert cpu.reg_read(UC_X86_REG_XMM0) == 0x123456789ABCDEF0123456789ABCDEF0


@pytest.mark.parametrize("mode", [0, 1])
@pytest.mark.parametrize("alpha", [0.0, 0.075, 0.25, 0.824999988079071, 1.0])
@pytest.mark.parametrize("backing", [False, True])
def test_capture_has_opaque_glyphs_no_backing_and_restores_authored_fields(
    mode: int, alpha: float, *, backing: bool
) -> None:
    cpu = _machine(backing=backing)
    authored = struct.pack("<I4f", mode, alpha, 1 - alpha, 0.125, 0.625)
    cpu.mem_write(_OBJECT + 0x5C, authored)
    calls: list[int] = []

    def inspect(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address != _TARGET:
            return
        stack = machine.reg_read(UC_X86_REG_ESP)
        assert struct.unpack("<2I", machine.mem_read(stack + 4, 8)) == (1234, 4567)
        assert machine.reg_read(UC_X86_REG_ECX) == _OBJECT
        assert machine.reg_read(UC_X86_REG_EAX) == 37
        assert machine.reg_read(UC_X86_REG_EDX) == 27
        assert machine.reg_read(UC_X86_REG_EFLAGS) == 0x202
        expected = (1, 0, 1) if backing else (0, 1, 0)
        assert bytes(machine.mem_read(_OBJECT + 0x5C, 12)) == struct.pack("<I2f", *expected)
        assert bytes(machine.mem_read(_OBJECT + 0x68, 8)) == authored[12:]
        assert _word(machine, _OBJECT + 0x88) == (0x3F800000 if backing else 0)
        assert _word(machine, _STATE + HUD_BUSY) == 1
        assert _word(machine, _STATE + HUD_READY) == 0
        calls.append(address)

    cpu.hook_add(UC_HOOK_CODE, inspect)
    cpu.emu_start(_ENTRY, _RETURN, count=1000)
    assert len(calls) == 1
    assert bytes(cpu.mem_read(_OBJECT + 0x5C, 20)) == authored
    assert bytes(cpu.mem_read(_OBJECT + 0x88, 4)) == _BACKING
    assert (
        _word(cpu, _STATE + HUD_GLYPH_OPACITY)
        == struct.unpack("<I", struct.pack("<f", alpha if mode else 1.0))[0]
    )
    assert bytes(cpu.mem_read(_STATE + HUD_BACKGROUND_OPACITY, 4)) == _BACKING
    assert _word(cpu, _STATE + HUD_CAPTURED_OWNER) == _OBJECT
    assert _word(cpu, _STATE + HUD_COMPLETED) == 1
    assert _word(cpu, _STATE + HUD_BUSY) == 0
    assert _word(cpu, _STATE + HUD_REGISTRATION) == 0
    assert _word(cpu, _STATE + HUD_READY) == 1
    _assert_return(cpu)


@pytest.mark.parametrize(
    "fault",
    [
        "disabled",
        "unknown_enable",
        "not_capture",
        "busy",
        "other_owner",
        "wrong_class",
        "hidden",
        "other_effect",
        "negative_glyph",
        "large_glyph",
        "nan_glyph",
        "inf_glyph",
        "negative_backing",
        "large_backing",
        "nan_backing",
        "inf_backing",
        "noncomplementary_destination",
        "negative_destination",
        "nan_destination",
    ],
)
def test_unqualified_calls_remain_native_without_mutating_the_widget(fault: str) -> None:
    cpu = _machine()
    addresses = {
        "disabled": (_STATE, 0),
        "unknown_enable": (_STATE, 2),
        "not_capture": (_CAPTURE, 0),
        "busy": (_STATE + HUD_BUSY, 1),
        "other_owner": (_STATE + 4, _OBJECT + 0x100),
        "wrong_class": (_OBJECT, _CLASS + 4),
        "hidden": (_OBJECT + 0x18, 0),
        "other_effect": (_OBJECT + 0x5C, 2),
        "noncomplementary_destination": (_OBJECT + 0x64, 0x3F000000),
        "negative_destination": (_OBJECT + 0x64, 0xBF400000),
        "nan_destination": (_OBJECT + 0x64, 0x7FC00000),
    }
    if fault in addresses:
        _word(cpu, *addresses[fault])
    else:
        value = {"negative": -0.1, "large": 1.1, "nan": float("nan"), "inf": float("inf")}
        kind, field = fault.split("_")
        cpu.mem_write(
            _OBJECT + (0x60 if field == "glyph" else 0x88), struct.pack("<f", value[kind])
        )
    authored = bytes(cpu.mem_read(_OBJECT, 0x90))
    seen: list[int] = []

    def inspect(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address == _TARGET:
            assert bytes(machine.mem_read(_OBJECT, 0x90)) == authored
            assert _word(machine, 0) == 0xFFFFFFFF
            seen.append(address)

    cpu.hook_add(UC_HOOK_CODE, inspect)
    cpu.emu_start(_ENTRY, _RETURN, count=1000)
    assert len(seen) == 1
    assert bytes(cpu.mem_read(_OBJECT, 0x90)) == authored
    assert _word(cpu, _STATE + HUD_READY) == 0
    assert _word(cpu, _STATE + HUD_COMPLETED) == 0
    _assert_return(cpu)


def _bound(*, font_scope: bool = False, prior_scope: int = 0) -> Uc:
    cpu = _machine(font_scope=font_scope)
    _word(cpu, _FONT_SCOPE, prior_scope)

    def stop(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address == _TARGET:
            machine.emu_stop()

    cpu.hook_add(UC_HOOK_CODE, stop)
    cpu.emu_start(_ENTRY, _RETURN, count=1000)
    return cpu


@pytest.mark.parametrize("prior_scope", [0, 2])
@pytest.mark.parametrize("backing", [False, True])
def test_qualified_capture_selects_and_restores_native_glyph_fill_affine(
    prior_scope: int, *, backing: bool
) -> None:
    cpu = _machine(backing=backing, font_scope=True)
    _word(cpu, _FONT_SCOPE, prior_scope)
    scopes: list[int] = []

    def inspect(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address == _TARGET:
            scopes.append(_word(machine, _FONT_SCOPE))

    cpu.hook_add(UC_HOOK_CODE, inspect)
    cpu.emu_start(_ENTRY, _RETURN, count=1000)
    assert scopes == [1]
    assert _word(cpu, _FONT_SCOPE) == prior_scope
    assert _word(cpu, _STATE + HUD_READY) == 1
    _assert_return(cpu)


@pytest.mark.parametrize("prior_scope", [0, 2])
def test_native_exception_restores_borrowed_glyph_fill_affine(prior_scope: int) -> None:
    cpu = _bound(font_scope=True, prior_scope=prior_scope)
    assert _word(cpu, _FONT_SCOPE) == 1
    _dispatch(cpu, 2)
    assert _word(cpu, _FONT_SCOPE) == prior_scope
    assert _word(cpu, _STATE + HUD_READY) == 0
    assert _word(cpu, _STATE + HUD_ABORTED) == 1


def _dispatch(cpu: Uc, flags: int, registration: int | None = None) -> None:
    exception, stack = _STACK + 0x300, _STACK + 0x100
    cpu.mem_write(exception, struct.pack("<2I", 0xE0424242, flags))
    cpu.mem_write(
        stack, struct.pack("<5I", _RETURN, exception, registration or _word(cpu, 0), 0, 0)
    )
    cpu.reg_write(UC_X86_REG_ESP, stack)
    cpu.reg_write(UC_X86_REG_EFLAGS, 0x202)
    cpu.emu_start(_UNWIND, _RETURN, count=1000)
    assert cpu.reg_read(UC_X86_REG_ESP) == stack + 4
    assert cpu.reg_read(UC_X86_REG_EAX) == 1
    assert cpu.reg_read(UC_X86_REG_EFLAGS) == 0x202


@pytest.mark.parametrize("flags", [0, 1, 0x10, 0x80])
def test_resumable_dispatch_does_not_restore_the_still_active_capture(flags: int) -> None:
    cpu = _bound()
    before = bytes(cpu.mem_read(_STATE, 64))
    _dispatch(cpu, flags)
    assert bytes(cpu.mem_read(_STATE, 64)) == before
    assert _word(cpu, _OBJECT + 0x88) == 0
    assert _word(cpu, _STATE + HUD_BUSY) == 1


@pytest.mark.parametrize("flags", [2, 4, 6, 0x22, 0x42])
def test_actual_unwind_restores_fields_and_withdraws_aborted_publication(flags: int) -> None:
    cpu = _bound()
    registration = _word(cpu, 0)
    _word(cpu, _STATE + HUD_READY, 1)
    _word(cpu, _STATE + HUD_CAPTURED_OWNER, _OBJECT)
    _dispatch(cpu, flags)
    assert bytes(cpu.mem_read(_OBJECT + 0x5C, 20)) == _AUTHORED
    assert bytes(cpu.mem_read(_OBJECT + 0x88, 4)) == _BACKING
    for offset in (HUD_BUSY, HUD_REGISTRATION, HUD_READY, HUD_CAPTURED_OWNER, HUD_COMPLETED):
        assert _word(cpu, _STATE + offset) == 0
    assert _word(cpu, _STATE + HUD_ABORTED) == 1
    assert _word(cpu, 0) == registration, "the OS owns exception-chain removal"
    _dispatch(cpu, flags, registration)
    assert _word(cpu, _STATE + HUD_ABORTED) == 1


@pytest.mark.parametrize("fault", ["other_registration", "other_state", "idle"])
def test_delayed_unwind_cannot_mutate_another_scope(fault: str) -> None:
    cpu = _bound()
    registration = _word(cpu, 0)
    if fault == "other_registration":
        registration += 0x100
    elif fault == "other_state":
        _word(cpu, registration + 8, _STATE + 0x100)
    else:
        _word(cpu, _STATE + HUD_BUSY, 0)
    before = bytes(cpu.mem_read(_STATE, 64))
    _dispatch(cpu, 2, registration)
    assert bytes(cpu.mem_read(_STATE, 64)) == before
    assert _word(cpu, _OBJECT + 0x88) == 0
