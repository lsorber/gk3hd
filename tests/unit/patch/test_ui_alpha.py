"""Execute paired-image ownership, clipping, density and mask safety contracts."""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

import pytest
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.runtime2d import ui_alpha as ui
from gk3hd.patch.definitions.runtime2d.ui_frames import build_resource_match, build_surface_match

BASE, STOP, STACK = 0x800000, 0x802000, 0x80F000
MANAGER, TABLE, RESOURCE, SURFACE, TARGET = range(0x803000, 0x803500, 0x100)
DEST, SOURCE, OPTIONS, LOG, EFFECT = range(0x803500, 0x803A00, 0x100)
ALPHA_TABLE, ALPHA, ALPHA_VTABLE, LOADER = range(0x804000, 0x804400, 0x100)
PROFILE = GOG_BUILD
FALLBACK = 0x805000


def _write(cpu: Uc, address: int, *values: int) -> None:
    cpu.mem_write(address, struct.pack(f"<{len(values)}I", *(n & 0xFFFFFFFF for n in values)))


def _read(cpu: Uc, address: int, count: int = 4) -> tuple[int, ...]:
    return struct.unpack(f"<{count}i", cpu.mem_read(address, count * 4))


def _machine(density: int, display: tuple[int, int], variant: str) -> Uc:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x400000)
    cpu.mem_map(BASE, 0x10000)
    code = ui.build_constructor(profile=PROFILE, base=BASE, fallback_va=FALLBACK)
    assert len(code) <= ui.CALLBACK - ui.CONSTRUCTOR
    cpu.mem_write(BASE + ui.CONSTRUCTOR, code)
    for scale, surface, resource in (
        (1, ui.NATIVE_SURFACE, ui.NATIVE_RESOURCE),
        (4, ui.DENSE_SURFACE, ui.DENSE_RESOURCE),
    ):
        cpu.mem_write(
            BASE + surface,
            build_surface_match(
                wrapper_va=BASE + surface,
                resource_match_va=BASE + resource,
                manager_va=PROFILE.address("bitmap.manager"),
                images=ui.OPACITY_IMAGE_PAIRS,
                density=scale,
            ),
        )
        cpu.mem_write(
            BASE + resource,
            build_resource_match(
                wrapper_va=BASE + resource,
                images=ui.OPACITY_IMAGE_PAIRS,
                density=scale,
            ),
        )
    _write(cpu, PROFILE.address("display.dimensions"), *display)
    _write(cpu, PROFILE.address("bitmap.manager"), MANAGER)
    _write(cpu, MANAGER + 0x120, TABLE, 1)
    _write(cpu, TABLE, RESOURCE)
    cpu.mem_write(RESOURCE + 8, b"CAIN\0")
    _write(cpu, RESOURCE + 0x30, SURFACE)
    _write(cpu, SURFACE + 0x38, 148 * density, 160 * density)
    _write(cpu, TARGET + 0x38, *display)
    _write(cpu, OPTIONS, 1, 0x3F800000, 0x3F800000, 0x610000, 0)
    _write(cpu, MANAGER + 0x150, ALPHA_TABLE, 1)
    _write(cpu, ALPHA_TABLE, ALPHA)
    _write(cpu, ALPHA, ALPHA_VTABLE, 0x10061)
    cpu.mem_write(ALPHA + 8, b"CAIN_ALPHA\0")
    _write(cpu, ALPHA + 0x34, 148 * density, 160 * density, 148 * density)
    _write(cpu, EFFECT, 123)
    stub = b""
    for index, offset in enumerate((12, 16, 20)):
        stub += b"\x8b\x44\x24" + bytes([offset]) + b"\xa3" + struct.pack("<I", LOG + index * 4)
    stub += b"\x89\x0d" + struct.pack("<I", LOG + 12) + b"\x8b\xc1\xc2\x14\x00"
    cpu.mem_write(PROFILE.address("bitmap.effect_constructor"), stub)
    cpu.mem_write(FALLBACK, stub)
    _configure_variant(cpu, density, variant)
    return cpu


def _configure_variant(cpu: Uc, density: int, variant: str) -> None:
    name_changes = {
        "lowercase": (ALPHA + 8, b"cain_alpha\0"),
        "name": (RESOURCE + 8, b"CAIN_EXTRA\0"),
        "mask_name": (ALPHA + 8, b"CAIN_ALPHAX\0"),
        "mask_underscore": (ALPHA + 12, b"\x7f"),
    }
    if variant in name_changes:
        address, value = name_changes[variant]
        cpu.mem_write(address, value)
    if variant == "lazy":
        _write(cpu, ALPHA + 4, 0x61)
        _write(cpu, ALPHA_VTABLE + 4, LOADER)
        cpu.mem_write(LOADER, b"\x66\xc7\x41\x06\x01\x00\xc3")
    elif variant == "mask_size":
        _write(cpu, ALPHA + 0x34, 148 * density + 1)
    elif variant == "stale":
        _write(cpu, ALPHA + 4, 0x10062)
    elif variant == "missing":
        _write(cpu, OPTIONS + 12, 0)
    elif variant == "index":
        _write(cpu, OPTIONS + 12, 0x610001)
    elif variant == "target":
        _write(cpu, TARGET + 0x38, 640, 480)
    elif variant == "effect":
        _write(cpu, OPTIONS, 2)


def _exercise() -> None:
    accepted = {"normal", "lowercase", "lazy", "clipped"}
    variants = (
        *sorted(accepted),
        "name",
        "mask_name",
        "mask_underscore",
        "mask_size",
        "stale",
        "missing",
        "index",
        "target",
        "effect",
        "source",
    )
    for density in (1, 4):
        for display in ((1024, 768), (1280, 800), (3840, 2160)):
            for variant in variants:
                cpu = _machine(density, display, variant)
                clip = (3, 7, 142, 158) if variant == "clipped" else (0, 0, 148, 160)
                dest = tuple(display[i % 2] // 2 - (74, 80)[i % 2] + n for i, n in enumerate(clip))
                _write(cpu, DEST, *dest)
                _write(cpu, SOURCE, *clip)
                if variant == "source":
                    _write(cpu, SOURCE, -1)
                _write(cpu, STACK, STOP, TARGET, SURFACE, DEST, SOURCE, OPTIONS)
                cpu.reg_write(UC_X86_REG_ECX, EFFECT)
                cpu.reg_write(UC_X86_REG_ESP, STACK)
                cpu.emu_start(BASE + ui.CONSTRUCTOR, STOP, count=10000)
                out_dest, out_source, options, owner = _read(cpu, LOG)
                assert (options, owner) == (OPTIONS, EFFECT), variant
                assert cpu.reg_read(UC_X86_REG_ESP) == STACK + 24, variant
                assert cpu.reg_read(UC_X86_REG_EAX) == EFFECT, variant
                assert _read(cpu, DEST) == dest, variant
                if variant not in accepted:
                    assert (out_dest, out_source) == (DEST, SOURCE), variant
                    assert _read(cpu, EFFECT, 1) == (123,), variant
                    continue
                expected = tuple(
                    display[i % 2] // 2 + int((n - display[i % 2] // 2) * display[1] / 768)
                    for i, n in enumerate(dest)
                )
                assert _read(cpu, out_dest) == expected, (variant, display)
                assert _read(cpu, out_source) == tuple(n * density for n in clip), variant
                assert _read(cpu, SOURCE) == clip, variant
                assert _read(cpu, EFFECT, 1) == (BASE + ui.VTABLE,), variant


@pytest.mark.slow
def test_paired_image_alpha_contracts() -> None:
    subprocess.run(  # noqa: S603 - fixed interpreter and own module.
        [sys.executable, str(Path(__file__).resolve())],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


if __name__ == "__main__":
    _exercise()
