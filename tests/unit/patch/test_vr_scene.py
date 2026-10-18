"""Original-engine eye transactions preserve flat rendering and authored state."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

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

from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter, encode_rel32_branch
from gk3hd.patch.builds import GOG_BUILD, SUPPORTED_BUILDS, BuildProfile
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError
from tests.unit.patch.test_complete_compilation import _source

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
def test_scene_hooks_verify_without_requiring_other_patches(profile: BuildProfile) -> None:
    compiler = VRSceneCompiler(profile=profile, units_per_meter=40)
    image = _source(profile)
    compiler.apply(image)
    compiler.postcheck(image)
    abi = compiler.abi(image)
    assert image.read_u32_va(abi.enabled_va) == 0
    assert image.read_u32_va(abi.submitted_frames_va) == 0
    assert image.read_u32_va(abi.eye_draws_va) == 0
    assert image.read_u32_va(abi.world_input_va) == 180
    assert image.read_u32_va(abi.recenter_va - 4 + 236) == abi.world_input_va
    with pytest.raises(PatchError, match="already installed"):
        compiler.apply(image)


@pytest.mark.parametrize("scale", [0, -1, float("inf"), float("nan"), 1e300, 1e-300])
def test_invalid_scale_is_rejected_before_any_mutation(scale: float) -> None:
    image = _source(GOG_BUILD)
    original = image.to_bytes()
    with pytest.raises(PatchError, match="world scale"):
        VRSceneCompiler(profile=GOG_BUILD, units_per_meter=scale).apply(image)
    assert image.to_bytes() == original


@pytest.mark.parametrize("name", VRSceneCompiler._anchors)
def test_changed_engine_anchors_are_rejected_without_writes(name: str) -> None:
    image = _source(GOG_BUILD)
    image.write_bytes(image.va_to_offset(GOG_BUILD.site(name).va), b"\xcc")
    original = image.to_bytes()
    with pytest.raises(PatchError, match="precheck"):
        VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40).apply(image)
    assert image.to_bytes() == original


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
@pytest.mark.parametrize("name", VRSceneCompiler._geometry_anchors)
def test_changed_geometry_dependency_invalidates_installed_scene(
    profile: BuildProfile, name: str
) -> None:
    compiler = VRSceneCompiler(profile=profile, units_per_meter=40)
    image = _source(profile)
    compiler.apply(image)
    site = profile.site(name)
    image.write_bytes(image.va_to_offset(site.va), b"\xcc")
    with pytest.raises(PatchError, match="VR geometry query changed"):
        compiler.postcheck(image)


def test_unknown_room_detour_is_rejected_without_writes() -> None:
    image = _source(GOG_BUILD)
    transition = TransitionFrameCompiler(profile=GOG_BUILD)
    transition.apply(image)
    site = GOG_BUILD.site("transition.seed_hook")
    image.write_bytes(
        image.va_to_offset(site.va),
        encode_rel32_branch(
            opcode=BranchOpcode.CALL, site_va=site.va, target_va=site.va + 20, size=5
        ),
    )
    original = image.to_bytes()
    with pytest.raises(PatchError, match="unknown room-draw"):
        VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40).apply(image)
    assert image.to_bytes() == original


def test_scene_hooks_compose_with_verified_transition_repair() -> None:
    image = _source(GOG_BUILD)
    transition = TransitionFrameCompiler(profile=GOG_BUILD)
    transition.apply(image)
    transition.postcheck(image)
    compiler = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40)
    compiler.apply(image)
    compiler.postcheck(image)


def test_modified_flat_frame_dependency_is_rejected_before_installation() -> None:
    image = _source(GOG_BUILD)
    transition = TransitionFrameCompiler(profile=GOG_BUILD)
    transition.apply(image)
    entry = transition.room_draw_entry(image)
    image.write_bytes(image.va_to_offset(entry), b"\xcc")
    original = image.to_bytes()
    with pytest.raises(PatchError, match="room draw entry is modified"):
        VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40).apply(image)
    assert image.to_bytes() == original


def test_postcheck_detects_changed_continuation_and_redirect() -> None:
    compiler = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40)
    for name in ("transition.scene_setup_anchor", "vr.camera_setup"):
        image = _source(GOG_BUILD)
        compiler.apply(image)
        image.write_bytes(image.va_to_offset(GOG_BUILD.site(name).va), b"\xcc")
        with pytest.raises(PatchError, match="verification"):
            compiler.postcheck(image)


_HEAP = 0x900000
_STACK = _HEAP + 0xF000
_RETURN = _HEAP + 0xE000
_CAMERA = _HEAP + 0x1000
_RENDERER = _HEAP + 0x2000


def _machine(image: PEFile) -> Uc:
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    end = max(
        image.rva_to_va(section.virtual_address) + section.size_of_raw_data
        for section in image.sections
    )
    machine.mem_map(0x400000, (end - 0x400000 + 0xFFF) & ~0xFFF)
    machine.mem_map(_HEAP, 0x10000)
    for section in image.sections:
        machine.mem_write(
            image.rva_to_va(section.virtual_address),
            image.read_bytes(section.pointer_to_raw_data, section.size_of_raw_data),
        )
    machine.mem_write(_STACK, struct.pack("<3I", _RETURN, 123, 456))
    machine.reg_write(UC_X86_REG_ESP, _STACK)
    return machine


@pytest.mark.parametrize("enabled", [False, True])
def test_non_world_draw_keeps_original_abi_and_arguments(*, enabled: bool) -> None:
    compiler = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40, enabled=enabled)
    image = _source(GOG_BUILD)
    compiler.apply(image)
    machine = _machine(image)
    abi = compiler.abi(image)
    machine.mem_write(abi.world_input_va + 4, struct.pack("<I", 3))
    site = GOG_BUILD.site("transition.seed_hook")
    machine.mem_write(site.va + len(site.original), bytes.fromhex("c2 08 00"))
    registers = {
        UC_X86_REG_ECX: _HEAP + 0x4000,
        UC_X86_REG_EBX: 12,
        UC_X86_REG_ESI: 34,
        UC_X86_REG_EDI: 56,
        UC_X86_REG_EBP: 78,
    }
    for register, value in registers.items():
        machine.reg_write(register, value)
    machine.emu_start(site.va, _RETURN, count=1000)
    assert machine.reg_read(UC_X86_REG_EAX) == 0x613D22
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 12
    for register, value in registers.items():
        assert machine.reg_read(register) == value
    abi = compiler.abi(image)
    assert struct.unpack("<I", machine.mem_read(abi.eye_draws_va, 4))[0] == 0
    assert struct.unpack("<I", machine.mem_read(abi.world_input_va + 4, 4))[0] == 0


@pytest.mark.parametrize("eye_active", [False, True])
def test_projection_scope_restores_authored_camera_and_shared_globals(*, eye_active: bool) -> None:
    compiler = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40)
    image = _source(GOG_BUILD)
    compiler.apply(image)
    machine = _machine(image)
    abi = compiler.abi(image)
    base = abi.enabled_va - compiler._enabled
    camera = bytes(range(208))
    eye = bytes(reversed(range(232)))
    globals_va = GOG_BUILD.address("vr.projection_globals")
    nesting = GOG_BUILD.address("vr.projection_nesting")
    globals_before = bytearray(bytes(range(256)) + bytes(range(28)))
    struct.pack_into("<I", globals_before, nesting - globals_va, 0)
    machine.mem_write(_CAMERA, camera)
    machine.mem_write(base + compiler._eye, eye)
    machine.mem_write(globals_va, bytes(globals_before))
    machine.mem_write(_RENDERER + 0x1C8, struct.pack("<I", _CAMERA))
    machine.mem_write(base + compiler._eye_active, struct.pack("<I", eye_active))
    setup = GOG_BUILD.site("vr.camera_setup")
    end = GOG_BUILD.site("vr.camera_end")
    machine.mem_write(setup.va + len(setup.original), bytes.fromhex("c9 c3"))
    machine.mem_write(
        end.va + len(end.original), b"\xff\x0d" + struct.pack("<I", nesting) + b"\xc3"
    )
    observed = []

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == setup.va + len(setup.original):
            observed.append(bytes(current.mem_read(_CAMERA, 208)))
            current.mem_write(nesting, struct.pack("<I", 1))

    machine.hook_add(UC_HOOK_CODE, observe)
    machine.reg_write(UC_X86_REG_ECX, _RENDERER)
    machine.emu_start(setup.va, _RETURN, count=1000)
    assert observed == [camera[:28] + eye[28:208] if eye_active else camera]
    if eye_active:
        assert bytes(machine.mem_read(globals_va + 0xD8, 24)) == eye[208:232]
    machine.mem_write(_STACK, struct.pack("<I", _RETURN))
    machine.reg_write(UC_X86_REG_ESP, _STACK)
    machine.emu_start(end.va, _RETURN, count=1000)
    assert bytes(machine.mem_read(_CAMERA, 208)) == camera
    assert bytes(machine.mem_read(globals_va, 284)) == globals_before
    assert struct.unpack("<I", machine.mem_read(base + compiler._projection_active, 4))[0] == 0


def _scene_machine(
    outcome: str,
    *,
    deferred: bool = False,
    mirror: bool = False,
    windowed: bool = False,
    prewarm: bool = False,
) -> tuple[Uc, VRSceneCompiler, PEFile]:
    compiler = VRSceneCompiler(
        profile=GOG_BUILD,
        units_per_meter=40,
        enabled=True,
        deferred_frame=deferred,
        mirror_world=mirror,
        prewarm_scene=prewarm,
    )
    image = _source(GOG_BUILD)
    if mirror:
        TransitionFrameCompiler(profile=GOG_BUILD).apply(image)
    compiler.apply(image)
    abi = compiler.abi(image)
    base = abi.enabled_va - compiler._enabled
    _payload, labels = compiler._payload(base, image.read_u32_va(base + compiler._flat_target))
    machine = _machine(image)
    machine.mem_map(0, 0x1000)
    machine.mem_write(0, struct.pack("<I", 0x12345678))
    p = GOG_BUILD
    machine.mem_write(p.address("vr.fullscreen_flag_ptr"), struct.pack("<I", _HEAP + 0xAF00))
    machine.mem_write(_HEAP + 0xAF00, bytes((int(not windowed),)))
    if mirror:
        layer = _HEAP + 0x3500
        machine.mem_write(layer, struct.pack("<I", p.address("transition.room_layer_vtable")))
        machine.mem_write(
            p.address("ui.current_layer"), b"\xb8" + struct.pack("<I", layer) + b"\xc3"
        )

    def word(address: int, value: int) -> None:
        machine.mem_write(address, struct.pack("<I", value))

    room, target, wrapper, device = (_HEAP + offset for offset in (0x3000, 0x4000, 0x5000, 0x6000))
    device_table, viewport, viewport_table = (_HEAP + offset for offset in (0x7000, 0x8000, 0x9000))
    bridge = _HEAP + 0xC000
    for address, value in (
        (p.address("vr.room_global"), room),
        (room + 0x50, target),
        (p.address("vr.renderer_global"), _RENDERER),
        (_RENDERER + 0x1C8, _CAMERA),
        (p.address("high_resolution_3d.render_wrapper_ptr"), wrapper),
        (wrapper + 0x4E8, device),
        (device, device_table),
        (viewport, viewport_table),
        (p.address("high_resolution_3d.display_width_ptr"), _HEAP + 0xA0),
        (p.address("high_resolution_3d.display_height_ptr"), _HEAP + 0xA4),
        (_HEAP + 0xA0, 1024),
        (_HEAP + 0xA4, 768),
        (p.address("win32.GetModuleHandleA"), _HEAP + 0xA000),
        (p.address("win32.GetProcAddress"), _HEAP + 0xB000),
        (device_table + 0x34, _HEAP + 0xD000),
        (viewport_table + 0x50, _HEAP + 0xD200),
        (viewport_table + 0x08, _HEAP + 0xD300),
    ):
        word(address, value)
    camera = bytes(range(208))
    machine.mem_write(_CAMERA, camera)
    machine.mem_write(_HEAP + 0xA000, bytes.fromhex("b8 01 00 00 00 c2 04 00"))
    machine.mem_write(
        _HEAP + 0xB000,
        b"\xb8" + struct.pack("<I", 0 if outcome == "missing_bridge" else bridge) + b"\xc2\x08\x00",
    )
    machine.mem_write(
        _HEAP + 0xD000,
        bytes.fromhex("8b 44 24 08 c7 00")
        + struct.pack("<I", viewport)
        + bytes.fromhex("31 c0 c2 08 00"),
    )
    clear_result = 0x80004005 if outcome == "clear_failure" else 0
    machine.mem_write(_HEAP + 0xD200, b"\xb8" + struct.pack("<I", clear_result) + b"\xc2\x1c\x00")
    machine.mem_write(_HEAP + 0xD300, bytes.fromhex("31 c0 c2 04 00"))
    setup, end, clear = (
        p.site(name) for name in ("vr.camera_setup", "vr.camera_end", "vr.room_clear")
    )
    nesting = p.address("vr.projection_nesting")
    machine.mem_write(
        setup.va + len(setup.original),
        bytes.fromhex("c7 05") + struct.pack("<II", nesting, 1) + bytes.fromhex("c9 c3"),
    )
    machine.mem_write(
        end.va + len(end.original), b"\xff\x0d" + struct.pack("<I", nesting) + b"\xc3"
    )
    machine.mem_write(clear.va + len(clear.original), b"\xc3")
    draw = p.site("transition.seed_hook")
    body = X86Emitter(base_va=draw.va + len(draw.original))
    body.raw(bytes.fromhex("53 89 cb b9") + struct.pack("<I", _RENDERER))
    body.call_absolute(setup.va)
    body.call_absolute(clear.va)
    body.call_absolute(end.va)
    body.raw(bytes.fromhex("5b c2 08 00"))
    machine.mem_write(draw.va + len(draw.original), body.build())
    _host_body(machine, bridge, base, labels["eye_callback"], outcome)
    return machine, compiler, image


def _host_body(machine: Uc, bridge: int, base: int, callback: int, outcome: str) -> None:
    host = X86Emitter(base_va=bridge)
    host.raw(bytes.fromhex("55 8b ec"))
    if outcome == "hidden":
        host.raw(bytes.fromhex("b8 01 00 00 00"))
    else:
        if outcome == "reentrant":
            host.push_imm32(789)
            host.push_imm32(987)
            host.raw(b"\xb9" + struct.pack("<I", _HEAP + 0x4500))
            host.call_absolute(GOG_BUILD.site("transition.seed_hook").va)
        for eye in range(2):
            pointer = _HEAP + 0xB00 + eye * 0x100
            machine.mem_write(pointer, bytes((value + eye) % 256 for value in range(232)))
            # The headset recommends independent eye sizes, not the desktop's
            # 1024x768 frame. The native camera, clip box and clear must agree.
            machine.mem_write(pointer + 0x58, struct.pack("<2I", 1920 + eye * 128, 1800))
            host.push_imm32(pointer)
            host.push_imm32(eye)
            host.push_imm32(base)
            host.call_absolute(callback)
            host.raw(bytes.fromhex("85 c0"))
            host.jump_if(Condition.NOT_EQUAL, "done")
    host.label("done")
    host.raw(bytes.fromhex("c9 c2 08 00"))
    machine.mem_write(bridge, host.build())


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
def test_experimental_resource_prewarm_is_verified_and_initially_dormant(
    profile: BuildProfile,
) -> None:
    compiler = VRSceneCompiler(profile=profile, units_per_meter=40, prewarm_scene=True)
    image = _source(profile)
    compiler.apply(image)
    compiler.postcheck(image)
    abi = compiler.abi(image)
    assert abi.prewarm_owner_va is not None
    assert abi.prewarm_count_va is not None
    assert image.read_u32_va(abi.enabled_va) == 0
    assert image.read_u32_va(abi.prewarm_owner_va) == 0
    assert image.read_u32_va(abi.prewarm_count_va) == 0


def test_resource_prewarm_runs_once_per_owner_and_retires_with_its_lease() -> None:
    machine, compiler, image = _scene_machine("rendered", deferred=True, prewarm=True)
    abi = compiler.abi(image)
    assert abi.prewarm_owner_va is not None
    assert abi.prewarm_count_va is not None
    base = abi.enabled_va - compiler._enabled
    draw = GOG_BUILD.site("transition.seed_hook")
    camera = bytes(machine.mem_read(_CAMERA, 208))
    draws: list[int] = []

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == draw.va + len(draw.original):
            draws.append(struct.unpack("<I", current.mem_read(base + compiler._eye_active, 4))[0])
            stack = current.reg_read(UC_X86_REG_ESP)
            assert struct.unpack("<2I", current.mem_read(stack + 4, 8)) == (123, 456)

    machine.hook_add(UC_HOOK_CODE, observe)
    for retired in (False, False, True):
        if retired:
            machine.mem_write(abi.prewarm_owner_va, bytes(4))
        machine.mem_write(abi.frame_pending_va, bytes(4))
        machine.mem_write(_STACK, struct.pack("<3I", _RETURN, 123, 456))
        machine.reg_write(UC_X86_REG_ESP, _STACK)
        machine.reg_write(UC_X86_REG_ECX, _HEAP + 0x4000)
        machine.emu_start(draw.va, _RETURN, count=10000)
        assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 12
        assert bytes(machine.mem_read(_CAMERA, 208)) == camera
    # Non-mirrored operation still keeps its ordinary center draw after the
    # pair. Resource preparation is the one additional draw on a new lease.
    assert draws == [0, 1, 1, 0, 1, 1, 0, 0, 1, 1, 0]
    assert struct.unpack("<I", machine.mem_read(abi.prewarm_count_va, 4))[0] == 2


@pytest.mark.parametrize("dormant", [False, True])
def test_resource_prewarm_requires_an_active_resolved_scene_bridge(*, dormant: bool) -> None:
    machine, compiler, image = _scene_machine("missing_bridge", deferred=True, prewarm=True)
    abi = compiler.abi(image)
    assert abi.prewarm_count_va is not None
    if dormant:
        machine.mem_write(abi.enabled_va, bytes(4))
    machine.reg_write(UC_X86_REG_ECX, _HEAP + 0x4000)
    machine.emu_start(GOG_BUILD.site("transition.seed_hook").va, _RETURN, count=10000)
    assert struct.unpack("<I", machine.mem_read(abi.prewarm_count_va, 4))[0] == 0
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 12


@pytest.mark.parametrize(
    "outcome", ["rendered", "hidden", "clear_failure", "missing_bridge", "reentrant"]
)
@pytest.mark.parametrize("deferred", [False, True])
def test_engine_bridge_draws_only_requested_eyes_and_always_preserves_flat_frame(
    outcome: str,
    *,
    deferred: bool,
) -> None:
    machine, compiler, image = _scene_machine(outcome, deferred=deferred)
    abi = compiler.abi(image)
    base = abi.enabled_va - compiler._enabled
    draw = GOG_BUILD.site("transition.seed_hook")
    viewport = _HEAP + 0x8000
    camera = bytes(machine.mem_read(_CAMERA, 208))
    draws: list[tuple[int, int, int]] = []
    clears: list[tuple[int, ...]] = []
    # A recenter request cannot accidentally turn off paired completion.
    machine.mem_write(abi.recenter_va, struct.pack("<I", 1))

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == _HEAP + 0xC000:
            assert struct.unpack("<I", current.mem_read(abi.recenter_va, 4))[0] == (
                3 if deferred else 1
            )
        if address == draw.va + len(draw.original):
            stack = current.reg_read(UC_X86_REG_ESP)
            first, second = struct.unpack("<2I", current.mem_read(stack + 4, 8))
            active = struct.unpack("<I", current.mem_read(base + compiler._eye_active, 4))[0]
            draws.append((active, first, second))
        elif address == _HEAP + 0xD200:
            stack = current.reg_read(UC_X86_REG_ESP)
            args = struct.unpack("<7I", current.mem_read(stack + 4, 28))
            assert args[0:2] == (viewport, 1)
            assert args[3] == 3
            clears.append(struct.unpack("<4I", current.mem_read(args[2], 16)))
            width = 1920 + (len(clears) - 1) * 128
            globals_va = GOG_BUILD.address("vr.projection_globals")
            assert struct.unpack("<2I", current.mem_read(globals_va + 0x20, 8)) == (width, 1800)
            assert struct.unpack("<4I", current.mem_read(globals_va + 0x90, 16)) == (
                0,
                0,
                width,
                1800,
            )

    machine.hook_add(UC_HOOK_CODE, observe)
    machine.reg_write(UC_X86_REG_ECX, _HEAP + 0x4000)
    nonvolatile = {UC_X86_REG_EBX: 11, UC_X86_REG_ESI: 22, UC_X86_REG_EDI: 33, UC_X86_REG_EBP: 44}
    for register, value in nonvolatile.items():
        machine.reg_write(register, value)
    machine.emu_start(draw.va, _RETURN, count=10000)
    assert struct.unpack("<I", machine.mem_read(0, 4))[0] == 0x12345678
    expected_eyes = {
        "rendered": 2,
        "hidden": 0,
        "clear_failure": 1,
        "missing_bridge": 0,
        "reentrant": 2,
    }[outcome]
    nested = [(0, 987, 789)] if outcome == "reentrant" else []
    assert draws == nested + [(1, 123, 456)] * expected_eyes + [(0, 123, 456)]
    assert clears == [(0, 0, 1920 + eye * 128, 1800) for eye in range(expected_eyes)]
    assert bytes(machine.mem_read(_CAMERA, 208)) == camera
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 12
    for register, value in nonvolatile.items():
        assert machine.reg_read(register) == value
    frames = struct.unpack("<I", machine.mem_read(abi.submitted_frames_va, 4))[0]
    assert frames == int(outcome in {"rendered", "reentrant"})
    enabled = struct.unpack("<I", machine.mem_read(abi.enabled_va, 4))[0]
    assert enabled == int(outcome in {"rendered", "hidden", "reentrant"})
    if outcome != "missing_bridge":
        assert struct.unpack("<I", machine.mem_read(abi.recenter_va, 4))[0] == (
            2 if deferred else 0
        )


@pytest.mark.parametrize("outcome", ["rendered", "hidden"])
def test_page_repair_does_not_start_another_world_frame_before_completion(outcome: str) -> None:
    machine, compiler, image = _scene_machine(outcome, deferred=True)
    abi = compiler.abi(image)
    draw = GOG_BUILD.site("transition.seed_hook")
    attempts: list[int] = []
    flat_draws: list[int] = []
    base = abi.enabled_va - compiler._enabled

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == _HEAP + 0xC000:
            attempts.append(address)
        elif address == draw.va + len(draw.original):
            active = struct.unpack("<I", current.mem_read(base + compiler._eye_active, 4))[0]
            if not active:
                flat_draws.append(address)

    def invoke() -> None:
        machine.mem_write(_STACK, struct.pack("<3I", _RETURN, 123, 456))
        machine.reg_write(UC_X86_REG_ESP, _STACK)
        machine.reg_write(UC_X86_REG_ECX, _HEAP + 0x4000)
        machine.emu_start(draw.va, _RETURN, count=10000)
        assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 12

    machine.hook_add(UC_HOOK_CODE, observe)
    invoke()
    picking = bytes(machine.mem_read(abi.world_input_va, 180))
    target = bytes(machine.mem_read(abi.target_va, 32))
    invoke()
    assert len(attempts) == 1
    assert len(flat_draws) == 2, "native page repair still receives its ordinary room draw"
    assert bytes(machine.mem_read(abi.world_input_va, 180)) == picking
    assert bytes(machine.mem_read(abi.target_va, 32)) == target
    assert struct.unpack("<I", machine.mem_read(abi.enabled_va, 4))[0] == 1
    # The paired completed-page presenter releases this boundary after end/cancel.
    machine.mem_write(abi.frame_pending_va, struct.pack("<I", 0))
    invoke()
    assert len(attempts) == 2
    assert len(flat_draws) == 3


@pytest.mark.parametrize("outcome", ["rendered", "hidden", "clear_failure", "missing_bridge"])
@pytest.mark.parametrize("windowed", [False, True])
def test_eye_mirror_keeps_native_ownership_and_falls_back_without_a_completed_pair(
    outcome: str,
    windowed: bool,
) -> None:
    machine, compiler, image = _scene_machine(
        outcome, deferred=True, mirror=True, windowed=windowed
    )
    abi = compiler.abi(image)
    base = abi.enabled_va - compiler._enabled
    transition = TransitionFrameCompiler.runtime_abi(image)
    draw = GOG_BUILD.site("transition.seed_hook")
    counts = {"eyes": 0, "center": 0}
    before = bytes(machine.mem_read(_CAMERA, 208))
    cache = _HEAP + 0x4000 + 0x34
    machine.mem_write(cache, struct.pack("<I", 3))

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == _HEAP + 0xC000:
            assert struct.unpack("<I", current.mem_read(abi.recenter_va, 4))[0] == 6
            assert (
                struct.unpack("<I", current.mem_read(transition.room_presentation_active_va, 4))[0]
                == 1
            ), "publish native room ownership before copying the eye"
        if address == draw.va + len(draw.original):
            eye = struct.unpack("<I", current.mem_read(base + compiler._eye_active, 4))[0]
            counts["eyes" if eye else "center"] += 1

    machine.hook_add(UC_HOOK_CODE, observe)
    machine.reg_write(UC_X86_REG_ECX, _HEAP + 0x4000)
    machine.emu_start(draw.va, _RETURN, count=10000)
    assert counts == {
        "eyes": {"rendered": 2, "hidden": 0, "clear_failure": 1, "missing_bridge": 0}[outcome],
        "center": int(outcome != "rendered"),
    }
    assert bytes(machine.mem_read(_CAMERA, 208)) == before
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 12
    if outcome == "rendered":
        assert struct.unpack("<I", machine.mem_read(cache, 4))[0] == 0


def test_mirror_cannot_omit_page_preparation_dependency() -> None:
    image = _source(GOG_BUILD)
    before = image.to_bytes()
    with pytest.raises(PatchError, match="page preparation"):
        VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40, mirror_world=True).apply(image)
    assert image.to_bytes() == before


def test_mirror_prepares_each_native_handoff_page_once_before_publishing_pixels() -> None:
    machine, compiler, image = _scene_machine("rendered", deferred=True, mirror=True)
    abi = compiler.abi(image)
    transition = TransitionFrameCompiler(profile=GOG_BUILD)
    section = image.get_section(transition.section_name)
    assert section is not None
    base = image.rva_to_va(section.virtual_address)
    back, primary, table, blt = (_HEAP + offset for offset in (0xA800, 0xA900, 0xAA00, 0xAB00))
    machine.mem_write(GOG_BUILD.address("transition.back_surface_ptr"), struct.pack("<I", back))
    machine.mem_write(
        GOG_BUILD.address("transition.primary_surface_ptr"), struct.pack("<I", primary)
    )
    machine.mem_write(back, struct.pack("<I", table))
    machine.mem_write(table + 0x1C, struct.pack("<I", blt))
    machine.mem_write(blt, bytes.fromhex("31 c0 c2 18 00"))
    invalidate = GOG_BUILD.address("transition.invalidate_all_damage")
    machine.mem_write(invalidate, b"\xc3")
    machine.mem_write(GOG_BUILD.address("transition.engine_loop_ptr"), struct.pack("<I", _RENDERER))
    machine.mem_write(base + transition._off_seed_pages_remaining, struct.pack("<I", 2))
    machine.mem_write(
        base + transition._off_last_seed_flip_generation, struct.pack("<I", 0xFFFFFFFF)
    )
    calls: list[str] = []

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == blt:
            stack = current.reg_read(UC_X86_REG_ESP)
            assert struct.unpack("<6I", current.mem_read(stack + 4, 24)) == (
                back,
                0,
                0,
                primary,
                0,
                0x10,
            )
            calls.append("seed")
        elif address == invalidate:
            calls.append("invalidate")
        elif address == _HEAP + 0xC000:
            calls.append("mirror")

    machine.hook_add(UC_HOOK_CODE, observe)
    for generation in (0, 0, 1, 2):
        machine.mem_write(base + transition._off_flip_count, struct.pack("<I", generation))
        machine.mem_write(abi.frame_pending_va, struct.pack("<I", 0))
        machine.mem_write(_STACK, struct.pack("<3I", _RETURN, 123, 456))
        machine.reg_write(UC_X86_REG_ESP, _STACK)
        machine.reg_write(UC_X86_REG_ECX, _HEAP + 0x4000)
        machine.emu_start(GOG_BUILD.site("transition.seed_hook").va, _RETURN, count=10000)
        assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 12
    assert calls == [
        "seed",
        "invalidate",
        "mirror",
        "mirror",
        "seed",
        "invalidate",
        "mirror",
        "mirror",
    ]
    assert (
        struct.unpack("<I", machine.mem_read(base + transition._off_seed_pages_remaining, 4))[0]
        == 0
    )


def test_windowed_mirror_does_not_seed_desktop_pixels_or_fake_flip_generations() -> None:
    machine, compiler, image = _scene_machine("rendered", deferred=True, mirror=True)
    abi = compiler.abi(image)
    transition = TransitionFrameCompiler(profile=GOG_BUILD)
    section = image.get_section(transition.section_name)
    assert section is not None
    base = image.rva_to_va(section.virtual_address)
    flag, back, primary, table, blt = (
        _HEAP + offset for offset in (0xA700, 0xA800, 0xA900, 0xAA00, 0xAB00)
    )
    machine.mem_write(GOG_BUILD.address("vr.fullscreen_flag_ptr"), struct.pack("<I", flag))
    machine.mem_write(flag, b"\x00")
    machine.mem_write(GOG_BUILD.address("transition.back_surface_ptr"), struct.pack("<I", back))
    machine.mem_write(
        GOG_BUILD.address("transition.primary_surface_ptr"), struct.pack("<I", primary)
    )
    machine.mem_write(back, struct.pack("<I", table))
    machine.mem_write(table + 0x1C, struct.pack("<I", blt))
    machine.mem_write(blt, bytes.fromhex("31 c0 c2 18 00"))
    invalidate = GOG_BUILD.address("transition.invalidate_all_damage")
    machine.mem_write(invalidate, b"\xc3")
    machine.mem_write(GOG_BUILD.address("transition.engine_loop_ptr"), struct.pack("<I", _RENDERER))
    machine.mem_write(base + transition._off_seed_pages_remaining, struct.pack("<I", 2))
    machine.mem_write(
        base + transition._off_last_seed_flip_generation, struct.pack("<I", 0xFFFFFFFF)
    )
    calls: list[str] = []

    def observe(_current: Uc, address: int, _size: int, _context: object) -> None:
        if address == blt:
            calls.append("seed")
        elif address == invalidate:
            calls.append("invalidate")
        elif address == _HEAP + 0xC000:
            calls.append("mirror")

    machine.hook_add(UC_HOOK_CODE, observe)

    def draw() -> None:
        machine.mem_write(abi.frame_pending_va, bytes(4))
        machine.mem_write(_STACK, struct.pack("<3I", _RETURN, 123, 456))
        machine.reg_write(UC_X86_REG_ESP, _STACK)
        machine.reg_write(UC_X86_REG_ECX, _HEAP + 0x4000)
        machine.emu_start(GOG_BUILD.site("transition.seed_hook").va, _RETURN, count=10000)
        assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 12

    for _ in range(4):
        draw()
    assert calls == ["mirror"] * 4
    assert struct.unpack("<I", machine.mem_read(base + transition._off_flip_count, 4))[0] == 0
    assert (
        struct.unpack("<I", machine.mem_read(base + transition._off_room_presentation_active, 4))[0]
        == 1
    )
    # Switching to a real fullscreen flip chain retains its pending repair.
    machine.mem_write(flag, b"\x01")
    draw()
    draw()
    assert calls[-4:] == ["seed", "invalidate", "mirror", "mirror"]
    assert struct.unpack("<I", machine.mem_read(base + transition._off_flip_count, 4))[0] == 0


def _interrupt_scene(machine: Uc, compiler: VRSceneCompiler, image: PEFile, stage: str) -> None:
    abi = compiler.abi(image)
    base = abi.enabled_va - compiler._enabled
    anchors = {
        "bridge": _HEAP + 0xC000,
        "setup": GOG_BUILD.site("vr.camera_setup").va + 6,
        "clear": _HEAP + 0xD200,
        "end": GOG_BUILD.site("vr.camera_end").va + 5,
        "flat": GOG_BUILD.site("transition.seed_hook").va
        + len(GOG_BUILD.site("transition.seed_hook").original),
    }
    reached = False

    def interrupt(current: Uc, address: int, _size: int, _context: object) -> None:
        nonlocal reached
        if reached:
            return
        if stage == "camera_copy":
            # Interrupt halfway through the actual REP MOVSD camera write,
            # rather than inventing a corrupted camera after the transaction.
            wanted = current.reg_read(UC_X86_REG_EDI) == _CAMERA + 0x60
            wanted = wanted and base < address < base + compiler._scene
        else:
            wanted = address == anchors[stage]
            if stage == "flat":
                wanted = (
                    wanted
                    and not struct.unpack("<I", current.mem_read(base + compiler._eye_active, 4))[0]
                )
        if wanted:
            reached = True
            current.emu_stop()

    machine.hook_add(UC_HOOK_CODE, interrupt)
    machine.reg_write(UC_X86_REG_ECX, _HEAP + 0x4000)
    machine.emu_start(GOG_BUILD.site("transition.seed_hook").va, _RETURN, count=10000)
    assert reached


def _dispatch_scene_handler(machine: Uc, registration: int, flags: int) -> None:
    record, stack = _HEAP + 0xD800, _HEAP + 0xE800
    machine.mem_write(record, struct.pack("<2I", 0xE1234567, flags))
    machine.mem_write(stack, struct.pack("<5I", _RETURN, record, registration, 0, 0))
    machine.reg_write(UC_X86_REG_ESP, stack)
    preserved = {UC_X86_REG_EBX: 11, UC_X86_REG_ESI: 22, UC_X86_REG_EDI: 33, UC_X86_REG_EBP: 44}
    for register, value in preserved.items():
        machine.reg_write(register, value)
    handler = struct.unpack("<I", machine.mem_read(registration + 4, 4))[0]
    machine.emu_start(handler, _RETURN, count=10000)
    assert machine.reg_read(UC_X86_REG_EAX) == 1  # ExceptionContinueSearch.
    assert machine.reg_read(UC_X86_REG_ESP) == stack + 4  # cdecl caller cleans arguments.
    for register, value in preserved.items():
        assert machine.reg_read(register) == value
    assert struct.unpack("<I", machine.mem_read(0, 4))[0] == registration


@pytest.mark.parametrize("stage", ["bridge", "camera_copy", "setup", "clear", "end", "flat"])
@pytest.mark.parametrize("flags", [0, 1, 2, 4, 6, 8])
@pytest.mark.parametrize("prewarm", [False, True])
def test_native_unwind_restores_owned_camera_without_interfering_with_inner_recovery(
    stage: str, flags: int, *, prewarm: bool
) -> None:
    machine, compiler, image = _scene_machine("rendered", deferred=True, prewarm=prewarm)
    abi = compiler.abi(image)
    base = abi.enabled_va - compiler._enabled
    globals_va = GOG_BUILD.address("vr.projection_globals")
    nesting = GOG_BUILD.address("vr.projection_nesting")
    authored = bytearray(bytes(range(256)) + bytes(range(28)))
    struct.pack_into("<I", authored, nesting - globals_va, 0)
    machine.mem_write(globals_va, bytes(authored))
    cache = _HEAP + 0x4000 + 0x34
    machine.mem_write(cache, struct.pack("<I", 0xA51C))
    camera = bytes(machine.mem_read(_CAMERA, 208))
    _interrupt_scene(machine, compiler, image, stage)
    # A previous/completed producer is also invalidated by an escaping scope.
    machine.mem_write(abi.world_input_va + 4, struct.pack("<I", 3))
    machine.mem_write(abi.target_va + 4, struct.pack("<2I", 1, 2))
    before = bytes(machine.mem_read(base, compiler.section_size))
    camera_before = bytes(machine.mem_read(_CAMERA, 208))
    globals_before = bytes(machine.mem_read(globals_va, 284))
    registration = struct.unpack("<I", machine.mem_read(0, 4))[0]
    _dispatch_scene_handler(machine, registration, flags)
    if not flags & 6:
        assert bytes(machine.mem_read(base, compiler.section_size)) == before
        assert bytes(machine.mem_read(_CAMERA, 208)) == camera_before
        assert bytes(machine.mem_read(globals_va, 284)) == globals_before
        return
    assert bytes(machine.mem_read(_CAMERA, 208)) == camera
    assert bytes(machine.mem_read(globals_va, 284)) == authored
    assert struct.unpack("<I", machine.mem_read(cache, 4))[0] == 0xA51C
    for address in (
        abi.enabled_va,
        abi.world_input_va + 4,
        base + compiler._projection_active,
        abi.frame_pending_va,
    ):
        assert struct.unpack("<I", machine.mem_read(address, 4))[0] == 0
    assert struct.unpack("<2I", machine.mem_read(abi.target_va + 4, 8)) == (0xFFFFFFFF, 0)
    assert struct.unpack("<I", machine.mem_read(abi.result_va, 4))[0] == 0x80004005
    # Windows then removes the registration and may unwind the outer scope too.
    previous = struct.unpack("<I", machine.mem_read(registration, 4))[0]
    machine.mem_write(0, struct.pack("<I", previous))
    if previous != 0x12345678:
        _dispatch_scene_handler(machine, previous, flags)
    assert struct.unpack("<I", machine.mem_read(abi.unwind_count_va, 4))[0] == 1
    machine.mem_write(0, struct.pack("<I", 0x12345678))
    # A healthy later native draw no longer inherits the aborted eye scope.
    machine.mem_write(_STACK, struct.pack("<3I", _RETURN, 123, 456))
    machine.reg_write(UC_X86_REG_ESP, _STACK)
    machine.reg_write(UC_X86_REG_ECX, _HEAP + 0x4000)
    machine.emu_start(GOG_BUILD.site("transition.seed_hook").va, _RETURN, count=10000)
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 12
    assert bytes(machine.mem_read(_CAMERA, 208)) == camera
    assert struct.unpack("<I", machine.mem_read(abi.enabled_va, 4))[0] == 0


def test_recovered_native_draw_without_scene_end_restores_state_and_rejects_eye() -> None:
    machine, compiler, image = _scene_machine("rendered")
    abi = compiler.abi(image)
    camera = bytes(machine.mem_read(_CAMERA, 208))
    nesting = GOG_BUILD.address("vr.projection_nesting")
    globals_va = GOG_BUILD.address("vr.projection_globals")
    before = bytes(machine.mem_read(globals_va, 284))
    # Model an inner engine handler returning without its usual EndScene call.
    # Setup has already replaced the camera, and clear reports success.
    base = abi.enabled_va - compiler._enabled
    _payload, labels = compiler._payload(base, 0)
    shim = X86Emitter(base_va=_HEAP + 0xD400)
    shim.raw(b"\x83\x3d" + struct.pack("<I", base + compiler._eye_active) + b"\x00")
    shim.jump_if(Condition.NOT_EQUAL, "recovered")
    shim.jump_absolute(labels["end"])
    shim.label("recovered")
    shim.raw(b"\xc3")
    machine.mem_write(_HEAP + 0xD400, shim.build())
    machine.mem_write(
        GOG_BUILD.site("vr.camera_end").va,
        encode_rel32_branch(
            opcode=BranchOpcode.JUMP,
            site_va=GOG_BUILD.site("vr.camera_end").va,
            target_va=_HEAP + 0xD400,
        ),
    )
    machine.reg_write(UC_X86_REG_ECX, _HEAP + 0x4000)
    machine.emu_start(GOG_BUILD.site("transition.seed_hook").va, _RETURN, count=10000)
    assert bytes(machine.mem_read(_CAMERA, 208)) == camera
    assert bytes(machine.mem_read(globals_va, 284)) == before
    assert struct.unpack("<I", machine.mem_read(nesting, 4))[0] == 0
    assert struct.unpack("<I", machine.mem_read(abi.result_va, 4))[0] == 0x80004005
    assert struct.unpack("<I", machine.mem_read(abi.enabled_va, 4))[0] == 0
    assert struct.unpack("<I", machine.mem_read(abi.submitted_frames_va, 4))[0] == 0
    assert struct.unpack("<I", machine.mem_read(abi.unwind_count_va, 4))[0] == 0
    assert struct.unpack("<I", machine.mem_read(0, 4))[0] == 0x12345678
