"""Keep software-alpha scratch surfaces in the pixel format the engine writes."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.layout import SURFACE_FORMAT_SEGMENT, install_runtime_segment
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile


def build_scratch_format_request(
    *, entry_va: int, scratch_return_va: int, continuation_va: int
) -> bytes:
    """Request RGB565 only for the format-3 software-alpha pool allocator.

    Its native callback writes 16-bit pixels, but the implicit CreateSurface
    format can follow a 32-bit Wine desktop. Fill the real creation descriptor;
    do not falsify Lock results or alter primary, texture or display formats.
    This type-switch arm owns format 3. Other callers retain its native behavior.
    """
    code = X86Emitter(base_va=entry_va)
    code.raw(b"\x9c")  # Preserve native flags and every register.
    code.raw(b"\x81\x7d\x04" + struct.pack("<I", scratch_return_va))
    code.jump_if(Condition.NOT_EQUAL, "native")
    # Stack-local DDSURFACEDESC: dwFlags at EBP-0x74, DDPIXELFORMAT at -0x30.
    code.raw(bytes.fromhex("81 4d 8c 00 10 00 00"))  # DDSD_PIXELFORMAT
    for displacement, value in (
        (-0x30, 32),  # DDPIXELFORMAT size
        (-0x2C, 0x40),  # DDPF_RGB
        (-0x28, 0),  # No FourCC
        (-0x24, 16),
        (-0x20, 0xF800),
        (-0x1C, 0x07E0),
        (-0x18, 0x001F),
        (-0x14, 0),  # No alpha mask
    ):
        code.raw(bytes((0xC7, 0x45, displacement & 0xFF)) + struct.pack("<I", value))
    code.label("native")
    code.raw(b"\x9d")
    code.jump_absolute(continuation_va)
    return code.build()


@dataclass(frozen=True, slots=True, kw_only=True)
class SurfaceFormatCompiler:
    """Preserve native RGB565 alpha arithmetic independently of desktop depth."""

    profile: BuildProfile
    id: ClassVar[str] = "runtime2d.surface_formats"
    _entry_offset: ClassVar[int] = 0x100

    def precheck(self, image: PEFile) -> None:
        """Validate the switch arm and its one scoped factory caller."""
        for name in ("bitmap.rgb565_creation_case", "bitmap.alpha_scratch_creation"):
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                detail = f"{self.id} requires pristine {name}"
                raise PatchError(detail)

    def apply(self, image: PEFile) -> None:
        """Build an explicit descriptor request without replacing the allocator."""
        section = install_runtime_segment(image, SURFACE_FORMAT_SEGMENT)
        entry = image.rva_to_va(section.virtual_address) + self._entry_offset
        caller = self.profile.site("bitmap.alpha_scratch_creation")
        payload = SegmentPayloadBuilder(
            owner=self.id,
            segment=SURFACE_FORMAT_SEGMENT.logical_name,
            size=SURFACE_FORMAT_SEGMENT.size,
        )
        payload.place(label="magic", offset=0, payload=SURFACE_FORMAT_SEGMENT.magic)
        payload.place(
            label="RGB565 scratch request",
            offset=self._entry_offset,
            payload=build_scratch_format_request(
                entry_va=entry,
                scratch_return_va=caller.va + len(caller.original),
                continuation_va=self.profile.address("bitmap.creation_descriptor_ready"),
            ),
        )
        image.write_bytes(section.pointer_to_raw_data, payload.build())
        site = self.profile.site("bitmap.rgb565_creation_case")
        mutations = ExecutableMutationPlan(owner=self.id)
        mutations.pointer(
            label=site.symbol,
            slot_va=site.va,
            expected=site.original,
            target_va=entry,
        )
        mutations.apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Delegate full payload and redirect verification to Runtime2D."""
        if image.get_section(SURFACE_FORMAT_SEGMENT.logical_name) is None:
            detail = f"{self.id} payload is missing"
            raise PatchError(detail)
