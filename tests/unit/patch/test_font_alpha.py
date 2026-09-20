"""Execute faded glyph geometry and sampling against the opaque-path contract."""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.runtime2d.font_sampling import (
    build_font_selector,
    build_font_source_copy,
)
from gk3hd.patch.definitions.runtime2d.inventory import InventoryFeatureCompiler
from gk3hd.patch.definitions.runtime2d.inventory_alpha import (
    build_effect_constructor_wrapper,
    build_scaled_font_alpha_callback,
)
from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.sidney_alpha import build_alpha_wrapper

_BASE, _STACK, _STOP = 0x800000, 0x900000, 0x810000
_RECT, _SOURCE, _EFFECT, _POINT, _TILE = range(0x820000, 0x820500, 0x100)
_STATE = {
    name: 0x801000 + index * 0x20
    for index, name in enumerate(
        (
            "item_draw_active_va",
            "output_rect_va",
            "source_rect_va",
            "dest_width_va",
            "dest_height_va",
            "transform_count_va",
            "item_alpha_handle_va",
            "item_dense_source_va",
            "denominator_va",
            "numerator_va",
            "x_offset_va",
            "y_offset_va",
            "scaled_alpha_vtable_va",
            "font_scaled_alpha_vtable_va",
            "selected_vtable_va",
            "hud_font_active_va",
            "hud_font_point_va",
            "hud_font_alpha_transform_count_va",
            "hd_font_active_va",
            "hd_font_source_transform_count_va",
            "physical_height_va",
        )
    )
}


def _compiler() -> InventoryFeatureCompiler:
    return InventoryFeatureCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=0x790004, height_va=0x790008),
    )


def _put(cpu: Uc, address: int, *values: int) -> None:
    cpu.mem_write(address, struct.pack("<" + "I" * len(values), *values))


def _get(cpu: Uc, address: int, count: int) -> tuple[int, ...]:
    return struct.unpack("<" + "I" * count, cpu.mem_read(address, count * 4))


def _install_selector(cpu: Uc) -> int:
    selector, copier, scope, entry = 0x850000, 0x851000, 0x852000, 0x853000
    manager_ptr, manager, table, resource = 0x854000, 0x855000, 0x856000, 0x857000
    cpu.mem_write(
        selector,
        build_font_selector(
            base_va=selector, native_va=copier, scope_va=scope, manager_va=manager_ptr
        ),
    )
    cpu.mem_write(copier, build_font_source_copy(base_va=copier))
    _put(cpu, scope, entry)
    _put(cpu, entry, 7, 183, 16, 94)
    _put(cpu, entry + 112, 732, 4, 64, 1)
    _put(cpu, manager_ptr, manager)
    _put(cpu, manager + 0x120, table, 16)
    _put(cpu, table + 28, resource)
    _put(cpu, resource + 0x30, 0x840000)
    _put(cpu, 0x840038, 1464, 256)
    return selector


def _geometry(height: int, mode: int, density: int, *, bank: bool = False) -> None:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x600000)
    payload = build_effect_constructor_wrapper(
        _compiler(),
        wrapper_va=_BASE,
        font_bank_select_va=_install_selector(cpu) if bank else None,
        **_STATE,
    )
    cpu.mem_write(_BASE, payload)
    native = GOG_BUILD.address("bitmap.effect_constructor")
    cpu.mem_write(native, b"\xc2\x14\x00")
    point, extent = (5, 11), (7, 12)
    physical = tuple(value * height // 768 for value in point)
    rect = (*physical, physical[0] + extent[0], physical[1] + extent[1])
    source = (13, 19, 20, 31)
    _put(cpu, _RECT, *rect)
    _put(cpu, _SOURCE, *source)
    _put(cpu, _STATE["physical_height_va"], height)
    _put(cpu, _STATE["hud_font_active_va"], mode)
    _put(cpu, _STATE["hud_font_point_va"], *(point if mode == 1 else physical))
    _put(cpu, _STATE["hd_font_active_va"], int(density == 4))
    _put(cpu, _STACK, _STOP, 0x830000, 0x840000, _RECT, _SOURCE, 0)
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.reg_write(UC_X86_REG_ECX, _EFFECT)
    calls = []

    def inspect(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address != native:
            return
        args = _get(machine, machine.reg_read(UC_X86_REG_ESP) + 4, 5)
        expected_far = tuple(
            (point[axis] + extent[axis]) * height // 768
            if mode == 1
            else physical[axis] + extent[axis] * height // 768
            for axis in range(2)
        )
        assert _get(machine, args[2], 4) == (*physical, *expected_far)
        enlarged = any(expected_far[i] - physical[i] > extent[i] for i in range(2))
        shift = 732 if bank and enlarged else 0
        assert _get(machine, args[3], 4) == tuple(
            value * density + (shift if i % 2 == 0 else 0) for i, value in enumerate(source)
        )
        assert args[:2] == (0x830000, 0x840000)
        assert args[4] == 0
        assert machine.reg_read(UC_X86_REG_ECX) == _EFFECT
        calls.append(address)
        machine.reg_write(UC_X86_REG_EAX, _EFFECT)

    cpu.hook_add(UC_HOOK_CODE, inspect)
    cpu.emu_start(_BASE, _STOP, count=1000)
    assert calls == [native]
    assert _get(cpu, _EFFECT, 1) == (_STATE["font_scaled_alpha_vtable_va"],)
    assert _get(cpu, _RECT, 4) == rect
    assert _get(cpu, _SOURCE, 4) == source
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 24


def _samples(density: int, extent: int, origin: int) -> None:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x600000)
    cpu.mem_write(
        _BASE,
        build_scaled_font_alpha_callback(
            _compiler(),
            callback_va=_BASE,
            source_rect_va=_SOURCE,
            dest_width_va=0x801000,
            dest_height_va=0x801004,
            trace_va=0x801100,
        ),
    )
    native = GOG_BUILD.address("bitmap.effect_callback")
    cpu.mem_write(native, b"\xc2\x10\x00")
    _put(cpu, _SOURCE, 20, 40, 20 + 12 * density, 40 + 12 * density)
    _put(cpu, 0x801000, extent, extent)
    _put(cpu, _POINT, origin, origin)
    _put(cpu, _TILE, 2, 2)
    _put(cpu, _STACK, _STOP, 0x830000, 1024, _TILE, _POINT)
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.reg_write(UC_X86_REG_ECX, _EFFECT)
    samples = []

    def inspect(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address == native:
            args = _get(machine, machine.reg_read(UC_X86_REG_ESP) + 4, 4)
            assert _get(machine, args[2], 2) == (1, 1)
            samples.append(_get(machine, args[3], 2))

    cpu.hook_add(UC_HOOK_CODE, inspect)
    cpu.emu_start(_BASE, _STOP, count=1000)
    step = (12 * density << 16) // extent
    assert samples == [
        tuple(((origin + offset) * step + step // 2) >> 16 for offset in (x, y))
        for y in range(2)
        for x in range(2)
    ]
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 20


def _sidney_geometry(width: int, height: int) -> None:
    """Compose both real adapters with a stale HUD point and nonzero UI origin."""
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x600000)
    entry, depth, display, classifier = 0x803000, 0x806000, 0x806010, 0x807000
    cpu.mem_write(_BASE, build_effect_constructor_wrapper(_compiler(), wrapper_va=_BASE, **_STATE))
    cpu.mem_write(
        entry,
        build_alpha_wrapper(
            wrapper_va=entry,
            target_va=_BASE,
            active_depth_va=depth,
            hud_font_active_va=_STATE["hud_font_active_va"],
            physical_width_va=display,
            cursor_classifier_va=classifier,
        ),
    )
    cpu.mem_write(classifier, b"\x31\xc0\xc3")
    native = GOG_BUILD.address("bitmap.effect_constructor")
    cpu.mem_write(native, b"\xc2\x14\x00")
    rect, source = (250, 174, 261, 191), (63, 1, 74, 18)
    _put(cpu, _RECT, *rect)
    _put(cpu, _SOURCE, *source)
    _put(cpu, depth, 1)
    _put(cpu, display, width, height)
    _put(cpu, 0x830038, width, height)
    _put(cpu, _STATE["physical_height_va"], height)
    _put(cpu, _STATE["hud_font_point_va"], 0, 0)
    _put(cpu, _STACK, _STOP, 0x830000, 0x840000, _RECT, _SOURCE, 0)
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.reg_write(UC_X86_REG_ECX, _EFFECT)
    calls = []

    def inspect(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address != native:
            return
        args = _get(machine, machine.reg_read(UC_X86_REG_ESP) + 4, 5)
        x = rect[0] * height // 768 + (width - 1024 * height // 768) // 2
        y = rect[1] * height // 768
        assert _get(machine, args[2], 4) == (x, y, x + 11 * height // 768, y + 17 * height // 768)
        assert _get(machine, args[3], 4) == source
        assert _get(machine, _STATE["hud_font_active_va"], 1) == (2,)
        assert args[:2] == (0x830000, 0x840000)
        calls.append(address)
        machine.reg_write(UC_X86_REG_EAX, _EFFECT)

    cpu.hook_add(UC_HOOK_CODE, inspect)
    cpu.emu_start(entry, _STOP, count=1500)
    assert calls == [native]
    assert _get(cpu, _RECT, 4) == rect
    assert _get(cpu, _SOURCE, 4) == source
    assert _get(cpu, _STATE["hud_font_active_va"], 1) == (0,)
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 24


@pytest.mark.slow
def test_faded_fonts_match_opaque_geometry_and_sampling() -> None:
    subprocess.run(  # noqa: S603 - fixed interpreter and own test module.
        [sys.executable, str(Path(__file__).resolve())],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )


if __name__ == "__main__":
    for _width, _height in ((1280, 800), (2560, 1536), (3840, 2160)):
        _sidney_geometry(_width, _height)
    for _density in (1, 4):
        for _height in (768, 800, 1536, 2160):
            for _mode in (1, 2):
                _geometry(_height, _mode, _density)
                if _density == 4:
                    _geometry(_height, _mode, _density, bank=True)
        for _extent in (12, 13, 24, 33, 34):
            # The midpoint of odd extents exercises exact-rational ties that
            # differ from the opaque renderer's truncated 16.16 increment.
            for _origin in (0, 3, _extent // 2, _extent - 2):
                _samples(_density, _extent, _origin)
