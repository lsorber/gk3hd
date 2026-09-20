"""Execute restored and newly constructed TimeBlock draw contracts."""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameABI
from gk3hd.patch.definitions.runtime2d.layout import (
    TIMEBLOCK_SEGMENT,
    RuntimeSegmentAddress,
    RuntimeSymbols,
)
from gk3hd.patch.definitions.runtime2d.resource_timeblock import build_root_draw
from gk3hd.patch.definitions.runtime2d.resources import ResourceDispatchCompiler

BASE = 0x800000
ROOT = BASE + 0x1000
RESOURCE = BASE + 0x2000
SURFACE = BASE + 0x3000
STATE = BASE + 0x4000
SCREEN = BASE + 0x5000
OVERLAY = BASE + 0x6000
STOP = BASE + 0x7000
STACK = BASE + 0xF000


@pytest.mark.parametrize("width", [640, 2560])
@pytest.mark.parametrize("height", [480, 481])
@pytest.mark.slow
def test_timeblock_restores_model_extents_and_preserves_draw_arguments(
    width: int, height: int
) -> None:
    subprocess.run(  # noqa: S603 - own fixed test module, integer arguments.
        [sys.executable, str(Path(__file__).resolve()), str(width), str(height)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _write(cpu: Uc, address: int, *values: int) -> None:
    cpu.mem_write(address, struct.pack(f"<{len(values)}I", *(v & 0xFFFFFFFF for v in values)))


def _read(cpu: Uc, address: int, count: int) -> tuple[int, ...]:
    return struct.unpack(f"<{count}I", cpu.mem_read(address, 4 * count))


def _payload() -> tuple[ResourceDispatchCompiler, bytes]:
    compiler = ResourceDispatchCompiler(
        symbols=RuntimeSymbols(segments=(RuntimeSegmentAddress(TIMEBLOCK_SEGMENT, 0, 0, BASE),)),
        profile=GOG_BUILD,
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=STATE + 100,
            room_presentation_active_va=STATE + 104,
            pre_flip_presenter_slot_va=STATE + 108,
            post_flip_presenter_slot_va=STATE + 112,
        ),
    )
    payload = build_root_draw(
        compiler,
        wrapper_va=BASE,
        overlay_draw_va=OVERLAY,
        clear_budget_va=STATE + 4,
        clear_count_va=STATE + 8,
        bltfx_va=STATE + 12,
        clear_flip_count_va=STATE + 16,
        successful_flip_count_va=STATE + 20,
        layer_va=STATE + 24,
        draw_scope_active_va=STATE + 28,
        raw_width_va=STATE + 32,
        raw_height_va=STATE + 36,
        control_seen_va=STATE + 40,
        control_count_va=STATE + 44,
    )
    assert len(payload) <= 0x200
    return compiler, payload


def _initialize_model(cpu: Uc, width: int, height: int) -> tuple[int, ...]:
    model_height = height * (width // 640)
    left, top = (1024 - width) // 2, 384 - model_height // 2
    original = (left, top, left + width, top + model_height)
    _write(cpu, ROOT + 0x1C, *original, 999)
    cpu.mem_write(ROOT + 0x18, b"\x01")
    cpu.mem_write(ROOT + 0x3C0, b"\x01")
    _write(cpu, RESOURCE + 0x30, SURFACE)
    _write(cpu, SURFACE + 0x38, 2560, height * 4)
    return original


def _exercise(width: int, height: int) -> None:
    compiler, payload = _payload()
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x400000)
    cpu.mem_map(BASE, 0x10000)
    cpu.mem_write(BASE, payload)
    current = GOG_BUILD.address("ui.current_layer")
    resolve = GOG_BUILD.address("bitmap.resolve_resource")
    center = GOG_BUILD.address("ui.center_drawable")
    cpu.mem_write(current, b"\xc3")
    cpu.mem_write(resolve, b"\xc2\x04\x00")
    cpu.mem_write(center, b"\xc2\x04\x00")
    cpu.mem_write(OVERLAY, b"\xc2\x08\x00")
    original = _initialize_model(cpu, width, height)
    _write(cpu, compiler._screen_rect_ptr_va, SCREEN)
    _write(cpu, SCREEN, 0, 0, 1024, 768)
    traversals: list[tuple[int, ...]] = []

    def native(machine: Uc, address: int, _size: int, _data: object) -> None:
        stack = machine.reg_read(UC_X86_REG_ESP)
        if address == current:
            machine.reg_write(UC_X86_REG_EAX, ROOT)
        elif address == resolve:
            handle = _read(machine, stack + 4, 1)[0]
            machine.reg_write(UC_X86_REG_EAX, RESOURCE if handle == 999 else 0)
        elif address == center:
            assert machine.reg_read(UC_X86_REG_ECX) == ROOT
            assert bytes(machine.mem_read(ROOT + 0x18, 1)) == b"\0"
            assert _read(machine, stack + 4, 1) == (SCREEN,)
            x1, y1, x2, y2 = _read(machine, ROOT + 0x1C, 4)
            w, h = (x2 - x1) & 0xFFFFFFFF, (y2 - y1) & 0xFFFFFFFF
            x, y = 512 - w // 2, 384 - h // 2
            _write(machine, ROOT + 0x1C, x, y, x + w, y + h)
        elif address == OVERLAY:
            assert _read(machine, stack + 4, 2) == (123, 456)
            assert _read(machine, STATE + 28, 1) == (1,)
            assert bytes(machine.mem_read(ROOT + 0x18, 1)) == b"\x01"
            traversals.append(_read(machine, ROOT + 0x1C, 4))

    cpu.hook_add(UC_HOOK_CODE, native)
    for _ in range(2):
        _write(cpu, STACK, STOP, 123, 456)
        cpu.reg_write(UC_X86_REG_ESP, STACK)
        cpu.reg_write(UC_X86_REG_ECX, ROOT)
        cpu.emu_start(BASE, STOP, count=2000)
        assert cpu.reg_read(UC_X86_REG_EIP) == STOP
        assert cpu.reg_read(UC_X86_REG_ESP) == STACK + 12
        assert _read(cpu, ROOT + 0x1C, 4) == tuple(v & 0xFFFFFFFF for v in original)
        assert _read(cpu, STATE + 28, 1) == (0,)
    y = 384 - height // 2
    assert traversals == [(192, y, 832, y + height)] * 2


if __name__ == "__main__":
    _exercise(int(sys.argv[1]), int(sys.argv[2]))
