"""Execute isolated tooltip glyph routing, including its native fallback."""

import struct

import pytest
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.binary.x86 import X86Emitter
from gk3hd.patch.definitions.runtime2d.system.menu_tooltip import TooltipFeatureCompiler
from tests.unit.patch.test_registry import _caption_compiler

_START, _AFFINE, _LOCAL, _STOP = range(0x880000, 0x884000, 0x1000)
_STATE, _OBJECT, _ORIGINAL, _PRIVATE, _DEST, _SOURCE, _SCRATCH, _STACK = range(
    0x900000, 0x908000, 0x1000
)


def _write(cpu: Uc, address: int, *values: int) -> None:
    cpu.mem_write(address, struct.pack(f"<{len(values)}I", *values))


@pytest.mark.parametrize("height", [768, 800, 2160])
@pytest.mark.parametrize("anchor", [(0, 0), (373, 261), (3000, 1800)])
@pytest.mark.parametrize("mode", [0, 1, 2])
@pytest.mark.parametrize("has_cache", [False, True])
def test_tooltip_glyphs_draw_locally_without_borrowing_the_live_page(
    height: int, anchor: tuple[int, int], mode: int, has_cache: bool
) -> None:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x600000)
    base = _caption_compiler()
    compiler = TooltipFeatureCompiler(
        profile=base.profile,
        symbols=base.symbols,
        room_rendering_abi=base.room_rendering_abi,
        transition_abi=base.transition_abi,
    )
    affine = compiler.build_tooltip_transfer_affine(
        wrapper_va=_AFFINE,
        downstream_va=_STOP,
        object_ptr_va=_STATE,
        dest_rect_va=_SCRATCH,
        transform_count_va=_STATE + 4,
        local_transfer_va=_LOCAL,
    )
    local = compiler.build_tooltip_local_transfer(
        wrapper_va=_LOCAL,
        local_wrapper_va=_PRIVATE,
        panel_surface_va=_STATE + 8,
        panel_dimensions_va=_STATE + 12,
        outer_rect_va=_STATE + 20,
        dest_rect_va=_SCRATCH,
        composition_mode_va=_STATE + 36,
    )
    entry = X86Emitter(base_va=_START)
    entry.raw(b"\x60\x8b\xcc")
    entry.jump_absolute(_AFFINE)
    cpu.mem_write(_START, entry.build())
    cpu.mem_write(_AFFINE, affine)
    cpu.mem_write(_LOCAL, local)
    _write(cpu, _STATE, _OBJECT, 0, 0x12345678 if has_cache else 0, 160, 40, *anchor, 0, 0, mode)
    _write(cpu, _OBJECT + 0x1C, *anchor)
    _write(cpu, base.profile.address("display.dimensions"), 3840, height)
    original = struct.pack("<12I", *range(1, 13))
    cpu.mem_write(_ORIGINAL, original)
    destination = struct.pack("<4I", anchor[0] + 3, anchor[1] + 2, anchor[0] + 11, anchor[1] + 14)
    source = struct.pack("<4I", 10, 20, 42, 68)
    cpu.mem_write(_DEST, destination)
    cpu.mem_write(_SOURCE, source)
    stack = _STACK + 0x800
    _write(cpu, stack, _STOP, 0x11111111, _DEST, _SOURCE)
    registers = {
        UC_X86_REG_EBP: 99,
        UC_X86_REG_EBX: 100,
        UC_X86_REG_ESI: 101,
        UC_X86_REG_EDI: 102,
        UC_X86_REG_EDX: 103,
        UC_X86_REG_ECX: _ORIGINAL,
    }
    for register, value in registers.items():
        cpu.reg_write(register, value)
    cpu.reg_write(UC_X86_REG_ESP, stack)
    cpu.emu_start(_START, _STOP, count=1000)
    assert cpu.reg_read(UC_X86_REG_ESP) == stack
    assert cpu.mem_read(_ORIGINAL, 48) == original
    assert cpu.mem_read(_DEST, 16) == destination
    assert cpu.mem_read(_SOURCE, 16) == source
    for register, value in registers.items():
        if register != UC_X86_REG_ECX:
            assert cpu.reg_read(register) == value
    expected = tuple(
        (edge * height + rounding) // 768
        for edge, rounding in ((3, 0), (2, 0), (11, 767), (14, 767))
    )
    if mode == 2 and has_cache:
        assert cpu.reg_read(UC_X86_REG_ECX) == _PRIVATE
        wrapper = struct.unpack("<12I", cpu.mem_read(_PRIVATE, 48))
        assert wrapper[2:4] == (160, 40)
        assert wrapper[10] == 0, "private destination borrowed a copied critical section"
        assert wrapper[11] == 0x12345678
        assert wrapper[:2] == (1, 2)
    else:
        assert cpu.reg_read(UC_X86_REG_ECX) == _ORIGINAL
        assert cpu.mem_read(_PRIVATE, 48) == bytes(48)
        expected = tuple(edge + anchor[index % 2] for index, edge in enumerate(expected))
    assert struct.unpack("<4I", cpu.mem_read(_SCRATCH, 16)) == expected
    assert struct.unpack("<I", cpu.mem_read(stack + 8, 4))[0] == _SCRATCH
