"""Execute scoped button bounds and opacity sampling without game assets."""

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
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameABI
from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.system.load_save import LoadSaveFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.load_save_buttons import LoadSaveButtonCompiler

BASE = 0x800000
ROOT_SLOT = BASE + 0x1000
ROOT = BASE + 0x2000
VTABLE = BASE + 0x3000
MANAGER = BASE + 0x4000
TABLE = BASE + 0x5000
RESOURCE = BASE + 0x6000
SURFACE = BASE + 0x7000
INPUT = BASE + 0x8000
OUTPUT = BASE + 0x9000
NATIVE = BASE + 0xA000
STOP = BASE + 0xB000
TRANSFORM = BASE + 0xC000
STACK = BASE + 0xF000
PRESERVED = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)


@pytest.mark.parametrize("height", [480, 768, 800, 2160, 4320])
@pytest.mark.slow
def test_loadsave_button_geometry_and_pixel_masks(height: int) -> None:
    subprocess.run(  # noqa: S603 - fixed interpreter, own test file, integer argument.
        [sys.executable, str(Path(__file__).resolve()), str(height)],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _write(machine: Uc, address: int, *words: int) -> None:
    machine.mem_write(address, struct.pack(f"<{len(words)}I", *words))


def _read(machine: Uc, address: int, count: int) -> tuple[int, ...]:
    return struct.unpack(f"<{count}I", machine.mem_read(address, count * 4))


def _compiler() -> LoadSaveButtonCompiler:
    return LoadSaveButtonCompiler(
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


def _machine(height: int) -> Uc:
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(BASE, 0x10000)
    for address in (GOG_BUILD.address("display.dimensions"), GOG_BUILD.address("bitmap.manager")):
        machine.mem_map(address & ~0xFFF, 0x1000)
    _write(machine, GOG_BUILD.address("display.dimensions"), height * 16 // 9, height)
    _write(machine, GOG_BUILD.address("bitmap.manager"), MANAGER)
    _write(machine, ROOT_SLOT, ROOT)
    _write(machine, ROOT, GOG_BUILD.address("loadgame.vtable"))
    _write(machine, MANAGER + 0x120, TABLE, 2)
    _write(machine, TABLE + 4, RESOURCE)
    _write(machine, RESOURCE + 0x30, SURFACE)
    _write(machine, VTABLE + 0xA8, NATIVE)
    return machine


def _start(machine: Uc, button: int, *args: int) -> None:
    _write(machine, OUTPUT, *(0xFFFFFFFF for _ in range(6)))
    _write(machine, STACK, STOP, *args)
    for register in PRESERVED:
        machine.reg_write(register, 0x12340000 + register)
    machine.reg_write(UC_X86_REG_ESP, STACK)
    machine.reg_write(UC_X86_REG_ECX, button)
    machine.reg_write(UC_X86_REG_EAX, VTABLE)
    machine.emu_start(BASE, STOP, count=3000)
    assert machine.reg_read(UC_X86_REG_ESP) == STACK + 4 * (1 + len(args))
    assert all(machine.reg_read(reg) == 0x12340000 + reg for reg in PRESERVED)


def _native_recorder(machine: Uc, words: int, argument_bytes: int) -> None:
    # Preserve callee-saved registers, record the by-value copy and original
    # object, and return a distinctive value to verify wrapper propagation.
    machine.mem_write(
        NATIVE,
        b"\x60\x89\x0d"
        + struct.pack("<I", OUTPUT + 16)
        + b"\x8b\x74\x24\x24\xbf"
        + struct.pack("<I", OUTPUT)
        + b"\xb9"
        + struct.pack("<I", words)
        + b"\xfc\xf3\xa5"
        + b"\x61\xb8\xbc\x0a\x00\x00\xc2"
        + struct.pack("<H", argument_bytes),
    )


def _bounds(height: int) -> None:
    compiler = _compiler()
    machine = _machine(height)
    machine.mem_write(BASE, compiler.build_set_rect(wrapper_va=BASE, layout_root_va=ROOT_SLOT))
    _native_recorder(machine, 4, 4)
    for offset, width, native_height in ((0x140, 58, 26), (0x1DC, 145, 39), (0x1DC, 145, 38)):
        button = ROOT + offset
        original = (333, 222, 333 + width, 222 + native_height)
        _write(machine, INPUT, *original)
        for owner in ("loadgame.vtable", "savegame.vtable", "loadsave.vtable"):
            _write(machine, ROOT, GOG_BUILD.address(owner))
            _start(machine, button, INPUT)
            expected = (
                original
                if owner == "loadsave.vtable"
                else (
                    333,
                    222,
                    333 + width * height // 768,
                    222 + native_height * height // 768,
                )
            )
            assert _read(machine, OUTPUT, 4) == expected
            assert _read(machine, INPUT, 4) == original
            assert _read(machine, OUTPUT + 16, 1) == (button,)
            assert machine.reg_read(UC_X86_REG_EAX) == 0xABC
        _write(machine, ROOT, GOG_BUILD.address("loadgame.vtable"))
        _write(machine, ROOT_SLOT, 0)
        _start(machine, button, INPUT)
        assert _read(machine, OUTPUT, 4) == original
        _write(machine, ROOT_SLOT, ROOT)
        _start(machine, button + 4, INPUT)
        assert _read(machine, OUTPUT, 4) == original


def _initial(height: int) -> None:
    compiler = _compiler()
    machine = _machine(height)
    machine.mem_write(BASE, compiler.build_initial_bounds(wrapper_va=BASE, transform_va=TRANSFORM))
    feature = LoadSaveFeatureCompiler(
        symbols=compiler.symbols,
        profile=compiler.profile,
        room_rendering_abi=compiler.room_rendering_abi,
        transition_abi=compiler.transition_abi,
    )
    machine.mem_write(TRANSFORM, feature.build_loadsave_rect_transform())
    for width, native_height in ((58, 26), (145, 39), (145, 38)):
        _write(machine, INPUT, 333, 222, 333 + width, 222 + native_height)
        _start(machine, INPUT)
        left, top, right, bottom = _read(machine, INPUT, 4)
        assert right - left == width * height // 768
        assert bottom - top == native_height * height // 768


def _hit(height: int) -> None:
    compiler = _compiler()
    machine = _machine(height)
    machine.mem_write(
        BASE,
        compiler.build_pixel_hit(
            wrapper_va=BASE,
            layout_root_va=ROOT_SLOT,
            native_va=NATIVE,
        ),
    )
    _native_recorder(machine, 2, 8)
    for offset, width, native_height in ((0x140, 58, 26), (0x1DC, 145, 39), (0x1DC, 145, 38)):
        button = ROOT + offset
        physical_width, physical_height = width * height // 768, native_height * height // 768
        _write(machine, button + 0x1C, 333, 222, 333 + physical_width, 222 + physical_height)
        for density in (1, 4):
            _write(machine, SURFACE + 0x38, width * density, native_height * density)
            for x, y in (
                (0, 0),
                (physical_width // 2, physical_height // 2),
                (physical_width - 1, physical_height - 1),
                (-1, 0),
                (physical_width, 0),
                (0, physical_height),
            ):
                point = (333 + x, 222 + y)
                _write(machine, INPUT, *point)
                _start(machine, button, INPUT, 1)
                outside = not (0 <= x < physical_width and 0 <= y < physical_height)
                if outside:
                    assert machine.reg_read(UC_X86_REG_EAX) == 0
                    assert _read(machine, OUTPUT, 2) == (0xFFFFFFFF, 0xFFFFFFFF)
                else:
                    sample = (
                        x * 768 // height * density + density // 2,
                        y * 768 // height * density + density // 2,
                    )
                    assert sample[0] < width * density
                    assert sample[1] < native_height * density
                    assert _read(machine, OUTPUT, 2) == (333 + sample[0], 222 + sample[1])
                    assert machine.reg_read(UC_X86_REG_EAX) == 0xABC
                assert _read(machine, INPUT, 2) == point
            # Reject width-only density guesses and all missing-resource paths.
            for address, bad_value in (
                (SURFACE + 0x3C, 101),
                (ROOT_SLOT, 0),
                (GOG_BUILD.address("bitmap.manager"), 0),
                (MANAGER + 0x120, 0),
                (MANAGER + 0x124, 1),
                (TABLE + 4, 0),
                (RESOURCE + 0x30, 0),
            ):
                previous = _read(machine, address, 1)[0]
                _write(machine, address, bad_value)
                _write(machine, INPUT, 341, 227)
                _start(machine, button, INPUT, 1)
                assert _read(machine, OUTPUT, 2) == (341, 227)
                _write(machine, address, previous)


if __name__ == "__main__":
    _bounds(int(sys.argv[1]))
    _initial(int(sys.argv[1]))
    _hit(int(sys.argv[1]))
