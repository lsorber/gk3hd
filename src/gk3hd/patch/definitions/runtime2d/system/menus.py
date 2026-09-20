"""Compile left/right menu geometry, hover, and tooltip presentation."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.binary.x86 import BranchOpcode, X86Emitter
from gk3hd.patch.definitions.runtime2d.geometry import AUTHORED_FRAME_HEIGHT
from gk3hd.patch.definitions.runtime2d.layout import (
    SYSTEM_CONTROL_ACTION_LIFETIME_RETIRE_COUNT_OFFSET,
    SYSTEM_CONTROL_ACTION_LIFETIME_STATE_END_OFFSET,
    SYSTEM_CONTROL_ACTION_TOOLTIP_CALL_COUNT_OFFSET,
    SYSTEM_CONTROL_ACTION_TOOLTIP_STATE_END_OFFSET,
    SYSTEM_CONTROL_ACTION_TOOLTIP_TOOLBAR_INVERSE_COUNT_OFFSET,
    SYSTEM_CONTROL_ACTION_TOOLTIP_TOOLBAR_INVERSE_STATE_END_OFFSET,
    SYSTEM_CONTROL_DROPDOWN_HIGHLIGHT_TRACE_OFFSET,
    SYSTEM_CONTROL_DROPDOWN_HIGHLIGHT_TRACE_SIZE,
    SYSTEM_CONTROL_DROPDOWN_SEED_BUDGET_OFFSET,
    SYSTEM_CONTROL_MODAL_DAMAGE_RECT_OFFSET,
    SYSTEM_CONTROL_MODAL_DAMAGE_REGION_OFFSET,
    SYSTEM_CONTROL_MODAL_DAMAGE_STATE_END_OFFSET,
    SYSTEM_CONTROL_RETAINED_OVERLAY_STATE_END_OFFSET,
    SYSTEM_CONTROL_TOOLBAR_INPUT_STATE_END_OFFSET,
    SYSTEM_CONTROL_TOOLBAR_INPUT_VALID_OFFSET,
    SYSTEM_CONTROL_TOOLBAR_SEED_BUDGET_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_DRAW_DEPTH_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_OBJECT_PTR_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_OUTER_RECT_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_PANEL_DESCRIPTOR_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_PANEL_WHITE_BLTFX_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_RENDER_DAMAGE_REGION_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_STATE_END_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_TEXT_POINTER_OFFSET,
)
from gk3hd.patch.definitions.runtime2d.system.menu_action import ActionMenuFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.menu_dropdown import DropdownFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.menu_tooltip import TooltipFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.shared import SystemCompilerContext

if TYPE_CHECKING:
    from gk3hd.patch.binary.mutations import ExecutableMutationPlan
    from gk3hd.patch.binary.payload import SegmentPayloadBuilder
    from gk3hd.patch.definitions.runtime2d.system.fixed_screens import FixedScreenFeatureCompiler
    from gk3hd.patch.definitions.runtime2d.system.menu_exports import (
        ActionMenuRuntimeExports,
        DropdownRuntimeExports,
        TooltipRuntimeExports,
    )


@dataclass(frozen=True, slots=True)
class MenuFeatureCompiler(SystemCompilerContext):
    """Fit every in-room action menu through one coherent UI affine.

    Outcome:
        Left-click actions, right-click toolbar panels, nested menus, hover
        states, cursor feedback, and tooltips retain reference-relative scale.
    Before:
        GK3 mixes physical menu anchors with authored bitmap extents and
        hit rectangles, so modern modes separate, overlap, or mis-hit controls.
    After:
        One menu-owned transform maps drawing and input through the same live
        geometry while preserving native animation and tooltip lifetimes.
    Strategy:
        Compile class-scoped root, final-blit, inverse-input, and tooltip
        helpers behind the shared 2D dispatcher. No output resolution is named.
    Boundaries:
        This feature owns menu and tooltip redirects; the facade only composes
        its plan. Cursor composition and 3D presentation retain independent
        runtime owners.
    """

    def dropdown_feature(self) -> DropdownFeatureCompiler:
        """Bind the dropdown compiler to this immutable runtime context."""
        return DropdownFeatureCompiler(
            symbols=self.symbols,
            profile=self.profile,
            room_rendering_abi=self.room_rendering_abi,
            transition_abi=self.transition_abi,
        )

    def action_feature(self) -> ActionMenuFeatureCompiler:
        """Bind the action-menu compiler to this immutable runtime context."""
        return ActionMenuFeatureCompiler(
            symbols=self.symbols,
            profile=self.profile,
            room_rendering_abi=self.room_rendering_abi,
            transition_abi=self.transition_abi,
        )

    def tooltip_feature(self) -> TooltipFeatureCompiler:
        """Bind the tooltip compiler to this immutable runtime context."""
        return TooltipFeatureCompiler(
            symbols=self.symbols,
            profile=self.profile,
            room_rendering_abi=self.room_rendering_abi,
            transition_abi=self.transition_abi,
        )

    def emit_state(
        self,
        system_payload: SegmentPayloadBuilder,
        control_payload: SegmentPayloadBuilder,
        *,
        control_va: int,
    ) -> None:
        """Own all persistent data interpreted by menu and tooltip code."""
        system_payload.place(
            label="ActionMenu layout state",
            offset=self._off_action_layout_state,
            payload=b"\x00" * 0x14 + struct.pack("<If", AUTHORED_FRAME_HEIGHT, 1.0) + b"\x00" * 8,
        )
        control_payload.reserve(
            label="dropdown highlight trace",
            offset=SYSTEM_CONTROL_DROPDOWN_HIGHLIGHT_TRACE_OFFSET,
            size=SYSTEM_CONTROL_DROPDOWN_HIGHLIGHT_TRACE_SIZE,
        )
        control_payload.reserve(
            label="dropdown publication",
            offset=self._off_control_dropdown_pending_ptr,
            size=12,
        )
        control_payload.reserve(
            label="toolbar input affine",
            offset=SYSTEM_CONTROL_TOOLBAR_INPUT_VALID_OFFSET,
            size=SYSTEM_CONTROL_TOOLBAR_INPUT_STATE_END_OFFSET
            - SYSTEM_CONTROL_TOOLBAR_INPUT_VALID_OFFSET,
        )
        control_payload.reserve(
            label="tooltip publication state",
            offset=SYSTEM_CONTROL_TOOLTIP_DRAW_DEPTH_OFFSET,
            size=SYSTEM_CONTROL_TOOLTIP_OBJECT_PTR_OFFSET
            - SYSTEM_CONTROL_TOOLTIP_DRAW_DEPTH_OFFSET
            + 4,
        )
        control_payload.reserve(
            label="dropdown page seed",
            offset=SYSTEM_CONTROL_DROPDOWN_SEED_BUDGET_OFFSET,
            size=4,
        )
        control_payload.reserve(
            label="toolbar page seed",
            offset=SYSTEM_CONTROL_TOOLBAR_SEED_BUDGET_OFFSET,
            size=4,
        )
        control_payload.reserve(
            label="tooltip page and geometry state",
            offset=SYSTEM_CONTROL_TOOLTIP_OUTER_RECT_OFFSET,
            size=SYSTEM_CONTROL_TOOLTIP_STATE_END_OFFSET - SYSTEM_CONTROL_TOOLTIP_OUTER_RECT_OFFSET,
        )

        # Tooltips need a retained off-screen panel because the native object
        # and its damage list can disappear before the next physical page is
        # presented. Seed the DirectDraw descriptors once; live pointers and
        # rectangles in the same bounded state are populated at run time.
        panel_descriptor = bytearray(self._ddsd_size)
        struct.pack_into("<I", panel_descriptor, 0, self._ddsd_size)
        struct.pack_into("<I", panel_descriptor, 4, self._ddsd_caps_height_width)
        struct.pack_into("<I", panel_descriptor, 0x68, self._tooltip_panel_caps)
        white_bltfx = bytearray(self._ddbltfx_size)
        struct.pack_into("<I", white_bltfx, 0, self._ddbltfx_size)
        struct.pack_into("<I", white_bltfx, 0x50, 0xFFFFFFFF)
        retained_state = bytearray(
            SYSTEM_CONTROL_RETAINED_OVERLAY_STATE_END_OFFSET
            - SYSTEM_CONTROL_TOOLTIP_TEXT_POINTER_OFFSET
        )
        outer_rect_va = control_va + SYSTEM_CONTROL_TOOLTIP_OUTER_RECT_OFFSET
        struct.pack_into(
            "<IIII",
            retained_state,
            SYSTEM_CONTROL_TOOLTIP_RENDER_DAMAGE_REGION_OFFSET
            - SYSTEM_CONTROL_TOOLTIP_TEXT_POINTER_OFFSET,
            0,
            outer_rect_va,
            outer_rect_va + 16,
            0,
        )
        descriptor_offset = (
            SYSTEM_CONTROL_TOOLTIP_PANEL_DESCRIPTOR_OFFSET
            - SYSTEM_CONTROL_TOOLTIP_TEXT_POINTER_OFFSET
        )
        retained_state[descriptor_offset : descriptor_offset + len(panel_descriptor)] = (
            panel_descriptor
        )
        white_bltfx_offset = (
            SYSTEM_CONTROL_TOOLTIP_PANEL_WHITE_BLTFX_OFFSET
            - SYSTEM_CONTROL_TOOLTIP_TEXT_POINTER_OFFSET
        )
        retained_state[white_bltfx_offset : white_bltfx_offset + len(white_bltfx)] = white_bltfx
        control_payload.place(
            label="retained tooltip state",
            offset=SYSTEM_CONTROL_TOOLTIP_TEXT_POINTER_OFFSET,
            payload=bytes(retained_state),
        )
        control_payload.reserve(
            label="ActionMenu tooltip trace",
            offset=SYSTEM_CONTROL_ACTION_TOOLTIP_CALL_COUNT_OFFSET,
            size=SYSTEM_CONTROL_ACTION_TOOLTIP_STATE_END_OFFSET
            - SYSTEM_CONTROL_ACTION_TOOLTIP_CALL_COUNT_OFFSET,
        )
        control_payload.reserve(
            label="ActionMenu lifetime state",
            offset=SYSTEM_CONTROL_ACTION_LIFETIME_RETIRE_COUNT_OFFSET,
            size=SYSTEM_CONTROL_ACTION_LIFETIME_STATE_END_OFFSET
            - SYSTEM_CONTROL_ACTION_LIFETIME_RETIRE_COUNT_OFFSET,
        )
        modal_damage_rect_va = control_va + SYSTEM_CONTROL_MODAL_DAMAGE_RECT_OFFSET
        control_payload.place(
            label="modal damage collection",
            offset=SYSTEM_CONTROL_MODAL_DAMAGE_REGION_OFFSET,
            payload=struct.pack(
                "<IIII",
                0,
                modal_damage_rect_va,
                modal_damage_rect_va + 16,
                0,
            )
            + bytes(
                SYSTEM_CONTROL_MODAL_DAMAGE_STATE_END_OFFSET
                - SYSTEM_CONTROL_MODAL_DAMAGE_RECT_OFFSET
            ),
        )
        control_payload.reserve(
            label="toolbar tooltip inverse trace",
            offset=SYSTEM_CONTROL_ACTION_TOOLTIP_TOOLBAR_INVERSE_COUNT_OFFSET,
            size=SYSTEM_CONTROL_ACTION_TOOLTIP_TOOLBAR_INVERSE_STATE_END_OFFSET
            - SYSTEM_CONTROL_ACTION_TOOLTIP_TOOLBAR_INVERSE_COUNT_OFFSET,
        )

    def emit_dropdown_runtime(
        self,
        payload: SegmentPayloadBuilder,
        *,
        system_va: int,
        control_va: int,
    ) -> DropdownRuntimeExports:
        """Compile the dropdown domain through its dedicated owner."""
        return self.dropdown_feature().emit_runtime(
            payload,
            system_va=system_va,
            control_va=control_va,
        )

    def emit_action_runtime(
        self,
        system_payload: SegmentPayloadBuilder,
        control_payload: SegmentPayloadBuilder,
        *,
        system_va: int,
        control_va: int,
        dropdown: DropdownRuntimeExports,
        cursor_surface_classifier_va: int,
        fixed_screens: FixedScreenFeatureCompiler,
    ) -> ActionMenuRuntimeExports:
        """Compile action-menu and toolbar roots through their dedicated owner."""
        return self.action_feature().emit_runtime(
            system_payload,
            control_payload,
            system_va=system_va,
            control_va=control_va,
            dropdown=dropdown,
            cursor_surface_classifier_va=cursor_surface_classifier_va,
            fixed_screens=fixed_screens,
        )

    def emit_tooltip_runtime(
        self,
        payload: SegmentPayloadBuilder,
        *,
        system_va: int,
        control_va: int,
        action: ActionMenuRuntimeExports,
    ) -> TooltipRuntimeExports:
        """Compile hover lookup and tooltip presentation through their owner."""
        return self.tooltip_feature().emit_runtime(
            payload,
            system_va=system_va,
            control_va=control_va,
            action=action,
        )

    def plan_hooks(
        self,
        plan: ExecutableMutationPlan,
        *,
        action_root_wrapper_va: int,
        action_destructor_wrapper_va: int,
        toolbar_root_wrapper_va: int,
        toolbar_destructor_wrapper_va: int,
        toolbar_layout_va: int,
        toolbar_cursor_warp_va: int,
        tooltip_visibility_wrapper_va: int,
        tooltip_draw_wrapper_va: int,
        dropdown_draw_wrapper_va: int,
        dropdown_visibility_wrapper_va: int,
        dropdown_highlight_wrapper_va: int,
        tooltip_base_wrapper_va: int,
        tooltip_border_wrapper_va: int,
        modal_tooltip_resolver_va: int,
        fixed_layer_epilogue_wrapper_va: int,
    ) -> None:
        """Own menu, hover, dropdown, and tooltip native redirects."""
        plan.branch(
            label="toolbar fitted layout commit",
            opcode=BranchOpcode.CALL,
            site_va=self.profile.address("ingame_toolbar.layout_commit_call"),
            expected=bytes.fromhex("e8 07 00 00 00"),
            target_va=toolbar_layout_va,
        )
        for name in ("sound", "lod", "gamma", "volume"):
            site_va = self.profile.address(f"ingame_toolbar.{name}_cursor_return_call")
            original = X86Emitter(base_va=site_va)
            original.call_absolute(self.profile.address("input.set_cursor_position"))
            plan.branch(
                label=f"toolbar {name} slider cursor return",
                opcode=BranchOpcode.CALL,
                site_va=site_va,
                expected=original.build(),
                target_va=toolbar_cursor_warp_va,
            )
        for label, slot_va, expected_va, target_va in (
            (
                "ActionMenu draw",
                self._action_draw_slot_va,
                self._native_draw_va,
                action_root_wrapper_va,
            ),
            (
                "ActionMenu destructor",
                self._action_destructor_slot_va,
                self._native_action_destructor_va,
                action_destructor_wrapper_va,
            ),
            (
                "in-game toolbar draw",
                self._ingame_toolbar_draw_slot_va,
                self._native_draw_va,
                toolbar_root_wrapper_va,
            ),
            (
                "in-game toolbar destructor",
                self._ingame_toolbar_destructor_slot_va,
                self._native_ingame_toolbar_destructor_va,
                toolbar_destructor_wrapper_va,
            ),
            (
                "tooltip visibility",
                self._tooltip_visibility_slot_va,
                self._native_tooltip_visibility_va,
                tooltip_visibility_wrapper_va,
            ),
            (
                "tooltip draw",
                self._tooltip_draw_slot_va,
                self._native_tooltip_draw_va,
                tooltip_draw_wrapper_va,
            ),
            (
                "resolution dropdown draw",
                self._resolution_dropdown_draw_slot_va,
                self._native_resolution_dropdown_draw_va,
                dropdown_draw_wrapper_va,
            ),
            (
                "resolution dropdown visibility",
                self._resolution_dropdown_visibility_slot_va,
                self._native_resolution_dropdown_visibility_va,
                dropdown_visibility_wrapper_va,
            ),
            (
                "resolution dropdown highlight",
                self._solid_color_draw_slot_va,
                self._native_solid_color_draw_va,
                dropdown_highlight_wrapper_va,
            ),
        ):
            plan.pointer(
                label=label,
                slot_va=slot_va,
                expected=expected_va,
                target_va=target_va,
            )
        plan.branch(
            label=self._tooltip_base_site_name,
            opcode=BranchOpcode.CALL,
            site_va=self._site_va(self._tooltip_base_site_name),
            expected=self._site_bytes(self._tooltip_base_site_name),
            target_va=tooltip_base_wrapper_va,
        )
        for name in self._tooltip_border_site_names:
            plan.branch(
                label=name,
                opcode=BranchOpcode.CALL,
                site_va=self._site_va(name),
                expected=self._site_bytes(name),
                target_va=tooltip_border_wrapper_va,
            )
        for name in self._action_tooltip_resolve_site_names:
            plan.branch(
                label=name,
                opcode=BranchOpcode.CALL,
                site_va=self._site_va(name),
                expected=self._site_bytes(name),
                target_va=modal_tooltip_resolver_va,
                size=len(self._site_bytes(name)),
            )
        fixed_layer_epilogue_site_va = self._site_va(self._tooltip_fixed_layer_epilogue_site_name)
        plan.branch(
            label=self._tooltip_fixed_layer_epilogue_site_name,
            opcode=BranchOpcode.JUMP,
            site_va=fixed_layer_epilogue_site_va,
            expected=self._site_bytes(self._tooltip_fixed_layer_epilogue_site_name),
            target_va=fixed_layer_epilogue_wrapper_va,
            size=len(self._site_bytes(self._tooltip_fixed_layer_epilogue_site_name)),
        )
