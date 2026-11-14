"""Scene retirement hides outgoing VR content without changing native teardown."""

from __future__ import annotations

import struct
from functools import partial
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE
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

from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.vr_loading import VRLoadingCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError
from gk3hd.vr import compiler as vr_compiler
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine

if TYPE_CHECKING:
    from unicorn import Uc

    from gk3hd.patch.builds import BuildProfile
    from gk3hd.vr.compiler import VRProgram

# Reuse the immutable, per-supported-profile compiled behavioral fixtures.
pytest_plugins = ("tests.unit.vr.test_compiler",)

_CALLBACK = _HEAP + 0x800
_WRAPPER = _HEAP + 0x1000
_DEVICE = _HEAP + 0x2000
_OWNER = _HEAP + 0x400
_CREATION = ("vr.scene_create", "vr.scene_owner_create")
_RESOURCE = "vr.scene_resource_retire"
_MANAGER, _ENGINE, _SERVICES = (_HEAP + offset for offset in (0x5000, 0x6000, 0x7000))


@pytest.fixture(scope="module")
def prewarmed_baseline(flat_bytes: tuple[bytes, BuildProfile]) -> VRProgram:
    data, profile = flat_bytes
    with pytest.MonkeyPatch.context() as context:
        context.setattr(
            vr_compiler, "VRSceneCompiler", partial(VRSceneCompiler, prewarm_scene=True)
        )
        return vr_compiler.compile_vr(PEFile(data), profile=profile, units_per_meter=40)


def _compiler(program: VRProgram) -> VRLoadingCompiler:
    return VRLoadingCompiler(
        profile=GOG_BUILD, panel=program.panel, scene=program.scene, text=program.text
    )


def _setup(program: VRProgram, case: str, result: int, site_name: str = "vr.scene_retire") -> Uc:
    machine = _machine(program.image)
    compiler = _compiler(program)
    profile = compiler.profile

    def word(address: int, value: int) -> None:
        machine.mem_write(address, struct.pack("<I", value))

    word(program.panel.enabled_va, case != "panel_disabled")
    word(program.scene.enabled_va, case != "world_disabled")
    word(profile.address("vr.room_global"), _HEAP if case != "inactive_scene" else _HEAP + 0x400)
    if site_name in _CREATION and case != "live_scene":
        word(profile.address("vr.room_global"), 0)
    word(profile.address("vr.scene_owner_global"), _OWNER if case == "live_owner" else 0)
    word(_OWNER + 0x14, 0 if case == "missing_scene" else _HEAP)
    if site_name == _RESOURCE and case == "inactive_scene":
        word(profile.address("vr.room_global"), 0)
        word(profile.address("vr.scene_owner_global"), _OWNER)
    if site_name == _RESOURCE and case == "absent_scene":
        word(profile.address("vr.room_global"), 0)
    word(profile.address("engine.loop"), 0 if case == "missing_engine" else _ENGINE)
    word(_ENGINE + 0x444, 0 if case == "missing_services" else _SERVICES)
    word(
        _SERVICES + 0x60,
        0 if case == "missing_manager" else _MANAGER + 4 if case == "foreign_manager" else _MANAGER,
    )
    word(_HEAP, profile.address("vr.user_scene_vtable") if case != "unknown_scene" else 0x12345678)
    word(program.panel.renderer_bridge_slot_va, 0 if case == "missing_bridge" else _CALLBACK)
    word(
        profile.address("high_resolution_3d.render_wrapper_ptr"),
        0 if case == "no_wrapper" else _WRAPPER,
    )
    word(_WRAPPER + 0x4E8, 0 if case == "no_device" else _DEVICE)
    machine.mem_write(_CALLBACK, b"\xb8" + struct.pack("<I", result) + bytes.fromhex("c2 0c 00"))
    machine.mem_write(program.panel.frame_va + 28, b"a" * 160)
    machine.mem_write(program.scene.world_input_va + 4, b"b" * 176)
    machine.mem_write(program.scene.target_va + 4, b"c" * 20)
    for address in (
        program.scene.frame_pending_va,
        program.text.focus_va,
        program.text.layer_va,
        program.text.request_va,
    ):
        word(address, 123)
    machine.mem_write(
        profile.site(site_name).va + 5,
        bytes.fromhex("5f 5e 5b c3") if site_name == _RESOURCE else b"\xc3",
    )
    for register, value in (
        (UC_X86_REG_EBX, 456),
        (
            UC_X86_REG_ECX,
            _MANAGER
            if site_name == _RESOURCE
            else _OWNER
            if site_name == "vr.scene_owner_retire"
            else _HEAP,
        ),
        (UC_X86_REG_EDX, 789),
        (UC_X86_REG_EBP, 321),
        (UC_X86_REG_ESI, 654),
        (UC_X86_REG_EDI, 987),
        (UC_X86_REG_EFLAGS, 0x446),
    ):
        machine.reg_write(register, value)
    return machine


def _execute(
    program: VRProgram, case: str, result: int, site_name: str = "vr.scene_retire"
) -> tuple[Uc, list[tuple[int, ...]]]:
    machine = _setup(program, case, result, site_name)
    if site_name in _CREATION:
        # Prove the loading hook never reads the incoming, uninitialized object.
        machine.reg_write(UC_X86_REG_ECX, 0xDEAD0000)
    if site_name == _RESOURCE and case == "missing_manager":
        machine.reg_write(UC_X86_REG_ECX, 0)
    calls: list[tuple[int, ...]] = []

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == _CALLBACK:
            stack = current.reg_read(UC_X86_REG_ESP)
            calls.append(struct.unpack("<3I", current.mem_read(stack + 4, 12)))

    machine.hook_add(UC_HOOK_CODE, observe)
    native = _compiler(program).profile.site(site_name)
    scene_before = bytes(machine.mem_read(_HEAP, 64))
    owner_before = bytes(machine.mem_read(_OWNER, 64))
    manager_before = bytes(machine.mem_read(_MANAGER, 0x100))
    eax_before = machine.reg_read(UC_X86_REG_EAX)
    machine.emu_start(native.va, _RETURN, count=2000)
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 4
    assert machine.reg_read(UC_X86_REG_EAX) == (
        eax_before if site_name == _RESOURCE else struct.unpack("<I", native.original[1:])[0]
    )
    assert machine.reg_read(UC_X86_REG_EBX) == 456
    assert machine.reg_read(UC_X86_REG_ECX) == (
        0xDEAD0000
        if site_name in _CREATION
        else 0
        if site_name == _RESOURCE and case == "missing_manager"
        else _MANAGER
        if site_name == _RESOURCE
        else _OWNER
        if site_name == "vr.scene_owner_retire"
        else _HEAP
    )
    assert machine.reg_read(UC_X86_REG_EDX) == 789
    assert machine.reg_read(UC_X86_REG_EBP) == 321
    assert machine.reg_read(UC_X86_REG_ESI) == 654
    assert machine.reg_read(UC_X86_REG_EDI) == 987
    assert machine.reg_read(UC_X86_REG_EFLAGS) == 0x446
    assert bytes(machine.mem_read(_HEAP, 64)) == scene_before
    assert bytes(machine.mem_read(_OWNER, 64)) == owner_before
    assert bytes(machine.mem_read(_MANAGER, 0x100)) == manager_before
    return machine, calls


@pytest.mark.parametrize("result", [0, 1, 0x80004005])
@pytest.mark.parametrize(
    "site_name",
    [
        "vr.scene_retire",
        "vr.scene_create",
        "vr.scene_owner_retire",
        "vr.scene_owner_create",
        _RESOURCE,
    ],
)
def test_active_scene_retires_content_and_pending_input(
    compiled_baseline: VRProgram, result: int, site_name: str
) -> None:
    program = compiled_baseline
    machine, calls = _execute(program, "active", result, site_name)
    abi = _compiler(program).abi(program.image)
    assert calls == [(_DEVICE, 7, 0)]
    assert struct.unpack("<I", machine.mem_read(abi.calls_va, 4))[0] == 1
    assert struct.unpack("<I", machine.mem_read(abi.result_va, 4))[0] == result
    assert struct.unpack("<I", machine.mem_read(abi.cleared_frames_va, 4))[0] == (result == 0)
    assert bytes(machine.mem_read(program.panel.frame_va + 28, 160)) == bytes(160)
    assert bytes(machine.mem_read(program.scene.world_input_va + 4, 176)) == bytes(176)
    assert bytes(machine.mem_read(program.scene.target_va + 4, 20)) == b"\xff" * 4 + bytes(16)
    assert struct.unpack("<I", machine.mem_read(program.scene.world_input_va, 4))[0] == 180
    assert struct.unpack("<I", machine.mem_read(program.scene.target_va, 4))[0] == 24
    for address in (
        program.scene.frame_pending_va,
        program.text.focus_va,
        program.text.layer_va,
        program.text.request_va,
    ):
        assert bytes(machine.mem_read(address, 4)) == bytes(4)
    for address in (program.panel.enabled_va, program.scene.enabled_va):
        assert struct.unpack("<I", machine.mem_read(address, 4))[0] == 1


@pytest.mark.parametrize(
    "site_name",
    [
        "vr.scene_retire",
        "vr.scene_create",
        "vr.scene_owner_retire",
        "vr.scene_owner_create",
        _RESOURCE,
    ],
)
def test_scene_retirement_invalidates_resource_prewarm_without_resetting_history(
    prewarmed_baseline: VRProgram, site_name: str
) -> None:
    program = prewarmed_baseline
    machine = _setup(program, "active", 0, site_name)
    assert program.scene.prewarm_owner_va is not None
    assert program.scene.prewarm_count_va is not None
    machine.mem_write(program.scene.prewarm_owner_va, struct.pack("<I", _HEAP))
    machine.mem_write(program.scene.prewarm_count_va, struct.pack("<I", 3))
    machine.emu_start(GOG_BUILD.site(site_name).va, _RETURN, count=2000)
    assert bytes(machine.mem_read(program.scene.prewarm_owner_va, 4)) == bytes(4)
    assert struct.unpack("<I", machine.mem_read(program.scene.prewarm_count_va, 4))[0] == 3
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 4


@pytest.mark.parametrize(
    "case",
    [
        "panel_disabled",
        "world_disabled",
        "inactive_scene",
        "unknown_scene",
        "missing_bridge",
        "no_wrapper",
        "no_device",
    ],
)
@pytest.mark.parametrize("site_name", ["vr.scene_retire", "vr.scene_owner_retire", _RESOURCE])
def test_unowned_or_dormant_retirement_preserves_native_behavior(
    compiled_baseline: VRProgram, case: str, site_name: str
) -> None:
    program = compiled_baseline
    machine, calls = _execute(program, case, 0, site_name)
    abi = _compiler(program).abi(program.image)
    assert not calls
    assert bytes(machine.mem_read(abi.calls_va, 12)) == bytes(12)
    assert bytes(machine.mem_read(program.panel.frame_va + 28, 160)) == b"a" * 160
    assert bytes(machine.mem_read(program.scene.world_input_va + 4, 176)) == b"b" * 176
    assert struct.unpack("<I", machine.mem_read(program.text.request_va, 4))[0] == 123


@pytest.mark.parametrize(
    "case",
    ["panel_disabled", "world_disabled", "live_scene", "missing_bridge", "no_wrapper", "no_device"],
)
@pytest.mark.parametrize("site_name", _CREATION)
def test_initial_loading_does_not_interfere_with_live_or_dormant_play(
    compiled_baseline: VRProgram, case: str, site_name: str
) -> None:
    program = compiled_baseline
    machine, calls = _execute(program, case, 0, site_name)
    abi = _compiler(program).abi(program.image)
    assert not calls
    assert bytes(machine.mem_read(abi.calls_va, 12)) == bytes(12)
    assert bytes(machine.mem_read(program.panel.frame_va + 28, 160)) == b"a" * 160
    assert bytes(machine.mem_read(program.scene.world_input_va + 4, 176)) == b"b" * 176


@pytest.mark.parametrize(
    "case", ["missing_engine", "missing_services", "missing_manager", "foreign_manager"]
)
def test_resource_retirement_requires_the_active_location_manager(
    compiled_baseline: VRProgram, case: str
) -> None:
    machine, calls = _execute(compiled_baseline, case, 0, _RESOURCE)
    assert not calls
    assert bytes(machine.mem_read(compiled_baseline.panel.frame_va + 28, 160)) == b"a" * 160


def test_resource_retirement_covers_scene_less_map_travel(
    compiled_baseline: VRProgram,
) -> None:
    machine, calls = _execute(compiled_baseline, "absent_scene", 0, _RESOURCE)
    assert calls == [(_DEVICE, 7, 0)]
    assert bytes(machine.mem_read(compiled_baseline.panel.frame_va + 28, 160)) == bytes(160)
    assert bytes(machine.mem_read(compiled_baseline.scene.world_input_va + 4, 176)) == bytes(176)


@pytest.mark.parametrize("site_name", ["vr.scene_owner_create", "vr.scene_owner_retire"])
def test_early_loading_rejects_live_owner_or_missing_active_scene(
    compiled_baseline: VRProgram, site_name: str
) -> None:
    case = "live_owner" if site_name.endswith("create") else "missing_scene"
    machine, calls = _execute(compiled_baseline, case, 0, site_name)
    assert not calls
    assert bytes(machine.mem_read(compiled_baseline.panel.frame_va + 28, 160)) == b"a" * 160


@pytest.mark.parametrize(
    "changed",
    [
        "payload",
        "native_context",
        "entry",
        "initial_context",
        "initial_entry",
        "owner_context",
        "owner_entry",
        "owner_create_context",
        "owner_create_entry",
        "resource_prefix",
        "resource_context",
        "resource_entry",
    ],
)
def test_loading_verification_rejects_changed_ownership_boundary(
    compiled_baseline: VRProgram, changed: str
) -> None:
    image = compiled_baseline.image.clone()
    compiler = _compiler(compiled_baseline)
    addresses = {
        "payload": compiler.abi(image).calls_va,
        "native_context": compiler.profile.site("vr.scene_retire").va + 5,
        "entry": compiler.profile.site("vr.scene_retire").va,
        "initial_context": compiler.profile.site("vr.scene_create").va + 5,
        "initial_entry": compiler.profile.site("vr.scene_create").va,
        "owner_context": compiler.profile.site("vr.scene_owner_retire").va + 5,
        "owner_entry": compiler.profile.site("vr.scene_owner_retire").va,
        "owner_create_context": compiler.profile.site("vr.scene_owner_create").va + 5,
        "owner_create_entry": compiler.profile.site("vr.scene_owner_create").va,
        "resource_prefix": compiler.profile.site(_RESOURCE).va - 1,
        "resource_context": compiler.profile.site(_RESOURCE).va + 5,
        "resource_entry": compiler.profile.site(_RESOURCE).va,
    }
    image.write_bytes(image.va_to_offset(addresses[changed]), b"\xcc")
    with pytest.raises(PatchError):
        compiler.postcheck(image)
