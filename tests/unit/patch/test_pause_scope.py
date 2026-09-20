"""Execute the Pause-only affine and prove its state/thiscall boundaries."""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

import pytest
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameABI
from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.system.fixed_screens import FixedScreenFeatureCompiler

BASE = 0x800000
SYSTEM = BASE + 0x1000
CONTROL = BASE + 0x2000
OUTPUT = BASE + 0x9000
STOP = BASE + 0xA000
STACK = BASE + 0xF000


@pytest.mark.parametrize("size", [(1024, 768), (1280, 800), (3840, 2160)])
@pytest.mark.slow
def test_pause_draw_restores_parent_and_forwards_native_arguments(size: tuple[int, int]) -> None:
    subprocess.run(  # noqa: S603 - fixed interpreter, own module, integer arguments.
        [sys.executable, str(Path(__file__).resolve()), *(str(value) for value in size)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )


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
    code = compiler.build_pause_draw_scope(wrapper_va=BASE, system_va=SYSTEM, control_va=CONTROL)
    assert len(code) <= 0x100
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(BASE, 0x10000)
    native = GOG_BUILD.address("ui.container_draw")
    dimensions = GOG_BUILD.address("display.dimensions")
    machine.mem_map(native & ~0xFFF, 0x1000)
    machine.mem_map(dimensions & ~0xFFF, 0x2000)
    machine.mem_write(dimensions, struct.pack("<II", *size))
    machine.mem_write(BASE, code)
    fields = (
        compiler._off_root_ptr,
        compiler._off_render_depth,
        compiler._off_input_active,
        compiler._off_clear_pending,
        compiler._off_transform_mode,
    )
    prior = (0x123450, 3, 1, 1, 7)
    stub = bytearray(b"\x89\x0d" + struct.pack("<I", OUTPUT))
    for index, stack_offset in enumerate((4, 8), 1):
        stub += b"\x8b\x44\x24" + bytes([stack_offset])
        stub += b"\xa3" + struct.pack("<I", OUTPUT + index * 4)
    for index, (offset, value) in enumerate(zip(fields, prior, strict=True), 3):
        machine.mem_write(SYSTEM + offset, struct.pack("<I", value))
        stub += b"\xa1" + struct.pack("<I", SYSTEM + offset)
        stub += b"\xa3" + struct.pack("<I", OUTPUT + index * 4)
    stub += b"\xb8\x42\x00\x00\x00\xc2\x08\x00"
    machine.mem_write(native, bytes(stub))
    machine.mem_write(STACK, struct.pack("<III", STOP, 0x1234, 0x5678))
    machine.reg_write(UC_X86_REG_ESP, STACK)
    machine.reg_write(UC_X86_REG_ECX, 0xABCDEF)
    machine.emu_start(BASE, STOP, count=1000)
    result = struct.unpack("<8I", machine.mem_read(OUTPUT, 32))
    assert result == (
        0xABCDEF,
        0x1234,
        CONTROL + compiler._off_control_full_damage_region,
        0xABCDEF,
        1,
        0,
        0,
        compiler._mode_local_root_canvas,
    )
    for offset, value in zip(fields, prior, strict=True):
        assert struct.unpack("<I", machine.mem_read(SYSTEM + offset, 4))[0] == value
    assert struct.unpack(
        "<4I", machine.mem_read(CONTROL + compiler._off_control_full_damage_rect, 16)
    ) == (0, 0, *size)
    assert machine.reg_read(UC_X86_REG_EAX) == 0x42
    assert machine.reg_read(UC_X86_REG_ESP) == STACK + 12


if __name__ == "__main__":
    _exercise((int(sys.argv[1]), int(sys.argv[2])))
