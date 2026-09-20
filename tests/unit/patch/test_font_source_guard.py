"""Only the live atlas may inherit density during a nested font alpha call."""

import struct
import subprocess
import sys
from pathlib import Path

import pytest
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.definitions.runtime2d.font_sampling import build_font_source_guard

BASE, STOP, STACK = 0x100000, 0x101000, 0x102000
ACTIVE, MANAGER, FRAME = 0x103000, 0x103010, 0x104000
OBJECT, TABLE, RESOURCE, SURFACE = 0x105000, 0x106000, 0x107000, 0x108000


def run() -> None:
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(BASE, 0x10000)
    code = build_font_source_guard(base_va=BASE, active_handle_va=ACTIVE, manager_va=MANAGER)
    assert len(code) <= 0x100
    machine.mem_write(BASE, code)
    for handle in (1, 7, 63):
        for fault in ("", "inactive", "manager", "range", "table", "resource", "null", "scratch"):
            fields = {
                ACTIVE: handle,
                MANAGER: OBJECT,
                OBJECT + 0x124: handle + 1,
                OBJECT + 0x120: TABLE,
                TABLE + handle * 4: RESOURCE,
                RESOURCE + 0x30: SURFACE,
                FRAME + 0x24: SURFACE,
                STACK: STOP,
            }
            changes = {
                "inactive": (ACTIVE, 0),
                "manager": (MANAGER, 0),
                "range": (OBJECT + 0x124, handle),
                "table": (OBJECT + 0x120, 0),
                "resource": (TABLE + handle * 4, 0),
                "null": (FRAME + 0x24, 0),
                "scratch": (FRAME + 0x24, SURFACE + 0x100),
            }
            if fault:
                address, value = changes[fault]
                fields[address] = value
            for address, value in fields.items():
                machine.mem_write(address, struct.pack("<I", value))
            machine.reg_write(UC_X86_REG_ECX, FRAME)
            machine.reg_write(UC_X86_REG_ESP, STACK)
            preserved = {UC_X86_REG_EBX: 0x123, UC_X86_REG_ESI: 0x456, UC_X86_REG_EDI: 0x789}
            for register, value in preserved.items():
                machine.reg_write(register, value)
            machine.emu_start(BASE, STOP, count=100)
            assert machine.reg_read(UC_X86_REG_EAX) == int(not fault), (handle, fault)
            assert machine.reg_read(UC_X86_REG_ESP) == STACK + 4
            assert all(machine.reg_read(register) == value for register, value in preserved.items())


@pytest.mark.slow
def test_font_source_identity() -> None:
    subprocess.run(  # noqa: S603 - fixed interpreter and this test module.
        [sys.executable, str(Path(__file__).resolve())], check=True, timeout=10
    )


if __name__ == "__main__":
    run()
