"""Execute SaveGame's scoped glyph/caret affine, including native fallthrough."""

import struct
import subprocess
import sys
from pathlib import Path

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameABI
from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.sidney_alpha import build_caret_wrapper
from gk3hd.patch.definitions.runtime2d.system.load_save import LoadSaveFeatureCompiler

BASE, HELPER, TARGET, STOP = 0x100000, 0x101000, 0x102000, 0x103000
STATE, ROOT, RECT, STACK = 0x200000, 0x201000, 0x203000, 0x308000


def _put(cpu: Uc, address: int, *values: int) -> None:
    cpu.mem_write(address, struct.pack(f"<{len(values)}I", *values))


def _words(cpu: Uc, address: int, count: int) -> tuple[int, ...]:
    return struct.unpack(f"<{count}I", cpu.mem_read(address, count * 4))


@pytest.mark.parametrize("height", [768, 800, 1440, 2160])
@pytest.mark.parametrize("active", [False, True])
@pytest.mark.slow
def test_save_caret_preserves_anchor_colors_arguments_and_input_rect(
    height: int,
    active: bool,
) -> None:
    subprocess.run(  # noqa: S603 - fixed interpreter and this test module.
        [sys.executable, str(Path(__file__).resolve()), str(height), str(int(active))],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )


def _execute(height: int, active: bool) -> None:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    for address in (BASE, STATE, 0x300000):
        cpu.mem_map(address, 0x10000)
    display = GOG_BUILD.address("display.dimensions")
    cpu.mem_map(display & ~0xFFF, 0x1000)
    _put(cpu, display, 3840, height)
    compiler = LoadSaveFeatureCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=STATE + 8, height_va=STATE + 12),
        transition_abi=TransitionFrameABI(0, 0, 0, 0),
    )
    cpu.mem_write(
        HELPER,
        compiler.build_loadsave_font_rect_helper(
            wrapper_va=HELPER,
            root_ptr_va=STATE,
            active_text_va=STATE + 4,
            trace_count_va=STATE + 32,
            trace_input_va=STATE + 36,
            trace_output_va=STATE + 44,
        ),
    )
    cpu.mem_write(
        BASE,
        build_caret_wrapper(
            wrapper_va=BASE,
            target_va=TARGET,
            resolve_bitmap_va=STOP,
            active_depth_va=STATE + 16,
            physical_width_va=STATE + 8,
            save_text_active_va=STATE + 4,
            save_edit_vtable_va=GOG_BUILD.address("savegame_edit.vtable"),
            save_point_helper_va=HELPER,
        ),
    )
    cpu.mem_write(TARGET, bytes.fromhex("c21000"))
    _put(cpu, STATE, ROOT, ROOT + 0x340 if active else 0, 3840, height)
    _put(cpu, ROOT, GOG_BUILD.address("savegame.vtable"))
    _put(cpu, ROOT + 0x340, GOG_BUILD.address("savegame_edit.vtable"))
    _put(cpu, ROOT + 0x340 + 0x1C, 1118, 703, 1619, 748)
    original = (1186, 703, 1188, 715)
    _put(cpu, RECT, *original)
    _put(cpu, STACK, STOP, 37, 0x2FABC1, 0x2FABC1, RECT)
    cpu.reg_write(UC_X86_REG_ESP, STACK)
    cpu.reg_write(UC_X86_REG_ECX, 0x123456)
    observed: list[tuple[int, ...]] = []

    def capture(machine: Uc, address: int, _size: int, _user: object) -> None:
        if address == TARGET:
            args = _words(machine, machine.reg_read(UC_X86_REG_ESP) + 4, 4)
            assert args[:3] == (37, 0x2FABC1, 0x2FABC1)
            assert machine.reg_read(UC_X86_REG_ECX) == 0x123456
            observed.append(_words(machine, args[3], 4))

    cpu.hook_add(UC_HOOK_CODE, capture)
    cpu.emu_start(BASE, STOP, count=1000)
    expected = (
        tuple(
            origin + (value - origin) * height // 768
            for value, origin in zip(original, (1118, 703, 1118, 703), strict=True)
        )
        if active
        else original
    )
    assert observed == [expected]
    assert _words(cpu, RECT, 4) == original
    assert cpu.reg_read(UC_X86_REG_ESP) == STACK + 20


if __name__ == "__main__":
    _execute(int(sys.argv[1]), bool(int(sys.argv[2])))
