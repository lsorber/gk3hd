"""Execute the Inventory-to-renderer adapter without Windows or game assets."""

from __future__ import annotations

import struct
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_EIP,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.runtime2d.inventory_filter import (
    CACHE_OFFSET,
    CALL_COUNT_OFFSET,
    HANDLED_COUNT_OFFSET,
    NAMES_OFFSET,
    WRAPPER_OFFSET,
    build_area_adapter,
)

BASE = 0x800000
DATA = 0x900000
STACK = 0xA00F00
STOP = 0x830000
MODULE = 0x820000
RESOLVE = 0x820100
EXPORT = 0x820200
NATIVE = 0x820300
ARGS = (0x920000, 128, DATA + 0x100, DATA + 0x108)
REGISTERS = {
    UC_X86_REG_EAX: 0x12345678,
    UC_X86_REG_ECX: DATA,
    UC_X86_REG_EDX: 0x23456789,
    UC_X86_REG_EBX: 0x3456789A,
    UC_X86_REG_ESI: 0x456789AB,
    UC_X86_REG_EDI: 0x56789ABC,
    UC_X86_REG_EBP: 0x6789ABCD,
}


@dataclass
class _Probe:
    loaded: bool
    available: bool
    handled: bool
    calls: dict[int, int] = field(
        default_factory=lambda: {MODULE: 0, RESOLVE: 0, EXPORT: 0, NATIVE: 0}
    )


def _words(machine: Uc, address: int, count: int) -> tuple[int, ...]:
    return struct.unpack(f"<{count}I", machine.mem_read(address, count * 4))


def _write(machine: Uc, address: int, *words: int) -> None:
    machine.mem_write(address, struct.pack(f"<{len(words)}I", *words))


@pytest.mark.parametrize(
    ("dense", "loaded", "available", "handled"),
    [
        (True, True, True, True),
        (True, True, True, False),
        (True, False, False, False),
        (True, True, False, False),
        (False, True, True, True),
    ],
)
@pytest.mark.slow
def test_area_adapter_preserves_native_contract_and_maps_every_request_word(
    *, dense: bool, loaded: bool, available: bool, handled: bool
) -> None:
    # Unicorn's Windows JIT uses handled access violations while committing
    # guest pages. Isolate it from pytest's fatal-signal handler (and isolate a
    # real native crash from the rest of the test runner); do not mute pytest.
    subprocess.run(  # noqa: S603 - fixed interpreter, own module and boolean arguments.
        [
            sys.executable,
            str(Path(__file__).resolve()),
            *(str(int(value)) for value in (dense, loaded, available, handled)),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _setup_machine(*, dense: bool) -> Uc:
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(BASE, 0x40000)
    machine.mem_map(DATA, 0x40000)
    machine.mem_map(0xA00000, 0x10000)
    machine.mem_map(0x660000, 0x10000)

    def write(address: int, *words: int) -> None:
        machine.mem_write(address, struct.pack(f"<{len(words)}I", *words))

    machine.mem_write(
        BASE + WRAPPER_OFFSET,
        build_area_adapter(
            profile=GOG_BUILD,
            filter_va=BASE,
            native_va=NATIVE,
            dense_source_va=0x810000,
            source_rect_va=0x810010,
            dest_width_va=0x810020,
            dest_height_va=0x810024,
        ),
    )
    machine.mem_write(BASE + NAMES_OFFSET, b"ddraw.dll\0".ljust(16, b"\0") + b"Gk3hdAreaBlend565\0")
    write(0x810000, int(dense))
    write(0x810010, 5, 7, 381, 383, 94, 94)
    write(GOG_BUILD.address("win32.GetModuleHandleA"), MODULE)
    write(GOG_BUILD.address("win32.GetProcAddress"), RESOLVE)
    for address, arguments in ((MODULE, 4), (RESOLVE, 8), (EXPORT, 4), (NATIVE, 16)):
        machine.mem_write(address, b"\xc2" + struct.pack("<H", arguments))
    for offset, value in (
        (0x30, 0x910000),
        (0x40, 0x918000),
        (0x34, 752),
        (0x44, 376),
        (0x38, 0xFFFFFFFF),
        (0x48, 65794),
    ):
        write(DATA + offset, value)
    write(DATA + 0x100, 62, 30)
    write(DATA + 0x108, 32, 64)
    return machine


def _observe(machine: Uc, address: int, _size: int, data: object) -> None:
    assert isinstance(data, _Probe)
    if address not in data.calls:
        return
    data.calls[address] += 1
    sp = machine.reg_read(UC_X86_REG_ESP)
    if address == MODULE:
        assert _words(machine, sp + 4, 1) == (BASE + NAMES_OFFSET,)
        machine.reg_write(UC_X86_REG_EAX, 0x710000 if data.loaded else 0)
    elif address == RESOLVE:
        assert _words(machine, sp + 4, 2) == (0x710000, BASE + NAMES_OFFSET + 16)
        machine.reg_write(UC_X86_REG_EAX, EXPORT if data.available else 0)
    elif address == EXPORT:
        request = _words(machine, sp + 4, 1)[0]
        assert _words(machine, request, 17) == (
            68,
            0x910000,
            0x918000,
            0x920000,
            752,
            376,
            128,
            376,
            376,
            94,
            94,
            32,
            64,
            62,
            30,
            0xFFFFFFFF,
            65794,
        )
        machine.reg_write(UC_X86_REG_EAX, int(data.handled))
    else:
        assert sp == STACK
        assert _words(machine, sp + 4, 4) == ARGS
        assert all(machine.reg_read(register) == value for register, value in REGISTERS.items())


def _exercise_adapter(*, dense: bool, loaded: bool, available: bool, handled: bool) -> None:
    machine = _setup_machine(dense=dense)
    probe = _Probe(loaded, available, handled)
    machine.hook_add(UC_HOOK_CODE, _observe, user_data=probe)
    for _ in range(2):
        _write(machine, STACK, STOP, *ARGS)
        for register, value in REGISTERS.items():
            machine.reg_write(register, value)
        machine.reg_write(UC_X86_REG_ESP, STACK)
        machine.emu_start(BASE + WRAPPER_OFFSET, STOP, count=10000)
        assert machine.reg_read(UC_X86_REG_EIP) == STOP
        assert machine.reg_read(UC_X86_REG_ESP) == STACK + 20
        assert all(machine.reg_read(register) == value for register, value in REGISTERS.items())
    uses_export = dense and loaded and available
    calls = probe.calls
    assert calls[EXPORT] == (2 if uses_export else 0)
    assert calls[NATIVE] == (0 if uses_export and handled else 2)
    assert calls[MODULE] == (0 if not dense else 1 if loaded else 2)
    assert calls[RESOLVE] == (1 if dense and loaded else 0)
    assert _words(machine, BASE + CALL_COUNT_OFFSET, 1) == (calls[EXPORT],)
    assert _words(machine, BASE + HANDLED_COUNT_OFFSET, 1) == (2 if uses_export and handled else 0,)
    assert _words(machine, BASE + CACHE_OFFSET, 1) == (
        EXPORT if uses_export else 0xFFFFFFFF if dense and loaded else 0,
    )


if __name__ == "__main__":
    _exercise_adapter(
        dense=bool(int(sys.argv[1])),
        loaded=bool(int(sys.argv[2])),
        available=bool(int(sys.argv[3])),
        handled=bool(int(sys.argv[4])),
    )
