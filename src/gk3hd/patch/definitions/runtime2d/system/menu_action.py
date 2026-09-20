"""Compile ActionMenu and right-click toolbar geometry and lifetime."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.geometry import AUTHORED_FRAME_HEIGHT
from gk3hd.patch.definitions.runtime2d.layout import (
    SYSTEM_CONTROL_ACTION_LIFETIME_LAST_LAYER_OFFSET,
    SYSTEM_CONTROL_ACTION_LIFETIME_LAST_ROOT_OFFSET,
    SYSTEM_CONTROL_ACTION_LIFETIME_RETIRE_COUNT_OFFSET,
    SYSTEM_CONTROL_ACTION_TOOLTIP_FRAME_REQUEST_PENDING_OFFSET,
    SYSTEM_CONTROL_MODAL_DAMAGE_RECT_OFFSET,
    SYSTEM_CONTROL_MODAL_DAMAGE_REGION_OFFSET,
    SYSTEM_CONTROL_TOOLBAR_INPUT_SOURCE_RECT_OFFSET,
    SYSTEM_CONTROL_TOOLBAR_INPUT_TARGET_RECT_OFFSET,
    SYSTEM_CONTROL_TOOLBAR_INPUT_VALID_OFFSET,
    SYSTEM_CONTROL_TOOLBAR_SEED_BUDGET_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_CAPTURED_HOVER_OWNER_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_COMPOSITION_PENDING_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_DAMAGE_PTR_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_HOVER_IDENTITY_VALID_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_HOVER_TARGET_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_MOUSE_OWNER_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_OBJECT_PTR_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_PANEL_OWNER_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_PANEL_SURFACE_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_TEXT_LENGTH_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_TEXT_POINTER_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_VISIBLE_LATCH_OFFSET,
)
from gk3hd.patch.definitions.runtime2d.system.menu_exports import (
    ActionMenuRuntimeExports,
    DropdownRuntimeExports,
)
from gk3hd.patch.definitions.runtime2d.system.shared import SystemCompilerContext
from gk3hd.patch.definitions.runtime2d.system.toolbar_layout import (
    build_toolbar_cursor_warp,
    build_toolbar_layout,
)
from gk3hd.patch.definitions.runtime2d.system.toolbar_preview import (
    build_preview_prepare,
    emit_preview_source,
)

if TYPE_CHECKING:
    from gk3hd.patch.binary.payload import SegmentPayloadBuilder
    from gk3hd.patch.definitions.runtime2d.system.fixed_screens import FixedScreenFeatureCompiler


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionMenuFeatureCompiler(SystemCompilerContext):
    """Keep left-click actions and the right-click toolbar spatially coherent.

    Outcome:
        Every action tile and toolbar control draws, highlights, receives input,
        and tears down at the reference-relative scale on any live framebuffer.

    Before:
        GK3 combines physical popup anchors with authored child extents and
        damage. At larger displays this separates or overlaps buttons, leaves
        stale pixels on one DirectDraw page, and sends hover input elsewhere.

    After:
        Each modal root publishes one affine and one lifetime. Composition,
        complete modal damage, inverse input, page seeding, and destruction all
        consume that same state.

    Strategy:
        Wrap the native ActionMenu and toolbar root lifecycles, derive geometry
        from their live root rectangles, transform their final transfers in the
        shared dispatcher, and export only the helpers needed by dropdown and
        tooltip owners.

    Boundaries:
        Dropdown rows and tooltip composition have separate feature owners.
        Cursor presentation, ordinary room rendering, and display cadence are
        not changed here.
    """

    def emit_runtime(
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
        """Compile ActionMenu and toolbar drawing, input affine, and lifetime."""
        action_root_va = control_va + self._off_control_action_root_draw_wrapper
        action_destructor_va = control_va + self._off_control_action_destructor_wrapper
        toolbar_root_va = control_va + self._off_control_ingame_toolbar_draw_wrapper
        preview_prepare_va = control_va + self._off_toolbar_preview_prepare
        preview_surface_va = control_va + self._off_toolbar_preview_surface
        control_payload.place(
            label="toolbar selected-item surface",
            offset=self._off_toolbar_preview_surface,
            payload=bytes(4),
            limit=self._off_toolbar_preview_prepare,
        )
        control_payload.place(
            label="toolbar selected-item layout",
            offset=self._off_toolbar_preview_prepare,
            payload=build_preview_prepare(
                wrapper_va=preview_prepare_va,
                surface_va=preview_surface_va,
                manager_va=self.profile.address("engine.loop"),
                resolve_va=self._resolve_bitmap_resource_va,
            ),
            limit=self._off_toolbar_preview_prepare_limit,
        )
        toolbar_destructor_va = control_va + self._off_ingame_toolbar_destructor_wrapper
        toolbar_cursor_warp_va = control_va + self._off_toolbar_cursor_warp
        control_payload.place(
            label="toolbar slider cursor return",
            offset=self._off_toolbar_cursor_warp,
            payload=build_toolbar_cursor_warp(
                wrapper_va=toolbar_cursor_warp_va,
                physical_width_va=self._physical_width_va,
                input_valid_va=control_va + SYSTEM_CONTROL_TOOLBAR_INPUT_VALID_OFFSET,
                source_rect_va=control_va + SYSTEM_CONTROL_TOOLBAR_INPUT_SOURCE_RECT_OFFSET,
                target_va=self.profile.address("input.set_cursor_position"),
            ),
            limit=self._off_ingame_toolbar_destructor_wrapper,
        )
        action_layout_va = control_va + self._off_action_layout_helper
        action_lifetime_va = control_va + self._off_action_lifetime_helper
        toolbar_blt_va = system_va + self._off_toolbar_blt_helper
        toolbar_layout_va = control_va + self._off_toolbar_layout
        control_payload.place(
            label="toolbar fitted layout commit",
            offset=self._off_toolbar_layout,
            payload=build_toolbar_layout(
                wrapper_va=toolbar_layout_va,
                physical_width_va=self._physical_width_va,
                input_valid_va=control_va + SYSTEM_CONTROL_TOOLBAR_INPUT_VALID_OFFSET,
                target_va=self.profile.address("ingame_toolbar.layout_commit"),
            ),
            limit=self._off_modal_tooltip_resolver_wrapper,
        )
        action_layout = self.build_action_layout_helper(
            wrapper_va=action_layout_va,
            state_va=system_va + self._off_action_layout_state,
        )
        action_root = fixed_screens.build_root_draw_wrapper(
            wrapper_va=action_root_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            transform_mode=self._mode_physical_canvas,
            input_enabled=False,
            target_va=self._native_draw_va,
            pre_draw_va=action_layout_va,
            post_draw_va=action_layout_va,
            full_damage_region_va=control_va + SYSTEM_CONTROL_MODAL_DAMAGE_REGION_OFFSET,
            full_damage_rect_va=control_va + SYSTEM_CONTROL_MODAL_DAMAGE_RECT_OFFSET,
            full_damage_uses_root_rect=True,
            full_damage_budget_va=control_va + SYSTEM_CONTROL_TOOLBAR_SEED_BUDGET_OFFSET,
        )
        action_destructor = fixed_screens.build_destructor_wrapper(
            wrapper_va=action_destructor_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            target_va=self._native_action_destructor_va,
            extra_clear_vas=(
                control_va + SYSTEM_CONTROL_TOOLBAR_SEED_BUDGET_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLBAR_INPUT_VALID_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_OWNER_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_OBJECT_PTR_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_DAMAGE_PTR_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_VISIBLE_LATCH_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_COMPOSITION_PENDING_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_TEXT_POINTER_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_TEXT_LENGTH_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_MOUSE_OWNER_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_HOVER_TARGET_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_CAPTURED_HOVER_OWNER_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_HOVER_IDENTITY_VALID_OFFSET,
            ),
            extra_release_vas=(control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_SURFACE_OFFSET,),
            publication_owner_va=system_va + self._off_action_layout_state + 0x20,
            pre_clear_vas=(
                system_va + self._off_action_layout_state + 0x20,
                control_va + SYSTEM_CONTROL_ACTION_TOOLTIP_FRAME_REQUEST_PENDING_OFFSET,
            ),
        )
        toolbar_root = fixed_screens.build_root_draw_wrapper(
            wrapper_va=toolbar_root_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            transform_mode=self._mode_popup,
            input_enabled=True,
            target_va=self._native_draw_va,
            full_damage_region_va=control_va + SYSTEM_CONTROL_MODAL_DAMAGE_REGION_OFFSET,
            full_damage_rect_va=control_va + SYSTEM_CONTROL_MODAL_DAMAGE_RECT_OFFSET,
            full_damage_uses_root_rect=True,
            full_damage_budget_va=control_va + SYSTEM_CONTROL_TOOLBAR_SEED_BUDGET_OFFSET,
            post_draw_va=dropdown.present_helper_va,
            post_draw_pass_args=True,
            pre_draw_va=preview_prepare_va,
        )
        toolbar_destructor = fixed_screens.build_destructor_wrapper(
            wrapper_va=toolbar_destructor_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            target_va=self._native_ingame_toolbar_destructor_va,
            extra_clear_vas=(
                preview_surface_va,
                control_va + self._off_control_dropdown_pending_ptr,
                control_va + SYSTEM_CONTROL_TOOLBAR_SEED_BUDGET_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLBAR_INPUT_VALID_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_OWNER_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_OBJECT_PTR_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_DAMAGE_PTR_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_VISIBLE_LATCH_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_COMPOSITION_PENDING_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_TEXT_POINTER_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_TEXT_LENGTH_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_MOUSE_OWNER_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_HOVER_TARGET_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_CAPTURED_HOVER_OWNER_OFFSET,
                control_va + SYSTEM_CONTROL_TOOLTIP_HOVER_IDENTITY_VALID_OFFSET,
            ),
            extra_release_vas=(control_va + SYSTEM_CONTROL_TOOLTIP_PANEL_SURFACE_OFFSET,),
        )
        action_lifetime = self.build_action_lifetime_helper(
            wrapper_va=action_lifetime_va,
            action_root_ptr_va=system_va + self._off_action_layout_state + 0x20,
            shared_root_ptr_va=system_va + self._off_root_ptr,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            transform_mode_va=system_va + self._off_transform_mode,
            retire_count_va=control_va + SYSTEM_CONTROL_ACTION_LIFETIME_RETIRE_COUNT_OFFSET,
            last_root_va=control_va + SYSTEM_CONTROL_ACTION_LIFETIME_LAST_ROOT_OFFSET,
            last_layer_va=control_va + SYSTEM_CONTROL_ACTION_LIFETIME_LAST_LAYER_OFFSET,
        )
        toolbar_blt = self.build_toolbar_blt_helper(
            wrapper_va=toolbar_blt_va,
            preview_surface_va=preview_surface_va,
            dropdown_ptr_va=control_va + self._off_control_dropdown_pending_ptr,
            root_ptr_va=system_va + self._off_root_ptr,
            source_rect_va=system_va + self._off_source_rect,
            target_rect_va=system_va + self._off_target_rect,
            dest_rect_va=system_va + self._off_dest_rect,
            transform_count_va=system_va + self._off_transform_count,
            clipped_source_rect_va=control_va + self._off_control_clipped_source_rect,
            cursor_surface_classifier_va=cursor_surface_classifier_va,
            input_snapshot_valid_va=control_va + SYSTEM_CONTROL_TOOLBAR_INPUT_VALID_OFFSET,
            input_snapshot_source_rect_va=(
                control_va + SYSTEM_CONTROL_TOOLBAR_INPUT_SOURCE_RECT_OFFSET
            ),
            input_snapshot_target_rect_va=(
                control_va + SYSTEM_CONTROL_TOOLBAR_INPUT_TARGET_RECT_OFFSET
            ),
        )
        system_payload.place(
            label="in-game toolbar blit helper",
            offset=self._off_toolbar_blt_helper,
            payload=toolbar_blt,
            limit=self._off_pause_draw_scope,
        )
        for label, offset, code, limit in (
            (
                "action-menu destructor",
                self._off_control_action_destructor_wrapper,
                action_destructor,
                self._off_control_action_destructor_wrapper_limit,
            ),
            (
                "in-game toolbar destructor",
                self._off_ingame_toolbar_destructor_wrapper,
                toolbar_destructor,
                self._off_ingame_toolbar_destructor_wrapper_limit,
            ),
            (
                "action-menu layout",
                self._off_action_layout_helper,
                action_layout,
                self._off_control_action_root_draw_wrapper,
            ),
            (
                "action-menu root",
                self._off_control_action_root_draw_wrapper,
                action_root,
                self._off_control_cursor_state,
            ),
            (
                "in-game toolbar root",
                self._off_control_ingame_toolbar_draw_wrapper,
                toolbar_root,
                self._off_resolution_dropdown_draw_wrapper,
            ),
            (
                "action-menu lifetime",
                self._off_action_lifetime_helper,
                action_lifetime,
                self._off_action_lifetime_helper_limit,
            ),
        ):
            control_payload.place(label=label, offset=offset, payload=code, limit=limit)
        return ActionMenuRuntimeExports(
            action_root_wrapper_va=action_root_va,
            action_destructor_wrapper_va=action_destructor_va,
            toolbar_root_wrapper_va=toolbar_root_va,
            toolbar_destructor_wrapper_va=toolbar_destructor_va,
            toolbar_layout_va=toolbar_layout_va,
            toolbar_cursor_warp_va=toolbar_cursor_warp_va,
            action_layout_helper_va=action_layout_va,
            action_lifetime_helper_va=action_lifetime_va,
            toolbar_blt_helper_va=toolbar_blt_va,
        )

    def build_action_layout_helper(
        self,
        *,
        wrapper_va: int,
        state_va: int,
    ) -> bytes:
        """Scale ActionMenu objects and hit rectangles around their native center."""
        # ActionMenu's variable set of transparent icons is emitted by the
        # compositor rather than the shared final Blt. Owning the class layout
        # is consequently narrower and more complete than recognizing those
        # color-keyed transfers downstream. The helper materializes final
        # physical object rectangles. Native Button containment consumes those
        # rectangles, while its subsequent 32x32 alpha-mask test receives a
        # private local-point adapter at the input boundary. Keeping those two
        # coordinate responsibilities separate preserves both exact visual
        # scale and the authored transparent hit mask. The helper itself
        # remains idempotent across repeated redraws.
        size_va = state_va
        center_x_va = state_va + 4
        center_y_va = state_va + 8
        cursor_x_va = state_va + 0x0C
        top_va = state_va + 0x10
        denominator_va = state_va + 0x14
        ratio_va = state_va + 0x18
        margin_va = state_va + 0x1C
        presented_root_va = state_va + 0x20

        # This helper now calls GK3's current-layer accessor, so unlike the
        # older position-independent form its emitter needs the final VA for a
        # correct near-CALL displacement.
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x60\x8b\xf1")
        # Object lifetime is independent of output geometry. Publish the exact
        # ActionMenu at every resolution so its destructor and the pre-Flip
        # membership oracle can retire retained room/cache/tooltip state. The
        # old early return at authored height left that state ownerless and let
        # the preceding room repaint a later CloseUp page.
        code.raw(b"\x8b\x5e\x50\x85\xdb")
        code.jump_if(Condition.LESS_OR_EQUAL, "done")
        code.raw(b"\x81\x3d" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(struct.pack("<I", AUTHORED_FRAME_HEIGHT))
        code.jump_if(Condition.BELOW_OR_EQUAL, "publish_authored_owner")

        # size = round(32 * physical_height / 768). This derives every mode
        # from the authored reference instead of enumerating output sizes.
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\xc1\xe0\x05\x05\x80\x01\x00\x00\x31\xd2")
        code.raw(b"\xb9\x00\x03\x00\x00\xf7\xf1")
        code.raw(b"\xa3" + struct.pack("<I", size_va))
        # Pointer motion makes native ActionMenu redraw restore its authored
        # 32-pixel children before this helper runs. Child width therefore is
        # not a durable "already mapped" sentinel: the same menu would map its
        # center again and visibly chase the cursor. Retain the first physical
        # center for this exact root until its destructor clears the pointer.
        code.raw(b"\x39\x35" + struct.pack("<I", presented_root_va))
        code.jump_if(Condition.EQUAL, "center_ready")
        code.raw(b"\x89\x35" + struct.pack("<I", presented_root_va))
        code.raw(b"\x8b\x46\x1c\x03\x46\x24\xd1\xf8")
        code.raw(b"\xa3" + struct.pack("<I", center_x_va))
        code.raw(b"\x8b\x46\x20\x03\x46\x28\xd1\xf8")
        code.raw(b"\xa3" + struct.pack("<I", center_y_va))

        # Native event dispatch constructs ActionMenu before Inventory's
        # temporary input-coordinate scope unwinds. Inventory therefore
        # supplies a fitted 1024x768 center, while the direct room renderer
        # already supplies physical coordinates. Convert only the Inventory
        # producer at this ownership boundary. The resulting object rectangles
        # remain stable while native Draw recreates its 32x32 children.
        code.call_absolute(self.profile.address("ui.current_layer"))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "center_ready")
        code.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("inventory.vtable")))
        code.jump_short_if(Condition.EQUAL, "reference_center")
        code.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("zodiac.vtable")))
        code.jump_if(Condition.NOT_EQUAL, "center_ready")
        code.label("reference_center")
        code.raw(b"\x8b\x0d" + struct.pack("<I", self._physical_width_va))
        code.raw(b"\x8b\x1d" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\x8b\xc1\x6b\xc0\x03\x8b\xd3\xc1\xe2\x02\x3b\xc2")
        code.jump_if(Condition.LESS, "map_center_narrow")
        # Wide mode uses scale=height/768 and a centered horizontal margin.
        code.raw(b"\x8b\xc3\xc1\xe0\x02\x99\xbf\x03\x00\x00\x00\xf7\xff")
        code.raw(b"\x2b\xc8\xd1\xf9\x89\x0d" + struct.pack("<I", margin_va))
        code.raw(b"\xa1" + struct.pack("<I", center_x_va))
        code.raw(b"\x0f\xaf\xc3\x99\xb9\x00\x03\x00\x00\xf7\xf9")
        code.raw(b"\x03\x05" + struct.pack("<I", margin_va))
        code.raw(b"\xa3" + struct.pack("<I", center_x_va))
        code.raw(b"\xa1" + struct.pack("<I", center_y_va))
        code.raw(b"\x0f\xaf\xc3\x99\xb9\x00\x03\x00\x00\xf7\xf9")
        code.raw(b"\xa3" + struct.pack("<I", center_y_va))
        code.jump("center_ready")
        code.label("map_center_narrow")
        # Narrow mode uses scale=width/1024 and a centered vertical margin.
        code.raw(b"\x8b\xc1\x6b\xc0\x03\xc1\xf8\x02")
        code.raw(b"\x2b\xd8\xd1\xfb\x89\x1d" + struct.pack("<I", margin_va))
        code.raw(b"\xa1" + struct.pack("<I", center_x_va))
        code.raw(b"\x0f\xaf\xc1\x99\xbb\x00\x04\x00\x00\xf7\xfb")
        code.raw(b"\xa3" + struct.pack("<I", center_x_va))
        code.raw(b"\xa1" + struct.pack("<I", center_y_va))
        code.raw(b"\x0f\xaf\xc1\x99\xbb\x00\x04\x00\x00\xf7\xfb")
        code.raw(b"\x03\x05" + struct.pack("<I", margin_va))
        code.raw(b"\xa3" + struct.pack("<I", center_y_va))

        code.label("center_ready")

        # Rebuild the root around its existing click-relative center. Children
        # are contiguous and share the same square size.
        code.raw(b"\x8b\x5e\x50")
        code.raw(b"\xa1" + struct.pack("<I", size_va) + b"\x0f\xaf\xc3")
        code.raw(b"\x8b\xd0\xd1\xfa")
        code.raw(b"\x8b\x3d" + struct.pack("<I", center_x_va) + b"\x2b\xfa")
        code.raw(b"\x89\x3d" + struct.pack("<I", cursor_x_va))
        code.raw(b"\x89\x7e\x1c\x03\xc7\x89\x46\x24")
        code.raw(b"\xa1" + struct.pack("<I", size_va) + b"\x8b\xd0\xd1\xfa")
        code.raw(b"\x8b\x0d" + struct.pack("<I", center_y_va) + b"\x2b\xca")
        code.raw(b"\x89\x0d" + struct.pack("<I", top_va))
        code.raw(b"\x89\x4e\x20\x03\xc8\x89\x4e\x28")

        # Produce one floating-point scale shared by every icon drawable.
        code.raw(b"\xdb\x05" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\xda\x35" + struct.pack("<I", denominator_va))
        code.raw(b"\xd9\x1d" + struct.pack("<I", ratio_va))
        code.raw(b"\x8b\x7e\x4c")
        code.label("child_loop")
        code.raw(b"\x8b\x0f\x85\xc9")
        code.jump_short_if(Condition.EQUAL, "next_child")
        code.raw(b"\xa1" + struct.pack("<I", cursor_x_va) + b"\x89\x41\x1c")
        code.raw(b"\xa1" + struct.pack("<I", top_va) + b"\x89\x41\x20")
        code.raw(b"\xa1" + struct.pack("<I", size_va))
        code.raw(b"\x03\x41\x1c\x89\x41\x24")
        code.raw(b"\xa1" + struct.pack("<I", size_va))
        code.raw(b"\x03\x41\x20\x89\x41\x28")
        # BitmapNode::Draw (0x0046709a) passes the inline options at +0x30 when
        # +0x44 is set. The direct color-key path owns these icons, so keep its
        # zero selector; the scoped final-blit branch enlarges the independent
        # destination extent. +0x2c is only a 16-bit bitmap handle.
        code.raw(b"\x8b\x15" + struct.pack("<I", ratio_va))
        code.raw(b"\x89\x51\x34\x89\x51\x38")
        code.label("next_child")
        code.raw(b"\xa1" + struct.pack("<I", size_va))
        code.raw(b"\x01\x05" + struct.pack("<I", cursor_x_va))
        code.raw(b"\x83\xc7\x04\x4b")
        code.jump_short_if(Condition.NOT_EQUAL, "child_loop")
        code.jump_short("done")
        code.label("publish_authored_owner")
        code.raw(b"\x89\x35" + struct.pack("<I", presented_root_va))
        code.label("done")
        code.raw(b"\x61\xc3")
        return code.build()

    def build_action_lifetime_helper(
        self,
        *,
        wrapper_va: int,
        action_root_ptr_va: int,
        shared_root_ptr_va: int,
        render_depth_va: int,
        input_active_va: int,
        clear_pending_va: int,
        transform_mode_va: int,
        retire_count_va: int,
        last_root_va: int,
        last_layer_va: int,
    ) -> bytes:
        """Retire an ActionMenu once it leaves the current layer's children.

        ActionMenu is a transient child rather than a top-level UI layer. Its
        native destructor may trail a successful button callback which has
        already installed a replacement layer. The shared system root must
        therefore use current-layer membership—not readable allocation
        memory—as its lifetime proof.

        The pre-Flip caller already preserves flags and registers. This helper
        additionally protects its own registers because it is a reusable
        no-argument ABI. Retirement clears only the patch's borrowed root
        identity; it never destroys or mutates the native menu object.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x60\x31\xdb")  # PUSHAD; EBX records the current layer.
        code.raw(b"\x8b\x35" + struct.pack("<I", action_root_ptr_va))
        code.raw(b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "done")

        # The native destructor can free/reuse the allocation before the next
        # Flip. Validate the complete header consumed below before comparing
        # its concrete class identity.
        code.raw(b"\x6a\x54\x56\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "retire")
        code.raw(b"\x81\x3e" + struct.pack("<I", self.profile.address("action_menu.vtable")))
        code.jump_if(Condition.NOT_EQUAL, "retire")

        code.call_absolute(self.profile.address("ui.current_layer"))
        code.raw(b"\x8b\xd8\x85\xdb")
        code.jump_if(Condition.EQUAL, "retire")
        code.raw(b"\x6a\x54\x53\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "retire")

        # Container children use the exact pointer/count pair at +0x4c/+0x50
        # consumed by GK3's own traversal. Bound and validate the array before
        # proving that the transient ActionMenu is still a direct child.
        code.raw(b"\x8b\x7b\x4c\x8b\x4b\x50\x85\xff")
        code.jump_if(Condition.EQUAL, "retire")
        code.raw(b"\x85\xc9")
        code.jump_if(Condition.LESS_OR_EQUAL, "retire")
        code.raw(b"\x83\xf9\x40")
        code.jump_if(Condition.GREATER, "retire")
        code.raw(b"\x8b\xc1\xc1\xe0\x02\x50\x57\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "retire")
        code.raw(b"\x8b\x4b\x50")
        code.label("child_loop")
        code.raw(b"\x39\x37")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x83\xc7\x04\x49")
        code.jump_short_if(Condition.NOT_EQUAL, "child_loop")

        code.label("retire")
        code.raw(b"\xff\x05" + struct.pack("<I", retire_count_va))
        code.raw(b"\x89\x35" + struct.pack("<I", last_root_va))
        code.raw(b"\x89\x1d" + struct.pack("<I", last_layer_va))
        code.raw(b"\x31\xc0\xa3" + struct.pack("<I", action_root_ptr_va))

        # The generic system scope is shared by successive fixed interfaces.
        # Withdraw it only if this retired menu still owns the published root;
        # a replacement layer which has already drawn must retain its state.
        code.raw(b"\x39\x35" + struct.pack("<I", shared_root_ptr_va))
        code.jump_if(Condition.NOT_EQUAL, "shared_scope_ready")
        for address in (
            render_depth_va,
            input_active_va,
            clear_pending_va,
            shared_root_ptr_va,
            transform_mode_va,
        ):
            code.raw(b"\xa3" + struct.pack("<I", address))
        code.label("shared_scope_ready")

        code.label("done")
        code.raw(b"\x61\xc3")
        return code.build()

    def build_toolbar_blt_helper(
        self,
        *,
        wrapper_va: int,
        preview_surface_va: int,
        dropdown_ptr_va: int,
        root_ptr_va: int,
        source_rect_va: int,
        target_rect_va: int,
        dest_rect_va: int,
        transform_count_va: int,
        clipped_source_rect_va: int,
        cursor_surface_classifier_va: int,
        input_snapshot_valid_va: int,
        input_snapshot_source_rect_va: int,
        input_snapshot_target_rect_va: int,
    ) -> bytes:
        """Map one toolbar transfer from the room stage to the framebuffer."""
        # ECX points at the outer blitter's PUSHAD frame. GK3 constructs the
        # toolbar in the same live stage domain used by the room picker. Above
        # the legacy target ceiling that domain is smaller than the physical
        # framebuffer, so preserving its numeric centre makes the popup appear
        # at a fraction of the click position. Convert the centre through the
        # live stage-to-framebuffer ratio, then height-scale every destination
        # edge around it. The native object tree stays in one coherent stage
        # domain and the existing target-to-source input inverse remains exact.
        # EAX returns one when the caller's RECT changed.
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x60\xc7\x44\x24\x1c\x00\x00\x00\x00")
        code.raw(b"\x8b\x35" + struct.pack("<I", root_ptr_va) + b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "done")
        # The toolbar root extends its bottom edge as the wrench, Advanced,
        # tabs, and resolution list become visible. Publish that complete live
        # source rectangle on every traversal: hit testing needs to cover the
        # added rows. The presentation anchor remains the centre of the
        # authored 252x75 base. Opening a child leaves that anchor unchanged
        # unless the native layout commit moves the whole panel to fit.
        for displacement in range(0, 16, 4):
            code.raw(b"\x8b\x46" + bytes([0x1C + displacement]))
            code.raw(b"\xa3" + struct.pack("<I", source_rect_va + displacement))

        # Publish the matching full destination rectangle for the existing
        # input inverse. Signed division preserves anchors on either side of
        # centre. A missing/incomplete stage descriptor is a short-lived
        # mode-change state; retaining the native centre is the safe fallback.
        for axis, first, second in (("x", 0, 8), ("y", 4, 12)):
            if axis == "x":
                # The root width stays at its authored base extent.
                code.raw(b"\x8b\x2d" + struct.pack("<I", source_rect_va + first))
                code.raw(b"\x03\x2d" + struct.pack("<I", source_rect_va + second))
                code.raw(b"\xd1\xfd")
            else:
                # Expanded rows grow downward. Keep Y anchored at the base
                # centre (top + floor(75/2)), not the expanded union centre.
                code.raw(b"\x8b\x2d" + struct.pack("<I", source_rect_va + first))
                code.raw(b"\x83\xc5\x25")
            code.raw(b"\x8b\xdd")  # EBX = direct framebuffer-space centre
            for displacement in (first, second):
                code.raw(b"\xa1" + struct.pack("<I", source_rect_va + displacement))
                code.raw(b"\x2b\xc5")
                code.raw(b"\x0f\xaf\x05" + struct.pack("<I", self._physical_width_va + 4))
                code.raw(b"\x99\xb9\x00\x03\x00\x00\xf7\xf9\x03\xc3")
                code.raw(b"\xa3" + struct.pack("<I", target_rect_va + displacement))

        # Pointer dispatch must never consume the mutable source/target scratch
        # above. Publish the first completed pair once and keep it immutable for
        # each stable layout. The toolbar inverse uses its fixed base anchor
        # and exact display-height scale, not these rounded endpoint ratios.
        # A native relocation explicitly invalidates this snapshot before the
        # next composition publishes the new anchor and matching inverse.
        code.raw(b"\x83\x3d" + struct.pack("<I", input_snapshot_valid_va) + b"\x00")
        code.jump_if(Condition.NOT_EQUAL, "input_snapshot_published")
        for source_va, snapshot_va in (
            (source_rect_va, input_snapshot_source_rect_va),
            (target_rect_va, input_snapshot_target_rect_va),
        ):
            for displacement in range(0, 16, 4):
                code.raw(b"\xa1" + struct.pack("<I", source_va + displacement))
                code.raw(b"\xa3" + struct.pack("<I", snapshot_va + displacement))
        # x86 orders these stores, so validity publishes only the complete pair.
        code.raw(b"\xc7\x05" + struct.pack("<I", input_snapshot_valid_va))
        code.raw(b"\x01\x00\x00\x00")
        code.label("input_snapshot_published")

        code.raw(b"\x8b\x6c\x24\x18\x8b\x75\x28\x85\xf6")
        code.jump_if(Condition.EQUAL, "done")
        # The toolbar traversal can synchronously ask the cursor manager to
        # restore or redraw its resolved source surface.  That transfer is
        # already owned by the shared cursor presenter and uses framebuffer-
        # relative coordinates, not toolbar-relative coordinates.  Applying
        # the popup affine here created a second cursor on one DirectDraw page.
        # Return "handled" without changing the RECT so the outer blitter goes
        # directly to GK3's native call instead of falling through into the
        # generic popup transform.  Source-surface identity is unambiguous at
        # this boundary and avoids guessing from atlas dimensions, requested
        # output resolution, or screen position.
        code.raw(b"\x8b\x4d\x18\x8b\x55\x24")
        # Source-less DDBLT_COLORFILL operations are real toolbar children as
        # well. Resolution-list hover/erase fills therefore continue through
        # the root/geometry mapping after the shared cursor predicate misses.
        code.call_absolute(cursor_surface_classifier_va)
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.label("not_cursor_save_under")
        emit_preview_source(code, surface_va=preview_surface_va, scratch_va=clipped_source_rect_va)

        # Exact button resources now expose logical dimensions before GK3's
        # clipping, and the shared UI adapter expands only their source RECT.
        # Shrinking a dense destination here was too late: parent clipping had
        # already discarded the right/bottom portions, especially at 1024.

        # The exact physical back-page identity above excludes local scratch
        # surfaces. Within that page, a toolbar-owned transfer is one whose
        # complete destination rectangle is contained by the live root or its
        # explicit sibling popup. An upward-fitted list can start above the
        # root: rejecting its backing while accepting lower glyphs yields a
        # partially native background under scaled labels. Keep the root's
        # base-centre affine unchanged; only extend transfer ownership. This
        # rejects interleaved room/status traffic without proximity margins,
        # sprite-size guesses, or resolution-specific thresholds.
        for displacement, root_displacement, outside_condition in (
            (0, 0, Condition.LESS),
            (4, 4, Condition.LESS),
            (8, 8, Condition.GREATER),
            (12, 12, Condition.GREATER),
        ):
            code.raw(b"\x8b\x46" + bytes([displacement]))
            code.raw(b"\x3b\x05" + struct.pack("<I", source_rect_va + root_displacement))
            code.jump_if(outside_condition, "dropdown_owner")
        code.jump("toolbar_owned")
        code.label("dropdown_owner")
        code.raw(b"\x8b\x15" + struct.pack("<I", dropdown_ptr_va) + b"\x85\xd2")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(
            b"\x81\x3a" + struct.pack("<I", self.profile.address("resolution_dropdown.vtable"))
        )
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\x80\x7a\x18\x00")
        code.jump_if(Condition.EQUAL, "done")
        for displacement, outside_condition in (
            (0, Condition.LESS),
            (4, Condition.LESS),
            (8, Condition.GREATER),
            (12, Condition.GREATER),
        ):
            code.raw(b"\x8b\x46" + bytes([displacement]))
            code.raw(b"\x3b\x42" + bytes([0x1C + displacement]))
            code.jump_if(outside_condition, "done")
        code.label("toolbar_owned")
        # Every row shares the original base anchor. Reconstructing a centre
        # from rounded expanded endpoints shifts it as panels open/close and
        # disagrees with the exact height-scale input and slider-return paths.
        for displacement, source_first in (
            (0, 0),
            (8, 0),
            (4, 4),
            (12, 4),
        ):
            code.raw(b"\x8b\x2d" + struct.pack("<I", source_rect_va + source_first))
            code.raw(b"\x83\xc5" + bytes([126 if source_first == 0 else 37]))
            code.raw(b"\x8b\xdd")
            code.raw(b"\x8b\x46" + bytes([displacement]) + b"\x2b\xc5")
            code.raw(b"\x0f\xaf\x05" + struct.pack("<I", self._physical_width_va + 4))
            code.raw(b"\x99\xb9\x00\x03\x00\x00\xf7\xf9\x03\xc3")
            code.raw(b"\x89\x46" + bytes([displacement]))

        # The transformed rectangle remains owned by this call through the
        # downstream DirectDraw operation. Earlier code redirected every
        # toolbar blit to one global RECT; an interleaved cursor/UI transfer
        # could overwrite that memory while DirectDraw still consumed it,
        # pairing one control's source with another call's (often origin-local)
        # destination. Keep the caller's private rectangle authoritative and
        # mirror it to global storage only for the exceptional resolution-list
        # crop below.
        code.raw(b"\x56\xbf" + struct.pack("<I", dest_rect_va))
        code.raw(b"\xb9\x04\x00\x00\x00\xf3\xa5\x5e")

        # DirectDraw 7 rejects a stretched Blt whose destination extends past
        # the surface instead of clipping it. In sufficiently dense modes the
        # Graphics resolution list becomes taller than the framebuffer, so its
        # exact 137x328 backing vanished while independently clipped row glyphs
        # remained.
        # Crop this one identified backing transfer at the bottom edge.  The
        # corresponding source bottom is reduced by the same ratio, preserving
        # the bitmap-to-row registration rather than compressing the full list.
        code.raw(b"\x8b\x6c\x24\x18")  # EBP = outer PUSHAD frame
        code.raw(b"\x8b\x55\x24\x85\xd2")  # resolved source wrapper
        code.jump_if(Condition.EQUAL, "toolbar_publish")
        code.raw(b"\x81\x7a\x38\x89\x00\x00\x00")  # source width = 137
        code.jump_if(Condition.NOT_EQUAL, "toolbar_publish")
        code.raw(b"\x81\x7a\x3c\x48\x01\x00\x00")  # source height = 328
        code.jump_if(Condition.NOT_EQUAL, "toolbar_publish")
        code.raw(b"\xa1" + struct.pack("<I", dest_rect_va + 12))
        code.raw(b"\x8b\x0d" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\x3b\xc1")
        code.jump_if(Condition.LESS_OR_EQUAL, "toolbar_publish")
        code.raw(b"\x3b\x0d" + struct.pack("<I", dest_rect_va + 4))
        code.jump_if(Condition.LESS_OR_EQUAL, "toolbar_publish")

        # Only this clipped-list branch needs private destination storage: it
        # changes both the destination bottom and source bottom as one atomic
        # pair. Ordinary toolbar calls retain their caller-owned RECT pointer.
        code.raw(b"\xc7\x45\x28" + struct.pack("<I", dest_rect_va))

        # Materialize the caller's source rectangle, or the complete source
        # surface when GK3 passed null to request the whole bitmap.
        code.raw(b"\x8b\x75\x2c\x85\xf6")
        code.jump_if(Condition.EQUAL, "toolbar_full_source")
        code.raw(b"\xbf" + struct.pack("<I", clipped_source_rect_va))
        code.raw(b"\xb9\x04\x00\x00\x00\xf3\xa5")
        code.jump("toolbar_source_ready")
        code.label("toolbar_full_source")
        code.raw(b"\x31\xc0")
        code.raw(b"\xa3" + struct.pack("<I", clipped_source_rect_va))
        code.raw(b"\xa3" + struct.pack("<I", clipped_source_rect_va + 4))
        code.raw(b"\xc7\x05" + struct.pack("<I", clipped_source_rect_va + 8))
        code.raw(b"\x89\x00\x00\x00")
        code.raw(b"\xc7\x05" + struct.pack("<I", clipped_source_rect_va + 12))
        code.raw(b"\x48\x01\x00\x00")
        code.label("toolbar_source_ready")

        # cropped_source_height = source_height * visible_dest_height /
        #                         transformed_dest_height
        code.raw(b"\xa1" + struct.pack("<I", clipped_source_rect_va + 12))
        code.raw(b"\x2b\x05" + struct.pack("<I", clipped_source_rect_va + 4))
        code.raw(b"\x8b\x0d" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\x2b\x0d" + struct.pack("<I", dest_rect_va + 4))
        code.raw(b"\x0f\xaf\xc1\x99")
        code.raw(b"\x8b\x1d" + struct.pack("<I", dest_rect_va + 12))
        code.raw(b"\x2b\x1d" + struct.pack("<I", dest_rect_va + 4))
        code.raw(b"\xf7\xfb")
        code.raw(b"\x03\x05" + struct.pack("<I", clipped_source_rect_va + 4))
        code.raw(b"\xa3" + struct.pack("<I", clipped_source_rect_va + 12))
        code.raw(b"\x8b\x0d" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\x89\x0d" + struct.pack("<I", dest_rect_va + 12))
        code.raw(b"\xc7\x45\x2c" + struct.pack("<I", clipped_source_rect_va))

        code.label("toolbar_publish")
        code.raw(b"\xff\x05" + struct.pack("<I", transform_count_va))
        code.raw(b"\xc7\x44\x24\x1c\x01\x00\x00\x00")
        code.jump("done")
        code.label("native")
        code.raw(b"\xc7\x44\x24\x1c\x01\x00\x00\x00")
        code.label("done")
        code.raw(b"\x61\xc3")
        return code.build()
