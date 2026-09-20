"""Execute the cursor effect dispatcher's native ABI and fallback contracts."""

from __future__ import annotations

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
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.runtime2d.inventory_alpha import build_native_alpha_resampler
from gk3hd.patch.definitions.runtime2d.system.cursor_blend import (
    CALLBACK,
    ENTRY,
    HEIGHT,
    SOURCE,
    TRACE,
    VTABLE,
    WIDTH,
    build_blend_wrapper,
)

_BASE, _STACK, _STOP = 0x800000, 0x900000, 0x810000
_SOURCE, _DEST, _SRC_RECT, _DEST_RECT, _OPTIONS = range(0x820000, 0x820500, 0x100)


def _put(cpu: Uc, address: int, *values: int) -> None:
    cpu.mem_write(address, struct.pack("<" + "I" * len(values), *values))


def _get(cpu: Uc, address: int, count: int) -> tuple[int, ...]:
    return struct.unpack("<" + "I" * count, cpu.mem_read(address, count * 4))


@pytest.mark.slow
def test_cursor_blend_preserves_native_effect_and_calling_convention() -> None:
    subprocess.run(  # noqa: S603 - fixed interpreter and own test module.
        [sys.executable, str(Path(__file__).resolve())],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _case(variant: str) -> None:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x600000)
    payload = build_blend_wrapper(profile=GOG_BUILD, base=_BASE)
    assert len(payload) <= CALLBACK - ENTRY
    cpu.mem_write(_BASE + ENTRY, payload)
    entries = {
        name: GOG_BUILD.address(key)
        for name, key in {
            "lock": "bitmap.effect_lockable",
            "construct": "bitmap.effect_constructor",
            "execute": "bitmap.effect_executor",
            "destroy": "bitmap.effect_destructor",
            "stretch": "runtime2d.final_stretch_blt",
        }.items()
    }
    for name, cleanup in (
        ("lock", 4),
        ("construct", 20),
        ("execute", 0),
        ("destroy", 0),
        ("stretch", 12),
    ):
        cpu.mem_write(entries[name], b"\xc2" + struct.pack("<H", cleanup))
    options = 0 if variant == "null" else _OPTIONS
    _put(cpu, _OPTIONS, int(variant != "empty"), 0x1234, 0xABCD)
    _put(cpu, _STACK, _STOP, _SOURCE, _DEST_RECT, _SRC_RECT, options)
    _put(cpu, _SRC_RECT, 644, 4, 792, 156)
    _put(cpu, _DEST_RECT, 0, 20, 100, 130)
    preserved = {
        UC_X86_REG_EBX: 123,
        UC_X86_REG_ESI: 456,
        UC_X86_REG_EDI: 789,
        UC_X86_REG_EBP: 321,
    }
    for register, value in preserved.items():
        cpu.reg_write(register, value)
    cpu.reg_write(UC_X86_REG_ECX, _DEST)
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    calls: list[str] = []
    objects: list[int] = []

    def inspect(machine: Uc, address: int, _size: int, _data: object) -> None:
        name = next((key for key, value in entries.items() if value == address), None)
        if name is None:
            return
        calls.append(name)
        stack = machine.reg_read(UC_X86_REG_ESP)
        obj = machine.reg_read(UC_X86_REG_ECX)
        if name == "lock":
            assert obj == (_SOURCE if calls.count("lock") == 1 else _DEST)
            assert _get(machine, stack + 4, 1) == (0xFFFF,)
            unavailable = (variant == "source_locked" and obj == _SOURCE) or (
                variant == "dest_locked" and obj == _DEST
            )
            machine.reg_write(UC_X86_REG_EAX, int(not unavailable))
        elif name == "construct":
            assert _get(machine, stack + 4, 5) == (_DEST, _SOURCE, _DEST_RECT, _SRC_RECT, _OPTIONS)
            assert _get(machine, _BASE + SOURCE, 4) == (644, 4, 792, 156)
            assert _get(machine, _BASE + WIDTH, 1) == (100,)
            assert _get(machine, _BASE + HEIGHT, 1) == (110,)
            # Exercise the full object extent, including the two opacity words.
            machine.mem_write(obj, bytes([0xA5]) * 0x50)
            objects.append(obj)
            machine.reg_write(UC_X86_REG_EAX, obj)
        elif name in {"execute", "destroy"}:
            assert objects == [obj]
            assert _get(machine, obj, 1) == (_BASE + VTABLE,)
            assert bytes(machine.mem_read(obj + 4, 0x4C)) == bytes([0xA5]) * 0x4C
            machine.reg_write(UC_X86_REG_EAX, 0)
        else:
            assert obj == _DEST
            assert _get(machine, stack + 4, 3) == (_SOURCE, _DEST_RECT, _SRC_RECT)
            machine.reg_write(UC_X86_REG_EAX, 7)

    cpu.hook_add(UC_HOOK_CODE, inspect)
    cpu.emu_start(_BASE + ENTRY, _STOP, count=1000)
    _verify(cpu, variant, calls, preserved)


def _verify(cpu: Uc, variant: str, calls: list[str], preserved: dict[int, int]) -> None:
    """Check the returned ABI and immutable input arguments for every branch."""
    expected = {
        "null": ["stretch"],
        "empty": ["stretch"],
        "source_locked": ["lock", "stretch"],
        "dest_locked": ["lock", "lock", "stretch"],
        "blend": ["lock", "lock", "construct", "execute", "destroy"],
    }
    assert calls == expected[variant]
    assert cpu.reg_read(UC_X86_REG_EAX) == (1 if variant == "blend" else 7)
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 20
    assert all(cpu.reg_read(register) == value for register, value in preserved.items())
    assert _get(cpu, _SRC_RECT, 4) == (644, 4, 792, 156)
    assert _get(cpu, _DEST_RECT, 4) == (0, 20, 100, 130)
    assert _get(cpu, _OPTIONS, 3) == (int(variant != "empty"), 0x1234, 0xABCD)


def _sample_case(density: int, frame: int, extent: int, origin: tuple[int, int]) -> None:
    """Map clipped frame-local samples, including nonzero executor tile origins."""
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x600000)
    native = GOG_BUILD.address("bitmap.effect_callback")
    cpu.mem_write(
        _BASE + CALLBACK,
        build_native_alpha_resampler(
            callback_va=_BASE + CALLBACK,
            native_callback_va=native,
            source_rect_va=_BASE + SOURCE,
            dest_width_va=_BASE + WIDTH,
            dest_height_va=_BASE + HEIGHT,
            trace_va=_BASE + TRACE,
            center_samples=True,
        ),
    )
    cpu.mem_write(native, b"\xc2\x10\x00")
    left, top = (frame * 40 + 1) * density, density
    _put(cpu, _BASE + SOURCE, left, top, left + 38 * density, top + 38 * density)
    _put(cpu, _BASE + WIDTH, extent, extent)
    _put(cpu, _SRC_RECT, 2, 2)
    _put(cpu, _DEST_RECT, *origin)
    _put(cpu, _STACK, _STOP, _DEST, 1024, _SRC_RECT, _DEST_RECT)
    preserved = {
        UC_X86_REG_EBX: 123,
        UC_X86_REG_ESI: 456,
        UC_X86_REG_EDI: 789,
        UC_X86_REG_EBP: 321,
    }
    for register, value in preserved.items():
        cpu.reg_write(register, value)
    cpu.reg_write(UC_X86_REG_ECX, _OPTIONS)
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    samples: list[tuple[int, ...]] = []

    def inspect(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address != native:
            return
        assert machine.reg_read(UC_X86_REG_ECX) == _OPTIONS
        target, pitch, dimensions, point = _get(machine, machine.reg_read(UC_X86_REG_ESP) + 4, 4)
        row, col = divmod(len(samples), 2)
        assert (target, pitch) == (_DEST + row * 1024 + col * 2, 1024)
        assert _get(machine, dimensions, 2) == (1, 1)
        samples.append(_get(machine, point, 2))

    cpu.hook_add(UC_HOOK_CODE, inspect)
    cpu.emu_start(_BASE + CALLBACK, _STOP, count=1000)
    assert samples == [
        tuple(
            ((origin[axis] + offset) * 38 * density + 19 * density) // extent
            for axis, offset in enumerate((col, row))
        )
        for row in range(2)
        for col in range(2)
    ]
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 20
    assert all(cpu.reg_read(register) == value for register, value in preserved.items())


if __name__ == "__main__":
    for _variant in ("null", "empty", "source_locked", "dest_locked", "blend"):
        _case(_variant)
    for _density in (1, 4):
        for _frame in (0, 7, 14):
            for _extent in (38, 107, 214):
                for _origin in ((0, 0), (5, 3), (_extent - 2, _extent - 2)):
                    _sample_case(_density, _frame, _extent, _origin)
