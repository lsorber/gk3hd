"""Use one recent completed VR head pose in the existing native audio update."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter, encode_rel32_branch
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.vr_ownership import VROwnershipABI
    from gk3hd.patch.definitions.vr_scene import VRSceneABI


@dataclass(frozen=True, slots=True)
class VRListenerABI:
    """Private diagnostics for native audio replacement, independent of volume."""

    applied_va: int
    fallback_va: int
    pose_va: int


@dataclass(frozen=True, slots=True, kw_only=True)
class VRListenerCompiler:
    """Update the VR listener during every native audio tick, including head-only turns.

    The renderer supplies a one-use completed focused head pose, not a newly
    sampled sensor pose. Its rigid forward/up preserve roll. Native cached
    yaw/pitch are applied before the existing software source update and commit.
    Missing export, ownership, device or pose retains the ordinary audio tick.
    No audio thread, buffer, source position, attenuation or volume is changed.
    """

    profile: BuildProfile
    scene: VRSceneABI
    ownership: VROwnershipABI

    section_name: ClassVar[str] = ".gk3au"
    section_size: ClassVar[int] = 0x2000
    _magic: ClassVar[bytes] = b"GK3XRA01"
    _resolved: ClassVar[int] = 0x0C
    _bridge: ClassVar[int] = 0x10
    _applied: ClassVar[int] = 0x18
    _fallback: ClassVar[int] = 0x1C
    _pose: ClassVar[int] = 0x100
    _module: ClassVar[int] = 0x180
    _export: ClassVar[int] = 0x1A0
    _code: ClassVar[int] = 0x1000
    _anchors: ClassVar[tuple[str, ...]] = (
        "vr.audio_tick",
        "vr.audio_listener_call",
        "vr.audio_listener_forward",
        "vr.audio_listener_cache",
        "vr.audio_listener_set",
    )

    def abi(self, image: PEFile) -> VRListenerABI:
        """Resolve counters only from this verified private audio section."""
        section = image.get_section(self.section_name)
        if section is None or image.read_bytes(section.pointer_to_raw_data, 8) != self._magic:
            msg = "VR audio adapter is absent or incompatible"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        return VRListenerABI(base + self._applied, base + self._fallback, base + self._pose)

    def _check(self, image: PEFile, *, installed: bool) -> None:
        for name in self._anchors:
            site = self.profile.site(name)
            if (
                not (installed and name == "vr.audio_tick")
                and image.read_bytes(image.va_to_offset(site.va), len(site.original))
                != site.original
            ):
                msg = f"VR audio dependency changed: {name}"
                raise PatchError(msg)
            for address, expected in (
                (site.va - len(site.context_before), site.context_before),
                (site.va + len(site.original), site.context_after),
            ):
                if (
                    expected
                    and image.read_bytes(image.va_to_offset(address), len(expected)) != expected
                ):
                    msg = f"VR audio context changed: {name}"
                    raise PatchError(msg)

    def apply(self, image: PEFile) -> None:
        """Add a dormant native audio adapter after checking original contracts."""
        self._check(image, installed=False)
        if image.get_section(self.section_name) is not None:
            msg = "VR audio adapter is already installed"
            raise PatchError(msg)
        section = image.add_section(self.section_name, bytes(self.section_size), 0xE0000060)
        base = image.rva_to_va(section.virtual_address)
        image.write_bytes(section.pointer_to_raw_data, self._payload(base))
        site = self.profile.site("vr.audio_tick")
        plan = ExecutableMutationPlan(owner="vr_audio")
        plan.branch(
            label=site.symbol,
            site_va=site.va,
            expected=site.original,
            target_va=base + self._code,
            opcode=BranchOpcode.JUMP,
            size=len(site.original),
        )
        plan.apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Verify the complete adapter, redirect and unchanged native fallback."""
        self._check(image, installed=True)
        self.abi(image)
        section = image.get_section(self.section_name)
        if section is None:
            msg = "VR audio section disappeared during verification"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        if image.read_bytes(section.pointer_to_raw_data, self.section_size) != self._payload(base):
            msg = "VR audio payload failed verification"
            raise PatchError(msg)
        site = self.profile.site("vr.audio_tick")
        expected = encode_rel32_branch(
            opcode=BranchOpcode.JUMP,
            site_va=site.va,
            target_va=base + self._code,
            size=len(site.original),
        )
        if image.read_bytes(image.va_to_offset(site.va), len(expected)) != expected:
            msg = "VR audio redirect failed verification"
            raise PatchError(msg)

    def _payload(self, base: int) -> bytes:
        e = X86Emitter(base_va=base + self._code)
        p = self.profile

        def absolute(opcode: bytes, address: int) -> None:
            e.raw(opcode + struct.pack("<I", address))

        def state(opcode: bytes, offset: int) -> None:
            absolute(opcode, base + offset)

        e.raw(bytes.fromhex("55 8b ec 53 56 57 8b f1"))
        absolute(b"\x83\x3d", self.scene.enabled_va)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "fallback")
        e.call_absolute(self.ownership.query_va)
        e.raw(bytes.fromhex("a8 01"))
        e.jump_if(Condition.EQUAL, "fallback")
        state(b"\x83\x3d", self._resolved)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "resolved")
        state(b"\xc7\x05", self._resolved)
        e.raw(struct.pack("<I", 1))
        state(b"\x68", self._module)
        absolute(b"\xff\x15", p.address("win32.GetModuleHandleA"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "fallback")
        state(b"\x68", self._export)
        e.raw(b"\x50")
        absolute(b"\xff\x15", p.address("win32.GetProcAddress"))
        state(b"\xa3", self._bridge)
        e.label("resolved")
        state(b"\x83\x3d", self._bridge)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "fallback")
        absolute(b"\xa1", p.address("high_resolution_3d.render_wrapper_ptr"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "fallback")
        e.raw(bytes.fromhex("8b 80 e8 04 00 00 85 c0"))
        e.jump_if(Condition.EQUAL, "fallback")
        state(b"\x68", self._pose)
        e.raw(b"\x50")
        state(b"\xff\x15", self._bridge)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "fallback")
        # Reject a failed or malformed native bridge before touching audio.
        for offset in range(4, 48, 4):
            state(b"\xa1", self._pose + offset)
            e.raw(bytes.fromhex("25 ff ff ff 7f 3d 00 00 80 7f"))
            e.jump_if(Condition.ABOVE_OR_EQUAL, "fallback")
        e.raw(bytes.fromhex("8b 5e 54 85 db"))
        e.jump_if(Condition.EQUAL, "cache")
        # Same deferred position/orientation calls as the original setter.
        # The existing native audio tick alone commits the complete batch.
        e.push_imm32(1)
        for offset in (12, 8, 4):
            state(b"\xff\x35", self._pose + offset)
        e.raw(bytes.fromhex("53 8b 03 ff 50 38 85 c0"))
        e.jump_if(Condition.SIGN, "rollback")
        e.push_imm32(1)
        for offset in (36, 32, 28, 24, 20, 16):
            state(b"\xff\x35", self._pose + offset)
        e.raw(bytes.fromhex("53 8b 03 ff 50 34 85 c0"))
        e.jump_if(Condition.SIGN, "rollback")
        e.label("cache")
        # The original audio tick updates software sources immediately after
        # this adapter. Change the same five cache fields without running its
        # source loop a second time. This also works when only the HMD moves.
        for source, target in ((4, 0x14), (8, 0x18), (12, 0x1C), (40, 0x20), (44, 0x24)):
            state(b"\xa1", self._pose + source)
            e.raw(bytes((0x89, 0x46, target)))
        state(b"\xff\x05", self._applied)
        e.jump("done")
        e.label("rollback")
        # Until both COM calls succeed, the native cached viewpoint is intact.
        # Restore the original setter on failure; its ordinary error behavior
        # and the subsequent native audio tick remain authoritative.
        e.raw(bytes.fromhex("ff 76 24 ff 76 20 8d 46 14 50 8b ce"))
        e.call_absolute(p.site("vr.audio_listener_set").va)
        e.label("fallback")
        state(b"\xff\x05", self._fallback)
        e.label("done")
        e.raw(bytes.fromhex("8b ce 5f 5e 5b c9"))
        tick = p.site("vr.audio_tick")
        e.raw(tick.original)
        e.jump_absolute(tick.va + len(tick.original))
        payload = SegmentPayloadBuilder(
            owner="vr_audio", segment=self.section_name, size=self.section_size
        )
        payload.place(label="identity", offset=0, payload=self._magic)
        payload.place(label="pose", offset=self._pose, payload=struct.pack("<I", 48))
        payload.place(label="module", offset=self._module, payload=b"ddraw.dll\0")
        payload.place(label="export", offset=self._export, payload=b"Gk3hdXrListenerV1\0")
        payload.place(label="code", offset=self._code, payload=e.build(maximum_size=0x1000))
        return payload.build()
