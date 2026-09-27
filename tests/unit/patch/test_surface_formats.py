"""Execute scratch creation requests; preserve unrelated surfaces and native ABI."""

from __future__ import annotations

import struct

import pytest
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_EFLAGS,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.runtime2d.surface_formats import build_scratch_format_request


@pytest.mark.parametrize("scratch", [True, False])
@pytest.mark.parametrize("dimensions", [(64, 64), (128, 32)])
def test_scratch_request_matches_16_bit_writer_without_changing_other_surfaces(
    *, scratch: bool, dimensions: tuple[int, int]
) -> None:
    """Desktop depth cannot select a different format for software-alpha pixels."""
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    entry, stack, frame = 0x800000, 0x900000, 0x901000
    stop = GOG_BUILD.address("bitmap.creation_descriptor_ready")
    cpu.mem_map(entry, 0x1000)
    cpu.mem_map(stack, 0x2000)
    cpu.mem_map(stop & ~0xFFF, 0x1000)
    caller = GOG_BUILD.site("bitmap.alpha_scratch_creation")
    return_va = caller.va + len(caller.original)
    cpu.mem_write(
        entry,
        build_scratch_format_request(
            entry_va=entry, scratch_return_va=return_va, continuation_va=stop
        ),
    )
    descriptor = bytearray(108)
    struct.pack_into("<IIII", descriptor, 0, 108, 7, dimensions[1], dimensions[0])
    struct.pack_into("<I", descriptor, 104, 0x840)
    cpu.mem_write(frame - 0x78, bytes(descriptor))
    cpu.mem_write(frame + 4, struct.pack("<III", return_va if scratch else 0x123456, *dimensions))
    registers = {
        UC_X86_REG_EAX: 3,
        UC_X86_REG_EBX: 0x765432,
        UC_X86_REG_ECX: 27,
        UC_X86_REG_EDX: 0x555555,
        UC_X86_REG_ESI: 0x666666,
        UC_X86_REG_EDI: 0x777777,
        UC_X86_REG_ESP: stack + 0x800,
        UC_X86_REG_EBP: frame,
        UC_X86_REG_EFLAGS: 0x246,
    }
    for register, value in registers.items():
        cpu.reg_write(register, value)
    cpu.emu_start(entry, stop, count=100)
    actual = bytes(cpu.mem_read(frame - 0x78, 108))
    expected = descriptor.copy()
    if scratch:
        struct.pack_into("<I", expected, 4, 7 | 0x1000)
        struct.pack_into("<8I", expected, 72, 32, 0x40, 0, 16, 0xF800, 0x7E0, 0x1F, 0)
    assert actual == expected
    assert {register: cpu.reg_read(register) for register in registers} == registers
