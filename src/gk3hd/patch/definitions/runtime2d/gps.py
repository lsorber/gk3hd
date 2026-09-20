"""Fit the GPS overlay without changing its world-coordinate calibration."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.layout import (
    GPS_SEGMENT,
    GPS_TRANSFER_OFFSET,
    install_runtime_segment,
)
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile

OWNER_OFFSET = 0x10
DEPTH_OFFSET = 0x14
RECT_OFFSET = 0x20
MEMBER_OFFSET = 0x200
MEMBER_FIELDS = (0xDC, 0x124, 0x16C, 0x1B4, 0x1FC, 0x2AC, 0x304)
AUXILIARY_FIELD = 0x3AC
DRAW_SITES = ("gps.bitmap_draw", "gps.button_draw", "gps.text_draw", "gps.auxiliary_draw")
# Move and release delegate to these virtual predicates: mapping those outer
# callbacks as well would inverse-map the same point twice. Down calls the
# native pixel predicate directly and therefore needs its own adapter.
INPUT_SITES = (
    "gps.button_down",
    "gps.button_bounds",
    "gps.button_pixels",
    "gps.auxiliary_bounds",
)


def build_member(*, wrapper_va: int, owner_va: int) -> bytes:
    """Return carry only for ECX's exact active GPS member; preserve registers."""
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x50\x52\x85\xc9")
    code.jump_if(Condition.EQUAL, "no")
    code.raw(b"\xa1" + struct.pack("<I", owner_va) + b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "no")
    for offset in MEMBER_FIELDS:
        code.raw(b"\x8d\x90" + struct.pack("<I", offset) + b"\x39\xd1")
        code.jump_if(Condition.EQUAL, "yes")
    code.raw(b"\x3b\x88" + struct.pack("<I", AUXILIARY_FIELD))
    code.jump_if(Condition.EQUAL, "yes")
    code.label("no")
    code.raw(b"\x5a\x58\xf8\xc3")
    code.label("yes")
    code.raw(b"\x5a\x58\xf9\xc3")
    return code.build()


def build_draw(*, wrapper_va: int, member_va: int, depth_va: int, native_va: int) -> bytes:
    """Scope each separately registered GPS sibling through its native Draw."""
    code = X86Emitter(base_va=wrapper_va)
    code.call_absolute(member_va)
    code.jump_if(Condition.ABOVE_OR_EQUAL, "native")
    code.raw(b"\xff\x05" + struct.pack("<I", depth_va))
    code.raw(b"\xff\x74\x24\x08\xff\x74\x24\x08")
    code.call_absolute(native_va)
    code.raw(b"\xff\x0d" + struct.pack("<I", depth_va) + b"\xc2\x08\x00")
    code.label("native")
    code.jump_absolute(native_va)
    return code.build()


def _floor_divide(code: X86Emitter, label: str) -> None:
    """Divide signed EDX:EAX by positive EBX with floor, not truncation."""
    code.raw(b"\xf7\xfb\x85\xd2")
    code.jump_if(Condition.GREATER_OR_EQUAL, label)
    code.raw(b"\x48")
    code.label(label)


def build_input(*, wrapper_va: int, member_va: int, height_va: int, native_va: int) -> bytes:
    """Pass a private inverse POINT to one native consumer, including edge pixels."""
    code = X86Emitter(base_va=wrapper_va)
    code.call_absolute(member_va)
    code.jump_if(Condition.ABOVE_OR_EQUAL, "native")
    code.raw(b"\x81\x3d" + struct.pack("<I", height_va) + struct.pack("<I", 768))
    code.jump_if(Condition.LESS_OR_EQUAL, "native")
    code.raw(b"\x83\x7c\x24\x04\x00")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x55\x8b\xec\x83\xec\x08\x53\x56\x57\x8b\xf9\x8b\x75\x08")
    for offset in (0, 4):
        # Inverse of floor(edge * H / 768): ceil((pixel+1)*768/H)-1.
        # Full signed products also handle negative points without overflow.
        code.raw(b"\x8b\x46" + bytes([offset]) + b"\xbb\x00\x03\x00\x00\xf7\xeb")
        code.raw(b"\x05\xff\x02\x00\x00\x83\xd2\x00\x8b\x1d" + struct.pack("<I", height_va))
        _floor_divide(code, f"point_{offset}")
        code.raw(b"\x89\x45" + bytes([0xF8 + offset]))
    code.raw(b"\x8d\x45\xf8\x50\x8b\xcf")
    code.call_absolute(native_va)
    code.raw(b"\x5f\x5e\x5b\xc9\xc2\x04\x00")
    code.label("native")
    code.jump_absolute(native_va)
    return code.build()


def build_transfer(*, wrapper_va: int, depth_va: int, dimensions_va: int, rect_va: int) -> bytes:
    """Transform the shared dispatcher's PUSHAD frame; EAX reports ownership.

    ECX points to that frame, not to a guessed caller stack. Preserve all other
    registers, both caller rectangles, source density, and non-display transfers.
    This is a helper of the one final-blit dispatcher, never another sink hook.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x60\x8b\xf9\x83\x3d" + struct.pack("<I", depth_va) + b"\x00")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x8b\x4f\x18\x85\xc9")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\xa1" + struct.pack("<I", dimensions_va) + b"\x39\x41\x38")
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(b"\xa1" + struct.pack("<I", dimensions_va + 4) + b"\x39\x41\x3c")
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(b"\x3d\x00\x03\x00\x00")
    code.jump_if(Condition.LESS_OR_EQUAL, "native")
    code.raw(b"\x8b\x77\x28\x85\xf6")
    code.jump_if(Condition.EQUAL, "native")
    for offset in (0, 4, 8, 12):
        code.raw(b"\x8b\x46" + bytes([offset]) + b"\xf7\x2d" + struct.pack("<I", dimensions_va + 4))
        code.raw(b"\xbb\x00\x03\x00\x00")
        _floor_divide(code, f"edge_{offset}")
        code.raw(b"\xa3" + struct.pack("<I", rect_va + offset))
    code.raw(b"\xc7\x47\x28" + struct.pack("<I", rect_va))
    code.raw(b"\xc7\x44\x24\x1c\x01\x00\x00\x00\x61\xc3")
    code.label("native")
    code.raw(b"\xc7\x44\x24\x1c\x00\x00\x00\x00\x61\xc3")
    return code.build()


@dataclass(frozen=True, slots=True, kw_only=True)
class GPSFeatureCompiler:
    """Own GPS lifecycle, sibling Draw scopes, and point-consuming callbacks."""

    profile: BuildProfile
    id: ClassVar[str] = "runtime2d.gps"

    def precheck(self, image: PEFile) -> None:
        """Require the exact native sites before installing shared-class adapters."""
        for name in ("gps.show", "gps.destroy", *DRAW_SITES, *INPUT_SITES):
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = f"{self.id} requires pristine {name}"
                raise PatchError(msg)

    def build(self, base: int) -> tuple[bytes, ExecutableMutationPlan]:
        """Build bounded payload and exact redirects for the shared runtime owner."""
        payload = SegmentPayloadBuilder(owner=self.id, segment="gps", size=GPS_SEGMENT.size)
        payload.place(label="identity", offset=0, payload=GPS_SEGMENT.magic)
        payload.reserve(label="owner and draw depth", offset=OWNER_OFFSET, size=8)
        payload.reserve(label="display rectangle", offset=RECT_OFFSET, size=16)
        mutations = ExecutableMutationPlan(owner=self.id)
        owner = base + OWNER_OFFSET
        for name, offset in (("gps.show", 0x100), ("gps.destroy", 0x140)):
            site = self.profile.site(name)
            code = X86Emitter(base_va=base + offset)
            if name == "gps.show":
                code.raw(b"\x89\x0d" + struct.pack("<I", owner))
            else:
                code.raw(b"\x39\x0d" + struct.pack("<I", owner))
                code.jump_if(Condition.NOT_EQUAL, "resume")
                code.raw(b"\xc7\x05" + struct.pack("<I", owner) + bytes(4))
                code.label("resume")
            code.raw(site.original)
            code.jump_absolute(site.va + len(site.original))
            payload.place(label=name, offset=offset, payload=code.build(), limit=offset + 0x40)
            mutations.branch(
                label=name,
                opcode=BranchOpcode.JUMP,
                site_va=site.va,
                expected=site.original,
                target_va=base + offset,
            )
        payload.place(
            label="member identity",
            offset=MEMBER_OFFSET,
            payload=build_member(wrapper_va=base + MEMBER_OFFSET, owner_va=owner),
            limit=0x400,
        )
        for index, name in enumerate((*DRAW_SITES, *INPUT_SITES)):
            offset = 0x400 + index * 0x100
            site = self.profile.site(name)
            native = int.from_bytes(site.original, "little")
            if name in DRAW_SITES:
                data = build_draw(
                    wrapper_va=base + offset,
                    member_va=base + MEMBER_OFFSET,
                    depth_va=base + DEPTH_OFFSET,
                    native_va=native,
                )
            else:
                data = build_input(
                    wrapper_va=base + offset,
                    member_va=base + MEMBER_OFFSET,
                    height_va=self.profile.address("display.dimensions") + 4,
                    native_va=native,
                )
            payload.place(label=name, offset=offset, payload=data, limit=offset + 0x100)
            mutations.pointer(
                label=name, slot_va=site.va, expected=site.original, target_va=base + offset
            )
        payload.place(
            label="display transfer",
            offset=GPS_TRANSFER_OFFSET,
            payload=build_transfer(
                wrapper_va=base + GPS_TRANSFER_OFFSET,
                depth_va=base + DEPTH_OFFSET,
                dimensions_va=self.profile.address("display.dimensions"),
                rect_va=base + RECT_OFFSET,
            ),
            limit=GPS_SEGMENT.size,
        )
        return payload.build(), mutations

    def apply(self, image: PEFile) -> None:
        """Install one owned segment and its checked native redirects."""
        section = install_runtime_segment(image, GPS_SEGMENT)
        payload, mutations = self.build(image.rva_to_va(section.virtual_address))
        image.write_bytes(section.pointer_to_raw_data, payload)
        mutations.apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Verify every generated byte and redirect, including owner isolation."""
        section = image.get_section(GPS_SEGMENT.logical_name)
        if section is None:
            msg = "GPS runtime segment is missing"
            raise PatchError(msg)
        payload, mutations = self.build(image.rva_to_va(section.virtual_address))
        if image.read_bytes(section.pointer_to_raw_data, len(payload)) != payload:
            msg = "GPS runtime payload differs from its compiler"
            raise PatchError(msg)
        mutations.verify(image)
