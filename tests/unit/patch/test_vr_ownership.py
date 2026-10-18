"""Execute automatic layer/camera classification and linked producer gates."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_ESP

from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.builds import GOG_BUILD, SUPPORTED_BUILDS, BuildProfile
from gk3hd.patch.definitions.vr_native_scene import NATIVE_SCENE_TYPES
from gk3hd.patch.definitions.vr_ownership import VROwnershipCompiler
from gk3hd.patch.definitions.vr_panel import VRPanelCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError
from tests.unit.patch.test_vr_panel import _image, _linked_panel, _panel_machine
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine, _scene_machine

if TYPE_CHECKING:
    from gk3hd.patch.definitions.vr_ownership import VROwnershipABI
    from gk3hd.patch.definitions.vr_scene import VRSceneABI


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
def test_ownership_is_dormant_on_supported_builds(profile: BuildProfile) -> None:
    image = _image(profile)
    scene = VRSceneCompiler(profile=profile, units_per_meter=40, deferred_frame=True)
    scene.apply(image)
    panel = VRPanelCompiler(profile=profile, world_enabled_va=scene.abi(image).enabled_va)
    panel.apply(image)
    compiler = VROwnershipCompiler(profile=profile, scene=scene.abi(image), panel=panel.abi(image))
    compiler.apply(image)
    compiler.postcheck(image)
    assert image.read_u32_va(compiler.abi(image).enabled_va) == 0
    with pytest.raises(PatchError, match="already installed"):
        compiler.apply(image)


@pytest.mark.parametrize(
    "changed",
    [
        "scene",
        "panel",
        "lock",
        "controller_top",
        "controller_stack",
        "user_camera",
        "user_scene",
        "conversation_scene",
        "conversation_context",
        "conversation_active",
        "cinematics",
    ],
)
def test_ownership_rejects_changed_dependencies_before_writes(changed: str) -> None:
    image, panel, _entry = _linked_panel(paired=True)
    scene = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40).abi(image)
    address = {
        "scene": scene.ownership_query_slot_va,
        "panel": panel.ownership_query_slot_va,
        "lock": GOG_BUILD.site("vr.camera_input_lock").va,
        "controller_top": GOG_BUILD.site("vr.camera_controller_top").va,
        "controller_stack": GOG_BUILD.site("vr.camera_controller_stack").va,
        "user_camera": GOG_BUILD.site("vr.user_camera_controller").va,
        "user_scene": GOG_BUILD.site("vr.user_scene_controller").va,
        "conversation_scene": GOG_BUILD.site("vr.conversation_scene_owner").va,
        "conversation_context": GOG_BUILD.site("vr.conversation_context").va,
        "conversation_active": GOG_BUILD.site("vr.conversation_active").va,
        "cinematics": GOG_BUILD.site("vr.cinematics_policy").va,
    }[changed]
    image.write_bytes(image.va_to_offset(address), b"\xcc")
    original = image.to_bytes()
    with pytest.raises(PatchError, match=r"occupied|anchor changed"):
        VROwnershipCompiler(profile=GOG_BUILD, scene=scene, panel=panel).apply(image)
    assert image.to_bytes() == original


@pytest.fixture(scope="module")
def ownership_program() -> tuple[bytes, VRSceneABI, VROwnershipABI]:
    """Compile once; every graph case still receives its own image and emulator."""
    image, panel, _entry = _linked_panel(paired=True)
    scene = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40).abi(image)
    compiler = VROwnershipCompiler(profile=GOG_BUILD, scene=scene, panel=panel)
    compiler.apply(image)
    compiler.postcheck(image)
    return image.to_bytes(), scene, compiler.abi(image)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("room", 1),
        ("menu", 3),
        ("toolbar", 3),
        ("hidden", 1),
        ("unknown_child", 1),
        ("modal", 2),
        ("layer_missing", 2),
        ("room_missing", 2),
        ("wrong_room", 2),
        ("node_missing", 2),
        ("engine_missing", 2),
        ("manager_missing", 2),
        ("wrong_manager", 2),
        ("locked", 2),
        ("empty_controllers", 2),
        ("stacked_controllers", 2),
        ("damaged_controller_count", 2),
        ("missing_controller", 2),
        ("scripted_controller", 2),
        ("user_camera", 1),
        ("conversation", 2),
        ("conversation_cinematics_off", 1),
        ("conversation_forced_cinematics_off", 2),
        ("conversation_manager_missing", 2),
        ("conversation_scene_missing", 2),
        ("conversation_context_missing", 2),
        ("bad_count", 2),
        ("bad_list", 2),
        ("disabled", 0),
    ],
)
@pytest.mark.parametrize("scene_type", NATIVE_SCENE_TYPES)
def test_native_graph_chooses_layers_without_changing_game_state(
    ownership_program: tuple[bytes, VRSceneABI, VROwnershipABI],
    state: str,
    expected: int,
    scene_type: str,
) -> None:
    data, scene, abi = ownership_program
    machine = _machine(PEFile(data))
    root, room, engine, owner, manager, children, child = (
        _HEAP + offset for offset in (0x1000, 0x2000, 0x3000, 0x4000, 0x5000, 0x6000, 0x7000)
    )

    def word(address: int, value: int) -> None:
        machine.mem_write(address, struct.pack("<I", value))

    word(abi.enabled_va, state != "disabled")
    word(scene.world_input_va + 4, 3)
    word(scene.target_va + 4, 1)
    word(scene.target_va + 8, 2)
    word(root, GOG_BUILD.address("vr.room_layer_vtable") if state != "modal" else 123)
    word(GOG_BUILD.address("vr.room_global"), 0 if state == "room_missing" else room)
    word(
        room,
        GOG_BUILD.address(scene_type) if state != "wrong_room" else 123,
    )
    word(room + 0x50, 0 if state == "node_missing" else room + 0x100)
    word(GOG_BUILD.address("engine.loop"), 0 if state == "engine_missing" else engine)
    word(engine + 0x444, owner)
    scene_manager, scene_owner, conversation = (
        _HEAP + offset for offset in (0x7200, 0x7300, 0x7400)
    )
    word(owner + 0x60, 0 if state == "conversation_manager_missing" else scene_manager)
    word(scene_manager + 0xC, 0 if state == "conversation_scene_missing" else scene_owner)
    word(scene_owner + 8, 0 if state == "conversation_context_missing" else conversation)
    word(conversation, conversation + 0x100 if state.startswith("conversation") else 0)
    word(owner + 0x28, 0 if state == "manager_missing" else manager)
    word(
        manager, GOG_BUILD.address("vr.camera_manager_vtable") if state != "wrong_manager" else 123
    )
    machine.mem_write(
        manager + 0x1C5, bytes((state in {"locked", "conversation_forced_cinematics_off"},))
    )
    machine.mem_write(
        manager + 0x1C4,
        bytes(
            (state not in {"conversation_cinematics_off", "conversation_forced_cinematics_off"},)
        ),
    )
    word(
        manager + 0xB0,
        {
            "empty_controllers": 0,
            "stacked_controllers": 2,
            "damaged_controller_count": 0xFFFFFFFF,
        }.get(state, 1),
    )
    controller = manager + 0x400
    word(
        controller,
        123
        if state == "scripted_controller"
        else GOG_BUILD.address(
            "vr.user_camera_controller_vtable"
            if state == "user_camera"
            else "vr.user_scene_controller_vtable"
        ),
    )
    machine.mem_write(
        GOG_BUILD.site("vr.camera_controller_top").va,
        b"\xb8" + struct.pack("<I", 0 if state == "missing_controller" else controller) + b"\xc3",
    )
    word(
        root + 0x50,
        257
        if state == "bad_count"
        else int(state in {"menu", "toolbar", "hidden", "unknown_child", "bad_list"}),
    )
    word(root + 0x4C, 0 if state == "bad_list" else children)
    word(children, child)
    word(
        child,
        GOG_BUILD.address("vr.toolbar_vtable" if state == "toolbar" else "vr.action_menu_vtable")
        if state != "unknown_child"
        else 123,
    )
    machine.mem_write(child + 0x18, bytes((state != "hidden",)))
    machine.mem_write(
        GOG_BUILD.address("ui.current_layer"),
        b"\xb8" + struct.pack("<I", 0 if state == "layer_missing" else root) + b"\xc3",
    )
    before = bytes(machine.mem_read(root, 0x7000))
    machine.mem_write(_STACK, struct.pack("<I", _RETURN))
    machine.reg_write(UC_X86_REG_ESP, _STACK)
    machine.reg_write(UC_X86_REG_EBX, 17)
    machine.reg_write(UC_X86_REG_ECX, 37)
    machine.emu_start(abi.query_va, _RETURN, count=2000)
    assert machine.reg_read(UC_X86_REG_EAX) == expected
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 4
    assert machine.reg_read(UC_X86_REG_EBX) == 17
    assert machine.reg_read(UC_X86_REG_ECX) == 37
    assert bytes(machine.mem_read(root, 0x7000)) == before
    assert struct.unpack("<I", machine.mem_read(scene.world_input_va + 4, 4))[0] == (
        3 if expected & 1 else 0
    )
    assert struct.unpack("<2I", machine.mem_read(scene.target_va + 4, 8)) == (
        (1, 2) if expected & 1 else (0xFFFFFFFF, 0)
    )


@pytest.mark.parametrize("mode", [0, 1, 2, 3])
def test_scene_ownership_retires_old_rays_without_disabling_the_master(mode: int) -> None:
    machine, compiler, image = _scene_machine("success", deferred=True)
    abi = compiler.abi(image)
    query = _HEAP + 0xA800
    machine.mem_write(query, b"\xb8" + struct.pack("<I", mode) + b"\xc3")
    machine.mem_write(abi.ownership_query_slot_va, struct.pack("<I", query))
    machine.mem_write(abi.world_input_va + 4, struct.pack("<I", 3))
    machine.mem_write(abi.target_va + 4, struct.pack("<2I", 1, 2))
    machine.reg_write(UC_X86_REG_ECX, _HEAP + 0x4000)
    machine.emu_start(GOG_BUILD.site("transition.seed_hook").va, _RETURN, count=10000)
    assert struct.unpack("<I", machine.mem_read(abi.enabled_va, 4))[0] == 1
    assert struct.unpack("<I", machine.mem_read(abi.submitted_frames_va, 4))[0] == bool(mode & 1)
    assert struct.unpack("<I", machine.mem_read(abi.world_input_va + 4, 4))[0] == 0
    assert struct.unpack("<2I", machine.mem_read(abi.target_va + 4, 8)) == (0xFFFFFFFF, 0)


@pytest.mark.parametrize(("mode", "operation"), [(0, 1), (1, 2), (2, 0), (3, 0)])
def test_panel_ownership_selects_finalizer_without_mutating_the_master(
    mode: int, operation: int
) -> None:
    machine, entry, abi, _calls, operations = _panel_machine("shared")
    query = _HEAP + 0xA800
    machine.mem_write(query, b"\xb8" + struct.pack("<I", mode) + b"\xc3")
    machine.mem_write(abi.ownership_query_slot_va, struct.pack("<I", query))
    machine.mem_write(_STACK, struct.pack("<I", _RETURN))
    machine.reg_write(UC_X86_REG_ESP, _STACK)
    machine.emu_start(entry, _RETURN, count=2000)
    assert operations == [operation]
    assert struct.unpack("<I", machine.mem_read(abi.enabled_va, 4))[0] == 1
