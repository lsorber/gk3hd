"""Own Le Serpent Rouge's page layout and reference-canvas lifecycle."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter, encode_rel32_branch
from gk3hd.patch.definitions.runtime2d.layout import (
    SYSTEM_CONTROL_SEGMENT,
    SYSTEM_SEGMENT,
    ZODIAC_SEGMENT,
    install_runtime_segment,
)
from gk3hd.patch.definitions.runtime2d.system.fixed_screens import FixedScreenFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.shared import SystemCompilerContext

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile

_DRAW = 0x100
_SHOW = 0x300
_HIDE = 0x380
_DESTRUCTOR = 0x400
_WIDTH = 0x500
_HEIGHT = 0x580
_EXIT_HEIGHT = 0x600
_BACKDROP = 0x680


@dataclass(frozen=True, slots=True, kw_only=True)
class ZodiacFeatureCompiler(SystemCompilerContext):
    """Keep page art, overlays and Exit in one authored coordinate domain.

    Native LSR centres its art and bottom-anchors Exit using physical display
    dimensions, but its background and status remain on a reference canvas.
    Normalize only those local dimension reads; never mutate the framebuffer
    globals. The concrete LSR root then owns drawing and inverse pointer input,
    independent of the inventory screen retained underneath it.
    """

    def build_dimension(self, *, wrapper_va: int, height: bool, output_ecx: bool = False) -> bytes:
        """Return a local reference extent, preserving flags and other registers.

        Original modes keep their native layout. Any larger output uses the
        complete 1024x768 canvas before the shared fitted presentation affine.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x9c")
        for offset, limit in ((0, 1024), (4, 768)):
            code.raw(b"\x81\x3d" + struct.pack("<II", self._physical_width_va + offset, limit))
            code.jump_short_if(Condition.ABOVE, "reference")
        address = self._physical_width_va + (4 if height else 0)
        code.raw((b"\x8b\x0d" if output_ecx else b"\xa1") + struct.pack("<I", address))
        code.jump_short("done")
        code.label("reference")
        code.raw((b"\xb9" if output_ecx else b"\xb8") + struct.pack("<I", 768 if height else 1024))
        code.label("done")
        code.raw(b"\x9d\xc3")
        return code.build()

    def apply(self, image: PEFile) -> None:
        """Install bounded, exact-class LSR hooks and local layout helpers."""
        section = install_runtime_segment(image, ZODIAC_SEGMENT)
        base = image.rva_to_va(section.virtual_address)
        system = self.symbols.va(SYSTEM_SEGMENT.logical_name)
        control = self.symbols.va(SYSTEM_CONTROL_SEGMENT.logical_name)
        payload = SegmentPayloadBuilder(
            owner=self.id, segment=ZODIAC_SEGMENT.logical_name, size=ZODIAC_SEGMENT.size
        )
        payload.place(label="identity", offset=0, payload=ZODIAC_SEGMENT.magic)
        fixed = FixedScreenFeatureCompiler(
            symbols=self.symbols,
            profile=self.profile,
            room_rendering_abi=self.room_rendering_abi,
            transition_abi=self.transition_abi,
        )
        draw = fixed.build_root_draw_wrapper(
            wrapper_va=base + _DRAW,
            render_depth_va=system + self._off_render_depth,
            input_active_va=system + self._off_input_active,
            clear_pending_va=system + self._off_clear_pending,
            root_ptr_va=system + self._off_root_ptr,
            transform_mode_va=system + self._off_transform_mode,
            transform_mode=self._mode_reference_canvas_all,
            input_enabled=True,
            target_va=self.profile.address("zodiac.draw"),
            full_damage_region_va=control + self._off_control_full_damage_region,
            full_damage_rect_va=control + self._off_control_full_damage_rect,
            pre_draw_va=base + _BACKDROP,
        )
        payload.place(label="LSR draw", offset=_DRAW, payload=draw, limit=_SHOW)
        # SolidColor draws through a native fill, not the bitmap affine. Its
        # concrete embedded backdrop therefore owns physical framebuffer
        # bounds. Page images and hit-test controls stay entirely logical.
        backdrop = X86Emitter(base_va=base + _BACKDROP)
        backdrop.raw(b"\x31\xc0\x89\x81\x60\x01\x00\x00\x89\x81\x64\x01\x00\x00")
        for source, destination in ((0, 0x168), (4, 0x16C)):
            backdrop.raw(b"\xa1" + struct.pack("<I", self._physical_width_va + source))
            backdrop.raw(b"\x89\x81" + struct.pack("<I", destination))
        backdrop.raw(b"\xc3")
        payload.place(
            label="LSR physical backdrop", offset=_BACKDROP, payload=backdrop.build(), limit=0x700
        )
        plan = ExecutableMutationPlan(owner=self.id)
        for edge, offset, limit, slot, value in (
            ("show", _SHOW, _HIDE, 0xD8, 1),
            ("hide", _HIDE, _DESTRUCTOR, 0xDC, 0),
        ):
            code = fixed.build_state_wrapper(
                wrapper_va=base + offset,
                state_va=system + self._off_input_active,
                value=value,
                target_va=self.profile.address(f"ui.{edge}"),
                root_ptr_va=system + self._off_root_ptr,
                transform_mode_va=system + self._off_transform_mode,
                transform_mode=self._mode_reference_canvas_all,
            )
            payload.place(label=f"LSR {edge}", offset=offset, payload=code, limit=limit)
            plan.pointer(
                label=f"LSR {edge}",
                slot_va=self.profile.address("zodiac.vtable") + slot,
                expected=self.profile.address(f"ui.{edge}"),
                target_va=base + offset,
            )
        destructor = fixed.build_destructor_wrapper(
            wrapper_va=base + _DESTRUCTOR,
            render_depth_va=system + self._off_render_depth,
            input_active_va=system + self._off_input_active,
            clear_pending_va=system + self._off_clear_pending,
            root_ptr_va=system + self._off_root_ptr,
            transform_mode_va=system + self._off_transform_mode,
            publication_owner_va=system + self._off_root_ptr,
            target_va=self.profile.address("zodiac.destructor"),
        )
        payload.place(label="LSR destructor", offset=_DESTRUCTOR, payload=destructor, limit=_WIDTH)
        for edge, slot, offset in (("draw", 0xA0, _DRAW), ("destructor", 0, _DESTRUCTOR)):
            plan.pointer(
                label=f"LSR {edge}",
                slot_va=self.profile.address("zodiac.vtable") + slot,
                expected=self.profile.address(f"zodiac.{edge}"),
                target_va=base + offset,
            )
        for offset, height, ecx in (
            (_WIDTH, False, False),
            (_HEIGHT, True, False),
            (_EXIT_HEIGHT, True, True),
        ):
            code = self.build_dimension(wrapper_va=base + offset, height=height, output_ecx=ecx)
            payload.place(
                label=f"LSR extent {offset:x}", offset=offset, payload=code, limit=offset + 0x80
            )
        for name, offset in (
            ("constructor_width", _WIDTH),
            ("constructor_height", _HEIGHT),
            ("layout_width", _WIDTH),
            ("layout_height", _HEIGHT),
            ("exit_height", _EXIT_HEIGHT),
        ):
            site = self.profile.site(f"zodiac.{name}")
            replacement = encode_rel32_branch(
                opcode=BranchOpcode.CALL, site_va=site.va, target_va=base + offset
            )
            if name == "constructor_width":
                # Preserve the interleaved MSVC exception-unwind state store.
                replacement += bytes.fromhex("c6 45 fc 07")
            replacement += b"\x90" * (len(site.original) - len(replacement))
            plan.replace(
                label=f"LSR {name}", va=site.va, expected=site.original, payload=replacement
            )
        image.write_bytes(section.pointer_to_raw_data, payload.build())
        plan.apply(image)
