"""Execute fingerprint-tool identity, clipping and drag-coordinate contracts."""

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
    UC_X86_REG_ECX,
    UC_X86_REG_EFLAGS,
    UC_X86_REG_EIP,
    UC_X86_REG_ESP,
)

from gk3hd.patch.definitions.runtime2d.fingerprint_tools import (
    build_damage_selector,
    build_dust_input,
    build_tool_match,
    build_tool_transform,
)
from gk3hd.patch.definitions.runtime2d.ui_frames import FINGERPRINT_TOOL_IMAGES

TOOL_SIZES = {name.decode(): (width, height) for name, width, height in FINGERPRINT_TOOL_IMAGES}

BASE = 0x800000
MATCH = BASE + 0x1000
STOP = BASE + 0x2000
STATE = BASE + 0x3000
MANAGER_SLOT = STATE + 0x10
MANAGER = STATE + 0x100
TABLE = STATE + 0x300
RESOURCE = STATE + 0x400
SURFACE = STATE + 0x500
TARGET = STATE + 0x600
DIMENSIONS = STATE + 0x700
DEST = STATE + 0x800
SOURCE = STATE + 0x810
OUT_DEST = STATE + 0x820
OUT_SOURCE = STATE + 0x830
STACK = BASE + 0xF000


@pytest.mark.slow
def test_moving_tool_code_executes_identity_scope_and_clip_contracts() -> None:
    # Isolate the Windows JIT's handled access violations from pytest.
    subprocess.run(  # noqa: S603 - fixed interpreter and own module.
        [sys.executable, str(Path(__file__).resolve())],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _write(machine: Uc, address: int, *words: int) -> None:
    machine.mem_write(address, struct.pack(f"<{len(words)}I", *(n & 0xFFFFFFFF for n in words)))


def _words(machine: Uc, address: int, count: int = 4) -> tuple[int, ...]:
    return struct.unpack(f"<{count}i", machine.mem_read(address, count * 4))


def _machine(name: str, density: int, size: tuple[int, int]) -> Uc:
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(BASE, 0x10000)
    match = build_tool_match(wrapper_va=MATCH, manager_va=MANAGER_SLOT)
    prefix = build_tool_transform(
        wrapper_va=BASE,
        match_va=MATCH,
        layout_active_va=STATE,
        dimensions_va=DIMENSIONS,
        dest_rect_va=OUT_DEST,
        source_rect_va=OUT_SOURCE,
    )
    assert len(match) <= 0xE00 - 0xCA0
    assert len(prefix) + 1045 <= 0x900 - 0x200
    machine.mem_write(MATCH, match)
    machine.mem_write(BASE, prefix + b"\xc3")
    _write(machine, STATE, 1)
    _write(machine, MANAGER_SLOT, MANAGER)
    _write(machine, MANAGER + 0x120, TABLE, 2)
    _write(machine, TABLE, 0, RESOURCE)
    machine.mem_write(RESOURCE + 8, name.encode() + b"\0")
    _write(machine, RESOURCE + 0x30, SURFACE)
    native_width, native_height = TOOL_SIZES.get(name.lower(), (24, 114))
    _write(machine, SURFACE + 0x38, native_width * density, native_height * density)
    _write(machine, DIMENSIONS, *size)
    _write(machine, TARGET + 0x38, *size)
    _write(machine, STACK, STOP)
    _write(machine, STACK + 0x1C, TARGET)
    _write(machine, STACK + 0x28, SURFACE, DEST, SOURCE)
    machine.reg_write(UC_X86_REG_ESP, STACK)
    return machine


def _exercise_geometry() -> None:
    for name in (*TOOL_SIZES, *(name.upper() for name in TOOL_SIZES)):
        native_width, native_height = TOOL_SIZES[name.lower()]
        for density in (1, 4):
            for width, height in ((1024, 768), (1280, 800), (3840, 2160)):
                for x, y in ((100, 120), (-5, -9), (width - 8, height - 20)):
                    machine = _machine(name, density, (width, height))
                    near = (max(x, 0), max(y, 0))
                    far = (min(x + native_width, width), min(y + native_height, height))
                    destination = (*near, *far)
                    source = (
                        (near[0] - x) * density,
                        (near[1] - y) * density,
                        (far[0] - x) * density,
                        (far[1] - y) * density,
                    )
                    _write(machine, DEST, *destination)
                    _write(machine, SOURCE, *source)
                    machine.emu_start(BASE, STOP, count=10000)
                    assert machine.reg_read(UC_X86_REG_EIP) == STOP
                    assert machine.reg_read(UC_X86_REG_ESP) == STACK + 4
                    assert _words(machine, STACK + 0x2C, 2) == (OUT_DEST, OUT_SOURCE)
                    expected_dest = [0] * 4
                    expected_source = [0] * 4
                    for axis, (origin, native, limit) in enumerate(
                        ((x, native_width, width), (y, native_height, height))
                    ):
                        extent = (native * height + 384) // 768
                        raster = native * density
                        expected_dest[axis] = max(origin, 0)
                        expected_dest[axis + 2] = min(origin + extent, limit)
                        expected_source[axis] = max(-origin, 0) * raster // extent
                        expected_source[axis + 2] = (
                            raster - max(origin + extent - limit, 0) * raster // extent
                        )
                    assert _words(machine, OUT_DEST) == tuple(expected_dest)
                    assert _words(machine, OUT_SOURCE) == tuple(expected_source)
                    assert _words(machine, DEST) == destination
                    assert _words(machine, SOURCE) == source


def _exercise_rejections() -> None:
    for name in (
        "C_FPBRUSH_EXTRA",
        "C_FPBRUSH_WDUST2",
        "C_OTHER",
        "FP_BRUSH",
        "C_FPBRUS",
        "C_FPTAPE_FP_EXTRA",
        "C_FPTAPE_NOFP2",
        "C_FPTAPE_F",
        "C_FPTAPE_NOF",
    ):
        machine = _machine(name, 4, (3840, 2160))
        machine.reg_write(UC_X86_REG_EAX, SURFACE)
        machine.emu_start(MATCH, STOP, count=10000)
        assert machine.reg_read(UC_X86_REG_EFLAGS) & 1 == 0
    for rejected in (
        "scope",
        "native_target",
        "wrong_dimensions",
        "recycled",
        "empty",
        "phase",
        "null",
    ):
        machine = _machine("C_FPBRUSH", 4, (3840, 2160))
        _write(machine, DEST, 10, 20, 34, 134)
        _write(machine, SOURCE, 0, 0, 96, 456)
        if rejected == "scope":
            _write(machine, STATE, 0)
        elif rejected == "native_target":
            _write(machine, TARGET + 0x38, 1024, 768)
        elif rejected == "wrong_dimensions":
            _write(machine, SURFACE + 0x3C, 455)
        elif rejected == "recycled":
            _write(machine, TABLE + 4, 0)
        elif rejected == "empty":
            _write(machine, SOURCE, 0, 0, 0, 456)
        elif rejected == "phase":
            _write(machine, SOURCE, 1, 0, 93, 456)
            _write(machine, DEST, 10, 20, 33, 134)
        else:
            _write(machine, STACK + 0x30, 0)
        original = _words(machine, STACK + 0x2C, 2)
        machine.emu_start(BASE, STOP, count=10000)
        assert _words(machine, STACK + 0x2C, 2) == original, rejected


def _exercise_damage() -> None:
    for size in ((640, 480), (1024, 768), (1280, 800), (3840, 2160)):
        for dense in (0, 1):
            machine = _machine("C_FPBRUSH", 4, size)
            _write(machine, STATE, dense)
            machine.mem_write(
                BASE,
                build_damage_selector(
                    wrapper_va=BASE,
                    hd_set_active_va=STATE,
                    dimensions_va=DIMENSIONS,
                    full_region_va=OUT_DEST,
                ),
            )
            machine.reg_write(UC_X86_REG_EAX, DEST)
            machine.emu_start(BASE, STOP, count=100)
            full = dense or size[0] > 1024 or size[1] > 768
            assert machine.reg_read(UC_X86_REG_EAX) == (OUT_DEST if full else DEST)
            assert machine.reg_read(UC_X86_REG_ESP) == STACK + 4


def _exercise_dust_input() -> None:
    for size in ((1024, 768), (1280, 800), (3840, 2160)):
        for dense in (0, 1):
            for point in ((0, 0), (2601, 1313), (-9, -17)):
                machine = _machine("C_FPBRUSH", 4, size)
                _write(machine, STATE, dense)
                code = build_dust_input(
                    wrapper_va=BASE,
                    native_va=MATCH,
                    hd_set_active_va=STATE,
                    dimensions_va=DIMENSIONS,
                )
                assert len(code) <= 0xF40 - 0xE60
                machine.mem_write(BASE, code)
                # Native callback records this, both scalar arguments, POINT
                # pointer and coordinates, then returns a distinctive value.
                stub = b"\x89\x0d" + struct.pack("<I", OUT_DEST)
                for offset in (4, 8, 12):
                    stub += b"\x8b\x44\x24" + bytes([offset])
                    stub += b"\xa3" + struct.pack("<I", OUT_DEST + offset)
                stub += b"\x8b\x44\x24\x04\x8b\x10\x8b\x40\x04"
                stub += b"\x89\x15" + struct.pack("<I", OUT_SOURCE)
                stub += b"\xa3" + struct.pack("<I", OUT_SOURCE + 4)
                stub += b"\xb8\x42\x00\x00\x00\xc2\x0c\x00"
                machine.mem_write(MATCH, stub)
                _write(machine, SOURCE, *point)
                _write(machine, STACK, STOP, SOURCE, 23, 47)
                machine.reg_write(UC_X86_REG_ECX, TARGET)
                machine.reg_write(UC_X86_REG_EBP, 0x123456)
                machine.emu_start(BASE, STOP, count=500)
                adjusted = bool(dense and size[1] > 768)
                expected = (
                    tuple(
                        extent // 2 + int((value - extent // 2) * 768 / size[1])
                        for value, extent in zip(point, size, strict=True)
                    )
                    if adjusted
                    else point
                )
                assert _words(machine, OUT_SOURCE, 2) == expected
                owner, pointer, second, third = _words(machine, OUT_DEST)
                assert (owner, second, third) == (TARGET, 23, 47)
                assert (pointer != SOURCE) == adjusted
                assert _words(machine, SOURCE, 2) == point
                assert machine.reg_read(UC_X86_REG_EAX) == 0x42
                assert machine.reg_read(UC_X86_REG_EBP) == 0x123456
                assert machine.reg_read(UC_X86_REG_ESP) == STACK + 16


if __name__ == "__main__":
    _exercise_geometry()
    _exercise_rejections()
    _exercise_damage()
    _exercise_dust_input()
