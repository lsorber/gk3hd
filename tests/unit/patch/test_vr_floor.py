"""Floor sampling uses the room's designated geometry and preserves native state."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD, SUPPORTED_BUILDS
from gk3hd.patch.definitions.vr_floor import VRFloorCompiler
from gk3hd.patch.definitions.vr_native_scene import NATIVE_SCENE_TYPES
from gk3hd.patch.model import PatchError
from tests.unit.patch.test_complete_compilation import _source
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine

if TYPE_CHECKING:
    from unicorn import Uc

    from gk3hd.patch.builds import BuildProfile


def _query(profile: BuildProfile = GOG_BUILD) -> tuple[Uc, int, dict[str, int]]:
    compiler = VRFloorCompiler(profile=profile)
    image = _source(profile)
    compiler.apply(image)
    compiler.postcheck(image)
    machine = _machine(image)
    pointers = {
        name: _HEAP + offset
        for name, offset in (
            ("room", 0x1000),
            ("widget", 0x2000),
            ("renderer", 0x3000),
            ("start", 0x4000),
            ("end", 0x4020),
            ("hit", 0x4040),
            ("data", 0x5000),
            ("name", 0x6000),
        )
    }
    pointers["handle"] = 0x10000011
    pointers["native"] = profile.site("vr.geometry_segment").va
    words = {
        profile.address("vr.room_global"): pointers["room"],
        pointers["room"]: profile.address("vr.user_scene_vtable"),
        pointers["room"] + 0x50: pointers["widget"],
        pointers["room"] + 0x54: pointers["data"],
        pointers["widget"] + 0x2C: pointers["handle"],
        pointers["data"] + 8: pointers["name"],
        profile.address("vr.renderer_global"): pointers["renderer"],
    }
    for address, value in words.items():
        machine.mem_write(address, struct.pack("<I", value))
    machine.mem_write(pointers["name"], b"r25_floor\0")
    machine.mem_write(pointers["start"], struct.pack("<3f", 278, 61.7, 50))
    machine.mem_write(pointers["end"], struct.pack("<3f", 278, -100, 50))
    machine.mem_write(pointers["hit"], bytes.fromhex("cc") * 12)
    machine.mem_write(pointers["renderer"] + 0x100, bytes(range(208)))
    machine.mem_write(
        _STACK,
        struct.pack("<5I", _RETURN, 123, pointers["start"], pointers["end"], pointers["hit"]),
    )
    machine.reg_write(UC_X86_REG_ESP, _STACK)
    machine.reg_write(UC_X86_REG_EBX, 999)
    return machine, compiler.abi(image).query_va, pointers


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda value: str(value.id))
@pytest.mark.parametrize("result", [0, 1])
def test_floor_query_passes_designated_name_and_preserves_camera_and_segment(
    profile: BuildProfile, result: int
) -> None:
    machine, entry, pointers = _query(profile)
    native = pointers["native"]
    machine.mem_write(native, b"\xb8" + struct.pack("<I", result) + b"\xc2\x28\x00")
    calls: list[tuple[int, ...]] = []

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == native:
            assert current.reg_read(UC_X86_REG_ECX) == pointers["renderer"]
            stack = current.reg_read(UC_X86_REG_ESP)
            calls.append(struct.unpack("<10I", current.mem_read(stack + 4, 40)))
            if result:
                current.mem_write(pointers["hit"], struct.pack("<3f", 278, 0, 50))

    machine.hook_add(UC_HOOK_CODE, observe)
    before = bytes(machine.mem_read(_HEAP, 0x7000))
    machine.emu_start(entry, _RETURN, count=1000)
    assert calls == [
        (
            pointers["handle"],
            pointers["start"],
            pointers["end"],
            0,
            0,
            pointers["hit"],
            pointers["name"],
            0,
            0,
            0,
        )
    ]
    assert machine.reg_read(UC_X86_REG_EAX) == result
    assert machine.reg_read(UC_X86_REG_EBX) == 999
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 20
    after = bytearray(machine.mem_read(_HEAP, 0x7000))
    if result:
        offset = pointers["hit"] - _HEAP
        after[offset : offset + 12] = before[offset : offset + 12]
    assert bytes(after) == before


@pytest.mark.parametrize("scene_type", NATIVE_SCENE_TYPES)
def test_verified_native_room_subclasses_can_sample_their_floor(scene_type: str) -> None:
    machine, entry, pointers = _query()
    machine.mem_write(pointers["room"], struct.pack("<I", GOG_BUILD.address(scene_type)))
    machine.mem_write(pointers["native"], bytes.fromhex("b8 01 00 00 00 c2 28 00"))
    machine.emu_start(entry, _RETURN, count=1000)
    assert machine.reg_read(UC_X86_REG_EAX) == 1


@pytest.mark.parametrize(
    "missing",
    [
        "room",
        "data",
        "name",
        "widget",
        "handle",
        "renderer",
        "start",
        "end",
        "hit",
        "empty_name",
        "unknown_room",
    ],
)
def test_unavailable_floor_does_not_query_unrelated_geometry(missing: str) -> None:
    machine, entry, pointers = _query()
    locations = {
        "room": GOG_BUILD.address("vr.room_global"),
        "data": pointers["room"] + 0x54,
        "name": pointers["data"] + 8,
        "widget": pointers["room"] + 0x50,
        "handle": pointers["widget"] + 0x2C,
        "renderer": GOG_BUILD.address("vr.renderer_global"),
        "start": _STACK + 8,
        "end": _STACK + 12,
        "hit": _STACK + 16,
        "empty_name": pointers["name"],
        "unknown_room": pointers["room"],
    }
    machine.mem_write(locations[missing], bytes(4))
    machine.mem_write(pointers["native"], b"\xcc")
    hit = bytes(machine.mem_read(pointers["hit"], 12))
    machine.emu_start(entry, _RETURN, count=1000)
    assert machine.reg_read(UC_X86_REG_EAX) == 0xFFFFFFFF
    assert bytes(machine.mem_read(pointers["hit"], 12)) == hit


@pytest.mark.parametrize("endpoint", ["start", "end"])
@pytest.mark.parametrize("axis", [0, 1, 2])
@pytest.mark.parametrize("value", [float("inf"), -float("inf"), float("nan")])
def test_nonfinite_segments_are_rejected_before_native_geometry(
    endpoint: str, axis: int, value: float
) -> None:
    machine, entry, pointers = _query()
    machine.mem_write(pointers[endpoint] + axis * 4, struct.pack("<f", value))
    machine.mem_write(pointers["native"], b"\xcc")
    machine.emu_start(entry, _RETURN, count=1000)
    assert machine.reg_read(UC_X86_REG_EAX) == 0xFFFFFFFF


@pytest.mark.parametrize("name", VRFloorCompiler._anchors)
def test_changed_floor_dependencies_reject_install_without_mutation(name: str) -> None:
    image = _source(GOG_BUILD)
    image.write_bytes(image.va_to_offset(GOG_BUILD.site(name).va), b"\xcc")
    before = image.to_bytes()
    with pytest.raises(PatchError, match="dependency changed"):
        VRFloorCompiler(profile=GOG_BUILD).apply(image)
    assert image.to_bytes() == before


@pytest.mark.parametrize(
    "controller", ["vr.user_camera_controller_vtable", "vr.user_scene_controller_vtable"]
)
@pytest.mark.parametrize("floor_result", [0, 1, -1])
@pytest.mark.parametrize(
    "blocked",
    [
        None,
        "missing_loop",
        "missing_scene",
        "missing_manager",
        "unknown_manager",
        "locked",
        "stacked",
        "missing_controller",
        "scripted",
    ],
)
def test_observer_height_is_restricted_to_unlocked_user_camera_ownership(
    controller: str, blocked: str | None, floor_result: int
) -> None:
    machine, floor_entry, pointers = _query()
    # Both entries are returned from the verified ABI, not guessed from code.
    image = _source(GOG_BUILD)
    compiler = VRFloorCompiler(profile=GOG_BUILD)
    compiler.apply(image)
    entry = compiler.abi(image).observer_query_va
    assert compiler.abi(image).query_va == floor_entry
    loop, scene, manager, top = (_HEAP + value for value in (0x7000, 0x7800, 0x8000, 0x9000))
    words = {
        GOG_BUILD.address("engine.loop"): loop,
        loop + 0x444: scene,
        scene + 0x28: manager,
        manager: GOG_BUILD.address("vr.camera_manager_vtable"),
        manager + 0xB0: 1,
        top: GOG_BUILD.address(controller),
    }
    invalid = {
        "missing_loop": GOG_BUILD.address("engine.loop"),
        "missing_scene": loop + 0x444,
        "missing_manager": scene + 0x28,
        "unknown_manager": manager,
        "locked": manager + 0x1C5,
        "stacked": manager + 0xB0,
        "scripted": top,
    }
    if blocked in invalid:
        words[invalid[blocked]] = 1 if blocked == "locked" else 0
    for address, value in words.items():
        machine.mem_write(address, struct.pack("<I", value))
    machine.mem_write(
        GOG_BUILD.site("vr.camera_controller_top").va,
        b"\xb8" + struct.pack("<I", 0 if blocked == "missing_controller" else top) + b"\xc3",
    )
    machine.mem_write(
        pointers["native"],
        b"\xcc" if blocked else b"\xb8" + struct.pack("<i", floor_result) + b"\xc2\x28\x00",
    )
    before = bytes(machine.mem_read(_HEAP, 0xA000))
    machine.emu_start(entry, _RETURN, count=1000)
    assert machine.reg_read(UC_X86_REG_EAX) == (0 if blocked else 1 if floor_result == 1 else 2)
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 20
    assert bytes(machine.mem_read(_HEAP, 0xA000)) == before
