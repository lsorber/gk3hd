"""Execute Death's reference-rounded placement without the game or Windows."""

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
    UC_X86_REG_EIP,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameABI
from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.system.fixed_screens import FixedScreenFeatureCompiler

BASE = 0x800000
NATIVE = BASE + 0x1000
STOP = BASE + 0x2000
BUTTON = BASE + 0x3000
VTABLE = BASE + 0x4000
OUTPUT = BASE + 0x5000
STACK = BASE + 0xF000
REGISTERS = (
    UC_X86_REG_EAX,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDX,
    UC_X86_REG_ESI,
    UC_X86_REG_EDI,
    UC_X86_REG_EBP,
)


@pytest.mark.parametrize("size", [(640, 480), (1024, 768), (1280, 800), (3840, 2160), (1080, 1920)])
@pytest.mark.slow
def test_death_layout_retains_reference_centres_and_native_virtual_contract(
    size: tuple[int, int],
) -> None:
    # Isolate Unicorn's Windows JIT from pytest's fatal-signal handler.
    subprocess.run(  # noqa: S603 - fixed interpreter, own module, integer arguments.
        [sys.executable, str(Path(__file__).resolve()), *(str(value) for value in size)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _write(machine: Uc, address: int, *words: int) -> None:
    machine.mem_write(address, struct.pack(f"<{len(words)}I", *words))


def _exercise(size: tuple[int, int]) -> None:
    compiler = FixedScreenFeatureCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=BASE, height_va=BASE + 4),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=BASE,
            room_presentation_active_va=BASE + 4,
            pre_flip_presenter_slot_va=BASE + 8,
            post_flip_presenter_slot_va=BASE + 12,
        ),
    )
    code = compiler.build_death_button_layout(wrapper_va=BASE)
    assert len(code) <= 0xF0
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(BASE, 0x10000)
    dimensions = GOG_BUILD.address("display.dimensions")
    machine.mem_map(dimensions & ~0xFFF, 0x2000)
    _write(machine, dimensions, *size)
    machine.mem_write(BASE, code)
    _write(machine, BUTTON, VTABLE)
    _write(machine, VTABLE + 0xA8, NATIVE)
    # Test SetRect copies its stack-local RECT and records the native `this`.
    machine.mem_write(
        NATIVE,
        b"\x89\x0d"
        + struct.pack("<I", OUTPUT + 16)
        + b"\x8b\x74\x24\x04\xbf"
        + struct.pack("<I", OUTPUT)
        + b"\xb9\x04\x00\x00\x00\xfc\xf3\xa5\xc2\x04\x00",
    )
    for left, reference_centre in ((181, 354), (280, 512), (379, 671)):
        authored = (left, 430, left + 81, 456)
        _write(machine, BUTTON + 0x1C, *authored)
        _write(machine, STACK, STOP, BUTTON)
        for register in REGISTERS:
            machine.reg_write(register, 0x12340000 + register)
        machine.reg_write(UC_X86_REG_ESP, STACK)
        machine.emu_start(BASE, STOP, count=1000)
        assert machine.reg_read(UC_X86_REG_EIP) == STOP
        assert machine.reg_read(UC_X86_REG_ESP) == STACK + 4
        assert all(machine.reg_read(reg) == 0x12340000 + reg for reg in REGISTERS)
        x = reference_centre * size[0] // 1024 - 40
        y = 708 * size[1] // 768 - 13
        assert struct.unpack("<5I", machine.mem_read(OUTPUT, 20)) == (
            x,
            y,
            x + 81,
            y + 26,
            BUTTON,
        )
        # All movement goes through SetRect, never direct writes to the child.
        assert struct.unpack("<4I", machine.mem_read(BUTTON + 0x1C, 16)) == authored
        assert struct.unpack("<2I", machine.mem_read(dimensions, 8)) == size


if __name__ == "__main__":
    _exercise((int(sys.argv[1]), int(sys.argv[2])))
