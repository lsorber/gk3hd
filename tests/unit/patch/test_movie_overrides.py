"""Exercise replacement lookup and decoder fallback through the emitted x86 ABI."""

from __future__ import annotations

import struct

import pytest
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

from gk3hd.patch.definitions.runtime2d.system.movie_overrides import (
    MOVIE_OVERRIDE_PREFIX,
    MOVIE_PATH_PREFIX,
    MovieOverrideImports,
    build_embedded_size,
    build_factory,
    build_logical_size,
    build_path_resolver,
)
from gk3hd.videos.catalog import replacement_name

_CODE = 0x800000
_RETURN = _CODE + 0xF000
_MODULE = _CODE + 0x8000
_CREATE = _CODE + 0x8100
_CLOSE = _CODE + 0x8200
_NATIVE = _CODE + 0x8300
_DATA = 0x900000
_NAME = _DATA + 0x100
_PREFIX = _DATA + 0x500
_MOVIE = _DATA + 0x1000
_ORIGINAL = _DATA + 0x2000
_TABLE = _DATA + 0x3000
_STACK = _DATA + 0xF000


@pytest.mark.parametrize(
    "screen", [(800, 600), (1024, 768), (1280, 800), (3840, 2160), (720, 1280)]
)
@pytest.mark.parametrize("source", [(432, 384), (320, 240), (41, 51)])
def test_embedded_layout_preserves_reference_scale_and_native_call_contract(
    screen: tuple[int, int], source: tuple[int, int]
) -> None:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(_CODE, 0x10000)
    cpu.mem_map(_DATA, 0x10000)
    output = _DATA + 0x4000
    frame_base = _DATA + 0xE000
    cpu.mem_write(_DATA, struct.pack("<II", *screen))
    cpu.mem_write(_CODE, build_embedded_size(wrapper_va=_CODE, dimensions_va=_DATA))
    cpu.mem_write(_TABLE + 0x4C, struct.pack("<I", _NATIVE))
    cpu.mem_write(_NATIVE, bytes.fromhex("c20400"))
    cpu.mem_write(_STACK, struct.pack("<III", _RETURN, output, 0x12345678))
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.reg_write(UC_X86_REG_EBP, frame_base)
    cpu.reg_write(UC_X86_REG_EAX, _TABLE)
    cpu.reg_write(UC_X86_REG_ECX, _MOVIE)
    preserved = {UC_X86_REG_EBX: 0x123, UC_X86_REG_ESI: 0x456, UC_X86_REG_EDI: 0x789}
    for register, value in preserved.items():
        cpu.reg_write(register, value)
    calls = []

    def native_call(machine: Uc, address: int, _size: int, _user: object) -> None:
        if address == _NATIVE:
            stack = machine.reg_read(UC_X86_REG_ESP)
            pointer = struct.unpack("<I", machine.mem_read(stack + 4, 4))[0]
            assert pointer == output
            assert machine.reg_read(UC_X86_REG_ECX) == _MOVIE
            machine.mem_write(pointer, struct.pack("<II", *source))
            calls.append(address)

    cpu.hook_add(UC_HOOK_CODE, native_call)
    cpu.emu_start(_CODE, _RETURN, count=500)
    scale = 1 if screen[0] <= 1024 and screen[1] <= 768 else min(screen[0] / 1024, screen[1] / 768)
    expected = tuple(int(value * scale + 0.5) for value in source)
    assert struct.unpack("<II", cpu.mem_read(output, 8)) == expected
    assert len(calls) == 1
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 8
    assert cpu.reg_read(UC_X86_REG_EAX) == frame_base - 12
    assert cpu.reg_read(UC_X86_REG_EBP) == frame_base
    assert all(cpu.reg_read(register) == value for register, value in preserved.items())
    assert bytes(cpu.mem_read(_STACK + 8, 4)) == struct.pack("<I", 0x12345678)


def _string(cpu: Uc, address: int) -> bytes:
    result = bytearray()
    while value := cpu.mem_read(address + len(result), 1)[0]:
        result.append(value)
        assert len(result) <= 300
    return bytes(result)


def _alias(name: bytes) -> bytes:
    basename = name.replace(b"\\", b"/").rsplit(b"/", 1)[-1]
    try:
        return replacement_name(basename.decode("ascii")).encode("ascii")
    except ValueError:
        return b""


@pytest.mark.parametrize(
    "name",
    [
        b"intro.bik",
        b"Data/intro.bik",
        b"Data\\intro.bik",
        b"intro",
        b"intro.part.bik",
        b"X" * 20 + b".bik",
        b"X" * 21 + b".bik",
        b"X" * 22 + b".bik",
        b"",
        b".bik",
    ],
)
@pytest.mark.parametrize("available", [False, True])
@pytest.mark.parametrize("decodable", [False, True])
def test_lookup_uses_executable_directory_and_falls_back_without_touching_originals(
    name: bytes, *, available: bool, decodable: bool
) -> None:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(_CODE, 0x10000)
    cpu.mem_map(_DATA, 0x10000)
    cpu.mem_write(_DATA, struct.pack("<III", _MODULE, _CREATE, _CLOSE))
    cpu.mem_write(_NAME, name + b"\0")
    cpu.mem_write(_PREFIX, MOVIE_PATH_PREFIX)
    cpu.mem_write(
        _CODE,
        build_factory(
            wrapper_va=_CODE,
            trampoline_va=_NATIVE,
            vtable_va=_TABLE,
            prefix_va=_PREFIX,
            imports=MovieOverrideImports(_DATA, _DATA + 4, _DATA + 8),
        ),
    )
    for address, instruction in (
        (_MODULE, b"\xc2\x0c\x00"),
        (_CREATE, b"\xc2\x1c\x00"),
        (_CLOSE, b"\xc2\x04\x00"),
        (_NATIVE, b"\xc3"),
    ):
        cpu.mem_write(address, instruction)
    opened: list[bytes] = []
    decoded: list[bytes] = []
    closed: list[int] = []

    def api(machine: Uc, address: int, _size: int, _user: object) -> None:
        stack = machine.reg_read(UC_X86_REG_ESP)
        args = struct.unpack("<7I", machine.mem_read(stack + 4, 28))
        if address == _MODULE:
            module = b"D:\\Games With Spaces\\GK3\\GK3.exe"
            assert args[0] == 0
            machine.mem_write(args[1], module + b"\0")
            machine.reg_write(UC_X86_REG_EAX, len(module))
        elif address == _CREATE:
            opened.append(_string(machine, args[0]))
            assert args[1:] == (0x80000000, 7, 0, 3, 0x80, 0)
            machine.reg_write(UC_X86_REG_EAX, 123 if available else 0xFFFFFFFF)
        elif address == _CLOSE:
            closed.append(args[0])
            machine.reg_write(UC_X86_REG_EAX, 1)
        elif address == _NATIVE:
            decoded.append(_string(machine, args[0]))
            result = _ORIGINAL if decoded[-1] == name else _MOVIE if decodable else 0
            machine.reg_write(UC_X86_REG_EAX, result)
        else:
            return
        machine.reg_write(UC_X86_REG_ECX, 0xCCCCCCCC)
        machine.reg_write(UC_X86_REG_EDX, 0xDDDDDDDD)

    cpu.hook_add(UC_HOOK_CODE, api)
    cpu.mem_write(_STACK, struct.pack("<II", _RETURN, _NAME))
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    preserved = (UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI)
    for register in preserved:
        cpu.reg_write(register, 0x12345678)
    cpu.emu_start(_CODE, _RETURN, count=10000)
    asset_name = _alias(name)
    valid = bool(asset_name)
    replacement = b"D:\\Games With Spaces\\GK3\\" + MOVIE_OVERRIDE_PREFIX + asset_name
    assert opened == ([replacement] if valid else [])
    assert closed == ([123] if valid and available else [])
    assert decoded == (
        [asset_name]
        if valid and available and decodable
        else [asset_name, name]
        if valid and available
        else [name]
    )
    assert cpu.reg_read(UC_X86_REG_EAX) == (
        _MOVIE if valid and available and decodable else _ORIGINAL
    )
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 4
    assert all(cpu.reg_read(register) == 0x12345678 for register in preserved)
    if valid and available and decodable:
        assert struct.unpack("<I", cpu.mem_read(_MOVIE, 4))[0] == _TABLE


def test_replacement_dimensions_are_logical_not_decoded_backing_size() -> None:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(_CODE, 0x10000)
    cpu.mem_map(_DATA, 0x10000)
    cpu.mem_write(_CODE, build_logical_size(wrapper_va=_CODE, native_va=_NATIVE))
    cpu.mem_write(_NATIVE, b"\xc2\x04\x00")

    def native(machine: Uc, address: int, _size: int, _user: object) -> None:
        if address == _NATIVE:
            stack = machine.reg_read(UC_X86_REG_ESP)
            pointer = struct.unpack("<I", machine.mem_read(stack + 4, 4))[0]
            machine.mem_write(pointer, struct.pack("<II", 1560, 1696))

    cpu.hook_add(UC_HOOK_CODE, native)
    cpu.mem_write(_STACK, struct.pack("<II", _RETURN, _DATA + 0x100))
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.emu_start(_CODE, _RETURN, count=100)
    assert struct.unpack("<II", cpu.mem_read(_DATA + 0x100, 8)) == (390, 424)
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 8


@pytest.mark.parametrize(
    ("name", "capacity", "available", "resolved"),
    [
        (b"GK3HD-INTRO.AVI", 300, True, True),
        (b"GK3HD-SIERRA.AVI", 300, True, True),
        (b"GK3HD-INTRO.AVI", 300, False, False),
        (b"GK3HD-INTRO.AVI", 16, True, False),
        (b"Sierra.avi", 300, True, False),
        (b"GK3HD-../escape.avi", 300, True, False),
    ],
)
def test_alias_resolver_is_bounded_and_leaves_other_resource_lookup_unchanged(
    name: bytes, capacity: int, *, available: bool, resolved: bool
) -> None:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(_CODE, 0x10000)
    cpu.mem_map(_DATA, 0x10000)
    cpu.mem_write(_DATA, struct.pack("<III", _MODULE, _CREATE, _CLOSE))
    cpu.mem_write(_NAME, name + b"\0")
    cpu.mem_write(_PREFIX, MOVIE_PATH_PREFIX)
    cpu.mem_write(
        _CODE,
        build_path_resolver(
            wrapper_va=_CODE,
            prefix_va=_PREFIX,
            imports=MovieOverrideImports(_DATA, _DATA + 4, _DATA + 8),
        ),
    )
    manager, destination, native_frame = _DATA + 0x5000, _DATA + 0x6000, _DATA + 0x7000
    cpu.mem_write(manager, struct.pack("<I", _TABLE))
    cpu.mem_write(_TABLE + 0x48, struct.pack("<I", _NATIVE))
    cpu.mem_write(destination, b"\xaa" * (capacity + 8))
    for address, instruction in (
        (_MODULE, b"\xc2\x0c\x00"),
        (_CREATE, b"\xc2\x1c\x00"),
        (_CLOSE, b"\xc2\x04\x00"),
        (_NATIVE, b"\xc2\x0c\x00"),
    ):
        cpu.mem_write(address, instruction)
    native_calls: list[bytes] = []

    def api(machine: Uc, address: int, _size: int, _user: object) -> None:
        stack = machine.reg_read(UC_X86_REG_ESP)
        args = struct.unpack("<3I", machine.mem_read(stack + 4, 12))
        if address == _MODULE:
            module = b"D:\\Games With Spaces\\GK3\\GK3.exe\0"
            machine.mem_write(args[1], module[: args[2]])
            machine.reg_write(UC_X86_REG_EAX, min(len(module) - 1, args[2]))
        elif address == _CREATE:
            assert _string(machine, args[0]) == (
                b"D:\\Games With Spaces\\GK3\\" + MOVIE_OVERRIDE_PREFIX + name
            )
            machine.reg_write(UC_X86_REG_EAX, 123 if available else 0xFFFFFFFF)
        elif address == _CLOSE:
            assert args[0] == 123
        elif address == _NATIVE:
            assert machine.reg_read(UC_X86_REG_ECX) == manager
            assert args == (_NAME, destination, capacity)
            native_calls.append(_string(machine, args[0]))
            machine.reg_write(UC_X86_REG_EAX, 0)

    cpu.hook_add(UC_HOOK_CODE, api)
    cpu.mem_write(_STACK, struct.pack("<4I", _RETURN, _NAME, destination, capacity))
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.reg_write(UC_X86_REG_ECX, manager)
    cpu.reg_write(UC_X86_REG_EBP, native_frame)
    cpu.emu_start(_CODE, _RETURN, count=10000)
    assert cpu.reg_read(UC_X86_REG_EAX) == resolved
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 16
    assert cpu.reg_read(UC_X86_REG_EBP) == native_frame
    assert cpu.mem_read(destination + capacity, 8) == b"\xaa" * 8
    assert native_calls == ([] if resolved else [name])
    if resolved:
        assert _string(cpu, destination) == (
            b"D:\\Games With Spaces\\GK3\\" + MOVIE_OVERRIDE_PREFIX + name
        )
