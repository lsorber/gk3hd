"""Compile tooltip lookup, hover feedback, and retained presentation."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.geometry import AUTHORED_FRAME_HEIGHT
from gk3hd.patch.definitions.runtime2d.layout import (
    RESOURCE_DRIVING_MAP_INPUT_ACTIVE_OFFSET,
    RESOURCE_SEGMENT,
    SIDNEY_DRIVING_MAP_INPUT_DEPTH_OFFSET,
    SIDNEY_INPUT_DISPATCHER_OFFSET,
    SIDNEY_PRESENTATION_SEGMENT,
    SIDNEY_TOOLBAR_INPUT_DEPTH_OFFSET,
    SIDNEY_TOOLBAR_INPUT_HELPER_OFFSET,
    SYSTEM_CONTROL_ACTION_TOOLTIP_CALL_COUNT_OFFSET,
    SYSTEM_CONTROL_ACTION_TOOLTIP_FRAME_CALL_COUNT_OFFSET,
    SYSTEM_CONTROL_ACTION_TOOLTIP_FRAME_REQUEST_CONSUME_COUNT_OFFSET,
    SYSTEM_CONTROL_ACTION_TOOLTIP_FRAME_REQUEST_PENDING_OFFSET,
    SYSTEM_CONTROL_ACTION_TOOLTIP_TOOLBAR_INVERSE_COUNT_OFFSET,
    SYSTEM_CONTROL_ACTION_TOOLTIP_VISIBILITY_PRESENT_COUNT_OFFSET,
    SYSTEM_CONTROL_TOOLBAR_INPUT_VALID_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_CAPTURED_HOVER_OWNER_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_COMPOSITION_PENDING_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_DAMAGE_PTR_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_DEST_HANDLE_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_FRAME_PRESENT_COUNT_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_HOVER_IDENTITY_VALID_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_HOVER_TARGET_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_INNER_RECT_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_MOUSE_OWNER_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_OBJECT_PTR_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_OUTER_RECT_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_PANEL_BLT_RESULT_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_PANEL_CAPTURE_MODE_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_PANEL_CAPTURE_RESULT_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_PANEL_CREATE_RESULT_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_PANEL_DESCRIPTOR_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_PANEL_DIMENSIONS_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_PANEL_FILL_RESULT_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_PANEL_LOCAL_INNER_RECT_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_PANEL_OWNER_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_PANEL_SOURCE_RECT_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_PANEL_SURFACE_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_PANEL_WHITE_BLTFX_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_PRESENTED_RECT_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_RENDER_DAMAGE_REGION_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_TEXT_LENGTH_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_TEXT_POINTER_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_VISIBLE_LATCH_OFFSET,
)
from gk3hd.patch.definitions.runtime2d.system.menu_exports import (
    ActionMenuRuntimeExports,
    TooltipRuntimeExports,
)
from gk3hd.patch.definitions.runtime2d.system.shared import SystemCompilerContext

if TYPE_CHECKING:
    from gk3hd.patch.binary.payload import SegmentPayloadBuilder


@dataclass(frozen=True, slots=True, kw_only=True)
class TooltipFeatureCompiler(SystemCompilerContext):
    """Retain native menu tooltips above fitted controls without trails.

    Outcome:
        Hover text appears beside the correct left- or right-click control at
        reference-relative font and panel scale, persists at display cadence,
        and disappears cleanly from both DirectDraw pages.

    Before:
        GK3 resolves hover in authored space but draws decoration through the
        current physical target. At larger displays the query, backing panel,
        glyphs, damage, and flip-page lifetime can disagree.

    After:
        Tooltip lookup uses the owning menu's inverse affine; one bounded cache
        captures panel and text as an atomic generation and the frame presenter
        reuses or withdraws that generation on the correct page.

    Strategy:
        Wrap native hover resolution, visibility, decoration, and Draw; publish
        exact text and panel identity; compose through a tooltip-local surface;
        and link its presenter into the shared pre-Flip transaction.

    Boundaries:
        Action/toolbar geometry and dropdown rows remain separate subfeatures.
        Native tooltip wording, cursor animation, room rendering, and cadence
        policy are unchanged.
    """

    def emit_runtime(
        self,
        payload: SegmentPayloadBuilder,
        *,
        system_va: int,
        control_va: int,
        action: ActionMenuRuntimeExports,
    ) -> TooltipRuntimeExports:
        """Compile tooltip lookup, composition cache, and lifetime presentation."""
        visibility_va = control_va + self._off_tooltip_visibility_wrapper
        draw_va = control_va + self._off_tooltip_draw_wrapper
        base_va = control_va + self._off_tooltip_base_decoration_wrapper
        border_va = control_va + self._off_tooltip_border_decoration_wrapper
        modal_va = control_va + self._off_modal_tooltip_resolver_wrapper
        epilogue_va = control_va + self._off_tooltip_fixed_layer_epilogue_wrapper
        frame_presenter_va = control_va + self._off_tooltip_frame_presenter
        background_va = control_va + self._off_tooltip_background_helper
        transfer_va = control_va + self._off_tooltip_transfer_affine
        draw = self.build_tooltip_draw_wrapper(
            wrapper_va=draw_va,
            depth_va=control_va + self._off_tooltip_draw_depth,
            count_va=control_va + self._off_tooltip_draw_count,
            target_va=self._native_tooltip_draw_va,
            dest_handle_va=control_va + SYSTEM_CONTROL_TOOLTIP_DEST_HANDLE_OFFSET,
            object_ptr_va=control_va + SYSTEM_CONTROL_TOOLTIP_OBJECT_PTR_OFFSET,
            damage_ptr_va=control_va + SYSTEM_CONTROL_TOOLTIP_DAMAGE_PTR_OFFSET,
        )
        modal = self.build_modal_tooltip_resolver_wrapper(
            wrapper_va=modal_va,
            action_root_ptr_va=system_va + self._off_action_layout_state + 0x20,
            action_layout_helper_va=action.action_layout_helper_va,
            trace_va=control_va + SYSTEM_CONTROL_ACTION_TOOLTIP_CALL_COUNT_OFFSET,
            system_root_ptr_va=system_va + self._off_root_ptr,
            toolbar_input_valid_va=control_va + SYSTEM_CONTROL_TOOLBAR_INPUT_VALID_OFFSET,
            toolbar_input_depth_va=self.symbols.va(
                SIDNEY_PRESENTATION_SEGMENT.logical_name,
                SIDNEY_TOOLBAR_INPUT_DEPTH_OFFSET,
            ),
            toolbar_input_wrapper_va=self.symbols.va(
                SIDNEY_PRESENTATION_SEGMENT.logical_name,
                SIDNEY_TOOLBAR_INPUT_HELPER_OFFSET,
            ),
            driving_map_active_va=self.symbols.va(
                RESOURCE_SEGMENT.logical_name,
                RESOURCE_DRIVING_MAP_INPUT_ACTIVE_OFFSET,
            ),
            driving_map_input_depth_va=self.symbols.va(
                SIDNEY_PRESENTATION_SEGMENT.logical_name,
                SIDNEY_DRIVING_MAP_INPUT_DEPTH_OFFSET,
            ),
            input_dispatcher_va=self.symbols.va(
                SIDNEY_PRESENTATION_SEGMENT.logical_name,
                SIDNEY_INPUT_DISPATCHER_OFFSET,
            ),
            toolbar_inverse_count_va=(
                control_va + SYSTEM_CONTROL_ACTION_TOOLTIP_TOOLBAR_INVERSE_COUNT_OFFSET
            ),
        )
        base = self.build_tooltip_decoration_wrapper(
            wrapper_va=base_va,
            target_va=self._original_call_target(self._tooltip_base_site_name),
            argument_bytes=8,
        )
        border = self.build_tooltip_decoration_wrapper(
            wrapper_va=border_va,
            target_va=self._original_call_target(self._tooltip_border_site_names[0]),
            argument_bytes=16,
        )
        frame_presenter = self.build_tooltip_frame_presenter(
            wrapper_va=frame_presenter_va,
            object_ptr_va=control_va + SYSTEM_CONTROL_TOOLTIP_OBJECT_PTR_OFFSET,
            destination_handle_va=control_va + SYSTEM_CONTROL_TOOLTIP_DEST_HANDLE_OFFSET,
            damage_ptr_va=control_va + SYSTEM_CONTROL_TOOLTIP_DAMAGE_PTR_OFFSET,
            target_va=self._native_tooltip_draw_va,
            background_helper_va=background_va,
            presented_rect_va=control_va + SYSTEM_CONTROL_TOOLTIP_PRESENTED_RECT_OFFSET,
            visible_latch_va=control_va + SYSTEM_CONTROL_TOOLTIP_VISIBLE_LATCH_OFFSET,
            composition_pending_va=control_va + SYSTEM_CONTROL_TOOLTIP_COMPOSITION_PENDING_OFFSET,
            text_pointer_va=control_va + SYSTEM_CONTROL_TOOLTIP_TEXT_POINTER_OFFSET,
            text_length_va=control_va + SYSTEM_CONTROL_TOOLTIP_TEXT_LENGTH_OFFSET,
            mouse_owner_va=control_va + SYSTEM_CONTROL_TOOLTIP_MOUSE_OWNER_OFFSET,
            hover_target_va=control_va + SYSTEM_CONTROL_TOOLTIP_HOVER_TARGET_OFFSET,
            captured_hover_owner_va=(
                control_va + SYSTEM_CONTROL_TOOLTIP_CAPTURED_HOVER_OWNER_OFFSET
            ),
            hover_identity_valid_va=(
                control_va + SYSTEM_CONTROL_TOOLTIP_HOVER_IDENTITY_VALID_OFFSET
            ),
            render_damage_region_va=(
                control_va + SYSTEM_CONTROL_TOOLTIP_RENDER_DAMAGE_REGION_OFFSET
            ),
            panel_surface_va=control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_SURFACE_OFFSET,
            panel_owner_va=control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_OWNER_OFFSET,
            panel_capture_mode_va=control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_CAPTURE_MODE_OFFSET,
            panel_capture_result_va=(
                control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_CAPTURE_RESULT_OFFSET
            ),
            depth_va=control_va + self._off_tooltip_draw_depth,
            present_count_va=control_va + SYSTEM_CONTROL_TOOLTIP_FRAME_PRESENT_COUNT_OFFSET,
            fixed_modal_object_ptr_va=system_va + self._off_action_layout_state + 0x20,
            frame_call_count_va=control_va + SYSTEM_CONTROL_ACTION_TOOLTIP_FRAME_CALL_COUNT_OFFSET,
        )
        background = self.build_tooltip_background_helper(
            wrapper_va=background_va,
            destination_handle_va=control_va + SYSTEM_CONTROL_TOOLTIP_DEST_HANDLE_OFFSET,
            ddraw_va=self.profile.address("high_resolution_3d.directdraw_ptr"),
            outer_rect_va=control_va + SYSTEM_CONTROL_TOOLTIP_OUTER_RECT_OFFSET,
            inner_rect_va=control_va + SYSTEM_CONTROL_TOOLTIP_INNER_RECT_OFFSET,
            presented_rect_va=control_va + SYSTEM_CONTROL_TOOLTIP_PRESENTED_RECT_OFFSET,
            panel_surface_va=control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_SURFACE_OFFSET,
            panel_owner_va=control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_OWNER_OFFSET,
            panel_dimensions_va=control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_DIMENSIONS_OFFSET,
            panel_source_rect_va=control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_SOURCE_RECT_OFFSET,
            panel_local_inner_rect_va=(
                control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_LOCAL_INNER_RECT_OFFSET
            ),
            panel_descriptor_va=control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_DESCRIPTOR_OFFSET,
            black_bltfx_va=system_va + self._off_bltfx,
            white_bltfx_va=control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_WHITE_BLTFX_OFFSET,
            create_result_va=control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_CREATE_RESULT_OFFSET,
            fill_result_va=control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_FILL_RESULT_OFFSET,
            blt_result_va=control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_BLT_RESULT_OFFSET,
            capture_mode_va=control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_CAPTURE_MODE_OFFSET,
            capture_result_va=control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_CAPTURE_RESULT_OFFSET,
        )
        transfer = self.build_tooltip_transfer_affine(
            wrapper_va=transfer_va,
            downstream_va=self._hd_wrapper_va(),
            object_ptr_va=control_va + SYSTEM_CONTROL_TOOLTIP_OBJECT_PTR_OFFSET,
            dest_rect_va=system_va + self._off_dest_rect,
            transform_count_va=system_va + self._off_transform_count,
        )
        visibility = self.build_tooltip_visibility_wrapper(
            wrapper_va=visibility_va,
            action_lifetime_helper_va=action.action_lifetime_helper_va,
            room_presentation_active_va=self.transition_abi.room_presentation_active_va,
            fixed_modal_object_ptr_va=system_va + self._off_action_layout_state + 0x20,
            present_request_count_va=(
                control_va + SYSTEM_CONTROL_ACTION_TOOLTIP_VISIBILITY_PRESENT_COUNT_OFFSET
            ),
            frame_request_pending_va=(
                control_va + SYSTEM_CONTROL_ACTION_TOOLTIP_FRAME_REQUEST_PENDING_OFFSET
            ),
        )
        epilogue = self.build_tooltip_fixed_layer_epilogue_wrapper(
            wrapper_va=epilogue_va,
            frame_request_pending_va=(
                control_va + SYSTEM_CONTROL_ACTION_TOOLTIP_FRAME_REQUEST_PENDING_OFFSET
            ),
            frame_request_consume_count_va=(
                control_va + SYSTEM_CONTROL_ACTION_TOOLTIP_FRAME_REQUEST_CONSUME_COUNT_OFFSET
            ),
        )
        for label, offset, code, limit in (
            (
                "tooltip visibility transition",
                self._off_tooltip_visibility_wrapper,
                visibility,
                self._off_tooltip_visibility_wrapper_limit,
            ),
            (
                "tooltip fixed-layer epilogue",
                self._off_tooltip_fixed_layer_epilogue_wrapper,
                epilogue,
                self._off_tooltip_fixed_layer_epilogue_wrapper_limit,
            ),
            (
                "action-menu tooltip resolver",
                self._off_modal_tooltip_resolver_wrapper,
                modal,
                self._off_modal_tooltip_resolver_wrapper_limit,
            ),
            (
                "tooltip base-decoration gate",
                self._off_tooltip_base_decoration_wrapper,
                base,
                self._off_tooltip_base_decoration_wrapper_limit,
            ),
            (
                "tooltip border-decoration gate",
                self._off_tooltip_border_decoration_wrapper,
                border,
                self._off_tooltip_border_decoration_wrapper_limit,
            ),
            (
                "tooltip draw scope",
                self._off_tooltip_draw_wrapper,
                draw,
                self._off_tooltip_draw_wrapper_limit,
            ),
            (
                "tooltip frame presenter",
                self._off_tooltip_frame_presenter,
                frame_presenter,
                self._off_tooltip_frame_presenter_limit,
            ),
            (
                "tooltip background",
                self._off_tooltip_background_helper,
                background,
                self._off_tooltip_background_helper_limit,
            ),
            (
                "tooltip transfer affine",
                self._off_tooltip_transfer_affine,
                transfer,
                self._off_tooltip_transfer_affine_limit,
            ),
        ):
            payload.place(label=label, offset=offset, payload=code, limit=limit)
        return TooltipRuntimeExports(
            visibility_wrapper_va=visibility_va,
            draw_wrapper_va=draw_va,
            base_wrapper_va=base_va,
            border_wrapper_va=border_va,
            modal_resolver_va=modal_va,
            fixed_layer_epilogue_va=epilogue_va,
            frame_presenter_va=frame_presenter_va,
            transfer_affine_va=transfer_va,
        )

    def _emit_native_tooltip_gate(self, code: X86Emitter, *, target: str) -> None:
        """Keep native tooltips except for scaled output or full-map redraws."""
        code.raw(b"\x81\x3d" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(struct.pack("<I", AUTHORED_FRAME_HEIGHT))
        code.jump_short_if(Condition.ABOVE, "tooltip_compositor")
        active_va = self.symbols.va(
            RESOURCE_SEGMENT.logical_name, RESOURCE_DRIVING_MAP_INPUT_ACTIVE_OFFSET
        )
        code.raw(b"\x83\x3d" + struct.pack("<I", active_va) + b"\x00")
        code.jump_if(Condition.EQUAL, target)
        code.label("tooltip_compositor")

    def build_tooltip_decoration_wrapper(
        self,
        *,
        wrapper_va: int,
        target_va: int,
        argument_bytes: int,
    ) -> bytes:
        """Tail-enter native chrome only outside full-frame tooltip composition.

        The wrapped call is ``stdcall`` and its arguments are already on the
        caller's stack. Reference-height paths tail-enter GK3's original callee
        unchanged except on the fully redrawn driving map. Above 768 lines every
        ToolTip is composed by the same scaled
        panel owner, including pure-2D title and Load/Save screens; returning
        locally prevents native-size chrome from clipping the scaled text.
        Runtime height—not an install-time resolution—selects the policy.
        """
        if argument_bytes not in {8, 16}:
            msg = "tooltip decoration wrapper requires 8 or 16 argument bytes"
            raise ValueError(msg)
        code = X86Emitter(base_va=wrapper_va)
        self._emit_native_tooltip_gate(code, target="native")
        code.label("suppress")
        code.raw(b"\x31\xc0\xc2" + struct.pack("<H", argument_bytes))
        code.label("native")
        code.jump_absolute(target_va)
        return code.build()

    def build_tooltip_draw_wrapper(
        self,
        *,
        wrapper_va: int,
        depth_va: int,
        count_va: int,
        target_va: int,
        dest_handle_va: int,
        object_ptr_va: int,
        damage_ptr_va: int,
    ) -> bytes:
        """Defer every modern ToolTip transaction to the final page owner.

        ToolTip is a global room overlay and may be traversed independently of
        InGameToolbar. Drawing it at event time therefore writes an arbitrary
        DirectDraw peer which the next staged room copy can immediately erase.
        At any output above the authored height, publish the live visible
        object, destination, and caller-owned damage collection, then return.
        The shared pre-Flip owner consumes that same-frame collection and
        invokes native Draw exactly once on the proven current back page. This
        same policy covers title, Load/Save, room, and ActionMenu tooltips, so
        native-size decoration can never be paired with scaled text. Hidden
        traversals remain synchronous because they own GK3's hover-delay state
        machine but paint no pixels. Reference-height operation remains fully
        native. The local return is initialized because a deferred caller must
        never observe arbitrary stack contents.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x55\x8b\xec\x83\xec\x04\x53\x8b\xd9\x31\xc0\x89\x45\xfc")
        code.raw(b"\x89\x1d" + struct.pack("<I", object_ptr_va))
        code.raw(b"\x8b\x45\x08\xa3" + struct.pack("<I", dest_handle_va))
        code.raw(b"\xff\x05" + struct.pack("<I", count_va))
        self._emit_native_tooltip_gate(code, target="native")
        # Hidden ToolTip traversals participate in GK3's native delayed-hover
        # state machine. Preserve them synchronously and transfer ownership
        # only after that state machine publishes a visible generation.
        code.raw(b"\x80\x7b\x18\x00")
        code.jump_if(Condition.EQUAL, "native")
        code.label("deferred")
        code.raw(b"\x8b\x45\x0c\xa3" + struct.pack("<I", damage_ptr_va))
        code.jump("done")

        code.label("native")
        code.raw(b"\xff\x05" + struct.pack("<I", depth_va))
        code.raw(b"\xff\x75\x0c\xff\x75\x08\x8b\xcb")
        code.call_absolute(target_va)
        code.raw(b"\x89\x45\xfc")
        code.raw(b"\xff\x0d" + struct.pack("<I", depth_va))
        code.label("done")
        code.raw(b"\x8b\x45\xfc\x5b\xc9\xc2\x08\x00")
        return code.build()

    def build_tooltip_visibility_wrapper(
        self,
        *,
        wrapper_va: int,
        action_lifetime_helper_va: int,
        room_presentation_active_va: int,
        fixed_modal_object_ptr_va: int,
        present_request_count_va: int,
        frame_request_pending_va: int,
    ) -> bytes:
        """Request a page pair following a pure-2D tooltip visibility edge.

        ToolTip's +0xB0 SetVisible virtual is invoked by the completion
        callback of its native hover animation during a stock engine tick.
        Invalidating from inside that callback is too early: the same tick can
        retire the collection before a visible traversal. Observe an exact
        visibility change and publish one pending frame token. Staged rooms
        already render continuously and need no request. A live ActionMenu is
        revalidated by current-layer membership; ordinary title, Load/Save,
        and other pure-2D roots need no modal identity. The fixed-layer render-
        call owner consumes the token only after its current outer render has
        returned, avoiding both re-entrancy and synthetic input. Requesting
        show and hide edges populates or clears both rotating pages. Reference
        resolution remains byte-for-byte native.
        """
        code = X86Emitter(base_va=wrapper_va)
        # +0xB0 is thiscall(bool) with RET 4. Preserve all nonvolatile state
        # used by the edge detector and retain the native return value in EDI.
        code.raw(b"\x53\x56\x57\x8b\xf1\x8a\x5e\x18")
        code.raw(b"\xff\x74\x24\x10")
        code.call_absolute(self._native_tooltip_visibility_va)
        code.raw(b"\x8b\xf8\x3a\x5e\x18")
        code.jump_if(Condition.EQUAL, "done")
        self._emit_native_tooltip_gate(code, target="done")
        code.raw(b"\x83\x3d" + struct.pack("<I", room_presentation_active_va) + b"\x00")
        code.jump_if(Condition.NOT_EQUAL, "done")

        # Allocation lifetime alone is not visibility proof for a transient
        # ActionMenu. Reuse the direct-child membership owner only when such a
        # modal is published; ordinary pure-2D roots proceed directly.
        code.raw(b"\x83\x3d" + struct.pack("<I", fixed_modal_object_ptr_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "request")
        code.call_absolute(action_lifetime_helper_va)
        code.raw(b"\x83\x3d" + struct.pack("<I", fixed_modal_object_ptr_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "done")
        code.label("request")
        code.raw(b"\xc7\x05" + struct.pack("<I", frame_request_pending_va))
        code.raw(b"\x01\x00\x00\x00")
        code.raw(b"\xff\x05" + struct.pack("<I", present_request_count_va))
        code.label("done")
        code.raw(b"\x8b\xc7\x5f\x5e\x5b\xc2\x04\x00")
        return code.build()

    def build_tooltip_fixed_layer_epilogue_wrapper(
        self,
        *,
        wrapper_va: int,
        frame_request_pending_va: int,
        frame_request_consume_count_va: int,
    ) -> bytes:
        """Append a tooltip-only pair at the fixed system-layer epilogue.

        GK3's native render pair and following UI update have both returned at
        this boundary. If that update published a hidden-to-visible token, two
        ordinary follow-up renders can now safely populate both rotating
        DirectDraw pages. The pending edge is consumed before either render,
        so their normal MouseManager and pre-Flip traversals observe one stable
        native object generation without recursively scheduling more work. The
        displaced callee epilogue restores all three nonvolatile registers and
        consumes its one argument.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x83\x3d" + struct.pack("<I", frame_request_pending_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "epilogue")
        code.raw(
            b"\x8b\x0d" + struct.pack("<I", self.profile.address("transition.engine_loop_ptr"))
        )
        code.raw(b"\x85\xc9")
        code.jump_if(Condition.EQUAL, "epilogue")
        # This epilogue is already beyond the producer and outside every render
        # call. Consume before the follow-up pair; the tooltip presenter reads
        # the coherent native object and needs no second SetVisible mutation.
        code.raw(b"\x83\x25" + struct.pack("<I", frame_request_pending_va) + b"\x00")
        code.raw(b"\xff\x05" + struct.pack("<I", frame_request_consume_count_va))
        code.raw(b"\x6a\x01\x6a\x00\x6a\x00")
        code.call_absolute(self.profile.address("engine.render_frame"))
        code.raw(
            b"\x8b\x0d" + struct.pack("<I", self.profile.address("transition.engine_loop_ptr"))
        )
        code.raw(b"\x85\xc9")
        code.jump_if(Condition.EQUAL, "epilogue")
        code.raw(b"\x6a\x01\x6a\x00\x6a\x00")
        code.call_absolute(self.profile.address("engine.render_frame"))
        code.label("epilogue")
        code.raw(b"\x5f\x5e\x5b\xc2\x04\x00")
        return code.build()

    def build_modal_tooltip_resolver_wrapper(
        self,
        *,
        wrapper_va: int,
        action_root_ptr_va: int,
        action_layout_helper_va: int,
        trace_va: int,
        system_root_ptr_va: int,
        toolbar_input_valid_va: int,
        toolbar_input_depth_va: int,
        toolbar_input_wrapper_va: int,
        toolbar_inverse_count_va: int,
        driving_map_active_va: int,
        driving_map_input_depth_va: int,
        input_dispatcher_va: int,
    ) -> bytes:
        """Resolve room-modal tooltips in their producer's coordinate domain.

        ActionMenu publishes physical object rectangles, so query its root with
        the untouched POINT after running the canonical layout owner. The
        registered InGameToolbar stays on GK3's complete native resolver, but
        delayed idle lookups can run outside the button-event inverse and then
        arrive with a physical POINT. Route only that exact toolbar lifetime
        through the existing target-to-source input helper. A re-entrant depth
        proves when the point is already logical, so the affine is never
        applied twice and this wrapper never synthesizes a toolbar descriptor.
        """
        code = X86Emitter(base_va=wrapper_va)
        # At the authored height the complete tooltip resolver contract is
        # already correct. Tail-enter it before saving registers, publishing
        # telemetry, or consulting asynchronously owned menu pointers. This
        # is intentionally stronger than reaching a later "native" branch:
        # the title transition can destroy one of ResolveHover's retained
        # children during a queued mouse event, so even harmless extra work at
        # this boundary widened a stock use-after-free window at 1024x768.
        code.raw(b"\x81\x3d" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(struct.pack("<I", AUTHORED_FRAME_HEIGHT))
        code.jump_if(Condition.ABOVE, "modern")
        code.jump_absolute(self.profile.address("tooltip.resolve_hover"))

        code.label("modern")
        # Preserve EBX/ESI/EDI. The original POINT* is then at ESP+0x10.
        code.raw(b"\x53\x56\x57\x8b\xd9")
        code.raw(b"\xff\x05" + struct.pack("<I", trace_va))
        code.raw(b"\x8b\x7c\x24\x10\x89\x3d" + struct.pack("<I", trace_va + 0x14))
        code.raw(b"\x85\xff")
        code.jump_if(Condition.EQUAL, "point_recorded")
        code.raw(b"\x8b\x07\xa3" + struct.pack("<I", trace_va + 0x18))
        code.raw(b"\x8b\x47\x04\xa3" + struct.pack("<I", trace_va + 0x1C))
        code.label("point_recorded")
        code.raw(b"\x85\xff")
        code.jump_if(Condition.EQUAL, "native")

        # ActionMenu owns final physical object rectangles.
        code.raw(b"\x8b\x35" + struct.pack("<I", action_root_ptr_va))
        code.raw(b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\x81\x3e" + struct.pack("<I", self.profile.address("action_menu.vtable")))
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.raw(b"\x89\x35" + struct.pack("<I", trace_va + 0x10))
        code.raw(b"\x8b\xce")
        code.call_absolute(action_layout_helper_va)

        # The layout owner publishes 32x32 ActionMenu sprites as larger
        # physical rectangles.  ActionMenu::GetToolTip first performs normal
        # rectangle containment, then asks the sprite for an opacity-mask hit
        # using the *same* POINT.  Supplying an untouched physical offset made
        # all but the upper-left 32 pixels of every enlarged button transparent
        # to hover: at a large output a visible button consequently had a narrow,
        # displaced tooltip target.  Keep the point inside its physical child
        # but map that child's local offset back to [0,32), exactly as the
        # button-edge dispatcher does.  Save the caller-owned physical pair on
        # this invocation's stack and restore it after the synchronous query;
        # no global cursor state or guessed child index participates.
        action_size_va = action_root_ptr_va - 0x20
        action_top_va = action_root_ptr_va - 0x10
        code.raw(b"\xff\x37\xff\x77\x04")  # physical X, then physical Y
        code.raw(b"\x8b\x07\x3b\x46\x1c")
        code.jump_if(Condition.LESS, "action_point_ready")
        code.raw(b"\x3b\x46\x24")
        code.jump_if(Condition.GREATER_OR_EQUAL, "action_point_ready")
        code.raw(b"\x8b\x57\x04\x3b\x56\x20")
        code.jump_if(Condition.LESS, "action_point_ready")
        code.raw(b"\x3b\x56\x28")
        code.jump_if(Condition.GREATER_OR_EQUAL, "action_point_ready")
        code.raw(b"\x8b\x0d" + struct.pack("<I", action_size_va))
        code.raw(b"\x83\xf9\x20")
        code.jump_if(Condition.LESS_OR_EQUAL, "action_point_ready")

        # X: retain the containing physical child anchor and scale only the
        # remainder inside that child into the authored sprite-mask domain.
        code.raw(b"\x8b\x07\x2b\x46\x1c\x99\xf7\xf9")
        code.raw(b"\x29\x17\x8b\xc2\x6b\xc0\x20\x99\xf7\xf9\x01\x07")
        # Y: every button shares the root top, so the ordinary affine is enough.
        code.raw(b"\x8b\x47\x04\x2b\x05" + struct.pack("<I", action_top_va))
        code.raw(b"\x6b\xc0\x20\x99\xf7\xf9")
        code.raw(b"\x03\x05" + struct.pack("<I", action_top_va) + b"\x89\x47\x04")
        code.label("action_point_ready")
        code.raw(b"\xa1" + struct.pack("<I", trace_va + 0x18))
        code.raw(b"\xa3" + struct.pack("<I", trace_va + 0x20))
        code.raw(b"\xa1" + struct.pack("<I", trace_va + 0x1C))
        code.raw(b"\xa3" + struct.pack("<I", trace_va + 0x24))
        code.raw(b"\x8b\x06\x57\x8b\xce\xff\x90\xbc\x00\x00\x00")
        # Preserve the descriptor result while restoring physical Y and X.
        code.raw(b"\x50\x8b\x54\x24\x04\x89\x57\x04")
        code.raw(b"\x8b\x54\x24\x08\x89\x17\x58\x83\xc4\x08")
        code.jump("descriptor_result")

        code.label("descriptor_result")
        code.raw(b"\xff\x05" + struct.pack("<I", trace_va + 0x08))
        code.raw(b"\xa3" + struct.pack("<I", trace_va + 0x28))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\xff\x05" + struct.pack("<I", trace_va + 0x0C))
        code.raw(b"\x8b\xf0\x39\x73\x10")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x89\x73\x10\x8b\x4b\x14\x56")
        code.call_absolute(self.profile.address("tooltip.set_descriptor"))

        code.label("done")
        code.raw(b"\x5f\x5e\x5b\xc2\x04\x00")
        code.label("native")
        code.raw(b"\xff\x05" + struct.pack("<I", trace_va + 0x04))
        # DrivingMap's child rectangles live in the full-width physical model
        # before the complete composition is fitted to a centered 4:3 view.
        # The normal movement traversal already owns this inverse. Idle
        # tooltip refreshes poll another physical POINT later, so route those
        # through the same dispatcher; a depth counter prevents the resolver
        # nested inside an already-adapted traversal from mapping twice.
        code.raw(b"\x83\x3d" + struct.pack("<I", driving_map_active_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "toolbar_check")
        code.raw(b"\x83\x3d" + struct.pack("<I", driving_map_input_depth_va) + b"\x00")
        code.jump_if(Condition.NOT_EQUAL, "native_tail")
        code.raw(b"\x8b\xcb\x5f\x5e\x5b")
        code.raw(b"\xb8" + struct.pack("<I", self.profile.address("tooltip.resolve_hover")))
        code.jump_absolute(input_dispatcher_va)
        code.label("toolbar_check")
        # Button-edge dispatch has already scoped a logical toolbar POINT. An
        # idle ToolTip lookup has not. The published depth distinguishes these
        # native call paths without inspecting coordinates, whose source and
        # target rectangles legitimately overlap at some display modes.
        code.raw(b"\x83\x3d" + struct.pack("<I", toolbar_input_depth_va) + b"\x00")
        code.jump_if(Condition.NOT_EQUAL, "native_tail")
        code.raw(b"\x83\x3d" + struct.pack("<I", toolbar_input_valid_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "native_tail")
        code.raw(b"\x8b\x35" + struct.pack("<I", system_root_ptr_va) + b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "native_tail")
        code.raw(b"\x81\x3e" + struct.pack("<I", self.profile.address("ingame_toolbar.vtable")))
        code.jump_if(Condition.NOT_EQUAL, "native_tail")
        code.raw(b"\x80\x7e\x18\x00")
        code.jump_if(Condition.EQUAL, "native_tail")
        code.raw(b"\xff\x05" + struct.pack("<I", toolbar_inverse_count_va))
        # Restore the original thiscall contract, then let the canonical
        # toolbar helper map both POINT and MouseManager's durable cursor cache
        # around one direct invocation of the untouched native resolver.
        code.raw(b"\x8b\xcb\x5f\x5e\x5b")
        code.raw(b"\xb8" + struct.pack("<I", self.profile.address("tooltip.resolve_hover")))
        code.jump_absolute(toolbar_input_wrapper_va)
        code.label("native_tail")
        code.raw(b"\x8b\xcb\x5f\x5e\x5b")
        code.jump_absolute(self.profile.address("tooltip.resolve_hover"))
        return code.build()

    def build_tooltip_frame_presenter(
        self,
        *,
        wrapper_va: int,
        object_ptr_va: int,
        destination_handle_va: int,
        damage_ptr_va: int,
        target_va: int,
        background_helper_va: int,
        presented_rect_va: int,
        visible_latch_va: int,
        composition_pending_va: int,
        text_pointer_va: int,
        text_length_va: int,
        mouse_owner_va: int,
        hover_target_va: int,
        captured_hover_owner_va: int,
        hover_identity_valid_va: int,
        render_damage_region_va: int,
        panel_surface_va: int,
        panel_owner_va: int,
        panel_capture_mode_va: int,
        panel_capture_result_va: int,
        depth_va: int,
        present_count_va: int,
        fixed_modal_object_ptr_va: int,
        frame_call_count_va: int,
    ) -> bytes:
        """Compose each tooltip generation once and replay its small panel.

        GK3 emits tooltip chrome and text through separate draw APIs. A private
        output-scale panel lets the native text renderer compose both once,
        after which one small asynchronous BltFast presents the completed
        result on every direct-rendered frame. Bounds plus text identity key
        generations, so moving between controls cannot reuse stale glyphs.
        The native object remains authoritative for hover delay, visibility,
        font, text, and metrics. Its visible/text fields are transient producer
        state, however, so a completed panel is retained by the exact live
        MouseManager owner/hover identity tuple until that tuple changes. No
        room-stage damage, timer, or retained-pixel assumption is involved.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x9c\x60")
        code.raw(b"\xff\x05" + struct.pack("<I", frame_call_count_va))
        # Every tooltip above the authored height uses one panel compositor.
        # This avoids a second, subtly different path for title/LoadSave while
        # retaining the pristine renderer at 1024x768.
        self._emit_native_tooltip_gate(code, target="inactive")
        code.label("active")
        # ConfirmQuit replaces the toolbar/controller lifetime immediately,
        # but the old MouseManager hover tuple can remain readable until the
        # following input pulse. Retire that completed tooltip generation at
        # the concrete modal boundary so its cached panel cannot be replayed
        # over the newly composed confirmation screen.
        code.call_absolute(self.profile.address("ui.current_layer"))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "after_modal_guard")
        code.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("confirm_quit.vtable")))
        code.jump_if(Condition.EQUAL, "hidden")
        code.label("after_modal_guard")
        code.raw(b"\x8b\x1d" + struct.pack("<I", object_ptr_va) + b"\x85\xdb")
        code.jump_if(Condition.EQUAL, "hidden")
        # The producer's DamageCollection is stack-owned and valid only in this
        # same render-thread frame. Validate its complete four-DWORD vector
        # header before any native traversal follows the begin/end pointers.
        code.raw(b"\x8b\x35" + struct.pack("<I", damage_ptr_va) + b"\x85\xf6")
        code.jump_if(Condition.NOT_EQUAL, "validate_damage")
        # Once one visible generation has been composed, its private panel is
        # authoritative and can be replayed on later Flip pages without
        # retaining the producer's caller-owned damage vector. The live object
        # and exact ActionMenu lifetime are revalidated below on every frame.
        code.raw(b"\x83\x3d" + struct.pack("<I", visible_latch_va) + b"\x00")
        code.jump_if(Condition.NOT_EQUAL, "validate_object")
        # Fixed ActionMenu deliberately executes hidden ToolTip draws so GK3's
        # native hover-delay state machine can advance. The timer may publish
        # visibility after the final hidden Draw, leaving no later caller-owned
        # DamageCollection to hand off. At this exact modal lifetime, the live
        # tooltip object plus the retained destination are the complete producer
        # proof: this presenter already constructs a private full-panel damage
        # collection before invoking native text. Staged room tooltips retain
        # their stricter same-frame damage publication above.
        code.raw(b"\x83\x3d" + struct.pack("<I", fixed_modal_object_ptr_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "done")
        code.jump("validate_object")
        code.label("validate_damage")
        code.raw(b"\x6a\x10\x56\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "withdraw_damage")
        # Native label composition reads through the final ToolTip fields.
        code.label("validate_object")
        code.raw(b"\x68\x9c\x01\x00\x00\x53\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "hidden")
        code.raw(b"\x81\x3b" + struct.pack("<I", self.profile.address("tooltip.vtable")))
        code.jump_if(Condition.NOT_EQUAL, "hidden")
        # Match ToolTip::Draw's three producer predicates before painting the
        # replacement panel. Native hover timing is owned by ToolTip's input
        # and timer virtuals, not Draw; a hidden candidate therefore remains a
        # cheap no-op until those methods publish a visible generation.
        code.raw(b"\x80\x7b\x18\x00")
        code.jump_if(Condition.EQUAL, "maybe_replay_retained")
        code.raw(b"\x83\xbb\x98\x01\x00\x00\x00")
        code.jump_if(Condition.EQUAL, "maybe_replay_retained")
        code.raw(b"\x80\xbb\x88\x01\x00\x00\x00")
        code.jump_if(Condition.EQUAL, "maybe_replay_retained")
        # A visible generation is stable until either its native bounds or its
        # text identity changes.  ToolTip reuses one object across toolbar
        # children, so visibility alone is not a sufficient generation key.
        code.raw(b"\x83\x3d" + struct.pack("<I", visible_latch_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "new_generation")
        for object_offset, retained_offset in (
            (0x1C, 0),
            (0x20, 4),
            (0x24, 8),
            (0x28, 12),
        ):
            code.raw(b"\x8b\x43" + bytes([object_offset]))
            code.raw(b"\x3b\x05" + struct.pack("<I", presented_rect_va + retained_offset))
            code.jump_if(Condition.NOT_EQUAL, "changed_generation")
        code.raw(b"\x8b\x83\x94\x01\x00\x00")
        code.raw(b"\x3b\x05" + struct.pack("<I", text_pointer_va))
        code.jump_if(Condition.NOT_EQUAL, "changed_generation")
        code.raw(b"\x8b\x83\x98\x01\x00\x00")
        code.raw(b"\x3b\x05" + struct.pack("<I", text_length_va))
        code.jump_if(Condition.EQUAL, "generation_ready")

        code.label("changed_generation")
        code.label("new_generation")
        code.raw(b"\xc7\x05" + struct.pack("<I", visible_latch_va) + b"\x01\x00\x00\x00")
        # Snapshot the concrete mouse-controller identity which selected this
        # text. ToolTip's visible/text bytes may clear after composition even
        # though the same hover remains active; the owner tuple is the durable
        # native lifetime contract. Every pointer is validated before use so
        # teardown cannot turn a retained panel into a stale dereference.
        code.raw(b"\x8b\x35" + struct.pack("<I", self.profile.address("engine.loop")))
        code.raw(b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "identity_unavailable")
        code.raw(b"\x68\x48\x04\x00\x00\x56\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "identity_unavailable")
        code.raw(b"\x8b\xb6\x44\x04\x00\x00\x85\xf6")
        code.jump_if(Condition.EQUAL, "identity_unavailable")
        code.raw(b"\x6a\x48\x56\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "identity_unavailable")
        code.raw(b"\x8b\x76\x44\x85\xf6")
        code.jump_if(Condition.EQUAL, "identity_unavailable")
        code.raw(b"\x6a\x64\x56\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "identity_unavailable")
        code.raw(b"\x39\x5e\x14")
        code.jump_if(Condition.NOT_EQUAL, "identity_unavailable")
        code.raw(b"\x8b\x46\x10\x8b\x56\x60\x8b\xf8\x0b\xfa")
        code.jump_if(Condition.EQUAL, "identity_unavailable")
        code.raw(b"\x89\x35" + struct.pack("<I", mouse_owner_va))
        code.raw(b"\xa3" + struct.pack("<I", hover_target_va))
        code.raw(b"\x89\x15" + struct.pack("<I", captured_hover_owner_va))
        code.raw(b"\xc7\x05" + struct.pack("<I", hover_identity_valid_va) + b"\x01\x00\x00\x00")
        code.jump("identity_ready")

        code.label("identity_unavailable")
        for state_va in (
            mouse_owner_va,
            hover_target_va,
            captured_hover_owner_va,
            hover_identity_valid_va,
        ):
            code.raw(b"\xc7\x05" + struct.pack("<I", state_va) + b"\x00\x00\x00\x00")
        code.label("identity_ready")
        # A changed label may have the same 84x20 authored extent. Retire its
        # cache by producer identity, not dimensions, before composing the new
        # native text. The toolbar destructor owns the final lifetime release.
        code.raw(b"\x8b\x35" + struct.pack("<I", panel_surface_va) + b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "generation_cache_released")
        code.raw(b"\x8b\x06\x56\xff\x50\x08")
        code.raw(b"\x31\xc0")
        code.raw(b"\xa3" + struct.pack("<I", panel_surface_va))
        code.raw(b"\xa3" + struct.pack("<I", panel_owner_va))
        code.label("generation_cache_released")
        # The private damage collection covers the full panel, so
        # ToolTip::Draw cannot clip the label to incidental cursor damage.
        # One means that this generation still needs native composition and a
        # successful cache capture; zero means replay is authoritative.
        code.raw(b"\xc7\x05" + struct.pack("<I", composition_pending_va) + b"\x01\x00\x00\x00")
        code.raw(b"\x8d\x73\x1c\xbf" + struct.pack("<I", presented_rect_va))
        code.raw(b"\xb9\x04\x00\x00\x00\xf3\xa5")
        code.raw(b"\x8b\x83\x94\x01\x00\x00")
        code.raw(b"\xa3" + struct.pack("<I", text_pointer_va))
        code.raw(b"\x8b\x83\x98\x01\x00\x00")
        code.raw(b"\xa3" + struct.pack("<I", text_length_va))

        code.jump("generation_ready")

        # Once a panel is complete, ToolTip's producer bytes are allowed to go
        # dormant. Replay only while the exact validated controller, ToolTip,
        # hover target, and captured owner still match the generation snapshot.
        # This both survives stationary UHD pages and withdraws immediately on
        # movement, menu closure, or controller replacement.
        code.label("maybe_replay_retained")
        code.raw(b"\x83\x3d" + struct.pack("<I", visible_latch_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "hidden")
        code.raw(b"\x83\x3d" + struct.pack("<I", hover_identity_valid_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "hidden")
        code.raw(b"\x8b\x35" + struct.pack("<I", mouse_owner_va) + b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "hidden")
        code.raw(b"\x6a\x64\x56\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "hidden")
        code.raw(b"\x39\x5e\x14")
        code.jump_if(Condition.NOT_EQUAL, "hidden")
        code.raw(b"\x8b\x46\x10")
        code.raw(b"\x3b\x05" + struct.pack("<I", hover_target_va))
        code.jump_if(Condition.NOT_EQUAL, "hidden")
        code.raw(b"\x8b\x46\x60")
        code.raw(b"\x3b\x05" + struct.pack("<I", captured_hover_owner_va))
        code.jump_if(Condition.NOT_EQUAL, "hidden")

        code.label("generation_ready")
        # Direct room and fixed-screen roots can redraw beneath the tooltip on
        # every frame. Replay this tiny cached overlay after that traversal;
        # relying on obsolete private-stage retention makes it disappear.
        code.label("panel_present")
        code.raw(b"\xc7\x05" + struct.pack("<I", panel_capture_mode_va) + b"\x00\x00\x00\x00")
        code.raw(b"\x8b\xcb")
        code.call_absolute(background_helper_va)
        code.raw(b"\x83\x3d" + struct.pack("<I", composition_pending_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "consume_damage")
        code.raw(b"\xa1" + struct.pack("<I", destination_handle_va) + b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "consume_damage")
        code.raw(b"\xff\x05" + struct.pack("<I", depth_va))
        code.raw(b"\x68" + struct.pack("<I", render_damage_region_va))
        code.raw(b"\x50\x8b\xcb")
        code.call_absolute(target_va)
        code.raw(b"\xff\x0d" + struct.pack("<I", depth_va))
        code.raw(b"\xff\x05" + struct.pack("<I", present_count_va))
        # Capture the now-complete physical panel back into its cache. A
        # failed/missing DirectDraw transaction leaves the seed armed so the
        # next frame retries native composition instead of retaining a blank.
        code.raw(b"\xc7\x05" + struct.pack("<I", panel_capture_result_va))
        code.raw(b"\x05\x40\x00\x80")  # E_FAIL until the helper proves success.
        code.raw(b"\xc7\x05" + struct.pack("<I", panel_capture_mode_va) + b"\x01\x00\x00\x00")
        code.raw(b"\x8b\xcb")
        code.call_absolute(background_helper_va)
        code.raw(b"\xc7\x05" + struct.pack("<I", panel_capture_mode_va) + b"\x00\x00\x00\x00")
        code.raw(b"\x83\x3d" + struct.pack("<I", panel_capture_result_va) + b"\x00")
        code.jump_if(Condition.NOT_EQUAL, "consume_damage")
        code.raw(b"\xc7\x05" + struct.pack("<I", composition_pending_va) + b"\x00\x00\x00\x00")

        # The producer publication is a same-frame liveness proof only. Native
        # text above receives the private complete-panel collection; never
        # replay this caller-owned stack vector after its bounded transaction.
        code.label("consume_damage")
        code.raw(b"\xc7\x05" + struct.pack("<I", damage_ptr_va) + b"\x00\x00\x00\x00")
        code.jump("done")

        code.label("withdraw_damage")
        code.raw(b"\xc7\x05" + struct.pack("<I", damage_ptr_va) + b"\x00\x00\x00\x00")
        code.jump("done")

        code.label("hidden")
        code.raw(b"\xc7\x05" + struct.pack("<I", damage_ptr_va) + b"\x00\x00\x00\x00")
        # ToolTip::Draw can publish the object before the native hover-delay
        # timer changes its visibility flag.  Keep that unpublished candidate:
        # otherwise the next pre-Flip pass consumes it while hidden and no
        # later Draw is guaranteed to republish it when the timer fires.  Only
        # a tooltip which we actually painted (visible_latch == 1) owns a
        # physical generation and therefore has a hide transition to consume.
        code.raw(b"\x83\x3d" + struct.pack("<I", visible_latch_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "done")
        # Consume the transition before recording it. If a later hover creates
        # another generation, the visible path rearms the latch naturally.
        code.raw(b"\xc7\x05" + struct.pack("<I", visible_latch_va) + b"\x00\x00\x00\x00")
        code.raw(b"\xc7\x05" + struct.pack("<I", composition_pending_va) + b"\x00\x00\x00\x00")
        code.raw(b"\xc7\x05" + struct.pack("<I", text_pointer_va) + b"\x00\x00\x00\x00")
        code.raw(b"\xc7\x05" + struct.pack("<I", text_length_va) + b"\x00\x00\x00\x00")
        code.raw(b"\xc7\x05" + struct.pack("<I", object_ptr_va) + b"\x00\x00\x00\x00")
        for state_va in (
            mouse_owner_va,
            hover_target_va,
            captured_hover_owner_va,
            hover_identity_valid_va,
        ):
            code.raw(b"\xc7\x05" + struct.pack("<I", state_va) + b"\x00\x00\x00\x00")
        code.jump("done")

        code.label("inactive")
        code.raw(b"\xc7\x05" + struct.pack("<I", damage_ptr_va) + b"\x00\x00\x00\x00")
        code.raw(b"\xc7\x05" + struct.pack("<I", visible_latch_va) + b"\x00\x00\x00\x00")
        code.raw(b"\xc7\x05" + struct.pack("<I", composition_pending_va) + b"\x00\x00\x00\x00")
        code.raw(b"\xc7\x05" + struct.pack("<I", text_pointer_va) + b"\x00\x00\x00\x00")
        code.raw(b"\xc7\x05" + struct.pack("<I", text_length_va) + b"\x00\x00\x00\x00")
        for state_va in (
            mouse_owner_va,
            hover_target_va,
            captured_hover_owner_va,
            hover_identity_valid_va,
        ):
            code.raw(b"\xc7\x05" + struct.pack("<I", state_va) + b"\x00\x00\x00\x00")
        code.label("done")
        code.raw(b"\x61\x9d\xc3")
        return code.build()

    def build_tooltip_background_helper(
        self,
        *,
        wrapper_va: int,
        destination_handle_va: int,
        ddraw_va: int,
        outer_rect_va: int,
        inner_rect_va: int,
        presented_rect_va: int,
        panel_surface_va: int,
        panel_owner_va: int,
        panel_dimensions_va: int,
        panel_source_rect_va: int,
        panel_local_inner_rect_va: int,
        panel_descriptor_va: int,
        black_bltfx_va: int,
        white_bltfx_va: int,
        create_result_va: int,
        fill_result_va: int,
        blt_result_va: int,
        capture_mode_va: int,
        capture_result_va: int,
    ) -> bytes:
        """Present one cached output-scale panel on the room back page.

        Build an outer rectangle from the retained generation bounds, scaling
        its authored extent uniformly about the already-physical top-left,
        derive an inset rectangle with one scaled reference pixel, and lazily
        materialize that black-outline/white-interior image in a same-format
        off-screen DirectDraw surface. Persistent frames issue only one normal
        source Blt before native text. Direct color fills against the physical
        page synchronize on current Windows even without ``DDBLT_WAIT`` and
        halve 120 Hz presentation to 60 FPS, whereas the cached source follows
        GK3's ordinary asynchronous bitmap path. A capture-mode call made just
        after native text copies the completed pixels back into this surface;
        all later calls therefore replay one composed panel, not every glyph.
        A changed output extent or DirectDraw owner releases and recreates the
        cache; the toolbar's exact destructor releases its final generation.
        The helper resolves ToolTip::Draw's own same-frame destination handle
        and proves that wrapper's raw surface is the current back page before
        either presenting or capturing. It never borrows CursorManager's last
        surface: on a static pure-2D screen that independently valid owner can
        remain bound to the alternating peer which is not about to Flip.
        """
        code = X86Emitter(base_va=wrapper_va)
        # The presenter has already snapshotted the generation bounds. Reading
        # that immutable copy is essential on cache replay because native
        # ToolTip fields may be dormant while the hover owner remains live.
        code.raw(b"\x60")

        # Write left/top, followed by scaled right/bottom, directly through a
        # running RECT pointer to keep this hot helper compact and auditable.
        code.raw(b"\xbe" + struct.pack("<I", presented_rect_va))
        code.raw(b"\xbf" + struct.pack("<I", outer_rect_va))
        code.raw(b"\xb9\x02\x00\x00\x00\xf3\xa5")
        for far_offset, origin_offset in ((8, 0), (12, 4)):
            code.raw(b"\xa1" + struct.pack("<I", presented_rect_va + far_offset))
            code.raw(b"\x2b\x05" + struct.pack("<I", presented_rect_va + origin_offset))
            code.call("scale_edge")
            code.raw(b"\x03\x05" + struct.pack("<I", presented_rect_va + origin_offset))
            code.raw(b"\xab")

        # Copy the outer rectangle while applying one scaled reference pixel
        # inward to each edge. EDX remains the inset throughout this loop.
        code.raw(b"\xb8\x01\x00\x00\x00")
        code.call("scale_edge")
        code.raw(b"\x8b\xd0")
        code.raw(b"\xbe" + struct.pack("<I", outer_rect_va))
        code.raw(b"\xbf" + struct.pack("<I", inner_rect_va))
        for operation in (b"\x03\xc2", b"\x03\xc2", b"\x2b\xc2", b"\x2b\xc2"):
            code.raw(b"\xad" + operation + b"\xab")

        # Retain the exact output dimensions and reject degenerate geometry
        # before touching the cache's COM lifetime.
        code.raw(b"\xa1" + struct.pack("<I", outer_rect_va + 8))
        code.raw(b"\x2b\x05" + struct.pack("<I", outer_rect_va) + b"\x85\xc0")
        code.jump_if(Condition.LESS_OR_EQUAL, "done")
        code.raw(b"\xa3" + struct.pack("<I", panel_dimensions_va))
        code.raw(b"\xa1" + struct.pack("<I", outer_rect_va + 12))
        code.raw(b"\x2b\x05" + struct.pack("<I", outer_rect_va + 4) + b"\x85\xc0")
        code.jump_if(Condition.LESS_OR_EQUAL, "done")
        code.raw(b"\xa3" + struct.pack("<I", panel_dimensions_va + 4))

        # Reuse only a cache created by the current DirectDraw object at the
        # current physical extent. Mode changes cannot retain stale surfaces.
        code.raw(b"\x8b\x35" + struct.pack("<I", panel_surface_va) + b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "create")
        code.raw(b"\xa1" + struct.pack("<I", ddraw_va) + b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "release")
        code.raw(b"\x3b\x05" + struct.pack("<I", panel_owner_va))
        code.jump_if(Condition.NOT_EQUAL, "release")
        code.raw(b"\xa1" + struct.pack("<I", panel_dimensions_va))
        code.raw(b"\x3b\x05" + struct.pack("<I", panel_descriptor_va + 0x0C))
        code.jump_if(Condition.NOT_EQUAL, "release")
        code.raw(b"\xa1" + struct.pack("<I", panel_dimensions_va + 4))
        code.raw(b"\x3b\x05" + struct.pack("<I", panel_descriptor_va + 0x08))
        code.jump_if(Condition.EQUAL, "present")

        code.label("release")
        code.raw(b"\x8b\x06\x56\xff\x50\x08")
        code.raw(b"\x31\xc0")
        code.raw(b"\xa3" + struct.pack("<I", panel_surface_va))
        code.raw(b"\xa3" + struct.pack("<I", panel_owner_va))

        code.label("create")
        code.raw(b"\x8b\x1d" + struct.pack("<I", ddraw_va) + b"\x85\xdb")
        code.jump_if(Condition.EQUAL, "done")
        # Publish the descriptor and matching local rectangles before the COM
        # call; validity is the returned non-null surface pointer.
        code.raw(b"\xa1" + struct.pack("<I", panel_dimensions_va + 4))
        code.raw(b"\xa3" + struct.pack("<I", panel_descriptor_va + 0x08))
        code.raw(b"\xa1" + struct.pack("<I", panel_dimensions_va))
        code.raw(b"\xa3" + struct.pack("<I", panel_descriptor_va + 0x0C))
        code.raw(b"\x31\xc0")
        code.raw(b"\xa3" + struct.pack("<I", panel_source_rect_va))
        code.raw(b"\xa3" + struct.pack("<I", panel_source_rect_va + 4))
        code.raw(b"\xa1" + struct.pack("<I", panel_dimensions_va))
        code.raw(b"\xa3" + struct.pack("<I", panel_source_rect_va + 8))
        code.raw(b"\xa1" + struct.pack("<I", panel_dimensions_va + 4))
        code.raw(b"\xa3" + struct.pack("<I", panel_source_rect_va + 12))
        for inner_offset, outer_offset in ((0, 0), (4, 4), (8, 0), (12, 4)):
            code.raw(b"\xa1" + struct.pack("<I", inner_rect_va + inner_offset))
            code.raw(b"\x2b\x05" + struct.pack("<I", outer_rect_va + outer_offset))
            code.raw(b"\xa3" + struct.pack("<I", panel_local_inner_rect_va + inner_offset))

        code.raw(b"\x8b\x03\x6a\x00")
        code.raw(b"\x68" + struct.pack("<I", panel_surface_va))
        code.raw(b"\x68" + struct.pack("<I", panel_descriptor_va))
        code.raw(b"\x53\xff\x50\x18")
        code.raw(b"\xa3" + struct.pack("<I", create_result_va) + b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\x8b\x35" + struct.pack("<I", panel_surface_va) + b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x89\x1d" + struct.pack("<I", panel_owner_va))

        # Build the immutable panel once. These two synchronous fills are paid
        # only for a new cache, never in the persistent frame loop.
        for rect_va, effect_va in (
            (panel_source_rect_va, black_bltfx_va),
            (panel_local_inner_rect_va, white_bltfx_va),
        ):
            code.raw(b"\x8b\x06")
            code.raw(b"\x68" + struct.pack("<I", effect_va))
            code.raw(b"\x68" + struct.pack("<I", self._ddblt_colorfill_wait))
            code.raw(b"\x6a\x00\x6a\x00")
            code.raw(b"\x68" + struct.pack("<I", rect_va))
            code.raw(b"\x56\xff\x50\x14")
            code.raw(b"\xa3" + struct.pack("<I", fill_result_va) + b"\x85\xc0")
            code.jump_if(Condition.NOT_EQUAL, "release_failed")

        code.label("present")
        # Resolve the exact destination published by this frame's ToolTip
        # producer. The resource manager's nested table is torn down before
        # its outer allocation, so validate both levels before calling the
        # stock encoded-handle resolver.
        code.raw(b"\x8b\x1d" + struct.pack("<I", destination_handle_va) + b"\x85\xdb")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x0d" + struct.pack("<I", self.profile.address("resource.manager")))
        code.raw(b"\x85\xc9")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x68\x24\x01\x00\x00\x51\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\x8b\x0d" + struct.pack("<I", self.profile.address("resource.manager")))
        code.raw(b"\x83\xb9\x20\x01\x00\x00\x00")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x53")
        code.call_absolute(self.profile.address("bitmap.resolve_resource"))
        code.raw(b"\x8b\xf8\x85\xff")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x6a\x34\x57\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\x8b\x6f\x30\x85\xed")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x6a\x30\x55\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\xa1" + struct.pack("<I", self.profile.address("transition.back_surface_ptr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x3b\x45\x2c")
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\x8b\x6d\x2c\x85\xed")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x35" + struct.pack("<I", panel_surface_va) + b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x83\x3d" + struct.pack("<I", capture_mode_va) + b"\x00")
        code.jump_if(Condition.NOT_EQUAL, "capture")
        code.raw(b"\x8b\x7d\x00")
        # The cache exactly matches the destination extent. BltFast follows
        # the same non-synchronizing path as GK3's glyph sprites; using the
        # general Blt slot here unnecessarily serialized with the next Flip.
        code.raw(b"\x6a\x00")
        code.raw(b"\x68" + struct.pack("<I", panel_source_rect_va))
        code.raw(b"\x56")
        code.raw(b"\xff\x35" + struct.pack("<I", outer_rect_va + 4))
        code.raw(b"\xff\x35" + struct.pack("<I", outer_rect_va))
        code.raw(b"\x55\xff\x57\x1c")
        code.raw(b"\xa3" + struct.pack("<I", blt_result_va))
        code.jump("done")

        code.label("capture")
        # Destination and source reverse for the one-time composition capture:
        # cache.BltFast(0, 0, physicalBack, &outer, 0).
        code.raw(b"\x8b\x3e")
        code.raw(b"\x6a\x00")
        code.raw(b"\x68" + struct.pack("<I", outer_rect_va))
        code.raw(b"\x55\x6a\x00\x6a\x00")
        code.raw(b"\x56\xff\x57\x1c")
        code.raw(b"\xa3" + struct.pack("<I", capture_result_va))
        code.jump("done")

        code.label("release_failed")
        code.raw(b"\x8b\x06\x56\xff\x50\x08")
        code.raw(b"\x31\xc0")
        code.raw(b"\xa3" + struct.pack("<I", panel_surface_va))
        code.raw(b"\xa3" + struct.pack("<I", panel_owner_va))

        code.label("done")
        code.raw(b"\x61\xc3")

        # EAX is a nonnegative authored extent. Use unsigned arithmetic and
        # ceil division so panel coverage cannot leave a one-pixel seam.
        code.label("scale_edge")
        code.raw(b"\xf7\x25" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\x05\xff\x02\x00\x00")
        code.raw(b"\x83\xd2\x00")
        code.raw(b"\xb9\x00\x03\x00\x00\xf7\xf1\xc3")
        return code.build()

    def build_tooltip_transfer_affine(
        self,
        *,
        wrapper_va: int,
        downstream_va: int,
        object_ptr_va: int,
        dest_rect_va: int,
        transform_count_va: int,
    ) -> bytes:
        """Map one native tooltip transfer about its physical top-left.

        ``ECX`` points at the common blitter's live PUSHAD frame. Tooltip
        layout has already positioned the anchor in physical coordinates, but
        native glyph/border submissions retain 768-line offsets and extents.
        Replace only the saved destination RECT, restore the dispatcher frame,
        and tail-enter the unchanged downstream blitter. The separate panel
        helper owns the non-blitted background.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x8b\xe9")
        code.raw(b"\x8b\x35" + struct.pack("<I", object_ptr_va) + b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x5d\x28\x85\xdb")
        code.jump_if(Condition.EQUAL, "done")

        code.raw(b"\x8b\xd6\x8b\xf3\xbf" + struct.pack("<I", dest_rect_va))
        code.raw(b"\xb9\x04\x00\x00\x00\xf3\xa5\x8b\xf2")
        code.raw(b"\x31\xff")
        for rect_offset, root_offset in ((0, 0x1C), (4, 0x20)):
            code.raw(b"\xa1" + struct.pack("<I", dest_rect_va + rect_offset))
            code.raw(b"\x8b\x5e" + bytes([root_offset]) + b"\x2b\xc3")
            code.call("scale_edge")
            code.raw(b"\xa3" + struct.pack("<I", dest_rect_va + rect_offset))
        code.raw(b"\xbf\xff\x02\x00\x00")
        for rect_offset, root_offset in ((8, 0x1C), (12, 0x20)):
            code.raw(b"\xa1" + struct.pack("<I", dest_rect_va + rect_offset))
            code.raw(b"\x8b\x5e" + bytes([root_offset]) + b"\x2b\xc3")
            code.call("scale_edge")
            code.raw(b"\xa3" + struct.pack("<I", dest_rect_va + rect_offset))

        code.raw(b"\xc7\x45\x28" + struct.pack("<I", dest_rect_va))
        code.raw(b"\xff\x05" + struct.pack("<I", transform_count_va))
        code.label("done")
        code.raw(b"\x61")
        code.jump_absolute(downstream_va)

        # EAX is a local edge and EBX its physical anchor. EDI is zero for
        # near edges and 767 for ceil-rounded far-edge coverage.
        code.label("scale_edge")
        code.raw(b"\x0f\xaf\x05" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\x03\xc7\x99\xb9\x00\x03\x00\x00\xf7\xf9\x03\xc3\xc3")
        return code.build()
