"""A toolbar nested in SIDNEY shares its panel's canvas, not the room affine."""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

import pytest
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.guard_stale_mouse_move_targets import MouseMoveDispatchABI
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameABI
from gk3hd.patch.definitions.runtime2d.layout import (
    SIDNEY_DRAW_DEPTH_OFFSET,
    SIDNEY_PRESENTATION_SEGMENT,
    SIDNEY_ROOT_POINTER_OFFSET,
    RuntimeLayout,
    RuntimeSegmentAddress,
    RuntimeSymbols,
)
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.sidney_composition import build_blt_wrapper
from gk3hd.patch.definitions.runtime2d.sidney_presentation import SidneyPresentationCompiler
from gk3hd.patch.definitions.runtime2d.sidney_toolbar import build_draw, build_layout, build_warp
from gk3hd.patch.definitions.runtime2d.system.menu_action import ActionMenuFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.menu_dropdown import DropdownFeatureCompiler


@pytest.mark.slow
def test_nested_toolbar_matches_sidney_canvas_at_all_display_sizes() -> None:
    subprocess.run(  # noqa: S603 - execute only this checked-in native-code test.
        [sys.executable, str(Path(__file__).resolve())],
        check=True,
        capture_output=True,
        timeout=10,
    )


def _exercise() -> None:
    compiler = ActionMenuFeatureCompiler(
        symbols=RuntimeSymbols(
            tuple(
                RuntimeSegmentAddress(segment, 0, 0, 0xA00000 + segment.offset)
                for segment in RuntimeLayout.segments
            )
        ),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=0x790004, height_va=0x790008),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x791000,
            room_presentation_active_va=0x791008,
            pre_flip_presenter_slot_va=0x791004,
            post_flip_presenter_slot_va=0x79100C,
        ),
    )
    active = compiler.symbols.va(SIDNEY_PRESENTATION_SEGMENT.logical_name, SIDNEY_DRAW_DEPTH_OFFSET)
    final = build_blt_wrapper(
        SidneyPresentationCompiler(
            symbols=compiler.symbols,
            profile=GOG_BUILD,
            room_rendering_abi=compiler.room_rendering_abi,
            mouse_move_abi=MouseMoveDispatchABI(ui_dispatch_adapter_slot_va=0x792000),
        ),
        wrapper_va=0x830000,
        active_depth_va=active,
        transformed_blit_count_va=0x906000,
        rect_scratch_va=0x906010,
        cursor_blt_trace_helper_va=0x820000,
        extension_surface_ptr_va=0x906020,
        status_trace_count_va=0x906024,
        status_trace_records_va=0x906100,
        system_blt_wrapper_va=0x820000,
        portrait_source_va=0x820000,
        frame_source_va=0x820000,
        cursor_surface_classifier_va=0x820000,
        final_transfer_va=0x810000,
    )
    payload = compiler.build_toolbar_blt_helper(
        wrapper_va=0x800000,
        preview_surface_va=0x901300,
        dropdown_ptr_va=0x901304,
        root_ptr_va=0x901040,
        source_rect_va=0x901000,
        target_rect_va=0x901050,
        dest_rect_va=0x901060,
        transform_count_va=0x901070,
        clipped_source_rect_va=0x901200,
        cursor_surface_classifier_va=0x820000,
        input_snapshot_valid_va=0x901248,
        input_snapshot_source_rect_va=0x90124C,
        input_snapshot_target_rect_va=0x90125C,
    )
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0xC00000)
    cpu.mem_write(0x800000, payload)
    cpu.mem_write(0x830000, final)
    cpu.mem_write(0x820000, bytes.fromhex("31 c0 c3"))
    width_va = GOG_BUILD.address("display.dimensions")
    cpu.mem_write(active, struct.pack("<I", 1))
    cpu.mem_write(0x902018, struct.pack("<I", 0x903000))
    cpu.mem_write(0x902028, struct.pack("<I", 0x904000))
    rectangles = ((141, 290, 173, 322), (930, 710, 962, 742), (136, 251, 388, 326))
    for width, height in ((800, 600), (1024, 768), (1280, 800), (1920, 1080), (3840, 2160)):
        cpu.mem_write(width_va, struct.pack("<II", width, height))
        for display in (True, False):
            cpu.mem_write(
                0x903038, struct.pack("<II", width if display else 128, height if display else 128)
            )
            for rect in rectangles:
                cpu.mem_write(0x904000, struct.pack("<4i", *rect))
                cpu.mem_write(0x905000, struct.pack("<I", 0x810000))
                cpu.reg_write(UC_X86_REG_ESP, 0x905000)
                cpu.reg_write(UC_X86_REG_ECX, 0x902000)
                cpu.emu_start(0x800000, 0x810000, count=300)
                # Room-local affine must not run before SIDNEY's final fit.
                assert struct.unpack("<4i", cpu.mem_read(0x904000, 16)) == rect
                assert cpu.reg_read(UC_X86_REG_EAX) == 0
                assert cpu.reg_read(UC_X86_REG_ECX) == 0x902000
                assert cpu.reg_read(UC_X86_REG_ESP) == 0x905004
                cpu.mem_write(0x905000, struct.pack("<4I", 0x850000, 0x903100, 0x904000, 0))
                cpu.reg_write(UC_X86_REG_ESP, 0x905000)
                cpu.reg_write(UC_X86_REG_ECX, 0x903000)
                cpu.emu_start(0x830000, 0x810000, count=300)
                expected = (
                    tuple(
                        edge * height // 768
                        + ((width - height * 4 // 3) // 2 if index % 2 == 0 else 0)
                        for index, edge in enumerate(rect)
                    )
                    if display
                    else rect
                )
                rectangle = struct.unpack("<I", cpu.mem_read(0x905008, 4))[0]
                assert struct.unpack("<4i", cpu.mem_read(rectangle, 16)) == expected
                # Do not publish a room-toolbar input inverse: SIDNEY already
                # applies its canvas inverse to the complete event traversal.
                assert bytes(cpu.mem_read(0x901248, 4)) == bytes(4)

    # Hover/visibility can draw outside the root traversal. A current SIDNEY
    # layer must still never publish a room-menu inverse for later input.
    cpu.mem_write(active, bytes(4))
    cpu.mem_write(
        compiler.symbols.va(SIDNEY_PRESENTATION_SEGMENT.logical_name, SIDNEY_ROOT_POINTER_OFFSET),
        struct.pack("<I", 0x907000),
    )
    cpu.mem_write(GOG_BUILD.address("ui.current_layer"), bytes.fromhex("b8 00 70 90 00 c3"))
    cpu.mem_write(0x904000, struct.pack("<4i", 770, 479, 1022, 766))
    cpu.mem_write(0x905000, struct.pack("<I", 0x810000))
    cpu.reg_write(UC_X86_REG_ESP, 0x905000)
    cpu.reg_write(UC_X86_REG_ECX, 0x902000)
    cpu.emu_start(0x800000, 0x810000, count=300)
    assert struct.unpack("<4i", cpu.mem_read(0x904000, 16)) == (770, 479, 1022, 766)
    assert bytes(cpu.mem_read(0x901248, 4)) == bytes(4)
    assert cpu.reg_read(UC_X86_REG_ECX) == 0x902000


def _exercise_bounds_and_warp() -> None:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x800000, 0x200000)
    cpu.mem_write(0x900010, struct.pack("<I", 0x900100))
    cpu.mem_write(
        0x800000,
        build_layout(
            wrapper_va=0x800000,
            current_layer_va=0x820000,
            root_va=0x900010,
            input_valid_va=0x900020,
            native_va=0x810000,
            fallback_va=0x810100,
        ),
    )
    cpu.mem_write(
        0x830000,
        build_warp(
            wrapper_va=0x830000,
            current_layer_va=0x820000,
            root_va=0x900010,
            physical_width_va=0x900030,
            native_va=0x810000,
            fallback_va=0x810100,
        ),
    )
    for current in (0, 0x900100, 0x900200):
        cpu.mem_write(0x820000, b"\xb8" + struct.pack("<I", current) + b"\xc3")
        cpu.ctl_remove_cache(0x820000, 0x820010)
        destination = 0x810000 if current == 0x900100 else 0x810100
        for rect in ((808, 596, 1060, 671), (-12, -20, 240, 320), (700, 620, 952, 950)):
            cpu.mem_write(0x904000, struct.pack("<4i", *rect))
            cpu.mem_write(0x905000, struct.pack("<II", 0x850000, 0x904000))
            cpu.reg_write(UC_X86_REG_ESP, 0x905000)
            cpu.reg_write(UC_X86_REG_ECX, 0x906000)
            cpu.emu_start(0x800000, destination, count=200)
            observed = struct.unpack("<4i", cpu.mem_read(0x904000, 16))
            if current == 0x900100:
                assert 2 <= observed[0] < observed[2] <= 1022
                assert 2 <= observed[1] < observed[3] <= 766
                assert observed[2] - observed[0] == rect[2] - rect[0]
                assert observed[3] - observed[1] == rect[3] - rect[1]
            else:
                assert observed == rect
            assert cpu.reg_read(UC_X86_REG_ECX) == 0x906000
            assert cpu.reg_read(UC_X86_REG_ESP) == 0x905000
        for width, height in ((1024, 768), (1280, 800), (3840, 2160)):
            cpu.mem_write(0x900030, struct.pack("<II", width, height))
            cpu.mem_write(0x904000, struct.pack("<ii", 876, 682))
            cpu.mem_write(0x905000, struct.pack("<II", 0x850000, 0x904000))
            cpu.reg_write(UC_X86_REG_ESP, 0x905000)
            # Unicorn caches stop boundaries in translated blocks. The same
            # callback was resumed through RET in the previous iteration.
            cpu.ctl_remove_cache(0x800000, 0x850100)
            cpu.emu_start(0x830000, destination, count=200)
            stack = cpu.reg_read(UC_X86_REG_ESP)
            point = struct.unpack("<I", cpu.mem_read(stack + 4, 4))[0]
            assert 0x800000 <= point < 0xA00000, (current, width, height, hex(stack), hex(point))
            expected = (
                (
                    876 * height // 768 + (width - height * 4 // 3) // 2,
                    682 * height // 768,
                )
                if current == 0x900100
                else (876, 682)
            )
            assert struct.unpack("<ii", cpu.mem_read(point, 8)) == expected
            assert struct.unpack("<ii", cpu.mem_read(0x904000, 8)) == (876, 682)
            if current == 0x900100:
                cpu.mem_write(destination, b"\xc3")
                cpu.emu_start(destination, 0x850000, count=20)
                assert cpu.reg_read(UC_X86_REG_ESP) == 0x905004


def _exercise_deferred_draw() -> None:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x800000, 0x200000)
    cpu.mem_write(0x900010, struct.pack("<I", 0x900100))
    cpu.mem_write(
        0x800000,
        build_draw(
            wrapper_va=0x800000,
            current_layer_va=0x820000,
            root_va=0x900010,
            depth_va=0x900020,
            native_va=0x810000,
        ),
    )
    cpu.mem_write(0x810000, bytes.fromhex("c2 08 00"))
    for current in (0, 0x900100, 0x900200):
        cpu.mem_write(0x820000, b"\xb8" + struct.pack("<I", current) + b"\xc3")
        for depth in (0, 1, 3):
            cpu.ctl_remove_cache(0x800000, 0x850100)
            cpu.mem_write(0x900020, struct.pack("<I", depth))
            cpu.mem_write(0x905000, struct.pack("<3I", 0x850000, 0x912300, 0x923400))
            cpu.reg_write(UC_X86_REG_ESP, 0x905000)
            cpu.reg_write(UC_X86_REG_ECX, 0x906000)
            cpu.emu_start(0x800000, 0x810000, count=100)
            assert struct.unpack("<I", cpu.mem_read(0x900020, 4))[0] == (
                depth + (current == 0x900100)
            )
            stack = cpu.reg_read(UC_X86_REG_ESP)
            assert struct.unpack("<2I", cpu.mem_read(stack + 4, 8)) == (0x912300, 0x923400)
            assert cpu.reg_read(UC_X86_REG_ECX) == 0x906000
            cpu.emu_start(0x810000, 0x850000, count=20)
            assert struct.unpack("<I", cpu.mem_read(0x900020, 4))[0] == depth
            assert cpu.reg_read(UC_X86_REG_ESP) == 0x90500C


def _exercise_dropdown_bounds() -> None:
    compiler = DropdownFeatureCompiler(
        symbols=RuntimeSymbols(
            segments=(RuntimeSegmentAddress(SIDNEY_PRESENTATION_SEGMENT, 0, 0, 0x910000),)
        ),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=0x790004, height_va=0x790008),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x791000,
            room_presentation_active_va=0x791008,
            pre_flip_presenter_slot_va=0x791004,
            post_flip_presenter_slot_va=0x79100C,
        ),
    )
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x600000)
    cpu.mem_write(
        0x800000,
        compiler.build_resolution_dropdown_fit_helper(wrapper_va=0x800000, root_ptr_va=0x900000),
    )
    cpu.mem_write(0x900000, struct.pack("<I", 0x901000))
    cpu.mem_write(0x910000 + SIDNEY_ROOT_POINTER_OFFSET, struct.pack("<I", 0x907000))
    cpu.mem_write(0x90204C, struct.pack("<II", 0x903000, 3))
    cpu.mem_write(0x903000, struct.pack("<3I", 0x904000, 0, 0x904100))
    for current in (0, 0x907000, 0x907100):
        cpu.mem_write(
            GOG_BUILD.address("ui.current_layer"), b"\xb8" + struct.pack("<I", current) + b"\xc3"
        )
        cpu.ctl_remove_cache(0x400000, 0x850100)
        for height in (600, 768, 800, 1080, 2160):
            cpu.mem_write(GOG_BUILD.address("display.dimensions"), struct.pack("<II", 1280, height))
            for bottom in (700, 900):
                cpu.mem_write(0x90101C, struct.pack("<4i", 770, 400, 1022, 687))
                cpu.mem_write(0x90201C, struct.pack("<4i", 877, bottom - 172, 1014, bottom))
                cpu.mem_write(0x90401C, struct.pack("<4i", 880, bottom - 170, 1011, bottom - 158))
                cpu.mem_write(0x90411C, struct.pack("<4i", 880, bottom - 14, 1011, bottom - 2))
                for _ in range(2):
                    cpu.mem_write(0x905000, struct.pack("<I", 0x850000))
                    cpu.reg_write(UC_X86_REG_ESP, 0x905000)
                    cpu.reg_write(UC_X86_REG_ECX, 0x902000)
                    cpu.emu_start(0x800000, 0x850000, count=300)
                    popup = struct.unpack("<4i", cpu.mem_read(0x90201C, 16))
                    first = struct.unpack("<4i", cpu.mem_read(0x90401C, 16))
                    last = struct.unpack("<4i", cpu.mem_read(0x90411C, 16))
                    assert popup[2] - popup[0] == 137
                    assert popup[3] - popup[1] == 172
                    assert first[1] == popup[1] + 2
                    assert last[3] == popup[3] - 2
                    if current == 0x907000:
                        assert popup[3] == min(bottom, 768)
                    else:
                        assert (popup[3] - 437) * height // 768 + 437 <= height
                    assert cpu.reg_read(UC_X86_REG_ECX) == 0x902000
                    assert cpu.reg_read(UC_X86_REG_ESP) == 0x905004


if __name__ == "__main__":
    _exercise()
    _exercise_bounds_and_warp()
    _exercise_deferred_draw()
    _exercise_dropdown_bounds()
