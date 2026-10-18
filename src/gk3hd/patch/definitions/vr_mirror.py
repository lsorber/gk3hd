"""Keep the VR player's desktop mirror from replacing flat display preferences."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile


@dataclass(frozen=True, slots=True, kw_only=True)
class VRMirrorABI:
    """Launch-owned protection, independent of renderer frame availability."""

    enabled_va: int


@dataclass(frozen=True, slots=True, kw_only=True)
class VRMirrorCompiler:
    """Suppress only display DWORD writes for the private VR launch lifetime.

    Native command-line window/width/height arguments otherwise persist Screen
    Width, Screen Height and Full Screen. This guard wraps the game's registry
    writer, not the system API or other processes. Reads, key lifetime, other
    settings, and native error returns for forwarded writes remain unchanged.
    The five display values are compared case-insensitively and exactly. No
    registry backup/restore race is introduced into the launch supervisor.
    VR also keeps the native brightness interface available with a windowed
    mirror, retaining capability checks and the original COM query/lifetime.
    Render failure must not retire this guard and persist mirror preferences.
    """

    profile: BuildProfile
    section_name: ClassVar[str] = ".vrxreg"
    _size: ClassVar[int] = 0x400
    _enabled: ClassVar[int] = 0x0C
    _code: ClassVar[int] = 0x40
    _names: ClassVar[int] = 0x300
    _gamma: ClassVar[int] = 0x380
    _magic: ClassVar[bytes] = b"GK3XRG01"
    _site: ClassVar[str] = "vr.mirror_preferences"
    _gamma_site: ClassVar[str] = "vr.windowed_gamma_query"
    _values: ClassVar[tuple[bytes, ...]] = (
        b"screen width",
        b"screen height",
        b"full screen",
        b"game width",
        b"game height",
    )

    def abi(self, image: PEFile) -> VRMirrorABI:
        """Locate the private launch switch without depending on render state."""
        section = image.get_section(self.section_name)
        if section is None or image.read_bytes(section.pointer_to_raw_data, 8) != self._magic:
            msg = "VR mirror preference section is absent or incompatible"
            raise PatchError(msg)
        return VRMirrorABI(enabled_va=image.rva_to_va(section.virtual_address) + self._enabled)

    def _check_context(self, image: PEFile) -> None:
        for name in (self._site, self._gamma_site):
            site = self.profile.site(name)
            for address, expected in (
                (site.va - len(site.context_before), site.context_before),
                (site.va + len(site.original), site.context_after),
            ):
                if image.read_bytes(image.va_to_offset(address), len(expected)) != expected:
                    msg = f"VR mirror native context changed: {name}"
                    raise PatchError(msg)

    def _payload(self, base: int) -> bytes:
        payload = bytearray(self._size)
        payload[:8] = self._magic
        code = X86Emitter(base_va=base + self._code)
        code.raw(bytes.fromhex("9c 60"))
        code.raw(b"\x83\x3d" + struct.pack("<I", base + self._enabled) + b"\x00")
        code.jump_if(Condition.EQUAL, "native")
        # After PUSHFD/PUSHAD: DWORD type, byte count and name are original
        # RegSetValueExA arguments, not offsets into the native writer frame.
        for offset in (0x34, 0x3C):
            code.raw(bytes((0x83, 0x7C, 0x24, offset, 4)))
            code.jump_if(Condition.NOT_EQUAL, "native")
        code.raw(bytes.fromhex("8b 54 24 2c 85 d2"))
        code.jump_if(Condition.EQUAL, "native")
        cursor = self._names
        for index, name in enumerate(self._values):
            payload[cursor : cursor + len(name) + 1] = name + b"\0"
            code.raw(b"\xbe" + struct.pack("<I", base + cursor))
            code.raw(b"\xb9" + struct.pack("<I", len(name)))
            code.raw(bytes.fromhex("8b fa"))
            code.label(f"compare-{index}")
            code.raw(bytes.fromhex("8a 07 84 c0"))
            code.jump_if(Condition.EQUAL, f"next-{index}")
            code.raw(bytes.fromhex("0c 20 3a 06"))
            code.jump_if(Condition.NOT_EQUAL, f"next-{index}")
            code.raw(bytes.fromhex("47 46 49"))
            code.jump_if(Condition.NOT_EQUAL, f"compare-{index}")
            code.raw(bytes.fromhex("80 3f 00"))
            code.jump_if(Condition.EQUAL, "suppressed")
            code.label(f"next-{index}")
            cursor += len(name) + 1
        code.label("native")
        code.raw(bytes.fromhex("61 9d"))
        # Tail-dispatch keeps the original six arguments and native stdcall
        # cleanup, including nonzero failure results. Never call with a second
        # wrapper return address between the API and its arguments.
        code.raw(b"\xff\x25" + self.profile.site(self._site).original[2:])
        code.label("suppressed")
        code.raw(bytes.fromhex("c7 44 24 1c 00 00 00 00 61 9d c2 18 00"))
        emitted = code.build(maximum_size=self._names - self._code)
        payload[self._code : self._code + len(emitted)] = emitted
        gamma = self._gamma_payload(base)
        payload[self._gamma : self._gamma + len(gamma)] = gamma
        return bytes(payload)

    def _gamma_payload(self, base: int) -> bytes:
        site = self.profile.site(self._gamma_site)
        continuation = site.va + len(site.original)
        rejected = continuation + struct.unpack("<b", site.original[-1:])[0]
        code = X86Emitter(base_va=base + self._gamma)
        code.raw(b"\x9c\x83\x3d" + struct.pack("<I", base + self._enabled) + b"\x00")
        code.jump_if(Condition.NOT_EQUAL, "vr")
        code.raw(b"\x9d" + site.original[:3])
        code.jump_if(Condition.EQUAL, "rejected")
        code.jump_absolute(continuation)
        code.label("vr")
        code.raw(b"\x9d")
        code.jump_absolute(continuation)
        code.label("rejected")
        code.jump_absolute(rejected)
        return code.build(maximum_size=self._size - self._gamma)

    def _plan(self, base: int) -> ExecutableMutationPlan:
        plan = ExecutableMutationPlan(owner="vr_mirror")
        for name, offset, opcode in (
            (self._site, self._code, BranchOpcode.CALL),
            (self._gamma_site, self._gamma, BranchOpcode.JUMP),
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
        """Publish a dormant guard only in the private compiled VR player."""
        self._check_context(image)
        if image.get_section(self.section_name) is not None:
            msg = "VR mirror preference guard is already installed"
            raise PatchError(msg)
        for name in (self._site, self._gamma_site):
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = f"VR mirror native entry changed: {name}"
                raise PatchError(msg)
        section = image.add_section(self.section_name, bytes(self._size), 0xE0000060)
        base = image.rva_to_va(section.virtual_address)
        image.write_bytes(section.pointer_to_raw_data, self._payload(base))
        self._plan(base).apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Verify the native context, complete guard and dormant launch switch."""
        self._check_context(image)
        section = image.get_section(self.section_name)
        if section is None:
            msg = "VR mirror preference guard is missing"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        if image.read_bytes(section.pointer_to_raw_data, self._size) != self._payload(base):
            msg = "VR mirror preference guard failed verification"
            raise PatchError(msg)
        self._plan(base).verify(image)
