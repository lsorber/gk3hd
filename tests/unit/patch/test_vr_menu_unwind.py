"""Execute menu termination cleanup without claiming to emulate Windows SEH."""

from __future__ import annotations

import pytest
from unicorn import UC_HOOK_CODE, Uc
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_EFLAGS, UC_X86_REG_ESP

from gk3hd.patch.definitions.vr_menu import build_menu_cache_unwind, build_menu_destination_scope
from tests.unit.patch.test_vr_menu import (
    _BLT_THUNK,
    _CACHE_VTABLE,
    _CLASS,
    _ENTRY,
    _FAST_THUNK,
    _GLOBALS,
    _ORIGINAL,
    _OWNED_CACHE,
    _RESOLVE,
    _RESOURCE,
    _RETURN,
    _STACK,
    _STATE,
    _TARGET,
    _assert_return,
    _scope,
    _words,
    _write,
)

_UNWIND = 0x889000


def _protected_scope(
    *, qualified: bool = False, state: str = "valid", single: bool = False
) -> tuple[Uc, list[tuple[int, int, int, int]]]:
    cpu, calls, _original = _scope(qualified=qualified, state=state)
    cpu.mem_map(0, 0x1000)  # FS:[0] is a synthetic x86 TIB in this fixture.
    _write(cpu, 0, 0xFFFFFFFF)
    cpu.mem_write(
        _UNWIND,
        build_menu_cache_unwind(wrapper_va=_UNWIND, state_va=_STATE, qualified=qualified),
    )
    cpu.mem_write(
        _ENTRY,
        build_menu_destination_scope(
            wrapper_va=_ENTRY,
            state_va=_STATE,
            target_va=_TARGET,
            class_vtable=_CLASS,
            toolbar=False,
            resolve_resource_va=_RESOLVE,
            resource_manager_va=_GLOBALS,
            back_surface_va=_GLOBALS + 4,
            directdraw_owner_va=_GLOBALS + 8,
            readable_iat_va=_GLOBALS + 12,
            blt_va=_BLT_THUNK if qualified else None,
            blt_fast_va=_FAST_THUNK if qualified else None,
            unwind_va=_UNWIND,
            mirror_va=0x88B000 if single else None,
        ),
    )
    if single:
        cpu.mem_write(0x88B000, bytes.fromhex("b8 01 00 00 00 c3"))
    return cpu, calls


@pytest.mark.parametrize("qualified", [False, True])
def test_normal_menu_return_restores_the_original_exception_chain(*, qualified: bool) -> None:
    cpu, calls = _protected_scope(qualified=qualified)
    registrations: list[int] = []

    def observe(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address == _TARGET:
            registrations.append(_words(machine, 0))
            if len(registrations) == 2:
                record = registrations[-1]
                assert _words(machine, record) == 0xFFFFFFFF
                assert _words(machine, record + 4) == _UNWIND
                assert _words(machine, record + 8) == _STATE
                assert _words(machine, _STATE + 0x88) == record

    cpu.hook_add(UC_HOOK_CODE, observe)
    cpu.emu_start(_ENTRY, _RETURN, count=4000)
    assert len(calls) == 2
    assert registrations[0] == 0xFFFFFFFF
    assert registrations[1] < _STACK
    assert _words(cpu, 0) == 0xFFFFFFFF
    assert _words(cpu, _STATE + 0x88) == 0
    assert _words(cpu, _STATE + 0x8C) == 0
    assert _words(cpu, _RESOURCE + 0x30) == _ORIGINAL
    _assert_return(cpu)


def _bound_scope(*, qualified: bool, single: bool = False) -> Uc:
    cpu, _calls = _protected_scope(qualified=qualified, single=single)

    def stop_at_bound_draw(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address == _TARGET and _words(machine, _STATE + 20) == 1:
            machine.emu_stop()

    cpu.hook_add(UC_HOOK_CODE, stop_at_bound_draw)
    cpu.emu_start(_ENTRY, _RETURN, count=4000)
    assert _words(cpu, _RESOURCE + 0x30) == _STATE + 0x100
    if qualified:
        assert _words(cpu, _OWNED_CACHE) == _STATE + 0x380
    return cpu


def test_single_traversal_restores_its_exception_chain_and_native_result() -> None:
    cpu, calls = _protected_scope(qualified=True, single=True)
    cpu.emu_start(_ENTRY, _RETURN, count=4000)
    assert len(calls) == 1
    assert _words(cpu, 0) == 0xFFFFFFFF
    assert _words(cpu, _STATE + 0x88) == 0
    assert _words(cpu, _RESOURCE + 0x30) == _ORIGINAL
    assert _words(cpu, _OWNED_CACHE) == _CACHE_VTABLE
    assert _words(cpu, _STATE + 0x70) == 1
    _assert_return(cpu)


@pytest.mark.parametrize("flags", [2, 4, 6, 0x22, 0x42])
def test_single_traversal_unwind_restores_bindings_without_mirroring_partial_pixels(
    flags: int,
) -> None:
    cpu = _bound_scope(qualified=True, single=True)
    _dispatch(cpu, flags=flags)
    assert _words(cpu, _RESOURCE + 0x30) == _ORIGINAL
    assert _words(cpu, _OWNED_CACHE) == _CACHE_VTABLE
    assert _words(cpu, _STATE + 0x70) == 0
    assert _words(cpu, _STATE + 0x74) == 0
    assert _words(cpu, _STATE + 20) == 0
    assert _words(cpu, _STATE + 0x8C) == 1


def _dispatch(cpu: Uc, *, flags: int, record: int | None = None) -> None:
    exception = _STACK + 0x300
    _write(cpu, exception, 0xE0424242, flags)
    _write(cpu, _STACK + 0x100, _RETURN, exception, record or _words(cpu, 0), 0, 0)
    cpu.reg_write(UC_X86_REG_ESP, _STACK + 0x100)
    cpu.reg_write(UC_X86_REG_EFLAGS, 0x202)
    cpu.reg_write(UC_X86_REG_EBX, 12345)
    cpu.emu_start(_UNWIND, _RETURN, count=1000)
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 0x104, "handler must return cdecl"
    assert cpu.reg_read(UC_X86_REG_EAX) == 1, "EXCEPTION_DISPOSITION, not filter value"
    assert cpu.reg_read(UC_X86_REG_EFLAGS) == 0x202
    assert cpu.reg_read(UC_X86_REG_EBX) == 12345


@pytest.mark.parametrize("qualified", [False, True])
@pytest.mark.parametrize("flags", [0, 1, 0x10, 0x80])
def test_first_pass_exception_dispatch_does_not_break_resumable_drawing(
    *, qualified: bool, flags: int
) -> None:
    cpu = _bound_scope(qualified=qualified)
    state = bytes(cpu.mem_read(_STATE, 0x500))
    chain = _words(cpu, 0)
    _dispatch(cpu, flags=flags)
    assert cpu.mem_read(_STATE, 0x500) == state
    assert _words(cpu, _RESOURCE + 0x30) == _STATE + 0x100
    assert _words(cpu, 0) == chain
    if qualified:
        assert _words(cpu, _OWNED_CACHE) == _STATE + 0x380


@pytest.mark.parametrize("qualified", [False, True])
@pytest.mark.parametrize("flags", [2, 4, 6, 0x22, 0x42])
def test_unwind_restores_private_bindings_and_withdraws_publication(
    *, qualified: bool, flags: int
) -> None:
    cpu = _bound_scope(qualified=qualified)
    _write(cpu, _STATE + 0x70, 1, 7, 123)
    chain = _words(cpu, 0)
    _dispatch(cpu, flags=flags)
    assert _words(cpu, _RESOURCE + 0x30) == _ORIGINAL
    if qualified:
        assert _words(cpu, _OWNED_CACHE) == _CACHE_VTABLE
    for offset in (20, 32, 0x70, 0x88):
        assert _words(cpu, _STATE + offset) == 0
    assert _words(cpu, _STATE + 0x64) == 1
    assert _words(cpu, _STATE + 0x74) == 7, "aborted draw is not a new publication"
    assert _words(cpu, _STATE + 0x8C) == 1
    assert _words(cpu, _STATE + 36) == 0, "aborted traversal is not completed"
    assert _words(cpu, 0) == chain, "the OS, not this handler, removes its registration"
    _dispatch(cpu, flags=flags, record=chain)
    assert _words(cpu, _STATE + 0x8C) == 1, "duplicate unwind must not repeat cleanup"


@pytest.mark.parametrize("fault", ["other_registration", "other_owner", "idle"])
def test_delayed_unwind_cannot_restore_another_scope(fault: str) -> None:
    cpu = _bound_scope(qualified=True)
    record = _words(cpu, 0)
    if fault == "other_registration":
        record += 0x100
    elif fault == "other_owner":
        _write(cpu, record + 8, _STATE + 0x1000)
    else:
        _write(cpu, _STATE + 20, 0)
    state = bytes(cpu.mem_read(_STATE, 0x500))
    _dispatch(cpu, flags=2, record=record)
    assert cpu.mem_read(_STATE, 0x500) == state
    assert _words(cpu, _RESOURCE + 0x30) == _STATE + 0x100
    assert _words(cpu, _OWNED_CACHE) == _STATE + 0x380


@pytest.mark.parametrize("state", ["disabled", "busy", "hidden", "foreign_page"])
def test_skipped_capture_does_not_register_an_exception_scope(state: str) -> None:
    cpu, calls = _protected_scope(state=state)
    cpu.emu_start(_ENTRY, _RETURN, count=4000)
    assert len(calls) == 1
    assert _words(cpu, 0) == 0xFFFFFFFF
    assert _words(cpu, _STATE + 0x88) == 0
    _assert_return(cpu)
