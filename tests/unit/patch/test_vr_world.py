"""Execute controller picking scopes without changing ordinary engine callers."""

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
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.binary.x86 import (
    BranchOpcode,
    X86Emitter,
    decode_rel32_branch,
    encode_rel32_branch,
)
from gk3hd.patch.builds import GOG_BUILD, SUPPORTED_BUILDS
from gk3hd.patch.definitions.vr_native_scene import NATIVE_SCENE_TYPES
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.definitions.vr_world import VRWorldCompiler
from gk3hd.patch.model import PatchError
from tests.unit.patch.test_complete_compilation import _source
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine

if TYPE_CHECKING:
    from unicorn import Uc

    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile


def _compiler(profile: BuildProfile = GOG_BUILD) -> tuple[PEFile, VRWorldCompiler]:
    image = _source(profile)
    scene = VRSceneCompiler(profile=profile, units_per_meter=40)
    scene.apply(image)
    compiler = VRWorldCompiler(profile=profile, scene=scene.abi(image))
    return image, compiler


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
def test_world_installation_verifies_and_remains_dormant(profile: BuildProfile) -> None:
    image, compiler = _compiler(profile)
    compiler.apply(image)
    compiler.postcheck(image)
    assert image.read_u32_va(compiler.abi(image).enabled_va) == 0
    with pytest.raises(PatchError, match="already installed"):
        compiler.apply(image)


@pytest.mark.parametrize("anchor", VRWorldCompiler._anchors)
def test_changed_pick_anchors_are_rejected_without_mutation(anchor: str) -> None:
    image, compiler = _compiler()
    image.write_bytes(image.va_to_offset(GOG_BUILD.site(anchor).va), b"\xcc")
    original = image.to_bytes()
    with pytest.raises(PatchError, match="anchor changed"):
        compiler.apply(image)
    assert image.to_bytes() == original


def test_changed_scene_output_is_rejected_without_mutation() -> None:
    image, compiler = _compiler()
    image.write_u32_va(compiler.scene.world_input_va, 1)
    original = image.to_bytes()
    with pytest.raises(PatchError, match="ABI changed"):
        compiler.apply(image)
    assert image.to_bytes() == original


def test_existing_world_query_is_rejected_without_mutation() -> None:
    image, compiler = _compiler()
    image.write_u32_va(compiler.scene.query_slot_va, 123)
    original = image.to_bytes()
    with pytest.raises(PatchError, match="callback is already occupied"):
        compiler.apply(image)
    assert image.to_bytes() == original


@pytest.mark.parametrize("replacement", [0, 123])
def test_disconnected_or_replaced_world_query_fails_verification(replacement: int) -> None:
    image, compiler = _compiler()
    compiler.apply(image)
    image.write_u32_va(compiler.scene.query_slot_va, replacement)
    with pytest.raises(PatchError):
        compiler.postcheck(image)


@pytest.mark.parametrize("anchor", VRWorldCompiler._anchors)
def test_postcheck_detects_changed_native_pick_graph(anchor: str) -> None:
    image, compiler = _compiler()
    compiler.apply(image)
    image.write_bytes(image.va_to_offset(GOG_BUILD.site(anchor).va), b"\xcc")
    with pytest.raises(PatchError):
        compiler.postcheck(image)


class Picker:
    """Observe a native picker using both endpoint and camera-origin producers."""

    node = _HEAP + 0x2000
    table = _HEAP + 0x3000
    near = _HEAP + 0x4000
    far = _HEAP + 0x4020
    point = _HEAP + 0x4040
    renderer = _HEAP + 0x5000
    camera = _HEAP + 0x6000
    stub = _HEAP + 0x7000
    rectangle = _HEAP + 0x8000

    def __init__(self, *, native_kind: int = 77) -> None:
        image, self.compiler = _compiler()
        self.compiler.apply(image)
        self.compiler.postcheck(image)
        self.abi = self.compiler.abi(image)
        self.machine = _machine(image)
        self.machine.mem_map(0, 0x1000)  # x86 TEB/FS exception chain in this emulator.
        self.word(0, 0x12345678)
        self.calls = 0
        self.native_rectangle_calls = 0
        self.native_ray_calls = 0
        self.received: list[tuple[int, ...]] = []
        self.mutate_snapshot = False
        self.unwind_handler = 0
        self.native_kind = native_kind
        self.word(self.abi.enabled_va, 1)
        self.word(self.compiler.scene.enabled_va, 1)
        self.word(self.node, self.table)
        self.word(self.node + 0x18, 1)
        self.word(self.table + 0xC4, GOG_BUILD.site("vr.world_pick").va)
        self.word(self.table + 0x94, self.rectangle)
        self.word(self.renderer + 0x1C8, self.camera)
        self.word(self.compiler.scene.world_input_va + 4, 3)
        self.word(self.compiler.scene.world_input_va + 8, 1)
        self.left = struct.pack("<9f", *range(1, 10))
        self.right = struct.pack("<9f", *range(21, 30))
        self.machine.mem_write(self.compiler.scene.world_input_va + 108, self.left + self.right)
        self.machine.mem_write(self.camera + 0x1C, struct.pack("<3f", 101, 102, 103))
        self.machine.mem_write(self.point, struct.pack("<2i", -10000, -10000))
        self._install_native_picker(image)
        self.machine.hook_add(UC_HOOK_CODE, self.observe)

    def _install_native_picker(self, image: PEFile) -> None:
        self.machine.mem_write(self.rectangle, bytes.fromhex("31 c0 c2 04 00"))
        ray = GOG_BUILD.site("vr.pick_ray")
        self.machine.mem_write(ray.va + len(ray.original), bytes.fromhex("c9 c3"))
        gate = GOG_BUILD.site("vr.pick_rectangle")
        self.gate = decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=gate.va,
            instruction=image.read_bytes(image.va_to_offset(gate.va), 5),
        )
        assert self.gate is not None
        e = X86Emitter(base_va=self.stub)
        e.raw(bytes.fromhex("55 8b ec"))
        e.push_imm32(self.point)
        e.raw(b"\xb8" + struct.pack("<I", self.table))
        e.call_absolute(self.gate)
        e.raw(b"\xa3" + struct.pack("<I", self.near + 0x80))
        e.push_imm32(self.far)
        e.push_imm32(self.near)
        e.push_imm32(self.point)
        e.call_absolute(ray.va)
        e.raw(bytes.fromhex("83 c4 0c"))
        e.raw(b"\xb9" + struct.pack("<I", self.renderer))
        e.call_absolute(GOG_BUILD.site("vr.pick_origin").va)
        e.raw(b"\xa3" + struct.pack("<I", self.near + 0x84))
        e.raw(b"\xb8" + struct.pack("<I", self.native_kind) + bytes.fromhex("c9 c2 10 00"))
        self.machine.mem_write(self.stub, e.build())
        _payload, labels = self.compiler._payload(self.abi.enabled_va - self.compiler._enabled)
        target = labels["native_pick"]
        self.machine.mem_write(
            target,
            encode_rel32_branch(opcode=BranchOpcode.JUMP, site_va=target, target_va=self.stub),
        )

    def observe(self, machine: Uc, address: int, _size: int, _context: object) -> None:
        if address == self.stub:
            self.calls += 1
            if self.read(self.abi.active_va):
                registration = self.read(0)
                assert self.read(registration) == 0x12345678
                self.unwind_handler = self.read(registration + 4)
            assert machine.reg_read(UC_X86_REG_ECX) == self.node
            self.received.append(
                struct.unpack("<4I", machine.mem_read(machine.reg_read(UC_X86_REG_ESP) + 4, 16))
            )
            if self.mutate_snapshot:
                machine.mem_write(self.compiler.scene.world_input_va + 108, bytes(72))
        if address == self.rectangle:
            self.native_rectangle_calls += 1
        ray = GOG_BUILD.site("vr.pick_ray")
        if address == ray.va + len(ray.original):
            self.native_ray_calls += 1
            machine.mem_write(self.near, bytes(12))
            machine.mem_write(self.far, bytes(12))

    def word(self, address: int, value: int) -> None:
        self.machine.mem_write(address, struct.pack("<I", value))

    def read(self, address: int) -> int:
        return struct.unpack("<I", self.machine.mem_read(address, 4))[0]

    def invoke(self, entry: int | None = None) -> int:
        self.machine.mem_write(_STACK, struct.pack("<5I", _RETURN, self.point, 123, 456, 789))
        self.machine.reg_write(UC_X86_REG_ESP, _STACK)
        saved = {UC_X86_REG_EBP: 17, UC_X86_REG_EBX: 31, UC_X86_REG_ESI: 47, UC_X86_REG_EDI: 59}
        for register, value in saved.items():
            self.machine.reg_write(register, value)
        self.machine.reg_write(UC_X86_REG_ECX, self.node)
        self.machine.emu_start(self.abi.pick_va if entry is None else entry, _RETURN, count=2000)
        assert self.machine.reg_read(UC_X86_REG_ESP) == _STACK + 20
        for register, value in saved.items():
            assert self.machine.reg_read(register) == value
        assert self.read(0) == 0x12345678
        return self.machine.reg_read(UC_X86_REG_EAX)

    def query(self, hand: int = 1, *, setup: bool = True) -> int:
        room, owner, ray, hit = (_HEAP + offset for offset in (0xA000, 0xB000, 0xC000, 0xC100))
        if setup:
            self.word(GOG_BUILD.address("vr.room_global"), room)
            self.word(room, GOG_BUILD.address("vr.user_scene_vtable"))
            self.word(room + 0x50, self.node)
            self.word(owner, GOG_BUILD.address("vr.room_layer_vtable"))
            self.machine.mem_write(
                GOG_BUILD.address("ui.current_layer"),
                b"\xb8" + struct.pack("<I", owner) + b"\xc3",
            )
            self.machine.mem_write(ray, struct.pack("<9f", *range(41, 50)))
        self.machine.mem_write(_STACK, struct.pack("<5I", _RETURN, 0, hand, ray, hit))
        self.machine.reg_write(UC_X86_REG_ESP, _STACK)
        saved = {UC_X86_REG_EBP: 17, UC_X86_REG_EBX: 31, UC_X86_REG_ESI: 47, UC_X86_REG_EDI: 59}
        for register, value in saved.items():
            self.machine.reg_write(register, value)
        self.machine.emu_start(self.read(self.compiler.scene.query_slot_va), _RETURN, count=2000)
        assert self.machine.reg_read(UC_X86_REG_ESP) == _STACK + 20
        for register, value in saved.items():
            assert self.machine.reg_read(register) == value
        assert self.read(0) == 0x12345678
        return self.machine.reg_read(UC_X86_REG_EAX)


@pytest.mark.parametrize("hand", [0, 1])
def test_visual_query_distinguishes_an_eligible_miss_from_lost_ownership(hand: int) -> None:
    picker = Picker(native_kind=0)
    picker.word(picker.abi.hand_va, hand)
    assert picker.query(hand) == 3
    assert len(picker.received) == 1
    assert picker.read(picker.abi.active_va) == picker.read(picker.abi.dispatch_va) == 0
    picker.word(picker.abi.enabled_va, 0)
    assert picker.query(hand, setup=False) == 0
    assert len(picker.received) == 1


@pytest.mark.parametrize("hand", [0, 1])
@pytest.mark.parametrize("scene_type", NATIVE_SCENE_TYPES)
def test_visual_query_uses_fresh_ray_without_publishing_or_dispatching_input(
    hand: int, scene_type: str
) -> None:
    picker = Picker(native_kind=2)
    picker.word(picker.abi.hand_va, hand)
    picker.word(picker.compiler.scene.world_input_va + 4, 0)
    picker.word(picker.compiler.scene.result_va, 0xFFFFFFFF)
    original = bytes(picker.machine.mem_read(picker.compiler.scene.world_input_va, 180))
    picker.query(hand)
    picker.word(_HEAP + 0xA000, GOG_BUILD.address(scene_type))
    picker.received.clear()
    assert picker.query(hand, setup=False) == 2
    ray = struct.pack("<9f", *range(41, 50))
    assert bytes(picker.machine.mem_read(picker.near, 12)) == ray[12:24]
    assert bytes(picker.machine.mem_read(picker.far, 12)) == ray[24:36]
    assert bytes(picker.machine.mem_read(picker.read(picker.near + 0x84), 12)) == ray[:12]
    assert bytes(picker.machine.mem_read(picker.compiler.scene.world_input_va, 180)) == original
    assert picker.read(picker.abi.active_va) == picker.read(picker.abi.dispatch_va) == 0
    assert picker.received[0][1:3] == (0, 0)  # Read-only pick, no noun/action transaction.


@pytest.mark.parametrize(
    "guard",
    [
        "disabled",
        "scene",
        "recursive",
        "dispatch",
        "hand",
        "layer",
        "room",
        "node",
        "list",
        "count",
    ],
)
def test_visual_query_rejects_non_world_or_unavailable_ownership(guard: str) -> None:
    picker = Picker(native_kind=2)
    assert picker.query() == 2
    room, owner = _HEAP + 0xA000, _HEAP + 0xB000
    values = {
        "disabled": (picker.abi.enabled_va, 0),
        "scene": (picker.compiler.scene.enabled_va, 0),
        "recursive": (picker.abi.active_va, 1),
        "dispatch": (picker.abi.dispatch_va, 1),
        "hand": (picker.abi.hand_va, 0),
        "layer": (owner, 1),
        "room": (room, 1),
        "node": (room + 0x50, 0),
        "list": (owner + 0x50, 1),
        "count": (owner + 0x50, 257),
    }
    picker.word(*values[guard])
    assert picker.query(setup=False) == 0
    assert picker.calls == 1


@pytest.mark.parametrize("widget", ["vr.action_menu_vtable", "vr.toolbar_vtable"])
@pytest.mark.parametrize("visible", [False, True])
def test_visual_reticle_yields_to_visible_action_menus(widget: str, visible: bool) -> None:
    picker = Picker(native_kind=2)
    assert picker.query() == 2
    owner, child, children = _HEAP + 0xB000, _HEAP + 0xD000, _HEAP + 0xD100
    picker.word(owner + 0x4C, children)
    picker.word(owner + 0x50, 1)
    picker.word(children, child)
    picker.word(child, GOG_BUILD.address(widget))
    picker.machine.mem_write(child + 0x18, bytes([visible]))
    assert picker.query(setup=False) == (0 if visible else 2)
    assert picker.calls == (1 if visible else 2)


@pytest.mark.parametrize("hand", [0, 1])
def test_native_pickers_receive_same_frozen_world_ray_and_origin(hand: int) -> None:
    picker = Picker()
    picker.word(picker.abi.hand_va, hand)
    picker.mutate_snapshot = True
    assert picker.invoke() == 77
    ray = picker.left if hand == 0 else picker.right
    assert bytes(picker.machine.mem_read(picker.near, 12)) == ray[12:24]
    assert bytes(picker.machine.mem_read(picker.far, 12)) == ray[24:36]
    origin = picker.read(picker.near + 0x84)
    assert bytes(picker.machine.mem_read(origin, 12)) == ray[:12]
    assert picker.read(picker.near + 0x80) == 1
    assert picker.native_ray_calls == picker.native_rectangle_calls == 0
    assert picker.received == [(picker.point, 123, 456, 789)]
    assert picker.read(picker.abi.active_va) == 0
    assert picker.read(picker.abi.calls_va) == 1
    # Ordinary picking still uses native endpoints, authored camera and bounds.
    assert picker.invoke(GOG_BUILD.site("vr.world_pick").va) == 77
    assert picker.read(picker.near + 0x80) == 0
    assert picker.read(picker.near + 0x84) == picker.camera + 0x1C
    assert picker.native_ray_calls == picker.native_rectangle_calls == 1


@pytest.mark.parametrize("hand", [0, 1])
@pytest.mark.parametrize("loss", [None, "focus", "tracking", "scene", "disabled", "recursive"])
def test_wall_fade_preserves_navigation_but_never_picks_a_stale_ray(
    hand: int, loss: str | None
) -> None:
    picker = Picker()
    source = picker.compiler.scene.world_input_va
    picker.word(source + 4, 0)
    picker.word(source + 8, loss != "focus")
    picker.word(source + 12 + hand * 48, loss != "tracking")
    if loss == "scene":
        picker.word(picker.compiler.scene.result_va, 0x80004005)
    elif loss == "disabled":
        picker.word(picker.abi.enabled_va, 0)
    elif loss == "recursive":
        picker.word(picker.abi.active_va, 1)
    picker.word(picker.abi.hand_va, hand)
    machine = picker.machine
    machine.mem_write(_STACK, struct.pack("<2I", _RETURN, hand))
    machine.reg_write(UC_X86_REG_ESP, _STACK)
    machine.emu_start(picker.abi.prepare_va, _RETURN, count=500)
    assert picker.read(picker.abi.ready_va) == (2 if loss is None else 0)
    assert picker.invoke() == 0
    picker.word(picker.abi.dispatch_va, 1)
    assert picker.invoke(GOG_BUILD.site("vr.world_pick").va) == 0
    assert picker.calls == 0


@pytest.mark.parametrize("hand", [0, 1])
def test_native_input_pick_uses_prepared_ray_during_synchronous_redraw(hand: int) -> None:
    picker = Picker()
    machine = picker.machine
    machine.mem_write(_STACK, struct.pack("<2I", _RETURN, hand))
    machine.reg_write(UC_X86_REG_ESP, _STACK)
    machine.emu_start(picker.abi.prepare_va, _RETURN, count=500)
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 8
    assert machine.reg_read(UC_X86_REG_EAX) == 1
    assert picker.read(picker.abi.ready_va) == 1
    picker.word(picker.abi.dispatch_va, 1)
    # A native UI redraw must not submit a second stereo frame or destroy the
    # ray used by another pick in the same synchronous input transaction.
    picker.word(picker.compiler.scene.enabled_va, 0)
    machine.mem_write(picker.compiler.scene.world_input_va + 4, bytes(176))
    assert picker.invoke(GOG_BUILD.site("vr.world_pick").va) == 77
    ray = picker.left if hand == 0 else picker.right
    assert bytes(machine.mem_read(picker.near, 12)) == ray[12:24]
    assert bytes(machine.mem_read(picker.far, 12)) == ray[24:36]
    assert picker.native_ray_calls == picker.native_rectangle_calls == 0
    picker.word(picker.abi.dispatch_va, 0)
    assert picker.invoke(GOG_BUILD.site("vr.world_pick").va) == 77
    assert picker.native_ray_calls == picker.native_rectangle_calls == 1


def test_unprepared_dispatch_does_not_fall_back_to_desktop_selection() -> None:
    picker = Picker()
    picker.word(picker.abi.dispatch_va, 1)
    assert picker.invoke(GOG_BUILD.site("vr.world_pick").va) == 0
    assert picker.calls == 0


@pytest.mark.parametrize(
    "loss",
    [
        "disabled",
        "scene_disabled",
        "scene_failed",
        "focus",
        "tracking",
        "invalid_hand",
        "node",
        "recursive",
    ],
)
def test_invalid_world_ownership_never_calls_native_picker(loss: str) -> None:
    picker = Picker()
    if loss == "disabled":
        picker.word(picker.abi.enabled_va, 0)
    elif loss == "scene_disabled":
        picker.word(picker.compiler.scene.enabled_va, 0)
    elif loss == "scene_failed":
        picker.word(picker.compiler.scene.result_va, 0x80004005)
    elif loss == "focus":
        picker.word(picker.compiler.scene.world_input_va + 8, 0)
    elif loss == "tracking":
        picker.word(picker.compiler.scene.world_input_va + 4, 1)
    elif loss == "invalid_hand":
        picker.word(picker.abi.hand_va, 2)
    elif loss == "node":
        picker.word(picker.table + 0xC4, 123)
    else:
        picker.word(picker.abi.active_va, 1)
    assert picker.invoke() == 0
    assert picker.calls == picker.read(picker.abi.calls_va) == 0
    assert picker.read(picker.abi.active_va) == (loss == "recursive")


def test_hidden_world_widget_is_not_made_interactive() -> None:
    picker = Picker()
    picker.word(picker.node + 0x18, 0)
    picker.invoke()
    assert picker.read(picker.near + 0x80) == 0


@pytest.mark.parametrize(
    ("active", "inside", "selectable", "resource", "expected"),
    [
        (False, False, True, 42, []),
        (False, True, True, 42, [42]),
        (True, False, True, 42, [42]),
        (True, True, True, 42, [42]),
        (True, False, False, 42, []),
        (True, False, True, 0, []),
    ],
)
def test_actor_candidates_keep_selectability_but_not_desktop_bounds_in_vr(
    active: bool, inside: bool, selectable: bool, resource: int, expected: list[int]
) -> None:
    picker = Picker()
    machine = picker.machine
    context, actor, rectangle, collection = (
        _HEAP + offset for offset in (0x9000, 0xA000, 0xB000, 0xC000)
    )
    picker.word(picker.abi.active_va, active)
    picker.word(context, collection)
    picker.word(context + 4, picker.point)
    picker.word(actor + 0x50, resource)
    machine.mem_write(actor + 0x54, bytes([selectable]))
    machine.mem_write(picker.point, struct.pack("<2i", *(0, 0) if inside else (-10000, -10000)))
    machine.mem_write(rectangle, struct.pack("<4i", -500, -500, 500, 500))
    # Original candidate collector before and after the verified redirect.
    # It checks resource/selectability, then desktop bounds, then appends the
    # actor handle. Its list allocator is replaced by an observable test sink.
    machine.mem_write(
        0x52BBFB,
        bytes.fromhex("55 8b ec 53 56 57 8b 7d 08 8b d9 8b 47 50 85 c0 74 39 80 7f 54 00 74 33"),
    )
    machine.mem_write(
        0x52BC18,
        bytes.fromhex(
            "e8 a3 b1 fa ff 8b 0e 39 08 7f 23 8b 76 04 39 70 04 7f 1b "
            "3b 48 08 7d 16 3b 70 0c 7d 11 8b 47 50 8b 0b 89 45 08 "
            "8d 45 08 50 e8 d9 aa f1 ff 5f 5e 5b 5d c2 04 00"
        ),
    )
    machine.mem_write(0x4D6DC0, b"\xb8" + struct.pack("<I", rectangle) + b"\xc3")
    machine.mem_write(0x44671F, bytes.fromhex("c2 04 00"))
    collected = []

    def append_handle(uc: Uc, address: int, _size: int, _context: object) -> None:
        if address == 0x44671F:
            assert uc.reg_read(UC_X86_REG_ECX) == collection
            pointer = struct.unpack("<I", uc.mem_read(uc.reg_read(UC_X86_REG_ESP) + 4, 4))[0]
            collected.append(struct.unpack("<I", uc.mem_read(pointer, 4))[0])

    machine.hook_add(UC_HOOK_CODE, append_handle)
    machine.mem_write(_STACK, struct.pack("<2I", _RETURN, actor))
    machine.reg_write(UC_X86_REG_ESP, _STACK)
    machine.reg_write(UC_X86_REG_ECX, context)
    machine.emu_start(0x52BBFB, _RETURN, count=500)
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 8
    assert collected == expected


def test_postcheck_rejects_changed_world_input_size() -> None:
    image, compiler = _compiler()
    compiler.apply(image)
    image.write_u32_va(compiler.scene.world_input_va, 4)
    with pytest.raises(PatchError, match="input ABI"):
        compiler.postcheck(image)


@pytest.mark.parametrize("exception_flags", [0, 1, 2, 4, 6])
def test_native_unwind_retires_ray_without_swallowing_exceptions(exception_flags: int) -> None:
    picker = Picker()
    picker.invoke()
    picker.word(picker.abi.active_va, 1)
    picker.word(picker.abi.dispatch_va, 1)
    picker.word(picker.abi.ready_va, 1)
    exception = _HEAP + 0x9000
    picker.word(exception, 0xE06D7363)  # Native C++ exception, not just access violations.
    picker.word(exception + 4, exception_flags)
    machine = picker.machine
    machine.mem_write(_STACK, struct.pack("<5I", _RETURN, exception, 0, 0, 0))
    machine.reg_write(UC_X86_REG_ESP, _STACK)
    machine.emu_start(picker.unwind_handler, _RETURN, count=100)
    assert machine.reg_read(UC_X86_REG_EAX) == 1  # ContinueSearch, never ContinueExecution.
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 4  # cdecl registration handler.
    unwinding = bool(exception_flags & 6)
    assert picker.read(picker.abi.active_va) == (not unwinding)
    assert picker.read(picker.abi.enabled_va) == (not unwinding)
    assert picker.read(picker.abi.unwind_count_va) == unwinding
    assert picker.read(picker.abi.dispatch_va) == (not unwinding)
    assert picker.read(picker.abi.ready_va) == (not unwinding)
