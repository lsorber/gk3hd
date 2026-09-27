"""Full-screen movie sizing preserves the reference frame across resolutions."""

from __future__ import annotations

import struct

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_ESI, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameABI
from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.system.movies import MovieFeatureCompiler

_CODE = 0x800000
_RETURN = 0x80F000
_ROOT = 0x900100
_MOVIE = 0x901000
_SOURCE = 0x902000
_STACK = 0x90F000


def _machine(screen: tuple[int, int], source: tuple[int, int]) -> Uc:
    compiler = MovieFeatureCompiler(
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
    native = GOG_BUILD.address("movies.layout")
    setter = GOG_BUILD.address("movies.set_rect")
    for address in (_CODE, 0x900000, dimensions & ~0xFFF, native & ~0xFFF, setter & ~0xFFF):
        machine.mem_map(address, 0x10000 if address in (_CODE, 0x900000) else 0x1000)
    machine.mem_write(_CODE, compiler.build_layout(wrapper_va=_CODE))
    machine.mem_write(native, b"\xc3")
    machine.mem_write(setter, b"\xc2\x04\x00")
    machine.mem_write(dimensions, struct.pack("<II", *screen))
    machine.mem_write(_ROOT + 0x13C, struct.pack("<IB", _MOVIE, 1))
    machine.mem_write(_MOVIE, struct.pack("<I", GOG_BUILD.address("movies.bink_vtable")))
    machine.mem_write(_MOVIE + 0x54, struct.pack("<I", _SOURCE))
    machine.mem_write(_SOURCE, struct.pack("<II", *source))
    machine.mem_write(_MOVIE + 0x40, struct.pack("<iiii", 0, 0, 640, 480))

    def native_call(cpu: Uc, address: int, _size: int, _user: object) -> None:
        if address == setter:
            assert cpu.reg_read(UC_X86_REG_ECX) == _MOVIE
            stack = cpu.reg_read(UC_X86_REG_ESP)
            pointer = struct.unpack("<I", cpu.mem_read(stack + 4, 4))[0]
            cpu.mem_write(_MOVIE + 0x40, bytes(cpu.mem_read(pointer, 16)))
        if address == native:
            assert cpu.reg_read(UC_X86_REG_ECX) == _ROOT
            _, _, width, height = struct.unpack("<iiii", cpu.mem_read(_MOVIE + 0x40, 16))
            x, y = ((screen[0] - width) // 2, (screen[1] - height) // 2)
            cpu.mem_write(_ROOT + 0x1C, struct.pack("<iiii", x, y, x + width, y + height))

    machine.hook_add(UC_HOOK_CODE, native_call)
    return machine


def _layout(machine: Uc) -> tuple[int, int, int, int]:
    machine.mem_write(_STACK, struct.pack("<I", _RETURN))
    machine.reg_write(UC_X86_REG_ESP, _STACK)
    machine.reg_write(UC_X86_REG_ECX, _ROOT)
    machine.reg_write(UC_X86_REG_ESI, 0x12345678)
    machine.emu_start(_CODE, _RETURN, count=1000)
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 4
    assert machine.reg_read(UC_X86_REG_ESI) == 0x12345678
    return struct.unpack("<iiii", machine.mem_read(_ROOT + 0x1C, 16))


@pytest.mark.parametrize(
    "screen", [(1024, 768), (1280, 800), (1280, 720), (3840, 2160), (800, 1280)]
)
@pytest.mark.parametrize("source", [(320, 240), (512, 384), (640, 480), (640, 240)])
def test_movie_matches_fitted_reference_and_repeated_layout_is_stable(
    screen: tuple[int, int], source: tuple[int, int]
) -> None:
    machine = _machine(screen, source)
    doubling = 2 if source[0] <= 512 and source[1] <= 384 else 1
    scale = min(screen[0] / 1024, screen[1] / 768)
    extent = tuple(int(dimension * doubling * scale + 0.5) for dimension in source)
    if screen == (1024, 768):
        # The reference mode keeps whatever rectangle the native initializer chose.
        machine.mem_write(_MOVIE + 0x40, struct.pack("<iiii", 0, 0, *extent))
    first = _layout(machine)
    assert (first[2] - first[0], first[3] - first[1]) == extent
    assert 0 <= first[0] < first[2] <= screen[0]
    assert 0 <= first[1] < first[3] <= screen[1]
    assert _layout(machine) == first


@pytest.mark.parametrize(
    ("offset", "payload"),
    [
        (_ROOT + 0x140, b"\x00"),  # embedded
        (_ROOT + 0x13C, bytes(4)),  # no movie
        (_MOVIE, bytes(4)),  # not a Bink instance
        (_MOVIE + 0x50, b"\x01"),  # hardware overlay
        (_MOVIE + 0x64, struct.pack("<I", 1)),  # custom sizing
        (_MOVIE + 0x54, bytes(4)),  # decoder not open
        (_SOURCE, bytes(8)),  # empty dimensions
        (_SOURCE, struct.pack("<II", 2048, 1536)),  # larger than reference
    ],
)
def test_other_movie_modes_keep_native_extent(offset: int, payload: bytes) -> None:
    machine = _machine((1280, 800), (320, 240))
    machine.mem_write(offset, payload)
    left, top, right, bottom = _layout(machine)
    assert (right - left, bottom - top) == (640, 480)


def test_original_small_mode_keeps_native_extent() -> None:
    machine = _machine((800, 600), (320, 240))
    left, top, right, bottom = _layout(machine)
    assert (right - left, bottom - top) == (640, 480)
