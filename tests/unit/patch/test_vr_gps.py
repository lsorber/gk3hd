"""Execute GPS publication, native order and withdrawal, not duplicated math."""

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

from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.runtime2d.gps import (
    AUXILIARY_FIELD,
    DRAW_SITES,
    MEMBER_FIELDS,
    native_gps_hooks,
)
from gk3hd.patch.definitions.vr_gps import VRGPSCompiler
from gk3hd.vr.compiler import compile_vr
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine
from tests.unit.vr import test_compiler as fixtures

if TYPE_CHECKING:
    from unicorn import Uc

    from gk3hd.patch.builds import BuildProfile
    from gk3hd.vr.compiler import VRProgram

_SCENE, _ROOM, _CHILDREN, _OWNER, _SURFACE, _FRAME, _AUX = (
    _HEAP + offset for offset in (0x1000, 0x2000, 0x3000, 0x4000, 0x5000, 0x6000, 0x8000)
)
_VTABLE, _RELEASE, _READABLE, _DRAW = (
    _HEAP + offset for offset in (0x5100, 0x5200, 0xD000, 0xD100)
)

flat_bytes = fixtures.flat_bytes


def _write(cpu: Uc, address: int, *values: int) -> None:
    cpu.mem_write(
        address, struct.pack(f"<{len(values)}I", *(value & 0xFFFFFFFF for value in values))
    )


def _words(cpu: Uc, address: int, count: int = 1) -> tuple[int, ...]:
    return struct.unpack(f"<{count}I", cpu.mem_read(address, count * 4))


@pytest.fixture(scope="module")
def gps_program(flat_bytes: tuple[bytes, BuildProfile]) -> tuple[VRProgram, BuildProfile]:
    data, profile = flat_bytes
    return compile_vr(PEFile(data), profile=profile, units_per_meter=40), profile


class _GPSMachine:
    """Real compiled x86 with only native read/Draw/COM callbacks substituted."""

    def __init__(
        self, program: VRProgram, profile: BuildProfile, size: tuple[int, int] = (1280, 800)
    ) -> None:
        self.cpu = _machine(program.image)
        self.profile = profile
        self.compiler = VRGPSCompiler(profile=profile, world_enabled_va=program.scene.enabled_va)
        self.abi = self.compiler.abi(program.image)
        self.base = self.abi.enabled_va - self.compiler._enabled
        self.cache = self.abi.cache_va
        self.hooks = native_gps_hooks(program.image, profile)
        self.releases = 0
        self.drawn: list[int] = []
        self.unreadable = 0
        self.mutate_after_draw = False
        cpu = self.cpu
        for address, values in (
            (self.abi.enabled_va, (1,)),
            (program.scene.enabled_va, (1,)),
            (self.hooks.owner_va, (_SCENE,)),
            (profile.address("vr.room_global"), (_SCENE,)),
            (_SCENE, (profile.address("vr.coordinate_device_scene_vtable"),)),
            (_ROOM, (profile.address("vr.room_layer_vtable"),)),
            (profile.address("high_resolution_3d.directdraw_ptr"), (_OWNER,)),
            (profile.address("display.dimensions"), size),
            (_SURFACE, (_VTABLE,)),
            (_VTABLE + 8, (_RELEASE,)),
            (profile.address("win32.IsBadReadPtr"), (_READABLE,)),
            (_FRAME, (188, 0, *size)),
            (_FRAME + 188, (2,)),
            (self.cache, (1, _SURFACE, *size, _OWNER, 0)),
            (self.cache + 32, (_SCENE + MEMBER_FIELDS[0],)),
            (self.cache + 0x70, (1,)),
        ):
            _write(cpu, address, *values)
        generation = TransitionFrameCompiler.runtime_abi(program.image).successful_flip_count_va
        _write(cpu, generation, 17)
        _write(cpu, self.cache + 0x78, 17)
        _write(cpu, _SCENE + AUXILIARY_FIELD, _AUX)
        for index, field in enumerate(MEMBER_FIELDS):
            kind = (0, 0, 0, 0, 1, 2, 2)[index]
            _write(cpu, _SCENE + field, profile.site(DRAW_SITES[kind]).va - 0xA0)
            _write(cpu, _SCENE + field + 0x18, 1)
        _write(cpu, _AUX, profile.site(DRAW_SITES[3]).va - 0xA0)
        _write(cpu, _AUX + 0x18, 1)
        self.rectangle((2, 2, 224, 334))
        self.children([_SCENE + field for field in MEMBER_FIELDS] + [_AUX])
        cpu.mem_write(
            profile.address("ui.current_layer"), b"\xb8" + struct.pack("<I", _ROOM) + b"\xc3"
        )
        cpu.mem_write(_READABLE, bytes.fromhex("c2 08 00"))
        cpu.mem_write(_RELEASE, bytes.fromhex("c2 04 00"))
        cpu.mem_write(_DRAW, bytes.fromhex("c2 08 00"))
        cpu.hook_add(UC_HOOK_CODE, self._native)

    def rectangle(self, rect: tuple[int, int, int, int]) -> None:
        _write(self.cpu, _SCENE + MEMBER_FIELDS[0] + 0x1C, *rect)
        _write(self.cpu, self.cache + 0x180, *rect)

    def children(self, children: list[int]) -> None:
        _write(self.cpu, _ROOM + 0x4C, _CHILDREN, len(children))
        _write(self.cpu, _CHILDREN, *children)

    def _native(self, cpu: Uc, address: int, _size: int, _data: object) -> None:
        if address == _READABLE:
            pointer = _words(cpu, cpu.reg_read(UC_X86_REG_ESP) + 4)[0]
            cpu.reg_write(UC_X86_REG_EAX, int(pointer == self.unreadable))
        elif address == _RELEASE:
            assert _words(cpu, cpu.reg_read(UC_X86_REG_ESP) + 4)[0] == _SURFACE
            assert _words(cpu, self.cache + 4)[0] == 0
            self.releases += 1
        elif address == _DRAW:
            assert _words(cpu, cpu.reg_read(UC_X86_REG_ESP) + 4, 2) == (123, 456)
            self.drawn.append(cpu.reg_read(UC_X86_REG_ECX))
            if self.mutate_after_draw:
                _write(cpu, _ROOM + 0x4C, _CHILDREN + 4)

    def run(self, entry: int, *args: int, this: int = 23) -> int:
        cpu = self.cpu
        preserved = {UC_X86_REG_EBX: 19, UC_X86_REG_EBP: 21, UC_X86_REG_ESI: 25, UC_X86_REG_EDI: 27}
        for register, value in preserved.items():
            cpu.reg_write(register, value)
        cpu.reg_write(UC_X86_REG_ECX, this)
        cpu.reg_write(UC_X86_REG_ESP, _STACK)
        cpu.reg_write(UC_X86_REG_EFLAGS, 0x202)
        _write(cpu, _STACK, _RETURN, *args)
        cpu.emu_start(entry, _RETURN, count=12000)
        assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 4 * (len(args) + 1)
        for register, value in preserved.items():
            assert cpu.reg_read(register) == value
        return cpu.reg_read(UC_X86_REG_EAX)


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "hidden",
        "old_scene",
        "modal",
        "missing",
        "duplicate",
        "class",
        "unreadable",
        "oversized",
    ],
)
def test_probe_requires_a_unique_visible_live_device(
    gps_program: tuple[VRProgram, BuildProfile], fault: str
) -> None:
    machine = _GPSMachine(*gps_program)
    cpu, profile = machine.cpu, machine.profile
    if fault == "hidden":
        _write(cpu, _SCENE + MEMBER_FIELDS[0] + 0x18, 0)
    elif fault == "old_scene":
        _write(cpu, profile.address("vr.room_global"), _SCENE + 0x800)
    elif fault == "modal":
        _write(cpu, _ROOM, 0)
    elif fault == "missing":
        machine.children([_AUX])
    elif fault == "duplicate":
        machine.children([_SCENE + MEMBER_FIELDS[0]] * 2)
    elif fault == "class":
        _write(cpu, _SCENE, 0)
    elif fault == "unreadable":
        machine.unreadable = _SCENE
    elif fault == "oversized":
        _write(cpu, _ROOM + 0x50, 257)
    expected = (
        _SCENE + MEMBER_FIELDS[0]
        if fault == "none"
        else (0 if fault in {"hidden", "old_scene", "modal"} else 0xFFFFFFFF)
    )
    assert machine.run(machine.abi.probe_va) == expected


@pytest.mark.parametrize("height", [600, 768, 800, 2160])
@pytest.mark.parametrize("rect", [(2, 2, 224, 334), (-3, -7, 224, 334)])
def test_publication_uses_native_corner_rounding_and_preserves_existing_parts(
    gps_program: tuple[VRProgram, BuildProfile], height: int, rect: tuple[int, int, int, int]
) -> None:
    machine = _GPSMachine(*gps_program, size=(3840, height))
    machine.rectangle(rect)
    before = bytes(machine.cpu.mem_read(_FRAME + 192, 80))
    assert machine.run(machine.abi.query_va, _FRAME) == 1
    assert _words(machine.cpu, _FRAME + 188)[0] == 3
    assert bytes(machine.cpu.mem_read(_FRAME + 192, 80)) == before
    physical = tuple(edge * height // 768 if height > 768 else edge for edge in rect)
    crop = (max(0, physical[0]), max(0, physical[1]), physical[2], physical[3])
    assert _words(machine.cpu, _FRAME + 192 + 80, 10) == (
        _SURFACE,
        2,
        0,
        *crop,
        *crop[:2],
        0x3F800000,
    )
    assert _words(machine.cpu, _FRAME + 4)[0] & 4


@pytest.mark.parametrize(
    "fault", ["page", "cold", "owner", "dimensions", "moved", "busy", "capacity", "empty"]
)
def test_unqualified_cache_cannot_append_a_partial_or_stale_device(
    gps_program: tuple[VRProgram, BuildProfile], fault: str
) -> None:
    machine = _GPSMachine(*gps_program)
    cpu = machine.cpu
    if fault == "page":
        _write(cpu, machine.cache + 0x78, 16)
    elif fault == "cold":
        _write(cpu, machine.cache + 0x70, 0)
    elif fault == "owner":
        _write(cpu, machine.profile.address("high_resolution_3d.directdraw_ptr"), _OWNER + 4)
    elif fault == "dimensions":
        _write(cpu, machine.profile.address("display.dimensions"), 1281)
    elif fault == "moved":
        _write(cpu, _SCENE + MEMBER_FIELDS[0] + 0x1C, 3)
    elif fault == "busy":
        _write(cpu, machine.cache + 20, 1)
    elif fault == "capacity":
        _write(cpu, _FRAME + 188, 11)
    elif fault == "empty":
        machine.rectangle((2, 2, 2, 334))
    count_before = _words(cpu, _FRAME + 188)[0]
    assert machine.run(machine.abi.query_va, _FRAME) == 0
    assert _words(cpu, _FRAME + 188)[0] == count_before
    assert _words(cpu, _FRAME + 4)[0] & 4 == 0


@pytest.mark.parametrize("busy", [False, True])
@pytest.mark.parametrize("cause", ["hidden", "disabled", "world_disabled", "scene_replaced"])
def test_withdrawal_releases_once_only_after_the_bound_scope_retires(
    gps_program: tuple[VRProgram, BuildProfile], busy: bool, cause: str
) -> None:
    machine = _GPSMachine(*gps_program)
    cpu = machine.cpu
    if cause == "hidden":
        _write(cpu, _SCENE + MEMBER_FIELDS[0] + 0x18, 0)
    elif cause == "disabled":
        _write(cpu, machine.abi.enabled_va, 0)
    elif cause == "world_disabled":
        _write(cpu, machine.abi.world_enabled_va, 0)
    else:
        _write(cpu, machine.profile.address("vr.room_global"), 0)
    _write(cpu, machine.cache + 20, int(busy))
    assert machine.run(machine.abi.query_va, _FRAME) == 1
    assert _words(cpu, machine.cache + 32)[0] == _words(cpu, machine.cache + 0x70)[0] == 0
    assert machine.releases == int(not busy)
    _write(cpu, machine.cache + 20, 0)
    assert machine.run(machine.abi.query_va, _FRAME) == 1
    assert machine.run(machine.abi.query_va, _FRAME) == 1
    assert machine.releases == 1
    assert _words(cpu, _FRAME + 188)[0] == 2


@pytest.mark.parametrize("fault", ["none", "duplicate", "mutation", "class"])
def test_capture_filters_owned_siblings_in_actual_reverse_native_order(
    gps_program: tuple[VRProgram, BuildProfile], fault: str
) -> None:
    machine = _GPSMachine(*gps_program)
    cpu = machine.cpu
    base, text, button = (_SCENE + MEMBER_FIELDS[index] for index in (0, 5, 4))
    children = [text, _HEAP + 0x8500, base, _AUX, button]
    if fault == "duplicate":
        children.insert(0, button)
    machine.children(children)
    assert machine.run(machine.abi.probe_va) == base
    _write(cpu, text + 0x18, 0)
    if fault == "class":
        _write(cpu, _AUX, machine.hooks.bitmap_vtable_va)
    machine.mutate_after_draw = fault == "mutation"
    for name in DRAW_SITES:
        _write(cpu, machine.profile.site(name).va, _DRAW)
    machine.run(machine.base + machine.compiler._group, 123, 456, this=base)
    expected = [button, _AUX, base] if fault in {"none", "duplicate"} else [button]
    assert machine.drawn == expected
    assert _words(cpu, machine.cache + 0x64)[0] == int(fault != "none")


@pytest.mark.parametrize("busy", [False, True])
@pytest.mark.parametrize("same_owner", [False, True])
def test_destruction_preserves_native_calls_and_does_not_release_a_newer_owner(
    gps_program: tuple[VRProgram, BuildProfile], busy: bool, same_owner: bool
) -> None:
    machine = _GPSMachine(*gps_program)
    cpu = machine.cpu
    cpu.mem_write(machine.hooks.destroy_va, bytes.fromhex("b8 d2 04 00 00 c3"))
    _write(cpu, machine.cache + 20, int(busy))
    owner = _SCENE if same_owner else _SCENE + 0x800
    assert machine.run(machine.base + machine.compiler._destroy, this=owner) == 1234
    assert cpu.reg_read(UC_X86_REG_ECX) == owner
    assert cpu.reg_read(UC_X86_REG_EFLAGS) == 0x202
    assert machine.releases == int(same_owner and not busy)
    if same_owner:
        assert _words(cpu, machine.cache)[0] == _words(cpu, machine.cache + 32)[0] == 0
        assert _words(cpu, machine.cache + 0x70)[0] == 0
        _write(cpu, machine.abi.enabled_va, 0)
        _write(cpu, machine.cache + 20, 0)
        assert machine.run(machine.abi.query_va, _FRAME) == 1
        assert machine.releases == 1
    else:
        assert _words(cpu, machine.cache + 4)[0] == _SURFACE


@pytest.mark.parametrize(
    "condition", ["active", "disabled", "world_disabled", "busy", "other_widget", "old_scene"]
)
def test_capture_gate_draws_the_flat_source_once_and_only_captures_its_live_base(
    gps_program: tuple[VRProgram, BuildProfile], condition: str
) -> None:
    machine = _GPSMachine(*gps_program)
    cpu = machine.cpu
    cpu.mem_write(machine.hooks.bitmap_draw_va, bytes.fromhex("b8 d2 04 00 00 c2 08 00"))
    capture = machine.base + machine.compiler._scope
    cpu.mem_write(capture, bytes.fromhex("c2 08 00"))
    base = _SCENE + MEMBER_FIELDS[0]
    if condition == "disabled":
        _write(cpu, machine.abi.enabled_va, 0)
    elif condition == "world_disabled":
        _write(cpu, machine.abi.world_enabled_va, 0)
    elif condition == "busy":
        _write(cpu, machine.cache + 20, 1)
    elif condition == "other_widget":
        base += MEMBER_FIELDS[1] - MEMBER_FIELDS[0]
    elif condition == "old_scene":
        _write(cpu, machine.profile.address("vr.room_global"), 0)
    seen: list[int] = []

    def observe(cpu: Uc, address: int, _size: int, _data: object) -> None:
        if address in {capture, machine.hooks.bitmap_draw_va}:
            seen.append(address)
            assert cpu.reg_read(UC_X86_REG_ECX) == base
            assert _words(cpu, cpu.reg_read(UC_X86_REG_ESP) + 4, 2) == (123, 456)

    cpu.hook_add(UC_HOOK_CODE, observe)
    assert machine.run(machine.base + machine.compiler._draw, 123, 456, this=base) == 1234
    assert seen == [machine.hooks.bitmap_draw_va] + ([capture] if condition == "active" else [])
