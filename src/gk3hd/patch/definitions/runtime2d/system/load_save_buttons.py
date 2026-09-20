"""Keep Load/Save button state geometry and opacity input in the same space."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter, encode_rel32_branch
from gk3hd.patch.definitions.runtime2d.layout import (
    LOAD_SAVE_BUTTON_INITIAL_BOUNDS_OFFSET,
    LOAD_SAVE_BUTTON_SEGMENT,
    LOAD_SAVE_SEGMENT,
    install_runtime_segment,
)
from gk3hd.patch.definitions.runtime2d.system.shared import SystemCompilerContext

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile

_SET_RECT = 0x100
_PIXEL_HIT = 0x300
_NATIVE_HIT = 0xC00


@dataclass(frozen=True, slots=True, kw_only=True)
class LoadSaveButtonCompiler(SystemCompilerContext):
    """Adapt only the two embedded buttons of the currently fitted Load/Save root."""

    def apply(self, image: PEFile) -> None:
        """Install bounded helpers and byte-checked native entry redirects."""
        section = install_runtime_segment(image, LOAD_SAVE_BUTTON_SEGMENT)
        base = image.rva_to_va(section.virtual_address)
        root = self.symbols.va(LOAD_SAVE_SEGMENT.logical_name, self._off_loadsave_layout_root)
        transform = self.symbols.va(
            LOAD_SAVE_SEGMENT.logical_name, self._off_loadsave_rect_transform
        )
        hit = self.profile.site("bitmap.pixel_hit_entry")
        rect = self.profile.site("bitmap.set_image_rect")
        payload = SegmentPayloadBuilder(
            owner=self.id,
            segment=LOAD_SAVE_BUTTON_SEGMENT.logical_name,
            size=LOAD_SAVE_BUTTON_SEGMENT.size,
        )
        payload.place(label="identity", offset=0, payload=LOAD_SAVE_BUTTON_SEGMENT.magic)
        for offset, limit, label, code in (
            (
                _SET_RECT,
                _PIXEL_HIT,
                "state bounds",
                self.build_set_rect(
                    wrapper_va=base + _SET_RECT,
                    layout_root_va=root,
                ),
            ),
            (
                _PIXEL_HIT,
                LOAD_SAVE_BUTTON_INITIAL_BOUNDS_OFFSET,
                "opacity coordinates",
                self.build_pixel_hit(
                    wrapper_va=base + _PIXEL_HIT, layout_root_va=root, native_va=base + _NATIVE_HIT
                ),
            ),
            (
                LOAD_SAVE_BUTTON_INITIAL_BOUNDS_OFFSET,
                _NATIVE_HIT,
                "initial bounds",
                self.build_initial_bounds(
                    wrapper_va=base + LOAD_SAVE_BUTTON_INITIAL_BOUNDS_OFFSET, transform_va=transform
                ),
            ),
            (
                _NATIVE_HIT,
                LOAD_SAVE_BUTTON_SEGMENT.size,
                "pristine hit trampoline",
                hit.original
                + encode_rel32_branch(
                    opcode=BranchOpcode.JUMP,
                    site_va=base + _NATIVE_HIT + len(hit.original),
                    target_va=hit.va + len(hit.original),
                ),
            ),
        ):
            payload.place(label=label, offset=offset, payload=code, limit=limit)
        image.write_bytes(section.pointer_to_raw_data, payload.build())
        mutations = ExecutableMutationPlan(owner=self.id)
        mutations.branch(
            label="Load/Save state bounds",
            opcode=BranchOpcode.CALL,
            site_va=rect.va,
            expected=rect.original,
            target_va=base + _SET_RECT,
            size=len(rect.original),
        )
        mutations.branch(
            label="Load/Save opacity input",
            opcode=BranchOpcode.JUMP,
            site_va=hit.va,
            expected=hit.original,
            target_va=base + _PIXEL_HIT,
        )
        mutations.apply(image)

    def _owned(self, code: X86Emitter, layout_root_va: int) -> None:
        # Do not dereference an inferred parent. Match against the lifecycle-
        # cleared root publication first, then validate its concrete class.
        code.raw(b"\x8b\x15" + struct.pack("<I", layout_root_va) + b"\x85\xd2")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\x8d\x82\x40\x01\x00\x00\x3b\xc1")
        code.jump_if(Condition.EQUAL, "root_class")
        code.raw(b"\x8d\x82\xdc\x01\x00\x00\x3b\xc1")
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.label("root_class")
        code.raw(b"\x81\x3a" + struct.pack("<I", self.profile.address("loadgame.vtable")))
        code.jump_if(Condition.EQUAL, "owned")
        code.raw(b"\x81\x3a" + struct.pack("<I", self.profile.address("savegame.vtable")))
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.label("owned")
        code.raw(b"\x83\x3d" + struct.pack("<I", self._physical_width_va + 4) + b"\x00")
        code.jump_if(Condition.LESS_OR_EQUAL, "native")

    def _fit_extents(self, code: X86Emitter) -> None:
        # ECX is a RECT with a physical origin and still-logical extents.
        # Fit extents, not individual edges: this agrees with bitmap drawing
        # and avoids a one-pixel initial-versus-hover width discontinuity.
        for near, far in ((0, 8), (4, 12)):
            code.raw(b"\x8b\x41" + bytes([far]) + b"\x2b\x41" + bytes([near]))
            code.raw(b"\x0f\xaf\x05" + struct.pack("<I", self._physical_width_va + 4))
            code.raw(b"\x99\xbb\x00\x03\x00\x00\xf7\xfb")
            code.raw(b"\x03\x41" + bytes([near]) + b"\x89\x41" + bytes([far]))

    def build_set_rect(self, *, wrapper_va: int, layout_root_va: int) -> bytes:
        """Wrap SetImage's virtual SetRect without modifying its caller-owned RECT."""
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x55\x8b\xec\x83\xec\x10\x60")
        self._owned(code, layout_root_va)
        code.raw(b"\x8b\x75\x08\x8d\x7d\xf0\xb9\x04\x00\x00\x00\xf3\xa5")
        code.raw(b"\x8d\x4d\xf0")
        self._fit_extents(code)
        code.raw(b"\x61\x8d\x55\xf0\x52\xff\x90\xa8\x00\x00\x00\xc9\xc2\x04\x00")
        code.label("native")
        code.raw(b"\x61\xff\x75\x08\xff\x90\xa8\x00\x00\x00\xc9\xc2\x04\x00")
        return code.build()

    def build_initial_bounds(self, *, wrapper_va: int, transform_va: int) -> bytes:
        """Fit initial placement with exactly the same extents as later states."""
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x60\x8b\x71\x08\x2b\x31\x8b\x79\x0c\x2b\x79\x04")
        code.call_absolute(transform_va)  # Native rectangle transform preserves registers.
        code.raw(b"\x03\x31\x89\x71\x08\x03\x79\x04\x89\x79\x0c")
        self._fit_extents(code)
        code.raw(b"\x61\xc3")
        return code.build()

    def build_pixel_hit(self, *, wrapper_va: int, layout_root_va: int, native_va: int) -> bytes:
        """Map physical input to exact native pixel centres in the selected source."""
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x55\x8b\xec\x83\xec\x08\x60")
        self._owned(code, layout_root_va)
        code.raw(b"\x8b\xf9\x8b\x75\x08\x85\xf6")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\x8b\x1d" + struct.pack("<I", self.profile.address("bitmap.manager")))
        code.raw(b"\x85\xdb")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\x0f\xb7\x45\x0c\x3b\x83\x24\x01\x00\x00")
        code.jump_if(Condition.ABOVE_OR_EQUAL, "native")
        code.raw(b"\x8b\x9b\x20\x01\x00\x00\x85\xdb")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\x8b\x04\x83\x85\xc0")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\x8b\x40\x30\x85\xc0")
        code.jump_if(Condition.EQUAL, "native")
        # Exact expected geometry, scoped by owner; unrelated larger bitmaps
        # must never acquire a density interpretation from width alone.
        code.raw(b"\x8b\x48\x38\x8b\x58\x3c\x8d\x82\x40\x01\x00\x00\x3b\xc7")
        code.jump_if(Condition.NOT_EQUAL, "primary")
        for width, height, label in ((58, 26, "native_size"), (232, 104, "dense")):
            code.raw(b"\x81\xf9" + struct.pack("<I", width))
            code.jump_if(Condition.NOT_EQUAL, f"next_{width}")
            code.raw(b"\x81\xfb" + struct.pack("<I", height))
            code.jump_if(Condition.EQUAL, label)
            code.label(f"next_{width}")
        code.jump("native")
        code.label("primary")
        for width, heights, label in ((145, (38, 39), "native_size"), (580, (152, 156), "dense")):
            code.raw(b"\x81\xf9" + struct.pack("<I", width))
            code.jump_if(Condition.NOT_EQUAL, f"next_{width}")
            for height in heights:
                code.raw(b"\x81\xfb" + struct.pack("<I", height))
                code.jump_if(Condition.EQUAL, label)
            code.label(f"next_{width}")
        code.jump("native")
        code.label("native_size")
        code.raw(b"\xbb\x01\x00\x00\x00")
        code.jump("scale_ready")
        code.label("dense")
        code.raw(b"\xbb\x04\x00\x00\x00")
        code.label("scale_ready")
        for axis, local in ((0, 0xF8), (4, 0xFC)):
            code.raw(b"\x8b\x46" + bytes([axis]) + b"\x3b\x47" + bytes([0x1C + axis]))
            code.jump_if(Condition.LESS, "outside")
            code.raw(b"\x3b\x47" + bytes([0x24 + axis]))
            code.jump_if(Condition.GREATER_OR_EQUAL, "outside")
            code.raw(b"\x2b\x47" + bytes([0x1C + axis]) + b"\x69\xc0\x00\x03\x00\x00\x99")
            code.raw(b"\xf7\x3d" + struct.pack("<I", self._physical_width_va + 4))
            code.raw(b"\x83\xfb\x04")
            code.jump_if(Condition.NOT_EQUAL, f"point_{axis}")
            # Quantize to a native pixel *before* density conversion: 4i+2 is
            # the source-preserving sample, including at the last visible pixel.
            code.raw(b"\xc1\xe0\x02\x83\xc0\x02")
            code.label(f"point_{axis}")
            code.raw(b"\x03\x47" + bytes([0x1C + axis]) + b"\x89\x45" + bytes([local]))
        code.raw(b"\x61\xff\x75\x0c\x8d\x45\xf8\x50")
        code.call_absolute(native_va)
        code.raw(b"\xc9\xc2\x08\x00")
        code.label("outside")
        code.raw(b"\x61\x31\xc0\xc9\xc2\x08\x00")
        code.label("native")
        code.raw(b"\x61\xc9")
        code.jump_absolute(native_va)
        return code.build()
