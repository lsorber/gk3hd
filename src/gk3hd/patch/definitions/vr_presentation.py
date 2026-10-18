"""Complete VR frames independently of native desktop focus/presentation."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.vr_panel import VRPanelCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.vr_panel import VRPanelABI
    from gk3hd.patch.definitions.vr_scene import VRSceneABI


@dataclass(frozen=True, slots=True, kw_only=True)
class VRPresentationCompiler:
    """Keep active VR updating and finish frames at completed-page boundaries.

    GK3's windowed path never calls Flip. Its entry precedes the bounded Blt
    retry loop, so a retry cannot duplicate an XR frame or controller action.
    The live callback slot includes text/input consumers installed after the
    panel producer. Fullscreen presentation and the native blit remain intact.
    No artificial successful-Flip generation or page exchange is introduced.
    An inactive desktop normally blocks the main loop in WaitMessage and skips
    page presentation. Active VR bypasses only that update gate, retaining the
    device-health check, then finalizes before the unchanged inactive-page exit.
    Native focus state, messages and minimized desktop blits remain unchanged.
    With both VR producers disabled, native behavior is unchanged, except that
    an already pending world can finish cancellation before returning dormant.
    """

    profile: BuildProfile
    panel: VRPanelABI
    scene: VRSceneABI
    section_name: ClassVar[str] = ".vrxwnd"
    _size: ClassVar[int] = 0x400
    _code: ClassVar[int] = 0x40
    _inactive_present: ClassVar[int] = 0x140
    _inactive_update: ClassVar[int] = 0x240
    _sites: ClassVar[tuple[str, ...]] = (
        "vr.windowed_present",
        "vr.inactive_present",
        "vr.inactive_update",
    )
    _magic: ClassVar[bytes] = b"GK3XRW02"

    def _check(self, image: PEFile) -> int:
        if (
            VRPanelCompiler(profile=self.profile).abi(image) != self.panel
            or VRSceneCompiler(profile=self.profile, units_per_meter=1).abi(image) != self.scene
            or self.panel.world_enabled_va != self.scene.enabled_va
        ):
            msg = "windowed VR presentation requires the verified panel boundary"
            raise PatchError(msg)
        for name in self._sites:
            site = self.profile.site(name)
            before = image.read_bytes(
                image.va_to_offset(site.va - len(site.context_before)), len(site.context_before)
            )
            continuation = image.read_bytes(
                image.va_to_offset(site.va + len(site.original)), len(site.context_after)
            )
            if before != site.context_before or continuation != site.context_after:
                msg = f"VR presentation native continuation changed: {name}"
                raise PatchError(msg)
        slot = TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va
        presenter = image.read_u32_va(slot)
        if not presenter:
            msg = "windowed VR presentation requires a linked presenter"
            raise PatchError(msg)
        image.va_to_offset(presenter)
        return slot

    def _active(self, code: X86Emitter, *, active: str, dormant: str) -> None:
        # Finalize a world begun before both producer switches were disabled.
        # A deferred XR frame must not survive a mid-frame ownership change.
        for address in (
            self.panel.enabled_va,
            self.scene.enabled_va,
            self.scene.frame_pending_va,
        ):
            if address:
                code.raw(b"\x83\x3d" + struct.pack("<I", address) + b"\x00")
                code.jump_if(Condition.NOT_EQUAL, active)
        code.jump(dormant)

    @staticmethod
    def _present(code: X86Emitter, *, base: int, slot: int) -> None:
        code.label("present")
        code.raw(b"\xa1" + struct.pack("<I", slot) + b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\xff\xd0")
        code.raw(b"\xff\x05" + struct.pack("<I", base + 0x10))

    def _payload(self, base: int, slot: int) -> bytes:
        payload = bytearray(self._size)
        payload[:8] = self._magic
        code = X86Emitter(base_va=base + self._code)
        code.raw(bytes.fromhex("9c 60"))
        self._active(code, active="present", dormant="native")
        self._present(code, base=base, slot=slot)
        code.label("native")
        code.raw(bytes.fromhex("61 9d"))
        code.raw(self.profile.site("vr.windowed_present").original)
        code.ret()
        emitted = code.build(maximum_size=self._inactive_present - self._code)
        payload[self._code : self._code + len(emitted)] = emitted

        code = X86Emitter(base_va=base + self._inactive_present)
        code.raw(bytes.fromhex("9c 60 83 7e 64 00"))
        code.jump_if(Condition.LESS_OR_EQUAL, "native")
        self._active(code, active="present", dormant="native")
        self._present(code, base=base, slot=slot)
        code.label("native")
        code.raw(bytes.fromhex("61 9d"))
        code.raw(self.profile.site("vr.inactive_present").original)
        code.ret()
        emitted = code.build(maximum_size=self._inactive_update - self._inactive_present)
        payload[self._inactive_present : self._inactive_present + len(emitted)] = emitted

        site = self.profile.site("vr.inactive_update")
        code = X86Emitter(base_va=base + self._inactive_update)
        code.raw(bytes.fromhex("9c 60"))
        self._active(code, active="update", dormant="native")
        code.label("update")
        code.raw(bytes.fromhex("61 9d"))
        code.raw(site.original)
        code.raw(bytes.fromhex("85 d2"))  # Keep TEST's flags, skip only inactive JG.
        code.jump_absolute(site.va + len(site.original) + 4)
        code.label("native")
        code.raw(bytes.fromhex("61 9d"))
        code.raw(site.original)
        code.jump_absolute(site.va + len(site.original))
        emitted = code.build(maximum_size=self._size - self._inactive_update)
        payload[self._inactive_update : self._inactive_update + len(emitted)] = emitted
        return bytes(payload)

    def _plan(self, base: int) -> ExecutableMutationPlan:
        plan = ExecutableMutationPlan(owner="vr_presentation")
        for name, offset, opcode in (
            ("vr.windowed_present", self._code, BranchOpcode.CALL),
            ("vr.inactive_present", self._inactive_present, BranchOpcode.CALL),
            ("vr.inactive_update", self._inactive_update, BranchOpcode.JUMP),
        ):
            site = self.profile.site(name)
            plan.branch(
                label=name,
                opcode=opcode,
                site_va=site.va,
                expected=site.original,
                target_va=base + offset,
                size=len(site.original),
            )
        return plan

    def apply(self, image: PEFile) -> None:
        """Publish a dormant VR-only boundary after all presenter consumers."""
        if image.get_section(self.section_name) is not None:
            msg = "windowed VR presentation is already installed"
            raise PatchError(msg)
        slot = self._check(image)
        for name in self._sites:
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = f"VR presentation native entry changed: {name}"
                raise PatchError(msg)
        section = image.add_section(self.section_name, bytes(self._size), 0xE0000060)
        base = image.rva_to_va(section.virtual_address)
        image.write_bytes(section.pointer_to_raw_data, self._payload(base, slot))
        self._plan(base).apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Verify native continuation, producer links and every emitted byte."""
        slot = self._check(image)
        section = image.get_section(self.section_name)
        if section is None:
            msg = "windowed VR presentation is missing"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        if image.read_bytes(section.pointer_to_raw_data, self._size) != self._payload(base, slot):
            msg = "windowed VR presentation payload failed verification"
            raise PatchError(msg)
        self._plan(base).verify(image)
