"""Execute caption-owned font mapping through the real shared blit dispatcher."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest
from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.binary.x86 import X86Emitter
from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.runtime2d.layout import (
    CAPTION_GLYPH_RECORDER_OFFSET,
    CAPTION_SEGMENT,
    RuntimeImage,
)
from gk3hd.patch.definitions.runtime2d.system import SystemScreenCompiler
from gk3hd.patch.definitions.runtime2d.system.blit_dispatch import BlitDispatchCompiler
from tests.unit.patch.test_complete_compilation import _source
from tests.unit.patch.test_registry import _caption_compiler

if TYPE_CHECKING:
    from collections.abc import Mapping

_FONT, _BLIT, _POINT_HELPER, _UNION, _NATIVE, _STOP = range(0x880000, 0x886000, 0x1000)
_STATE, _OBJECT, _POINT, _DEST, _SOURCE, _EFFECT, _SURFACE, _STACK = range(
    0x900000, 0x908000, 0x1000
)
_ACTIVE, _VALID, _BOUNDS = _STATE + 0xC00, _STATE + 0xC04, _STATE + 0xC10
_REGISTERS = {
    UC_X86_REG_EBX: 123,
    UC_X86_REG_EBP: 456,
    UC_X86_REG_ESI: 789,
    UC_X86_REG_EDI: 1011,
    UC_X86_REG_EDX: 1213,
    UC_X86_REG_ECX: _SURFACE,
}


def _write(cpu: Uc, address: int, *values: int) -> None:
    cpu.mem_write(address, struct.pack(f"<{len(values)}I", *(v & 0xFFFFFFFF for v in values)))


def _read(cpu: Uc, address: int, count: int) -> tuple[int, ...]:
    return struct.unpack(f"<{count}i", cpu.mem_read(address, count * 4))


def _machine() -> tuple[Uc, Mapping[str, int], list[tuple[int, ...]], list[tuple[int, ...]]]:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x600000)
    caption = _caption_compiler()
    symbols = RuntimeImage(_source(GOG_BUILD)).prepare()
    system = SystemScreenCompiler(
        symbols=symbols,
        profile=caption.profile,
        room_rendering_abi=caption.room_rendering_abi,
        transition_abi=caption.transition_abi,
    )
    names = (
        "render_depth_va",
        "input_active_va",
        "transform_mode_va",
        "root_ptr_va",
        "clear_pending_va",
        "transform_count_va",
        "composite_surface_va",
        "source_rect_va",
        "target_rect_va",
        "dest_rect_va",
        "bltfx_va",
        "left_bar_rect_va",
        "right_bar_rect_va",
        "hud_font_active_va",
        "hud_font_point_va",
        "hud_transform_count_va",
        "hud_last_rect_va",
        "hd_font_active_va",
        "hd_font_source_rect_va",
        "hd_font_source_transform_count_va",
        "toolbar_blt_helper_va",
        "loadsave_background_helper_va",
        "cursor_surface_classifier_va",
        "tooltip_draw_depth_va",
        "tooltip_transfer_affine_va",
        "binocs_local_blt_helper_va",
        "hud_font_transform_count_va",
        "hd_font_handle_count_va",
        "hd_font_handles_va",
        "room_status_present_depth_va",
        "font_rect_helper_va",
    )
    state = {name: _STATE + index * 0x40 for index, name in enumerate(names)}
    blit = BlitDispatchCompiler(
        symbols=symbols,
        profile=caption.profile,
        room_rendering_abi=caption.room_rendering_abi,
        transition_abi=caption.transition_abi,
    ).build_blt_wrapper(
        wrapper_va=_BLIT, downstream_va=_NATIVE, **{name: state[name] for name in names[:26]}
    )
    font = system.load_save_feature().build_loadsave_font_wrapper(
        wrapper_va=_FONT,
        caption_point_helper_va=_POINT_HELPER,
        hud_font_last_point_va=state["hud_font_point_va"],
        **{
            name: state[name]
            for name in (
                "root_ptr_va",
                "font_rect_helper_va",
                "hud_font_active_va",
                "hud_font_transform_count_va",
                "hd_font_active_va",
                "hd_font_handle_count_va",
                "hd_font_handles_va",
                "room_status_present_depth_va",
            )
        },
    )
    recorder = symbols.va(CAPTION_SEGMENT.logical_name, CAPTION_GLYPH_RECORDER_OFFSET)
    # Other interface classifiers decline. The font/dispatcher/recorder/union
    # under test execute their real emitted instructions, not Python mocks.
    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    for base, body in ((_FONT, font), (_BLIT, blit)):
        for instruction in decoder.disasm(body, base):
            if instruction.mnemonic == "call" and instruction.op_str.startswith("0x"):
                cpu.mem_write(int(instruction.op_str, 16), bytes.fromhex("31c0 f8 c3"))
    cpu.mem_write(_FONT, font)
    cpu.mem_write(_BLIT, blit)
    cpu.mem_write(
        _POINT_HELPER, caption._build_font_point(wrapper_va=_POINT_HELPER, active_object_va=_ACTIVE)
    )
    cpu.mem_write(
        recorder,
        caption._build_glyph_recorder(
            wrapper_va=recorder,
            active_object_va=_ACTIVE,
            glyph_rect_valid_va=_VALID,
            glyph_rect_va=_BOUNDS,
            damage_record_helper_va=_UNION,
            font_active_va=state["hud_font_active_va"],
        ),
    )
    cpu.mem_write(_UNION, caption._build_damage_record_helper(wrapper_va=_UNION))
    native_font = system._font_blt_target_va
    stub = X86Emitter(base_va=native_font)
    for value in (_SOURCE, _DEST, 77):
        stub.raw(b"\x68" + struct.pack("<I", value))
    stub.call_absolute(_BLIT)
    stub.raw(bytes.fromhex("b878563412 c21400"))
    cpu.mem_write(native_font, stub.build())
    cpu.mem_write(_NATIVE, bytes.fromhex("c20c00"))
    font_points: list[tuple[int, ...]] = []
    final_rects: list[tuple[int, ...]] = []

    def observe(machine: Uc, address: int, _size: int, _user: object) -> None:
        stack = machine.reg_read(UC_X86_REG_ESP)
        if address == native_font:
            args = _read(machine, stack + 4, 5)
            assert args[:2] == (55, 77)
            assert args[3:] == (_SOURCE, _EFFECT)
            point = _read(machine, args[2], 2)
            font_points.append(point)
            _write(machine, _DEST, *point, point[0] + 11, point[1] + 17)
        elif address == _NATIVE:
            source, rect, atlas = _read(machine, stack + 4, 3)
            assert (source, atlas) == (77, _SOURCE)
            assert machine.reg_read(UC_X86_REG_ECX) == _SURFACE
            final_rects.append(_read(machine, rect, 4))

    cpu.hook_add(UC_HOOK_CODE, observe)
    return cpu, state, font_points, final_rects


@pytest.mark.parametrize("display", [(1024, 768), (1280, 800), (1920, 1080), (3840, 2160)])
@pytest.mark.parametrize("bottom_offset", [0, 17, 34])
@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("cursor", [False, True])
def test_caption_glyphs_keep_native_inputs_and_record_only_owned_final_geometry(
    display: tuple[int, int], bottom_offset: int, *, owned: bool, cursor: bool
) -> None:
    cpu, state, points, rectangles = _machine()
    width, height = display
    native_point = (width // 2 - 41, height - bottom_offset - 19)
    _write(cpu, GOG_BUILD.address("display.dimensions"), width, height)
    _write(cpu, _SURFACE + 0x38, width, height)
    _write(
        cpu,
        _OBJECT + 0x1C,
        width // 2 - 50,
        height - bottom_offset - 20,
        width // 2 + 50,
        height - bottom_offset,
    )
    _write(cpu, _ACTIVE, _OBJECT if owned else 0)
    _write(cpu, _POINT, *native_point)
    _write(cpu, _SOURCE, 13, 19, 24, 36)
    _write(cpu, _EFFECT, 1, 0x3F800000, 0x3F000000, 0, 0)
    if cursor:
        # Cursor identity bypasses recording even while native font scope is live.
        cpu.mem_write(state["cursor_surface_classifier_va"], bytes.fromhex("b801000000 c3"))
    outer = (0, 0xAABB, 314, 271)
    for address, value in zip(
        (
            state["hud_font_active_va"],
            state["hd_font_active_va"],
            state["hud_font_point_va"],
            state["hud_font_point_va"] + 4,
        ),
        outer,
        strict=True,
    ):
        _write(cpu, address, value)
    for register, value in _REGISTERS.items():
        cpu.reg_write(register, value)
    _write(cpu, _STACK, _STOP, 55, 77, _POINT, _SOURCE, _EFFECT)
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    original_object = bytes(cpu.mem_read(_OBJECT, 0x30))
    original_effect = bytes(cpu.mem_read(_EFFECT, 20))
    cpu.emu_start(_FONT, _STOP, count=10000)
    mapped = (
        width // 2 + int(-41 * height / 768),
        height + int((-19 - bottom_offset) * height / 768),
    )
    point = mapped if owned else native_point
    expected = (
        *point,
        point[0] + (11 * height // 768 if owned and not cursor else 11),
        point[1] + (17 * height // 768 if owned and not cursor else 17),
    )
    assert points == [point]
    assert rectangles == [expected]
    assert _read(cpu, _VALID, 1) == (int(owned and not cursor),)
    if owned and not cursor:
        assert _read(cpu, _BOUNDS, 4) == expected
    assert _read(cpu, _POINT, 2) == native_point
    assert _read(cpu, _SOURCE, 4) == (13, 19, 24, 36)
    assert bytes(cpu.mem_read(_OBJECT, 0x30)) == original_object
    assert bytes(cpu.mem_read(_EFFECT, 20)) == original_effect
    assert _read(cpu, state["hud_font_active_va"], 1) == outer[:1]
    assert _read(cpu, state["hd_font_active_va"], 1) == outer[1:2]
    assert _read(cpu, state["hud_font_point_va"], 2) == outer[2:]
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 24
    assert cpu.reg_read(UC_X86_REG_EAX) == 0x12345678
    assert all(cpu.reg_read(register) == value for register, value in _REGISTERS.items())


@pytest.mark.parametrize("height", [480, 768, 800, 1080, 2160, 4000, 0, -1])
@pytest.mark.parametrize("line_count", [0, 1, 3, 20])
def test_caption_layout_wraps_in_font_units_and_keeps_native_line_origins(
    height: int, line_count: int
) -> None:
    """Construction keeps the physical centre and the native layout's line breaks."""
    compiler = _caption_compiler()
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x600000)
    cpu.mem_write(_FONT, compiler._build_initial_layout(wrapper_va=_FONT))
    native = compiler.profile.address("caption.layout")
    cpu.mem_write(native, b"\xc3")
    width = 10_000_000 if height == 4000 else 3840
    bottom = max(768, height)
    _write(cpu, GOG_BUILD.address("display.dimensions"), width, height)
    _write(cpu, _OBJECT + 0xF4, 0, width, 0, bottom)
    untouched_lines = tuple(range(100, 120))
    _write(cpu, _OBJECT + 0xA4, *untouched_lines)
    _write(cpu, _STACK, _STOP)
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    for register, value in _REGISTERS.items():
        cpu.reg_write(register, value)
    cpu.reg_write(UC_X86_REG_ECX, _OBJECT)
    native_calls = []

    def native_layout(machine: Uc, address: int, _size: int, _user: object) -> None:
        if address != native:
            return
        assert machine.reg_read(UC_X86_REG_ECX) == _OBJECT
        native_calls.append(_read(machine, _OBJECT + 0xF8, 3))
        # Model only the native routine's published layout result. The adapter
        # must not synthesize another wrapping algorithm or alter these breaks.
        _write(machine, _OBJECT + 0x50, line_count)
        _write(machine, _OBJECT + 0xA4, *untouched_lines[:line_count])
        _write(machine, _OBJECT + 0x54, *range(31, 51))
        # Void layout still has native caller-clobbered register side effects.
        machine.reg_write(UC_X86_REG_EAX, 0xAABB)
        machine.reg_write(UC_X86_REG_EDX, 0xCCDD)
        machine.reg_write(UC_X86_REG_ECX, 0xEEFF)

    cpu.hook_add(UC_HOOK_CODE, native_layout)
    cpu.emu_start(_FONT, _STOP, count=10000)
    logical_width = max(1, width * 768 // height) if height > 0 else width
    delta = (width - logical_width) // 2
    assert native_calls == [(logical_width, delta, bottom)]
    assert _read(cpu, _OBJECT + 0xA4, 20) == tuple(
        value + (delta if index < line_count else 0) for index, value in enumerate(untouched_lines)
    )
    assert _read(cpu, _OBJECT + 0x54, 20) == tuple(range(31, 51))
    assert _read(cpu, _OBJECT + 0x100, 1) == (bottom,)
    assert abs(delta + logical_width // 2 - width // 2) <= 1
    assert _read(cpu, GOG_BUILD.address("display.dimensions"), 2) == (width, height)
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 4
    assert cpu.reg_read(UC_X86_REG_EAX) == 0xAABB
    assert cpu.reg_read(UC_X86_REG_EDX) == 0xCCDD
    assert cpu.reg_read(UC_X86_REG_ECX) == 0xEEFF
    assert all(
        cpu.reg_read(register) == value
        for register, value in _REGISTERS.items()
        if register not in (UC_X86_REG_ECX, UC_X86_REG_EDX)
    )
