"""Execute complete second-pass pointer transport without a game or runtime."""

from __future__ import annotations

import struct

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.guard_stale_mouse_move_targets import MouseMoveDispatchABI
from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.sidney_input import (
    build_input_dispatch_wrapper,
    build_pointer_motion_dispatch_thunk,
    build_pointer_motion_dispatch_wrapper,
)
from gk3hd.patch.definitions.runtime2d.sidney_presentation import SidneyPresentationCompiler


@pytest.mark.parametrize("owner", ["sidney", "retained", "absent", "null"])
@pytest.mark.parametrize(
    ("screen", "point"),
    [
        ((1280, 800), (763, 392)),
        ((3840, 2160), (1900, 1000)),
        ((1024, 768), (700, 350)),
        ((1280, 800), (101, -1)),
        ((1568, 1568), (400, 701)),
        ((1280, 800), None),
    ],
)
@pytest.mark.parametrize("flags", [0, 1])
@pytest.mark.parametrize("delta", [(-17, 23), (0, 0), (3, -5), None])
def test_motion_picker_receives_one_inverse_only_for_current_sidney(
    owner: str,
    screen: tuple[int, int],
    point: tuple[int, int] | None,
    flags: int,
    delta: tuple[int, int] | None,
) -> None:
    compiler = SidneyPresentationCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=0x900800, height_va=0x900804),
        mouse_move_abi=MouseMoveDispatchABI(ui_dispatch_adapter_slot_va=0x900808),
    )
    names = (
        "root_ptr_va",
        "input_transform_count_va",
        "input_source_x_va",
        "input_logical_x_va",
        "driving_map_active_va",
        "driving_map_input_depth_va",
        "tbt_layer_va",
        "tbt_target_rect_va",
        "tbt_input_wrapper_va",
        "system_active_va",
        "system_root_ptr_va",
        "system_transform_mode_va",
        "system_input_wrapper_va",
        "toolbar_input_wrapper_va",
        "reference_anchor_input_wrapper_va",
        "reference_canvas_input_wrapper_va",
        "binocs_input_wrapper_va",
        "system_action_presented_root_va",
    )
    state = {name: 0x900000 + index * 32 for index, name in enumerate(names)}
    wrapper, inverse, thunk = 0x830000, 0x831000, 0x832000
    current, point_va, delta_va, stack, stop = 0x901000, 0x902000, 0x902020, 0xA01000, 0x840000
    native = GOG_BUILD.address("mouse_move.motion_dispatch")
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x700000)
    cpu.mem_write(
        inverse,
        build_input_dispatch_wrapper(
            compiler,
            wrapper_va=inverse,
            **state,
            system_native_input_vtables=(),
        ),
    )
    cpu.mem_write(
        thunk,
        build_pointer_motion_dispatch_thunk(
            compiler, wrapper_va=thunk, sidney_root_va=state["root_ptr_va"]
        ),
    )
    cpu.mem_write(
        wrapper,
        build_pointer_motion_dispatch_wrapper(
            wrapper_va=wrapper,
            input_wrapper_va=inverse,
            thunk_va=thunk,
            native_dispatch_va=native,
            physical_width_va=compiler._physical_width_global_va,
            sidney_root_va=state["root_ptr_va"],
            tbt_layer_va=state["tbt_layer_va"],
            current_layer_va=compiler._current_layer_va,
            driving_map_active_va=state["driving_map_active_va"],
            inventory_active_va=0x901100,
            toolbar_input_valid_va=0x901104,
            system_active_va=state["system_active_va"],
            system_transform_mode_va=state["system_transform_mode_va"],
            toolbar_transform_mode=compiler._system_popup_mode,
            reference_canvas_transform_mode=compiler._system_reference_canvas_mode,
            system_root_ptr_va=state["system_root_ptr_va"],
            toolbar_vtable_va=GOG_BUILD.address("ingame_toolbar.vtable"),
            death_vtable_va=GOG_BUILD.address("death.vtable"),
            zodiac_vtable_va=GOG_BUILD.address("zodiac.vtable"),
            is_bad_read_ptr_va=GOG_BUILD.address("win32.IsBadReadPtr"),
        ),
    )
    cpu.mem_write(compiler._current_layer_va, b"\xa1" + struct.pack("<I", current) + b"\xc3")
    cpu.mem_write(native, bytes.fromhex("b8 a5 00 00 00 c2 14 00"))
    cpu.mem_write(current, struct.pack("<I", 0 if owner == "null" else 0x904000))
    cpu.mem_write(
        state["root_ptr_va"],
        struct.pack(
            "<I",
            {
                "sidney": 0x904000,
                "retained": 0x905000,
                "absent": 0,
                "null": 0,
            }[owner],
        ),
    )
    cpu.mem_write(compiler._physical_width_global_va, struct.pack("<2I", *screen))
    original_point = struct.pack("<2i", *point) if point is not None else bytes(8)
    original_delta = struct.pack("<2i", *delta) if delta is not None else bytes(8)
    cpu.mem_write(point_va, original_point)
    cpu.mem_write(delta_va, original_delta)
    cpu.mem_write(
        stack,
        struct.pack(
            "<6I",
            stop,
            point_va if point is not None else 0,
            delta_va if delta is not None else 0,
            flags,
            0x778899,
            0x28,
        ),
    )
    seeds = {
        UC_X86_REG_EBX: 0x3333,
        UC_X86_REG_ESI: 0x4444,
        UC_X86_REG_EDI: 0x5555,
        UC_X86_REG_EBP: 0x6666,
    }
    for register, value in seeds.items():
        cpu.reg_write(register, value)
    cpu.reg_write(UC_X86_REG_ESP, stack)
    cpu.reg_write(UC_X86_REG_ECX, 0x906000)
    seen = []

    def observe(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address == native:
            args = struct.unpack("<5I", machine.mem_read(machine.reg_read(UC_X86_REG_ESP) + 4, 20))
            seen.append(
                (
                    struct.unpack("<2i", machine.mem_read(args[0], 8)) if args[0] else None,
                    struct.unpack("<2i", machine.mem_read(args[1], 8)) if args[1] else None,
                    args[2:],
                    machine.reg_read(UC_X86_REG_ECX),
                )
            )

    cpu.hook_add(UC_HOOK_CODE, observe)
    cpu.emu_start(wrapper, stop, count=2000)
    offset = (screen[0] - screen[1] * 4 // 3) // 2

    # Both endpoints use signed truncation, not a separately rounded/scaled
    # delta. This preserves the native previous = current - delta identity.
    def inverse(value: tuple[int, int]) -> tuple[int, int]:
        return (
            int((value[0] - offset) * 768 / screen[1]),
            int(value[1] * 768 / screen[1]),
        )

    expected = inverse(point) if owner == "sidney" and point is not None else point
    expected_delta = delta
    if owner == "sidney" and expected is not None and point is not None and delta is not None:
        previous = inverse((point[0] - delta[0], point[1] - delta[1]))
        expected_delta = (expected[0] - previous[0], expected[1] - previous[1])
    assert seen == [(expected, expected_delta, (flags, 0x778899, 0x28), 0x906000)]
    assert bytes(cpu.mem_read(point_va, 8)) == original_point
    assert bytes(cpu.mem_read(delta_va, 8)) == original_delta
    assert cpu.reg_read(UC_X86_REG_EAX) == 0xA5
    assert cpu.reg_read(UC_X86_REG_ESP) == stack + 24
    assert all(cpu.reg_read(register) == value for register, value in seeds.items())
