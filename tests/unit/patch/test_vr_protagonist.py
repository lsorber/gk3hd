"""Read the actual ego anchor without changing a character or retaining stale state."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EFLAGS,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.builds import GOG_BUILD, SUPPORTED_BUILDS
from gk3hd.patch.definitions.vr_native_scene import NATIVE_SCENE_TYPES
from gk3hd.patch.definitions.vr_protagonist import VRProtagonistCompiler
from gk3hd.patch.model import PatchError
from tests.unit.patch.test_complete_compilation import _source
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine

if TYPE_CHECKING:
    from unicorn import Uc

    from gk3hd.patch.builds import BuildProfile


def _query(profile: BuildProfile = GOG_BUILD) -> tuple[Uc, int, dict[str, int], list[int]]:
    image = _source(profile)
    compiler = VRProtagonistCompiler(profile=profile)
    compiler.apply(image)
    compiler.postcheck(image)
    machine = _machine(image)
    pointers = {
        name: _HEAP + offset
        for name, offset in (
            ("room", 0x1000),
            ("actor", 0x2000),
            ("model", 0x3000),
            ("data", 0x4000),
            ("transform", 0x5000),
            ("output", 0x6000),
            ("other_actor", 0x7000),
        )
    }
    for address, value in {
        profile.address("vr.room_global"): pointers["room"],
        pointers["room"]: profile.address("vr.user_scene_vtable"),
        pointers["room"] + 0x58: pointers["actor"],
        pointers["actor"] + 0x64: pointers["model"],
        pointers["other_actor"] + 0x64: pointers["model"],
        pointers["model"] + 0xB0: pointers["data"],
        pointers["data"] + 4: pointers["transform"],
        pointers["model"] + 0xB8: pointers["transform"],
    }.items():
        machine.mem_write(address, struct.pack("<I", value))
    machine.mem_write(pointers["output"], struct.pack("<I", 32) + b"\xcc" * 28)
    # These animated/rendered fields must never substitute for the native root.
    machine.mem_write(pointers["model"] + 0x110, struct.pack("<4f", 999, 888, 777, 666))
    native = profile.site("vr.protagonist_position").va
    machine.mem_write(native, bytes.fromhex("c2 08 00"))
    calls: list[int] = []

    def get_position(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == native:
            calls.append(current.reg_read(UC_X86_REG_ECX))
            stack = current.reg_read(UC_X86_REG_ESP)
            position, heading = struct.unpack("<2I", current.mem_read(stack + 4, 8))
            current.mem_write(position, struct.pack("<3f", 235.25, 34.125, 58))
            current.mem_write(heading, struct.pack("<f", 1.25))

    machine.hook_add(UC_HOOK_CODE, get_position)
    return machine, compiler.abi(image).query_va, pointers, calls


def _call(machine: Uc, entry: int, output: int) -> int:
    machine.mem_write(_STACK, struct.pack("<2I", _RETURN, output))
    machine.reg_write(UC_X86_REG_ESP, _STACK)
    machine.emu_start(entry, _RETURN, count=1000)
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 8
    return machine.reg_read(UC_X86_REG_EAX)


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda value: str(value.id))
def test_reads_native_anchor_preserving_game_memory_and_caller_registers(
    profile: BuildProfile,
) -> None:
    machine, entry, p, calls = _query(profile)
    registers = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)
    for index, register in enumerate(registers):
        machine.reg_write(register, 100 + index)
    machine.reg_write(UC_X86_REG_EFLAGS, 0x402)  # Also preserve the caller's direction flag.
    before = bytes(machine.mem_read(_HEAP, 0x8000))
    assert _call(machine, entry, p["output"]) == 1
    assert calls == [p["model"]]
    output = bytes(machine.mem_read(p["output"], 32))
    assert struct.unpack("<4I4f", output) == (
        32,
        p["room"],
        p["actor"],
        p["model"],
        235.25,
        34.125,
        58,
        1.25,
    )
    after = bytearray(machine.mem_read(_HEAP, 0x8000))
    offset = p["output"] - _HEAP
    after[offset : offset + 32] = before[offset : offset + 32]
    assert bytes(after) == before
    assert [machine.reg_read(register) for register in registers] == [100, 101, 102, 103]
    assert machine.reg_read(UC_X86_REG_EFLAGS) == 0x402


@pytest.mark.parametrize("scene_type", NATIVE_SCENE_TYPES)
def test_verified_scene_subclasses_resolve_the_current_protagonist(scene_type: str) -> None:
    machine, entry, p, _calls = _query()
    machine.mem_write(p["room"], struct.pack("<I", GOG_BUILD.address(scene_type)))
    assert _call(machine, entry, p["output"]) == 1
    machine.mem_write(p["room"] + 0x58, struct.pack("<I", p["other_actor"]))
    assert _call(machine, entry, p["output"]) == 1
    assert struct.unpack("<I", machine.mem_read(p["output"] + 8, 4))[0] == p["other_actor"]


@pytest.mark.parametrize(
    "missing", ["room", "scene_type", "actor", "model", "data", "root", "transform"]
)
def test_partial_or_unknown_scene_has_no_anchor_and_never_calls_the_getter(missing: str) -> None:
    machine, entry, p, calls = _query()
    address = {
        "room": GOG_BUILD.address("vr.room_global"),
        "scene_type": p["room"],
        "actor": p["room"] + 0x58,
        "model": p["actor"] + 0x64,
        "data": p["model"] + 0xB0,
        "root": p["data"] + 4,
        "transform": p["model"] + 0xB8,
    }[missing]
    machine.mem_write(address, bytes(4))
    assert _call(machine, entry, p["output"]) == 0
    assert calls == []
    assert bytes(machine.mem_read(p["output"], 32)) == struct.pack("<I", 32) + bytes(28)


@pytest.mark.parametrize("changed", ["scene", "actor", "model"])
def test_changes_during_native_evaluation_invalidate_the_complete_snapshot(changed: str) -> None:
    machine, entry, p, _calls = _query()
    native = GOG_BUILD.site("vr.protagonist_position").va
    address = {
        "scene": GOG_BUILD.address("vr.room_global"),
        "actor": p["room"] + 0x58,
        "model": p["actor"] + 0x64,
    }[changed]

    def change_owner(current: Uc, instruction: int, _size: int, _context: object) -> None:
        if instruction == native:
            current.mem_write(address, bytes(4))

    machine.hook_add(UC_HOOK_CODE, change_owner)
    assert _call(machine, entry, p["output"]) == 0
    assert bytes(machine.mem_read(p["output"], 32)) == struct.pack("<I", 32) + bytes(28)


@pytest.mark.parametrize("offset", [16, 20, 24, 28])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_native_coordinates_or_heading_are_rejected(offset: int, value: float) -> None:
    machine, entry, p, _calls = _query()
    native = GOG_BUILD.site("vr.protagonist_position").va

    def invalid_anchor(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == native:
            current.mem_write(p["output"] + offset, struct.pack("<f", value))

    machine.hook_add(UC_HOOK_CODE, invalid_anchor)
    assert _call(machine, entry, p["output"]) == 0
    assert bytes(machine.mem_read(p["output"], 32)) == struct.pack("<I", 32) + bytes(28)


@pytest.mark.parametrize("size", [0, 16, 31, 33, 0xFFFFFFFF])
def test_wrong_sized_output_is_left_untouched(size: int) -> None:
    machine, entry, p, calls = _query()
    before = struct.pack("<I", size) + b"\xcc" * 28
    machine.mem_write(p["output"], before)
    assert _call(machine, entry, p["output"]) == 0
    assert bytes(machine.mem_read(p["output"], 32)) == before
    assert calls == []


def test_null_output_does_not_dereference_it_or_call_the_engine() -> None:
    machine, entry, _p, calls = _query()
    assert _call(machine, entry, 0) == 0
    assert calls == []


@pytest.mark.parametrize("name", VRProtagonistCompiler._anchors)
def test_changed_engine_dependencies_fail_before_mutation(name: str) -> None:
    image = _source(GOG_BUILD)
    image.write_bytes(image.va_to_offset(GOG_BUILD.site(name).va), b"\xcc")
    before = image.to_bytes()
    with pytest.raises(PatchError, match="dependency changed"):
        VRProtagonistCompiler(profile=GOG_BUILD).apply(image)
    assert image.to_bytes() == before
