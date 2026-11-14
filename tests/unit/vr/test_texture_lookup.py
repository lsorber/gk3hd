"""Exercise emitted texture lookup code with the Win32 stack and error ABI."""

from __future__ import annotations

import struct

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_EDI,
    UC_X86_REG_EIP,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.definitions.vr_texture_lookup import _lookup_code

_CODE = 0x100000
_STACK = 0x200000
_PATH = 0x300000
_IMPORTS = 0x400000
_KERNEL = 0x500000
_CREATE, _GET_ERROR, _SET_ERROR, _RETURN = (_KERNEL + offset for offset in (0, 16, 32, 48))
_REGISTERS = (UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_ESI)
_READ = 0x80000000
_OPEN_EXISTING = 3
_INITIAL_ERROR = 123
_FAILED_OPEN = 0xFFFFFFFF
_PREFIX = b"gk3hd/textures/installed\\"
_VITOUX = _PREFIX + b"vit_blink_01.bmp"


@pytest.mark.parametrize(
    ("request_path", "first_path", "fallback"),
    [
        (_VITOUX, _PREFIX + b"VIT_BLINK_01.BMP", False),
        (_VITOUX, _PREFIX + b"VIT_BLINK_01.BMP", True),
        (_PREFIX + b"jea_blink_01.bmp", _PREFIX + b"JEA_BLINK_01.BMP", False),
        (_PREFIX + b"jea_blink_02.bmp", _PREFIX + b"JEA_BLINK_02.BMP", True),
        (_PREFIX + b"GAB_BLINK_01.BMP", _PREFIX + b"GAB_BLINK_01.BMP", False),
        (b".\\" + _PREFIX + b"gab_blink_02.bmp", b".\\" + _PREFIX + b"GAB_BLINK_02.BMP", False),
        (
            b"C:\\gk3hd-vr\\" + _PREFIX + b"vit_blink_02.bmp",
            b"C:\\gk3hd-vr\\" + _PREFIX + b"VIT_BLINK_02.BMP",
            False,
        ),
        (_VITOUX + b".bak", _VITOUX + b".bak", False),
        (_PREFIX + b"*.bmp", _PREFIX + b"*.bmp", False),
        (b"other\\" + _VITOUX, b"other\\" + _VITOUX, False),
        (b"vit_blink_01.bmp", b"vit_blink_01.bmp", False),
        (b"", b"", False),
        (None, None, False),
        (b"x" * 64, b"x" * 64, False),
    ],
)
def test_texture_open_uses_exact_name_and_native_fallback(
    request_path: bytes | None, first_path: bytes | None, fallback: bool
) -> None:
    _run_open(
        request_path,
        (first_path, request_path) if fallback else (first_path,),
        (_FAILED_OPEN, _FAILED_OPEN) if fallback else (0x42,),
    )


@pytest.mark.parametrize(
    ("access", "disposition", "flags"),
    [(0x40000000, 3, 0x80), (_READ, 2, 0x80), (_READ, 3, 0x04000080)],
)
def test_texture_open_preserves_mutating_requests(
    access: int, disposition: int, flags: int
) -> None:
    _run_open(_VITOUX, (_VITOUX,), (0x42,), arguments=(access, 7, 0, disposition, flags, 0))


def test_texture_open_falls_back_to_an_alternate_installation_spelling() -> None:
    _run_open(_VITOUX, (_PREFIX + b"VIT_BLINK_01.BMP", _VITOUX), (_FAILED_OPEN, 0x42))


def _native_path(cpu: Uc, pointer: int) -> bytes | None:
    if not pointer:
        return None
    chars = bytearray()
    while char := cpu.mem_read(pointer + len(chars), 1)[0]:
        chars.append(char)
    return bytes(chars)


def _run_open(
    path: bytes | None,
    expected: tuple[bytes | None, ...],
    results: tuple[int, ...],
    *,
    arguments: tuple[int, ...] = (_READ, 7, 0x1B0, _OPEN_EXISTING, 0x08000080, 0x1CC),
) -> None:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    for address in (_CODE, _STACK, _PATH, _IMPORTS, _KERNEL):
        cpu.mem_map(address, 0x1000)
    cpu.mem_write(_CODE, _lookup_code(_CODE, _IMPORTS, _IMPORTS + 4, _IMPORTS + 8))
    cpu.mem_write(_IMPORTS, struct.pack("<3I", _CREATE, _GET_ERROR, _SET_ERROR))
    cpu.mem_write(_CREATE, b"\xc2\x1c\0")
    cpu.mem_write(_GET_ERROR, b"\xc3")
    cpu.mem_write(_SET_ERROR, b"\xc2\x04\0")
    # The original pathname ends on the last readable byte of its page.
    address = _PATH + 0xFFF - len(path) if path is not None else 0
    if path is not None:
        cpu.mem_write(address, path + b"\0")
    stack = _STACK + 0xE00
    cpu.mem_write(stack, struct.pack("<8I", _RETURN, address, *arguments))
    cpu.reg_write(UC_X86_REG_ESP, stack)
    saved = {register: 0x430000 + register for register in _REGISTERS}
    for register, value in saved.items():
        cpu.reg_write(register, value)

    seen: list[bytes | None] = []
    error = _INITIAL_ERROR

    def callback(machine: Uc, instruction: int, _size: int, _user: object) -> None:
        nonlocal error
        esp = int(machine.reg_read(UC_X86_REG_ESP))
        if instruction == _CREATE:
            pointer, *forwarded = struct.unpack("<7I", machine.mem_read(esp + 4, 28))
            assert tuple(forwarded) == arguments
            value = _native_path(machine, pointer)
            assert error == _INITIAL_ERROR
            result = results[len(seen)]
            seen.append(value)
            machine.reg_write(UC_X86_REG_EAX, result)
            if result == _FAILED_OPEN:
                error = 2
        elif instruction == _GET_ERROR:
            machine.reg_write(UC_X86_REG_EAX, error)
        elif instruction == _SET_ERROR:
            error = struct.unpack("<I", machine.mem_read(esp + 4, 4))[0]

    cpu.hook_add(UC_HOOK_CODE, callback)
    cpu.emu_start(_CODE, _RETURN, count=5000)
    assert cpu.reg_read(UC_X86_REG_EIP) == _RETURN
    assert cpu.reg_read(UC_X86_REG_ESP) == stack + 32
    assert cpu.reg_read(UC_X86_REG_EAX) == results[-1]
    assert error == (2 if results[-1] == _FAILED_OPEN else _INITIAL_ERROR)
    assert tuple(seen) == expected
    assert all(cpu.reg_read(register) == value for register, value in saved.items())
    if path is not None:
        assert bytes(cpu.mem_read(address, len(path) + 1)) == path + b"\0"
