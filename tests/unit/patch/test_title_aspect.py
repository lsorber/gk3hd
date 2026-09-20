"""Execute the title-only cache fit, including its DirectDraw calling contract."""

import struct
import subprocess
import sys
from pathlib import Path

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EBP,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameABI
from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.system.fixed_screens import FixedScreenFeatureCompiler

BASE, BLT, STATE, STACK = 0x100000, 0x101000, 0x200000, 0x308000
SOURCE, DEST, RESOURCE, SURFACE, VTABLE = (STATE + offset for offset in (256, 512, 768, 1024, 1280))


def _put(cpu: Uc, address: int, *values: int) -> None:
    cpu.mem_write(address, struct.pack(f"<{len(values)}I", *values))


def _words(cpu: Uc, address: int, count: int) -> tuple[int, ...]:
    return struct.unpack(f"<{count}I", cpu.mem_read(address, count * 4))


@pytest.mark.slow
def test_title_cache_aspect_and_unrelated_resource_abi() -> None:
    # Isolate Unicorn from Windows pytest/plugin DLL teardown.
    subprocess.run(  # noqa: S603 - fixed interpreter and this test module.
        [sys.executable, str(Path(__file__).resolve())],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )


def _execute(source: tuple[int, int], dest: tuple[int, int], *, title: bool) -> None:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    stop = GOG_BUILD.address("resource.cache_blt_continue")
    for address in (BASE, STATE, 0x300000, stop & ~0xFFFF):
        cpu.mem_map(address, 0x10000)
    compiler = FixedScreenFeatureCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=STATE + 64, height_va=STATE + 68),
        transition_abi=TransitionFrameABI(0, 0, 0, 0),
    )
    code = compiler.build_title_cache_blt_wrapper(
        wrapper_va=BASE, dest_rect_va=STATE, source_rect_va=STATE + 16, trace_va=STATE + 32
    )
    assert len(code) <= compiler._off_title_cache_blt_limit - compiler._off_title_cache_blt_wrapper
    cpu.mem_write(BASE, code)
    cpu.mem_write(BLT, bytes.fromhex("31c0c21800"))  # success, stdcall Blt's six arguments
    _put(cpu, SOURCE + 0x38, *source)
    _put(cpu, DEST + 0x38, *dest)
    _put(cpu, DEST + 0x2C, SURFACE)
    _put(cpu, RESOURCE + 0x30, SOURCE)
    _put(cpu, SURFACE, VTABLE)
    _put(cpu, VTABLE + 0x14, BLT)
    caller = GOG_BUILD.address("title.cache_resize_return") if title else 0x440925
    _put(cpu, STACK + 128, 0, caller)
    _put(cpu, STACK, SURFACE, 0, SOURCE, 0, 0x1000200, 0)
    for register, value in (
        (UC_X86_REG_ESP, STACK),
        (UC_X86_REG_EBP, STACK + 128),
        (UC_X86_REG_ESI, RESOURCE),
        (UC_X86_REG_EDI, DEST),
        (UC_X86_REG_EDX, VTABLE),
    ):
        cpu.reg_write(register, value)
    calls: list[tuple[int, tuple[int, ...] | None, tuple[int, ...] | None]] = []

    def capture(machine: Uc, address: int, _size: int, _user: object) -> None:
        if address != BLT:
            return
        surface, dest_ptr, src, source_ptr, flags, effects = _words(
            machine, machine.reg_read(UC_X86_REG_ESP) + 4, 6
        )
        assert surface == SURFACE
        if flags == 0x1000400:
            assert (dest_ptr, src, source_ptr) == (0, 0, 0)
            assert _words(machine, effects, 25) == (100, *([0] * 24))
        else:
            assert (src, flags, effects) == (SOURCE, 0x1000200, 0)
        calls.append(
            (
                flags,
                _words(machine, dest_ptr, 4) if dest_ptr else None,
                _words(machine, source_ptr, 4) if source_ptr else None,
            )
        )

    cpu.hook_add(UC_HOOK_CODE, capture)
    cpu.emu_start(BASE, stop, count=1000)
    if source == dest:
        assert calls == [(0x1000200, None, None)]
    else:
        width, height = dest
        if title:
            if width * source[1] // source[0] <= height:
                height = width * source[1] // source[0]
            else:
                width = height * source[0] // source[1]
        x, y = (dest[0] - width) // 2, (dest[1] - height) // 2
        expected = [(0x1000400, None, None)] if title else []
        expected.append((0x1000200, (x, y, x + width, y + height), (0, 0, *source)))
        assert calls == expected
    assert cpu.reg_read(UC_X86_REG_ESP) == STACK + 16  # six arguments popped, two pushes replayed
    assert cpu.reg_read(UC_X86_REG_ESI) == RESOURCE
    assert cpu.reg_read(UC_X86_REG_EDI) == DEST
    assert cpu.reg_read(UC_X86_REG_EBP) == STACK + 128


if __name__ == "__main__":
    for source_size in ((640, 480), (2560, 1920), (1024, 768)):
        for dest_size in ((1024, 768), (1280, 800), (3840, 2160), (800, 1280), (1365, 768)):
            for is_title in (False, True):
                _execute(source_size, dest_size, title=is_title)
