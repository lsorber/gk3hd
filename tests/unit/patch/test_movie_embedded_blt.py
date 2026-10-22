"""SIDNEY movies keep one presentation affine with dense or native backings."""

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

from gk3hd.patch.definitions.runtime2d.system.movie_overrides import (
    MovieBlitABI,
    build_embedded_blt,
)

_CODE, _DATA = 0x800000, 0x900000
_NATIVE, _STRETCH, _RETURN = _CODE + 0x8000, _CODE + 0x8100, _CODE + 0x8200
_MOVIE, _TARGET, _SOURCE = _DATA + 0x100, _DATA + 0x200, _DATA + 0x300
_DEST_RECT, _SOURCE_RECT, _STACK = _DATA + 0x400, _DATA + 0x500, _DATA + 0xF000
_TABLE = _DATA + 0x600
_DESTINATION = (202, 194, 634, 578)
_BACKING = (0, 0, 1728, 1536)


def _machine(screen: tuple[int, int], *, replacement: bool, active: bool, offscreen: bool) -> Uc:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(_CODE, 0x10000)
    cpu.mem_map(_DATA, 0x10000)
    cpu.mem_write(_DATA, struct.pack("<III", *screen, int(active)))
    cpu.mem_write(_MOVIE, struct.pack("<I", _TABLE if replacement else _TABLE + 100))
    cpu.mem_write(_TARGET + 0x38, struct.pack("<II", *((640, 480) if offscreen else screen)))
    cpu.mem_write(_DEST_RECT, struct.pack("<4i", *_DESTINATION))
    cpu.mem_write(_SOURCE_RECT, struct.pack("<4i", *_BACKING))
    cpu.mem_write(
        _CODE,
        build_embedded_blt(
            wrapper_va=_CODE,
            abi=MovieBlitABI(_TABLE, _DATA + 8, _DATA, _NATIVE, _STRETCH),
        ),
    )
    for address in (_NATIVE, _STRETCH):
        cpu.mem_write(address, bytes.fromhex("c20c00"))
    cpu.mem_write(_STACK, struct.pack("<4I", _RETURN, _SOURCE, _DEST_RECT, _SOURCE_RECT))
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.reg_write(UC_X86_REG_ECX, _TARGET)
    return cpu


@pytest.mark.parametrize("screen", [(1024, 768), (1280, 800), (3840, 2160), (4096, 3072)])
@pytest.mark.parametrize("replacement", [True, False])
@pytest.mark.parametrize("active", [True, False])
@pytest.mark.parametrize("offscreen", [True, False])
def test_embedded_movie_fit_is_scoped_preserves_source_and_does_not_mutate_ui_state(
    screen: tuple[int, int], *, replacement: bool, active: bool, offscreen: bool
) -> None:
    cpu = _machine(screen, replacement=replacement, active=active, offscreen=offscreen)
    adapted = replacement and active and not offscreen
    calls = []
    saved = {
        UC_X86_REG_EBP: _DATA + 0x8000,
        UC_X86_REG_EBX: 123,
        UC_X86_REG_ESI: _MOVIE + 0x40,
        UC_X86_REG_EDI: 456,
    }
    for register, value in saved.items():
        cpu.reg_write(register, value)

    def blit(machine: Uc, address: int, _size: int, _user: object) -> None:
        if address not in {_NATIVE, _STRETCH}:
            return
        args = struct.unpack("<3I", machine.mem_read(machine.reg_read(UC_X86_REG_ESP) + 4, 12))
        assert args[0] == _SOURCE
        assert args[2] == _SOURCE_RECT
        assert machine.reg_read(UC_X86_REG_ECX) == _TARGET
        calls.append((address, struct.unpack("<4i", machine.mem_read(args[1], 16))))
        machine.reg_write(UC_X86_REG_EAX, 1)

    cpu.hook_add(UC_HOOK_CODE, blit)
    cpu.emu_start(_CODE, _RETURN, count=1000)
    offset = (screen[0] - screen[1] * 4 // 3) // 2
    expected = tuple(
        edge * screen[1] // 768 + (offset if index % 2 == 0 else 0)
        for index, edge in enumerate(_DESTINATION)
    )
    assert calls == [(_STRETCH, expected) if adapted else (_NATIVE, _DESTINATION)]
    assert cpu.mem_read(_DEST_RECT, 16) == struct.pack("<4i", *_DESTINATION)
    assert cpu.mem_read(_SOURCE_RECT, 16) == struct.pack("<4i", *_BACKING)
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 16
    assert cpu.reg_read(UC_X86_REG_EAX) == 1
    assert all(cpu.reg_read(register) == value for register, value in saved.items())
