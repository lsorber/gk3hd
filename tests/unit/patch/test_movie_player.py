"""AV1 adapter lookup preserves the game's COM ABI and never searches cwd."""

from __future__ import annotations

import struct

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_EDI,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.definitions.runtime2d.system.movie_player import (
    PLAYER_EXPORT,
    PLAYER_PATH,
    MoviePlayerABI,
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
    abi = MoviePlayerABI(_DATA, _DATA + 4, _DATA + 8, _DATA + 0x500, _DATA + 0x600, _CACHE)
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
