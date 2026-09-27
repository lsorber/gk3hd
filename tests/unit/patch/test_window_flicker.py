"""Repeated topmost requests are harmless, but real window changes still occur."""

from __future__ import annotations

import struct

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_EDI,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler

_BASE = 0x800000
_API = 0x810000
_STACK = 0x82F000
_RETURN = 0x81F000


@pytest.mark.parametrize(
    "case",
    [
        (8, -1, 3, 1, 1, False),
        (0x108, -1, 3, 1, 1, False),
        (0, -1, 3, 1, 1, True),  # also covers a failed style query
        (0x100, -1, 3, 1, 1, True),
        (8, 0, 3, 1, 1, True),  # change z-order
        (8, -2, 3, 1, 1, True),  # remove topmost
        (8, -1, 0, 1, 1, True),  # move/resize
        (8, -1, 0x13, 1, 1, True),  # additional flags are not assumed redundant
        (8, -1, 3, 0, 1, True),
        (8, -1, 3, 1, 0, True),
        (8, -1, 3, 1, 2, True),  # style API exists, but z-order query is unavailable
    ],
)
@pytest.mark.parametrize("native_result", [0, 1])
@pytest.mark.parametrize("previous", [0, 0x23456])
@pytest.mark.parametrize("foreground", [False, True])
def test_topmost_bridge_preserves_required_calls_arguments_results_and_abi(
    case: tuple[int, int, int, int, int, bool],
    native_result: int,
    previous: int,
    *,
    foreground: bool,
) -> None:
    style, insert_after, flags, module, proc, forwarded = case
    compiler = TransitionFrameCompiler(profile=GOG_BUILD)
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    for address, size in ((_BASE, 0x10000), (_API, 0x20000), (0x665000, 0x1000)):
        machine.mem_map(address, size)
    machine.mem_write(_BASE, compiler._build_payload(section_va=_BASE))
    apis = (
        (GOG_BUILD.address("win32.GetModuleHandleA"), _API, module, 4),
        (GOG_BUILD.address("win32.GetProcAddress"), _API + 0x100, _API + 0x200 if proc else 0, 8),
        (0x665368, _API + 0x300, native_result, 28),
        (
            GOG_BUILD.address("win32.GetForegroundWindow"),
            _API + 0x500,
            0x12345 if foreground else 0,
            0,
        ),
    )
    for iat, target, result, pop in apis:
        machine.mem_write(iat, struct.pack("<I", target))
        machine.mem_write(
            target, b"\xb8" + struct.pack("<I", result) + b"\xc2" + struct.pack("<H", pop)
        )
    machine.mem_write(_API + 0x200, b"\xc2\x08\x00")
    machine.mem_write(_API + 0x100, b"\xc2\x08\x00")
    machine.mem_write(_API + 0x400, b"\xb8" + struct.pack("<I", previous) + b"\xc2\x08\x00")
    arguments = (0x12345, insert_after & 0xFFFFFFFF, 31, 47, 1280, 800, flags)
    frame = struct.pack("<8I", _RETURN, *arguments)
    registers = (UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI)
    for index, register in enumerate(registers):
        machine.reg_write(register, 0xC0FFEE00 + index)
    calls: list[tuple[int, ...]] = []

    def record_call(cpu: Uc, address: int, _size: int, _data: object) -> None:
        stack = cpu.reg_read(UC_X86_REG_ESP)
        if address == _API + 0x300:
            calls.append(struct.unpack("<7I", cpu.mem_read(stack + 4, 28)))
        elif address == _API + 0x200:
            assert struct.unpack("<2I", cpu.mem_read(stack + 4, 8)) == (arguments[0], 0xFFFFFFEC)
            cpu.reg_write(UC_X86_REG_EAX, current_style)
        elif address == _API + 0x100:
            _, name = struct.unpack("<2I", cpu.mem_read(stack + 4, 8))
            is_order = bytes(cpu.mem_read(name, 10)).startswith(b"GetWindow\0")
            available = bool(proc) and not (proc == 2 and is_order)
            cpu.reg_write(
                UC_X86_REG_EAX, (_API + (0x400 if is_order else 0x200)) if available else 0
            )
        elif address == _API + 0x400:
            assert struct.unpack("<2I", cpu.mem_read(stack + 4, 8)) == (arguments[0], 3)

    machine.hook_add(UC_HOOK_CODE, record_call)
    # Repeat to expose stack drift; alter style externally between independent
    # calls rather than allowing a cached request to substitute for live style.
    for current_style in (style, style & ~8, style):
        machine.mem_write(_STACK, frame)
        machine.reg_write(UC_X86_REG_ESP, _STACK)
        before = len(calls)
        machine.emu_start(_BASE + compiler._off_window_wrapper, _RETURN, count=200)
        must_forward = forwarded or not current_style & 8 or bool(previous) or not foreground
        assert calls[before:] == ([arguments] if must_forward else [])
        assert machine.reg_read(UC_X86_REG_EAX) == (native_result if must_forward else 1)
        assert machine.reg_read(UC_X86_REG_ESP) == _STACK + len(frame)
        assert [machine.reg_read(register) for register in registers] == [
            0xC0FFEE00 + index for index in range(len(registers))
        ]
