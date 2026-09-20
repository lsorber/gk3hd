"""Execute input routing with retained SIDNEY beneath an inventory overlay."""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.guard_stale_mouse_move_targets import MouseMoveDispatchABI
from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols
from gk3hd.patch.definitions.runtime2d.resource_driving_map import build_source_grid_rect
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.sidney_input import build_input_dispatch_wrapper
from gk3hd.patch.definitions.runtime2d.sidney_presentation import SidneyPresentationCompiler

BASE = 0x800000
STATE = BASE + 0x2000
POINT = BASE + 0x3000
ROOT = BASE + 0x4000
CALLBACK = BASE + 0x6000
STOP = BASE + 0x7000
STACK = BASE + 0xF000


@pytest.mark.slow
def test_current_layer_owns_input_not_retained_sidney() -> None:
    subprocess.run(  # noqa: S603 - own fixed test module, no external arguments.
        [sys.executable, str(Path(__file__).resolve())],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _write(cpu: Uc, address: int, *values: int) -> None:
    cpu.mem_write(address, struct.pack(f"<{len(values)}I", *values))


def _exercise() -> None:
    compiler = SidneyPresentationCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=0x790004, height_va=0x790008),
        mouse_move_abi=MouseMoveDispatchABI(ui_dispatch_adapter_slot_va=0x792000),
    )
    payload = build_input_dispatch_wrapper(
        compiler,
        wrapper_va=BASE,
        root_ptr_va=STATE,
        input_transform_count_va=STATE + 4,
        input_source_x_va=STATE + 8,
        input_logical_x_va=STATE + 12,
        driving_map_active_va=STATE + 16,
        driving_map_input_depth_va=STATE + 20,
        tbt_layer_va=STATE + 24,
        tbt_target_rect_va=STATE + 28,
        tbt_input_wrapper_va=STOP,
        system_active_va=STATE + 44,
        system_root_ptr_va=STATE + 48,
        system_transform_mode_va=STATE + 52,
        system_input_wrapper_va=STOP,
        toolbar_input_wrapper_va=STOP,
        reference_anchor_input_wrapper_va=STOP,
        reference_canvas_input_wrapper_va=STOP,
        binocs_input_wrapper_va=STOP,
        system_action_presented_root_va=STATE + 96,
        system_native_input_vtables=(),
    )
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x400000)
    cpu.mem_map(BASE, 0x10000)
    cpu.mem_write(BASE, payload)
    current = GOG_BUILD.address("ui.current_layer")
    cpu.mem_write(current, b"\xc3")
    cpu.mem_write(CALLBACK, b"\xc2\x04\x00")
    seen: list[tuple[int, int]] = []
    layer = ROOT

    def native(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address == current:
            machine.reg_write(UC_X86_REG_EAX, layer)
            machine.reg_write(UC_X86_REG_ECX, 0xBAD)
        elif address == CALLBACK:
            assert machine.reg_read(UC_X86_REG_ECX) == 123
            stack = machine.reg_read(UC_X86_REG_ESP)
            assert struct.unpack("<I", machine.mem_read(stack + 4, 4)) == (POINT,)
            seen.append(struct.unpack("<2I", machine.mem_read(POINT, 8)))
            # Nested dispatch may overwrite diagnostic state. Restoration
            # must use this invocation's saved physical coordinates instead.
            _write(machine, STATE + 8, 9999, 8888)
            machine.reg_write(UC_X86_REG_EAX, 789)

    cpu.hook_add(UC_HOOK_CODE, native)
    for width, height in ((1024, 768), (1280, 800), (3840, 2160)):
        for layer in (ROOT, ROOT + 0x100):
            for icon_size in (0, 32, 64):
                action = bool(icon_size)
                cpu.mem_write(STATE, bytes(128))
                _write(cpu, STATE, ROOT)
                # The overlay publishes physical button rectangles; only
                # dense icons need the local opacity lookup adjustment.
                _write(cpu, STATE + 96, ROOT + 0x100 if action else 0)
                _write(cpu, STATE + 64, icon_size)
                _write(cpu, STATE + 80, 320)
                _write(cpu, ROOT + 0x100 + 0x1C, 720, 320, 848, 384)
                _write(cpu, compiler._physical_width_global_va, width, height)
                _write(cpu, POINT, 786, 365)
                _write(cpu, STACK, STOP, POINT)
                cpu.reg_write(UC_X86_REG_ESP, STACK)
                cpu.reg_write(UC_X86_REG_EAX, CALLBACK)
                cpu.reg_write(UC_X86_REG_ECX, 123)
                cpu.emu_start(BASE, STOP, count=1000)
                assert cpu.reg_read(UC_X86_REG_EIP) == STOP
                assert cpu.reg_read(UC_X86_REG_ESP) == STACK + 8
                assert cpu.reg_read(UC_X86_REG_EAX) == 789
                assert struct.unpack("<2I", cpu.mem_read(POINT, 8)) == (786, 365), (
                    width,
                    height,
                    layer,
                    action,
                    seen[-1],
                    struct.unpack("<2I", cpu.mem_read(POINT, 8)),
                )
                if layer == ROOT and (width > 1024 or height > 768):
                    offset = (width - height * 4 // 3) // 2
                    assert seen[-1] == (int((786 - offset) * 768 / height), 365 * 768 // height)
                elif icon_size == 64 and (width > 1024 or height > 768):
                    assert seen[-1] == (785, 342)
                else:
                    assert seen[-1] == (786, 365)
    assert len(seen) == 18
    _exercise_map(compiler, cpu, seen)


def _exercise_map(
    compiler: SidneyPresentationCompiler, cpu: Uc, seen: list[tuple[int, int]]
) -> None:
    # Drawing and picking must agree for the map on wide and narrow displays,
    # including reference resolution with dense replacement artwork installed.
    for width, height in ((1024, 768), (1280, 800), (1280, 1024), (3840, 2160)):
        fit_height = min(height, width * 3 // 4)
        fit_width = fit_height * 4 // 3
        for x, y in ((130, 275), (350, 222), (830, 315)):
            point = (
                (width - fit_width) // 2 + round(x * fit_width / 1024),
                (height - fit_height) // 2 + round(y * fit_height / 768),
            )
            cpu.mem_write(STATE, bytes(128))
            _write(cpu, STATE + 16, 1)
            _write(cpu, compiler._physical_width_global_va, width, height)
            _write(cpu, POINT, *point)
            cursor = GOG_BUILD.address("input.cursor_position")
            _write(cpu, cursor, *point)
            _write(cpu, STACK, STOP, POINT)
            cpu.reg_write(UC_X86_REG_ESP, STACK)
            cpu.reg_write(UC_X86_REG_EAX, CALLBACK)
            cpu.reg_write(UC_X86_REG_ECX, 123)
            cpu.emu_start(BASE, STOP, count=1000)
            assert struct.unpack("<2I", cpu.mem_read(POINT, 8)) == point
            assert struct.unpack("<2I", cpu.mem_read(cursor, 8)) == point
            assert cpu.reg_read(UC_X86_REG_ESP) == STACK + 8
            assert cpu.reg_read(UC_X86_REG_EAX) == 789
    _exercise_map_edges(compiler, cpu, seen)


def _exercise_map_edges(
    compiler: SidneyPresentationCompiler, cpu: Uc, seen: list[tuple[int, int]]
) -> None:
    """Check actual emitted drawing against picking at every location boundary."""
    from unicorn.x86_const import UC_X86_REG_ESI  # noqa: PLC0415 - emulator child only.

    helper, rectangle = BASE + 0x8000, POINT + 256
    cpu.mem_write(
        helper, build_source_grid_rect(physical_width_va=compiler._physical_width_global_va)
    )
    # All sixteen native crop rectangles, with corrected terrain origins.
    locations = (
        (458, 225, 55, 39),
        (94, 400, 56, 50),
        (499, 137, 44, 39),
        (396, 187, 54, 40),
        (520, 4, 58, 54),
        (387, 258, 82, 45),
        (454, 65, 37, 24),
        (442, 155, 37, 32),
        (555, 72, 48, 49),
        (447, 91, 37, 30),
        (578, 22, 53, 49),
        (487, 174, 59, 48),
        (193, 119, 52, 47),
        (57, 131, 49, 38),
        (506, 89, 44, 38),
        (44, 218, 98, 75),
        (0, 0, 640, 480),
    )
    for width, height in ((1024, 768), (1280, 800), (1280, 1024), (1920, 1080), (3840, 2160)):
        _write(cpu, compiler._physical_width_global_va, width, height)
        for x, y, w, h in locations:
            left, top = x * width // 640, y * height // 480
            model = (left, top, (x + w) * width // 640, (y + h) * height // 480)
            _write(cpu, rectangle, *model)
            _write(cpu, STACK, STOP)
            cpu.reg_write(UC_X86_REG_ESP, STACK)
            cpu.reg_write(UC_X86_REG_ESI, rectangle)
            cpu.emu_start(helper, STOP, count=500)
            display = struct.unpack("<4I", cpu.mem_read(rectangle, 16))
            fit = min(height, width * 3 // 4)
            offsets = ((width - fit * 4 // 3) // 2, (height - fit) // 2)
            assert display == tuple(
                edge * fit // 480 + offsets[index % 2]
                for index, edge in enumerate((x, y, x + w, y + h))
            )
            for axis in (0, 1):
                for boundary in (display[axis], display[axis + 2]):
                    for delta in (-1, 0, 1):
                        point = [(display[0] + display[2]) // 2, (display[1] + display[3]) // 2]
                        point[axis] = boundary + delta
                        cpu.mem_write(STATE, bytes(128))
                        _write(cpu, STATE + 16, 1)
                        cpu.mem_write(POINT, struct.pack("<2i", *point))
                        _write(cpu, STACK, STOP, POINT)
                        cpu.reg_write(UC_X86_REG_ESP, STACK)
                        cpu.reg_write(UC_X86_REG_EAX, CALLBACK)
                        cpu.reg_write(UC_X86_REG_ECX, 123)
                        cpu.emu_start(BASE, STOP, count=1000)
                        hit = all(model[i] <= seen[-1][i] < model[i + 2] for i in (0, 1))
                        visible = all(display[i] <= point[i] < display[i + 2] for i in (0, 1))
                        assert hit == visible, (width, height, model, display, point, seen[-1])


if __name__ == "__main__":
    _exercise()
