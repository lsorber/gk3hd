"""Read the designated native floor without treating furniture as ground."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.vr_native_scene import (
    check_native_scene_types,
    emit_native_scene_guard,
)
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile


@dataclass(frozen=True, slots=True)
class VRFloorABI:
    """Read-only stdcall(context, from*, to*, hit*) query, matching scene geometry."""

    query_va: int  # Direct floor: 1 hit, 0 miss, -1 unavailable.
    observer_query_va: int  # 0 authored owner, 1 floor hit, 2 upright/unknown height.


@dataclass(frozen=True, slots=True, kw_only=True)
class VRFloorCompiler:
    """Provide a finite segment query restricted to the current room's SIF floor.

    Return 1 for a floor hit, 0 for a miss, -1 for unavailable/invalid inputs.
    The observer wrapper distinguishes non-user ownership (0) from missing
    ground under a user camera (2), so an unknown height cannot tilt VR.
    Scenery and actor meshes are not substitutes for the designated floor.
    No camera, actor, visibility, simulation or walker data is changed. The
    caller chooses the segment and must validate returned hit coordinates.
    """

    profile: BuildProfile

    section_name: ClassVar[str] = ".gk3vf"
    section_size: ClassVar[int] = 0x800
    _code: ClassVar[int] = 0x100
    _observer: ClassVar[int] = 0x500
    _magic: ClassVar[bytes] = b"GK3XRF01"
    _anchors: ClassVar[tuple[str, ...]] = (
        "vr.geometry_segment",
        "vr.floor_scene_data",
        "vr.floor_data_name",
        "vr.floor_string_buffer",
        "vr.camera_input_lock",
        "vr.camera_controller_top",
        "vr.camera_controller_stack",
        "vr.user_camera_controller",
        "vr.user_scene_controller",
    )

    def _check(self, image: PEFile) -> None:
        check_native_scene_types(image, self.profile)
        for name in self._anchors:
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = f"VR floor query dependency changed: {name}"
                raise PatchError(msg)

    def abi(self, image: PEFile) -> VRFloorABI:
        """Return the adapter entry after checking its identity."""
        section = image.get_section(self.section_name)
        if section is None or image.read_bytes(section.pointer_to_raw_data, 8) != self._magic:
            msg = "VR floor query is absent or incompatible"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        return VRFloorABI(base + self._code, base + self._observer)

    def apply(self, image: PEFile) -> None:
        """Add an inert query entry, without changing any original call site."""
        if image.get_section(self.section_name) is not None:
            msg = "VR floor query is already installed"
            raise PatchError(msg)
        self._check(image)
        section = image.add_section(self.section_name, bytes(self.section_size), 0xE0000060)
        image.write_bytes(
            section.pointer_to_raw_data, self._payload(image.rva_to_va(section.virtual_address))
        )

    def postcheck(self, image: PEFile) -> None:
        """Verify layout dependencies and the complete callback."""
        self._check(image)
        base = self.abi(image).query_va - self._code
        if image.read_bytes(image.va_to_offset(base), self.section_size) != self._payload(base):
            msg = "VR floor query payload failed verification"
            raise PatchError(msg)

    def _payload(self, base: int) -> bytes:
        e = X86Emitter(base_va=base + self._code)

        def absolute(op: bytes, address: int) -> None:
            e.raw(op + struct.pack("<I", address))

        e.raw(bytes.fromhex("55 8b ec 53 56 57"))
        for offset in (0x0C, 0x10, 0x14):
            e.raw(bytes((0x83, 0x7D, offset, 0)))
            e.jump_if(Condition.EQUAL, "unavailable")
        for pointer in (0x0C, 0x10):
            e.raw(bytes((0x8B, 0x55, pointer)))
            for offset in (0, 4, 8):
                e.raw(bytes((0x8B, 0x42, offset)))
                e.raw(bytes.fromhex("25 ff ff ff 7f 3d 00 00 80 7f"))
                e.jump_if(Condition.ABOVE_OR_EQUAL, "unavailable")
        absolute(b"\xa1", self.profile.address("vr.room_global"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "unavailable")
        emit_native_scene_guard(e, self.profile, register="eax", rejected="unavailable")
        e.raw(bytes.fromhex("8b 78 54 85 ff"))
        e.jump_if(Condition.EQUAL, "unavailable")
        e.raw(bytes.fromhex("8b 7f 08 85 ff"))
        e.jump_if(Condition.EQUAL, "unavailable")
        e.raw(bytes.fromhex("80 3f 00"))
        e.jump_if(Condition.EQUAL, "unavailable")
        e.raw(bytes.fromhex("8b 40 50 85 c0"))
        e.jump_if(Condition.EQUAL, "unavailable")
        e.raw(bytes.fromhex("8b 58 2c 85 db"))
        e.jump_if(Condition.EQUAL, "unavailable")
        absolute(b"\x8b\x0d", self.profile.address("vr.renderer_global"))
        e.raw(bytes.fromhex("85 c9"))
        e.jump_if(Condition.EQUAL, "unavailable")
        for _ in range(3):
            e.push_imm32(0)
        e.raw(bytes.fromhex("57 ff 75 14"))  # floor filter, hit pointer
        e.push_imm32(0)
        e.push_imm32(0)
        e.raw(bytes.fromhex("ff 75 10 ff 75 0c 53"))
        e.call_absolute(self.profile.site("vr.geometry_segment").va)
        e.jump("done")
        e.label("unavailable")
        e.raw(bytes.fromhex("b8 ff ff ff ff"))
        e.label("done")
        e.raw(bytes.fromhex("5f 5e 5b c9 c2 10 00"))
        code = e.build(maximum_size=self._observer - self._code)
        observer = X86Emitter(base_va=base + self._observer)
        observer.raw(bytes.fromhex("55 8b ec"))
        # Match the original camera ownership guards used by VR navigation.
        # Scripted/locked cameras keep their authored viewpoint, not standing height.
        observer.raw(b"\xa1" + struct.pack("<I", self.profile.address("engine.loop")))
        for instruction in (b"", bytes.fromhex("8b 80 44 04 00 00"), b"\x8b\x40\x28"):
            observer.raw(instruction + bytes.fromhex("85 c0"))
            observer.jump_if(Condition.EQUAL, "authored")
        observer.raw(
            bytes.fromhex("81 38")
            + struct.pack("<I", self.profile.address("vr.camera_manager_vtable"))
        )
        observer.jump_if(Condition.NOT_EQUAL, "authored")
        observer.raw(bytes.fromhex("80 b8 c5 01 00 00 00"))
        observer.jump_if(Condition.NOT_EQUAL, "authored")
        observer.raw(bytes.fromhex("83 b8 b0 00 00 00 01"))
        observer.jump_if(Condition.NOT_EQUAL, "authored")
        observer.raw(bytes.fromhex("89 c1"))
        observer.call_absolute(self.profile.site("vr.camera_controller_top").va)
        observer.raw(bytes.fromhex("85 c0"))
        observer.jump_if(Condition.EQUAL, "authored")
        for name in ("vr.user_camera_controller_vtable", "vr.user_scene_controller_vtable"):
            observer.raw(b"\x81\x38" + struct.pack("<I", self.profile.address(name)))
            observer.jump_if(Condition.EQUAL, "observer")
        observer.jump("authored")
        observer.label("observer")
        observer.raw(bytes.fromhex("ff 75 14 ff 75 10 ff 75 0c ff 75 08"))
        observer.call_absolute(base + self._code)
        # Missing ground must not confuse an ordinary pitched free camera
        # with a scripted owner. Retain its height, but keep VR upright.
        observer.raw(bytes.fromhex("83 f8 00"))
        observer.jump_if(Condition.EQUAL, "upright")
        observer.raw(bytes.fromhex("83 f8 ff"))
        observer.jump_if(Condition.NOT_EQUAL, "done")
        observer.label("upright")
        observer.raw(bytes.fromhex("b8 02 00 00 00"))
        observer.jump("done")
        observer.label("authored")
        observer.raw(bytes.fromhex("33 c0"))
        observer.label("done")
        observer.raw(bytes.fromhex("c9 c2 10 00"))
        tail = observer.build(maximum_size=self.section_size - self._observer)
        return (
            self._magic.ljust(self._code, b"\0")
            + code.ljust(self._observer - self._code, b"\0")
            + tail.ljust(self.section_size - self._observer, b"\0")
        )
