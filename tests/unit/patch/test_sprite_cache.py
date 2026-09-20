"""Execute dense SpriteButton cache geometry, fallback and ownership adapters."""

from __future__ import annotations

import itertools
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_EFLAGS,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.runtime2d.dropdown_cache import DropdownCacheRuntime
from gk3hd.patch.definitions.runtime2d.layout import (
    FONT_BANK_ALPHA_SELECT_OFFSET,
    FONT_BANK_SEGMENT,
    INVENTORY_ALPHA_HEIGHT_OFFSET,
    INVENTORY_ALPHA_OUTPUT_RECT_OFFSET,
    INVENTORY_ALPHA_SOURCE_RECT_OFFSET,
    INVENTORY_ALPHA_WIDTH_OFFSET,
    INVENTORY_FONT_ALPHA_VTABLE_OFFSET,
    INVENTORY_SEGMENT,
    RUNTIME_SEGMENTS,
    RuntimeSegmentAddress,
    RuntimeSymbols,
)
from gk3hd.patch.definitions.runtime2d.sprite_cache import (
    CACHE_CAPACITY,
    CACHE_OFFSET,
    CACHE_STRIDE,
    STATE_OFFSET,
    SpriteCacheRuntime,
)
from gk3hd.patch.definitions.runtime2d.styled_cache import StyledTextCacheRuntime

BASE, TARGET, STOP = 0x100000, 0x109000, 0x10A000
DATA, STACK = 0x200000, 0x308000
KEY, NATIVE, DENSE, RESOURCE, DENSE_RESOURCE = (DATA + i * 256 for i in range(5))
MANAGER, TABLE, DEST, SOURCE_RECT, DEST_RECT, POINT = (DATA + i * 256 for i in range(8, 14))
RECORD = BASE + CACHE_OFFSET
ACTIVE_FONT = DATA + 0xE00
EFFECT = DATA + 0xF00
PRESERVED = (UC_X86_REG_EBX, UC_X86_REG_EBP, UC_X86_REG_ESI, UC_X86_REG_EDI)


def put(cpu: Uc, address: int, *values: int) -> None:
    cpu.mem_write(address, struct.pack("<" + "I" * len(values), *(v & 0xFFFFFFFF for v in values)))


def words(cpu: Uc, address: int, count: int) -> tuple[int, ...]:
    return struct.unpack("<" + "I" * count, cpu.mem_read(address, count * 4))


def fixture() -> tuple[Uc, list[tuple[int, tuple[int, ...], tuple[int, ...]]]]:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    for start, length in (
        (BASE, 0x10000),
        (DATA, 0x10000),
        (0x300000, 0x10000),
        (0x400000, 0x320000),
    ):
        cpu.mem_map(start, length)
    runtime = SpriteCacheRuntime(BASE, TARGET, GOG_BUILD, ACTIVE_FONT)
    for offset, builder in (
        (0x100, runtime.paint),
        (0x800, runtime.point),
        (0x1000, runtime.transfer),
        (0x1800, runtime.release),
        (0x2000, runtime.assign),
    ):
        cpu.mem_write(BASE + offset, builder())
    cpu.mem_write(BASE + 0x500, runtime.paint(offset=0x500))
    cpu.mem_write(TARGET, bytes.fromhex("b878563412 c20c00"))
    put(cpu, GOG_BUILD.address("bitmap.manager"), MANAGER)
    put(cpu, MANAGER + 0x120, TABLE, 16)
    put(cpu, TABLE + 4, RESOURCE, DENSE_RESOURCE)
    calls: list[tuple[int, tuple[int, ...], tuple[int, ...]]] = []

    def capture(machine: Uc, address: int, _size: int, _user: object) -> None:
        if address == TARGET:
            source, dest_rect, source_rect = words(machine, machine.reg_read(UC_X86_REG_ESP) + 4, 3)
            calls.append((source, words(machine, dest_rect, 4), words(machine, source_rect, 4)))

    cpu.hook_add(UC_HOOK_CODE, capture)
    return cpu, calls


def reset(cpu: Uc) -> None:
    put(cpu, ACTIVE_FONT, 0)
    put(cpu, BASE + STATE_OFFSET, 0, 0, 0, 0, 0)
    put(cpu, KEY, 0x10001)
    put(cpu, RECORD, KEY, KEY - 0xAC, 0x10001, 0x20002, NATIVE, DENSE, RESOURCE, 1)
    put(cpu, TABLE + 4, RESOURCE, DENSE_RESOURCE)
    put(cpu, RESOURCE + 0x30, NATIVE)
    put(cpu, DENSE_RESOURCE + 0x30, DENSE)
    put(cpu, NATIVE + 0x38, 112, 13)
    put(cpu, DENSE + 0x38, 448, 52)
    put(cpu, SOURCE_RECT, 0, 0, 112, 13)


def execute(cpu: Uc, entry: int, receiver: int, *args: int) -> None:
    put(cpu, STACK, STOP, *args)
    cpu.reg_write(UC_X86_REG_ESP, STACK)
    cpu.reg_write(UC_X86_REG_ECX, receiver)
    cpu.reg_write(UC_X86_REG_EDX, 0x7788)
    cpu.reg_write(UC_X86_REG_EFLAGS, 0x246)
    for index, register in enumerate(PRESERVED):
        cpu.reg_write(register, 0xAB00 + index)
    cpu.emu_start(entry, STOP, count=50000)
    assert cpu.reg_read(UC_X86_REG_ESP) == STACK + 4 * (len(args) + 1)
    assert all(cpu.reg_read(register) == 0xAB00 + index for index, register in enumerate(PRESERVED))


def check_transfers() -> None:
    cpu, calls = fixture()
    faults = {
        "generation": (KEY, 0x30001),
        "resource": (TABLE + 4, DENSE_RESOURCE),
        "surface": (RESOURCE + 0x30, DENSE),
        "dense": (DENSE_RESOURCE + 0x30, NATIVE),
        "size": (DENSE + 0x38, 447),
        "unready": (RECORD + 28, 0),
        "bounds": (SOURCE_RECT, 0, 0, 113, 13),
        "empty": (TABLE + 4, 0),
        "negative-source": (SOURCE_RECT, -1, 0, 112, 13),
        "empty-source": (SOURCE_RECT, 0, 0, 0, 13),
        "inverted-source": (SOURCE_RECT, 20, 0, 10, 13),
    }
    for factor, fault in itertools.product(
        (0.5, 1, 2, 4),
        ("", *faults),
    ):
        reset(cpu)
        rect = (40, 50, 40 + int(112 * factor), 50 + int(13 * factor))
        put(cpu, DEST_RECT, *rect)
        if fault:
            address, *values = faults[fault]
            put(cpu, address, *values)
        source = words(cpu, SOURCE_RECT, 4)
        calls.clear()
        execute(cpu, BASE + 0x1000, DEST, NATIVE, DEST_RECT, SOURCE_RECT)
        use_dense = not fault and factor > 1
        assert calls == [
            (
                DENSE if use_dense else NATIVE,
                rect,
                tuple(v * 4 for v in source) if use_dense else source,
            )
        ], (factor, fault, calls)
        assert words(cpu, SOURCE_RECT, 4) == source
        assert words(cpu, DEST_RECT, 4) == rect
        assert cpu.reg_read(UC_X86_REG_EAX) == 0x12345678
    # A dense cache allocation is not itself permission to scale every draw.
    reset(cpu)
    put(cpu, BASE + STATE_OFFSET + 4, DENSE)
    put(cpu, DEST_RECT, 216, 4, 222, 14)
    calls.clear()
    execute(cpu, BASE + 0x1000, DENSE, NATIVE, DEST_RECT, SOURCE_RECT)
    assert calls[0][1] == (216, 4, 240, 44)
    assert words(cpu, DEST_RECT, 4) == (216, 4, 222, 14)
    # Alpha scratch is already composed at 4x. Only direct font surfaces still
    # need their destination extent transformed at the final transfer.
    for handle, source, expected in (
        (0x10001, NATIVE, (216, 4, 240, 44)),
        (0x10001, DEST, (216, 4, 222, 14)),
        (0x10010, DEST, (216, 4, 240, 44)),  # Invalid resource: ordinary path.
        (0, DEST, (216, 4, 240, 44)),
    ):
        put(cpu, ACTIVE_FONT, handle)
        calls.clear()
        execute(cpu, BASE + 0x1000, DENSE, source, DEST_RECT, SOURCE_RECT)
        assert calls[0][1] == expected


def check_points() -> None:
    cpu, _ = fixture()
    cpu.mem_write(BASE + 0x2840, bytes.fromhex("b878563412 c21400"))
    calls: list[tuple[int, ...]] = []

    def capture(machine: Uc, address: int, _size: int, _user: object) -> None:
        if address == BASE + 0x2840:
            args = words(machine, machine.reg_read(UC_X86_REG_ESP) + 4, 5)
            calls.append((*args[:2], *words(machine, args[2], 2), *args[3:]))

    cpu.hook_add(UC_HOOK_CODE, capture)
    for active in (0, 7, 8):
        put(cpu, BASE + STATE_OFFSET, active)
        put(cpu, POINT, 54, 1)
        calls.clear()
        execute(cpu, BASE + 0x800, MANAGER, 7, 11, POINT, SOURCE_RECT, 123)
        scale = 4 if active == 7 else 1
        assert calls == [(7, 11, 54 * scale, scale, SOURCE_RECT, 123)]
        assert words(cpu, POINT, 2) == (54, 1)


def check_construction_clipping() -> None:
    cpu, calls = fixture()
    for size, dest, source, expected in (
        ((312, 52), (308, 0, 310, 13), (0, 0, 8, 52), ((308, 0, 312, 52), (0, 0, 4, 52))),
        ((312, 52), (308, 0, 310, 13), (0, 0, 2, 13), ((308, 0, 312, 52), (0, 0, 1, 13))),
        ((312, 52), (4, 48, 6, 50), (8, 12, 16, 20), ((4, 48, 12, 52), (8, 12, 16, 16))),
        ((312, 52), (308, 48, 310, 50), (8, 12, 16, 20), ((308, 48, 312, 52), (8, 12, 12, 16))),
        ((312, 52), (312, 0, 314, 2), (0, 0, 8, 8), None),
        ((312, 52), (0, 52, 2, 54), (0, 0, 8, 8), None),
        # Exercise the high half of MUL, not a wrapped 32-bit product.
        (
            (4096, 52),
            (0, 0, 2048, 2),
            (0, 0, 2000000000, 8),
            ((0, 0, 4096, 8), (0, 0, 1000000000, 8)),
        ),
    ):
        reset(cpu)
        put(cpu, BASE + STATE_OFFSET + 4, DENSE)
        put(cpu, DENSE + 0x38, *size)
        put(cpu, DEST_RECT, *dest)
        put(cpu, SOURCE_RECT, *source)
        calls.clear()
        execute(cpu, BASE + 0x1000, DENSE, NATIVE, DEST_RECT, SOURCE_RECT)
        assert calls == ([] if expected is None else [(NATIVE, *expected)])
        assert words(cpu, DEST_RECT, 4) == dest
        assert words(cpu, SOURCE_RECT, 4) == source
        assert cpu.reg_read(UC_X86_REG_EAX) == (0 if expected is None else 0x12345678)
        assert cpu.reg_read(UC_X86_REG_EFLAGS) == 0x246


def check_dropdown_bridge() -> None:
    cpu, _ = fixture()
    runtime = DropdownCacheRuntime(BASE)
    owner, selected = DATA + 0x1800, DATA + 0x1900
    cpu.mem_write(BASE + 0x3500, runtime.entry())
    cpu.mem_write(BASE + 0x3600, runtime.paint_bridge())
    cpu.mem_write(BASE + 0x3100, bytes.fromhex("b878563412 c20800"))
    cpu.mem_write(BASE + 0x3700, bytes.fromhex("b878563412 c3"))
    put(cpu, owner + 0x60, 0x10001, 0x20002)
    put(cpu, selected, 0x30003)
    calls: list[tuple[int, ...]] = []

    def capture(machine: Uc, address: int, _size: int, _user: object) -> None:
        receiver = machine.reg_read(UC_X86_REG_ECX)
        if address == BASE + 0x3100:
            calls.append((receiver, *words(machine, machine.reg_read(UC_X86_REG_ESP) + 4, 2)))
        elif address == BASE + 0x3700:
            calls.append((receiver, *words(machine, owner + 0x60, 2)))

    cpu.hook_add(UC_HOOK_CODE, capture)
    execute(cpu, BASE + 0x3500, owner)
    assert calls == [(owner, owner + 0x60, 0x60), (owner, owner + 0x64, 0x64)]
    for offset in (0x60, 0x64):
        for pointer in (owner + offset, selected):
            calls.clear()
            execute(cpu, BASE + 0x3600, owner, pointer, offset)
            expected = [0x10001, 0x20002]
            if pointer == selected:
                expected[(offset - 0x60) // 4] = 0x30003
            assert calls == [(owner, *expected)]
            assert words(cpu, owner + 0x60, 2) == (0x10001, 0x20002)
            assert cpu.reg_read(UC_X86_REG_EAX) == 0x12345678


def check_release() -> None:
    cpu, _ = fixture()
    native_release = BASE + 0x28C0
    native_assign = GOG_BUILD.address("sprite_cache.assign")
    cpu.mem_write(native_release, bytes.fromhex("b878563412 c3"))
    cpu.mem_write(native_assign, bytes.fromhex("b878563412 c20400"))
    calls: list[tuple[int, int, int]] = []

    def capture(machine: Uc, address: int, _size: int, _user: object) -> None:
        if address in (native_release, native_assign):
            receiver = machine.reg_read(UC_X86_REG_ECX)
            calls.append((address, receiver, words(machine, RECORD, 1)[0]))

    cpu.hook_add(UC_HOOK_CODE, capture)
    for entry, target in ((BASE + 0x1800, native_release), (BASE + 0x2000, native_assign)):
        for owned in (True, False):
            reset(cpu)
            calls.clear()
            receiver = KEY if owned else KEY + 4
            execute(cpu, entry, receiver, *((0,) if entry == BASE + 0x2000 else ()))
            assert calls == ([(native_release, RECORD + 12, 0)] if owned else []) + [
                (target, receiver, 0 if owned else KEY)
            ]
            assert words(cpu, RECORD, 8) == (
                (0,) * 8
                if owned
                else (KEY, KEY - 0xAC, 0x10001, 0x20002, NATIVE, DENSE, RESOURCE, 1)
            )


def capture_paint(
    machine: Uc, address: int, _size: int, user: tuple[str, list[tuple[str, tuple[int, ...]]]]
) -> None:
    case, calls = user
    stack = machine.reg_read(UC_X86_REG_ESP) + 4
    if address == BASE + 0x2800:
        pointer, state = words(machine, stack, 2)
        calls.append(("paint", (pointer, state, *words(machine, BASE + STATE_OFFSET, 2))))
        if pointer != KEY:
            assert words(machine, pointer + 16, 1) == (0,)  # Not published until complete.
    elif address == GOG_BUILD.address("sprite_cache.resolve"):
        handle = words(machine, stack, 1)[0]
        machine.reg_write(UC_X86_REG_EAX, RESOURCE if handle == 0x10001 else DENSE_RESOURCE)
    elif address == GOG_BUILD.address("sprite_cache.allocate"):
        pointer = machine.reg_read(UC_X86_REG_ECX)
        calls.append(("allocate", words(machine, stack + 4, 3)))
        put(machine, pointer, 0 if case == "failed-allocation" else 0x20002)


def check_paint(*, styled: bool = False) -> None:
    """Keep logical metrics, reuse records past holes, and restore nested scope."""
    for case in ("existing", "hole", "new", "full", "failed-allocation", "empty-native"):
        cpu, _ = fixture()
        reset(cpu)
        entry = BASE + (0x500 if styled else 0x100)
        cpu.mem_write(BASE + 0x2800, bytes.fromhex("b878563412 c20800"))
        for symbol, cleanup in (("allocate", 16), ("resolve", 4), ("dimensions", 4)):
            cpu.mem_write(GOG_BUILD.address(f"sprite_cache.{symbol}"), bytes((0xC2, cleanup, 0)))
        if case == "hole":
            cpu.mem_write(RECORD + 5 * CACHE_STRIDE, bytes(cpu.mem_read(RECORD, CACHE_STRIDE)))
            cpu.mem_write(RECORD, bytes(CACHE_STRIDE))
        elif case == "new":
            cpu.mem_write(RECORD, bytes(CACHE_STRIDE))
        elif case == "full":
            for index in range(CACHE_CAPACITY):
                put(cpu, RECORD + index * CACHE_STRIDE, KEY + 4 + index * 4)
        elif case == "empty-native":
            put(cpu, KEY, 0)
        put(cpu, BASE + STATE_OFFSET, 33, DEST)
        calls: list[tuple[str, tuple[int, ...]]] = []

        cpu.hook_add(UC_HOOK_CODE, capture_paint, (case, calls))
        execute(cpu, entry, KEY - 0xAC, KEY, 1)
        assert calls[0] == ("paint", (KEY, 1, 33, DEST))
        assert words(cpu, BASE + STATE_OFFSET, 2) == (33, DEST)
        assert cpu.reg_read(UC_X86_REG_EAX) == 0x12345678
        if case in ("full", "empty-native"):
            assert len(calls) == 1
        elif case == "failed-allocation":
            assert calls[1] == ("allocate", (448, 52, 0))
            assert len(calls) == 2
            assert words(cpu, RECORD + 28, 1) == (0,)
        else:
            assert calls[1] == ("allocate", (448, 52, 0))
            expected = RECORD + (
                5 * CACHE_STRIDE
                if case == "hole"
                else (CACHE_CAPACITY - 1) * CACHE_STRIDE
                if case == "new"
                else 0
            )
            assert calls[2] == ("paint", (expected + 12, 1, 0x20002, DENSE))
            assert words(cpu, expected + 28, 1) == (1,)
            assert len(calls) == 3


def styled_fixture() -> tuple[Uc, StyledTextCacheRuntime]:
    cpu, _ = fixture()
    cpu.mem_map(0x800000, 0x40000)
    symbols = RuntimeSymbols(
        tuple(
            RuntimeSegmentAddress(
                segment, segment.offset, segment.offset, 0x800000 + segment.offset
            )
            for segment in RUNTIME_SEGMENTS
        )
    )
    runtime = StyledTextCacheRuntime(BASE, BASE + STATE_OFFSET + 4, GOG_BUILD, symbols)
    cpu.mem_write(BASE + 0x40, runtime.entry())
    cpu.mem_write(BASE + 0x2200, runtime.alpha_constructor())
    cpu.mem_write(BASE + 0x2600, runtime.paint_bridge())
    return cpu, runtime


def check_paint_limits() -> None:
    for entry, dimensions in itertools.product(
        (BASE + 0x100, BASE + 0x500),
        ((0, 13), (112, 0), (2049, 13), (112, 2049), (0xFFFFFFFF, 13)),
    ):
        cpu, _ = fixture()
        reset(cpu)
        put(cpu, NATIVE + 0x38, *dimensions)
        put(cpu, BASE + STATE_OFFSET, 33, DEST)
        cpu.mem_write(BASE + 0x2800, bytes.fromhex("b878563412 c20800"))
        cpu.mem_write(GOG_BUILD.address("sprite_cache.resolve"), bytes.fromhex("c20400"))
        calls: list[tuple[str, tuple[int, ...]]] = []
        cpu.hook_add(UC_HOOK_CODE, capture_paint, ("invalid-dimensions", calls))
        # No allocator stub: reaching allocation fails execution immediately.
        execute(cpu, entry, KEY - 0x74, KEY, 1)
        assert calls == [("paint", (KEY, 1, 33, DEST))]
        assert words(cpu, BASE + STATE_OFFSET, 2) == (33, DEST)
        assert cpu.reg_read(UC_X86_REG_EAX) == 0x12345678


def check_styled_bridge() -> None:
    cpu, _ = styled_fixture()
    calls: list[tuple[int, tuple[int, ...]]] = []
    put(cpu, KEY, 0x10001)
    put(cpu, GOG_BUILD.address("engine.loop"), MANAGER)
    for address, cleanup in (
        (BASE + 0x500, 8),
        (GOG_BUILD.address("runtime2d.fill_rect"), 16),
        (GOG_BUILD.address("sprite_cache.styled_paint"), 4),
    ):
        cpu.mem_write(address, bytes.fromhex("b878563412") + bytes((0xC2, cleanup, 0)))

    def capture(machine: Uc, address: int, _size: int, _user: object) -> None:
        argc = {
            BASE + 0x500: 2,
            GOG_BUILD.address("runtime2d.fill_rect"): 4,
            GOG_BUILD.address("sprite_cache.styled_paint"): 1,
        }.get(address)
        if argc:
            calls.append(
                (
                    machine.reg_read(UC_X86_REG_ECX),
                    words(machine, machine.reg_read(UC_X86_REG_ESP) + 4, argc),
                )
            )

    cpu.hook_add(UC_HOOK_CODE, capture)
    execute(cpu, BASE + 0x40, KEY - 0x74, 0x10001)
    assert calls == [(KEY - 0x74, (KEY, 0))]
    calls.clear()
    execute(cpu, BASE + 0x2600, KEY - 0x74, KEY, 0)
    assert calls == [(MANAGER, (0x10001, 0, 0, 0x3F800000)), (KEY - 0x74, (0x10001,))]
    assert cpu.reg_read(UC_X86_REG_EAX) == 0x12345678


def check_styled_alpha() -> None:
    cpu, runtime = styled_fixture()
    inv = runtime.symbols.va(INVENTORY_SEGMENT.logical_name)
    selector = runtime.symbols.va(FONT_BANK_SEGMENT.logical_name, FONT_BANK_ALPHA_SELECT_OFFSET)
    cpu.mem_write(selector, bytes.fromhex("c20c00"))
    cpu.mem_write(BASE + 0x2880, bytes.fromhex("b878563412 c21400"))
    calls: list[tuple[int, ...]] = []
    selections: list[tuple[int, ...]] = []

    def capture(machine: Uc, address: int, _size: int, _user: object) -> None:
        stack = machine.reg_read(UC_X86_REG_ESP) + 4
        if address == selector:
            source, destination, source_rect = words(machine, stack, 3)
            selections.append((source, *words(machine, destination, 4)))
            rect = words(machine, source_rect, 4)
            # Simulate the already independently tested bank selector. Native
            # sources are untouched; signed dense sources select the detail bank.
            if words(machine, ACTIVE_FONT, 1)[0]:
                rect = (rect[0] + 1964, rect[1], rect[2] + 1964, rect[3])
            put(machine, machine.reg_read(UC_X86_REG_ECX), *rect)
        elif address == BASE + 0x2880:
            dest, source, dest_rect, source_rect, options = words(machine, stack, 5)
            calls.append(
                (
                    dest,
                    source,
                    options,
                    machine.reg_read(UC_X86_REG_ECX),
                    *words(machine, dest_rect, 4),
                    *words(machine, source_rect, 4),
                )
            )

    cpu.hook_add(UC_HOOK_CODE, capture)
    for active, dense, origin in itertools.product((0, DEST, DENSE), (False, True), (20, -4)):
        reset(cpu)
        put(cpu, BASE + STATE_OFFSET + 4, active)
        put(cpu, ACTIVE_FONT, int(dense))
        put(cpu, EFFECT, 0x1111)
        dest_rect = (origin & 0xFFFFFFFF, 40, origin + 8, 56)
        source_rect = (100, 4, 132, 68) if dense else (25, 1, 33, 17)
        put(cpu, DEST_RECT, *dest_rect)
        put(cpu, SOURCE_RECT, *source_rect)
        calls.clear()
        selections.clear()
        execute(cpu, BASE + 0x2200, EFFECT, DEST, NATIVE, DEST_RECT, SOURCE_RECT, 0xABCDEF)
        owned = active == DEST
        expected_dest = (origin & 0xFFFFFFFF, 40, origin + 32, 104) if owned else dest_rect
        expected_source = (
            (source_rect[0] + 1964, source_rect[1], source_rect[2] + 1964, source_rect[3])
            if owned and dense
            else source_rect
        )
        assert calls == [(DEST, NATIVE, 0xABCDEF, EFFECT, *expected_dest, *expected_source)]
        assert selections == ([(NATIVE, *expected_dest)] if owned else [])
        assert words(cpu, DEST_RECT, 4) == dest_rect
        assert words(cpu, SOURCE_RECT, 4) == source_rect
        assert words(cpu, EFFECT, 1) == (
            inv + INVENTORY_FONT_ALPHA_VTABLE_OFFSET if owned else 0x1111,
        )
        assert cpu.reg_read(UC_X86_REG_EAX) == 0x12345678
        assert cpu.reg_read(UC_X86_REG_EFLAGS) == 0x246
        if owned:
            assert words(cpu, inv + INVENTORY_ALPHA_OUTPUT_RECT_OFFSET, 4) == expected_dest
            assert words(cpu, inv + INVENTORY_ALPHA_SOURCE_RECT_OFFSET, 4) == expected_source
            assert words(cpu, inv + INVENTORY_ALPHA_WIDTH_OFFSET, 1) == (32,)
            assert words(cpu, inv + INVENTORY_ALPHA_HEIGHT_OFFSET, 1) == (64,)


@pytest.mark.slow
def test_executed_sprite_cache() -> None:
    subprocess.run(  # noqa: S603 - fixed interpreter and this test module.
        [sys.executable, str(Path(__file__).resolve())],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )


if __name__ == "__main__":
    check_transfers()
    check_construction_clipping()
    check_dropdown_bridge()
    check_points()
    check_release()
    check_paint()
    check_paint(styled=True)
    check_paint_limits()
    check_styled_bridge()
    check_styled_alpha()
