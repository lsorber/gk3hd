"""Execute padded glyph clipping through the actual stack-local draw adapter."""

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

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.font_bank import FontBankRuntime
from gk3hd.textures.upscale.fonts.bank import FONT_PADDED_BANK_LAYOUTS, font_bank_layout

_BASE, _RECORD, _TARGET, _STOP = 0x100000, 0x100800, 0x101000, 0x102000
_CACHE, _FONT, _STACK, _FRAME = 0x200000, 0x210000, 0x308000, 0x310000
_POINT, _SOURCE, _CONTEXT, _OPTIONS = 0x211000, 0x211020, 0x212000, 0x212100
_RETURN = 0x12345678


def _put(machine: Uc, address: int, *values: int) -> None:
    machine.mem_write(
        address, struct.pack("<" + "I" * len(values), *(v & 0xFFFFFFFF for v in values))
    )


def _words(machine: Uc, address: int, count: int) -> tuple[int, ...]:
    return struct.unpack("<" + "i" * count, machine.mem_read(address, count * 4))


def _draw_contract(name: str) -> None:
    layout = font_bank_layout(name)
    assert layout is not None
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(_BASE, 0x3000)
    machine.mem_map(_CACHE, 0x14000)
    machine.mem_map(0x300000, 0x20000)
    runtime = FontBankRuntime(_CACHE, _CACHE + 0x3000, _CACHE + 0x3004, _STOP)
    machine.mem_write(_BASE, runtime.draw(_BASE, record_va=_RECORD, target_va=_TARGET))
    machine.mem_write(_RECORD, runtime.glyph_record(_RECORD))
    machine.mem_write(_TARGET, b"\xb8" + struct.pack("<I", _RETURN) + bytes.fromhex("c21400"))
    _put(machine, _CACHE, 123, *layout.source_size, layout.max_advance)
    machine.mem_write(_CACHE + 16, ((1 << layout.glyph_count) - 1).to_bytes(96, "little"))
    _put(machine, _CACHE + 112, layout.bank_distance, layout.glyph_count, layout.source_size[1], 0)
    _put(machine, _FONT + 4, 123)
    _put(machine, _FONT + 0x34, layout.source_size[0] - 1, layout.source_size[1] - 1)
    machine.mem_write(
        _FONT + 0x50,
        struct.pack(
            f"<{layout.glyph_count + 1}H", *(1 + 4 * i for i in range(layout.glyph_count + 1))
        ),
    )
    calls = []

    def capture(cpu: Uc, address: int, _size: int, _user: object) -> None:
        if address == _TARGET:
            args = _words(cpu, cpu.reg_read(UC_X86_REG_ESP) + 4, 5)
            calls.append(
                (
                    cpu.reg_read(UC_X86_REG_ECX),
                    args,
                    _words(cpu, args[2], 2),
                    _words(cpu, args[3], 4),
                )
            )

    machine.hook_add(UC_HOOK_CODE, capture)
    for index, cut, room in itertools.product(
        (0, 37, layout.glyph_count - 2, layout.glyph_count - 1),
        itertools.product((0, 1), repeat=4),
        itertools.product((0, 1), repeat=4),
    ):
        left = 1 + index * 4
        height = layout.source_size[1]
        rect = (left + cut[0], 1 + cut[1], left + 4 - cut[2], height - cut[3])
        _put(machine, _POINT, 100, 200)
        _put(machine, _SOURCE, *rect)
        _put(
            machine,
            _CONTEXT + 0x28,
            100 - room[0],
            200 - room[1],
            100 + rect[2] - rect[0] + room[2],
            200 + rect[3] - rect[1] + room[3],
        )
        _put(machine, _FRAME - 0x14, index)
        _put(machine, _STACK, _STOP, 11, 123, _POINT, _SOURCE, _OPTIONS)
        registers = {
            UC_X86_REG_EAX: 3,
            UC_X86_REG_EBX: _CONTEXT,
            UC_X86_REG_ECX: 0x777,
            UC_X86_REG_EDX: _FONT,
            UC_X86_REG_ESI: 6,
            UC_X86_REG_EDI: 7,
            UC_X86_REG_EBP: _FRAME,
            UC_X86_REG_ESP: _STACK,
            UC_X86_REG_EFLAGS: 0x246,
        }
        for register, value in registers.items():
            machine.reg_write(register, value)
        calls.clear()
        machine.emu_start(_BASE, _STOP, count=2000)
        assert len(calls) == 1
        this, args, point, source = calls[0]
        bank_left, bank_top, _right, _bottom = layout.glyph_rect(index, 4)
        dx, dy = bank_left + 1 - left, bank_top
        expand = tuple(int(not edge and margin > 0) for edge, margin in zip(cut, room, strict=True))
        assert point == (100 - expand[0], 200 - expand[1])
        assert source == (
            rect[0] + dx - expand[0],
            rect[1] + dy - expand[1],
            rect[2] + dx + expand[2],
            rect[3] + dy + expand[3],
        )
        assert this == 0x777
        assert args[:2] == (11, 123)
        assert args[4] == _OPTIONS
        assert _words(machine, _POINT, 2) == (100, 200)
        assert _words(machine, _SOURCE, 4) == rect
        for register, value in registers.items():
            expected = (
                _RETURN
                if register == UC_X86_REG_EAX
                else value + (24 if register == UC_X86_REG_ESP else 0)
            )
            assert machine.reg_read(register) == expected
    _nested_draw(machine, registers, calls)


def _nested_draw(machine: Uc, registers: dict[int, int], calls: list) -> None:
    """A delegated blit reenters font drawing without overwriting outer locals."""
    depth = _CONTEXT + 0x200
    inner_frame, inner_context = _FRAME + 0x100, _CONTEXT + 0x300
    inner_point, inner_source = _POINT + 0x100, _SOURCE + 0x100
    height = _words(machine, _FONT + 0x38, 1)[0] + 1
    _put(machine, inner_point, 300, 400)
    _put(machine, inner_source, 1, 1, 5, height)
    _put(machine, inner_context + 0x28, 299, 399, 305, 400 + height)
    _put(machine, inner_frame - 0x14, 0)
    code = X86Emitter(base_va=_TARGET)
    code.raw(bytes.fromhex("833d") + struct.pack("<I", depth) + b"\0")
    code.jump_if(Condition.NOT_EQUAL, "return")
    code.raw(bytes.fromhex("9c60 c705") + struct.pack("<II", depth, 1))
    for opcode, value in ((0xBD, inner_frame), (0xBB, inner_context), (0xBA, _FONT), (0xB9, 0x888)):
        code.raw(bytes([opcode]) + struct.pack("<I", value))
    for value in (_OPTIONS, inner_source, inner_point, 123, 99):
        code.raw(b"\x68" + struct.pack("<I", value))
    code.call_absolute(_BASE)
    code.raw(bytes.fromhex("619d"))
    code.label("return")
    code.raw(b"\xb8" + struct.pack("<I", _RETURN) + bytes.fromhex("c21400"))
    machine.mem_write(_TARGET, code.build())
    machine.ctl_remove_cache(_TARGET, _TARGET + len(code.build()))
    for register, value in registers.items():
        machine.reg_write(register, value)
    calls.clear()
    machine.emu_start(_BASE, _STOP, count=4000)
    assert len(calls) == 2, calls
    assert calls[0][0] == 0x777
    assert calls[1][0] == 0x888
    assert calls[1][1][:2] == (99, 123)
    for _this, args, point, source in calls:
        assert _words(machine, args[2], 2) == point
        assert _words(machine, args[3], 4) == source
    assert _words(machine, inner_point, 2) == (300, 400)
    assert _words(machine, inner_source, 4) == (1, 1, 5, height)
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 24
    assert machine.reg_read(UC_X86_REG_EAX) == _RETURN


@pytest.mark.slow
def test_stack_local_font_bank_draw() -> None:
    subprocess.run(  # noqa: S603 - fixed interpreter and own test module.
        [sys.executable, str(Path(__file__).resolve())],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )


if __name__ == "__main__":
    for _name in FONT_PADDED_BANK_LAYOUTS:
        _draw_contract(_name)
