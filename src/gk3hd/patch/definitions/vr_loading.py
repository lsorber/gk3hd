"""Keep headset frames flowing while native scene construction or teardown blocks."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter
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
    from gk3hd.patch.definitions.vr_panel import VRPanelABI
    from gk3hd.patch.definitions.vr_scene import VRSceneABI
    from gk3hd.patch.definitions.vr_text import VRTextABI


@dataclass(frozen=True, slots=True)
class VRLoadingABI:
    """Attempt/result counters, not an independent activation switch."""

    calls_va: int
    result_va: int
    cleared_frames_va: int


@dataclass(frozen=True, slots=True, kw_only=True)
class VRLoadingCompiler:
    """Cover resource/scene-owner retirement and construction with safe fallbacks.

    Empty XR frames replace the outgoing world, UI and keyboard while native
    construction or teardown blocks, including asset work before UserScene exists
    and resource purging/exit callbacks before its destructor. Only the active
    native location manager can enter the earlier resource boundary. The renderer
    owns a frame helper, not another game thread. It does not accelerate loading
    or hold a screenshot.
    The next ordinary frame joins the helper and resumes presentation. Dormant
    flat behavior and native construction/destruction are intact.
    """

    profile: BuildProfile
    panel: VRPanelABI
    scene: VRSceneABI
    text: VRTextABI
    section_name: ClassVar[str] = ".gk3vl"
    _size: ClassVar[int] = 0x800
    _code: ClassVar[int] = 0x100
    _magic: ClassVar[bytes] = b"GK3XRL01"
    _sites: ClassVar[tuple[tuple[str, int], ...]] = (
        ("vr.scene_retire", 0x100),
        ("vr.scene_create", 0x200),
        ("vr.scene_owner_retire", 0x300),
        ("vr.scene_owner_create", 0x400),
        ("vr.scene_resource_retire", 0x500),
    )

    def abi(self, image: PEFile) -> VRLoadingABI:
        """Resolve independently verifiable loading observations."""
        section = image.get_section(self.section_name)
        if section is None or image.read_bytes(section.pointer_to_raw_data, 8) != self._magic:
            msg = "VR loading boundary is absent or incompatible"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        return VRLoadingABI(base + 12, base + 16, base + 20)

    def _check(self, image: PEFile) -> None:
        check_native_scene_types(image, self.profile)
        if (
            VRSceneCompiler(profile=self.profile, units_per_meter=1).abi(image) != self.scene
            or VRPanelCompiler(profile=self.profile).abi(image) != self.panel
            or self.panel.world_enabled_va != self.scene.enabled_va
        ):
            msg = "VR loading requires the linked world/panel boundary"
            raise PatchError(msg)
        for name, _ in self._sites:
            site = self.profile.site(name)
            if site.context_before and (
                image.read_bytes(
                    image.va_to_offset(site.va - len(site.context_before)), len(site.context_before)
                )
                != site.context_before
            ):
                msg = "VR loading native resource context changed"
                raise PatchError(msg)
            if (
                image.read_bytes(image.va_to_offset(site.va + 5), len(site.context_after))
                != site.context_after
            ):
                msg = "VR loading native scene context changed"
                raise PatchError(msg)

    def _plan(self, base: int) -> ExecutableMutationPlan:
        plan = ExecutableMutationPlan(owner="vr_loading")
        for name, offset in self._sites:
            site = self.profile.site(name)
            plan.branch(
                label=name,
                opcode=BranchOpcode.JUMP,
                site_va=site.va,
                expected=site.original,
                target_va=base + offset,
                size=5,
            )
        return plan

    def _payload(self, base: int) -> bytes:
        code = X86Emitter(base_va=base + self._code)
        for name, offset in self._sites:
            code.nop(offset - self._code - code.offset)
            native = f"{name}.native"
            code.raw(bytes.fromhex("9c 60"))
            for address in (self.panel.enabled_va, self.scene.enabled_va):
                code.raw(b"\x83\x3d" + struct.pack("<I", address) + b"\x01")
                code.jump_if(Condition.NOT_EQUAL, native)
            if name == "vr.scene_resource_retire":
                # Location-manager resource purging precedes the scene owner.
                # Reject foreign/cache-only managers, absent services and unknown
                # active scene types; never change the manager's native members.
                code.raw(bytes.fromhex("85 c9"))
                code.jump_if(Condition.EQUAL, native)
                code.raw(b"\xa1" + struct.pack("<I", self.profile.address("engine.loop")))
                code.raw(bytes.fromhex("85 c0"))
                code.jump_if(Condition.EQUAL, native)
                code.raw(bytes.fromhex("8b 80 44 04 00 00 85 c0"))
                code.jump_if(Condition.EQUAL, native)
                code.raw(bytes.fromhex("3b 48 60"))
                code.jump_if(Condition.NOT_EQUAL, native)
                code.raw(b"\x8b\x0d" + struct.pack("<I", self.profile.address("vr.room_global")))
                code.raw(bytes.fromhex("85 c9"))
                code.jump_if(Condition.NOT_EQUAL, "resource_scene")
                # Fullscreen map travel has already withdrawn both scene
                # globals before purging graphics. The verified live manager
                # still owns this boundary; do not wait for a new constructor.
                # A partially published owner remains a guarded fallback case.
                code.raw(
                    b"\x83\x3d"
                    + struct.pack("<I", self.profile.address("vr.scene_owner_global"))
                    + b"\x00"
                )
                code.jump_if(Condition.NOT_EQUAL, native)
                code.jump("resource_ready")
                code.label("resource_scene")
                emit_native_scene_guard(code, self.profile, register="ecx", rejected=native)
                code.label("resource_ready")
            elif name in {"vr.scene_retire", "vr.scene_owner_retire"}:
                code.raw(bytes.fromhex("85 c9"))
                code.jump_if(Condition.EQUAL, native)
                if name == "vr.scene_owner_retire":
                    # The owner invokes exit/unregistration before UserScene's
                    # destructor. Its active UserScene must still be ours.
                    code.raw(bytes.fromhex("8b 49 14 85 c9"))
                    code.jump_if(Condition.EQUAL, native)
                code.raw(b"\x3b\x0d" + struct.pack("<I", self.profile.address("vr.room_global")))
                code.jump_if(Condition.NOT_EQUAL, native)
                emit_native_scene_guard(code, self.profile, register="ecx", rejected=native)
            else:
                # Initial Play has no outgoing scene. Never inspect the incoming
                # object's uninitialized vtable, and leave live scenes alone.
                code.raw(
                    b"\x83\x3d"
                    + struct.pack("<I", self.profile.address("vr.room_global"))
                    + b"\x00"
                )
                code.jump_if(Condition.NOT_EQUAL, native)
                if name == "vr.scene_owner_create":
                    code.raw(
                        b"\x83\x3d"
                        + struct.pack("<I", self.profile.address("vr.scene_owner_global"))
                        + b"\x00"
                    )
                    code.jump_if(Condition.NOT_EQUAL, native)
            code.call("loading")
            code.label(native)
            code.raw(bytes.fromhex("61 9d"))
            site = self.profile.site(name)
            code.raw(site.original)
            code.jump_absolute(site.va + len(site.original))
        code.label("loading")
        bridge = self.panel.renderer_bridge_slot_va
        code.raw(b"\x83\x3d" + struct.pack("<I", bridge) + b"\x00")
        code.jump_if(Condition.EQUAL, "return")
        code.raw(
            b"\xa1"
            + struct.pack("<I", self.profile.address("high_resolution_3d.render_wrapper_ptr"))
        )
        code.raw(bytes.fromhex("85 c0"))
        code.jump_if(Condition.EQUAL, "return")
        code.raw(bytes.fromhex("8b 80 e8 04 00 00 85 c0"))
        code.jump_if(Condition.EQUAL, "return")
        code.raw(b"\xff\x05" + struct.pack("<I", base + 12))
        code.raw(bytes.fromhex("6a 00 6a 07 50"))  # No source image or input request.
        code.raw(b"\xff\x15" + struct.pack("<I", bridge))
        code.raw(b"\xa3" + struct.pack("<I", base + 16))
        code.raw(bytes.fromhex("85 c0"))
        code.jump_if(Condition.NOT_EQUAL, "retire")
        code.raw(b"\xff\x05" + struct.pack("<I", base + 20))
        code.label("retire")
        # Never carry outgoing hits/characters into the replacement scene. Keep
        # ABI sizes, native buffers, editor contents and activation switches.
        for address, count in (
            (self.panel.frame_va + 28, 40),
            (self.scene.world_input_va + 4, 44),
            (self.scene.target_va + 4, 5),
        ):
            code.raw(b"\xbf" + struct.pack("<I", address))
            code.raw(b"\xb9" + struct.pack("<I", count) + bytes.fromhex("31 c0 fc f3 ab"))
        for address in (
            self.scene.frame_pending_va,
            self.text.focus_va,
            self.text.layer_va,
            self.text.request_va,
        ):
            code.raw(b"\xc7\x05" + struct.pack("<I", address) + bytes(4))
        if self.scene.prewarm_owner_va is not None:
            code.raw(b"\xc7\x05" + struct.pack("<I", self.scene.prewarm_owner_va) + bytes(4))
        code.raw(
            b"\xc7\x05" + struct.pack("<I", self.scene.target_va + 4) + bytes.fromhex("ff ff ff ff")
        )
        code.label("return")
        code.ret()
        payload = bytearray(self._size)
        payload[:8] = self._magic
        emitted = code.build(maximum_size=self._size - self._code)
        payload[self._code : self._code + len(emitted)] = emitted
        return bytes(payload)

    def apply(self, image: PEFile) -> None:
        """Publish only in an independently built private VR player."""
        self._check(image)
        if image.get_section(self.section_name) is not None:
            msg = "VR loading boundary is already installed"
            raise PatchError(msg)
        for name, _ in self._sites:
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = "VR loading native entry changed"
                raise PatchError(msg)
        section = image.add_section(self.section_name, bytes(self._size), 0xE0000060)
        base = image.rva_to_va(section.virtual_address)
        image.write_bytes(section.pointer_to_raw_data, self._payload(base))
        self._plan(base).apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Verify every loading hook and unchanged native scene contexts."""
        self._check(image)
        abi = self.abi(image)
        base = abi.calls_va - 12
        if image.read_bytes(image.va_to_offset(base), self._size) != self._payload(base):
            msg = "VR loading payload failed verification"
            raise PatchError(msg)
        self._plan(base).verify(image)
