"""Preserve the reference presentation size of full-screen Bink movies."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.layout import MOVIE_SEGMENT, install_runtime_segment
from gk3hd.patch.definitions.runtime2d.system.shared import SystemCompilerContext

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile


@dataclass(frozen=True, slots=True, kw_only=True)
class MovieFeatureCompiler(SystemCompilerContext):
    """Supply a fitted reference extent before native layout builds its borders.

    Bink's software path doubles small movies when they fit the physical screen.
    Consequently a 320x240 intro stays 640x480 even at 4K. Use the doubling that
    fits 1024x768, then scale that extent uniformly with the fitted reference
    canvas. Native layout still owns centering, child borders and invalidation.
    Embedded movies, custom sizing modes, hardware overlays and original display
    modes are untouched. No decoder, audio, frame timing or global is modified.
    """

    def build_layout(self, *, wrapper_va: int) -> bytes:
        """Build an idempotent, call-local extent adapter for MovieLayer."""
        code = X86Emitter(base_va=wrapper_va)
        code.raw(bytes.fromhex("9c60 83ec10 89ce"))
        code.raw(bytes.fromhex("80be4001000000"))  # MovieLayer.fullscreen
        code.jump_if(Condition.EQUAL, "native")
        code.raw(bytes.fromhex("8bbe3c010000 85ff"))
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\x81\x3f" + struct.pack("<I", self.profile.address("movies.bink_vtable")))
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.raw(bytes.fromhex("807f5000"))  # native hardware overlay
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.raw(bytes.fromhex("837f6400"))  # default movie sizing only
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.raw(b"\x8b\x0d" + struct.pack("<I", self._physical_width_va))
        code.raw(b"\x8b\x15" + struct.pack("<I", self._physical_width_va + 4))
        for register in (b"\x81\xf9", b"\x81\xfa"):
            code.raw(register + struct.pack("<I", 32768))
            code.jump_if(Condition.ABOVE, "native")
        code.raw(bytes.fromhex("85c9"))
        code.jump_if(Condition.LESS_OR_EQUAL, "native")
        code.raw(bytes.fromhex("85d2"))
        code.jump_if(Condition.LESS_OR_EQUAL, "native")
        code.raw(b"\x81\xf9" + struct.pack("<I", 1024))
        code.jump_if(Condition.ABOVE, "scaled")
        code.raw(b"\x81\xfa" + struct.pack("<I", 768))
        code.jump_if(Condition.BELOW_OR_EQUAL, "native")
        code.label("scaled")
        code.raw(bytes.fromhex("8b4754 85c0"))  # raw BINK dimensions, never the prior RECT
        code.jump_if(Condition.EQUAL, "native")
        code.raw(bytes.fromhex("8b18 8b6804"))
        for register, bound in ((b"\x81\xfb", 1024), (b"\x81\xfd", 768)):
            code.raw(register + struct.pack("<I", bound))
            code.jump_if(Condition.ABOVE, "native")
        for instruction in ("85db", "85ed"):
            code.raw(bytes.fromhex(instruction))
            code.jump_if(Condition.LESS_OR_EQUAL, "native")
        code.raw(b"\x81\xfb" + struct.pack("<I", 512))
        code.jump_if(Condition.ABOVE, "fit")
        code.raw(b"\x81\xfd" + struct.pack("<I", 384))
        code.jump_if(Condition.ABOVE, "fit")
        code.raw(bytes.fromhex("d1e3 d1e5"))
        code.label("fit")
        code.raw(bytes.fromhex("69c100030000 69f200040000 39f0"))
        code.jump_if(Condition.BELOW_OR_EQUAL, "width")
        code.raw(bytes.fromhex("89d6 b900030000"))  # height / 768
        code.jump("extent")
        code.label("width")
        code.raw(bytes.fromhex("89ce b900040000"))  # width / 1024
        code.label("extent")
        code.raw(bytes.fromhex("31c0 890424 89442404"))
        for source, destination in (("89d8", 8), ("89e8", 12)):
            code.raw(bytes.fromhex(source + " 0fafc6 89ca d1ea 01d0 31d2 f7f1"))
            code.raw(bytes((0x89, 0x44, 0x24, destination)))
        code.raw(bytes.fromhex("89e0 50 89f9"))
        code.call_absolute(self.profile.address("movies.set_rect"))
        code.label("native")
        code.raw(bytes.fromhex("83c410 619d"))
        code.jump_absolute(self.profile.address("movies.layout"))
        return code.build()

    def apply(self, image: PEFile) -> None:
        """Install both native layout entry callers as one checked transaction."""
        section = install_runtime_segment(image, MOVIE_SEGMENT)
        base = image.rva_to_va(section.virtual_address)
        payload = SegmentPayloadBuilder(
            owner=self.id, segment=MOVIE_SEGMENT.logical_name, size=MOVIE_SEGMENT.size
        )
        payload.place(label="identity", offset=0, payload=MOVIE_SEGMENT.magic)
        payload.place(
            label="movie extent", offset=0x100, payload=self.build_layout(wrapper_va=base + 0x100)
        )
        plan = ExecutableMutationPlan(owner=self.id)
        for name in ("initial_layout", "resize_layout"):
            site = self.profile.site(f"movies.{name}")
            plan.branch(
                label=f"movie {name}",
                opcode=BranchOpcode.CALL,
                site_va=site.va,
                expected=site.original,
                target_va=base + 0x100,
            )
        image.write_bytes(section.pointer_to_raw_data, payload.build())
        plan.apply(image)
