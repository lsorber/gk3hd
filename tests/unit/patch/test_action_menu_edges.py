"""Enlarged action rows stay visible and clickable at horizontal screen edges."""

from __future__ import annotations

import struct

import pytest
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameABI
from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.system.menu_action import ActionMenuFeatureCompiler

_CODE = 0x800000
_ORIGIN = 0x800800
_STATE = 0x802000
_ROOT = 0x900100
_CHILDREN = 0x900200
_STACK = 0x90F000
_RETURN = 0x80F000


def _machine(screen: tuple[int, int], center: tuple[int, int], button_count: int) -> Uc:
    compiler = ActionMenuFeatureCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=0x900000, height_va=0x900004),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x900010,
            room_presentation_active_va=0x900014,
            pre_flip_presenter_slot_va=0x900018,
            post_flip_presenter_slot_va=0x90001C,
        ),
    )
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    dimensions = GOG_BUILD.address("display.dimensions")
    current_layer = GOG_BUILD.address("ui.current_layer")
    for address, length in (
        (_CODE, 0x10000),
        (0x900000, 0x10000),
        (dimensions & ~0xFFF, 0x1000),
        (current_layer & ~0xFFF, 0x1000),
    ):
        machine.mem_map(address, length)
    machine.mem_write(
        _CODE,
        compiler.build_action_layout_helper(
            wrapper_va=_CODE, state_va=_STATE, horizontal_origin_va=_ORIGIN
        ),
    )
    machine.mem_write(
        _ORIGIN,
        compiler.build_action_horizontal_origin_helper(wrapper_va=_ORIGIN, center_x_va=_STATE + 4),
    )
    machine.mem_write(current_layer, b"\x31\xc0\xc3")  # no Inventory coordinate owner
    machine.mem_write(dimensions, struct.pack("<II", *screen))
    machine.mem_write(_STATE + 0x14, struct.pack("<I", 768))
    x, y = center
    half_width = 16 * button_count
    machine.mem_write(
        _ROOT + 0x1C, struct.pack("<iiii", x - half_width, y - 16, x + half_width, y + 16)
    )
    machine.mem_write(_ROOT + 0x4C, struct.pack("<II", _CHILDREN, button_count))
    for index in range(button_count):
        machine.mem_write(_CHILDREN + index * 4, struct.pack("<I", 0x901000 + index * 0x100))
    return machine


@pytest.mark.parametrize("screen", [(1280, 800), (1920, 1080), (3840, 2160)])
@pytest.mark.parametrize("position", ["left", "right", "center"])
@pytest.mark.parametrize("button_count", [4, 5])
def test_action_row_fits_without_squashing_and_stays_stable(
    screen: tuple[int, int], position: str, button_count: int
) -> None:
    width, height = screen
    center = {
        "left": (16 * button_count, height // 2),
        "right": (width - 16 * button_count - 2, height // 2),
        "center": (width // 2, height // 2),
    }[position]
    machine = _machine(screen, center, button_count)
    size = (32 * height + 384) // 768
    previous = None
    for _ in range(2):
        machine.mem_write(_STACK, struct.pack("<I", _RETURN))
        machine.reg_write(UC_X86_REG_ESP, _STACK)
        machine.reg_write(UC_X86_REG_ECX, _ROOT)
        machine.emu_start(_CODE, _RETURN, count=1000)
        rectangle = struct.unpack("<iiii", machine.mem_read(_ROOT + 0x1C, 16))
        left, top, right, bottom = rectangle
        assert 0 <= left < right <= width
        assert 0 <= top < bottom <= height
        assert right - left == size * button_count
        assert bottom - top == size
        for index in range(button_count):
            button = struct.unpack("<iiii", machine.mem_read(0x90101C + index * 0x100, 16))
            assert button == (left + size * index, top, left + size * (index + 1), bottom)
        if previous is not None:
            assert rectangle == previous
        previous = rectangle
