"""Compile fingerprint-workstation composition into the shared runtime."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import (
    REL32_INSTRUCTION_SIZE,
    BranchOpcode,
    Condition,
    X86Emitter,
    decode_rel32_branch,
    encode_rel32_branch,
)
from gk3hd.patch.definitions.runtime2d.fingerprint_tools import (
    build_damage_selector,
    build_dust_input,
    build_tool_match,
    build_tool_transform,
)
from gk3hd.patch.definitions.runtime2d.geometry import AUTHORED_FRAME_HEIGHT
from gk3hd.patch.definitions.runtime2d.layout import (
    FINGERPRINT_DAMAGE_SELECTOR_OFFSET,
    FINGERPRINT_LAYOUT_ACTIVE_OFFSET,
    FINGERPRINT_SEGMENT,
    FINGERPRINT_TOOL_MATCH_OFFSET,
    RESOURCE_SEGMENT,
    SYSTEM_CONTROL_FULL_DAMAGE_REGION_OFFSET,
    SYSTEM_CONTROL_SEGMENT,
    SYSTEM_SEGMENT,
    install_runtime_segment,
)
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols


@dataclass(frozen=True, slots=True, kw_only=True)
class FingerprintFeatureCompiler:
    """Render the fingerprint workstation from one authored logical model.

    Outcome:
        Base, mirror, brush, print overlays, and hit rectangles retain the stock
        centered 640x480 composition at every display size.
    Before:
        GK3 treats raster pixels as model units, so exact 4x ``FP_*`` replacements
        expand the workstation and displace its independently drawn overlays.
    After:
        Dense source rasters sample into their original logical rectangles, then
        the complete workstation follows the fixed-interface affine and inverse.
    Strategy:
        Record only bitmap surfaces whose resource name starts with ``FP_``;
        exact 2560x1920 ``FP_BASE`` dimensions activate dense-art handling. The
        shared dispatcher restores full sources and presents them at one quarter
        of their raster dimensions. Physical overlays first rebase from GK3's
        centered 1024x768 canvas; private intermediate surfaces keep local origins.
        The two moving tool images are identified independently through live
        resources. Their physical pointer anchors remain fixed while extents
        follow the workstation scale, including native/dense mixed packs.
    Boundaries:
        Unrelated resources pass through untouched. This feature does not own the
        general fixed-root transform, pointer dispatcher, or ordinary 3D viewport.
    """

    symbols: RuntimeSymbols
    profile: BuildProfile

    id: ClassVar[str] = "runtime2d.fingerprint"

    _section_name: ClassVar[str] = FINGERPRINT_SEGMENT.logical_name
    _section_size: ClassVar[int] = FINGERPRINT_SEGMENT.size
    _section_characteristics: ClassVar[int] = FINGERPRINT_SEGMENT.characteristics
    _magic: ClassVar[bytes] = FINGERPRINT_SEGMENT.magic
    _layout_version: ClassVar[int] = 18
    _off_layout_version: ClassVar[int] = 0x08
    _off_transform_count: ClassVar[int] = 0x0C
    _off_hd_set_active: ClassVar[int] = 0x10
    _off_dest_rect: ClassVar[int] = 0x20
    _off_source_rect: ClassVar[int] = 0x30
    _off_last_surface: ClassVar[int] = 0x44
    _off_last_width: ClassVar[int] = 0x48
    _off_last_height: ClassVar[int] = 0x4C
    _off_surface_count: ClassVar[int] = 0x50
    _off_surfaces: ClassVar[int] = 0x54
    # Forty-eight live FP surfaces still leaves ample headroom (the complete
    # workstation currently owns four).  The reclaimed tail of this table is
    # dedicated to FP_BRUSH geometry because a misplaced opaque brush overlay
    # is otherwise indistinguishable from corruption in the 4x FP_BASE image.
    _surface_capacity: ClassVar[int] = 48
    _off_brush_input_dest_rect: ClassVar[int] = 0x114
    _off_brush_input_source_rect: ClassVar[int] = 0x124
    _off_brush_dest_rect: ClassVar[int] = 0x134
    _off_brush_source_rect: ClassVar[int] = 0x144
    # Keep dedicated FP_BASE telemetry outside the bounded surface table.  The
    # generic "last" record normally belongs to MIRROR because it is drawn
    # later, which made a missing/clipped base impossible to distinguish from
    # a correct base followed by a bad overlay.
    _off_base_dest_rect: ClassVar[int] = 0x154
    _off_base_source_rect: ClassVar[int] = 0x164
    _off_base_transform_count: ClassVar[int] = 0x174
    _off_base_input_dest_wrapper: ClassVar[int] = 0x178
    _off_base_input_dest_dimensions: ClassVar[int] = 0x17C
    _off_base_input_dest_rect: ClassVar[int] = 0x184
    _off_base_input_source_rect: ClassVar[int] = 0x194
    # Preserve the first FP_BASE transfer separately from the "latest" fields
    # above. FP_BASE is submitted twice: once while the workstation is being
    # composed and once when that composition reaches the physical screen.
    _off_base_first_input_dest_wrapper: ClassVar[int] = 0x1A4
    _off_base_first_input_dest_dimensions: ClassVar[int] = 0x1A8
    _off_base_first_input_dest_rect: ClassVar[int] = 0x1B0
    _off_base_first_input_source_rect: ClassVar[int] = 0x1C0
    _off_base_native_dest_rect: ClassVar[int] = 0x1D0
    _off_base_system_source_rect: ClassVar[int] = 0x1E0
    _off_base_system_target_rect: ClassVar[int] = 0x1F0
    _off_wrapper: ClassVar[int] = 0x200
    _off_resource_probe_wrapper: ClassVar[int] = 0x900
    _off_layout_prepare_wrapper: ClassVar[int] = 0xA00
    _off_layout_restore_wrapper: ClassVar[int] = 0xC00
    _off_dust_input: ClassVar[int] = 0xE60
    _off_layout_saved_root: ClassVar[int] = 0xE00
    _off_layout_saved_rects: ClassVar[int] = 0xE04
    _off_layout_active: ClassVar[int] = FINGERPRINT_LAYOUT_ACTIVE_OFFSET
    _off_tool_match: ClassVar[int] = FINGERPRINT_TOOL_MATCH_OFFSET

    # FingerprintLayer embeds these widgets directly. Runtime object-tree
    # telemetry confirms the offsets on both the stock and normalized Steam
    # builds; +0x1C is the common Drawable RECT.
    _fingerprint_exit_object_offset: ClassVar[int] = 0x464
    _fingerprint_mask_object_offsets: ClassVar[tuple[int, ...]] = (
        0x500,  # top
        0x534,  # bottom
        0x568,  # left
        0x59C,  # right
    )
    _drawable_rect_offset: ClassVar[int] = 0x1C

    _hd_2d_bitmap_entry_probe_offset: ClassVar[int] = 0xA00
    _system_input_active_offset: ClassVar[int] = 0x10
    _system_source_rect_offset: ClassVar[int] = 0x20
    _system_target_rect_offset: ClassVar[int] = 0x30
    _system_transform_mode_offset: ClassVar[int] = 0xE0
    _system_popup_mode: ClassVar[int] = 2

    @property
    def _resolve_bitmap_resource_va(self) -> int:
        return self.profile.address("bitmap.resolve_resource")

    @property
    def _physical_width_va(self) -> int:
        return self.profile.address("display.dimensions")

    @staticmethod
    def _rel_target(site_va: int, branch: bytes) -> int | None:
        if len(branch) != REL32_INSTRUCTION_SIZE:
            return None
        try:
            opcode = BranchOpcode(branch[0])
        except ValueError:
            return None
        return decode_rel32_branch(opcode=opcode, site_va=site_va, instruction=branch)

    def _hd_section(self) -> tuple[int, int]:
        address = self.symbols.require(RESOURCE_SEGMENT.logical_name)
        return address.raw_offset, address.va

    def _system_state(self) -> tuple[int, int, int, int]:
        base = self.symbols.va(SYSTEM_SEGMENT.logical_name)
        return (
            base + self._system_input_active_offset,
            base + self._system_transform_mode_offset,
            base + self._system_source_rect_offset,
            base + self._system_target_rect_offset,
        )

    def _hd_resource_lookup_call(
        self,
        pe: PEFile,
        *,
        fingerprint_probe_va: int | None,
    ) -> tuple[int, int]:
        raw, section_va = self._hd_section()
        segment = self.symbols.require(RESOURCE_SEGMENT.logical_name).segment
        start = self._hd_2d_bitmap_entry_probe_offset
        end = min(0xC00, segment.size)
        probe = pe.read_bytes(raw + start, end - start)
        allowed_targets = {self._resolve_bitmap_resource_va}
        if fingerprint_probe_va is not None:
            allowed_targets.add(fingerprint_probe_va)
        matches: list[tuple[int, int]] = []
        for index in range(len(probe) - (REL32_INSTRUCTION_SIZE - 1)):
            if probe[index] != BranchOpcode.CALL:
                continue
            call_va = section_va + start + index
            target = self._rel_target(
                call_va,
                probe[index : index + REL32_INSTRUCTION_SIZE],
            )
            if target in allowed_targets:
                matches.append((raw + start + index, call_va))
        if len(matches) != 1:
            msg = f"{self.id} expected one bitmap-resource lookup, found {len(matches)}"
            raise PatchError(msg)
        return matches[0]

    def _build_resource_probe_wrapper(
        self,
        *,
        wrapper_va: int,
        hd_set_active_va: int,
        surface_count_va: int,
        surfaces_va: int,
        last_surface_va: int,
    ) -> bytes:
        # The resource feature already resolves the bitmap under its recursion
        # guard. Wrap that one stdcall instead of resolving a second
        # time from the bitmap entry, which could re-enter the older engine's
        # resource loader while an FP surface was still being constructed.
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\xff\x74\x24\x04")
        code.call_absolute(self._resolve_bitmap_resource_va)
        code.raw(b"\x9c\x60")
        code.raw(b"\x8b\x44\x24\x1c")
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\x66\x81\x78\x08FP")
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.raw(b"\x80\x78\x0a_")
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.raw(b"\x8b\x50\x30\x85\xd2")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\x89\x15" + struct.pack("<I", last_surface_va))

        # Activate only for the exact 4x FP_BASE. Native resources share the
        # same prefix and must never be quartered.
        code.raw(b"\x81\x78\x08FP_B")
        code.jump_if(Condition.NOT_EQUAL, "store_surface")
        code.raw(b"\x81\x78\x0cASE\x00")
        code.jump_if(Condition.NOT_EQUAL, "store_surface")
        code.raw(b"\x81\x7a\x38\x00\x0a\x00\x00")
        code.jump_if(Condition.NOT_EQUAL, "store_surface")
        code.raw(b"\x81\x7a\x3c\x80\x07\x00\x00")
        code.jump_if(Condition.NOT_EQUAL, "store_surface")
        code.raw(b"\xc7\x05" + struct.pack("<I", hd_set_active_va) + b"\x01\x00\x00\x00")
        code.label("store_surface")

        # Keep a bounded unique set. The HD pack currently contains fewer than
        # 64 FP surfaces and the whole interface owns only a subset at once.
        code.raw(b"\x8b\x0d" + struct.pack("<I", surface_count_va))
        code.raw(b"\x31\xdb")
        code.label("scan")
        code.raw(b"\x39\xcb")
        code.jump_short_if(Condition.ABOVE_OR_EQUAL, "append")
        code.raw(b"\x39\x14\x9d" + struct.pack("<I", surfaces_va))
        code.jump_short_if(Condition.EQUAL, "native")
        code.raw(b"\x43")
        code.jump_short("scan")
        code.label("append")
        code.raw(b"\x83\xf9" + bytes([self._surface_capacity]))
        code.jump_short_if(Condition.ABOVE_OR_EQUAL, "native")
        code.raw(b"\x89\x14\x8d" + struct.pack("<I", surfaces_va))
        code.raw(b"\x41\x89\x0d" + struct.pack("<I", surface_count_va))

        code.label("native")
        code.raw(b"\x61\x9d\xc2\x04\x00")
        return code.build()

    def _build_layout_prepare_wrapper(
        self,
        *,
        hd_set_active_va: int,
        saved_root_va: int,
        saved_rects_va: int,
        layout_active_va: int,
    ) -> bytes:
        """Temporarily align non-bitmap FP widgets with the HD viewport."""
        code = X86Emitter(base_va=0)
        code.raw(b"\x83\x3d" + struct.pack("<I", hd_set_active_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x83\x3d" + struct.pack("<I", layout_active_va) + b"\x00")
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\x81\x3d" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(struct.pack("<I", AUTHORED_FRAME_HEIGHT))
        code.jump_if(Condition.BELOW_OR_EQUAL, "done")
        code.raw(b"\x89\x0d" + struct.pack("<I", saved_root_va))

        # Save the exact object rectangles. Input dispatch runs after Draw has
        # returned, so restoring these values preserves GK3's raw hit geometry.
        object_offsets = (
            self._fingerprint_exit_object_offset,
            *self._fingerprint_mask_object_offsets,
        )
        for index, object_offset in enumerate(object_offsets):
            code.raw(b"\x8b\x35" + struct.pack("<I", saved_root_va))
            code.raw(b"\x81\xc6" + struct.pack("<I", object_offset + self._drawable_rect_offset))
            code.raw(b"\xbf" + struct.pack("<I", saved_rects_va + index * 16))
            code.raw(b"\xb9\x04\x00\x00\x00\xf3\xa5")
        code.raw(b"\xc7\x05" + struct.pack("<I", layout_active_va) + b"\x01\x00\x00\x00")

        # EDX owns the layer base, EBX/ECX the physical dimensions, ESI/EDI
        # their centers, and EBP the fixed 768 reference denominator.
        code += b"\x8b\x15" + struct.pack("<I", saved_root_va)
        code += b"\x8b\x1d" + struct.pack("<I", self._physical_width_va)
        code += b"\x8b\x0d" + struct.pack("<I", self._physical_width_va + 4)
        code += b"\x8b\xf3\xd1\xee\x8b\xf9\xd1\xef\xbd\x00\x03\x00\x00"

        exit_rect = self._fingerprint_exit_object_offset + self._drawable_rect_offset
        # Transform the Exit anchor about the physical center, but retain its
        # native 58x26 extent: the downstream sprite blit scales that extent
        # once. Moving the far edge here as well would double-scale the button.
        code += b"\x8b\xc1\x69\xc0" + struct.pack("<i", -315) + b"\x99\xf7\xfd\x03\xc6"
        code += b"\x8b\x15" + struct.pack("<I", saved_root_va)
        code += b"\x89\x82" + struct.pack("<I", exit_rect)
        code += b"\x83\xc0\x3a\x89\x82" + struct.pack("<I", exit_rect + 8)
        code += b"\x8b\xc1\x69\xc0" + struct.pack("<i", 205) + b"\x99\xf7\xfd\x03\xc7"
        code += b"\x8b\x15" + struct.pack("<I", saved_root_va)
        code += b"\x89\x82" + struct.pack("<I", exit_rect + 4)
        code += b"\x83\xc0\x1a\x89\x82" + struct.pack("<I", exit_rect + 12)

        top_rect = self._fingerprint_mask_object_offsets[0] + self._drawable_rect_offset
        bottom_rect = self._fingerprint_mask_object_offsets[1] + self._drawable_rect_offset
        left_rect = self._fingerprint_mask_object_offsets[2] + self._drawable_rect_offset
        right_rect = self._fingerprint_mask_object_offsets[3] + self._drawable_rect_offset

        # left boundary = centerX - 320 * H / 768
        code += b"\x8b\xc1\x69\xc0" + struct.pack("<i", -320) + b"\x99\xf7\xfd\x03\xc6"
        code += b"\x8b\x15" + struct.pack("<I", saved_root_va)
        code += b"\x89\x82" + struct.pack("<I", left_rect + 8)
        # right boundary = centerX + 320 * H / 768
        code += b"\x8b\xc1\x69\xc0" + struct.pack("<i", 320) + b"\x99\xf7\xfd\x03\xc6"
        code += b"\x8b\x15" + struct.pack("<I", saved_root_va)
        code += b"\x89\x82" + struct.pack("<I", right_rect)
        # top boundary = centerY - 240 * H / 768
        code += b"\x8b\xc1\x69\xc0" + struct.pack("<i", -240) + b"\x99\xf7\xfd\x03\xc7"
        code += b"\x8b\x15" + struct.pack("<I", saved_root_va)
        for displacement in (top_rect + 12, left_rect + 4, right_rect + 4):
            code += b"\x89\x82" + struct.pack("<I", displacement)
        # bottom boundary = centerY + 240 * H / 768
        code += b"\x8b\xc1\x69\xc0" + struct.pack("<i", 240) + b"\x99\xf7\xfd\x03\xc7"
        code += b"\x8b\x15" + struct.pack("<I", saved_root_va)
        for displacement in (bottom_rect + 4, left_rect + 12, right_rect + 12):
            code += b"\x89\x82" + struct.pack("<I", displacement)

        # Complete the four screen-cover rectangles from physical edges.
        for displacement in (
            top_rect,
            top_rect + 4,
            bottom_rect,
            left_rect,
        ):
            code += b"\xc7\x82" + struct.pack("<I", displacement) + b"\x00\x00\x00\x00"
        for displacement in (top_rect + 8, bottom_rect + 8, right_rect + 8):
            code += b"\x89\x9a" + struct.pack("<I", displacement)
        code += b"\x89\x8a" + struct.pack("<I", bottom_rect + 12)

        code.label("done")
        code.ret()
        return code.build()

    def _build_layout_restore_wrapper(
        self,
        *,
        saved_root_va: int,
        saved_rects_va: int,
        layout_active_va: int,
    ) -> bytes:
        code = X86Emitter(base_va=0)
        code.raw(b"\x83\x3d" + struct.pack("<I", layout_active_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "done")
        object_offsets = (
            self._fingerprint_exit_object_offset,
            *self._fingerprint_mask_object_offsets,
        )
        for index, object_offset in enumerate(object_offsets):
            code += b"\xbe" + struct.pack("<I", saved_rects_va + index * 16)
            code += b"\x8b\x3d" + struct.pack("<I", saved_root_va)
            code += b"\x81\xc7" + struct.pack("<I", object_offset + self._drawable_rect_offset)
            code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        code += b"\xc7\x05" + struct.pack("<I", layout_active_va) + b"\x00\x00\x00\x00"
        code.label("done")
        code.ret()
        return code.build()

    def _build_wrapper(
        self,
        *,
        wrapper_va: int,
        tool_match_va: int,
        layout_active_va: int,
        transform_count_va: int,
        hd_set_active_va: int,
        dest_rect_va: int,
        source_rect_va: int,
        surface_count_va: int,
        surfaces_va: int,
        last_surface_va: int,
        last_width_va: int,
        last_height_va: int,
        base_dest_rect_va: int,
        base_source_rect_va: int,
        base_transform_count_va: int,
        base_input_dest_wrapper_va: int,
        base_input_dest_dimensions_va: int,
        base_input_dest_rect_va: int,
        base_input_source_rect_va: int,
        base_first_input_dest_wrapper_va: int,
        base_first_input_dest_dimensions_va: int,
        base_first_input_dest_rect_va: int,
        base_first_input_source_rect_va: int,
        base_native_dest_rect_va: int,
        base_system_source_rect_va: int,
        base_system_target_rect_va: int,
        brush_input_dest_rect_va: int,
        brush_input_source_rect_va: int,
        brush_dest_rect_va: int,
        brush_source_rect_va: int,
        system_state: tuple[int, int, int, int],
    ) -> bytes:
        # Called from inside the resource dispatcher's PUSHAD frame. The helper may
        # use general registers freely; the outer dispatcher restores them.
        # Its source, destination RECT, and source RECT are at +28/+2C/+30.
        code = X86Emitter(base_va=wrapper_va)
        code.raw(
            build_tool_transform(
                wrapper_va=wrapper_va,
                match_va=tool_match_va,
                layout_active_va=layout_active_va,
                dimensions_va=self._physical_width_va,
                dest_rect_va=dest_rect_va,
                source_rect_va=source_rect_va,
            )
        )
        code += b"\x83\x3d" + struct.pack("<I", hd_set_active_va) + b"\x00"
        code.jump_if(Condition.EQUAL, "native")
        code += b"\x8b\x5c\x24\x28"
        code += b"\x8b\x0d" + struct.pack("<I", surface_count_va)
        code += b"\x31\xd2"
        code.label("scan")
        code += b"\x39\xca"
        code.jump_if(Condition.ABOVE_OR_EQUAL, "native")
        code += b"\x3b\x1c\x95" + struct.pack("<I", surfaces_va)
        code.jump_short_if(Condition.EQUAL, "transform")
        code += b"\x42"
        code.jump_short("scan")
        code.label("transform")

        code += b"\x8b\x74\x24\x2c\x85\xf6"
        code.jump_if(Condition.EQUAL, "native")
        code += b"\x8b\x7c\x24\x30\x85\xff"
        code.jump_if(Condition.EQUAL, "native")
        code += b"\x89\x1d" + struct.pack("<I", last_surface_va)
        code += b"\x8b\x4b\x38\x89\x0d" + struct.pack("<I", last_width_va)
        code += b"\x8b\x53\x3c\x89\x15" + struct.pack("<I", last_height_va)
        code += b"\x83\xf9\x04"
        code.jump_if(Condition.BELOW, "native")
        code += b"\x83\xfa\x04"
        code.jump_if(Condition.BELOW, "native")

        # Retain both ends of FP_BRUSH's geometry pipeline.  Unlike transparent
        # print overlays, this bitmap intentionally contains a rectangular
        # slice of FP_BASE, so even a small origin error is immediately visible.
        code += b"\x81\xf9\xac\x02\x00\x00"
        code.jump_short_if(Condition.NOT_EQUAL, "brush_input_recorded")
        code += b"\x81\xfa\xb4\x00\x00\x00"
        code.jump_short_if(Condition.NOT_EQUAL, "brush_input_recorded")
        code += b"\xbf" + struct.pack("<I", brush_input_dest_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        code += b"\x8b\x74\x24\x30\xbf" + struct.pack("<I", brush_input_source_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        code.label("brush_input_recorded")
        # REP MOVSD advanced the incoming pointers; all following logic expects
        # their original addresses and reloads surface dimensions independently.
        code += b"\x8b\x74\x24\x2c\x8b\x7c\x24\x30"

        # Capture the exact FP_BASE input before either the system-coordinate
        # recovery or quarter-size reconstruction mutates it.  Only one
        # fixed-size record is needed: the last base transfer is sufficient to
        # identify its destination surface and clipping convention.
        code += b"\x81\xf9\x00\x0a\x00\x00"
        code.jump_short_if(Condition.NOT_EQUAL, "input_base_recorded")
        code += b"\x81\xfa\x80\x07\x00\x00"
        code.jump_short_if(Condition.NOT_EQUAL, "input_base_recorded")
        code += b"\x8b\x44\x24\x1c\xa3" + struct.pack("<I", base_input_dest_wrapper_va)
        code += b"\x85\xc0"
        code.jump_short_if(Condition.EQUAL, "input_dest_dimensions_done")
        code += b"\x8b\x68\x38\x89\x2d" + struct.pack("<I", base_input_dest_dimensions_va)
        code += b"\x8b\x68\x3c\x89\x2d" + struct.pack("<I", base_input_dest_dimensions_va + 4)
        code.label("input_dest_dimensions_done")
        code += b"\x8b\x74\x24\x2c\xbf" + struct.pack("<I", base_input_dest_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        code += b"\x8b\x74\x24\x30\xbf" + struct.pack("<I", base_input_source_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        # System-screen globals are scoped and can change again before the
        # capture tool samples them. Preserve the exact affine seen by FP_BASE
        # so the native and mapped rectangles can be reconciled.
        code += b"\xbe" + struct.pack("<I", system_state[2])
        code += b"\xbf" + struct.pack("<I", base_system_source_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        code += b"\xbe" + struct.pack("<I", system_state[3])
        code += b"\xbf" + struct.pack("<I", base_system_target_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        code.label("input_base_recorded")
        # REP MOVSD advances both registers.  Restore the caller-owned RECT
        # pointers expected by the reconstruction below; otherwise its first
        # edge reads immediately past the source RECT and the clip-origin
        # subtraction uses the end of our telemetry buffer.
        code += b"\x8b\x74\x24\x2c\x8b\x7c\x24\x30"

        # Retain the first FP_BASE input before the common "latest call"
        # fields are overwritten by the presentation transfer. The counter is
        # incremented only after a transformed call, so zero identifies this
        # composition phase without adding mutable render-path state.
        code += b"\x83\x3d" + struct.pack("<I", base_transform_count_va) + b"\x00"
        code.jump_if(Condition.NOT_EQUAL, "first_base_recorded")
        code += b"\x8b\x44\x24\x1c\xa3" + struct.pack("<I", base_first_input_dest_wrapper_va)
        code += b"\x85\xc0"
        code.jump_short_if(Condition.EQUAL, "first_input_dest_dimensions_done")
        code += b"\x8b\x68\x38\x89\x2d" + struct.pack("<I", base_first_input_dest_dimensions_va)
        code += b"\x8b\x68\x3c\x89\x2d" + struct.pack("<I", base_first_input_dest_dimensions_va + 4)
        code.label("first_input_dest_dimensions_done")
        code += b"\x8b\x74\x24\x2c\xbf" + struct.pack("<I", base_first_input_dest_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        code += b"\x8b\x74\x24\x30\xbf" + struct.pack("<I", base_first_input_source_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        code.label("first_base_recorded")
        # REP MOVSD advances the caller-owned RECT pointers.
        code += b"\x8b\x74\x24\x2c\x8b\x7c\x24\x30"

        # Physical-screen FP children arrive in a centered 1024x768 canvas.
        # This is a crucially different coordinate space from the system root:
        # at 1920x1080 an overlay submitted at (768, 645) actually denotes the
        # reference point (320, 489), after removing the (448, 156) canvas
        # offset.  The former system-affine inverse merely canceled its later
        # forward transform and left that offset embedded in MIRROR/BRUSH.
        (
            system_input_active_va,
            system_transform_mode_va,
            _system_source_rect_va,
            _system_target_rect_va,
        ) = system_state
        # The outer system dispatcher applies its popup affine only when ECX
        # is the physical screen wrapper. FP assets also use private surfaces;
        # reproduce that destination identity check before applying an inverse.
        code += b"\x8b\x44\x24\x1c\x85\xc0"
        code.jump_if(Condition.EQUAL, "native_dest")
        code += b"\x8b\x2d" + struct.pack("<I", self._physical_width_va)
        code += b"\x39\x68\x38"
        code.jump_if(Condition.NOT_EQUAL, "native_dest")
        code += b"\x8b\x2d" + struct.pack("<I", self._physical_width_va + 4)
        code += b"\x39\x68\x3c"
        code.jump_if(Condition.NOT_EQUAL, "native_dest")
        code += b"\x83\x3d" + struct.pack("<I", system_input_active_va) + b"\x00"
        code.jump_if(Condition.EQUAL, "native_dest")
        code += b"\x83\x3d" + struct.pack("<I", system_transform_mode_va)
        code += bytes([self._system_popup_mode])
        code.jump_if(Condition.NOT_EQUAL, "native_dest")

        # FP_BASE's oversized right/bottom edges are already screen-clipped;
        # reconstruct its authored 640x480 origin directly in reference space.
        code += b"\x8b\x4b\x38\x8b\x53\x3c"
        code += b"\x81\xf9\x00\x0a\x00\x00"
        code.jump_if(Condition.NOT_EQUAL, "centered_child")
        code += b"\x81\xfa\x80\x07\x00\x00"
        code.jump_if(Condition.NOT_EQUAL, "centered_child")
        code += b"\xc7\x05" + struct.pack("<I", dest_rect_va)
        code += struct.pack("<I", 192)
        code += b"\xc7\x05" + struct.pack("<I", dest_rect_va + 4)
        code += struct.pack("<I", 144)
        code.jump("recovered_dest_ready")
        code.label("centered_child")
        code += b"\x8b\x06\x8b\x2d" + struct.pack("<I", self._physical_width_va)
        code += b"\x81\xed\x00\x04\x00\x00\xd1\xfd\x29\xe8"
        code += b"\xa3" + struct.pack("<I", dest_rect_va)
        code += b"\x8b\x46\x04\x8b\x2d" + struct.pack("<I", self._physical_width_va + 4)
        code += b"\x81\xed\x00\x03\x00\x00\xd1\xfd\x29\xe8"
        code += b"\xa3" + struct.pack("<I", dest_rect_va + 4)
        code.jump("recovered_dest_ready")
        code.label("native_dest")
        code += b"\x8b\x06\xa3" + struct.pack("<I", dest_rect_va)
        code += b"\x8b\x46\x04\xa3" + struct.pack("<I", dest_rect_va + 4)
        code.label("recovered_dest_ready")

        # The system-coordinate inverse above deliberately uses ECX
        # and EDX for its source/target spans and signed division.  Reload the
        # FP surface dimensions here: retaining the temporaries made the final
        # width depend on a viewport span and the height on CDQ's sign word,
        # which stretched the MIRROR asset horizontally and flattened it
        # vertically.  EBX still owns the matched surface wrapper throughout.
        code += b"\x8b\x4b\x38\x8b\x53\x3c"

        # Recover the unclipped native-pixel origin and quarter only the extent.
        code += b"\xa1" + struct.pack("<I", dest_rect_va) + b"\x2b\x07\xa3"
        code += struct.pack("<I", dest_rect_va)
        code += b"\xc1\xe9\x02\x01\xc8\xa3" + struct.pack("<I", dest_rect_va + 8)
        code += b"\xa1" + struct.pack("<I", dest_rect_va + 4) + b"\x2b\x47\x04\xa3"
        code += struct.pack("<I", dest_rect_va + 4)
        code += b"\xc1\xea\x02\x01\xd0\xa3" + struct.pack("<I", dest_rect_va + 12)

        # Snapshot the reconstructed native-pixel rectangle before the shared
        # popup affine. This separates quarter-size mistakes from later
        # viewport mapping in live diagnostics.
        code += b"\x81\x7b\x38\x00\x0a\x00\x00"
        code.jump_short_if(Condition.NOT_EQUAL, "native_base_recorded")
        code += b"\x81\x7b\x3c\x80\x07\x00\x00"
        code.jump_short_if(Condition.NOT_EQUAL, "native_base_recorded")
        code += b"\xbe" + struct.pack("<I", dest_rect_va)
        code += b"\xbf" + struct.pack("<I", base_native_dest_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        code.label("native_base_recorded")

        # Map the complete quarter-size reference rectangle directly into the
        # height-fitted 4:3 viewport. The system root's affine maps a physical
        # canvas and is deliberately not reused for offscreen composition.
        code += b"\x8b\x44\x24\x1c\x85\xc0"
        code.jump_if(Condition.EQUAL, "forward_done")
        code += b"\x8b\x2d" + struct.pack("<I", self._physical_width_va)
        code += b"\x39\x68\x38"
        code.jump_if(Condition.NOT_EQUAL, "forward_done")
        code += b"\x8b\x2d" + struct.pack("<I", self._physical_width_va + 4)
        code += b"\x39\x68\x3c"
        code.jump_if(Condition.NOT_EQUAL, "forward_done")
        code += b"\x83\x3d" + struct.pack("<I", system_state[0]) + b"\x00"
        code.jump_if(Condition.EQUAL, "forward_done")
        code += b"\x83\x3d" + struct.pack("<I", system_state[1])
        code += bytes([self._system_popup_mode])
        code.jump_if(Condition.NOT_EQUAL, "forward_done")

        for index, axis in enumerate((0, 1, 0, 1)):
            code += b"\xa1" + struct.pack("<I", dest_rect_va + index * 4)
            code += b"\x0f\xaf\x05" + struct.pack("<I", self._physical_width_va + 4)
            code += b"\x99\xb9\x00\x03\x00\x00\xf7\xf9"
            if axis == 0:
                # left margin = (W - 1024 * H / 768) / 2
                code += b"\x89\xc5\xa1" + struct.pack("<I", self._physical_width_va + 4)
                code += b"\xc1\xe0\x0a\x99\xf7\xf9"
                code += b"\x8b\x15" + struct.pack("<I", self._physical_width_va)
                code += b"\x29\xc2\xd1\xfa\x89\xe8\x01\xd0"
            code += b"\xa3" + struct.pack("<I", dest_rect_va + index * 4)
        code.label("forward_done")

        code += b"\x81\x7b\x38\xac\x02\x00\x00"
        code.jump_short_if(Condition.NOT_EQUAL, "brush_dest_recorded")
        code += b"\x81\x7b\x3c\xb4\x00\x00\x00"
        code.jump_short_if(Condition.NOT_EQUAL, "brush_dest_recorded")
        code += b"\xbe" + struct.pack("<I", dest_rect_va)
        code += b"\xbf" + struct.pack("<I", brush_dest_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        code.label("brush_dest_recorded")

        code += b"\x31\xc0\xa3" + struct.pack("<I", source_rect_va)
        code += b"\xa3" + struct.pack("<I", source_rect_va + 4)
        code += b"\x8b\x43\x38\xa3" + struct.pack("<I", source_rect_va + 8)
        code += b"\x8b\x43\x3c\xa3" + struct.pack("<I", source_rect_va + 12)

        code += b"\x81\x7b\x38\xac\x02\x00\x00"
        code.jump_short_if(Condition.NOT_EQUAL, "brush_source_recorded")
        code += b"\x81\x7b\x3c\xb4\x00\x00\x00"
        code.jump_short_if(Condition.NOT_EQUAL, "brush_source_recorded")
        code += b"\xbe" + struct.pack("<I", source_rect_va)
        code += b"\xbf" + struct.pack("<I", brush_source_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        code.label("brush_source_recorded")

        # FP_BASE is the one exact 2560x1920 member that defines the complete
        # workstation canvas.  Snapshot its final rectangles immediately
        # before the downstream blit so a live capture proves whether missing
        # base pixels are caused by geometry or by later composition.
        code += b"\x81\x7b\x38\x00\x0a\x00\x00"
        code.jump_short_if(Condition.NOT_EQUAL, "base_recorded")
        code += b"\x81\x7b\x3c\x80\x07\x00\x00"
        code.jump_short_if(Condition.NOT_EQUAL, "base_recorded")
        code += b"\xbe" + struct.pack("<I", dest_rect_va)
        code += b"\xbf" + struct.pack("<I", base_dest_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        code += b"\xbe" + struct.pack("<I", source_rect_va)
        code += b"\xbf" + struct.pack("<I", base_source_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        code += b"\xff\x05" + struct.pack("<I", base_transform_count_va)
        code.label("base_recorded")

        code += b"\xc7\x44\x24\x2c" + struct.pack("<I", dest_rect_va)
        code += b"\xc7\x44\x24\x30" + struct.pack("<I", source_rect_va)
        code += b"\xff\x05" + struct.pack("<I", transform_count_va)

        code.label("native")
        code.ret()
        return code.build()

    def precheck(self, pe: PEFile) -> None:
        """Validate pristine fingerprint and resource-dispatch sites."""
        if pe.get_section(self._section_name) is not None:
            msg = f"{self.id} requires a pristine fingerprint section"
            raise PatchError(msg)
        # Resource composition already targets this planned symbol before the
        # fingerprint payload bytes are emitted; symbol ownership replaces the
        # former install-order discovery pass.
        probe_va = self.symbols.va(
            FINGERPRINT_SEGMENT.logical_name, self._off_resource_probe_wrapper
        )
        self._hd_resource_lookup_call(pe, fingerprint_probe_va=probe_va)

    def apply(self, pe: PEFile) -> None:
        """Emit fingerprint composition, lookup, layout, and input state."""
        section = install_runtime_segment(pe, FINGERPRINT_SEGMENT)
        section_va = pe.rva_to_va(section.virtual_address)
        resource_probe_va = section_va + self._off_resource_probe_wrapper

        wrapper = self._build_wrapper(
            wrapper_va=section_va + self._off_wrapper,
            tool_match_va=section_va + self._off_tool_match,
            layout_active_va=section_va + self._off_layout_active,
            transform_count_va=section_va + self._off_transform_count,
            hd_set_active_va=section_va + self._off_hd_set_active,
            dest_rect_va=section_va + self._off_dest_rect,
            source_rect_va=section_va + self._off_source_rect,
            surface_count_va=section_va + self._off_surface_count,
            surfaces_va=section_va + self._off_surfaces,
            last_surface_va=section_va + self._off_last_surface,
            last_width_va=section_va + self._off_last_width,
            last_height_va=section_va + self._off_last_height,
            base_dest_rect_va=section_va + self._off_base_dest_rect,
            base_source_rect_va=section_va + self._off_base_source_rect,
            base_transform_count_va=section_va + self._off_base_transform_count,
            base_input_dest_wrapper_va=(section_va + self._off_base_input_dest_wrapper),
            base_input_dest_dimensions_va=(section_va + self._off_base_input_dest_dimensions),
            base_input_dest_rect_va=section_va + self._off_base_input_dest_rect,
            base_input_source_rect_va=section_va + self._off_base_input_source_rect,
            base_first_input_dest_wrapper_va=(section_va + self._off_base_first_input_dest_wrapper),
            base_first_input_dest_dimensions_va=(
                section_va + self._off_base_first_input_dest_dimensions
            ),
            base_first_input_dest_rect_va=(section_va + self._off_base_first_input_dest_rect),
            base_first_input_source_rect_va=(section_va + self._off_base_first_input_source_rect),
            base_native_dest_rect_va=section_va + self._off_base_native_dest_rect,
            base_system_source_rect_va=section_va + self._off_base_system_source_rect,
            base_system_target_rect_va=section_va + self._off_base_system_target_rect,
            brush_input_dest_rect_va=section_va + self._off_brush_input_dest_rect,
            brush_input_source_rect_va=section_va + self._off_brush_input_source_rect,
            brush_dest_rect_va=section_va + self._off_brush_dest_rect,
            brush_source_rect_va=section_va + self._off_brush_source_rect,
            system_state=self._system_state(),
        )
        resource_probe = self._build_resource_probe_wrapper(
            wrapper_va=resource_probe_va,
            hd_set_active_va=section_va + self._off_hd_set_active,
            surface_count_va=section_va + self._off_surface_count,
            surfaces_va=section_va + self._off_surfaces,
            last_surface_va=section_va + self._off_last_surface,
        )
        layout_prepare = self._build_layout_prepare_wrapper(
            hd_set_active_va=section_va + self._off_hd_set_active,
            saved_root_va=section_va + self._off_layout_saved_root,
            saved_rects_va=section_va + self._off_layout_saved_rects,
            layout_active_va=section_va + self._off_layout_active,
        )
        layout_restore = self._build_layout_restore_wrapper(
            saved_root_va=section_va + self._off_layout_saved_root,
            saved_rects_va=section_va + self._off_layout_saved_rects,
            layout_active_va=section_va + self._off_layout_active,
        )
        payload = SegmentPayloadBuilder(
            owner=self.id,
            segment=FINGERPRINT_SEGMENT.logical_name,
            size=FINGERPRINT_SEGMENT.size,
        )
        payload.place(label="magic", offset=0, payload=self._magic)
        payload.place(
            label="layout version",
            offset=self._off_layout_version,
            payload=struct.pack("<I", self._layout_version),
        )
        payload.reserve(
            label="surface and affine state",
            offset=self._off_transform_count,
            size=self._off_wrapper - self._off_transform_count,
        )
        for label, offset, code, limit in (
            ("fingerprint blitter", self._off_wrapper, wrapper, self._off_resource_probe_wrapper),
            (
                "FP resource probe",
                self._off_resource_probe_wrapper,
                resource_probe,
                self._off_layout_prepare_wrapper,
            ),
            (
                "layout prepare",
                self._off_layout_prepare_wrapper,
                layout_prepare,
                self._off_layout_restore_wrapper,
            ),
            (
                "layout restore",
                self._off_layout_restore_wrapper,
                layout_restore,
                self._off_tool_match,
            ),
            (
                "fingerprint drag input",
                self._off_dust_input,
                build_dust_input(
                    wrapper_va=section_va + self._off_dust_input,
                    native_va=self.profile.address("fingerprint.dust"),
                    hd_set_active_va=section_va + self._off_hd_set_active,
                    dimensions_va=self._physical_width_va,
                ),
                FINGERPRINT_DAMAGE_SELECTOR_OFFSET,
            ),
        ):
            payload.place(label=label, offset=offset, payload=code, limit=limit)
        payload.reserve(
            label="saved workstation layout",
            offset=self._off_layout_saved_root,
            size=0x58,
        )
        payload.place(
            label="live moving-tool identity",
            offset=self._off_tool_match,
            payload=build_tool_match(
                wrapper_va=section_va + self._off_tool_match,
                manager_va=self.profile.address("bitmap.manager"),
            ),
            limit=self._off_layout_saved_root,
        )
        payload.place(
            label="dense workstation damage policy",
            offset=FINGERPRINT_DAMAGE_SELECTOR_OFFSET,
            payload=build_damage_selector(
                wrapper_va=section_va + FINGERPRINT_DAMAGE_SELECTOR_OFFSET,
                hd_set_active_va=section_va + self._off_hd_set_active,
                dimensions_va=self._physical_width_va,
                full_region_va=self.symbols.va(
                    SYSTEM_CONTROL_SEGMENT.logical_name, SYSTEM_CONTROL_FULL_DAMAGE_REGION_OFFSET
                ),
            ),
        )
        pe.write_bytes(section.pointer_to_raw_data, payload.build())

        _lookup_offset, lookup_va = self._hd_resource_lookup_call(
            pe, fingerprint_probe_va=resource_probe_va
        )
        mutations = ExecutableMutationPlan(owner=self.id)
        mutations.pointer(
            label="fingerprint drag input",
            slot_va=self.profile.address("fingerprint.vtable") + 0x80,
            expected=self.profile.address("fingerprint.dust"),
            target_va=section_va + self._off_dust_input,
        )
        mutations.apply(pe)
        # Resource composition has already linked this cross-owner call;
        # it is independent of the pristine native input vtable redirect.
        mutations = ExecutableMutationPlan(owner=self.id)
        mutations.branch(
            label="fingerprint resource lookup",
            opcode=BranchOpcode.CALL,
            site_va=lookup_va,
            expected=encode_rel32_branch(
                opcode=BranchOpcode.CALL,
                site_va=lookup_va,
                target_va=self._resolve_bitmap_resource_va,
            ),
            target_va=resource_probe_va,
        )
        mutations.apply(pe)

    def postcheck(self, pe: PEFile) -> None:
        """Require this owner's segment after deterministic compilation.

        Runtime2D independently rebuilds and compares every segment and native
        redirect. Re-emitting fingerprint composition here duplicated that proof.
        """
        if pe.get_section(self._section_name) is None:
            msg = f"{self.id} postcheck failed: section missing"
            raise PatchError(msg)
