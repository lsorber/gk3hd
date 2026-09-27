"""SIDNEY clips in model space before fitting onto the physical framebuffer."""

import struct

import pytest
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EFLAGS,
    UC_X86_REG_ESP,
)

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.guard_stale_mouse_move_targets import MouseMoveDispatchABI
from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.sidney_composition import build_root_draw_bridge
from gk3hd.patch.definitions.runtime2d.sidney_presentation import SidneyPresentationCompiler
from gk3hd.patch.definitions.runtime2d.ui_frames import build_high_dimensions


@pytest.mark.parametrize("size", [(640, 480), (800, 600), (1024, 768), (1280, 800), (3840, 2160)])
@pytest.mark.parametrize("kind", ["sidney", "inactive", "offscreen", "cursor"])
@pytest.mark.parametrize("dense", [False, True])
def test_model_clipping_preserves_sampling_and_unowned_surfaces(
    size: tuple[int, int], kind: str, *, dense: bool
) -> None:
    base, match, classifier, stop = 0x800000, 0x801000, 0x802000, 0x803000
    state, source, destination, frame, stack = 0x804000, 0x805000, 0x806000, 0x808000, 0x809000
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(base, 0x10000)
    cpu.mem_write(
        base,
        build_high_dimensions(
            wrapper_va=base,
            surface_match_va=match,
            original=GOG_BUILD.site("runtime2d.high_blt_dimensions").original,
            return_va=stop,
            sidney_depth_va=state,
            physical_width_va=state + 4,
            cursor_classifier_va=classifier,
        ),
    )
    cpu.mem_write(match, b"\xf9\xc3" if dense else b"\xf8\xc3")
    cpu.mem_write(classifier, b"\xb8" + struct.pack("<I", kind == "cursor") + b"\xc3")
    cpu.mem_write(state, struct.pack("<3I", kind != "inactive", *size))
    actual_size = (128, 128) if kind == "offscreen" else size
    cpu.mem_write(source + 0x38, struct.pack("<2I", 256, 128))
    cpu.mem_write(destination + 0x38, struct.pack("<2I", *actual_size))
    for register, value in (
        (UC_X86_REG_EBX, source),
        (UC_X86_REG_EDI, destination),
        (UC_X86_REG_EBP, frame),
        (UC_X86_REG_ESP, stack),
        (UC_X86_REG_EFLAGS, 0x246),
    ):
        cpu.reg_write(register, value)
    cpu.emu_start(base, stop, count=200)
    clip = struct.unpack("<2I", cpu.mem_read(frame - 0x5C, 8))
    assert clip == ((1024, 768) if kind == "sidney" else actual_size)
    expected_source = (64, 32) if dense else (256, 128)
    assert (cpu.reg_read(UC_X86_REG_EAX), cpu.reg_read(UC_X86_REG_ECX)) == expected_source
    assert bytes(cpu.mem_read(destination + 0x38, 8)) == struct.pack("<2I", *actual_size)
    assert bytes(cpu.mem_read(source + 0x38, 8)) == struct.pack("<2I", 256, 128)
    assert cpu.reg_read(UC_X86_REG_ESP) == stack
    assert cpu.reg_read(UC_X86_REG_EFLAGS) == 0x246


@pytest.mark.parametrize("size", [(640, 480), (800, 600), (1024, 768), (1280, 800), (3840, 2160)])
def test_root_contains_the_complete_logical_laptop_after_presentation(
    size: tuple[int, int],
) -> None:
    compiler = SidneyPresentationCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=0x790004, height_va=0x790008),
        mouse_move_abi=MouseMoveDispatchABI(ui_dispatch_adapter_slot_va=0x792000),
    )
    base, helper, root, stack, stop = 0x800000, 0x801000, 0x802000, 0x808000, 0x809000
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x400000)
    cpu.mem_map(base, 0x10000)
    cpu.mem_write(
        base,
        build_root_draw_bridge(
            compiler,
            wrapper_va=base,
            extension_helper_va=helper,
            status_replay_helper_va=helper,
            damage_selector_va=helper,
        ),
    )
    cpu.mem_write(helper, b"\xc3")
    cpu.mem_write(GOG_BUILD.address("ui.container_draw"), b"\xc2\x08\x00")
    cpu.mem_write(root + 0x1C, struct.pack("<4I", 0, 0, *size))
    cpu.mem_write(stack, struct.pack("<3I", stop, 123, 456))
    cpu.reg_write(UC_X86_REG_ECX, root)
    cpu.reg_write(UC_X86_REG_ESP, stack)
    cpu.emu_start(base, stop, count=100)
    bounds = struct.unpack("<4I", cpu.mem_read(root + 0x1C, 16))
    assert bounds == (0, 0, 1024, 768)
    # Main Menu's authored center must survive root containment after inverse
    # input mapping; a 640x480 root incorrectly rejects this complete button.
    assert bounds[0] <= 762 < bounds[2]
    assert bounds[1] <= 604 < bounds[3]
    assert cpu.reg_read(UC_X86_REG_ESP) == stack + 12
