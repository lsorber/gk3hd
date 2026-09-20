"""Execute exact print ownership, geometry and persistent hit-box contracts."""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

import pytest
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_ESP

from gk3hd.patch.builds import SUPPORTED_BUILDS
from gk3hd.patch.definitions.runtime2d import fingerprint_alpha as fp
from gk3hd.patch.definitions.runtime2d.layout import FINGERPRINT_ALPHA_NORMALIZE_OFFSET
from gk3hd.patch.definitions.runtime2d.ui_frames import build_resource_match, build_surface_match

BASE = 0x800000
STATE = BASE + 0x3000
MANAGER = STATE + 0x100
TABLE = STATE + 0x300
RESOURCE = STATE + 0x400
SURFACE = STATE + 0x500
TARGET = STATE + 0x600
ROOT = STATE + 0x700
DEST = STATE + 0x800
SOURCE = STATE + 0x820
LOG = STATE + 0x840
EFFECT = STATE + 0x860
NODE = STATE + 0x900
STOP = BASE + 0x2000
STACK = BASE + 0xF000
PROFILE = next(iter(SUPPORTED_BUILDS.values()))


@pytest.mark.slow
def test_print_alpha_geometry_and_owner_contracts() -> None:
    subprocess.run(  # noqa: S603 - fixed interpreter and own module.
        [sys.executable, str(Path(__file__).resolve())],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _write(machine: Uc, address: int, *words: int) -> None:
    machine.mem_write(address, struct.pack(f"<{len(words)}I", *(n & 0xFFFFFFFF for n in words)))


def _words(machine: Uc, address: int, count: int = 4) -> tuple[int, ...]:
    return struct.unpack(f"<{count}i", machine.mem_read(address, count * 4))


def _machine(name: bytes, size: tuple[int, int], density: int, display: tuple[int, int]) -> Uc:
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(0x400000, 0x400000)
    machine.mem_map(BASE, 0x10000)
    constructor = fp.build_constructor(
        profile=PROFILE, base=BASE, root_va=STATE, hd_set_active_va=STATE + 4
    )
    assert len(constructor) <= fp.CALLBACK - fp.CONSTRUCTOR
    machine.mem_write(BASE + fp.CONSTRUCTOR, constructor)
    for scale, surface, resource in (
        (1, fp.NATIVE_SURFACE, fp.NATIVE_RESOURCE),
        (4, fp.DENSE_SURFACE, fp.DENSE_RESOURCE),
    ):
        machine.mem_write(
            BASE + surface,
            build_surface_match(
                wrapper_va=BASE + surface,
                resource_match_va=BASE + resource,
                manager_va=PROFILE.address("bitmap.manager"),
                images=fp.PRINT_IMAGES,
                density=scale,
            ),
        )
        machine.mem_write(
            BASE + resource,
            build_resource_match(wrapper_va=BASE + resource, images=fp.PRINT_IMAGES, density=scale),
        )
    machine.mem_write(BASE + FINGERPRINT_ALPHA_NORMALIZE_OFFSET, fp.build_normalize(base=BASE))
    _write(machine, STATE, ROOT, 1)
    _write(machine, ROOT, PROFILE.address("fingerprint.vtable"))
    _write(machine, PROFILE.address("display.dimensions"), *display)
    _write(machine, PROFILE.address("bitmap.manager"), MANAGER)
    _write(machine, MANAGER + 0x120, TABLE, 1)
    _write(machine, TABLE, RESOURCE)
    machine.mem_write(RESOURCE + 8, name + b"\0")
    _write(machine, RESOURCE + 0x30, SURFACE)
    _write(machine, SURFACE + 0x38, *(value * density for value in size))
    _write(machine, TARGET + 0x38, *display)
    _write(machine, EFFECT, 123)
    stub = b""
    for index, offset in enumerate((12, 16, 20)):
        stub += b"\x8b\x44\x24" + bytes([offset]) + b"\xa3" + struct.pack("<I", LOG + index * 4)
    stub += b"\x89\x0d" + struct.pack("<I", LOG + 12) + b"\x8b\xc1\xc2\x14\x00"
    machine.mem_write(PROFILE.address("bitmap.effect_constructor"), stub)
    return machine


def _exercise() -> None:
    for name, width, height in fp.PRINT_IMAGES:
        for density in (1, 4):
            for display in ((1024, 768), (1280, 800), (3840, 2160)):
                machine = _machine(name.upper(), (width, height), density, display)
                x, y = display[0] // 2 + 230, display[1] // 2 + 61
                original_dest = (x, y, x + width * density, y + height * density)
                original_source = (0, 0, width * density, height * density)
                _write(machine, DEST, *original_dest)
                _write(machine, SOURCE, *original_source)
                _write(machine, STACK, STOP, TARGET, SURFACE, DEST, SOURCE, 17)
                machine.reg_write(UC_X86_REG_ECX, EFFECT)
                machine.reg_write(UC_X86_REG_ESP, STACK)
                machine.emu_start(BASE + fp.CONSTRUCTOR, STOP, count=10000)
                dx = display[0] // 2 + int(230 * display[1] / 768)
                dy = display[1] // 2 + int(61 * display[1] / 768)
                dest, source, options, owner = _words(machine, LOG)
                assert _words(machine, dest) == (
                    dx,
                    dy,
                    dx + width * display[1] // 768,
                    dy + height * display[1] // 768,
                )
                assert _words(machine, source) == original_source
                assert (options, owner) == (17, EFFECT)
                assert _words(machine, EFFECT, 1) == (BASE + fp.VTABLE,)
                assert _words(machine, DEST) == original_dest
                assert machine.reg_read(UC_X86_REG_ESP) == STACK + 24
                # Normalize only the dense node's bounds, preserving its anchor.
                _write(machine, NODE + 0x1C, *original_dest)
                _write(machine, STACK, STOP)
                machine.reg_write(UC_X86_REG_ESP, STACK)
                machine.reg_write(UC_X86_REG_EAX, RESOURCE)
                machine.reg_write(UC_X86_REG_ECX, NODE)
                machine.emu_start(BASE + FINGERPRINT_ALPHA_NORMALIZE_OFFSET, STOP, count=10000)
                assert _words(machine, NODE + 0x1C) == (x, y, x + width, y + height)
    for rejection in ("name", "dimensions", "root", "target", "no_pack"):
        machine = _machine(b"fp_lhomir_p1", (25, 44), 4, (3840, 2160))
        if rejection == "name":
            machine.mem_write(RESOURCE + 8, b"fp_lhomir_p1_extra\0")
        elif rejection == "dimensions":
            _write(machine, SURFACE + 0x38, 101, 176)
        elif rejection == "root":
            _write(machine, ROOT, 0)
        elif rejection == "target":
            _write(machine, TARGET + 0x38, 640, 480)
        else:
            _write(machine, STATE + 4, 0)
        _write(machine, STACK, STOP, TARGET, SURFACE, DEST, SOURCE, 17)
        machine.reg_write(UC_X86_REG_ECX, EFFECT)
        machine.reg_write(UC_X86_REG_ESP, STACK)
        machine.emu_start(BASE + fp.CONSTRUCTOR, STOP, count=10000)
        assert _words(machine, LOG) == (DEST, SOURCE, 17, EFFECT), rejection
        assert _words(machine, EFFECT, 1) == (123,), rejection


if __name__ == "__main__":
    _exercise()
