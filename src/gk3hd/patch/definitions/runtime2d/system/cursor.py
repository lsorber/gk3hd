"""Compile software-cursor geometry, save-under, and final-page ownership."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.cursor_history import HISTORY_OFFSET, emit_history_adapter
from gk3hd.patch.definitions.runtime2d.geometry import AUTHORED_FRAME_HEIGHT
from gk3hd.patch.definitions.runtime2d.layout import (
    BINOCULAR_SEGMENT,
    CAPTION_PRESENTER_OFFSET,
    CAPTION_SEGMENT,
    CURSOR_BLEND_SEGMENT,
    CURSOR_DENSITY_PROBE_OFFSET,
    SIDNEY_PRESENTATION_SEGMENT,
    SYSTEM_CONTROL_CLOSEUP_DEST_HANDLE_OFFSET,
    SYSTEM_CONTROL_CONFIRM_QUIT_CURSOR_SUSPENDED_OFFSET,
    SYSTEM_CONTROL_CURSOR_CLASSIFIER_TRACE_OFFSET,
    SYSTEM_CONTROL_CURSOR_CLASSIFIER_TRACE_SIZE,
    SYSTEM_CONTROL_CURSOR_DISPLAY_BLT_COUNT_OFFSET,
    SYSTEM_CONTROL_CURSOR_DISPLAY_BLT_RESULT_OFFSET,
    SYSTEM_CONTROL_CURSOR_PRESENTED_SOURCE_RECT_OFFSET,
    SYSTEM_CONTROL_CURSOR_PRESENTED_SOURCE_STATE_END_OFFSET,
    SYSTEM_CONTROL_CURSOR_RESOURCE_DRAWABLE_OFFSET,
    SYSTEM_CONTROL_CURSOR_RESOURCE_FRAME_OFFSET,
    SYSTEM_CONTROL_CURSOR_RESOURCE_INVALIDATION_COUNT_OFFSET,
    SYSTEM_CONTROL_CURSOR_RESOURCE_ROOM_ROOT_OFFSET,
    SYSTEM_CONTROL_CURSOR_RESOURCE_STATE_END_OFFSET,
    SYSTEM_CONTROL_CURSOR_RESOURCE_VALID_OFFSET,
    SYSTEM_CONTROL_SEGMENT,
)
from gk3hd.patch.definitions.runtime2d.system.cursor_blend import ENTRY as BLEND_ENTRY
from gk3hd.patch.definitions.runtime2d.system.shared import SystemCompilerContext

if TYPE_CHECKING:
    from gk3hd.patch.binary.mutations import ExecutableMutationPlan
    from gk3hd.patch.binary.payload import SegmentPayloadBuilder


@dataclass(frozen=True, slots=True)
class CursorRuntimeExports:
    """Entry addresses exported by cursor primitive emission."""

    capacity_wrapper_va: int
    scope_wrapper_va: int
    prep_wrapper_va: int
    final_wrapper_va: int
    manager_draw_wrapper_va: int
    bounds_wrapper_va: int
    surface_classifier_va: int
    resource_rebuild_wrapper_va: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CursorFeatureCompiler(SystemCompilerContext):
    """Scale and present GK3's software cursor as one atomic transaction.

    Outcome:
        Cursor sprites, hover frames, loading orbs, save-under repair, and final
        page copies remain visible at the reference-relative scale.
    Before:
        GK3 mixes logical cursor extents with physical positions and restores
        saved pixels through whichever flip peer is current.
    After:
        Sprite extent, scratch capacity, damage, save-under identity, and final
        presentation share one physical transaction and stable scale.
    Strategy:
        Classify concrete cursor surfaces, enlarge capacity before allocation,
        transform cursor extents and hotspots, and publish the completed transaction at
        the render thread's final-page boundary.
    Boundaries:
        Mouse event validity and coordinate inversion have separate owners; this
        feature neither synthesizes pointer input nor changes cursor artwork.
    """

    def emit_state(self, payload: SegmentPayloadBuilder) -> None:
        """Own transform, classification, and final-transfer cursor state."""
        payload.reserve(
            label="cursor transform state",
            offset=self._off_control_cursor_state,
            size=self._control_cursor_state_size,
        )
        payload.reserve(
            label="cursor classifier trace",
            offset=SYSTEM_CONTROL_CURSOR_CLASSIFIER_TRACE_OFFSET,
            size=SYSTEM_CONTROL_CURSOR_CLASSIFIER_TRACE_SIZE,
        )
        payload.reserve(
            label="cursor display-transfer trace",
            offset=SYSTEM_CONTROL_CURSOR_DISPLAY_BLT_COUNT_OFFSET,
            size=SYSTEM_CONTROL_CURSOR_DISPLAY_BLT_RESULT_OFFSET
            - SYSTEM_CONTROL_CURSOR_DISPLAY_BLT_COUNT_OFFSET
            + 4,
        )
        payload.reserve(
            label="cursor presented-source rectangle",
            offset=SYSTEM_CONTROL_CURSOR_PRESENTED_SOURCE_RECT_OFFSET,
            size=SYSTEM_CONTROL_CURSOR_PRESENTED_SOURCE_STATE_END_OFFSET
            - SYSTEM_CONTROL_CURSOR_PRESENTED_SOURCE_RECT_OFFSET,
        )
        payload.reserve(
            label="cursor resource transition state",
            offset=SYSTEM_CONTROL_CURSOR_RESOURCE_DRAWABLE_OFFSET,
            size=SYSTEM_CONTROL_CURSOR_RESOURCE_STATE_END_OFFSET
            - SYSTEM_CONTROL_CURSOR_RESOURCE_DRAWABLE_OFFSET,
        )

    def emit_primitives(
        self,
        system_payload: SegmentPayloadBuilder,
        control_payload: SegmentPayloadBuilder,
        *,
        system_va: int,
        control_va: int,
    ) -> CursorRuntimeExports:
        """Compile and place cursor transforms that have no overlay dependency."""
        emit_history_adapter(profile=self.profile, payload=control_payload, control_va=control_va)
        hotspot_va = control_va + 0x3A50
        control_payload.place(
            label="cursor hotspot geometry",
            offset=0x3A50,
            payload=self.build_cursor_hotspot_adjustment(wrapper_va=hotspot_va),
            limit=0x3B00,
        )
        exports = CursorRuntimeExports(
            capacity_wrapper_va=control_va + self._off_control_cursor_capacity_wrapper,
            scope_wrapper_va=system_va + self._off_cursor_scope_wrapper,
            prep_wrapper_va=control_va + self._off_control_cursor_prep_wrapper,
            final_wrapper_va=control_va + self._off_control_cursor_final_wrapper,
            manager_draw_wrapper_va=(control_va + self._off_control_cursor_manager_draw_wrapper),
            bounds_wrapper_va=system_va + self._off_cursor_bounds_wrapper,
            surface_classifier_va=control_va + self._off_control_cursor_surface_classifier,
            resource_rebuild_wrapper_va=(
                control_va + self._off_control_cursor_resource_rebuild_wrapper
            ),
        )
        scope = self.build_cursor_scope_wrapper(
            wrapper_va=exports.scope_wrapper_va,
            cursor_active_va=system_va + self._off_cursor_active,
            hotspot_va=hotspot_va,
        )
        bounds = self.build_cursor_bounds_wrapper(
            wrapper_va=exports.bounds_wrapper_va, hotspot_va=hotspot_va
        )
        capacity = self.build_cursor_capacity_wrapper(
            wrapper_va=exports.capacity_wrapper_va,
            cursor_state_va=control_va + self._off_control_cursor_state,
        )
        prep = self.build_cursor_prep_wrapper(
            wrapper_va=exports.prep_wrapper_va,
            cursor_state_va=control_va + self._off_control_cursor_state,
            cursor_active_va=system_va + self._off_cursor_active,
            sidney_root_ptr_va=self.symbols.va(
                SIDNEY_PRESENTATION_SEGMENT.logical_name,
                self._sidney_root_ptr_offset,
            ),
            hotspot_va=hotspot_va,
        )
        final = self.build_cursor_final_wrapper(
            blend_wrapper_va=self.symbols.va(CURSOR_BLEND_SEGMENT.logical_name, BLEND_ENTRY),
            wrapper_va=exports.final_wrapper_va,
            cursor_transform_count_va=system_va + self._off_cursor_transform_count,
            cursor_state_va=control_va + self._off_control_cursor_state,
            density_probe_va=self.symbols.va(
                BINOCULAR_SEGMENT.logical_name, CURSOR_DENSITY_PROBE_OFFSET
            ),
            cursor_presented_source_rect_va=(
                control_va + SYSTEM_CONTROL_CURSOR_PRESENTED_SOURCE_RECT_OFFSET
            ),
            cursor_display_blt_count_va=(
                control_va + SYSTEM_CONTROL_CURSOR_DISPLAY_BLT_COUNT_OFFSET
            ),
            cursor_display_blt_result_va=(
                control_va + SYSTEM_CONTROL_CURSOR_DISPLAY_BLT_RESULT_OFFSET
            ),
        )
        manager = self.build_cursor_manager_draw_wrapper(
            wrapper_va=exports.manager_draw_wrapper_va,
            cursor_state_va=control_va + self._off_control_cursor_state,
            sidney_active_depth_va=self.symbols.va(
                SIDNEY_PRESENTATION_SEGMENT.logical_name,
                self._sidney_active_depth_offset,
            ),
        )
        classifier = self.build_cursor_surface_classifier(
            wrapper_va=exports.surface_classifier_va,
            cursor_state_va=control_va + self._off_control_cursor_state,
            trace_va=control_va + self._off_cursor_classifier_trace,
        )
        resource_rebuild = self.build_cursor_resource_rebuild_wrapper(
            wrapper_va=exports.resource_rebuild_wrapper_va,
            drawable_va=control_va + SYSTEM_CONTROL_CURSOR_RESOURCE_DRAWABLE_OFFSET,
            frame_va=control_va + SYSTEM_CONTROL_CURSOR_RESOURCE_FRAME_OFFSET,
            valid_va=control_va + SYSTEM_CONTROL_CURSOR_RESOURCE_VALID_OFFSET,
            invalidation_count_va=(
                control_va + SYSTEM_CONTROL_CURSOR_RESOURCE_INVALIDATION_COUNT_OFFSET
            ),
            room_root_va=control_va + SYSTEM_CONTROL_CURSOR_RESOURCE_ROOM_ROOT_OFFSET,
        )
        for label, offset, code, limit in (
            (
                "cursor scope",
                self._off_cursor_scope_wrapper,
                scope,
                self._off_cursor_bounds_wrapper,
            ),
            (
                "cursor bounds",
                self._off_cursor_bounds_wrapper,
                bounds,
                self._off_loadsave_root_draw_wrapper,
            ),
        ):
            system_payload.place(label=label, offset=offset, payload=code, limit=limit)
        for label, offset, code, limit in (
            (
                "cursor capacity",
                self._off_control_cursor_capacity_wrapper,
                capacity,
                self._off_control_cursor_capacity_limit,
            ),
            (
                "cursor preparation",
                self._off_control_cursor_prep_wrapper,
                prep,
                self._off_control_cursor_prep_limit,
            ),
            (
                "cursor final stretch",
                self._off_control_cursor_final_wrapper,
                final,
                self._off_control_cursor_final_limit,
            ),
            (
                "cursor manager transaction",
                self._off_control_cursor_manager_draw_wrapper,
                manager,
                self._off_control_cursor_manager_draw_limit,
            ),
            (
                "cursor surface classifier",
                self._off_control_cursor_surface_classifier,
                classifier,
                self._off_control_cursor_surface_classifier_limit,
            ),
            (
                "cursor resource transition invalidator",
                self._off_control_cursor_resource_rebuild_wrapper,
                resource_rebuild,
                self._off_control_cursor_resource_rebuild_limit,
            ),
        ):
            control_payload.place(label=label, offset=offset, payload=code, limit=limit)
        return exports

    def emit_frame_presenter(
        self,
        payload: SegmentPayloadBuilder,
        *,
        control_va: int,
        loadsave_va: int,
        action_lifetime_helper_va: int,
        tooltip_frame_presenter_va: int,
        loadsave_frame_presenter_va: int,
        closeup_frame_presenter_va: int,
    ) -> int:
        """Compile the final cursor/page owner after overlay exports are known."""
        wrapper_va = control_va + self._off_control_cursor_frame_presenter
        code = self.build_cursor_frame_presenter(
            wrapper_va=wrapper_va,
            action_lifetime_helper_va=action_lifetime_helper_va,
            cursor_state_va=control_va + self._off_control_cursor_state,
            caption_frame_presenter_va=self.symbols.va(
                CAPTION_SEGMENT.logical_name,
                CAPTION_PRESENTER_OFFSET,
            ),
            tooltip_frame_presenter_va=tooltip_frame_presenter_va,
            loadsave_frame_presenter_va=loadsave_frame_presenter_va,
            room_presentation_active_va=self.transition_abi.room_presentation_active_va,
            fixed_canvas_owner_va=self.room_rendering_abi.fixed_canvas_owner_va,
            loadsave_root_ptr_va=loadsave_va + self._off_loadsave_layout_root,
            closeup_frame_presenter_va=closeup_frame_presenter_va,
            closeup_destination_handle_va=(control_va + SYSTEM_CONTROL_CLOSEUP_DEST_HANDLE_OFFSET),
            confirm_quit_cursor_suspended_va=(
                control_va + SYSTEM_CONTROL_CONFIRM_QUIT_CURSOR_SUSPENDED_OFFSET
            ),
        )
        payload.place(
            label="staged-room cursor frame presenter",
            offset=self._off_control_cursor_frame_presenter,
            payload=code,
            limit=self._off_control_cursor_frame_presenter_limit,
        )
        return wrapper_va

    def plan_hooks(
        self,
        plan: ExecutableMutationPlan,
        *,
        frame_presenter_va: int,
        capacity_wrapper_va: int,
        scope_wrapper_va: int,
        prep_wrapper_va: int,
        final_wrapper_va: int,
        manager_draw_wrapper_va: int,
        bounds_wrapper_va: int,
        resource_rebuild_wrapper_va: int,
    ) -> None:
        """Own every native redirect required by the cursor transaction."""
        site = self.profile.site("cursor.restore_history_query")
        plan.branch(
            label="cursor retained-surface background history",
            opcode=BranchOpcode.CALL,
            site_va=site.va,
            expected=site.original,
            target_va=self.symbols.va(SYSTEM_CONTROL_SEGMENT.logical_name, HISTORY_OFFSET),
            size=len(site.original),
        )
        plan.pointer(
            label="cursor pre-Flip presenter",
            slot_va=self.transition_abi.pre_flip_presenter_slot_va,
            expected=0,
            target_va=frame_presenter_va,
        )
        for label, site_va, original in (
            (
                "cursor platform initialize capacity",
                self._cursor_platform_initialize_call_site_va,
                self._cursor_platform_initialize_call_original,
            ),
            (
                "cursor platform restore capacity",
                self._cursor_platform_restore_call_site_va,
                self._cursor_platform_restore_call_original,
            ),
        ):
            plan.branch(
                label=label,
                opcode=BranchOpcode.CALL,
                site_va=site_va,
                expected=original,
                target_va=capacity_wrapper_va,
                size=len(original),
            )
        plan.branch(
            label="cursor draw scope",
            opcode=BranchOpcode.JUMP,
            site_va=self._cursor_draw_scope_site_va,
            expected=self._cursor_draw_scope_original,
            target_va=scope_wrapper_va,
            size=len(self._cursor_draw_scope_original),
        )
        plan.branch(
            label="cursor drawable preparation",
            opcode=BranchOpcode.CALL,
            site_va=self._cursor_drawable_blt_call_site_va,
            expected=self._cursor_drawable_blt_call_original,
            target_va=prep_wrapper_va,
            size=len(self._cursor_drawable_blt_call_original),
        )
        plan.branch(
            label="cursor final blit",
            opcode=BranchOpcode.CALL,
            site_va=self._cursor_resolved_blt_call_site_va,
            expected=self._cursor_resolved_blt_call_original,
            target_va=final_wrapper_va,
            size=len(self._cursor_resolved_blt_call_original),
        )
        plan.pointer(
            label="cursor-manager draw vtable",
            slot_va=self._cursor_manager_draw_slot_va,
            expected=self._cursor_manager_draw_slot_original,
            target_va=manager_draw_wrapper_va,
        )
        # Sprite extent and save-under/damage bounds must be transformed by
        # the same owner or the scaled cursor intermittently restores itself.
        plan.branch(
            label="cursor dirty/save-under bounds",
            opcode=BranchOpcode.JUMP,
            site_va=self._cursor_bounds_hook_site_va,
            expected=self._cursor_bounds_hook_original,
            target_va=bounds_wrapper_va,
            size=len(self._cursor_bounds_hook_original),
        )
        plan.branch(
            label="cursor resource transition invalidation",
            opcode=BranchOpcode.CALL,
            site_va=self._cursor_frame_begin_call_site_va,
            expected=self._cursor_frame_begin_call_original,
            target_va=resource_rebuild_wrapper_va,
            size=len(self._cursor_frame_begin_call_original),
        )

    def build_cursor_hotspot_adjustment(self, *, wrapper_va: int) -> bytes:
        """Correct a native hotspot-subtracted POINT without changing input or assets.

        EAX is the exact CursorManager; EDX points to the local destination.
        All registers/flags survive. Draw and save-under bounds must subtract
        the same scaled hotspot. Leave the manager's authored values intact so
        cursor changes and live resolution changes cannot compound the scale.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x9c\x60\x89\xc6\x89\xd7")
        code.raw(b"\x8b\x2d" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\x81\xfd\x00\x03\x00\x00")
        code.jump_if(Condition.LESS_OR_EQUAL, "done")
        for source, destination in ((0x28, 0), (0x2C, 4)):
            # Symmetric nearest-integer rounding, including negative hotspots.
            code.raw(b"\x8b\x46" + bytes([source]) + b"\x0f\xaf\xc5\x99\x89\xd3")
            code.raw(b"\x31\xd0\x29\xd0\x05\x80\x01\x00\x00\x99")
            code.raw(b"\xb9\x00\x03\x00\x00\xf7\xf9\x31\xd8\x29\xd8")
            code.raw(b"\x2b\x46" + bytes([source]))
            code.raw(b"\x29\x47" + bytes([destination]))
        code.label("done")
        code.raw(b"\x61\x9d\xc3")
        return code.build(maximum_size=0xB0)

    def build_cursor_scope_wrapper(
        self,
        *,
        wrapper_va: int,
        cursor_active_va: int,
        hotspot_va: int,
    ) -> bytes:
        """Scope the cursor drawable's virtual Draw call."""
        code = X86Emitter(base_va=wrapper_va)
        # Replay the displaced point write and vtable load. The cursor manager
        # has already completed its damage/UI repaint work at this site, so the
        # active flag cannot leak into button, font, or scrollbar transfers.
        code += b"\x89\x45\xe8\x60\x89\xf0\x8d\x55\xe8"
        code.call_absolute(hotspot_va)
        code += b"\x61\x8b\x01"
        # Publish the concrete drawable, not just a Boolean scope. The shared
        # blitter can then require the destination's native extent to match
        # this cursor frame exactly and reject nested damaged-UI transfers.
        code += b"\x89\x0d" + struct.pack("<I", cursor_active_va)
        code += b"\xff\x50\x18"
        code += b"\xc7\x05" + struct.pack("<I", cursor_active_va) + b"\x00\x00\x00\x00"
        code.jump_absolute(self._cursor_draw_scope_continue_va)
        return code.build()

    def build_cursor_resource_rebuild_wrapper(
        self,
        *,
        wrapper_va: int,
        drawable_va: int,
        frame_va: int,
        valid_va: int,
        invalidation_count_va: int,
        room_root_va: int,
    ) -> bytes:
        """Invalidate room histories when the contextual cursor image changes."""
        # This call site runs immediately before the room chooses and consumes
        # its retained DirectDraw history. Preserve CursorManager's complete
        # native update first; it resolves both contextual drawable and frame.
        code = X86Emitter(base_va=wrapper_va)
        code.call_absolute(self.profile.address("cursor.frame_begin"))
        code.raw(b"\x9c\x60")
        code.raw(b"\x81\x3d" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(struct.pack("<I", AUTHORED_FRAME_HEIGHT))
        code.jump_if(Condition.BELOW_OR_EQUAL, "done")

        # The hook belongs to the ordinary room loop, but keep an explicit
        # concrete-layer proof so fixed interfaces never inherit this policy.
        code.call_absolute(self.profile.address("ui.current_layer"))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(
            b"\x81\x38" + struct.pack("<I", self.profile.address("transition.room_layer_vtable"))
        )
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\xa3" + struct.pack("<I", room_root_va))

        # Resolve the manager only after its native update has completed:
        # EngineLoop -> scene owner -> input dispatcher -> CursorManager.
        code.raw(b"\x8b\x1d" + struct.pack("<I", self.profile.address("engine.loop")))
        code.raw(b"\x85\xdb")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x83\x44\x04\x00\x00\x85\xc0")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x40\x44\x85\xc0")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x70\x08\x85\xf6")
        code.jump_if(Condition.EQUAL, "done")

        # Position changes are already bounded by native damage. Only a new
        # drawable or animation frame changes the footprint/opaque mask and
        # requires every retained room page to retire the preceding raster.
        code.raw(b"\x83\x3d" + struct.pack("<I", valid_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "resource_changed")
        code.raw(b"\x8b\x46\x70")
        code.raw(b"\x3b\x05" + struct.pack("<I", drawable_va))
        code.jump_if(Condition.NOT_EQUAL, "resource_changed")
        code.raw(b"\x8b\x46\x74")
        code.raw(b"\x3b\x05" + struct.pack("<I", frame_va))
        code.jump_if(Condition.EQUAL, "done")

        code.label("resource_changed")
        code.raw(b"\x8b\x46\x70")
        code.raw(b"\xa3" + struct.pack("<I", drawable_va))
        code.raw(b"\x8b\x46\x74")
        code.raw(b"\xa3" + struct.pack("<I", frame_va))
        code.raw(b"\xc7\x05" + struct.pack("<I", valid_va) + b"\x01\x00\x00\x00")
        code.raw(b"\x8b\xcb")
        code.call_absolute(self.profile.address("transition.invalidate_all_damage"))
        code.raw(b"\xff\x05" + struct.pack("<I", invalidation_count_va))

        code.label("done")
        code.raw(b"\x61\x9d\xc3")
        return code.build()

    def build_cursor_bounds_wrapper(
        self,
        *,
        wrapper_va: int,
        hotspot_va: int,
    ) -> bytes:
        """Scale and publish the cursor's exact physical save-under bounds."""
        # EDI points one RECT past the copied output at this hook. Recompute
        # right/bottom from the hotspot-corrected left/top so background save and
        # restore region covers the cursor's stretched final destination.
        code = X86Emitter(base_va=wrapper_va)
        code += b"\x60"
        # EBX is manager+0x30 at the native copied-RECT boundary.
        code += b"\x8d\x43\xd0\x8d\x57\xf0"
        code.call_absolute(hotspot_va)
        # Shift the far edges by the same delta before measuring native size.
        # The copied native width/height are still in the local source RECT.
        code += b"\x8b\x45\xe8\x03\x47\xf0\x89\x47\xf8"
        code += b"\x8b\x45\xec\x03\x47\xf4\x89\x47\xfc"
        code += b"\x8b\x5f\xf8\x2b\x5f\xf0"  # native width
        code += b"\x8b\x47\xfc\x2b\x47\xf4"  # native height
        code += b"\x8b\x0d" + struct.pack("<I", self._physical_width_va + 4)
        code += b"\x0f\xaf\xd9\x81\xc3\xff\x02\x00\x00"
        code += b"\x0f\xaf\xc1\x05\xff\x02\x00\x00"
        code += b"\x99\xb9\x00\x03\x00\x00\xf7\xf9\x8b\xf0"
        code += b"\x8b\xc3\x99\xb9\x00\x03\x00\x00\xf7\xf9"
        code += b"\x03\x47\xf0\x83\xc0\x02\x89\x47\xf8"
        code += b"\x03\x77\xf4\x83\xc6\x02\x89\x77\xfc"
        code += b"\x61" + self._cursor_bounds_hook_original
        code.jump_absolute(self._cursor_bounds_hook_back_va)
        return code.build()

    def build_cursor_prep_wrapper(
        self,
        *,
        wrapper_va: int,
        cursor_state_va: int,
        cursor_active_va: int,
        sidney_root_ptr_va: int,
        hotspot_va: int,
    ) -> bytes:
        """Scope one exact cursor bitmap submission and retain its geometry."""
        # This replaces the one call from BitmapDrawable::Draw to GK3's
        # clipped-copy helper.  CursorManager can queue a drawable submission
        # after its outer Draw call has returned, so the manager's transient
        # scope alone is not a complete ownership proof.  Resolve the manager's
        # current BitmapDrawable and compare it with EBX, the concrete object
        # executing this call.  The exact identity remains valid for normal,
        # clipped, and queued copies without classifying unrelated atlas-sized
        # UI resources.
        #
        # This wrapper calls (rather than tail-jumps to) the native helper so
        # state+76 remains set for precisely that helper's complete call tree,
        # including the final resolved-surface hook, and is cleared before the
        # caller resumes.  After PUSHAD, arg3 is the destination POINT* at
        # +0x2c and arg4 is the complete source RECT* at +0x30.
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x60")
        code.raw(b"\xc7\x05" + struct.pack("<I", cursor_state_va + 76) + b"\x00\x00\x00\x00")
        # Startup can draw the cursor before EngineLoop publishes a scene
        # input dispatcher. The synchronous manager call already publishes
        # the exact drawable, so it does not need that later lifetime chain.
        # Its POINT was prepared by the manager wrapper (including SIDNEY).
        code.raw(b"\x3b\x1d" + struct.pack("<I", cursor_active_va))
        code.jump_if(Condition.EQUAL, "point_ready")
        code.raw(b"\xa1" + struct.pack("<I", self.profile.address("engine.loop")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "record_done")
        code.raw(b"\x8b\x80\x44\x04\x00\x00\x85\xc0")
        code.jump_if(Condition.EQUAL, "record_done")
        code.raw(b"\x8b\x40\x44\x85\xc0")
        code.jump_if(Condition.EQUAL, "record_done")
        code.raw(b"\x8b\x40\x08\x85\xc0")
        code.jump_if(Condition.EQUAL, "record_done")
        code.raw(b"\x8b\xd0")  # retain the validated CursorManager
        code.raw(b"\x8b\x40\x70\x3b\xc3")
        code.jump_if(Condition.NOT_EQUAL, "record_done")

        code.raw(b"\x8b\x74\x24\x2c\x85\xf6")
        code.jump_if(Condition.EQUAL, "record_done")

        # A retained SIDNEY page can invoke BitmapDrawable::Draw directly,
        # after CursorManager's outer Draw has returned. Canonicalize at this
        # exact drawable-owned boundary as well: EDX is the validated manager
        # and ESI is the caller-owned destination POINT. This heals the queued
        # record before both its private composition and framebuffer copies.
        code.raw(b"\x81\x3d" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(struct.pack("<I", AUTHORED_FRAME_HEIGHT))
        code.jump_if(Condition.BELOW_OR_EQUAL, "point_ready")
        # Root lifetime, rather than recursive Draw depth, also covers work
        # queued by the retained DirectDraw pages after that traversal returns.
        code.raw(b"\x83\x3d" + struct.pack("<I", sidney_root_ptr_va) + b"\x00")
        code.jump_short_if(Condition.EQUAL, "point_ready")
        code.raw(b"\x8b\x82\xb4\x01\x00\x00\x2b\x42\x28\x89\x06")
        code.raw(b"\x8b\x82\xb8\x01\x00\x00\x2b\x42\x2c\x89\x46\x04")
        code.raw(b"\x89\xd0\x89\xf2")
        code.call_absolute(hotspot_va)
        code.raw(b"\xff\x05" + struct.pack("<I", cursor_state_va + 84))
        code.label("point_ready")

        code.raw(b"\x8b\x74\x24\x2c\x85\xf6")
        code.jump_short_if(Condition.EQUAL, "record_done")
        code.raw(b"\xbf" + struct.pack("<I", cursor_state_va))
        code.raw(b"\xa5\xa5")
        code.raw(b"\x8b\x74\x24\x30\x85\xf6")
        code.jump_short_if(Condition.EQUAL, "record_done")

        code.raw(b"\xbf" + struct.pack("<I", cursor_state_va + 8))
        code.raw(b"\xb9\x04\x00\x00\x00\xf3\xa5")

        # Publish ownership only after both geometry pointers have been
        # validated and copied. A malformed native call must not make the
        # final hook consume stale coordinates under a true scope flag.
        code.raw(b"\x89\x1d" + struct.pack("<I", cursor_state_va + 152))
        code.raw(b"\xc7\x05" + struct.pack("<I", cursor_state_va + 76) + b"\x01\x00\x00\x00")
        code.label("record_done")
        code.raw(b"\x61")
        # Re-push the six original arguments in reverse order.  Each PUSH
        # shifts the next original argument to the same ESP+0x18 address.
        code.raw(b"\xff\x74\x24\x18" * 6)
        code.call_absolute(self._cursor_drawable_blt_va)
        code.raw(b"\xc7\x05" + struct.pack("<I", cursor_state_va + 76) + b"\x00\x00\x00\x00")
        code.raw(b"\xc2\x18\x00")
        return code.build()

    def build_cursor_capacity_wrapper(
        self,
        *,
        wrapper_va: int,
        cursor_state_va: int,
    ) -> bytes:
        """Give every native cursor allocation a scaled private capacity.

        Both patched call sites invoke the same two-argument thiscall:
        ``Initialize(const POINT* logical_max, int update_interval)``. Copy the
        logical point to this wrapper's stack, scale the copy uniformly by the
        selected engine height, and pass it to the pristine allocator. The
        CursorManager field remains logical (and therefore save-compatible),
        while constructor and post-deserialization allocations both receive
        the physical capacity required by the final cursor compositor. Publish
        the resulting native backing extent from this authoritative allocation
        boundary. Resolve and publish both resulting private surface wrappers
        there as well, before their first copy can be mistaken for fixed UI.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x55\x8b\xec\x83\xec\x08\x53\x56\x57")
        code.raw(b"\x8b\xf9")  # retain the native platform object
        code.raw(b"\x8b\x75\x08\x85\xf6")
        code.jump_if(Condition.EQUAL, "native_null")

        # Materialize an independent POINT so the serialized manager field is
        # never overwritten with a physical size and cannot be double-scaled
        # when a save created under this patch is restored later.
        code.raw(b"\x8b\x06\x89\x45\xf8\x8b\x46\x04\x89\x45\xfc")
        code.raw(b"\xa1" + struct.pack("<I", self.profile.address("engine.loop")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "native_copy")
        code.raw(b"\x8b\x58\x34")
        code.raw(b"\x81\xfb\x00\x03\x00\x00")
        code.jump_if(Condition.BELOW_OR_EQUAL, "native_copy")

        for offset in (-8, -4):
            # Values are small positive cursor dimensions, so the low 32-bit
            # product cannot overflow in any DirectDraw mode GK3 can create.
            code.raw(b"\x8b\x45" + bytes([offset & 0xFF]))
            code.raw(b"\x0f\xaf\xc3\x05\xff\x02\x00\x00")
            code.raw(b"\x31\xd2\xb9\x00\x03\x00\x00\xf7\xf1")
            code.raw(b"\x89\x45" + bytes([offset & 0xFF]))

        code.label("native_copy")
        # Reinitialization releases the old platform resources before creating
        # replacements. Withdraw their identities first so no nested transfer
        # can classify a recycled wrapper address as the current cursor owner.
        code.raw(b"\x31\xc0")
        code.raw(b"\xa3" + struct.pack("<I", cursor_state_va + 88))
        code.raw(b"\xa3" + struct.pack("<I", cursor_state_va + 148))
        code.raw(b"\xff\x75\x0c\x8d\x45\xf8\x50\x8b\xcf")
        code.call_absolute(self._cursor_platform_initialize_va)

        # CursorPlatform stores the encoded requested-capacity and doubled-
        # capacity bitmap handles at +4/+8. The pristine initializer has just
        # created and resolved both resources, so resolve the same handles
        # through GK3's bitmap table and publish their exact surface wrappers.
        # This authoritative boundary eliminates first-use size/geometry
        # inference and makes the very first cursor save-under transaction safe.
        for platform_offset, state_offset, done_label in (
            (4, 148, "requested_surface_done"),
            (8, 88, "doubled_surface_done"),
        ):
            code.raw(b"\x8b\x47" + bytes([platform_offset]) + b"\x85\xc0")
            code.jump_short_if(Condition.EQUAL, done_label)
            code.raw(b"\x50")
            code.raw(b"\x8b\x0d" + struct.pack("<I", self.profile.address("resource.manager")))
            code.call_absolute(self.profile.address("bitmap.resolve_resource"))
            code.raw(b"\x85\xc0")
            code.jump_short_if(Condition.EQUAL, done_label)
            code.raw(b"\x8b\x40\x30")
            code.raw(b"\xa3" + struct.pack("<I", cursor_state_va + state_offset))
            code.label(done_label)
        code.jump_short("done")

        code.label("native_null")
        code.raw(b"\xff\x75\x0c\x6a\x00\x8b\xcf")
        code.call_absolute(self._cursor_platform_initialize_va)

        code.label("done")
        code.raw(b"\x5f\x5e\x5b\xc9\xc2\x08\x00")
        return code.build()

    def build_cursor_final_wrapper(
        self,
        *,
        wrapper_va: int,
        cursor_transform_count_va: int,
        cursor_state_va: int,
        density_probe_va: int,
        blend_wrapper_va: int,
        cursor_presented_source_rect_va: int,
        cursor_display_blt_count_va: int,
        cursor_display_blt_result_va: int,
    ) -> bytes:
        """Scale exact cursor transfers at GK3's resolved 2D boundary.

        The concrete cursor-drawable scope selects only cursor fragments, which
        use native stretch or software blending with their clipping, color key
        and opacity options intact. Every unrelated 2D transfer tail-enters the
        pristine implementation unchanged.
        """
        # This wrapper replaces the final call inside FUN_0054D330, after GK3
        # has resolved both bitmap resources to the low-level surface wrappers
        # accepted by its native blitters. Its normal target takes five stack
        # arguments (source, X, Y, source RECT, options) and performs BltFast.
        # The cursor-only branch dispatches RECT/RECT transfers to native
        # stretch or a native-effect sampling adapter. This preserves color-key, retry,
        # locking, error, and boolean-return semantics rather than duplicating
        # DirectDraw policy in injected code. Crucially, CursorManager first
        # composes the sprite into a private surface whose capacity is scaled
        # with the display, and only then copies that surface to the
        # framebuffer. Stretching the exact cursor bitmap here makes that
        # native transaction carry a scaled sprite;
        # redrawing the cursor after a screen traversal produced a second copy
        # at the previous mouse position. Every non-cursor call tail-enters the
        # original final BltFast implementation unchanged.
        #
        # Clipped calls carry a source sub-rectangle and an adjusted point.
        # Derive both destination edges from the complete source origin saved
        # by _build_cursor_prep_wrapper. Each output edge is the original point
        # plus its source-relative offset multiplied by physical height / 768.
        # Adjacent fragments therefore meet exactly instead of independently
        # growing each fragment about its own near edge.
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x55\x8b\xec\x83\xec\x08\x53\x56\x57\x51")
        # Reserve real local DWORDs rather than reusing the saved-ECX slot.
        # GK3's surrounding helper happens to retain ECX across this internal
        # call even though the platform ABI marks it volatile. Preserving that
        # native register contract prevents a pre-title cursor submission from
        # returning through a corrupted owner. The local survives the native
        # stretch and distinguishes a durable framebuffer transfer from the
        # cursor's private composition work.
        code.raw(b"\xc7\x45\xfc\x00\x00\x00\x00")

        code.raw(b"\x8b\x1d" + struct.pack("<I", self._physical_width_va + 4))
        # FUN_005343E0 pushes the resolved call as
        #   (source_wrapper, destination_POINT, source_RECT, options).
        # The RECT is therefore the third stack argument at EBP+0x10; EBP+0x0c
        # is only the two-dword destination point and must never be sampled as
        # four rectangle edges.
        # At this final boundary the source RECT is argument four.
        code.raw(b"\x8b\x75\x14\x85\xf6")
        code.jump_if(Condition.EQUAL, "native")

        # Require the exact live-drawable scope established at the caller of
        # BitmapDrawable's native helper. It encloses synchronous and queued
        # submissions while excluding every other bitmap by concrete object
        # identity. Earlier revisions retained CursorManager timing and source-
        # surface fallbacks; both are redundant now and can misclassify nested
        # UI/cache transfers, so there is deliberately no heuristic fallback.
        code.raw(b"\x83\x3d" + struct.pack("<I", cursor_state_va + 76) + b"\x00")
        code.jump_if(Condition.EQUAL, "native")
        # The preparation hook records geometry only for the manager's exact
        # published cursor object. Require this final call's fragment to remain
        # inside that complete frame as a second, geometry-level invariant.
        for offset, complete_offset, condition in (
            (0, 8, Condition.LESS),
            (4, 12, Condition.LESS),
            (8, 16, Condition.GREATER),
            (12, 20, Condition.GREATER),
        ):
            code.raw(b"\x8b\x46" + bytes([offset]))
            code.raw(b"\x3b\x05" + struct.pack("<I", cursor_state_va + complete_offset))
            code.jump_if(condition, "native")
        # The destination may be either the physical framebuffer or the cursor
        # manager's private save-under surface. Both are part of the same
        # cursor-owned composition transaction and need the same scaled bitmap.
        # Do not classify by surface dimensions: exact drawable identity plus
        # this scoped source frame is the stronger and resolution-independent
        # ownership proof.
        code.raw(b"\x8b\xf9")

        # Pair the manager's pending destination handle with the high-level
        # wrapper for the concrete physical back page at the only boundary
        # where exact cursor ownership and both resolved surfaces are proven.
        # Publish the handle last so the pre-Flip reader never observes it
        # before the diagnostic wrapper belongs to the same transaction.
        code.raw(b"\xa1" + struct.pack("<I", self.profile.address("transition.back_surface_ptr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "cursor_destination_ready")
        code.raw(b"\x3b\x47\x2c")
        code.jump_if(Condition.NOT_EQUAL, "private_cursor_destination")
        code.raw(b"\x89\x3d" + struct.pack("<I", cursor_state_va + 136))
        code.raw(b"\xa1" + struct.pack("<I", cursor_state_va + 128))
        code.raw(b"\xa3" + struct.pack("<I", cursor_state_va + 132))
        code.jump_short("cursor_destination_ready")

        # The exact drawable scope admits only two resolved destinations: the
        # live back page above and CursorManager's private composition owner.
        # Learn the latter from concrete transaction ownership. Its dimensions
        # deliberately grow with output height, so comparing them with the
        # stock 128x128 capacity both fails in modern modes and lets its delayed
        # save-under restore fall through an unrelated interface affine.
        code.label("private_cursor_destination")
        code.raw(b"\x89\x3d" + struct.pack("<I", cursor_state_va + 80))
        code.label("cursor_destination_ready")

        # Destination ownership is independent of scale. Publish the exact
        # physical handle/wrapper pair above even at the authored height, then
        # retain stock BltFast rasterization for native sources there. Dense
        # sources still need their source-coordinate adapter at that height.
        # The Load/Save pre-Flip
        # compositor needs this identity to redraw the native-size cursor over
        # its cursor-free full-page cache; previously the early height return
        # left that final z-order owner with a zero destination and made cursor
        # movement invisible throughout the 1024 Restore browser.
        # Source density is independent of display scale. Resolve only the
        # exact live cursor's approved resource; dimensions alone are not proof.
        code.raw(b"\xc7\x45\xf8\x01\x00\x00\x00")
        code.raw(b"\xa1" + struct.pack("<I", cursor_state_va + 152))
        code.raw(b"\x8b\x55\x08")
        code.call_absolute(density_probe_va)
        code.jump_if(Condition.ABOVE_OR_EQUAL, "cursor_density_ready")
        code.raw(b"\xc7\x45\xf8\x04\x00\x00\x00")
        code.jump("render_cursor")
        code.label("cursor_density_ready")
        code.raw(b"\x81\xfb" + struct.pack("<I", AUTHORED_FRAME_HEIGHT))
        code.jump_if(Condition.BELOW_OR_EQUAL, "native")
        code.label("render_cursor")
        # Low-resolution modes keep native cursor metrics and hotspots. Dense
        # pixels must not introduce a new downscale in that original path.
        code.raw(b"\x81\xfb" + struct.pack("<I", AUTHORED_FRAME_HEIGHT))
        code.jump_short_if(Condition.ABOVE_OR_EQUAL, "cursor_scale_ready")
        code.raw(b"\xbb" + struct.pack("<I", AUTHORED_FRAME_HEIGHT))
        code.label("cursor_scale_ready")

        # RECT alternates X/Y. The saved point is at state+0, the complete
        # source frame at state+8, the latest physical destination at state+24,
        # per-call fragment scratch at state+40, and its source frame at
        # state+56. The physical diagnostic pair is published atomically below.
        code.raw(b"\xb9\x00\x03\x00\x00")
        for output_offset, source_offset, axis_offset in (
            (40, 0, 0),
            (44, 4, 4),
            (48, 8, 0),
            (52, 12, 4),
        ):
            code.raw(b"\x8b\x46" + bytes([source_offset]))
            code.raw(b"\x2b\x05" + struct.pack("<I", cursor_state_va + 8 + axis_offset))
            # Round to the nearest reference-space edge, matching the bounds
            # helper and avoiding a systematic undersize at non-integer scale.
            code.raw(b"\x0f\xaf\xc3\x05\x80\x01\x00\x00\x99\xf7\xf9")
            code.raw(b"\x03\x05" + struct.pack("<I", cursor_state_va + axis_offset))
            code.raw(b"\xa3" + struct.pack("<I", cursor_state_va + output_offset))

        # BltFast accepts a negative destination point and clips it internally,
        # but the sibling RECT/RECT primitive rejects any destination edge
        # outside its surface with DDERR_INVALIDRECT.  The cursor hotspot makes
        # a perfectly ordinary pointer at the top or left screen edge negative,
        # so replacing BltFast with stretch without translating its clipping
        # contract produces an error on every frame.  Carry an independent
        # source scratch rectangle and crop it by the inverse height affine as
        # each physical destination edge is clamped.  This preserves scale and
        # the visible part of the cursor rather than moving or squashing it.
        for offset in (0, 4, 8, 12):
            code.raw(b"\x8b\x46" + bytes([offset]))
            code.raw(b"\xa3" + struct.pack("<I", cursor_state_va + 56 + offset))

        for axis, near_offset, far_offset, surface_size_offset in (
            ("x", 40, 48, 0x38),
            ("y", 44, 52, 0x3C),
        ):
            # Crop the source near edge by the ceiling of the inverse-scaled
            # destination overhang.
            code.raw(b"\xa1" + struct.pack("<I", cursor_state_va + near_offset))
            code.raw(b"\x85\xc0")
            code.jump_if(Condition.GREATER_OR_EQUAL, f"cursor_{axis}_near_inside")
            code.raw(b"\xf7\xd8\x69\xc0" + struct.pack("<I", AUTHORED_FRAME_HEIGHT))
            code.raw(b"\x03\xc3\x48\x99\xf7\xfb")
            code.raw(b"\x01\x05" + struct.pack("<I", cursor_state_va + 56 + near_offset - 40))
            code.raw(b"\x31\xc0\xa3" + struct.pack("<I", cursor_state_va + near_offset))
            code.label(f"cursor_{axis}_near_inside")

            # Crop the source far edge by the ceiling of the inverse-scaled
            # destination overhang.
            code.raw(b"\xa1" + struct.pack("<I", cursor_state_va + far_offset))
            code.raw(b"\x3b\x47" + bytes([surface_size_offset]))
            code.jump_if(Condition.LESS_OR_EQUAL, f"cursor_{axis}_far_inside")
            code.raw(b"\x2b\x47" + bytes([surface_size_offset]))
            code.raw(b"\x69\xc0" + struct.pack("<I", AUTHORED_FRAME_HEIGHT))
            code.raw(b"\x03\xc3\x48\x99\xf7\xfb")
            code.raw(b"\x29\x05" + struct.pack("<I", cursor_state_va + 56 + far_offset - 40))
            code.raw(b"\x8b\x47" + bytes([surface_size_offset]))
            code.raw(b"\xa3" + struct.pack("<I", cursor_state_va + far_offset))
            code.label(f"cursor_{axis}_far_inside")

        # A fully external fragment is a successful no-op under BltFast.  Do
        # not feed an empty rectangle to DirectDraw merely to reproduce that
        # result through an error path.
        for near_offset, far_offset in ((40, 48), (44, 52), (56, 64), (60, 68)):
            code.raw(b"\xa1" + struct.pack("<I", cursor_state_va + near_offset))
            code.raw(b"\x3b\x05" + struct.pack("<I", cursor_state_va + far_offset))
            code.jump_if(Condition.GREATER_OR_EQUAL, "cursor_empty")

        # Cursor fragments are also composed into CursorManager's small private
        # surface. Scaling that transfer is necessary, but it is not a durable
        # presentation and must not replace the last visible framebuffer
        # footprint. Identify the display wrapper by comparing its live native
        # extent with the engine's selected physical dimensions; this remains
        # resolution-agnostic and rejects every scratch surface.
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va))
        code.raw(b"\x39\x47\x38")
        code.jump_if(Condition.NOT_EQUAL, "fragment_ready")
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\x39\x47\x3c")
        code.jump_if(Condition.NOT_EQUAL, "fragment_ready")
        code.raw(b"\xc7\x45\xfc\x01\x00\x00\x00")

        # Reconstruct the complete physical frame only for a display transfer.
        # GK3 often submits clipped pieces, so waiting for a complete fragment
        # would miss real movements. PUSHAD makes the destination/source pair a
        # coherent out-of-process diagnostic snapshot.
        code.raw(b"\x60")
        for output_offset, source_offset, axis_offset in (
            (24, 0, 0),
            (28, 4, 4),
            (32, 8, 0),
            (36, 12, 4),
        ):
            code.raw(b"\xa1" + struct.pack("<I", cursor_state_va + 8 + source_offset))
            code.raw(b"\x2b\x05" + struct.pack("<I", cursor_state_va + 8 + axis_offset))
            code.raw(b"\x0f\xaf\xc3\x05\x80\x01\x00\x00\x99\xf7\xf9")
            code.raw(b"\x03\x05" + struct.pack("<I", cursor_state_va + axis_offset))
            code.raw(b"\xa3" + struct.pack("<I", cursor_state_va + output_offset))
        # +56 is per-call clipping scratch and a later private save-under copy
        # may replace it without publishing a new display destination. Retain
        # the complete source in a dedicated diagnostic record inside this
        # same PUSHAD publication as +24, so cursor-scale gates compare one
        # actual framebuffer transaction across loading/arrow handoffs.
        code.raw(b"\xbe" + struct.pack("<I", cursor_state_va + 8))
        code.raw(b"\xbf" + struct.pack("<I", cursor_presented_source_rect_va))
        code.raw(b"\xb9\x04\x00\x00\x00\xf3\xa5")
        # Retain the resolved source identity as diagnostic evidence only.
        code.raw(b"\x8b\x45\x08")
        code.raw(b"\xa3" + struct.pack("<I", cursor_state_va + 72))
        code.raw(b"\x61")
        code.label("fragment_ready")

        # Logical animation origins may be nonzero. Expand all four source
        # edges, after clipping, without changing the caller's native RECT.
        code.raw(b"\x83\x7d\xf8\x04")
        code.jump_if(Condition.NOT_EQUAL, "cursor_source_ready")
        for offset in (56, 60, 64, 68):
            code.raw(b"\xc1\x25" + struct.pack("<I", cursor_state_va + offset) + b"\x02")
        code.label("cursor_source_ready")

        # Keep the native effect options: replacing every transfer with plain
        # stretch loses the wait cursor's mask and other cursors' global opacity.
        # The dispatcher consumes four arguments and preserves native blending.
        code.raw(b"\xff\x75\x18")
        code.raw(b"\x68" + struct.pack("<I", cursor_state_va + 56))
        code.raw(b"\x68" + struct.pack("<I", cursor_state_va + 40))
        code.raw(b"\xff\x75\x08")
        code.raw(b"\x8b\xcf")
        code.call_absolute(blend_wrapper_va)
        code.raw(b"\x83\x7d\xfc\x00")
        code.jump_if(Condition.EQUAL, "transform_count")
        code.raw(b"\xa3" + struct.pack("<I", cursor_display_blt_result_va))
        code.raw(b"\xff\x05" + struct.pack("<I", cursor_display_blt_count_va))
        code.label("transform_count")
        code.raw(b"\xff\x05" + struct.pack("<I", cursor_transform_count_va))
        code.raw(b"\x59\x5f\x5e\x5b\xc9\xc2\x14\x00")

        code.label("cursor_empty")
        code.raw(b"\xb8\x01\x00\x00\x00\x59\x5f\x5e\x5b\xc9\xc2\x14\x00")

        code.label("native")
        code.raw(b"\x59\x5f\x5e\x5b\xc9")
        code.jump_absolute(self._native_mid_blt_va)
        return code.build()

    def build_loadsave_post_draw_cursor_presenter(self, *, wrapper_va: int) -> bytes:
        """Re-submit the live software cursor above a completed Load/Save draw.

        ``EAX`` is the encoded destination handle just used by the retained
        root. That root can redraw without a mouse event—most visibly while
        Restore progress advances—so GK3 does not necessarily schedule
        CursorManager again after covering its old pixels. Invoke the native
        manager transaction at this exact z-order boundary, after the root has
        been captured into its cursor-free cache. This preserves cursor
        selection, animation, hotspot, clipping, save-under, and hidden state
        without recognizing a resource name, screen coordinate, or resolution.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x9c\x60")
        # PUSHFD/PUSHAD retain the incoming encoded handle in saved EAX.
        code.raw(b"\x8b\x5c\x24\x1c\x85\xdb")
        code.jump_if(Condition.EQUAL, "done")
        # Preserve stock behavior at the authored reference size. The modern
        # fitted root is the only producer whose transformed redraw ordering
        # requires an explicit final cursor submission.
        code.raw(b"\x81\x3d" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(struct.pack("<I", AUTHORED_FRAME_HEIGHT))
        code.jump_if(Condition.BELOW_OR_EQUAL, "done")

        # Resolve the same engine-owned chain as the render-thread presenter:
        # EngineLoop -> scene owner -> input dispatcher -> CursorManager.
        code.raw(b"\x8b\x15" + struct.pack("<I", self.profile.address("engine.loop")))
        code.raw(b"\x85\xd2")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x92\x44\x04\x00\x00\x85\xd2")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x52\x44\x85\xd2")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x72\x08\x85\xf6")
        code.jump_if(Condition.EQUAL, "done")
        # The dispatcher may disappear during shutdown. Validate every manager
        # byte consumed below before following its drawable/current-point state.
        code.raw(b"\x68\xbc\x01\x00\x00\x56\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\x81\x3e" + struct.pack("<I", self.profile.address("cursor.manager_vtable")))
        code.jump_if(Condition.NOT_EQUAL, "done")
        # A null drawable is CursorManager's authoritative hidden state.
        code.raw(b"\x83\x7e\x70\x00")
        code.jump_if(Condition.EQUAL, "done")
        # Draw(destination, &manager.current_point) uses GK3's complete native
        # save-under transaction. Its RET 8 consumes both copied arguments.
        code.raw(b"\x8d\x86\xb4\x01\x00\x00\x50\x53\x8b\xce")
        code.call_absolute(self.profile.address("cursor.manager_draw"))
        code.label("done")
        code.raw(b"\x61\x9d\xc3")
        return code.build()

    def build_cursor_manager_draw_wrapper(
        self,
        *,
        wrapper_va: int,
        cursor_state_va: int,
        sidney_active_depth_va: int,
    ) -> bytes:
        """Preserve native cursor drawing and heal queued SIDNEY points.

        GK3 owns the complete synchronous save-under/draw/restore transaction
        in rooms and pure-2D roots. SIDNEY can queue an authored point after its
        retained traversal; only that exact lifetime is canonicalized to the
        manager's current physical point before tail-calling native Draw.

        CursorManager's native implementation subtracts the hotspot immediately
        after this boundary. Compare and rewrite the raw point, never the
        hotspot-adjusted destination.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x9c\x60")
        # Argument one is GK3's encoded destination bitmap handle.  Retain the
        # candidate before any owner-specific policy; the synchronous final
        # transfer promotes it only after resolving to the live physical page.
        code.raw(b"\x8b\x44\x24\x28")
        code.raw(b"\xa3" + struct.pack("<I", cursor_state_va + 128))
        # The authored-resolution path remains byte-for-byte native.
        code.raw(b"\x81\x3d" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(struct.pack("<I", AUTHORED_FRAME_HEIGHT))
        code.jump_if(Condition.BELOW_OR_EQUAL, "native")

        # SIDNEY's exact traversal retains its native synchronous transaction,
        # with only an obsolete point canonicalized below.
        code.raw(b"\x83\x3d" + struct.pack("<I", sidney_active_depth_va) + b"\x00")
        code.jump_if(Condition.NOT_EQUAL, "validate_sidney_point")

        # Direct room rendering uses GK3's native synchronous CursorManager
        # transaction. The renderer-capability adapter selects its background
        # history; routing a room draw to a second pre-Flip presenter creates competing
        # cursor histories and can hide hover/loading generations.
        code.jump("native")

        code.label("validate_sidney_point")
        # PUSHFD/PUSHAD retain ECX at +0x18 and arg2 (POINT*) at +0x2C.
        code.raw(b"\x8b\x44\x24\x18")
        code.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("cursor.manager_vtable")))
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.raw(b"\x8b\x54\x24\x2c\x85\xd2")
        code.jump_if(Condition.EQUAL, "native")
        # The POINT consumed by CursorManager::Draw is the raw pointer
        # position. The native function, not its caller, subtracts +0x28/+0x2c
        # (the cursor hotspot) before forwarding to BitmapDrawable::Draw.
        code.raw(b"\x8b\x88\xb4\x01\x00\x00\x3b\x0a")
        code.jump_if(Condition.NOT_EQUAL, "obsolete")
        code.raw(b"\x8b\x88\xb8\x01\x00\x00\x3b\x4a\x04")
        code.jump_if(Condition.EQUAL, "native")

        code.label("obsolete")
        code.raw(b"\xff\x05" + struct.pack("<I", cursor_state_va + 84))
        # EAX is the validated CursorManager and EDX is the retained POINT.
        # Healing the caller-owned point also prevents the same page history
        # from repeatedly resubmitting an obsolete physical destination.
        code.raw(b"\x8b\x88\xb4\x01\x00\x00\x89\x0a")
        code.raw(b"\x8b\x88\xb8\x01\x00\x00\x89\x4a\x04")

        code.label("native")
        code.raw(b"\x61\x9d")
        code.jump_absolute(self.profile.address("cursor.manager_draw"))
        return code.build()

    def build_cursor_frame_presenter(
        self,
        *,
        wrapper_va: int,
        action_lifetime_helper_va: int,
        cursor_state_va: int,
        caption_frame_presenter_va: int,
        tooltip_frame_presenter_va: int,
        loadsave_frame_presenter_va: int,
        room_presentation_active_va: int,
        fixed_canvas_owner_va: int,
        loadsave_root_ptr_va: int,
        closeup_frame_presenter_va: int,
        closeup_destination_handle_va: int,
        confirm_quit_cursor_suspended_va: int,
    ) -> bytes:
        """Draw retained-root overlays and cursor at the final page owner.

        The transition runtime invokes this no-argument callback immediately
        before native Flip. The staged 3D copy has therefore erased every old
        cursor from the current back page and native HUD rendering is complete.
        Repainting live dialogue captions and room status here gives the
        current page its exact retained generation. The modal toolbar is
        traversed here only for copied native damage or a bounded page seed;
        every accepted traversal uses its complete small root bounds so the
        subsequently captured composition is authoritative. The staged
        producer itself replaces
        CursorManager's save-under/background restoration, so the final owner
        invokes the live drawable directly with GK3's native destination,
        frame, hotspot-adjusted point, draw options, clipping, and color-key
        path. Avoiding only the redundant save/copy/restore transaction keeps
        modal frames from contending with Flip while preserving a current
        cursor on every continuously rebuilt room page.

        The encoded destination handle is learned only from a proven cursor
        transfer, resolved through GK3's own bitmap table, and revalidated
        against the current DirectDraw back interface on every frame. Pure-2D
        roots retain their native synchronous cursor transaction. A pre-stage
        RoomLayer is owned separately by its exact completed Draw wrapper, so
        this callback has no transitional fallback and cannot double-present.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x9c\x60")
        # A successful ActionMenu callback may replace the current layer before
        # GK3 runs the transient menu's destructor. Validate presentation
        # membership at this exact final-page ownership edge; allocation
        # lifetime alone is not proof that the old menu or tooltip is visible.
        code.call_absolute(action_lifetime_helper_va)
        # Load/Save owns a retained full-screen canvas independently of the
        # room-stage lifetime. Its producer wrapper captured the exact native
        # destination handle, while this callback is the only proof of the
        # physical page about to Flip. Compose that root, its global tooltip,
        # and finally the cursor on this one page; room overlays belong below
        # the retained canvas and must not leak through it.
        code.raw(b"\xa1" + struct.pack("<I", fixed_canvas_owner_va) + b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "no_suspended_canvas")
        # The page lease is shared by every full-screen fixed interface, but
        # only Load/Save needs patch-owned cache replay at this boundary.
        # Compare exact producer identities rather than inferring a class from
        # stale cache state: CloseUp owns its native tree and cursor transaction
        # synchronously, so the final presenter must merely refrain from
        # repainting the staged room over it. ConfirmQuit seeds its complete
        # composition independently at the post-Flip boundary.
        code.raw(b"\x3b\x05" + struct.pack("<I", loadsave_root_ptr_va))
        code.jump_if(Condition.EQUAL, "loadsave")
        code.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("closeup.vtable")))
        code.jump_if(Condition.NOT_EQUAL, "done")
        # CloseUp's bounded page initializer runs before the cursor. Once both
        # peers are seeded it becomes a cheap budget check, while the cursor
        # continues to follow hover/loading animation on every visible frame.
        code.call_absolute(closeup_frame_presenter_va)
        code.call_absolute(tooltip_frame_presenter_va)
        code.raw(b"\x8b\x1d" + struct.pack("<I", closeup_destination_handle_va))
        code.jump("destination_ready")
        code.label("no_suspended_canvas")
        # ConfirmQuit pauses the native worker only while both modal pages are
        # initialized. Keep that seed cursor-free; its post-Flip owner resumes
        # the worker, including native save-under cleanup, after the copy.
        code.raw(b"\x83\x3d" + struct.pack("<I", confirm_quit_cursor_suspended_va) + b"\x01")
        code.jump_if(Condition.EQUAL, "done")
        code.label("ordinary_pure_2d")
        # Every pure-2D root keeps its native page and cursor transaction, but
        # its modern scaled tooltip still needs this exact pre-Flip owner to
        # remain visible on both rotating pages.
        code.raw(b"\x83\x3d" + struct.pack("<I", room_presentation_active_va) + b"\x00")
        code.jump_if(Condition.NOT_EQUAL, "staged_room")
        code.call_absolute(tooltip_frame_presenter_va)
        code.jump("done")
        code.label("staged_room")
        # Room status, toolbar, ActionMenu, and cursor now draw synchronously.
        # Captions and tooltips still retain their independent final-page
        # owners while those features are migrated to the same direct model.
        code.call_absolute(caption_frame_presenter_va)
        code.call_absolute(tooltip_frame_presenter_va)
        code.jump("done")
        code.label("loadsave")
        code.call_absolute(loadsave_frame_presenter_va)
        code.call_absolute(tooltip_frame_presenter_va)
        # The Load/Save handle belongs to its retained canvas. Cursor
        # composition must target the physical page proved by the last
        # synchronous framebuffer transfer; using the canvas handle here
        # either fails the back-page identity check or paints underneath the
        # canvas which was just presented above.
        code.raw(b"\x8b\x1d" + struct.pack("<I", cursor_state_va + 132))
        code.label("destination_ready")
        code.raw(b"\x85\xdb")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x0d" + struct.pack("<I", self.profile.address("resource.manager")))
        code.raw(b"\x85\xc9")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x68\x24\x01\x00\x00\x51\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "done")
        # The lookup at 0x00534560 dereferences its owner's +0x120 array pointer
        # without a null check. GK3 clears that nested table before withdrawing
        # the outer RoomLayer/stage identities during shutdown, so the outer
        # readability proof alone is insufficient at the final teardown Flip.
        code.raw(b"\x8b\x0d" + struct.pack("<I", self.profile.address("resource.manager")))
        code.raw(b"\x83\xb9\x20\x01\x00\x00\x00")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x53")
        code.call_absolute(self.profile.address("bitmap.resolve_resource"))
        code.raw(b"\x8b\xf8\x85\xff")
        code.jump_if(Condition.EQUAL, "done")
        # The resolver returns the bitmap resource. Its +0x30 child is the
        # surface wrapper whose +0x2c field holds IDirectDrawSurface; comparing
        # resource+0x2c instead reads unrelated bitmap metadata.
        code.raw(b"\x6a\x34\x57\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\x8b\x7f\x30\x85\xff")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x6a\x30\x57\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\xa1" + struct.pack("<I", self.profile.address("transition.back_surface_ptr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x3b\x47\x2c")
        code.jump_if(Condition.NOT_EQUAL, "done")

        # Resolve the same engine-owned CursorManager chain used by the native
        # input dispatcher only after all cursor-independent overlays have been
        # presented: EngineLoop -> scene owner -> dispatcher -> manager.
        code.raw(b"\x8b\x15" + struct.pack("<I", self.profile.address("engine.loop")))
        code.raw(b"\x85\xd2")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x92\x44\x04\x00\x00\x85\xd2")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x52\x44\x85\xd2")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x72\x08\x85\xf6")
        code.jump_if(Condition.EQUAL, "done")
        # The dispatcher may tear down between room publication and the next
        # render pass. Validate the complete manager extent consumed below,
        # not merely its first vtable DWORD, before dereferencing either.
        code.raw(b"\x68\xbc\x01\x00\x00\x56\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\x81\x3e" + struct.pack("<I", self.profile.address("cursor.manager_vtable")))
        code.jump_if(Condition.NOT_EQUAL, "done")
        # A null drawable is CursorManager's authoritative hidden state during
        # cursor selection handoff. Do not substitute the prior generation.
        code.raw(b"\x8b\x4e\x70\x85\xc9")
        code.jump_if(Condition.EQUAL, "done")
        # CursorManager::Draw owns the hotspot adjustment and drawable lock;
        # CursorPlatform (not this method) owns background save/restore.
        code.raw(b"\x83\xec\x08")
        # Fixed retained canvases can replace the drawable (C_POINT -> C_WAIT)
        # after the last event-time transfer. Their manager point is in the
        # temporary authored-input domain and may lag the physical pointer.
        # Read GK3's authoritative Win32-to-client producer at this final page
        # boundary. Passing that physical point to CursorManager::Draw is the
        # native retained-canvas contract; the cursor blitter scales only the
        # sprite extent and must never inverse-map its absolute destination.
        # Staged rooms continue to invoke BitmapDrawable directly because
        # their completed 3D stage already is the cursor's save-under.
        code.raw(b"\x83\x3d" + struct.pack("<I", fixed_canvas_owner_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "manager_cursor_point")
        code.label("live_manager_cursor")
        code.raw(b"\x8d\x04\x24\x50")
        code.call_absolute(self.profile.address("cursor.get_client_point"))
        code.raw(b"\x83\xc4\x04")
        # CursorManager::Draw(destination, POINT*) is thiscall/RET 8. Call the
        # pristine function directly so the event-routing slot cannot send
        # this final retained-canvas owner back through the staged-room path.
        code.raw(b"\x8d\x04\x24\x50\x53\x8b\xce")
        code.call_absolute(self.profile.address("cursor.manager_draw"))
        code.raw(b"\x83\xc4\x08")
        code.raw(b"\xff\x05" + struct.pack("<I", cursor_state_va + 140))
        code.jump("done")
        code.label("manager_cursor_point")
        code.raw(b"\x8b\x86\xb4\x01\x00\x00\x2b\x46\x28\x89\x04\x24")
        code.raw(b"\x8b\x86\xb8\x01\x00\x00\x2b\x46\x2c\x89\x44\x24\x04")
        code.label("draw_cursor_bitmap")
        code.raw(b"\x8d\x46\x14\x50")
        code.raw(b"\xff\x76\x74\x6a\x00")
        code.raw(b"\x8d\x44\x24\x0c\x50\x53")
        code.raw(b"\x8b\x01\xff\x50\x18")
        code.raw(b"\x83\xc4\x08")
        code.raw(b"\xff\x05" + struct.pack("<I", cursor_state_va + 140))
        code.label("done")
        code.raw(b"\x61\x9d\xc3")
        return code.build()

    def build_cursor_surface_classifier(
        self,
        *,
        wrapper_va: int,
        cursor_state_va: int,
        trace_va: int,
    ) -> bytes:
        """Return whether either resolved surface belongs to CursorManager.

        ``ECX`` is the resolved destination wrapper, ``EDX`` the resolved
        source wrapper, and ``ESI`` the destination rectangle. The three
        durable cursor identities are sufficient after their first
        publication. Testing both transfer endpoints is essential: restoring
        a saved cursor background owns a private source, while capturing the
        next background owns a private destination. Either half must bypass a
        surrounding fixed-interface affine.

        Keeping this classifier at the shared system-blitter boundary matters:
        a title or Load/Save traversal can synchronously restore the cursor
        without ever entering the room-toolbar helper. Applying that root's
        affine to the private restore is what produced alternating cursor-sized
        title fragments on one DirectDraw page. Both callers emit this single
        predicate, so no fixed interface owns a screen-specific cursor bypass.
        The routine returns one in ``EAX`` for cursor-owned work and zero for an
        ordinary interface transfer. All other registers may be clobbered;
        each caller already encloses the call in ``PUSHAD``.
        """
        code = X86Emitter(base_va=wrapper_va)
        # The native allocator has already published both platform surfaces.
        # Test exact identities only: surface size, cursor position, and output
        # resolution are neither necessary nor sufficient ownership proofs.
        code.raw(b"\x85\xc9")
        code.jump_if(Condition.EQUAL, "source_identities")
        for state_offset in (80, 72, 88, 148):
            code.raw(b"\x3b\x0d" + struct.pack("<I", cursor_state_va + state_offset))
            code.jump_if(Condition.EQUAL, "owned_destination")
        code.label("source_identities")
        code.raw(b"\x85\xd2")
        code.jump_if(Condition.EQUAL, "miss")
        for state_offset in (80, 72, 88, 148):
            code.raw(b"\x3b\x15" + struct.pack("<I", cursor_state_va + state_offset))
            code.jump_if(Condition.EQUAL, "owned_source")
        code.label("miss")
        code.raw(b"\x31\xc0\xc3")
        code.label("owned_destination")
        code.raw(b"\xb8\x02\x00\x00\x00")
        code.jump_short("publish_owned")
        code.label("owned_source")
        code.raw(b"\xb8\x01\x00\x00\x00")
        code.jump_short("publish_owned")
        code.label("publish_owned")
        code.raw(b"\xa3" + struct.pack("<I", trace_va + 12))
        code.raw(b"\xff\x05" + struct.pack("<I", trace_va))
        code.raw(b"\x89\x15" + struct.pack("<I", trace_va + 4))
        code.raw(b"\x89\x0d" + struct.pack("<I", trace_va + 8))
        code.raw(b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "clear_trace_rect")
        for rect_offset in range(0, 16, 4):
            code.raw(b"\x8b\x46" + bytes([rect_offset]))
            code.raw(b"\xa3" + struct.pack("<I", trace_va + 16 + rect_offset))
        code.jump_short("owned_done")
        code.label("clear_trace_rect")
        code.raw(b"\x31\xc0")
        for rect_offset in range(0, 16, 4):
            code.raw(b"\xa3" + struct.pack("<I", trace_va + 16 + rect_offset))
        code.label("owned_done")
        code.raw(b"\xb8\x01\x00\x00\x00\xc3")
        return code.build()
