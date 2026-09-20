"""Action-menu display scaling must not resize concurrent actor texture edits."""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

import pytest
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_EIP, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameABI
from gk3hd.patch.definitions.runtime2d.layout import (
    RuntimeLayout,
    RuntimeSegmentAddress,
    RuntimeSymbols,
)
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.system.blit_dispatch import BlitDispatchCompiler


def _wrapper() -> bytes:
    compiler = BlitDispatchCompiler(
        symbols=RuntimeSymbols(
            tuple(
                RuntimeSegmentAddress(
                    segment, segment.offset, segment.offset, 0xA00000 + segment.offset
                )
                for segment in RuntimeLayout.segments
            )
        ),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=0x900000, height_va=0x900004),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x900100,
            room_presentation_active_va=0x900104,
            pre_flip_presenter_slot_va=0x900108,
            post_flip_presenter_slot_va=0x90010C,
        ),
    )
    return compiler.build_blt_wrapper(
        wrapper_va=0x800000,
        downstream_va=0x820000,
        render_depth_va=0x900200,
        input_active_va=0x900204,
        transform_mode_va=0x900208,
        root_ptr_va=0x90020C,
        clear_pending_va=0x900210,
        transform_count_va=0x900214,
        composite_surface_va=0x900218,
        source_rect_va=0x900220,
        target_rect_va=0x900230,
        dest_rect_va=0x900240,
        bltfx_va=0x900250,
        left_bar_rect_va=0x900300,
        right_bar_rect_va=0x900310,
        hud_font_active_va=0x900320,
        hud_font_point_va=0x900324,
        hud_transform_count_va=0x90032C,
        hud_last_rect_va=0x900330,
        hd_font_active_va=0x900340,
        hd_font_source_rect_va=0x900350,
        hd_font_source_transform_count_va=0x900360,
        toolbar_blt_helper_va=0x820100,
        loadsave_background_helper_va=0x820200,
        cursor_surface_classifier_va=0x820300,
        tooltip_draw_depth_va=0x900364,
        tooltip_transfer_affine_va=0x820400,
        binocs_local_blt_helper_va=0x820500,
    )


@pytest.mark.parametrize("screen", [(1024, 768), (1280, 800), (3840, 2160)])
@pytest.mark.parametrize("target", ["display", "actor", "wrong-width", "wrong-height"])
@pytest.mark.slow
def test_action_extent_gate_only_accepts_display_target(
    screen: tuple[int, int], target: str
) -> None:
    subprocess.run(  # noqa: S603 - own test module and enumerated fixture values.
        [sys.executable, str(Path(__file__).resolve()), target, *(str(value) for value in screen)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _execute(screen: tuple[int, int], target: str) -> None:
    payload = _wrapper()
    # Select the first display gate, which must precede ActionMenu's extent
    # transform; the generic UI gate later in the dispatcher is insufficient.
    width_va = GOG_BUILD.address("display.dimensions")
    marker = b"\x8b\x54\x24\x18\xa1" + struct.pack("<I", width_va) + b"\x39\x42\x38"
    start = payload.index(marker)
    assert payload[start - 12 : start - 6] == b"\x81\x38" + struct.pack(
        "<I", GOG_BUILD.address("action_menu.vtable")
    )
    assert payload[start + 12 : start + 14] == b"\x0f\x85"
    native = 0x800000 + start + 18 + struct.unpack_from("<i", payload, start + 14)[0]
    accepted = 0x800000 + start + 32
    assert payload[start + 32 : start + 36] == b"\x8b\x74\x24\x28"
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    for address, size in ((0x800000, 0x10000), (0x900000, 0x10000), (width_va & ~0xFFF, 0x1000)):
        machine.mem_map(address, size)
    machine.mem_write(0x800000, payload)
    dimensions = {
        "display": screen,
        "actor": (256, 256),
        "wrong-width": (256, screen[1]),
        "wrong-height": (screen[0], 256),
    }[target]
    machine.mem_write(width_va, struct.pack("<II", *screen))
    machine.mem_write(0x901038, struct.pack("<II", *dimensions))
    machine.mem_write(0x902018, struct.pack("<I", 0x901000))
    machine.reg_write(UC_X86_REG_ESP, 0x902000)
    # Stop before the selected downstream policy; execute the unmodified gate.
    expected = accepted if target == "display" else native
    machine.emu_start(0x800000 + start, expected, count=16)
    assert machine.reg_read(UC_X86_REG_EIP) == expected


if __name__ == "__main__":
    _execute((int(sys.argv[2]), int(sys.argv[3])), sys.argv[1])
