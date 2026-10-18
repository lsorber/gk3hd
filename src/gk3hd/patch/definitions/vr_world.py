"""Scoped original-engine picking for the private native OpenXR world rays."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter
from gk3hd.patch.definitions.vr_native_scene import (
    check_native_scene_types,
    emit_native_scene_guard,
)
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.vr_scene import VRSceneABI


@dataclass(frozen=True, slots=True)
class VRWorldABI:
    """Dormant render-thread picking/dispatch boundary, not a player command."""

    enabled_va: int
    hand_va: int
    active_va: int
    pick_va: int
    calls_va: int
    unwind_count_va: int
    prepare_va: int
    dispatch_va: int
    ready_va: int  # 0 unavailable, 1 selectable ray, 2 wall-fade navigation only.
    query_va: int


@dataclass(frozen=True, slots=True, kw_only=True)
class VRWorldCompiler:
    """Feed the same tracked ray to native BSP, actor and closest-hit logic.

    The private entry has the original Room3D thiscall signature:
    (screen_point, optional_noun_string, optional_actor_string, optional_hit).
    Its point is only a placeholder. While the verified picker runs, its ray
    and origin producers use one frozen controller ray, and only its desktop
    rectangle gates are bypassed. Hidden widgets and non-selectable actors
    still reject picks. All other
    game callers retain their native ray, camera and rectangle behavior.

    VRInputCompiler can prepare one completed-frame ray before a synchronous
    native event transaction and redirect that transaction's ordinary picks.
    A completed wall-fade snapshot can instead permit navigation without a
    selectable ray; neither direct nor prepared picking accepts that state.
    Menus still use native interface events. This is not yet complete automatic
    scene/interface integration. Entries must run on the game's render thread.
    """

    profile: BuildProfile
    scene: VRSceneABI

    section_name: ClassVar[str] = ".gk3vw"
    section_size: ClassVar[int] = 0x1000
    _magic: ClassVar[bytes] = b"GK3XRW01"
    _enabled: ClassVar[int] = 0x0C
    _hand: ClassVar[int] = 0x10
    _active: ClassVar[int] = 0x14
    _calls: ClassVar[int] = 0x18
    _unwinds: ClassVar[int] = 0x1C
    _ray: ClassVar[int] = 0x20
    _dispatch: ClassVar[int] = 0x44
    _ready: ClassVar[int] = 0x48
    _query_point: ClassVar[int] = 0x50
    _code: ClassVar[int] = 0x100
    _anchors: ClassVar[tuple[str, ...]] = (
        "vr.pick_ray",
        "vr.pick_origin",
        "vr.pick_rectangle",
        "vr.pick_actor_rectangle",
        "vr.pick_actor_accept",
        "vr.world_pick",
        "vr.world_hover",
    )

    def abi(self, image: PEFile) -> VRWorldABI:
        """Resolve the verified private picker entry."""
        section = image.get_section(self.section_name)
        if section is None or image.read_bytes(section.pointer_to_raw_data, 8) != self._magic:
            msg = "VR world section is absent or incompatible"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        _payload, labels = self._payload(base)
        return VRWorldABI(
            base + self._enabled,
            base + self._hand,
            base + self._active,
            labels["pick"],
            base + self._calls,
            base + self._unwinds,
            labels["prepare"],
            base + self._dispatch,
            base + self._ready,
            labels["query"],
        )

    def precheck(self, image: PEFile) -> None:
        """Reject changed dependencies and anchors before any mutation."""
        check_native_scene_types(image, self.profile)
        if image.get_section(self.section_name) is not None:
            msg = "VR world hooks are already installed"
            raise PatchError(msg)
        if VRSceneCompiler(profile=self.profile, units_per_meter=1).abi(image) != self.scene:
            msg = "VR world scene boundary changed"
            raise PatchError(msg)
        if image.read_u32_va(self.scene.world_input_va) != VRSceneCompiler.world_input_size:
            msg = "VR world input ABI changed"
            raise PatchError(msg)
        if image.read_u32_va(self.scene.query_slot_va):
            msg = "VR world picking callback is already occupied"
            raise PatchError(msg)
        for name in self._anchors:
            site = self.profile.site(name)
            if (
                image.read_bytes(
                    image.va_to_offset(site.va), len(site.original) + len(site.context_after)
                )
                != site.original + site.context_after
            ):
                msg = f"VR world anchor changed: {name}"
                raise PatchError(msg)

    def _mutations(self, labels: dict[str, int]) -> ExecutableMutationPlan:
        plan = ExecutableMutationPlan(owner="vr_world")
        for name, label, opcode in (
            ("vr.pick_ray", "ray", BranchOpcode.JUMP),
            ("vr.pick_origin", "origin", BranchOpcode.JUMP),
            ("vr.pick_rectangle", "rectangle", BranchOpcode.CALL),
            ("vr.pick_actor_rectangle", "actor_rectangle", BranchOpcode.JUMP),
            ("vr.world_pick", "route", BranchOpcode.JUMP),
        ):
            site = self.profile.site(name)
            plan.branch(
                label=name,
                opcode=opcode,
                site_va=site.va,
                expected=site.original,
                target_va=labels[label],
                size=len(site.original),
            )
        return plan

    def _links(self, query_va: int) -> ExecutableMutationPlan:
        plan = ExecutableMutationPlan(owner="vr_world")
        plan.pointer(
            label="world picking callback",
            slot_va=self.scene.query_slot_va,
            expected=0,
            target_va=query_va,
        )
        return plan

    def apply(self, image: PEFile) -> None:
        """Install dormant explicit picking and scoped native-event redirects."""
        self.precheck(image)
        section = image.add_section(self.section_name, bytes(self.section_size), 0xE0000060)
        base = image.rva_to_va(section.virtual_address)
        payload, labels = self._payload(base)
        image.write_bytes(section.pointer_to_raw_data, payload)
        self._mutations(labels).apply(image)
        self._links(labels["query"]).apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Verify code, redirects, scene ABI and untouched continuations."""
        check_native_scene_types(image, self.profile)
        base = self.abi(image).enabled_va - self._enabled
        expected, labels = self._payload(base)
        if image.read_bytes(image.va_to_offset(base), self.section_size) != expected:
            msg = "VR world payload failed verification"
            raise PatchError(msg)
        self._mutations(labels).verify(image)
        self._links(labels["query"]).verify(image)
        if VRSceneCompiler(profile=self.profile, units_per_meter=1).abi(image) != self.scene:
            msg = "VR world scene boundary failed verification"
            raise PatchError(msg)
        if image.read_u32_va(self.scene.world_input_va) != VRSceneCompiler.world_input_size:
            msg = "VR world input ABI failed verification"
            raise PatchError(msg)
        for name in self._anchors:
            site = self.profile.site(name)
            untouched = name in {"vr.pick_actor_accept", "vr.world_hover"}
            address = site.va if untouched else site.va + len(site.original)
            expected = site.original + site.context_after if untouched else site.context_after
            if image.read_bytes(image.va_to_offset(address), len(expected)) != expected:
                msg = f"VR world continuation failed verification: {name}"
                raise PatchError(msg)

    def _payload(self, base: int) -> tuple[bytes, dict[str, int]]:
        e = X86Emitter(base_va=base + self._code)
        p = self.profile

        def absolute(opcode: bytes, address: int) -> None:
            e.raw(opcode + struct.pack("<I", address))

        def state(opcode: bytes, offset: int) -> None:
            absolute(opcode, base + offset)

        def store(offset: int, value: int) -> None:
            state(b"\xc7\x05", offset)
            e.raw(struct.pack("<I", value))

        def valid_snapshot() -> None:
            state(b"\x83\x3d", self._enabled)
            e.raw(b"\x00")
            e.jump_if(Condition.EQUAL, "snapshot_invalid")
            state(b"\x83\x3d", self._active)
            e.raw(b"\x00")
            e.jump_if(Condition.NOT_EQUAL, "snapshot_invalid")
            absolute(b"\x83\x3d", self.scene.enabled_va)
            e.raw(b"\x00")
            e.jump_if(Condition.EQUAL, "snapshot_invalid")
            absolute(b"\x83\x3d", self.scene.result_va)
            e.raw(b"\x00")
            e.jump_if(Condition.NOT_EQUAL, "snapshot_invalid")
            e.raw(bytes.fromhex("83 f8 01"))
            e.jump_if(Condition.ABOVE, "snapshot_invalid")
            absolute(b"\x83\x3d", self.scene.world_input_va + 8)
            e.raw(b"\x01")
            e.jump_if(Condition.NOT_EQUAL, "snapshot_invalid")
            absolute(b"\x0f\xa3\x05", self.scene.world_input_va + 4)
            e.jump_if(Condition.ABOVE_OR_EQUAL, "snapshot_no_ray")
            e.raw(bytes.fromhex("6b c0 24"))
            absolute(b"\x8d\xb0", self.scene.world_input_va + 108)
            state(b"\xbf", self._ray)
            e.raw(bytes.fromhex("b9 09 00 00 00 fc f3 a5"))

        # Current predicted ray for a visual reticle. This is not completed
        # input and never changes the action-dispatch flag or opens a menu.
        # stdcall(context, hand, ray*, hit*), ret 16. Only the selected hand may
        # point through the room, and visible native menus retain panel priority.
        e.label("query")
        e.raw(bytes.fromhex("55 8b ec 53 56 57"))
        for offset in (self._active, self._dispatch):
            state(b"\x83\x3d", offset)
            e.raw(b"\x00")
            e.jump_if(Condition.NOT_EQUAL, "query_none")
        state(b"\x83\x3d", self._enabled)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "query_none")
        absolute(b"\x83\x3d", self.scene.enabled_va)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "query_none")
        e.raw(bytes.fromhex("8b 45 0c 83 f8 01"))
        e.jump_if(Condition.ABOVE, "query_none")
        state(b"\x3b\x05", self._hand)
        e.jump_if(Condition.NOT_EQUAL, "query_none")
        for offset in (0x10, 0x14):
            e.raw(bytes((0x83, 0x7D, offset, 0)))
            e.jump_if(Condition.EQUAL, "query_none")
        e.call_absolute(p.address("ui.current_layer"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "query_none")
        e.raw(b"\x81\x38" + struct.pack("<I", p.address("vr.room_layer_vtable")))
        e.jump_if(Condition.NOT_EQUAL, "query_none")
        e.raw(bytes.fromhex("8b 50 4c 8b 48 50 81 f9 00 01 00 00"))
        e.jump_if(Condition.ABOVE, "query_none")
        e.raw(bytes.fromhex("85 c9"))
        e.jump_if(Condition.EQUAL, "query_room")
        e.raw(bytes.fromhex("85 d2"))
        e.jump_if(Condition.EQUAL, "query_none")
        e.label("query_children")
        e.raw(bytes.fromhex("8b 02 85 c0"))
        e.jump_if(Condition.EQUAL, "query_next")
        e.raw(bytes.fromhex("80 78 18 00"))
        e.jump_if(Condition.EQUAL, "query_next")
        e.raw(bytes.fromhex("8b 00"))
        for name in ("vr.action_menu_vtable", "vr.toolbar_vtable"):
            e.raw(b"\x3d" + struct.pack("<I", p.address(name)))
            e.jump_if(Condition.EQUAL, "query_none")
        e.label("query_next")
        e.raw(bytes.fromhex("83 c2 04 49"))
        e.jump_if(Condition.NOT_EQUAL, "query_children")
        e.label("query_room")
        absolute(b"\xa1", p.address("vr.room_global"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "query_none")
        emit_native_scene_guard(e, p, register="eax", rejected="query_none")
        e.raw(bytes.fromhex("8b 58 50 85 db"))
        e.jump_if(Condition.EQUAL, "query_none")
        store(self._ready, 0)
        e.raw(bytes.fromhex("8b 75 10"))
        state(b"\xbf", self._ray)
        e.raw(bytes.fromhex("b9 09 00 00 00 fc f3 a5 ff 75 14 6a 00 6a 00"))
        state(b"\x68", self._query_point)
        e.raw(bytes.fromhex("89 d9"))
        e.call("fresh_pick")
        # An eligible world miss is different from a menu/ownership rejection.
        # The renderer may show an aiming beam for the former, never the latter.
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "query_done")
        e.raw(bytes.fromhex("b8 03 00 00 00"))
        e.jump("query_done")
        e.label("query_none")
        e.raw(bytes.fromhex("31 c0"))
        e.label("query_done")
        e.raw(bytes.fromhex("5f 5e 5b c9 c2 10 00"))

        # Freeze before dispatch disables stereo during synchronous native UI
        # redraws. A redraw may clear the producer's output, not this snapshot.
        # Stack argument with callee cleanup: (selected_hand), ret 4.
        e.label("prepare")
        e.raw(bytes.fromhex("53 56 57"))
        store(self._ready, 0)
        e.raw(bytes.fromhex("8b 44 24 10"))
        e.call("snapshot")
        state(b"\xa3", self._ready)
        e.raw(bytes.fromhex("5f 5e 5b c2 04 00"))

        e.label("snapshot")
        valid_snapshot()
        e.raw(bytes.fromhex("b8 01 00 00 00 c3"))
        e.label("snapshot_no_ray")
        # The completed renderer snapshot retains focused, tracked controls
        # during a wall fade, but deliberately publishes no selectable ray.
        # Never copy/reuse the old ray for this navigation-only owner.
        e.raw(bytes.fromhex("6b c0 30"))
        absolute(b"\x83\xb8", self.scene.world_input_va + 12)
        e.raw(b"\x01")
        e.jump_if(Condition.NOT_EQUAL, "snapshot_invalid")
        e.raw(bytes.fromhex("b8 02 00 00 00 c3"))
        e.label("snapshot_invalid")
        e.raw(bytes.fromhex("31 c0 c3"))

        # Only the synchronous VR input transaction can redirect normal game
        # picks. Ordinary mouse, scripts and later updates remain unchanged.
        e.label("route")
        e.raw(b"\x9c")
        state(b"\x83\x3d", self._dispatch)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "route_native")
        e.raw(b"\x9d")
        e.jump("prepared_pick")
        e.label("route_native")
        e.raw(b"\x9d")
        e.label("native_pick")
        site = p.site("vr.world_pick")
        e.raw(site.original[:5])
        e.call_absolute(p.address("vr.seh_prologue"))
        e.jump_absolute(site.va + len(site.original))

        e.label("pick")
        e.raw(bytes.fromhex("55 8b ec 53 56 57"))
        state(b"\x83\x3d", self._enabled)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "no_pick")
        state(b"\x83\x3d", self._active)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "no_pick")
        e.raw(bytes.fromhex("89 cb"))
        state(b"\xa1", self._hand)
        e.call("snapshot")
        e.raw(bytes.fromhex("83 f8 01 89 d9"))
        e.jump_if(Condition.NOT_EQUAL, "no_pick")
        e.jump("pick_node")
        e.label("prepared_pick")
        e.raw(bytes.fromhex("55 8b ec 53 56 57"))
        state(b"\x83\x3d", self._enabled)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "no_pick")
        state(b"\x83\x3d", self._ready)
        e.raw(b"\x01")
        e.jump_if(Condition.NOT_EQUAL, "no_pick")
        state(b"\x83\x3d", self._active)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "no_pick")
        e.jump("pick_node")
        e.label("fresh_pick")
        e.raw(bytes.fromhex("55 8b ec 53 56 57"))
        state(b"\x83\x3d", self._active)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "no_pick")
        e.label("pick_node")
        e.raw(bytes.fromhex("85 c9"))
        e.jump_if(Condition.EQUAL, "no_pick")
        # Refuse another widget type, even if a caller supplies its pointer.
        e.raw(bytes.fromhex("8b 01 81 b8 c4 00 00 00"))
        e.raw(struct.pack("<I", p.site("vr.world_pick").va))
        e.jump_if(Condition.NOT_EQUAL, "no_pick")
        e.raw(bytes.fromhex("89 cb"))
        store(self._active, 1)
        state(b"\xff\x05", self._calls)
        # Native picking uses C++/SEH frames. If an outer handler unwinds this
        # scope, retire its ray ownership rather than leaking it into ordinary
        # engine calls. Do not swallow faults or interfere with inner recovery.
        e.raw(b"\x68")
        e.absolute_label("unwind")
        e.raw(bytes.fromhex("64 ff 35 00 00 00 00 64 89 25 00 00 00 00"))
        for offset in (0x14, 0x10, 0x0C, 0x08):
            e.raw(bytes((0xFF, 0x75, offset)))
        e.raw(bytes.fromhex("89 d9"))
        e.call("native_pick")
        e.raw(bytes.fromhex("8b 14 24 64 89 15 00 00 00 00 83 c4 08"))
        store(self._active, 0)
        e.jump("pick_done")
        e.label("no_pick")
        e.raw(bytes.fromhex("31 c0"))
        e.label("pick_done")
        e.raw(bytes.fromhex("5f 5e 5b c9 c2 10 00"))

        e.label("ray")
        state(b"\x83\x3d", self._active)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "ray_native")
        e.raw(bytes.fromhex("56 57 51 8b 7c 24 14"))  # output near pointer
        state(b"\xbe", self._ray + 12)
        e.raw(bytes.fromhex("b9 03 00 00 00 fc f3 a5 8b 7c 24 18"))
        state(b"\xbe", self._ray + 24)
        e.raw(bytes.fromhex("b9 03 00 00 00 f3 a5 59 5f 5e c3"))
        e.label("ray_native")
        site = p.site("vr.pick_ray")
        e.raw(site.original)
        e.jump_absolute(site.va + len(site.original))

        e.label("unwind")
        e.raw(bytes.fromhex("8b 44 24 04 f7 40 04 06 00 00 00"))
        e.jump_if(Condition.EQUAL, "unwind_search")
        store(self._active, 0)
        store(self._enabled, 0)
        store(self._dispatch, 0)
        store(self._ready, 0)
        state(b"\xff\x05", self._unwinds)
        e.label("unwind_search")
        e.raw(bytes.fromhex("b8 01 00 00 00 c3"))  # ExceptionContinueSearch.

        e.label("origin")
        state(b"\x83\x3d", self._active)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "origin_native")
        state(b"\xb8", self._ray)
        e.raw(b"\xc3")
        e.label("origin_native")
        site = p.site("vr.pick_origin")
        e.raw(site.original)
        e.jump_absolute(site.va + len(site.original))

        e.label("rectangle")
        state(b"\x83\x3d", self._active)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "rectangle_native")
        e.raw(bytes.fromhex("31 c0 80 79 18 00 0f 95 c0 c2 04 00"))
        e.label("rectangle_native")
        e.raw(bytes.fromhex("ff a0 94 00 00 00"))

        e.label("actor_rectangle")
        # Native candidate collection checks the authored screen rectangle
        # before ray intersection. Keep its preceding selectable/resource
        # checks, but include off-screen candidates while a controller picks.
        e.raw(b"\x9c")
        state(b"\x83\x3d", self._active)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "actor_rectangle_native")
        e.raw(b"\x9d")
        e.jump_absolute(p.site("vr.pick_actor_accept").va)
        e.label("actor_rectangle_native")
        e.raw(b"\x9d")
        site = p.site("vr.pick_actor_rectangle")
        e.raw(site.original)
        e.jump_absolute(site.va + len(site.original))

        labels = {name: address for name, _offset, address in e.listing()}
        payload = SegmentPayloadBuilder(
            owner="vr_world", segment=self.section_name, size=self.section_size
        )
        header = bytearray(self._code)
        header[:8] = self._magic
        struct.pack_into("<I", header, self._hand, 1)
        struct.pack_into("<2i", header, self._query_point, -10000, -10000)
        payload.place(label="world picker state", offset=0, payload=bytes(header))
        payload.place(
            label="scoped native picking", offset=self._code, payload=e.build(maximum_size=0xF00)
        )
        return payload.build(), labels
