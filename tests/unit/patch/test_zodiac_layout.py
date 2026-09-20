"""Execute LSR's local extent contract without the proprietary executable."""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

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
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameABI
from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.system.zodiac import ZodiacFeatureCompiler

_BASE = 0x800000
_STOP = _BASE + 0x1000
_STACK = _BASE + 0xF000
_REGISTERS = (
    UC_X86_REG_EAX,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDX,
    UC_X86_REG_ESI,
    UC_X86_REG_EDI,
    UC_X86_REG_EBP,
)


@pytest.mark.slow
def test_zodiac_extents_preserve_native_modes_and_do_not_mutate_display() -> None:
    subprocess.run(  # noqa: S603 - fixed interpreter and own executable test module.
        [sys.executable, str(Path(__file__).resolve())],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _exercise() -> None:
    compiler = ZodiacFeatureCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=_BASE, height_va=_BASE + 4),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=_BASE,
            room_presentation_active_va=_BASE + 4,
            pre_flip_presenter_slot_va=_BASE + 8,
            post_flip_presenter_slot_va=_BASE + 12,
        ),
    )
    dimensions = GOG_BUILD.address("display.dimensions")
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(_BASE, 0x10000)
    machine.mem_map(dimensions & ~0xFFF, 0x2000)
    for size in (
        (640, 480),
        (800, 600),
        (1024, 768),
        (1280, 720),
        (1280, 800),
        (3840, 2160),
        (1080, 1920),
    ):
        native = struct.pack("<II", *size)
        machine.mem_write(dimensions, native)
        logical = (1024, 768) if size[0] > 1024 or size[1] > 768 else size
        for height, ecx in ((False, False), (True, False), (True, True)):
            code = compiler.build_dimension(wrapper_va=_BASE, height=height, output_ecx=ecx)
            assert len(code) <= 0x80
            machine.mem_write(_BASE, code)
            # Each variant changes machine code at the same address.
            machine.ctl_remove_cache(_BASE, _BASE + 0x80)
            machine.mem_write(_STACK, struct.pack("<I", _STOP))
            initial = {reg: 0x123400 + index for index, reg in enumerate(_REGISTERS)}
            for reg, value in initial.items():
                machine.reg_write(reg, value)
            machine.reg_write(UC_X86_REG_ESP, _STACK)
            machine.reg_write(UC_X86_REG_EFLAGS, 0x246)
            machine.emu_start(_BASE, _STOP, count=100)
            output = UC_X86_REG_ECX if ecx else UC_X86_REG_EAX
            assert machine.reg_read(output) == logical[int(height)]
            assert all(
                machine.reg_read(reg) == value for reg, value in initial.items() if reg != output
            )
            assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 4
            assert machine.reg_read(UC_X86_REG_EFLAGS) == 0x246
            assert bytes(machine.mem_read(dimensions, 8)) == native


if __name__ == "__main__":
    _exercise()
