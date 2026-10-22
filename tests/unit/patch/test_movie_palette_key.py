"""Native diagram transparency matches its original five-bit palette in RGB565 too."""

import struct

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_ESP

from gk3hd.patch.definitions.runtime2d.system.movie_overrides import build_palette_key


@pytest.mark.parametrize("available", [False, True])
@pytest.mark.parametrize("original", [False, True])
@pytest.mark.parametrize("color", [0x0000FF00, 0xFF00FF00, 0x00FF00FF, 0xFF123456])
def test_only_private_original_green_keys_match_the_real_palette(
    available: bool, original: bool, color: int
) -> None:
    code, data, resume, native = 0x800000, 0x900000, 0x808000, 0x808100
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(code, 0x10000)
    cpu.mem_map(data, 0x10000)
    cpu.mem_write(
        code,
        build_palette_key(
            wrapper_va=code,
            player_va=data,
            native_vtable=0x699564,
            native_va=native,
            resume_va=resume,
        ),
    )
    cpu.mem_write(native, bytes.fromhex("c20400"))
    cpu.mem_write(data, struct.pack("<I", int(available)))
    cpu.mem_write(data + 0x100, struct.pack("<I", 0x699564 if original else 0x77BA04))
    cpu.reg_write(UC_X86_REG_ESI, data + 0x100)
    cpu.reg_write(UC_X86_REG_ECX, data + 0x200)
    cpu.reg_write(UC_X86_REG_EDX, color)
    cpu.reg_write(UC_X86_REG_ESP, data + 0xF000)
    received = []

    def invoke(machine: Uc, address: int, _size: int, _user: object) -> None:
        if address == native:
            assert machine.reg_read(UC_X86_REG_ECX) == data + 0x200
            pointer = machine.reg_read(UC_X86_REG_ESP)
            received.append(struct.unpack("<I", machine.mem_read(pointer + 4, 4))[0])

    cpu.hook_add(UC_HOOK_CODE, invoke)
    cpu.emu_start(code, resume, count=1000)
    corrected = available and original and color & 0xFFFFFF == 0x00FF00
    assert received == [(color & 0xFF000000) | 0x03FB03 if corrected else color]
    assert cpu.reg_read(UC_X86_REG_ESP) == data + 0xF000
