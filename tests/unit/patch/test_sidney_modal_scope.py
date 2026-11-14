"""A laptop redraw must not inherit a retained modal's destination affine."""

from __future__ import annotations

import struct

import pytest
from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_ESP

from gk3hd.patch.binary.x86 import X86Emitter
from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.guard_stale_mouse_move_targets import MouseMoveDispatchABI
from gk3hd.patch.definitions.runtime2d.layout import (
    SIDNEY_DRAW_DEPTH_OFFSET,
    SIDNEY_PRESENTATION_SEGMENT,
    RuntimeLayout,
    RuntimeSegmentAddress,
    RuntimeSymbols,
)
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.sidney_composition import build_blt_wrapper
from gk3hd.patch.definitions.runtime2d.sidney_presentation import SidneyPresentationCompiler
from tests.unit.patch.test_action_blit_target import _wrapper


def _divide(value: int, divisor: int) -> int:
    """Match signed integer geometry without floating-point rounding."""
    return (abs(value) // divisor) * (-1 if value < 0 else 1)


@pytest.mark.parametrize("screen", [(1024, 768), (1280, 800), (3840, 2160)])
@pytest.mark.parametrize("destination", [(0, 0, 1024, 144), (0, 624, 1024, 768)])
@pytest.mark.parametrize("laptop_depth", [0, 1, 2])
def test_current_laptop_draw_owns_frame_fit_without_withdrawing_quit_input(
    screen: tuple[int, int], destination: tuple[int, ...], laptop_depth: int
) -> None:
    symbols = RuntimeSymbols(
        tuple(
            RuntimeSegmentAddress(
                segment, segment.offset, segment.offset, 0xA00000 + segment.offset
            )
            for segment in RuntimeLayout.segments
        )
    )
    compiler = SidneyPresentationCompiler(
        symbols=symbols,
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=0x900000, height_va=0x900004),
        mouse_move_abi=MouseMoveDispatchABI(ui_dispatch_adapter_slot_va=0x900400),
    )
    depth = symbols.va(SIDNEY_PRESENTATION_SEGMENT.logical_name, SIDNEY_DRAW_DEPTH_OFFSET)
    laptop = build_blt_wrapper(
        compiler,
        wrapper_va=0x830000,
        active_depth_va=depth,
        transformed_blit_count_va=0x904100,
        rect_scratch_va=0x904000,
        cursor_blt_trace_helper_va=0x840000,
        extension_surface_ptr_va=0x904104,
        status_trace_count_va=0x904108,
        status_trace_records_va=0x905000,
        system_blt_wrapper_va=0x800000,
        portrait_source_va=0x840100,
        frame_source_va=0x840200,
        cursor_surface_classifier_va=0x820300,
        final_transfer_va=0x850000,
    )
    shared = _wrapper()
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x700000)
    # Unrelated resource classifiers decline. Both destination-transform
    # owners execute their real emitted instructions, in production order.
    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    for base, body in ((0x800000, shared), (0x830000, laptop)):
        for instruction in decoder.disasm(body, base):
            if instruction.mnemonic == "call" and instruction.op_str.startswith("0x"):
                cpu.mem_write(int(instruction.op_str, 16), bytes.fromhex("31 c0 f8 c3"))
    cpu.mem_write(0x800000, shared)
    cpu.mem_write(0x830000, laptop)
    downstream = X86Emitter(base_va=0x820000)
    downstream.jump_absolute(0x830000)
    cpu.mem_write(0x820000, downstream.build())

    def write(address: int, *values: int) -> None:
        cpu.mem_write(address, struct.pack(f"<{len(values)}i", *values))

    write(GOG_BUILD.address("display.dimensions"), *screen)
    write(depth, laptop_depth)
    # Quit remains the input owner, including after its Draw has returned.
    write(0x900200, 0, 1, 10, 0x901000)
    root = (343, 291, 938, 509)
    write(0x901000, GOG_BUILD.address("confirm_quit.vtable"))
    write(0x90101C, *root)
    write(0x902038, *screen)
    write(0x906000, *destination)
    source = struct.pack("<4i", 0, 0, 4096, 576)
    cpu.mem_write(0x906020, source)
    write(
        0x909000, GOG_BUILD.address("runtime2d.high_blt_final_return"), 0x903000, 0x906000, 0x906020
    )
    cpu.reg_write(UC_X86_REG_ECX, 0x902000)
    cpu.reg_write(UC_X86_REG_ESP, 0x909000)
    cpu.emu_start(0x800000, 0x850000, count=2000)

    _, destination_pointer, source_pointer = struct.unpack("<3I", cpu.mem_read(0x909004, 12))
    actual = struct.unpack("<4i", cpu.mem_read(destination_pointer, 16))
    height = screen[1]
    if laptop_depth:
        pillar = (screen[0] - height * 4 // 3) // 2
        expected = tuple(
            edge * height // 768 + (pillar if index % 2 == 0 else 0)
            for index, edge in enumerate(destination)
        )
        assert 0 <= actual[1] < actual[3] <= height
    else:
        # With no laptop Draw in progress, the dialog's local affine still
        # applies. The fix must not disable ordinary modal child rendering.
        centers = ((root[0] + root[2]) // 2, (root[1] + root[3]) // 2)
        target = tuple(
            centers[index % 2] + _divide((edge - centers[index % 2]) * height, 768)
            for index, edge in enumerate(root)
        )
        expected = tuple(
            target[index % 2]
            + _divide(
                (edge - root[index % 2]) * (target[index % 2 + 2] - target[index % 2]),
                root[index % 2 + 2] - root[index % 2],
            )
            for index, edge in enumerate(destination)
        )
    assert actual == expected
    assert source_pointer == 0x906020
    assert cpu.mem_read(source_pointer, 16) == source
    assert cpu.mem_read(0x906000, 16) == struct.pack("<4i", *destination)
    assert struct.unpack("<4I", cpu.mem_read(0x900200, 16)) == (0, 1, 10, 0x901000)
    assert struct.unpack("<I", cpu.mem_read(depth, 4))[0] == laptop_depth
