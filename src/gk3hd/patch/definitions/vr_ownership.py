"""Render-thread world/interface ownership from the original engine graph."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.vr_gps import VRGPSCompiler
from gk3hd.patch.definitions.vr_native_scene import (
    check_native_scene_types,
    emit_native_scene_guard,
)
from gk3hd.patch.definitions.vr_panel import VRPanelCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.vr_gps import VRGPSABI
    from gk3hd.patch.definitions.vr_panel import VRPanelABI
    from gk3hd.patch.definitions.vr_scene import VRSceneABI


@dataclass(frozen=True, slots=True)
class VROwnershipABI:
    """Dormant switch and current classification, not a launcher interface."""

    enabled_va: int
    mode_va: int
    query_va: int


@dataclass(frozen=True, slots=True, kw_only=True)
class VROwnershipCompiler:
    """Choose layers without mutating native UI, camera locks or VR switches.

    Bits are world=1 and panel=2. A free room gets stereo without an opaque
    desktop quad. Visible room menus get both; modal interfaces, unknown layers,
    unavailable room/camera state, camera locks and scripted controllers get
    the panel only. Native glides do not necessarily set the input lock, so
    world ownership also requires the sole active controller to be a verified
    user camera/scene controller. No scripted movement is changed. Transparent
    room HUD isolation and movie-specific comfort handling remain separate.
    Cinematic conversations also use the stationary panel: their authored cuts
    can retain a sole user controller and leave its input lock clear. Consult
    the original conversation owner, not subtitle visibility or camera motion
    heuristics. Respect the native disabled-cinematics policy; ordinary voice-
    overs and free viewing retain stereo.
    """

    profile: BuildProfile
    scene: VRSceneABI
    panel: VRPanelABI
    gps: VRGPSABI | None = None

    section_name: ClassVar[str] = ".gk3vo"
    section_size: ClassVar[int] = 0x1000
    _magic: ClassVar[bytes] = b"GK3XRO01"
    _enabled: ClassVar[int] = 0x0C
    _mode: ClassVar[int] = 0x10
    _code: ClassVar[int] = 0x100

    def abi(self, image: PEFile) -> VROwnershipABI:
        """Resolve the verified native ownership entry."""
        section = image.get_section(self.section_name)
        if section is None or image.read_bytes(section.pointer_to_raw_data, 8) != self._magic:
            msg = "VR ownership section is absent or incompatible"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        return VROwnershipABI(base + self._enabled, base + self._mode, base + self._code)

    def _check(self, image: PEFile) -> None:
        check_native_scene_types(image, self.profile)
        if (
            VRSceneCompiler(profile=self.profile, units_per_meter=1).abi(image) != self.scene
            or VRPanelCompiler(profile=self.profile).abi(image) != self.panel
            or self.panel.world_enabled_va != self.scene.enabled_va
        ):
            msg = "VR ownership requires a linked world/panel boundary"
            raise PatchError(msg)
        if self.gps is not None:
            compiler = VRGPSCompiler(profile=self.profile, world_enabled_va=self.scene.enabled_va)
            if (
                compiler.abi(image) != self.gps
                or self.gps.world_enabled_va != self.scene.enabled_va
            ):
                msg = "VR ownership requires the verified GPS producer"
                raise PatchError(msg)
            compiler.postcheck(image)
        for name in (
            "vr.camera_input_lock",
            "vr.camera_controller_top",
            "vr.camera_controller_stack",
            "vr.user_camera_controller",
            "vr.user_scene_controller",
            "vr.conversation_scene_owner",
            "vr.conversation_context",
            "vr.conversation_active",
            "vr.cinematics_policy",
        ):
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = f"VR ownership native camera anchor changed: {name}"
                raise PatchError(msg)

    def _links(self, query_va: int) -> ExecutableMutationPlan:
        plan = ExecutableMutationPlan(owner="vr_ownership")
        for label, slot in (
            ("world ownership", self.scene.ownership_query_slot_va),
            ("interface ownership", self.panel.ownership_query_slot_va),
        ):
            plan.pointer(label=label, slot_va=slot, expected=0, target_va=query_va)
        return plan

    def apply(self, image: PEFile) -> None:
        """Install a dormant classifier after the two verified producers."""
        if image.get_section(self.section_name) is not None:
            msg = "VR ownership is already installed"
            raise PatchError(msg)
        self._check(image)
        for slot in (self.scene.ownership_query_slot_va, self.panel.ownership_query_slot_va):
            if image.read_u32_va(slot):
                msg = "VR ownership callback is already occupied"
                raise PatchError(msg)
        section = image.add_section(self.section_name, bytes(self.section_size), 0xE0000060)
        base = image.rva_to_va(section.virtual_address)
        image.write_bytes(section.pointer_to_raw_data, self._payload(base))
        self._links(base + self._code).apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Verify dependencies, callback links and complete dormant code."""
        self._check(image)
        abi = self.abi(image)
        base = abi.enabled_va - self._enabled
        if image.read_bytes(image.va_to_offset(base), self.section_size) != self._payload(base):
            msg = "VR ownership payload failed verification"
            raise PatchError(msg)
        self._links(abi.query_va).verify(image)

    def _payload(self, base: int) -> bytes:
        e = X86Emitter(base_va=base + self._code)
        p = self.profile

        def absolute(op: bytes, address: int) -> None:
            e.raw(op + struct.pack("<I", address))

        e.raw(bytes.fromhex("9c 60"))
        absolute(b"\x83\x3d", base + self._enabled)
        e.raw(b"\x01")
        e.jump_if(Condition.NOT_EQUAL, "disabled")
        e.call_absolute(p.address("ui.current_layer"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "panel")
        e.raw(b"\x81\x38" + struct.pack("<I", p.address("vr.room_layer_vtable")))
        e.jump_if(Condition.NOT_EQUAL, "panel")
        e.raw(bytes.fromhex("89 c3"))  # Preserve room root while inspecting camera.
        absolute(b"\xa1", p.address("vr.room_global"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "panel")
        emit_native_scene_guard(e, p, register="eax", rejected="panel")
        e.raw(bytes.fromhex("83 78 50 00"))
        e.jump_if(Condition.EQUAL, "panel")
        absolute(b"\xa1", p.address("engine.loop"))
        for instruction in (b"", bytes.fromhex("8b 80 44 04 00 00"), b"\x8b\x40\x28"):
            e.raw(instruction + bytes.fromhex("85 c0"))
            e.jump_if(Condition.EQUAL, "panel")
        e.raw(b"\x81\x38" + struct.pack("<I", p.address("vr.camera_manager_vtable")))
        e.jump_if(Condition.NOT_EQUAL, "panel")
        # Cinematic dialogue cuts do not necessarily push another camera or
        # lock input. Preserve native cinematics-off behavior and classify the
        # live conversation independently of captions/voice-over text.
        e.raw(bytes.fromhex("80 b8 c4 01 00 00 00"))
        e.jump_if(Condition.EQUAL, "conversation_ready")
        absolute(b"\x8b\x15", p.address("engine.loop"))
        for instruction in (
            bytes.fromhex("8b 92 44 04 00 00"),
            bytes.fromhex("8b 52 60"),
            bytes.fromhex("8b 52 0c"),
            bytes.fromhex("8b 52 08"),
        ):
            e.raw(instruction + bytes.fromhex("85 d2"))
            e.jump_if(Condition.EQUAL, "panel")
        e.raw(bytes.fromhex("83 3a 00"))
        e.jump_if(Condition.NOT_EQUAL, "panel")
        e.label("conversation_ready")
        e.raw(bytes.fromhex("80 b8 c5 01 00 00 00"))
        e.jump_if(Condition.NOT_EQUAL, "panel")
        # Glides stack another controller without setting the input lock.
        # Reject empty/damaged/stacked ownership before the native deque query.
        e.raw(bytes.fromhex("83 b8 b0 00 00 00 01"))
        e.jump_if(Condition.NOT_EQUAL, "panel")
        e.raw(bytes.fromhex("89 c1"))
        e.call_absolute(p.site("vr.camera_controller_top").va)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "panel")
        for name in ("vr.user_camera_controller_vtable", "vr.user_scene_controller_vtable"):
            e.raw(b"\x81\x38" + struct.pack("<I", p.address(name)))
            e.jump_if(Condition.EQUAL, "user_camera")
        e.jump("panel")
        e.label("user_camera")
        if self.gps is not None:
            # Device visibility does not remove world ownership. Its independent
            # source supplies an interactive footprint; damaged ownership falls
            # back to the ordinary completed page instead of losing controls.
            e.call_absolute(self.gps.probe_va)
            e.raw(bytes.fromhex("83 f8 ff"))
            e.jump_if(Condition.EQUAL, "panel")
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.NOT_EQUAL, "combined")
        # Same native child graph used by world input. Bound a damaged graph;
        # do not classify random child dimensions or filename heuristics.
        e.raw(bytes.fromhex("8b 53 4c 8b 4b 50 81 f9 00 01 00 00"))
        e.jump_if(Condition.ABOVE, "panel")
        e.raw(bytes.fromhex("85 c9"))
        e.jump_if(Condition.EQUAL, "world")
        e.raw(bytes.fromhex("85 d2"))
        e.jump_if(Condition.EQUAL, "panel")
        e.label("children")
        e.raw(bytes.fromhex("8b 02 85 c0"))
        e.jump_if(Condition.EQUAL, "next")
        e.raw(bytes.fromhex("80 78 18 00"))
        e.jump_if(Condition.EQUAL, "next")
        e.raw(bytes.fromhex("8b 00"))
        for name in ("vr.action_menu_vtable", "vr.toolbar_vtable"):
            e.raw(b"\x3d" + struct.pack("<I", p.address(name)))
            e.jump_if(Condition.EQUAL, "combined")
        e.label("next")
        e.raw(bytes.fromhex("83 c2 04 49"))
        e.jump_if(Condition.NOT_EQUAL, "children")
        e.label("world")
        e.raw(bytes.fromhex("b8 01 00 00 00"))
        e.jump("done")
        e.label("combined")
        e.raw(bytes.fromhex("b8 03 00 00 00"))
        e.jump("done")
        e.label("panel")
        e.raw(bytes.fromhex("b8 02 00 00 00"))
        e.jump("done")
        e.label("disabled")
        e.raw(bytes.fromhex("31 c0"))
        e.label("done")
        absolute(b"\xa3", base + self._mode)
        # A modal update need not call Room3D::Draw at all. Retire its old
        # producer output here too, before final-page input can consume it.
        e.raw(bytes.fromhex("a8 01"))
        e.jump_if(Condition.NOT_EQUAL, "return")
        for address, value in (
            (self.scene.world_input_va + 4, 0),
            (self.scene.target_va + 4, 0xFFFFFFFF),
            (self.scene.target_va + 8, 0),
        ):
            absolute(b"\xc7\x05", address)
            e.raw(struct.pack("<I", value))
        e.label("return")
        e.raw(bytes.fromhex("89 44 24 1c 61 9d c3"))
        payload = SegmentPayloadBuilder(
            owner="vr_ownership", segment=self.section_name, size=self.section_size
        )
        header = bytearray(0x100)
        header[:8] = self._magic
        payload.place(label="ownership state", offset=0, payload=bytes(header))
        payload.place(
            label="ownership query", offset=self._code, payload=e.build(maximum_size=0xF00)
        )
        return payload.build()
