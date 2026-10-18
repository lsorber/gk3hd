"""Native wall probes use geometry, not screen picking or controller actions."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.binary.x86 import X86Emitter
from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.vr_native_scene import NATIVE_SCENE_TYPES
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from tests.unit.patch.test_complete_compilation import _source
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine

if TYPE_CHECKING:
    from unicorn import Uc


@pytest.mark.parametrize("result", [0, 1])
@pytest.mark.parametrize("scene_type", NATIVE_SCENE_TYPES)
def test_probe_passes_finite_world_segment_without_screen_or_action_filters(
    result: int, scene_type: str
) -> None:
    compiler = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40)
    image = _source(GOG_BUILD)
    compiler.apply(image)
    compiler.postcheck(image)
    abi = compiler.abi(image)
    entry = image.read_u32_va(abi.geometry_query_slot_va)
    machine = _machine(image)
    room, widget, renderer = (_HEAP + offset for offset in (0x1000, 0x2000, 0x3000))
    start, end, hit = (_HEAP + offset for offset in (0x4000, 0x4020, 0x4040))
    handle = 17
    words = {
        GOG_BUILD.address("vr.room_global"): room,
        room: GOG_BUILD.address(scene_type),
        room + 0x50: widget,
        widget + 0x2C: handle,
        GOG_BUILD.address("vr.renderer_global"): renderer,
    }
    for address, value in words.items():
        machine.mem_write(address, struct.pack("<I", value))
    camera = bytes(range(208))
    machine.mem_write(renderer + 0x100, camera)
    segment = struct.pack("<6f", 10, 20, 30, 40, 50, 60)
    machine.mem_write(start, segment[:12])
    machine.mem_write(end, segment[12:])
    seen = []
    native = GOG_BUILD.site("vr.geometry_segment").va
    machine.mem_write(native, b"\xb8" + struct.pack("<I", result) + b"\xc2\x28\x00")
    machine.mem_write(
        GOG_BUILD.site("vr.geometry_actor_enumerate").va, bytes.fromhex("b8 01 00 00 00 c2 08 00")
    )

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address != native:
            return
        assert current.reg_read(UC_X86_REG_ECX) == renderer
        stack = current.reg_read(UC_X86_REG_ESP)
        args = struct.unpack("<10I", current.mem_read(stack + 4, 40))
        seen.append(args)
        current.mem_write(hit, struct.pack("<3f", 25, 35, 45))

    machine.hook_add(UC_HOOK_CODE, observe)
    machine.mem_write(_STACK, struct.pack("<5I", _RETURN, 123, start, end, hit))
    machine.reg_write(UC_X86_REG_ESP, _STACK)
    machine.reg_write(UC_X86_REG_EBX, 999)
    machine.emu_start(entry, _RETURN, count=1000)
    assert seen == [(handle, start, end, 0, 0, hit, 0, 0, 0, 0)]
    assert machine.reg_read(UC_X86_REG_EAX) == result
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 20
    assert machine.reg_read(UC_X86_REG_EBX) == 999
    assert bytes(machine.mem_read(renderer + 0x100, 208)) == camera
    assert bytes(machine.mem_read(start, 12)) + bytes(machine.mem_read(end, 12)) == segment


def _model_queries(
    machine: Uc, renderer: int, hit: int, bsp: int | None, models: list[tuple[int, bool]]
) -> list[tuple[int, float]]:
    native = GOG_BUILD.site("vr.geometry_segment").va
    actors = GOG_BUILD.site("vr.geometry_actor_segment").va
    enumerate_models = GOG_BUILD.site("vr.geometry_actor_enumerate").va
    machine.mem_write(native, b"\xb8" + struct.pack("<I", bsp is not None) + b"\xc2\x28\x00")
    machine.mem_write(actors, bytes.fromhex("8b 44 24 04 c2 28 00"))
    handles = [0xF50000, 0xF60001]  # Slot zero is valid with its generation tag.
    enumerator = X86Emitter(base_va=enumerate_models)
    enumerator.raw(bytes.fromhex("55 8b ec 56 57 8b 75 08 8b 7d 0c"))
    for handle in handles:
        enumerator.raw(b"\x57")
        enumerator.push_imm32(handle)
        enumerator.raw(bytes.fromhex("ff d6 83 c4 08"))
    enumerator.raw(bytes.fromhex("b8 01 00 00 00 5f 5e c9 c2 08 00"))
    machine.mem_write(enumerate_models, enumerator.build())
    seen: list[tuple[int, float]] = []

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address not in (native, actors, enumerate_models):
            return
        assert current.reg_read(UC_X86_REG_ECX) == renderer
        stack = current.reg_read(UC_X86_REG_ESP)
        if address == native:
            if bsp is not None:
                current.mem_write(hit, struct.pack("<3f", bsp, 0, 0))
            return
        if address != actors:
            return
        out, array, count = struct.unpack("<3I", current.mem_read(stack + 4, 12))
        handle = struct.unpack("<I", current.mem_read(array, 4))[0]
        origin = struct.unpack("<3f", current.mem_read(stack + 16, 12))
        endpoint = struct.unpack("<3f", current.mem_read(stack + 28, 12))
        destination = struct.unpack("<I", current.mem_read(stack + 40, 4))[0]
        assert count == 1
        assert origin == (0, 0, 0)
        assert destination == hit
        seen.append((handle, endpoint[0]))
        distance, visible = models[handles.index(handle)]
        accepted = visible and distance <= endpoint[0]
        current.mem_write(out, struct.pack("<I", handle if accepted else 0))
        if accepted:
            current.mem_write(hit, struct.pack("<3f", distance, 0, 0))

    machine.hook_add(UC_HOOK_CODE, observe)
    return seen


@pytest.mark.parametrize(
    ("bsp", "models", "expected"),
    [
        (None, [(80, True), (20, True)], 20),
        (None, [(20, True), (80, True)], 20),
        (60, [(80, True), (20, True)], 20),
        (10, [(80, True), (20, True)], 10),
        (None, [(20, False), (80, True)], 80),
        (None, [(20, False), (80, False)], None),
        (None, [(120, True), (130, True)], None),
    ],
)
def test_visible_models_and_scenery_share_the_nearest_finite_segment(
    bsp: int | None, models: list[tuple[int, bool]], expected: int | None
) -> None:
    compiler = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40)
    image = _source(GOG_BUILD)
    compiler.apply(image)
    abi = compiler.abi(image)
    machine = _machine(image)
    room, widget, renderer = (_HEAP + offset for offset in (0x1000, 0x2000, 0x3000))
    start, end, hit = (_HEAP + offset for offset in (0x4000, 0x4020, 0x4040))
    for address, value in {
        GOG_BUILD.address("vr.room_global"): room,
        room: GOG_BUILD.address("vr.user_scene_vtable"),
        room + 0x50: widget,
        widget + 0x2C: 17,
        GOG_BUILD.address("vr.renderer_global"): renderer,
    }.items():
        machine.mem_write(address, struct.pack("<I", value))
    segment = struct.pack("<6f", 0, 0, 0, 100, 0, 0)
    machine.mem_write(start, segment[:12])
    machine.mem_write(end, segment[12:])
    camera = bytes(range(208))
    machine.mem_write(renderer + 0x100, camera)
    seen = _model_queries(machine, renderer, hit, bsp, models)
    machine.mem_write(_STACK, struct.pack("<5I", _RETURN, 123, start, end, hit))
    machine.reg_write(UC_X86_REG_ESP, _STACK)
    for register, value in ((UC_X86_REG_EBX, 999), (UC_X86_REG_ESI, 888), (UC_X86_REG_EDI, 777)):
        machine.reg_write(register, value)
    machine.emu_start(image.read_u32_va(abi.geometry_query_slot_va), _RETURN, count=1000)
    assert machine.reg_read(UC_X86_REG_EAX) == int(expected is not None)
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 20
    for register, value in ((UC_X86_REG_EBX, 999), (UC_X86_REG_ESI, 888), (UC_X86_REG_EDI, 777)):
        assert machine.reg_read(register) == value
    assert len(seen) == len(models)
    assert seen[0][1] == (bsp if bsp is not None else 100)
    if expected is not None:
        assert struct.unpack("<3f", machine.mem_read(hit, 12)) == (expected, 0, 0)
    assert bytes(machine.mem_read(start, 12)) + bytes(machine.mem_read(end, 12)) == segment
    assert bytes(machine.mem_read(renderer + 0x100, 208)) == camera


def test_repeated_probes_follow_live_model_motion_and_visibility() -> None:
    compiler = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40)
    image = _source(GOG_BUILD)
    compiler.apply(image)
    abi = compiler.abi(image)
    machine = _machine(image)
    room, widget, renderer = (_HEAP + offset for offset in (0x1000, 0x2000, 0x3000))
    start, end, hit = (_HEAP + offset for offset in (0x4000, 0x4020, 0x4040))
    for address, value in {
        GOG_BUILD.address("vr.room_global"): room,
        room: GOG_BUILD.address("vr.user_scene_vtable"),
        room + 0x50: widget,
        widget + 0x2C: 17,
        GOG_BUILD.address("vr.renderer_global"): renderer,
    }.items():
        machine.mem_write(address, struct.pack("<I", value))
    segment = struct.pack("<6f", 0, 0, 0, 100, 0, 0)
    machine.mem_write(start, segment[:12])
    machine.mem_write(end, segment[12:])
    camera = bytes(range(208))
    machine.mem_write(renderer + 0x100, camera)
    models = [(20, True), (120, False)]
    seen = _model_queries(machine, renderer, hit, None, models)
    entry = image.read_u32_va(abi.geometry_query_slot_va)
    # Reuse the same installed adapter and caller endpoints across frames.
    # Movement outside the segment and hiding must not retain a previous hit;
    # returning to the segment must use the current triangle, not a cached point.
    for distance, visible, expected in (
        (20, True, 20),
        (120, True, None),
        (40, True, 40),
        (40, False, None),
        (20, True, 20),
    ):
        models[0] = (distance, visible)
        seen.clear()
        machine.mem_write(_STACK, struct.pack("<5I", _RETURN, 123, start, end, hit))
        machine.reg_write(UC_X86_REG_ESP, _STACK)
        machine.emu_start(entry, _RETURN, count=1000)
        assert machine.reg_read(UC_X86_REG_EAX) == int(expected is not None)
        assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 20
        assert len(seen) == len(models)
        if expected is not None:
            assert struct.unpack("<3f", machine.mem_read(hit, 12)) == (expected, 0, 0)
        assert bytes(machine.mem_read(start, 12)) + bytes(machine.mem_read(end, 12)) == segment
        assert bytes(machine.mem_read(renderer + 0x100, 208)) == camera


@pytest.mark.parametrize(
    "missing", ["room", "room_type", "widget", "geometry", "renderer", "from", "to", "hit"]
)
def test_unavailable_probe_fails_closed_without_native_call(missing: str) -> None:
    compiler = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40)
    image = _source(GOG_BUILD)
    compiler.apply(image)
    abi = compiler.abi(image)
    entry = image.read_u32_va(abi.geometry_query_slot_va)
    machine = _machine(image)
    room, widget, renderer, point = (_HEAP + offset for offset in (0x1000, 0x2000, 0x3000, 0x4000))
    for name, address, value in (
        ("room", GOG_BUILD.address("vr.room_global"), room),
        ("room_type", room, GOG_BUILD.address("vr.user_scene_vtable")),
        ("widget", room + 0x50, widget),
        ("geometry", widget + 0x2C, 17),
        ("renderer", GOG_BUILD.address("vr.renderer_global"), renderer),
    ):
        machine.mem_write(address, struct.pack("<I", 0 if missing == name else value))
    args = [0 if missing == name else point for name in ("from", "to", "hit")]
    machine.mem_write(_STACK, struct.pack("<5I", _RETURN, 123, *args))
    machine.reg_write(UC_X86_REG_ESP, _STACK)
    machine.emu_start(entry, _RETURN, count=1000)
    assert machine.reg_read(UC_X86_REG_EAX) == 0xFFFFFFFF
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 20
