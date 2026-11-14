"""Standalone numeric conversion keeps native results and caller state."""

from __future__ import annotations

import math
import struct
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ESP

from gk3hd.patch.builds import SUPPORTED_BUILDS
from gk3hd.patch.model import PatchError
from gk3hd.vr.standalone.pack import _standalone_cpu_source
from tests.unit.patch.test_complete_compilation import _source

if TYPE_CHECKING:
    from gk3hd.patch.builds import BuildProfile


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
@pytest.mark.parametrize("rounding", range(4))
def test_conversion_truncates_without_changing_rounding_or_remaining_stack(
    profile: BuildProfile, rounding: int
) -> None:
    source = _source(profile)
    before = source.to_bytes()
    image = _standalone_cpu_source(source, profile)
    assert source.to_bytes() == before
    site = profile.site("engine.float_to_int64")
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(site.va & ~0xFFF, 0x1000)
    machine.mem_write(site.va, image.read_bytes(image.va_to_offset(site.va), len(site.original)))
    machine.mem_map(0x1000, 0x4000)
    # Keep a second x87 value beneath the argument, then observe caller state.
    code = bytes.fromhex("db e3 d9 2d 00 20 00 00 d9 e8 dd 05 10 20 00 00")
    call = 0x1000 + len(code)
    code += b"\xe8" + struct.pack("<i", site.va - call - 5)
    code += bytes.fromhex("d9 3d 40 20 00 00 dd 1d 30 20 00 00")
    machine.mem_write(0x1000, code)
    for precision in (0, 2, 3):
        control = 0x7F | precision << 8 | rounding << 10
        for value in (0.0, -0.0, 0.9, -0.9, 1.75, -1.75, 2**31 + 0.5, -(2**31) - 0.5):
            machine.mem_write(0x2000, struct.pack("<H", control))
            machine.mem_write(0x2010, struct.pack("<d", value))
            machine.reg_write(UC_X86_REG_ESP, 0x4FF0)
            machine.emu_start(0x1000, 0x1000 + len(code), count=100)
            result = machine.reg_read(UC_X86_REG_EAX) | machine.reg_read(UC_X86_REG_EDX) << 32
            assert result == math.trunc(value) & 0xFFFFFFFFFFFFFFFF
            assert machine.mem_read(0x2040, 2) == struct.pack("<H", control)
            assert struct.unpack("<d", machine.mem_read(0x2030, 8))[0] == 1.0
            assert machine.reg_read(UC_X86_REG_ESP) == 0x4FF0


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
def test_unknown_conversion_code_is_rejected_without_mutating_source(profile: BuildProfile) -> None:
    source = _source(profile)
    source.write_bytes(source.va_to_offset(profile.site("engine.float_to_int64").va), b"\xcc")
    before = source.to_bytes()
    with pytest.raises(PatchError, match="standalone_float_conversion"):
        _standalone_cpu_source(source, profile)
    assert source.to_bytes() == before
