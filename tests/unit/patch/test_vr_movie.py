"""Movie content fits a fixed cinema without stretching or changing native data."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.vr_movie import movie_extent
from tests.unit.patch.test_complete_compilation import _source
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine

if TYPE_CHECKING:
    from unicorn import Uc


def _stack_root(machine: Uc, manager: int, root: int, state: str) -> None:
    if state not in {"deque", "previous_block"}:
        return
    block = _HEAP + 0xB000
    entries = [(manager + 0x58, 0), (manager + 0x3C, block)]
    if state == "previous_block":
        entries.extend(
            [
                (manager + 0x44, block),
                (manager + 0x48, _HEAP + 0xC004),
                (_HEAP + 0xC000, block),
                (block + 0xFF0, root),
            ]
        )
    else:
        entries.extend([(manager + 0x44, block + 16), (block, root)])
    for address, value in entries:
        machine.mem_write(address, struct.pack("<I", value))


def _run(
    canvas: tuple[int, int], rectangle: tuple[int, int, int, int], state: str = "movie"
) -> tuple[float, bytes, bytes]:
    machine = _machine(_source(GOG_BUILD))
    engine, services, manager, root, player = (_HEAP + n * 0x1000 for n in range(1, 6))
    frame, scratch, constants, operation = (_HEAP + n for n in (0x7000, 0x7100, 0x7200, 0x7300))
    entry, probe = _HEAP + 0x9000, _HEAP + 0xA000

    def word(address: int, value: int) -> None:
        machine.mem_write(address, struct.pack("<I", value))

    word(GOG_BUILD.address("engine.loop"), engine)
    word(engine + 0x444, services)
    word(services + 0x44, manager)
    word(manager + 0x58, root)
    word(root, GOG_BUILD.address("movies.layer_vtable"))
    word(root + 0x18, 0x101)
    word(root + 0x140, state != "embedded")
    word(root + 0x13C, player)
    word(player, GOG_BUILD.address("movies.bink_vtable"))
    machine.mem_write(root + 0x1C, struct.pack("<4i", *rectangle))
    machine.mem_write(player + 0x40, struct.pack("<4i", *rectangle))
    word(player + 0x50, state == "overlay")
    word(player + 0x64, state == "custom")
    if state == "different_destination":
        word(player + 0x40, 1)
    if state == "other_layer":
        word(root, GOG_BUILD.address("vr.room_layer_vtable"))
    if state == "hidden":
        word(root + 0x18, 0)
    _stack_root(machine, manager, root, state)
    machine.mem_write(frame, struct.pack("<5I2f", 188, 0, *canvas, 1, 2.4, 1.6))
    machine.mem_write(constants, struct.pack("<2f", 2.4, 1.5))
    word(operation, 2 if state == "world" else 5 if state == "subtitles" else 0)
    word(GOG_BUILD.address("win32.IsBadReadPtr"), probe)
    machine.mem_write(probe, bytes.fromhex("c2 08 00"))
    machine.mem_write(
        entry,
        movie_extent(
            GOG_BUILD,
            entry=entry,
            frame=frame,
            scratch=scratch,
            width=constants,
            height=constants + 4,
            operation=operation,
        ),
    )

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == probe:
            stack = current.reg_read(UC_X86_REG_ESP)
            pointer = struct.unpack("<I", current.mem_read(stack + 4, 4))[0]
            current.reg_write(UC_X86_REG_EAX, int(state == "unreadable" and pointer == root))

    machine.hook_add(UC_HOOK_CODE, observe)
    before = bytes(machine.mem_read(root, 0x144)) + bytes(machine.mem_read(player, 0x68))
    machine.emu_start(entry, _RETURN, count=3000)
    result = struct.unpack("<f", machine.mem_read(frame + 20, 4))[0]
    # Repeating must not compound the earlier frame's cinema enlargement.
    machine.reg_write(UC_X86_REG_ESP, _STACK)
    machine.emu_start(entry, _RETURN, count=3000)
    assert struct.unpack("<f", machine.mem_read(frame + 20, 4))[0] == result
    assert struct.unpack("<f", machine.mem_read(frame + 24, 4))[0] == pytest.approx(1.6)
    after = bytes(machine.mem_read(root, 0x144)) + bytes(machine.mem_read(player, 0x68))
    return result, before, after


@pytest.mark.parametrize("canvas", [(1280, 800), (1920, 1080), (3840, 2160)])
@pytest.mark.parametrize("extent", [(640, 480), (640, 360), (400, 600)])
@pytest.mark.parametrize("state", ["movie", "subtitles", "deque", "previous_block"])
def test_visible_movie_fits_fixed_cinema(
    canvas: tuple[int, int], extent: tuple[int, int], state: str
) -> None:
    rectangle = (0, 0, *extent)
    width, before, after = _run(canvas, rectangle, state)
    expected = canvas[0] * min(2.4 / extent[0], 1.5 / extent[1])
    assert width == pytest.approx(expected)
    assert before == after


@pytest.mark.parametrize(
    "state",
    [
        "embedded",
        "overlay",
        "custom",
        "different_destination",
        "other_layer",
        "hidden",
        "world",
        "unreadable",
    ],
)
def test_non_movie_or_unqualified_content_keeps_ordinary_size(state: str) -> None:
    width, before, after = _run((1280, 800), (0, 0, 640, 480), state)
    assert width == pytest.approx(2.4)
    assert before == after


@pytest.mark.parametrize(
    "rectangle", [(0, 0, 0, 480), (-1, 0, 640, 480), (0, 0, 1281, 480), (0, 0, 640, 801)]
)
def test_invalid_movie_rectangle_keeps_ordinary_size(rectangle: tuple[int, int, int, int]) -> None:
    width, before, after = _run((1280, 800), rectangle)
    assert width == pytest.approx(2.4)
    assert before == after
