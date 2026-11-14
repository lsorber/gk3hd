"""Read the current protagonist through the engine's original model accessor."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.payload import SegmentPayloadBuilder
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
class VRProtagonistABI:
    """Read-only stdcall(snapshot*): one for a current finite anchor, zero otherwise.

    The caller supplies 32 bytes: size, scene, actor, model, XYZ and heading.
    Failed valid-sized records retain their size and clear every output field.
    A snapshot does not establish permission or a safe destination for movement.
    """

    query_va: int


@dataclass(frozen=True, slots=True, kw_only=True)
class VRProtagonistCompiler:
    """Resolve the scene's actual ego actor afresh, without moving any object.

    Original GetPosition evaluates the model's root transform. Rendered vertex
    positions and animated model fields are not substitutes for that anchor.
    Scene/actor/model changes during evaluation invalidate the whole snapshot.
    The caller owns its record and invokes this entry on the game thread.
    No game hook or persistent character pointer is installed by this compiler.
    """

    profile: BuildProfile

    section_name: ClassVar[str] = ".gk3eg"
    section_size: ClassVar[int] = 0x1000
    snapshot_size: ClassVar[int] = 32
    _magic: ClassVar[bytes] = b"GK3XRE01"
    _code: ClassVar[int] = 0x100
    _anchors: ClassVar[tuple[str, ...]] = (
        "vr.current_protagonist",
        "vr.protagonist_model",
        "vr.protagonist_position",
        "vr.protagonist_position_evaluator",
    )

    def _check(self, image: PEFile) -> None:
        check_native_scene_types(image, self.profile)
        for name in self._anchors:
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = f"VR protagonist dependency changed: {name}"
                raise PatchError(msg)

    def abi(self, image: PEFile) -> VRProtagonistABI:
        """Read a verified callable query, never a saved actor pointer."""
        section = image.get_section(self.section_name)
        if section is None or image.read_bytes(section.pointer_to_raw_data, 8) != self._magic:
            msg = "VR protagonist query is absent or incompatible"
            raise PatchError(msg)
        return VRProtagonistABI(image.rva_to_va(section.virtual_address) + self._code)

    def apply(self, image: PEFile) -> None:
        """Add an inert read-only query without replacing native code or hooks."""
        if image.get_section(self.section_name) is not None:
            msg = "VR protagonist query is already installed"
            raise PatchError(msg)
        self._check(image)
        section = image.add_section(self.section_name, bytes(self.section_size), 0x60000020)
        base = image.rva_to_va(section.virtual_address)
        image.write_bytes(section.pointer_to_raw_data, self._payload(base))

    def postcheck(self, image: PEFile) -> None:
        """Verify the native dependencies and complete callable bytes."""
        self._check(image)
        base = self.abi(image).query_va - self._code
        if image.read_bytes(image.va_to_offset(base), self.section_size) != self._payload(base):
            msg = "VR protagonist query failed verification"
            raise PatchError(msg)

    def _payload(self, base: int) -> bytes:
        e = X86Emitter(base_va=base + self._code)
        e.raw(bytes.fromhex("9c 60 8b 5c 24 28 85 db"))
        e.jump_if(Condition.EQUAL, "invalid")
        e.raw(bytes.fromhex("83 3b 20"))
        e.jump_if(Condition.NOT_EQUAL, "invalid")
        self._clear(e)
        e.raw(b"\xa1" + struct.pack("<I", self.profile.address("vr.room_global")))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "failed")
        emit_native_scene_guard(e, self.profile, register="eax", rejected="failed")
        e.raw(bytes.fromhex("89 43 04 8b 40 58 85 c0"))
        e.jump_if(Condition.EQUAL, "failed")
        e.raw(bytes.fromhex("89 43 08 8b 48 64 85 c9"))
        e.jump_if(Condition.EQUAL, "failed")
        e.raw(bytes.fromhex("89 4b 0c 8b 81 b0 00 00 00 85 c0"))
        e.jump_if(Condition.EQUAL, "failed")
        e.raw(bytes.fromhex("83 78 04 00"))
        e.jump_if(Condition.EQUAL, "failed")
        e.raw(bytes.fromhex("83 b9 b8 00 00 00 00"))
        e.jump_if(Condition.EQUAL, "failed")
        e.raw(bytes.fromhex("8d 43 1c 50 8d 43 10 50"))
        e.call_absolute(self.profile.site("vr.protagonist_position").va)
        self._validate(e)
        e.raw(bytes.fromhex("b8 01 00 00 00"))
        e.jump("done")
        e.label("failed")
        self._clear(e)
        e.label("invalid")
        e.raw(bytes.fromhex("31 c0"))
        e.label("done")
        e.raw(bytes.fromhex("89 44 24 1c 61 9d c2 04 00"))
        payload = SegmentPayloadBuilder(
            owner="vr_protagonist", segment=self.section_name, size=self.section_size
        )
        payload.place(label="query identity", offset=0, payload=self._magic)
        payload.place(
            label="native anchor query",
            offset=self._code,
            payload=e.build(maximum_size=self.section_size - self._code),
        )
        return payload.build()

    @staticmethod
    def _clear(e: X86Emitter) -> None:
        e.raw(bytes.fromhex("fc 8d 7b 04 31 c0 b9 07 00 00 00 f3 ab"))

    def _validate(self, e: X86Emitter) -> None:
        e.raw(b"\xa1" + struct.pack("<I", self.profile.address("vr.room_global")))
        e.raw(bytes.fromhex("3b 43 04"))
        e.jump_if(Condition.NOT_EQUAL, "failed")
        for instruction in ("8b 40 58 3b 43 08", "8b 40 64 3b 43 0c"):
            e.raw(bytes.fromhex(instruction))
            e.jump_if(Condition.NOT_EQUAL, "failed")
        for offset in (16, 20, 24, 28):
            e.raw(bytes((0x8B, 0x43, offset)))
            e.raw(bytes.fromhex("25 ff ff ff 7f 3d 00 00 80 7f"))
            e.jump_if(Condition.ABOVE_OR_EQUAL, "failed")
