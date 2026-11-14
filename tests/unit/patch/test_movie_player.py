"""AV1 adapter lookup preserves the game's COM ABI and never searches cwd."""

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
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.definitions.runtime2d.system.movie_player import (
    PLAYER_EXPORT,
    PLAYER_PATH,
    PLAYER_STATE_EXPORT,
    MoviePlayerABI,
    MovieStateABI,
    build_avi_state,
    build_movie_state_call,
    build_native_movie_attach,
    build_open_movie,
)

_CODE, _DATA = 0x800000, 0x900000
_RETURN, _MODULE, _LOAD, _PROC, _NATIVE, _ADAPTER = (
    _CODE + value for value in (0x8000, 0x8100, 0x8200, 0x8300, 0x8400, 0x8500)
)
_STREAM, _TABLE, _FILENAME, _CACHE, _STACK = (
    _DATA + value for value in (0x100, 0x200, 0x300, 0x400, 0xF000)
)


def _machine(cached: bool) -> tuple[Uc, dict[int, int]]:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(_CODE, 0x10000)
    cpu.mem_map(_DATA, 0x10000)
    abi = MoviePlayerABI(
        _DATA, _DATA + 4, _DATA + 8, _DATA + 0x500, _DATA + 0x600, _CACHE, _DATA + 0x700
    )
    cpu.mem_write(_DATA, struct.pack("<III", _MODULE, _LOAD, _PROC))
    cpu.mem_write(abi.path, PLAYER_PATH)
    cpu.mem_write(abi.symbol, PLAYER_EXPORT)
    cpu.mem_write(_CODE, build_open_movie(wrapper_va=_CODE, abi=abi))
    cpu.mem_write(_CACHE, struct.pack("<I", _ADAPTER if cached else 0))
    cpu.mem_write(_STREAM, struct.pack("<I", _TABLE))
    cpu.mem_write(_TABLE + 0x40, struct.pack("<I", _NATIVE))
    for function in (_MODULE, _PROC, _NATIVE, _ADAPTER):
        cpu.mem_write(function, bytes.fromhex("c20c00" if function != _PROC else "c20800"))
    cpu.mem_write(_LOAD, bytes.fromhex("c20400"))
    cpu.mem_write(_STACK, struct.pack("<5I", _RETURN, _STREAM, _FILENAME, 7, 0xABCDEF))
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    preserved = {UC_X86_REG_EBP: 123, UC_X86_REG_EBX: 456, UC_X86_REG_ESI: 789, UC_X86_REG_EDI: 321}
    for register, value in preserved.items():
        cpu.reg_write(register, value)
    return cpu, preserved


def _string(machine: Uc, pointer: int) -> bytes:
    result = bytearray()
    while value := machine.mem_read(pointer + len(result), 1)[0]:
        result.append(value)
        assert len(result) <= 300
    return bytes(result)


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("failure", [None, "module", "load", "symbol", "long", "relative"])
def test_adapter_lookup_is_executable_relative_and_preserves_call_contract(
    cached: bool, failure: str | None
) -> None:
    cpu, preserved = _machine(cached)
    calls = []

    def invoke(machine: Uc, address: int, _size: int, _user: object) -> None:
        if address not in {_MODULE, _LOAD, _PROC, _NATIVE, _ADAPTER}:
            return
        calls.append(address)
        sp = machine.reg_read(UC_X86_REG_ESP)
        arguments = struct.unpack("<3I", machine.mem_read(sp + 4, 12))
        if address == _MODULE:
            assert arguments[0] == 0
            assert arguments[2] == 300
            path = b"D:\\Games With Spaces\\GK3\\GK3.exe"
            if failure == "relative":
                path = b"GK3.exe"
            machine.mem_write(arguments[1], path + b"\0")
            result = 0 if failure == "module" else 300 if failure == "long" else len(path)
        elif address == _LOAD:
            expected = b"D:\\Games With Spaces\\GK3\\" + PLAYER_PATH[:-1]
            assert _string(machine, arguments[0]) == expected
            result = 0 if failure == "load" else 1234
        elif address == _PROC:
            assert arguments[0] == 1234
            assert _string(machine, arguments[1]) == PLAYER_EXPORT[:-1]
            result = 0 if failure == "symbol" else _ADAPTER
        else:
            assert arguments == (_STREAM, _FILENAME, 7)
            result = 0x12345678 if address == _ADAPTER else 0x80004005
        machine.reg_write(UC_X86_REG_EAX, result)

    cpu.hook_add(UC_HOOK_CODE, invoke)
    cpu.emu_start(_CODE, _RETURN, count=1000)
    adapter = cached or failure is None
    assert calls[-1] == (_ADAPTER if adapter else _NATIVE)
    assert cpu.reg_read(UC_X86_REG_EAX) == (0x12345678 if adapter else 0x80004005)
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 16
    assert all(cpu.reg_read(register) == value for register, value in preserved.items())
    assert struct.unpack("<I", cpu.mem_read(_STACK + 16, 4))[0] == 0xABCDEF
    if cached:
        assert calls == [_ADAPTER]


@pytest.mark.parametrize("running", [False, True])
@pytest.mark.parametrize("route", ["cached", "resolved", "missing-export", "missing-player"])
def test_movie_controls_preserve_state_result_stack_and_native_fallback(
    running: bool, route: str
) -> None:
    cpu, preserved = _machine(cached=False)
    state_call, movie, module = _CODE + 0x2000, _DATA + 0x800, _DATA + 0x700
    abi = MovieStateABI(_DATA + 8, module, _DATA + 0x600, _CACHE)
    cpu.mem_write(abi.symbol, PLAYER_STATE_EXPORT)
    cpu.mem_write(module, struct.pack("<I", 0 if route == "missing-player" else 1234))
    cpu.mem_write(_CACHE, struct.pack("<I", _ADAPTER if route == "cached" else 0))
    cpu.mem_write(state_call, build_movie_state_call(wrapper_va=state_call, abi=abi))
    cpu.mem_write(
        _CODE, build_avi_state(wrapper_va=_CODE, state_call_va=state_call, running=running)
    )
    cpu.mem_write(movie + 0x54, struct.pack("<I", _STREAM))
    cpu.mem_write(_TABLE + 0x1C, struct.pack("<I", _NATIVE))
    for function in (_NATIVE, _ADAPTER):
        cpu.mem_write(function, bytes.fromhex("c20800"))
    cpu.mem_write(_STACK, struct.pack("<2I", _RETURN, 0xABCDEF))
    cpu.reg_write(UC_X86_REG_ECX, movie)
    calls = []

    def invoke(machine: Uc, address: int, _size: int, _user: object) -> None:
        if address not in {_PROC, _NATIVE, _ADAPTER}:
            return
        calls.append(address)
        sp = machine.reg_read(UC_X86_REG_ESP)
        arguments = struct.unpack("<2I", machine.mem_read(sp + 4, 8))
        if address == _PROC:
            assert arguments[0] == 1234
            assert _string(machine, arguments[1]) == PLAYER_STATE_EXPORT[:-1]
            result = 0 if route == "missing-export" else _ADAPTER
        else:
            assert arguments == (_STREAM, int(running))
            result = 0x12345678 if address == _ADAPTER else 0x80004005
        machine.reg_write(UC_X86_REG_EAX, result)

    cpu.hook_add(UC_HOOK_CODE, invoke)
    cpu.emu_start(_CODE, _RETURN, count=1000)
    adapted = route in {"cached", "resolved"}
    assert calls[-1] == (_ADAPTER if adapted else _NATIVE)
    assert cpu.reg_read(UC_X86_REG_EAX) == (0x12345678 if adapted else 0x80004005)
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 4
    assert struct.unpack("<I", cpu.mem_read(_STACK + 4, 4))[0] == 0xABCDEF
    assert all(cpu.reg_read(register) == value for register, value in preserved.items())
    if route == "cached":
        assert calls == [_ADAPTER]
    if route == "missing-player":
        assert calls == [_NATIVE]
    if route == "resolved":
        cpu.reg_write(UC_X86_REG_ESP, _STACK)
        cpu.reg_write(UC_X86_REG_ECX, movie)
        cpu.emu_start(_CODE, _RETURN, count=1000)
        assert calls == [_PROC, _ADAPTER, _ADAPTER]


@pytest.mark.parametrize("available", ["module-missing", "export-missing", "present"])
def test_native_movie_offer_preserves_caller_and_falls_back(available: str) -> None:
    """A provider is optional; a successful offer receives the exact native owner."""
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(_CODE, 0x10000)
    cpu.mem_map(_DATA, 0x10000)
    cpu.mem_write(_CACHE, struct.pack("<I", 0 if available == "module-missing" else _MODULE))
    cpu.mem_write(_DATA, struct.pack("<I", _PROC))
    fragment = build_native_movie_attach(
        entry_va=_CODE, module_va=_CACHE, get_proc_address=_DATA, complete_va=_NATIVE
    )
    cpu.mem_write(_CODE, fragment + b"\xc3")
    cpu.mem_write(_PROC, bytes.fromhex("c20800"))
    cpu.mem_write(_ADAPTER, bytes.fromhex("c20800"))
    calls: list[int] = []

    def observe(machine: Uc, address: int, _size: int, _user: object) -> None:
        if address == _PROC:
            stack = machine.reg_read(UC_X86_REG_ESP)
            module, symbol = struct.unpack("<II", machine.mem_read(stack + 4, 8))
            assert module == _MODULE
            assert (
                bytes(machine.mem_read(symbol, 25)).split(b"\0", 1)[0]
                == b"_Gk3hdAttachNativeMovie@8"
            )
            machine.reg_write(UC_X86_REG_EAX, _ADAPTER if available == "present" else 0)
            calls.append(address)
        elif address == _ADAPTER:
            stack = machine.reg_read(UC_X86_REG_ESP)
            assert struct.unpack("<II", machine.mem_read(stack + 4, 8)) == (_STREAM, _NATIVE)
            machine.reg_write(UC_X86_REG_EAX, 1)
            machine.reg_write(UC_X86_REG_ECX, 0x1234)
            calls.append(address)

    cpu.hook_add(UC_HOOK_CODE, observe)
    before = {
        UC_X86_REG_EAX: 77,
        UC_X86_REG_EBX: 91,
        UC_X86_REG_ECX: 103,
        UC_X86_REG_EDI: _STREAM,
        UC_X86_REG_ESI: 127,
        UC_X86_REG_EBP: 131,
    }
    for register, value in before.items():
        cpu.reg_write(register, value)
    cpu.mem_write(_STACK, struct.pack("<I", _RETURN))
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.emu_start(_CODE, _RETURN)
    assert {register: cpu.reg_read(register) for register in before} == before
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 4
    assert calls == (
        []
        if available == "module-missing"
        else [_PROC]
        if available == "export-missing"
        else [_PROC, _ADAPTER]
    )
