"""Execute navigation resource geometry and owner-scoped dense sampling."""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

import pytest
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ESI, UC_X86_REG_ESP

from gk3hd.patch.definitions.runtime2d.inventory_navigation import (
    IMAGES,
    SURFACES_SIZE,
    build_source,
)
from gk3hd.patch.definitions.runtime2d.sidney_images import build_image_dimensions

BASE = 0x800000
DATA = 0x900000
SURFACE = DATA + 0x1000
STATE = DATA + 0x2000
LAYER = DATA + 0x3000
RECT = DATA + 0x4000
STACK = DATA + 0xF000
SOURCE = BASE + 0x4000
CURRENT_LAYER = BASE + 0x6000
STOP = BASE + 0x7000


@pytest.mark.slow
def test_navigation_catalog_geometry_and_sampling() -> None:
    subprocess.run(  # noqa: S603 - fixed interpreter and this test module.
        [sys.executable, str(Path(__file__).resolve())],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _write(machine: Uc, address: int, *values: int) -> None:
    machine.mem_write(address, struct.pack(f"<{len(values)}I", *values))


def _sample(machine: Uc, *, owner: int, dense: bool) -> None:
    _write(machine, LAYER, owner)
    _write(machine, RECT, 1, 2, 15, 18)
    _write(machine, STACK, STOP, 0, SURFACE, 0, RECT)
    machine.reg_write(UC_X86_REG_ESP, STACK)
    machine.emu_start(SOURCE, STOP, count=3000)
    pointer = struct.unpack("<I", machine.mem_read(STACK + 16, 4))[0]
    assert pointer == (STATE + SURFACES_SIZE if dense else RECT)
    assert struct.unpack("<4I", machine.mem_read(pointer, 16)) == (
        (4, 8, 60, 72) if dense else (1, 2, 15, 18)
    )
    assert struct.unpack("<4I", machine.mem_read(RECT, 16)) == (1, 2, 15, 18)
    assert machine.reg_read(UC_X86_REG_ESP) == STACK + 4


def _exercise() -> None:
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(BASE, 0x10000)
    machine.mem_map(DATA, 0x10000)
    machine.mem_write(
        BASE, build_image_dimensions(wrapper_va=BASE, surfaces_va=STATE, images=IMAGES)
    )
    machine.mem_write(
        SOURCE,
        build_source(
            wrapper_va=SOURCE,
            state_va=STATE,
            current_layer_va=CURRENT_LAYER,
            inventory_vtable_va=1,
            loadgame_vtable_va=2,
            savegame_vtable_va=3,
        ),
    )
    machine.mem_write(CURRENT_LAYER, b"\xb8" + struct.pack("<I", LAYER) + b"\xc3")
    for name, width, height in IMAGES:
        for density in (1, 4):
            machine.mem_write(STATE, bytes(SURFACES_SIZE + 24))
            machine.mem_write(DATA + 8, name.upper() + bytes(32 - len(name)))
            _write(machine, SURFACE + 0x38, width * density, height * density)
            _write(machine, STACK, STOP)
            machine.reg_write(UC_X86_REG_ESP, STACK)
            machine.reg_write(UC_X86_REG_ESI, DATA)
            machine.reg_write(UC_X86_REG_EAX, SURFACE)
            machine.emu_start(BASE, STOP, count=3000)
            logical = STATE + SURFACES_SIZE + 16
            assert machine.reg_read(UC_X86_REG_EAX) == (logical if density == 4 else SURFACE)
            if density == 4:
                assert struct.unpack("<2I", machine.mem_read(logical, 8)) == (width, height)
            assert struct.unpack("<2I", machine.mem_read(SURFACE + 0x38, 8)) == (
                width * density,
                height * density,
            )
            for owner in (1, 2, 3, 4):
                matches_owner = owner == 1 if name.startswith(b"inv_") else owner in (2, 3)
                _sample(machine, owner=owner, dense=density == 4 and matches_owner)


if __name__ == "__main__":
    _exercise()
