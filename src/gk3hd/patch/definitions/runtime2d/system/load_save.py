"""Compile Load/Save layout, fonts, backing cache, and Restore progress."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter, encode_rel32_branch
from gk3hd.patch.definitions.runtime2d.geometry import (
    AUTHORED_FRAME_HEIGHT,
    RESTORE_PROGRESS_LOGICAL_HEIGHT,
    RESTORE_PROGRESS_LOGICAL_WIDTH,
)
from gk3hd.patch.definitions.runtime2d.inventory_navigation import LOADSAVE_CONTROL_PREDICATE_OFFSET
from gk3hd.patch.definitions.runtime2d.layout import (
    INVENTORY_NAVIGATION_INPUT_OFFSET,
    INVENTORY_NAVIGATION_INPUT_STRIDE,
    INVENTORY_NAVIGATION_SEGMENT,
    LOAD_SAVE_BUTTON_INITIAL_BOUNDS_OFFSET,
    LOAD_SAVE_BUTTON_SEGMENT,
    RESOURCE_PROGRESS_DRAW_DEPTH_OFFSET,
    RESOURCE_SEGMENT,
    SIDNEY_BUTTON_DISPATCH_ADAPTER_OFFSET,
    SIDNEY_PRESENTATION_SEGMENT,
    SYSTEM_CONTROL_HD_FONT_HANDLE_CAPACITY,
)
from gk3hd.patch.definitions.runtime2d.system.shared import SystemCompilerContext
from gk3hd.patch.model import PatchError
from gk3hd.textures.upscale.fonts.bank import FONT_ROW_BANK_LAYOUTS

if TYPE_CHECKING:
    from gk3hd.patch.binary.mutations import ExecutableMutationPlan
    from gk3hd.patch.binary.payload import SegmentPayloadBuilder
    from gk3hd.patch.definitions.runtime2d.font_bank import FontBankEntryPoints
    from gk3hd.patch.definitions.runtime2d.system.cursor import CursorFeatureCompiler
    from gk3hd.patch.definitions.runtime2d.system.fixed_screens import FixedScreenFeatureCompiler


@dataclass(frozen=True, slots=True)
class LoadSaveSegmentExports:
    """Addresses exported by the complete Load/Save-owned runtime segment."""

    layout_wrapper_va: int
    preview_attach_va: int
    damage_selector_va: int
    background_helper_va: int
    font_rect_helper_va: int
    cache_update_helper_va: int
    frame_presenter_va: int
    progress_background_wrapper_va: int
    progress_initial_show_wrapper_va: int
    progress_canvas_update_wrapper_va: int
    scrollbar_input_stub_vas: tuple[int, ...]
    scrollbar_hit_test_wrapper_va: int
    scrollbar_arrow_left_down_stub_va: int
    scrollbar_arrow_release_va: int
    scrollbar_thumb_move_stub_va: int


@dataclass(frozen=True, slots=True)
class LoadSaveLifecycleExports:
    """Native entry addresses exported by the complete Load/Save lifecycle."""

    root_wrapper_va: int
    show_wrapper_va: int
    hide_wrapper_va: int
    load_destructor_wrapper_va: int
    save_destructor_wrapper_va: int
    font_entry_va: int
    font_metrics_wrapper_va: int
    text_draw_wrapper_va: int


@dataclass(frozen=True, slots=True, kw_only=True)
class LoadSaveFeatureCompiler(SystemCompilerContext):
    """Present every Load/Save surface in one reference-relative layout.

    Outcome:
        Save names, screenshots, controls, cursor, backgrounds, and Restore
        progress match the apparent scale and reveal behavior of 1024x768.
    Before:
        GK3 mixes a physically laid-out root with authored bitmap and font
        extents; dense replacement art is clipped or rescaled inconsistently.
    After:
        Layout, glyphs, cache composition, and progress source/destination
        clipping share one explicit Load/Save coordinate contract.
    Strategy:
        Wrap the concrete layout and font paths, cache the completed physical
        canvas, and preserve the progress strip's left-to-right source reveal.
    Boundaries:
        Generic high-resolution resource recognition, cursor final-page
        ownership, and save parsing belong to their existing owners.
    """

    _scrollbar_input_slots: ClassVar[tuple[tuple[int, str, int], ...]] = (
        (0x44, "scrollbar.event_44", 1),
        (0x48, "scrollbar.event_48", 1),
        (0x4C, "scrollbar.event_4c", 1),
        (0x50, "scrollbar.event_50", 1),
        (0x54, "scrollbar.event_54", 1),
        (0x58, "scrollbar.event_58", 1),
        (0x5C, "scrollbar.event_5c", 1),
        (0x7C, "scrollbar.event_7c", 3),
        (0x80, "scrollbar.event_80", 3),
    )

    def emit_segment(
        self,
        payload: SegmentPayloadBuilder,
        *,
        system_va: int,
        control_va: int,
        loadsave_va: int,
        cursor: CursorFeatureCompiler,
    ) -> LoadSaveSegmentExports:
        """Compile and place every Load/Save-segment helper and wrapper."""
        payload.place(label="magic", offset=0, payload=self._loadsave_magic)
        payload.place(
            label="layout version",
            offset=self._off_layout_version,
            payload=struct.pack("<I", self._loadsave_layout_version),
        )
        payload.reserve(
            label="layout and font state",
            offset=self._off_loadsave_layout_root,
            size=self._off_loadsave_layout_wrapper - self._off_loadsave_layout_root,
        )
        payload.reserve(
            label="dynamic Load/Save geometry state",
            offset=self._off_loadsave_preview_rect,
            size=self._off_loadsave_dynamic_state_end - self._off_loadsave_preview_rect,
        )
        cache_descriptor = bytearray(self._ddsd_size)
        struct.pack_into("<I", cache_descriptor, 0, self._ddsd_size)
        struct.pack_into("<I", cache_descriptor, 4, self._ddsd_caps_height_width)
        struct.pack_into("<I", cache_descriptor, 0x68, self._tooltip_panel_caps)
        cache_state = bytearray(
            self._off_loadsave_cache_update_helper - self._off_loadsave_destination_handle
        )
        descriptor_offset = (
            self._off_loadsave_cache_descriptor - self._off_loadsave_destination_handle
        )
        cache_state[descriptor_offset : descriptor_offset + len(cache_descriptor)] = (
            cache_descriptor
        )
        payload.place(
            label="cache state",
            offset=self._off_loadsave_destination_handle,
            payload=bytes(cache_state),
        )
        layout_wrapper_va = loadsave_va + self._off_loadsave_layout_wrapper
        rect_transform_va = loadsave_va + self._off_loadsave_rect_transform
        damage_selector_va = loadsave_va + self._off_loadsave_damage_selector
        background_helper_va = loadsave_va + self._off_loadsave_background_helper
        font_rect_helper_va = loadsave_va + self._off_loadsave_font_rect_helper
        cache_update_helper_va = loadsave_va + self._off_loadsave_cache_update_helper
        frame_presenter_va = loadsave_va + self._off_loadsave_frame_presenter
        post_draw_cursor_presenter_va = loadsave_va + self._off_loadsave_post_draw_cursor_presenter
        page_clear_helper_va = loadsave_va + self._off_loadsave_page_clear_helper
        scrollbar_input_wrapper_vas = {
            1: loadsave_va + self._off_loadsave_scroll_input_1,
            3: loadsave_va + self._off_loadsave_scroll_input_3,
        }
        scrollbar_input_stub_vas = tuple(
            loadsave_va
            + self._off_loadsave_scroll_input_stubs
            + index * self._loadsave_scroll_input_stub_stride
            for index in range(len(self._scrollbar_input_slots))
        )
        scrollbar_hit_test_wrapper_va = loadsave_va + self._off_loadsave_scroll_hit_test
        scrollbar_arrow_input_wrapper_va = loadsave_va + self._off_loadsave_scroll_arrow_input
        scrollbar_arrow_left_down_stub_va = (
            loadsave_va + self._off_loadsave_scroll_arrow_left_down_stub
        )
        scrollbar_arrow_release_stub_va = loadsave_va + self._off_loadsave_scroll_arrow_release_stub
        scrollbar_arrow_release_va = loadsave_va + self._off_loadsave_scroll_arrow_release_dispatch
        scrollbar_thumb_move_stub_va = loadsave_va + self._off_loadsave_scroll_thumb_move_stub
        progress_background_wrapper_va = (
            loadsave_va + self._off_restore_progress_background_attach_wrapper
        )
        progress_initial_show_wrapper_va = (
            loadsave_va + self._off_restore_progress_initial_show_wrapper
        )
        progress_canvas_update_wrapper_va = (
            loadsave_va + self._off_restore_progress_canvas_update_wrapper
        )
        layout_wrapper = self.build_loadsave_layout_wrapper(
            wrapper_va=layout_wrapper_va,
            rect_transform_va=rect_transform_va,
            layout_root_va=loadsave_va + self._off_loadsave_layout_root,
            selection_rects_va=loadsave_va + self._off_loadsave_selection_rects,
            initial_preview_transform_va=loadsave_va + self._off_loadsave_initial_preview_transform,
            initial_button_transform_va=self.symbols.va(
                LOAD_SAVE_BUTTON_SEGMENT.logical_name, LOAD_SAVE_BUTTON_INITIAL_BOUNDS_OFFSET
            ),
        )
        rect_transform = self.build_loadsave_rect_transform()
        background_helper = self.build_loadsave_background_helper(
            control_predicate_va=self.symbols.va(
                INVENTORY_NAVIGATION_SEGMENT.logical_name, LOADSAVE_CONTROL_PREDICATE_OFFSET
            ),
            wrapper_va=background_helper_va,
            rect_transform_va=rect_transform_va,
            root_ptr_va=system_va + self._off_root_ptr,
            source_rect_va=system_va + self._off_source_rect,
            dest_rect_va=system_va + self._off_dest_rect,
            scroll_raw_top_va=loadsave_va + self._off_loadsave_scroll_raw_top,
            scroll_origin_seen_va=loadsave_va + self._off_loadsave_scroll_origin_seen,
            preview_trace_va=loadsave_va + self._off_loadsave_preview_trace,
        )
        font_rect_helper = self.build_loadsave_font_rect_helper(
            wrapper_va=font_rect_helper_va,
            root_ptr_va=system_va + self._off_root_ptr,
            trace_count_va=loadsave_va + self._off_loadsave_record_font_count,
            trace_input_va=loadsave_va + self._off_loadsave_record_font_input,
            trace_output_va=loadsave_va + self._off_loadsave_record_font_output,
            active_text_va=loadsave_va + self._off_loadsave_record_text_active,
        )
        damage_selector = self.build_loadsave_damage_selector(
            wrapper_va=damage_selector_va,
            native_damage_ptr_va=loadsave_va + self._off_loadsave_native_damage_ptr,
            native_damage_count_va=loadsave_va + self._off_loadsave_native_damage_count,
            native_damage_rects_va=loadsave_va + self._off_loadsave_native_damage_rects,
            selection_rects_va=loadsave_va + self._off_loadsave_selection_rects,
            selection_repair_count_va=(loadsave_va + self._off_loadsave_selection_repair_count),
            selection_repair_pending_va=(loadsave_va + self._off_loadsave_selection_repair_pending),
            full_damage_region_va=control_va + self._off_control_full_damage_region,
        )
        cache_update_helper = self.build_loadsave_cache_update_helper(
            wrapper_va=cache_update_helper_va,
            ddraw_va=self.profile.address("high_resolution_3d.directdraw_ptr"),
            back_surface_va=self.profile.address("transition.back_surface_ptr"),
            surface_va=loadsave_va + self._off_loadsave_cache_surface,
            owner_va=loadsave_va + self._off_loadsave_cache_owner,
            ready_va=loadsave_va + self._off_loadsave_cache_ready,
            descriptor_va=loadsave_va + self._off_loadsave_cache_descriptor,
            source_rect_va=loadsave_va + self._off_loadsave_cache_source_rect,
            scratch_rect_va=loadsave_va + self._off_loadsave_cache_scratch_rect,
            create_result_va=loadsave_va + self._off_loadsave_cache_create_result,
            capture_result_va=loadsave_va + self._off_loadsave_cache_capture_result,
            capture_count_va=loadsave_va + self._off_loadsave_cache_capture_count,
            full_capture_count_va=loadsave_va + self._off_loadsave_full_damage_count,
            selection_repair_pending_va=(loadsave_va + self._off_loadsave_selection_repair_pending),
            full_damage_region_va=control_va + self._off_control_full_damage_region,
            post_draw_cursor_presenter_va=post_draw_cursor_presenter_va,
        )
        frame_presenter = self.build_loadsave_frame_presenter(
            wrapper_va=frame_presenter_va,
            current_layer_va=self.profile.address("ui.current_layer"),
            root_ptr_va=system_va + self._off_root_ptr,
            fixed_canvas_owner_va=self.room_rendering_abi.fixed_canvas_owner_va,
            cache_surface_va=loadsave_va + self._off_loadsave_cache_surface,
            cache_ready_va=loadsave_va + self._off_loadsave_cache_ready,
            source_rect_va=loadsave_va + self._off_loadsave_cache_source_rect,
            back_surface_va=self.profile.address("transition.back_surface_ptr"),
            present_result_va=loadsave_va + self._off_loadsave_cache_present_result,
            present_count_va=loadsave_va + self._off_loadsave_cache_present_count,
            frame_present_count_va=loadsave_va + self._off_loadsave_frame_present_count,
        )
        post_draw_cursor_presenter = cursor.build_loadsave_post_draw_cursor_presenter(
            wrapper_va=post_draw_cursor_presenter_va,
        )
        page_clear_helper = self.build_loadsave_page_clear_helper(
            wrapper_va=page_clear_helper_va,
            back_surface_va=self.profile.address("transition.back_surface_ptr"),
            bltfx_va=system_va + self._off_bltfx,
            result_va=loadsave_va + self._off_loadsave_page_clear_result,
            count_va=loadsave_va + self._off_loadsave_page_clear_count,
        )
        scrollbar_input_wrappers = {
            argument_count: self.build_loadsave_scrollbar_input_wrapper(
                wrapper_va=wrapper_va,
                argument_count=argument_count,
                input_depth_va=loadsave_va + self._off_loadsave_scroll_input_depth,
                mapped_point_va=loadsave_va + self._off_loadsave_scroll_input_mapped_point,
                inventory_input_va=self.symbols.va(
                    INVENTORY_NAVIGATION_SEGMENT.logical_name,
                    INVENTORY_NAVIGATION_INPUT_OFFSET
                    + (argument_count // 3) * INVENTORY_NAVIGATION_INPUT_STRIDE,
                ),
            )
            for argument_count, wrapper_va in scrollbar_input_wrapper_vas.items()
        }
        scrollbar_input_stubs = tuple(
            self.build_loadsave_scrollbar_input_stub(
                stub_va=stub_va,
                wrapper_va=scrollbar_input_wrapper_vas[argument_count],
                original_va=self.profile.address(symbol),
            )
            for stub_va, (_, symbol, argument_count) in zip(
                scrollbar_input_stub_vas,
                self._scrollbar_input_slots,
                strict=True,
            )
        )
        scrollbar_hit_test_wrapper = self.build_loadsave_scrollbar_hit_test_wrapper(
            wrapper_va=scrollbar_hit_test_wrapper_va,
            native_va=self.profile.address("scrollbar.hit_test"),
            input_depth_va=loadsave_va + self._off_loadsave_scroll_input_depth,
        )
        scrollbar_arrow_input_wrapper = self.build_loadsave_scrollbar_arrow_input_wrapper(
            wrapper_va=scrollbar_arrow_input_wrapper_va,
        )
        scrollbar_arrow_left_down_stub = self.build_loadsave_scrollbar_input_stub(
            stub_va=scrollbar_arrow_left_down_stub_va,
            wrapper_va=scrollbar_arrow_input_wrapper_va,
            original_va=self.profile.address("scrollbar_arrow.left_down"),
        )
        scrollbar_arrow_release_stub = self.build_loadsave_scrollbar_input_stub(
            stub_va=scrollbar_arrow_release_stub_va,
            wrapper_va=scrollbar_arrow_input_wrapper_va,
            original_va=self.profile.address("scrollbar_arrow.left_release"),
        )
        scrollbar_arrow_release = self.build_scrollbar_release_dispatch(
            wrapper_va=scrollbar_arrow_release_va,
            input_depth_va=loadsave_va + self._off_loadsave_scroll_input_depth,
            input_wrapper_va=scrollbar_input_wrapper_vas[1],
            native_stub_va=scrollbar_arrow_release_stub_va,
        )
        scrollbar_thumb_move_stub = self.build_scrollbar_thumb_move_dispatch(
            stub_va=scrollbar_thumb_move_stub_va,
            wrapper_va=scrollbar_input_wrapper_vas[3],
            sidney_adapter_va=self.symbols.va(
                SIDNEY_PRESENTATION_SEGMENT.logical_name, SIDNEY_BUTTON_DISPATCH_ADAPTER_OFFSET
            ),
        )
        progress_background_wrapper = self.build_restore_progress_background_attach_wrapper(
            wrapper_va=progress_background_wrapper_va,
        )
        progress_draw_depth_va = self.symbols.va(
            RESOURCE_SEGMENT.logical_name,
            RESOURCE_PROGRESS_DRAW_DEPTH_OFFSET,
        )
        progress_initial_show_wrapper = self.build_restore_progress_draw_scope_wrapper(
            wrapper_va=progress_initial_show_wrapper_va,
            native_va=self.profile.address("restore_progress.initial_show"),
            draw_depth_va=progress_draw_depth_va,
            argument_bytes=0,
        )
        progress_canvas_update_wrapper = self.build_restore_progress_draw_scope_wrapper(
            wrapper_va=progress_canvas_update_wrapper_va,
            native_va=self.profile.address("restore_progress.canvas_update"),
            draw_depth_va=progress_draw_depth_va,
            argument_bytes=4,
        )
        for label, offset, code, limit in (
            (
                "initial preview transform",
                self._off_loadsave_initial_preview_transform,
                self.build_loadsave_initial_preview_transform(),
                self._off_loadsave_damage_selector,
            ),
            (
                "layout wrapper",
                self._off_loadsave_layout_wrapper,
                layout_wrapper,
                self._off_loadsave_rect_transform,
            ),
            (
                "RECT transform",
                self._off_loadsave_rect_transform,
                rect_transform,
                self._off_loadsave_damage_selector,
            ),
            (
                "damage selector",
                self._off_loadsave_damage_selector,
                damage_selector,
                self._off_loadsave_background_helper,
            ),
            (
                "background helper",
                self._off_loadsave_background_helper,
                background_helper,
                self._off_loadsave_preview_attach,
            ),
            (
                "selection-time preview layout",
                self._off_loadsave_preview_attach,
                self.build_loadsave_preview_attach(
                    wrapper_va=loadsave_va + self._off_loadsave_preview_attach,
                    layout_root_va=loadsave_va + self._off_loadsave_layout_root,
                    preview_rect_va=loadsave_va + self._off_loadsave_preview_rect,
                ),
                self._off_loadsave_font_rect_helper,
            ),
            (
                "font RECT helper",
                self._off_loadsave_font_rect_helper,
                font_rect_helper,
                self._off_loadsave_destination_handle,
            ),
            (
                "cache update helper",
                self._off_loadsave_cache_update_helper,
                cache_update_helper,
                self._off_loadsave_frame_presenter,
            ),
            (
                "frame presenter",
                self._off_loadsave_frame_presenter,
                frame_presenter,
                self._off_loadsave_post_draw_cursor_presenter,
            ),
            (
                "post-draw cursor presenter",
                self._off_loadsave_post_draw_cursor_presenter,
                post_draw_cursor_presenter,
                self._off_loadsave_post_draw_cursor_presenter_limit,
            ),
            (
                "restore-progress background wrapper",
                self._off_restore_progress_background_attach_wrapper,
                progress_background_wrapper,
                self._off_restore_progress_background_attach_wrapper_limit,
            ),
            (
                "restore-progress initial Show wrapper",
                self._off_restore_progress_initial_show_wrapper,
                progress_initial_show_wrapper,
                self._off_restore_progress_initial_show_wrapper_limit,
            ),
            (
                "restore-progress canvas Update wrapper",
                self._off_restore_progress_canvas_update_wrapper,
                progress_canvas_update_wrapper,
                self._off_restore_progress_canvas_update_wrapper_limit,
            ),
            (
                "Load/Save page clear helper",
                self._off_loadsave_page_clear_helper,
                page_clear_helper,
                self._off_loadsave_page_clear_helper_limit,
            ),
            (
                "Load/Save ScrollBar one-argument input adapter",
                self._off_loadsave_scroll_input_1,
                scrollbar_input_wrappers[1],
                self._off_loadsave_scroll_input_3,
            ),
            (
                "Load/Save ScrollBar three-argument input adapter",
                self._off_loadsave_scroll_input_3,
                scrollbar_input_wrappers[3],
                self._off_loadsave_scroll_input_stubs,
            ),
        ):
            payload.place(label=label, offset=offset, payload=code, limit=limit)
        for index, stub in enumerate(scrollbar_input_stubs):
            offset = (
                self._off_loadsave_scroll_input_stubs
                + index * self._loadsave_scroll_input_stub_stride
            )
            payload.place(
                label=f"Load/Save ScrollBar input stub {index + 1}",
                offset=offset,
                payload=stub,
                limit=offset + self._loadsave_scroll_input_stub_stride,
            )
        payload.place(
            label="Load/Save ScrollBar arrow left-down stub",
            offset=self._off_loadsave_scroll_arrow_left_down_stub,
            payload=scrollbar_arrow_left_down_stub,
            limit=self._off_loadsave_scroll_arrow_release_stub,
        )
        payload.place(
            label="Load/Save ScrollBar arrow left-release stub",
            offset=self._off_loadsave_scroll_arrow_release_stub,
            payload=scrollbar_arrow_release_stub,
            limit=self._off_loadsave_scroll_arrow_release_dispatch,
        )
        payload.place(
            label="Load/Save ScrollBar thumb drag-move stub",
            offset=self._off_loadsave_scroll_thumb_move_stub,
            payload=scrollbar_thumb_move_stub,
            limit=self._off_loadsave_scroll_thumb_move_limit,
        )
        payload.place(
            label="Load/Save captured arrow release",
            offset=self._off_loadsave_scroll_arrow_release_dispatch,
            payload=scrollbar_arrow_release,
            limit=self._off_loadsave_scroll_input_mapped_point,
        )
        payload.place(
            label="Load/Save ScrollBar outer hit-test adapter",
            offset=self._off_loadsave_scroll_hit_test,
            payload=scrollbar_hit_test_wrapper,
            limit=self._off_loadsave_scroll_arrow_input,
        )
        payload.place(
            label="Load/Save ScrollBar arrow dense-mask adapter",
            offset=self._off_loadsave_scroll_arrow_input,
            payload=scrollbar_arrow_input_wrapper,
            limit=self._off_loadsave_scroll_input_tail_limit,
        )
        return LoadSaveSegmentExports(
            layout_wrapper_va=layout_wrapper_va,
            preview_attach_va=loadsave_va + self._off_loadsave_preview_attach,
            damage_selector_va=damage_selector_va,
            background_helper_va=background_helper_va,
            font_rect_helper_va=font_rect_helper_va,
            cache_update_helper_va=cache_update_helper_va,
            frame_presenter_va=frame_presenter_va,
            progress_background_wrapper_va=progress_background_wrapper_va,
            progress_initial_show_wrapper_va=progress_initial_show_wrapper_va,
            progress_canvas_update_wrapper_va=progress_canvas_update_wrapper_va,
            scrollbar_input_stub_vas=scrollbar_input_stub_vas,
            scrollbar_hit_test_wrapper_va=scrollbar_hit_test_wrapper_va,
            scrollbar_arrow_left_down_stub_va=scrollbar_arrow_left_down_stub_va,
            scrollbar_arrow_release_va=scrollbar_arrow_release_va,
            scrollbar_thumb_move_stub_va=scrollbar_thumb_move_stub_va,
        )

    def emit_lifecycle(
        self,
        system_payload: SegmentPayloadBuilder,
        control_payload: SegmentPayloadBuilder,
        *,
        system_va: int,
        control_va: int,
        loadsave_va: int,
        segment: LoadSaveSegmentExports,
        fixed_screens: FixedScreenFeatureCompiler,
        font_bank: FontBankEntryPoints,
    ) -> LoadSaveLifecycleExports:
        """Compile and place Load/Save root, font, and lifetime wrappers."""
        root_wrapper_va = control_va + self._off_control_loadsave_root_draw_wrapper
        show_wrapper_va = system_va + self._off_loadgame_show_wrapper
        hide_wrapper_va = system_va + self._off_loadgame_hide_wrapper
        load_destructor_wrapper_va = system_va + self._off_loadgame_destructor_wrapper
        save_destructor_wrapper_va = system_va + self._off_loadsave_destructor_wrapper
        font_entry_va = system_va + self._off_loadsave_root_draw_wrapper
        font_wrapper_va = control_va + self._off_control_font_wrapper
        font_metrics_wrapper_va = control_va + self._off_control_font_metrics_wrapper
        text_draw_wrapper_va = control_va + self._off_control_loadsave_text_draw_wrapper

        root_wrapper = fixed_screens.build_root_draw_wrapper(
            wrapper_va=root_wrapper_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            # Layout has already transformed controls and hit rectangles. Keep
            # this concrete root published as the active input owner; the
            # shared dispatcher recognizes its vtable and preserves the
            # physical POINT instead of applying another canvas inverse.
            transform_mode=self._mode_loadsave,
            input_enabled=False,
            target_va=self._native_draw_va,
            full_damage_region_va=control_va + self._off_control_full_damage_region,
            full_damage_rect_va=control_va + self._off_control_full_damage_rect,
            damage_selector_va=segment.damage_selector_va,
            fixed_canvas_owner_va=self.room_rendering_abi.fixed_canvas_owner_va,
            presentation_owner_reset_vas=(
                loadsave_va + self._off_loadsave_full_damage_count,
                loadsave_va + self._off_loadsave_destination_handle,
                loadsave_va + self._off_loadsave_frame_present_count,
                loadsave_va + self._off_loadsave_cache_ready,
                loadsave_va + self._off_loadsave_cache_capture_count,
                loadsave_va + self._off_loadsave_cache_present_count,
                loadsave_va + self._off_loadsave_page_clear_count,
                loadsave_va + self._off_loadsave_selection_repair_pending,
            ),
            presentation_destination_handle_va=(
                loadsave_va + self._off_loadsave_destination_handle
            ),
            pre_draw_va=loadsave_va + self._off_loadsave_page_clear_helper,
            post_draw_va=segment.cache_update_helper_va,
            post_draw_pass_args=True,
        )
        root_entry = encode_rel32_branch(
            opcode=BranchOpcode.JUMP,
            site_va=system_va + self._off_loadgame_root_draw_wrapper,
            target_va=root_wrapper_va,
        )
        show_wrapper = fixed_screens.build_state_wrapper(
            state_va=system_va + self._off_input_active,
            value=1,
            target_va=self._native_show_va,
            wrapper_va=show_wrapper_va,
        )
        hide_wrapper = fixed_screens.build_state_wrapper(
            state_va=system_va + self._off_input_active,
            value=0,
            target_va=self._native_hide_va,
            wrapper_va=hide_wrapper_va,
            fixed_canvas_owner_va=self.room_rendering_abi.fixed_canvas_owner_va,
        )
        load_destructor_wrapper = fixed_screens.build_destructor_wrapper(
            wrapper_va=load_destructor_wrapper_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            target_va=self._native_loadgame_destructor_va,
            extra_clear_vas=(loadsave_va + self._off_loadsave_layout_root,),
            fixed_canvas_owner_va=self.room_rendering_abi.fixed_canvas_owner_va,
        )
        save_destructor_wrapper = fixed_screens.build_destructor_wrapper(
            wrapper_va=save_destructor_wrapper_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            target_va=self._native_savegame_destructor_va,
            extra_clear_vas=(loadsave_va + self._off_loadsave_layout_root,),
            fixed_canvas_owner_va=self.room_rendering_abi.fixed_canvas_owner_va,
        )
        font_wrapper = self.build_loadsave_font_wrapper(
            wrapper_va=font_wrapper_va,
            root_ptr_va=system_va + self._off_root_ptr,
            font_rect_helper_va=segment.font_rect_helper_va,
            hud_font_active_va=loadsave_va + self._off_hud_font_active,
            hud_font_transform_count_va=loadsave_va + self._off_hud_font_transform_count,
            hud_font_last_point_va=loadsave_va + self._off_hud_font_last_point,
            hd_font_active_va=control_va + self._off_control_hd_font_active,
            hd_font_handle_count_va=(control_va + self._off_control_hd_font_handle_count),
            hd_font_handles_va=control_va + self._off_control_hd_font_handles,
            room_status_present_depth_va=(control_va + self._off_room_status_present_depth),
        )
        font_entry = encode_rel32_branch(
            opcode=BranchOpcode.JUMP,
            site_va=font_entry_va,
            target_va=font_bank.draw_va,
        )
        font_metrics_wrapper = self.build_hd_font_metrics_wrapper(
            wrapper_va=font_metrics_wrapper_va,
            normalize_count_va=control_va + self._off_control_hd_font_normalize_count,
            handle_count_va=control_va + self._off_control_hd_font_handle_count,
            handles_va=control_va + self._off_control_hd_font_handles,
            bank_registration_va=font_bank.registration_va,
        )
        text_draw_wrapper = self.build_loadsave_text_draw_wrapper(
            wrapper_va=text_draw_wrapper_va,
            active_text_va=loadsave_va + self._off_loadsave_record_text_active,
            native_va=self.profile.address("loadsave_text.draw"),
        )
        control_payload.place(
            label="Save name EditBox draw",
            offset=self._off_control_loadsave_text_draw_wrapper + 0x40,
            payload=self.build_loadsave_text_draw_wrapper(
                wrapper_va=text_draw_wrapper_va + 0x40,
                active_text_va=loadsave_va + self._off_loadsave_record_text_active,
                native_va=self.profile.address("savegame_edit.draw"),
            ),
            limit=self._off_control_loadsave_text_draw_wrapper_limit,
        )
        for label, offset, code, limit in (
            (
                "Load/Save root entry",
                self._off_loadgame_root_draw_wrapper,
                root_entry,
                self._off_loadgame_show_wrapper,
            ),
            (
                "LoadGame show",
                self._off_loadgame_show_wrapper,
                show_wrapper,
                self._off_loadgame_hide_wrapper,
            ),
            (
                "LoadGame hide",
                self._off_loadgame_hide_wrapper,
                hide_wrapper,
                self._off_loadgame_destructor_wrapper,
            ),
            (
                "LoadGame destructor",
                self._off_loadgame_destructor_wrapper,
                load_destructor_wrapper,
                self._off_action_layout_state,
            ),
            (
                "Load/Save font",
                self._off_loadsave_root_draw_wrapper,
                font_entry,
                self._off_loadsave_destructor_wrapper,
            ),
            (
                "Load/Save destructor",
                self._off_loadsave_destructor_wrapper,
                save_destructor_wrapper,
                self._section_size,
            ),
        ):
            system_payload.place(label=label, offset=offset, payload=code, limit=limit)
        control_payload.place(
            label="Load/Save root",
            offset=self._off_control_loadsave_root_draw_wrapper,
            payload=root_wrapper,
            limit=self._off_control_ingame_toolbar_draw_wrapper,
        )
        control_payload.place(
            label="shared font wrapper",
            offset=self._off_control_font_wrapper,
            payload=font_wrapper,
            limit=self._off_control_font_wrapper_limit,
        )
        control_payload.place(
            label="HD font metric normalizer",
            offset=self._off_control_font_metrics_wrapper,
            payload=font_metrics_wrapper,
            limit=self._off_control_font_metrics_wrapper_limit,
        )
        for label, offset, code, limit in (
            (
                "Load/Save record TextBox draw",
                self._off_control_loadsave_text_draw_wrapper,
                text_draw_wrapper,
                self._off_control_loadsave_text_draw_wrapper + 0x40,
            ),
        ):
            control_payload.place(label=label, offset=offset, payload=code, limit=limit)
        return LoadSaveLifecycleExports(
            root_wrapper_va=root_wrapper_va,
            show_wrapper_va=show_wrapper_va,
            hide_wrapper_va=hide_wrapper_va,
            load_destructor_wrapper_va=load_destructor_wrapper_va,
            save_destructor_wrapper_va=save_destructor_wrapper_va,
            font_entry_va=font_entry_va,
            font_metrics_wrapper_va=font_metrics_wrapper_va,
            text_draw_wrapper_va=text_draw_wrapper_va,
        )

    def plan_hooks(
        self,
        plan: ExecutableMutationPlan,
        *,
        root_wrapper_va: int,
        show_wrapper_va: int,
        hide_wrapper_va: int,
        load_destructor_wrapper_va: int,
        save_destructor_wrapper_va: int,
        layout_wrapper_va: int,
        preview_attach_va: int,
        font_entry_va: int,
        font_metrics_wrapper_va: int,
        text_draw_wrapper_va: int,
        progress_background_wrapper_va: int,
        progress_initial_show_wrapper_va: int,
        progress_canvas_update_wrapper_va: int,
        scrollbar_input_stub_vas: tuple[int, ...],
        scrollbar_hit_test_wrapper_va: int,
        scrollbar_arrow_left_down_stub_va: int,
        scrollbar_arrow_release_va: int,
        scrollbar_thumb_move_stub_va: int,
    ) -> None:
        """Own Load/Save vtables, font interception, and progress redirects."""
        preview_site = self.profile.site("loadsave.preview_attach")
        plan.branch(
            label="Load/Save selection-time preview layout",
            opcode=BranchOpcode.CALL,
            site_va=preview_site.va,
            expected=preview_site.original,
            target_va=preview_attach_va,
            size=len(preview_site.original),
        )
        for label, slot_va, expected_va, target_va in (
            ("LoadGame draw", self._loadgame_draw_slot_va, self._native_draw_va, root_wrapper_va),
            ("LoadGame show", self._loadgame_show_slot_va, self._native_show_va, show_wrapper_va),
            ("LoadGame hide", self._loadgame_hide_slot_va, self._native_hide_va, hide_wrapper_va),
            (
                "LoadGame destructor",
                self._loadgame_destructor_slot_va,
                self._native_loadgame_destructor_va,
                load_destructor_wrapper_va,
            ),
            ("SaveGame draw", self._savegame_draw_slot_va, self._native_draw_va, root_wrapper_va),
            ("SaveGame show", self._savegame_show_slot_va, self._native_show_va, show_wrapper_va),
            ("SaveGame hide", self._savegame_hide_slot_va, self._native_hide_va, hide_wrapper_va),
            (
                "SaveGame destructor",
                self._savegame_destructor_slot_va,
                self._native_savegame_destructor_va,
                save_destructor_wrapper_va,
            ),
            (
                "Load/Save record TextBox draw",
                self.profile.address("loadsave_text.vtable") + 0xA0,
                self.profile.address("loadsave_text.draw"),
                text_draw_wrapper_va,
            ),
            (
                "Save name EditBox draw",
                self.profile.address("savegame_edit.vtable") + 0xA0,
                self.profile.address("savegame_edit.draw"),
                text_draw_wrapper_va + 0x40,
            ),
            (
                "LoadGame layout",
                self._loadgame_layout_slot_va,
                self._native_loadsave_layout_va,
                layout_wrapper_va,
            ),
            (
                "SaveGame layout",
                self._savegame_layout_slot_va,
                self._native_loadsave_layout_va,
                layout_wrapper_va,
            ),
        ):
            plan.pointer(
                label=label,
                slot_va=slot_va,
                expected=expected_va,
                target_va=target_va,
            )
        scrollbar_vtable_va = self.profile.address("scrollbar.vtable")
        for (slot_offset, symbol, _), target_va in zip(
            self._scrollbar_input_slots,
            scrollbar_input_stub_vas,
            strict=True,
        ):
            plan.pointer(
                label=f"Load/Save ScrollBar input +0x{slot_offset:02x}",
                slot_va=scrollbar_vtable_va + slot_offset,
                expected=self.profile.address(symbol),
                target_va=target_va,
            )
        plan.pointer(
            label="Load/Save ScrollBar outer hit test",
            slot_va=scrollbar_vtable_va + 0x94,
            expected=self.profile.address("scrollbar.hit_test"),
            target_va=scrollbar_hit_test_wrapper_va,
        )
        arrow_vtable_va = self.profile.address("scrollbar_arrow.vtable")
        plan.pointer(
            label="Load/Save ScrollBar arrow left down",
            slot_va=arrow_vtable_va + 0x44,
            expected=self.profile.address("scrollbar_arrow.left_down"),
            target_va=scrollbar_arrow_left_down_stub_va,
        )
        plan.pointer(
            label="Load/Save ScrollBar arrow left release",
            slot_va=arrow_vtable_va + 0x54,
            expected=self.profile.address("scrollbar_arrow.left_release"),
            target_va=scrollbar_arrow_release_va,
        )
        thumb_vtable_va = self.profile.address("scrollbar_thumb.vtable")
        plan.pointer(
            label="Load/Save ScrollBar thumb drag move",
            slot_va=thumb_vtable_va + 0x80,
            expected=self.profile.address("scrollbar_thumb.drag_move"),
            target_va=scrollbar_thumb_move_stub_va,
        )
        plan.branch(
            label="Font submission tail trampoline",
            opcode=BranchOpcode.CALL,
            site_va=self._font_blt_call_site_va,
            expected=self._font_blt_call_original,
            target_va=font_entry_va,
            size=len(self._font_blt_call_original),
        )
        plan.branch(
            label="HD font metric normalization",
            opcode=BranchOpcode.JUMP,
            site_va=self._font_metrics_site_va,
            expected=self._font_metrics_original,
            target_va=font_metrics_wrapper_va,
            size=len(self._font_metrics_original),
        )
        plan.branch(
            label="restore-progress background attach",
            opcode=BranchOpcode.CALL,
            site_va=self._restore_progress_background_attach_call_va,
            expected=self._restore_progress_background_attach_call_original,
            target_va=progress_background_wrapper_va,
            size=len(self._restore_progress_background_attach_call_original),
        )
        for label, site_va, original, target_va in (
            (
                "restore-progress initial show",
                self._restore_progress_initial_show_call_va,
                self._restore_progress_initial_show_call_original,
                progress_initial_show_wrapper_va,
            ),
            (
                "restore-progress canvas update",
                self._restore_progress_canvas_update_call_va,
                self._restore_progress_canvas_update_call_original,
                progress_canvas_update_wrapper_va,
            ),
        ):
            plan.branch(
                label=label,
                opcode=BranchOpcode.CALL,
                site_va=site_va,
                expected=original,
                target_va=target_va,
                size=len(original),
            )

    def build_scrollbar_release_dispatch(
        self, *, wrapper_va: int, input_depth_va: int, input_wrapper_va: int, native_stub_va: int
    ) -> bytes:
        """Map captured Load/Save releases without remapping nested or Inventory events."""
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x83\x3d" + struct.pack("<I", input_depth_va) + b"\x00")
        code.jump_short_if(Condition.NOT_EQUAL, "native")
        code.raw(b"\x51")
        code.call_absolute(self.profile.address("ui.current_layer"))
        code.raw(b"\x59\x85\xc0")
        code.jump_short_if(Condition.EQUAL, "native")
        code.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("loadgame.vtable")))
        code.jump_short_if(Condition.EQUAL, "captured")
        code.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("savegame.vtable")))
        code.jump_short_if(Condition.NOT_EQUAL, "native")
        code.label("captured")
        # The existing adapter calls this stub after normalizing the POINT;
        # the stub then applies dense-mask sampling before the native release.
        code.raw(b"\xb8" + struct.pack("<I", native_stub_va))
        code.jump_absolute(input_wrapper_va)
        code.label("native")
        code.jump_absolute(native_stub_va)
        return code.build()

    def build_loadsave_scrollbar_input_wrapper(
        self,
        *,
        wrapper_va: int,
        argument_count: int,
        input_depth_va: int,
        mapped_point_va: int,
        inventory_input_va: int,
    ) -> bytes:
        """Map only one selected ScrollBar event into its native child model.

        The root traversal has already hit-tested the outer, physical ScrollBar
        before this vtable entry runs. Its arrow, thumb, and track children keep
        their original global coordinates because their native drag/page math
        depends on that 22-pixel model. Replace only the event POINT and scope
        MouseManager's cursor cache to the same value for the native callback.
        """
        if argument_count not in {1, 3}:
            detail = f"unsupported ScrollBar input argument count: {argument_count}"
            raise PatchError(detail)

        width_va = self.room_rendering_abi.width_va
        height_va = self.room_rendering_abi.height_va
        cursor_position_va = self.profile.address("input.cursor_position")
        code = X86Emitter(base_va=wrapper_va)
        # Locals: target, this, saved cursor x/y, mapped POINT x/y.
        code.raw(b"\x55\x8b\xec\x83\xec\x18")
        code.raw(b"\x89\x45\xfc\x89\x4d\xf8")
        # Inventory shares this native ScrollBar class, but its root dispatcher
        # has already inverse-mapped the POINT into the authored canvas. Do not
        # apply Load/Save's physical-centred child mapping a second time there.
        code.call_absolute(self.profile.address("ui.current_layer"))
        code.raw(b"\x85\xc0")
        code.jump_short_if(Condition.EQUAL, "native")
        code.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("inventory.vtable")))
        code.jump_short_if(Condition.NOT_EQUAL, "loadsave_owner")
        code.raw(b"\x8b\x45\xfc\x8b\x4d\xf8\xc9")
        code.jump_absolute(inventory_input_va)
        code.label("loadsave_owner")
        # This vtable is shared by SIDNEY and other authored interfaces. Their
        # root input adapter already mapped the POINT; the physical Load/Save
        # inverse would map it again and prevent arrows from receiving events.
        # Only the two concrete roots with physical outer scrollbar bounds own
        # this conversion. All other roots retain the pristine native callback.
        code.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("loadgame.vtable")))
        code.jump_short_if(Condition.EQUAL, "map_loadsave")
        code.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("savegame.vtable")))
        code.jump_short_if(Condition.EQUAL, "map_loadsave")
        code.label("native")
        code.raw(b"\x8b\x45\xfc\x8b\x4d\xf8\xc9\xff\xe0")
        code.label("map_loadsave")
        code.raw(b"\xa1" + struct.pack("<I", cursor_position_va) + b"\x89\x45\xf4")
        code.raw(b"\xa1" + struct.pack("<I", cursor_position_va + 4) + b"\x89\x45\xf0")
        code.raw(b"\xff\x05" + struct.pack("<I", input_depth_va))

        # Undo the screen-centred height fit for the horizontal coordinate.
        code.raw(b"\x8b\x45\x08\x8b\x00")
        code.raw(b"\x8b\x0d" + struct.pack("<I", width_va) + b"\xd1\xf9\x2b\xc1")
        code.raw(b"\x69\xc0" + struct.pack("<I", AUTHORED_FRAME_HEIGHT) + b"\x99")
        code.raw(b"\x8b\x0d" + struct.pack("<I", height_va) + b"\xf7\xf9")
        code.raw(b"\x8b\x15" + struct.pack("<I", width_va) + b"\xd1\xfa\x03\xc2")
        code.raw(b"\x89\x45\xe8")
        code.raw(b"\xa3" + struct.pack("<I", mapped_point_va))

        # Undo the screen-centred height fit for the vertical coordinate.
        code.raw(b"\x8b\x45\x08\x8b\x40\x04")
        code.raw(b"\x8b\x0d" + struct.pack("<I", height_va) + b"\x8b\xd1\xd1\xfa\x2b\xc2")
        code.raw(b"\x69\xc0" + struct.pack("<I", AUTHORED_FRAME_HEIGHT) + b"\x99\xf7\xf9")
        code.raw(b"\x8b\x15" + struct.pack("<I", height_va) + b"\xd1\xfa\x03\xc2")
        code.raw(b"\x89\x45\xec")
        code.raw(b"\xa3" + struct.pack("<I", mapped_point_va + 4))

        code.raw(b"\x8b\x45\xe8\xa3" + struct.pack("<I", cursor_position_va))
        code.raw(b"\x8b\x45\xec\xa3" + struct.pack("<I", cursor_position_va + 4))
        forwarded_arguments = {
            1: b"",
            3: b"\xff\x75\x10\xff\x75\x0c",
        }
        code.raw(forwarded_arguments[argument_count])
        code.raw(b"\x8d\x45\xe8\x50\x8b\x4d\xf8\xff\x55\xfc")

        # EAX is the native result; restore the durable physical cursor using
        # only caller-clobbered EDX, then clean the original caller's args.
        code.raw(b"\x8b\x55\xf4\x89\x15" + struct.pack("<I", cursor_position_va))
        code.raw(b"\x8b\x55\xf0\x89\x15" + struct.pack("<I", cursor_position_va + 4))
        code.raw(b"\xff\x0d" + struct.pack("<I", input_depth_va))
        code.raw(b"\xc9\xc2" + struct.pack("<H", argument_count * 4))
        return code.build()

    def build_scrollbar_thumb_move_dispatch(
        self, *, stub_va: int, wrapper_va: int, sidney_adapter_va: int
    ) -> bytes:
        """Map SIDNEY's captured thumb POINT through its root input affine.

        Drag-begin traverses the root and stores an authored grab offset in
        Thumb+0x68. Captured drag-move bypasses that traversal: native 508506
        adds its first POINT.y to this offset, not its movement delta. Forward
        this physical POINT through the existing three-argument adapter only
        for the current SIDNEY root. Ordinary ScrollBar events already contain
        authored points and must not inherit this additional conversion.
        """
        code = X86Emitter(base_va=stub_va)
        code.raw(b"\x51")
        code.call_absolute(self.profile.address("ui.current_layer"))
        code.raw(b"\x59\x85\xc0")
        code.jump_short_if(Condition.EQUAL, "other_root")
        code.raw(
            b"\x81\x38" + struct.pack("<I", self.profile.address("sidney.root_destructor_slot"))
        )
        code.jump_short_if(Condition.NOT_EQUAL, "other_root")
        code.raw(b"\xb8" + struct.pack("<I", self.profile.address("scrollbar_thumb.drag_move")))
        code.raw(b"\xba\x03\x00\x00\x00")
        code.jump_absolute(sidney_adapter_va)
        code.label("other_root")
        code.raw(b"\xb8" + struct.pack("<I", self.profile.address("scrollbar_thumb.drag_move")))
        code.jump_absolute(wrapper_va)
        return code.build()

    @staticmethod
    def build_loadsave_scrollbar_hit_test_wrapper(
        *,
        wrapper_va: int,
        native_va: int,
        input_depth_va: int,
    ) -> bytes:
        """Retain the outer physical self-test inside a mapped child event."""
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x83\x3d" + struct.pack("<I", input_depth_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "native")
        # The root traversal already selected this exact physical component;
        # only its redundant inner check sees the child-model POINT.
        code.raw(b"\x6a\x01\x58\xc2\x04\x00")
        code.label("native")
        code.jump_absolute(native_va)
        return code.build()

    def build_loadsave_scrollbar_arrow_input_wrapper(self, *, wrapper_va: int) -> bytes:
        """Scale only an exact 4x arrow's opacity-mask sample coordinates."""
        code = X86Emitter(base_va=wrapper_va)
        # Locals: pristine target, arrow this, and the adjusted POINT.
        code.raw(b"\x55\x8b\xec\x83\xec\x10\x89\x45\xfc\x89\x4d\xf8")
        code.raw(b"\x8b\x41\x54")
        code.raw(b"\x8b\x0d" + struct.pack("<I", self.profile.address("resource.manager")))
        code.raw(b"\x50")
        code.call_absolute(self._resolve_bitmap_resource_va)
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\x8b\x40\x30\x85\xc0")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\x8b\x4d\xf8\x8b\x51\x24\x2b\x51\x1c\xc1\xe2\x02")
        code.raw(b"\x3b\x50\x38")
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.raw(b"\x8b\x51\x28\x2b\x51\x20\xc1\xe2\x02\x3b\x50\x3c")
        code.jump_if(Condition.NOT_EQUAL, "native")

        # Keep the global child rectangle in model space while sampling the
        # corresponding pixel in the exact 4x resource's opacity mask.
        code.raw(b"\x8b\x45\x08\x8b\x10\x2b\x51\x1c\xc1\xe2\x02\x03\x51\x1c")
        code.raw(b"\x89\x55\xf0\x8b\x50\x04\x2b\x51\x20\xc1\xe2\x02\x03\x51\x20")
        code.raw(b"\x89\x55\xf4\x8d\x45\xf0\x50\x8b\x4d\xf8\xff\x55\xfc")
        code.raw(b"\xc9\xc2\x04\x00")

        code.label("native")
        code.raw(b"\x8b\x45\xfc\x8b\x4d\xf8\xc9\xff\xe0")
        return code.build()

    @staticmethod
    def build_loadsave_text_draw_wrapper(
        *, wrapper_va: int, active_text_va: int, native_va: int
    ) -> bytes:
        """Scope glyph submissions to their exact Load/Save record TextBox."""
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x55\x8b\xec\x83\xec\x04")
        code.raw(b"\xa1" + struct.pack("<I", active_text_va) + b"\x89\x45\xfc")
        code.raw(b"\x89\x0d" + struct.pack("<I", active_text_va))
        code.raw(b"\xff\x75\x0c\xff\x75\x08")
        code.call_absolute(native_va)
        code.raw(b"\x8b\x55\xfc\x89\x15" + struct.pack("<I", active_text_va))
        code.raw(b"\xc9\xc2\x08\x00")
        return code.build()

    @staticmethod
    def build_loadsave_scrollbar_input_stub(
        *,
        stub_va: int,
        wrapper_va: int,
        original_va: int,
    ) -> bytes:
        """Load one pristine ScrollBar method and tail-dispatch its ABI adapter."""
        code = X86Emitter(base_va=stub_va)
        code.raw(b"\xb8" + struct.pack("<I", original_va))
        code.jump_absolute(wrapper_va)
        return code.build()

    def build_restore_progress_background_attach_wrapper(self, *, wrapper_va: int) -> bytes:
        """Separate a dense progress raster from its logical model rectangle.

        GK3's native attachment routine resolves the selected ``PROGRESS_*``
        bitmap and stores its *raster* width and height in the owning UI
        object's presentation rectangle. That is correct for stock art but
        turns a dense replacement into a screen-sized model before its first
        draw. This wrapper calls the pristine routine once, then corrects only
        the concrete owner's rectangle. The target dimensions derive from the
        live display height and the authored 593x201 geometry; no output
        resolution or resource name is embedded. The dense surface remains
        intact for slider composition and DirectDraw downsamples it only when
        the complete model is presented. The 1024x768 path remains byte-for-
        byte native.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x55\x8b\xec\x53\x56\x57")
        code.raw(b"\x8b\xf1")  # ESI = the controller-owned UI object

        # Preserve the original thiscall and its single resource-handle
        # argument. The native callee owns RET 4 and returns before geometry is
        # corrected, so construction cannot observe a half-attached object.
        code.raw(b"\xff\x75\x08\x8b\xce")
        code.call_absolute(self._native_restore_progress_background_attach_va)
        code.raw(b"\x50")  # preserve the native return value

        code.raw(b"\x8b\x3d" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\x81\xff" + struct.pack("<I", AUTHORED_FRAME_HEIGHT))
        code.jump_if(Condition.BELOW_OR_EQUAL, "done")

        # Derive the width from the live height with nearest-pixel rounding.
        code.raw(b"\x8b\xc7\x69\xc0" + struct.pack("<I", RESTORE_PROGRESS_LOGICAL_WIDTH))
        code.raw(b"\x05" + struct.pack("<I", AUTHORED_FRAME_HEIGHT // 2))
        code.raw(b"\x31\xd2\xb9" + struct.pack("<I", AUTHORED_FRAME_HEIGHT))
        code.raw(b"\xf7\xf1\x8b\xd8")  # EBX = target width

        # Derive the height through the identical reference-scale affine.
        code.raw(b"\x8b\xc7\x69\xc0" + struct.pack("<I", RESTORE_PROGRESS_LOGICAL_HEIGHT))
        code.raw(b"\x05" + struct.pack("<I", AUTHORED_FRAME_HEIGHT // 2))
        code.raw(b"\x31\xd2\xf7\xf1\x8b\xd0")  # EDX = target height

        # Center the model in the live physical client. Keeping this rectangle
        # at the owner means construction, every progress update, clipping, and
        # the final reveal all consume one authoritative geometry contract.
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va))
        code.raw(b"\x2b\xc3\xd1\xf8\x89\x46\x28\x03\xc3\x89\x46\x30")
        code.raw(b"\x8b\xc7\x2b\xc2\xd1\xf8\x89\x46\x2c\x03\xc2\x89\x46\x34")

        code.label("done")
        code.raw(b"\x58\x5f\x5e\x5b\xc9\xc2\x04\x00")
        return code.build()

    @staticmethod
    def build_restore_progress_draw_scope_wrapper(
        *,
        wrapper_va: int,
        native_va: int,
        draw_depth_va: int,
        argument_bytes: int,
    ) -> bytes:
        """Bracket one concrete progress presentation without retained identity.

        The constructor's initial Show and RestoreProgressController's later
        UI Update are the only calls which copy the private progress canvas to
        a physical page. A depth counter gives ResourceDispatch a synchronous
        producer proof while the native call is live, then disappears before
        control returns. This is safer than caching a surface pointer across
        controller destruction or classifying all equal-sized resources.
        """
        if argument_bytes not in {0, 4}:
            msg = "restore-progress draw scope supports zero or one argument"
            raise PatchError(msg)
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x55\x8b\xec\x56\x8b\xf1")
        code.raw(b"\xff\x05" + struct.pack("<I", draw_depth_va))
        if argument_bytes:
            code.raw(b"\xff\x75\x08")
        code.raw(b"\x8b\xce")
        code.call_absolute(native_va)
        code.raw(b"\x50")
        code.raw(b"\xff\x0d" + struct.pack("<I", draw_depth_va))
        code.raw(b"\x58\x5e\xc9")
        if argument_bytes:
            code.raw(b"\xc2\x04\x00")
        else:
            code.raw(b"\xc3")
        return code.build()

    def build_loadsave_font_wrapper(
        self,
        *,
        wrapper_va: int,
        root_ptr_va: int,
        font_rect_helper_va: int,
        hud_font_active_va: int,
        hud_font_transform_count_va: int,
        hud_font_last_point_va: int,
        hd_font_active_va: int,
        hd_font_handle_count_va: int,
        hd_font_handles_va: int,
        room_status_present_depth_va: int,
    ) -> bytes:
        """Scale Load/Save and room-status glyph destinations.

        The hook is at GK3's high-level font submission call, before the engine
        clips the glyph, records its damage, and chooses a DirectDraw page.
        Scaling at the later shared-blitter boundary caused page-dependent
        clipping artefacts because those decisions had already been made in
        1024x768 coordinates.
        """
        # FUN_005343E0 is a thiscall with five stack arguments. Its third
        # argument points to the destination X/Y pair, its fourth is the
        # clipped glyph-atlas source RECT, and its fifth is BitmapDrawable's
        # five-word effect-options record. Both remain byte-for-byte authored:
        # screen-scaling arg4 selects unrelated atlas glyphs, while scaling
        # arg5 turns its floating-point blend weights into NaNs. The final
        # blitter constructs a destination RECT from the mapped point and the
        # native glyph extent, then performs the matching source clipping.
        code = X86Emitter(base_va=wrapper_va)
        # Font submission is re-entrant: native text rendering can submit a
        # nested glyph before the outer glyph reaches the final blitter. Save
        # the caller's narrow scopes AND point so a nested call cannot erase
        # them. The mapped point belongs to this stack frame, never the final
        # blitter's shared destination RECT (which that same call overwrites).
        code.raw(b"\xff\x35" + struct.pack("<I", hd_font_active_va))
        code.raw(b"\xff\x35" + struct.pack("<I", hud_font_active_va))
        code.raw(b"\xff\x35" + struct.pack("<I", hud_font_last_point_va + 4))
        code.raw(b"\xff\x35" + struct.pack("<I", hud_font_last_point_va))
        code.raw(b"\x83\xec\x08")
        code.raw(b"\x60")
        code.raw(b"\x31\xc0")
        for state_va in (hd_font_active_va, hud_font_active_va):
            code.raw(b"\xa3" + struct.pack("<I", state_va))

        # Metric initialization has already vetted each generated atlas and
        # recorded its stable 16-bit resource handle. Matching arg2 is enough
        # to scope 4x source sampling; never resolve the resource again here.
        code.raw(b"\x0f\xb7\x44\x24\x40\x85\xc0")
        code.jump_if(Condition.EQUAL, "font_owner")
        code.raw(b"\x8b\x0d" + struct.pack("<I", hd_font_handle_count_va))
        code.raw(b"\x31\xff")
        code.label("hd_handle_loop")
        code.raw(b"\x3b\xf9")
        code.jump_if(Condition.ABOVE_OR_EQUAL, "font_owner")
        code.raw(b"\x0f\xb7\x14\x7d" + struct.pack("<I", hd_font_handles_va))
        code.raw(b"\x3b\xc2")
        code.jump_if(Condition.EQUAL, "hd_handle")
        code.raw(b"\x47")
        code.jump("hd_handle_loop")
        code.label("hd_handle")
        # Publish identity, not merely a boolean: nested alpha scratch/capture
        # transfers are not reads from this fourfold atlas.
        code.raw(b"\xa3" + struct.pack("<I", hd_font_active_va))

        code.label("font_owner")
        # RoomLayer's status TextBox publishes this exact synchronous depth.
        # Its logical point must be mapped before GK3 clips and damages the
        # glyph; the final blitter then reconstructs the scaled far edge.
        code.raw(b"\x83\x3d" + struct.pack("<I", room_status_present_depth_va) + b"\x00")
        code.jump_if(Condition.NOT_EQUAL, "room_status")

        # CloseUp and Fingerprint construct native-size copies of the room HUD instead
        # of drawing RoomLayer's retained status TextBox.  Admit only that
        # exact modal owner and the same authored top-band point used by the
        # room-status route; the close-up object and every other font remain
        # outside this affine.
        code.call_absolute(self.profile.address("ui.current_layer"))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "inventory_status_owner")
        code.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("closeup.vtable")))
        code.jump_if(Condition.EQUAL, "modal_status_band")
        code.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("zodiac.vtable")))
        code.jump_if(Condition.EQUAL, "modal_status_band")
        code.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("fingerprint.vtable")))
        code.jump_if(Condition.NOT_EQUAL, "inventory_status_owner")
        code.label("modal_status_band")
        code.raw(b"\x8b\x74\x24\x44\x85\xf6")
        code.jump_if(Condition.EQUAL, "inventory_status_owner")
        code.raw(b"\x8b\x06\x85\xc0")
        code.jump_if(Condition.SIGN, "inventory_status_owner")
        code.raw(b"\x3d\x00\x04\x00\x00")
        code.jump_if(Condition.ABOVE_OR_EQUAL, "inventory_status_owner")
        code.raw(b"\x8b\x4e\x04\x85\xc9")
        code.jump_if(Condition.SIGN, "inventory_status_owner")
        code.raw(b"\x83\xf9\x20")
        code.jump_if(Condition.BELOW, "room_status")

        code.label("inventory_status_owner")

        # Inventory and the in-game toolbar redraw the underlying room caption
        # after the retained TextBox traversal has unwound. Recover that late
        # submission only while one of those exact roots owns the screen and
        # the glyph point remains inside the authored top status band. This
        # avoids the broad global top-edge heuristic that used to catch
        # unrelated UI text.
        code.raw(b"\xa1" + struct.pack("<I", root_ptr_va) + b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "loadsave_owner")
        code.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("inventory.vtable")))
        code.jump_if(Condition.EQUAL, "late_room_status")
        code.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("ingame_toolbar.vtable")))
        code.jump_if(Condition.NOT_EQUAL, "loadsave_owner")
        code.label("late_room_status")
        code.raw(b"\x8b\x74\x24\x44\x85\xf6")
        code.jump_if(Condition.EQUAL, "loadsave_owner")
        code.raw(b"\x8b\x06\x85\xc0")
        code.jump_if(Condition.SIGN, "loadsave_owner")
        code.raw(b"\x3d\x00\x04\x00\x00")
        code.jump_if(Condition.ABOVE_OR_EQUAL, "loadsave_owner")
        code.raw(b"\x8b\x4e\x04\x85\xc9")
        code.jump_if(Condition.SIGN, "loadsave_owner")
        code.raw(b"\x83\xf9\x20")
        code.jump_if(Condition.BELOW, "room_status")

        code.label("loadsave_owner")
        # Load/Save retains a concrete root for its complete visible lifetime.
        # Only its record TextBoxes are accepted by the bounded helper; titles,
        # controls, and unrelated fonts remain native.
        code.raw(b"\xa1" + struct.pack("<I", root_ptr_va) + b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "classification_done")
        code.raw(b"\x8b\xd8")
        code.call_absolute(self.profile.address("ui.current_layer"))
        code.raw(b"\x3b\xc3")
        code.jump_if(Condition.NOT_EQUAL, "classification_done")
        code.raw(b"\x8b\x13")
        code.raw(b"\x81\xfa" + struct.pack("<I", self.profile.address("loadgame.vtable")))
        code.jump_if(Condition.EQUAL, "loadsave")
        code.raw(b"\x81\xfa" + struct.pack("<I", self.profile.address("savegame.vtable")))
        code.jump_if(Condition.NOT_EQUAL, "classification_done")

        code.label("loadsave")
        code.raw(b"\x8b\x74\x24\x44\x85\xf6")
        code.jump_if(Condition.EQUAL, "classification_done")
        code.raw(b"\x8d\x7c\x24\x20")
        code.raw(b"\xfc\xb9\x02\x00\x00\x00\xf3\xa5")
        code.raw(b"\x8d\x4c\x24\x20")
        code.call_absolute(font_rect_helper_va)
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "classification_done")
        for displacement in (0, 4):
            code.raw(b"\x8b\x44\x24" + bytes([0x20 + displacement]))
            code.raw(b"\xa3" + struct.pack("<I", hud_font_last_point_va + displacement))
        code.raw(b"\x8d\x44\x24\x20\x89\x44\x24\x44")
        code.raw(b"\xc7\x05" + struct.pack("<I", hud_font_active_va) + b"\x02\x00\x00\x00")
        code.raw(b"\xff\x05" + struct.pack("<I", hud_font_transform_count_va))
        code.jump("scoped_call")

        code.label("room_status")
        code.raw(b"\x8b\x74\x24\x44\x85\xf6")
        code.jump_if(Condition.EQUAL, "classification_done")
        for displacement in (0, 4):
            code.raw(b"\x8b\x46" + bytes([displacement]))
            code.raw(b"\xa3" + struct.pack("<I", hud_font_last_point_va + displacement))
        code.raw(b"\x8d\x7c\x24\x20")
        code.raw(b"\x8b\x1d" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\xbd\x00\x03\x00\x00\xb9\x02\x00\x00\x00")
        code.label("room_status_scale")
        code.raw(b"\xad\x0f\xaf\xc3\x99\xf7\xfd\xab")
        code.loop_short("room_status_scale")
        code.raw(b"\x8d\x44\x24\x20\x89\x44\x24\x44")
        code.raw(b"\xc7\x05" + struct.pack("<I", hud_font_active_va) + b"\x01\x00\x00\x00")
        code.raw(b"\xff\x05" + struct.pack("<I", hud_font_transform_count_va))
        code.jump("scoped_call")

        code.label("classification_done")
        # Even an unclassified nested draw must run with its own cleared
        # scopes. Restoring the outer flags BEFORE a native tail-call would
        # incorrectly apply the outer glyph's transform to that nested draw.

        # Duplicate the caller's five arguments. Native RET 14h consumes only
        # those copies; this wrapper then restores its caller's narrow states
        # and consumes the originals with the identical ABI.
        code.label("scoped_call")
        code.raw(b"\x61")
        code.raw(b"\xff\x74\x24\x2c" * 5)
        code.call_absolute(self._font_blt_target_va)
        code.raw(b"\x50")
        for displacement, state_va in (
            (0x0C, hud_font_last_point_va),
            (0x10, hud_font_last_point_va + 4),
            (0x14, hud_font_active_va),
            (0x18, hd_font_active_va),
        ):
            code.raw(b"\x8b\x44\x24" + bytes([displacement]) + b"\xa3")
            code.raw(struct.pack("<I", state_va))
        code.raw(b"\x58\x83\xc4\x18\xc2\x14\x00")
        return code.build()

    def build_hd_font_metrics_wrapper(
        self,
        *,
        wrapper_va: int,
        normalize_count_va: int,
        handle_count_va: int,
        handles_va: int,
        bank_registration_va: int | None = None,
    ) -> bytes:
        """Normalize one vetted 4x atlas back to GK3's logical font metrics."""
        code = X86Emitter(base_va=wrapper_va)
        # The parsed marker width is already available at this hook.  Reject
        # every stock atlas before entering the resource manager: font loading
        # is re-entrant during Title construction and an identity probe there
        # is observably not equivalent to executing the original tail.
        code.raw(b"\x60")
        self._emit_hd_font_size_gate(code)
        code.label("resolve_font")
        code.raw(b"\x8b\x46\x04\x50")
        code.raw(b"\x8b\x0d" + struct.pack("<I", self.profile.address("resource.manager")))
        code.call_absolute(self._resolve_bitmap_resource_va)
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "stock")
        code.raw(b"\x8b\x50\x30\x85\xd2")
        code.jump_if(Condition.EQUAL, "stock")
        # The resource must agree with the dimensions just read by the parser.
        # This also guards the exact small-bank exceptions admitted above.
        code.raw(bytes.fromhex("8b4e34 3b4a38"))
        code.jump_if(Condition.NOT_EQUAL, "stock")
        code.raw(bytes.fromhex("8b4e38 3b4a3c"))
        code.jump_if(Condition.NOT_EQUAL, "stock")
        code.raw(b"\xf7\x42\x38\x03\x00\x00\x00")
        code.jump_if(Condition.NOT_EQUAL, "stock")
        code.raw(b"\xf7\x42\x3c\x03\x00\x00\x00")
        code.jump_if(Condition.NOT_EQUAL, "stock")
        last_object_va = handles_va + SYSTEM_CONTROL_HD_FONT_HANDLE_CAPACITY * 2
        code.raw(b"\x89\x35" + struct.pack("<I", last_object_va + 4))
        code.raw(b"\x8b\x50\x08\x89\x15" + struct.pack("<I", last_object_va + 8))
        code.label("hd")
        code.raw(b"\x89\x35" + struct.pack("<I", last_object_va))
        # Publish the already-vetted 16-bit resource handle once. Glyph
        # submission can recognize generated atlases without re-entering the
        # resource manager during re-entrant UI construction.
        code.raw(b"\x0f\xb7\x46\x04\x85\xc0")
        code.jump_if(Condition.EQUAL, "handle_done")
        code.raw(b"\x8b\x0d" + struct.pack("<I", handle_count_va) + b"\x31\xff")
        code.label("handle_loop")
        code.raw(b"\x3b\xf9")
        code.jump_if(Condition.ABOVE_OR_EQUAL, "handle_append")
        code.raw(b"\x0f\xb7\x14\x7d" + struct.pack("<I", handles_va) + b"\x3b\xc2")
        code.jump_if(Condition.EQUAL, "handle_done")
        code.raw(b"\x47")
        code.jump("handle_loop")
        code.label("handle_append")
        code.raw(b"\x83\xf9" + bytes([SYSTEM_CONTROL_HD_FONT_HANDLE_CAPACITY]))
        code.jump_if(Condition.ABOVE_OR_EQUAL, "handle_done")
        code.raw(b"\x66\x89\x04\x4d" + struct.pack("<I", handles_va))
        code.raw(b"\x41\x89\x0d" + struct.pack("<I", handle_count_va))
        code.label("handle_done")
        # Width and line height remain logical. The sparse marker metadata was
        # emitted at exact 4x coordinates. The parser flattens successive rows
        # using a one-pixel separator, not a scaled separator: its cumulative
        # X tables therefore contain an extra three units per preceding row.
        # Remove that carry before division, including shared row-boundary
        # entries, or a later row's last character gains a pixel of advance.
        code.raw(b"\x8b\x46\x34\xc1\xe8\x02\x48\x89\x46\x34")
        code.raw(b"\x8b\x46\x38\x99\xf7\x7e\x4c\xc1\xf8\x02\x48\x89\x46\x38")
        code.raw(b"\xc1\x7e\x40\x02")
        code.raw(bytes.fromhex("8b7e4c 8b9e58020000 31c9"))
        code.label("boundary_loop")
        code.raw(b"\x0f\xb7\x44\x4e\x50\x66\x83\xf8\xff")
        code.jump_short_if(Condition.EQUAL, "boundary_next")
        code.raw(bytes.fromhex("ba01000000"))
        code.label("boundary_row")
        code.raw(bytes.fromhex("39fa"))
        code.jump_if(Condition.ABOVE_OR_EQUAL, "boundary_scale")
        code.raw(bytes.fromhex("0fb72c53 39e8"))
        code.jump_if(Condition.BELOW, "boundary_scale")
        code.raw(bytes.fromhex("42"))
        code.jump("boundary_row")
        code.label("boundary_scale")
        code.raw(bytes.fromhex("4a 8d1452 29d0"))
        code.raw(b"\x66\xc1\xe8\x02\x66\x89\x44\x4e\x50")
        code.label("boundary_next")
        code.raw(b"\x41\x81\xf9\x01\x01\x00\x00")
        code.jump_if(Condition.BELOW, "boundary_loop")

        code.raw(b"\x8b\x4e\x4c\x83\xf9\x01")
        code.jump_if(Condition.LESS_OR_EQUAL, "tables_done")
        code.raw(b"\x8b\xbe\x58\x02\x00\x00\x8b\xae\x5c\x02\x00\x00\x31\xdb")
        code.label("row_table_loop")
        code.raw(bytes.fromhex("0fb7045f 8d145b 29d0 66c1e802 6689045f"))
        code.raw(b"\x66\x8b\x44\x5d\x00\x66\x83\xc0\x03\x66\xc1\xe8\x02")
        code.raw(b"\x66\x89\x44\x5d\x00\x43\x3b\xd9")
        code.jump_if(Condition.BELOW, "row_table_loop")
        code.label("tables_done")
        code.raw(b"\xc7\x46\x3c\x00\x00\x00\x00")
        code.raw(b"\xff\x05" + struct.pack("<I", normalize_count_va))
        code.raw(b"\x61\x8b\x46\x38\x31\xd2\x5b")
        if bank_registration_va is not None:
            code.call_absolute(bank_registration_va)
        code.jump_absolute(self._font_metrics_continue_va)

        code.label("stock")
        code.raw(b"\x61")
        code.raw(self._font_metrics_original)
        if bank_registration_va is not None:
            code.call_absolute(bank_registration_va)
        code.jump_absolute(self._font_metrics_continue_va)
        return code.build()

    @staticmethod
    def _emit_hd_font_size_gate(code: X86Emitter) -> None:
        """Reject stock fonts before lookup; admit only exact narrow-bank layouts."""
        minimum_width = 1600
        code.raw(b"\x81\x7e\x34" + struct.pack("<I", minimum_width))
        code.jump_if(Condition.ABOVE_OR_EQUAL, "resolve_font")
        for index, layout in enumerate(FONT_ROW_BANK_LAYOUTS.values()):
            width, height = layout.image_size
            if width >= minimum_width:
                continue
            next_layout = f"next_narrow_font_{index}"
            for offset, expected in ((0x34, width), (0x38, height), (0x4C, layout.line_count)):
                code.raw(b"\x81\x7e" + bytes([offset]) + struct.pack("<I", expected))
                code.jump_if(Condition.NOT_EQUAL, next_layout)
            code.jump("resolve_font")
            code.label(next_layout)
        code.jump("stock")

    def build_loadsave_font_rect_helper(
        self,
        *,
        wrapper_va: int,
        root_ptr_va: int,
        trace_count_va: int,
        trace_input_va: int,
        trace_output_va: int,
        active_text_va: int,
    ) -> bytes:
        """Scale one glyph point inside a constructed record TextBox.

        Return one when ``ECX`` was recognized and rewritten, or zero when the
        active draw did not belong to a save-record TextBox. This helper deliberately
        touches only the two-DWORD X/Y argument owned by GK3's high-level font
        call; treating adjacent arguments as RECT.right/bottom corrupts the
        later clip and damage calculations.
        """
        # ECX is a writable destination RECT.  The Load/Save root owns a vector
        # of 0x4c-byte save records at +2b4/+2b8; each record points to its Name,
        # Day/Time, and Score TextBoxes at +20, +34, and +3c.  Their object
        # rectangles already carry the height-relative layout transform.  Map
        # each glyph relative to its exact drawing TextBox so the engine performs
        # clipping and damage tracking at the final physical anchor.  The final
        # blitter separately scales the glyph extent about this mapped point.
        code = X86Emitter(base_va=wrapper_va)
        code += b"\x53\x55\x56\x57\x31\xc0\x8b\xf9\x85\xff"
        code.jump_if(Condition.EQUAL, "done")
        for displacement in (0, 4):
            code += b"\x8b\x57" + bytes([displacement])
            code += b"\x89\x15" + struct.pack("<I", trace_input_va + displacement)
        code += b"\x8b\x2d" + struct.pack("<I", root_ptr_va) + b"\x85\xed"
        code.jump_if(Condition.EQUAL, "done")
        code += b"\x8b\x35" + struct.pack("<I", active_text_va) + b"\x85\xf6"
        code.jump_if(Condition.EQUAL, "done")
        # SaveGame embeds its editable name at +0x340. Selection has already
        # copied the fitted row rectangle into it; scale only local glyph
        # offsets about that physical anchor, exactly like record labels.
        code += b"\x81\x7d\x00" + struct.pack("<I", self.profile.address("savegame.vtable"))
        code.jump_if(Condition.NOT_EQUAL, "records")
        code += b"\x8d\x85\x40\x03\x00\x00\x3b\xc6"
        code.jump_if(Condition.EQUAL, "found")
        code.label("records")
        code += b"\x8b\x9d\xb4\x02\x00\x00\x8b\x95\xb8\x02\x00\x00"
        # Layout publishes the root before its record vector has necessarily
        # completed construction.  Accept only a bounded, stride-exact vector;
        # a transient begin/end pair must never become an arbitrary memory
        # walk merely because a glyph is submitted synchronously in Layout.
        code += b"\x3b\xda"
        code.jump_if(Condition.ABOVE_OR_EQUAL, "done")
        code += b"\x8b\xca\x2b\xcb\x81\xf9\xe0\x28\x01\x00"
        code.jump_if(Condition.ABOVE, "done")
        code += b"\x8b\xc1\x31\xd2\xb9\x4c\x00\x00\x00\xf7\xf1\x85\xd2"
        code.jump_if(Condition.NOT_EQUAL, "done")
        code += b"\x8b\x95\xb8\x02\x00\x00"
        code.label("record_loop")
        code += b"\x3b\xda"
        code.jump_if(Condition.ABOVE_OR_EQUAL, "done")

        for pointer_offset in (0x20, 0x34, 0x3C):
            next_text = f"next_text_{pointer_offset:x}"
            code += b"\x3b\x73" + bytes([pointer_offset])
            code.jump_if(Condition.NOT_EQUAL, next_text)
            code.jump("found")
            code.label(next_text)

        code += b"\x83\xc3\x4c"
        code.jump("record_loop")
        code.label("found")
        for displacement, anchor_offset in ((0, 0x1C), (4, 0x20)):
            if displacement == 0:
                code += b"\x8b\x07"
            else:
                code += b"\x8b\x47" + bytes([displacement])
            code += b"\x2b\x46" + bytes([anchor_offset])
            code += b"\x0f\xaf\x05" + struct.pack("<I", self._physical_width_va + 4)
            code += b"\x99\xb9\x00\x03\x00\x00\xf7\xf9"
            code += b"\x03\x46" + bytes([anchor_offset])
            if displacement == 0:
                code += b"\x89\x07"
            else:
                code += b"\x89\x47" + bytes([displacement])

        for displacement in (0, 4):
            code += b"\x8b\x57" + bytes([displacement])
            code += b"\x89\x15" + struct.pack("<I", trace_output_va + displacement)
        code += b"\xff\x05" + struct.pack("<I", trace_count_va)
        code += b"\xb8\x01\x00\x00\x00"

        code.label("done")
        code += b"\x5f\x5e\x5d\x5b\xc3"
        return code.build()

    def build_loadsave_damage_selector(
        self,
        *,
        wrapper_va: int,
        native_damage_ptr_va: int,
        native_damage_count_va: int,
        native_damage_rects_va: int,
        selection_rects_va: int,
        selection_repair_count_va: int,
        selection_repair_pending_va: int,
        full_damage_region_va: int,
    ) -> bytes:
        """Repair dynamic selection geometry and request complete damage.

        GK3 rewrites the three selected-row objects after construction using
        authored horizontal coordinates and physical vertical coordinates.
        Restore their canonical column extents before Draw. Every transformed
        interaction redraw uses the complete physical region: GK3 can emit
        preview/highlight traffic before the root traversal, and its authored
        partial collection cannot describe the resulting output-scale pixels.
        """
        # EAX is GK3's caller-owned collection and ECX is the concrete root.
        # Preserve thiscall state and every callee-saved register used below.
        # ESI retains the native collection until a repair proves that the
        # static complete collection is required; EBP is the repair flag.
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x53\x52\x55\x56\x57\x8b\xf0\x31\xed\x85\xc9")

        for child_offset, canonical_offset in (
            (0x2C4, 0),
            (0x2C8, 16),
            (0x2CC, 32),
        ):
            next_child = f"selection_child_{child_offset:x}_done"
            repair_child = f"selection_child_{child_offset:x}_repair"
            code.raw(b"\x8b\xb9" + struct.pack("<I", child_offset) + b"\x85\xff")
            code.jump_if(Condition.EQUAL, next_child)
            code.raw(b"\xa1" + struct.pack("<I", selection_rects_va + canonical_offset))
            code.raw(b"\x3b\x47\x1c")
            code.jump_if(Condition.NOT_EQUAL, repair_child)
            code.raw(b"\xa1" + struct.pack("<I", selection_rects_va + canonical_offset + 8))
            code.raw(b"\x3b\x47\x24")
            code.jump_if(Condition.EQUAL, next_child)
            code.label(repair_child)
            code.raw(b"\xa1" + struct.pack("<I", selection_rects_va + canonical_offset))
            code.raw(b"\x89\x47\x1c")
            code.raw(b"\xa1" + struct.pack("<I", selection_rects_va + canonical_offset + 8))
            code.raw(b"\x89\x47\x24\xbd\x01\x00\x00\x00")
            code.raw(b"\xff\x05" + struct.pack("<I", selection_repair_count_va))
            code.raw(
                b"\xc7\x05" + struct.pack("<I", selection_repair_pending_va) + b"\x01\x00\x00\x00"
            )
            code.label(next_child)

        # Retain the caller-owned collection for read-only diagnostics. GK3
        # reuses this object between traversals, so the capture harness can
        # recover its concrete region layout without changing behavior.
        code.raw(b"\x89\x35" + struct.pack("<I", native_damage_ptr_va))
        code.raw(b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x56\x04\x8b\x5e\x08")
        code.raw(b"\x3b\xd3")
        code.jump_if(Condition.ABOVE_OR_EQUAL, "done")
        # Empty collections are common once GK3 consumes a dirty region. Keep
        # the most recent non-empty sample so a later read-only probe observes
        # the cursor/hover damage that actually triggered the traversal.
        code.raw(b"\xc7\x05" + struct.pack("<I", native_damage_count_va) + b"\x00\x00\x00\x00")
        code.label("damage_trace_loop")
        code.raw(b"\x3b\xd3")
        code.jump_if(Condition.ABOVE_OR_EQUAL, "damage_trace_done")
        code.raw(b"\xa1" + struct.pack("<I", native_damage_count_va) + b"\x83\xf8\x08")
        code.jump_if(Condition.ABOVE_OR_EQUAL, "damage_trace_done")
        code.raw(b"\xc1\xe0\x04\x05" + struct.pack("<I", native_damage_rects_va) + b"\x8b\xf8")
        for offset in range(0, 16, 4):
            code.raw(b"\x8b\x42" + bytes([offset]) + b"\x89\x47" + bytes([offset]))
        code.raw(b"\xff\x05" + struct.pack("<I", native_damage_count_va))
        code.raw(b"\x83\xc2\x10")
        code.jump("damage_trace_loop")
        code.label("damage_trace_done")

        code.label("done")
        code.raw(b"\xbe" + struct.pack("<I", full_damage_region_va))
        code.raw(b"\x8b\xc6\x5f\x5e\x5d\x5a\x5b\xc3")
        return code.build()

    def build_loadsave_cache_update_helper(
        self,
        *,
        wrapper_va: int,
        ddraw_va: int,
        back_surface_va: int,
        surface_va: int,
        owner_va: int,
        ready_va: int,
        descriptor_va: int,
        source_rect_va: int,
        scratch_rect_va: int,
        create_result_va: int,
        capture_result_va: int,
        capture_count_va: int,
        full_capture_count_va: int,
        selection_repair_pending_va: int,
        full_damage_region_va: int,
        post_draw_cursor_presenter_va: int,
    ) -> bytes:
        """Capture the complete generation selected by the Load/Save redraw owner.

        The pre-Draw damage selector always requests a complete physical redraw.
        The post-Draw stack still carries the original native damage collection,
        not that replacement. Reusing it here loses updates outside those old
        rectangles, leaving stale list rows and scrollbar thumbs in the cache.
        Capture the same complete region that was actually drawn, before cursor
        presentation; no additional redraw or coordinate transform is needed.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x60")
        # Match build_loadsave_damage_selector even when no selection-column
        # repair was needed (notably a captured scrollbar-thumb drag).
        code.raw(b"\xbd" + struct.pack("<I", full_damage_region_va))
        code.raw(b"\x85\xed")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x3d" + struct.pack("<I", ddraw_va) + b"\x85\xff")
        code.jump_if(Condition.EQUAL, "invalidate")

        # Reuse the surface only for the same DirectDraw owner and dimensions.
        code.raw(b"\x8b\x35" + struct.pack("<I", surface_va) + b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "create")
        code.raw(b"\x3b\x3d" + struct.pack("<I", owner_va))
        code.jump_if(Condition.NOT_EQUAL, "release")
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va))
        code.raw(b"\x3b\x05" + struct.pack("<I", descriptor_va + 0x0C))
        code.jump_if(Condition.NOT_EQUAL, "release")
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\x3b\x05" + struct.pack("<I", descriptor_va + 0x08))
        code.jump_if(Condition.EQUAL, "surface_ready")

        code.label("release")
        code.raw(b"\x8b\x06\x56\xff\x50\x08\x31\xc0")
        for address in (surface_va, owner_va, ready_va):
            code.raw(b"\xa3" + struct.pack("<I", address))

        code.label("create")
        # DDSURFACEDESC retains its size/flags/caps; publish only live output
        # dimensions and the matching complete source rectangle.
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\xa3" + struct.pack("<I", descriptor_va + 0x08))
        code.raw(b"\xa3" + struct.pack("<I", source_rect_va + 12))
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va))
        code.raw(b"\xa3" + struct.pack("<I", descriptor_va + 0x0C))
        code.raw(b"\xa3" + struct.pack("<I", source_rect_va + 8))
        code.raw(b"\x31\xc0")
        code.raw(b"\xa3" + struct.pack("<I", source_rect_va))
        code.raw(b"\xa3" + struct.pack("<I", source_rect_va + 4))
        code.raw(b"\xa3" + struct.pack("<I", ready_va))
        code.raw(b"\x8b\x07\x6a\x00")
        code.raw(b"\x68" + struct.pack("<I", surface_va))
        code.raw(b"\x68" + struct.pack("<I", descriptor_va))
        code.raw(b"\x57\xff\x50\x18")
        code.raw(b"\xa3" + struct.pack("<I", create_result_va) + b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "invalidate")
        code.raw(b"\x8b\x35" + struct.pack("<I", surface_va) + b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "invalidate")
        code.raw(b"\x89\x3d" + struct.pack("<I", owner_va))

        code.label("surface_ready")
        # Load/Save's child tree targets GK3's live back surface even though
        # the root call also carries an encoded canvas handle. The latter is a
        # distinct blank resource at high resolutions; treating it as the
        # display page makes every successful cache capture black.
        code.raw(b"\x8b\x1d" + struct.pack("<I", back_surface_va) + b"\x85\xdb")
        code.jump_if(Condition.EQUAL, "invalidate")
        code.raw(b"\x8b\x75\x04\x8b\x6d\x08")
        code.raw(b"\x3b\xf5")
        code.jump_if(Condition.ABOVE_OR_EQUAL, "done")
        # Reject malformed/unbounded collections before reading their RECTs.
        code.raw(b"\x8b\xc5\x2b\xc6\x3d\x00\x04\x00\x00")
        code.jump_if(Condition.ABOVE, "done")
        code.raw(b"\xa8\x0f")
        code.jump_if(Condition.NOT_EQUAL, "done")

        code.label("capture_loop")
        code.raw(b"\x3b\xf5")
        code.jump_if(Condition.ABOVE_OR_EQUAL, "done")
        # Clamp every producer rectangle to the physical surface. Native
        # cursor damage can legally straddle an edge by a few pixels.
        for source_offset, target_offset, dimension_va, near in (
            (0, 0, None, True),
            (4, 4, None, True),
            (8, 8, self._physical_width_va, False),
            (12, 12, self._physical_width_va + 4, False),
        ):
            code.raw(b"\x8b\x46" + bytes([source_offset]))
            if near:
                code.raw(b"\x85\xc0")
                code.jump_if(Condition.GREATER_OR_EQUAL, f"component_{source_offset}_ready")
                code.raw(b"\x31\xc0")
            else:
                if dimension_va is None:
                    msg = "far-edge capture components require a physical dimension"
                    raise ValueError(msg)
                code.raw(b"\x3b\x05" + struct.pack("<I", dimension_va))
                code.jump_if(Condition.LESS_OR_EQUAL, f"component_{source_offset}_ready")
                code.raw(b"\xa1" + struct.pack("<I", dimension_va))
            code.label(f"component_{source_offset}_ready")
            code.raw(b"\xa3" + struct.pack("<I", scratch_rect_va + target_offset))
        code.raw(b"\xa1" + struct.pack("<I", scratch_rect_va))
        code.raw(b"\x3b\x05" + struct.pack("<I", scratch_rect_va + 8))
        code.jump_if(Condition.GREATER_OR_EQUAL, "capture_next")
        code.raw(b"\xa1" + struct.pack("<I", scratch_rect_va + 4))
        code.raw(b"\x3b\x05" + struct.pack("<I", scratch_rect_va + 12))
        code.jump_if(Condition.GREATER_OR_EQUAL, "capture_next")

        # cache.BltFast(left, top, back, &rect, DDBLTFAST_WAIT) copies only
        # pixels whose native producer transaction has just completed on this
        # back page. WAIT makes an otherwise-transient busy surface part of
        # the same producer transaction: dropping one unique damage rectangle
        # would leave the retained composition permanently incomplete.
        code.raw(b"\x8b\x3d" + struct.pack("<I", surface_va) + b"\x8b\x07\x6a\x10")
        code.raw(b"\x68" + struct.pack("<I", scratch_rect_va))
        code.raw(b"\x53")
        code.raw(b"\xff\x35" + struct.pack("<I", scratch_rect_va + 4))
        code.raw(b"\xff\x35" + struct.pack("<I", scratch_rect_va))
        code.raw(b"\x57\xff\x50\x1c")
        code.raw(b"\xa3" + struct.pack("<I", capture_result_va) + b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "invalidate")
        code.raw(b"\xff\x05" + struct.pack("<I", capture_count_va))

        # A successful full-surface generation makes every prior partial merge
        # meaningful and is the only edge allowed to publish cache readiness.
        code.raw(b"\x83\x3d" + struct.pack("<I", scratch_rect_va) + b"\x00")
        code.jump_if(Condition.NOT_EQUAL, "capture_next")
        code.raw(b"\x83\x3d" + struct.pack("<I", scratch_rect_va + 4) + b"\x00")
        code.jump_if(Condition.NOT_EQUAL, "capture_next")
        code.raw(b"\xa1" + struct.pack("<I", scratch_rect_va + 8))
        code.raw(b"\x3b\x05" + struct.pack("<I", self._physical_width_va))
        code.jump_if(Condition.NOT_EQUAL, "capture_next")
        code.raw(b"\xa1" + struct.pack("<I", scratch_rect_va + 12))
        code.raw(b"\x3b\x05" + struct.pack("<I", self._physical_width_va + 4))
        code.jump_if(Condition.NOT_EQUAL, "capture_next")
        code.raw(b"\xc7\x05" + struct.pack("<I", ready_va) + b"\x01\x00\x00\x00")
        code.raw(b"\xff\x05" + struct.pack("<I", full_capture_count_va))
        code.raw(b"\xc7\x05" + struct.pack("<I", selection_repair_pending_va) + b"\x00\x00\x00\x00")
        code.label("capture_next")
        code.raw(b"\x83\xc6\x10")
        code.jump("capture_loop")

        code.label("invalidate")
        code.raw(b"\xc7\x05" + struct.pack("<I", ready_va) + b"\x00\x00\x00\x00")
        code.label("done")
        # The cache must remain cursor-free. Only after every authoritative
        # root rectangle has been merged may the visual top layer be restored
        # on the exact encoded destination used by this Draw transaction.
        code.raw(b"\x8b\x44\x24\x24")
        code.call_absolute(post_draw_cursor_presenter_va)
        code.raw(b"\x61\xc2\x08\x00")
        return code.build()

    def build_loadsave_page_clear_helper(
        self,
        *,
        wrapper_va: int,
        back_surface_va: int,
        bltfx_va: int,
        result_va: int,
        count_va: int,
    ) -> bytes:
        """Start every authoritative Load/Save generation on a black page.

        The stock tree paints controls and artwork over an assumed-black flip
        page; it does not cover every pixel itself.  A page last owned by the
        title screen therefore leaks through the first complete Load/Save
        generation on modern rotating chains.  This helper runs inside the
        root's producer transaction, before native Draw, and fills the exact
        back page that the cache-update helper will capture afterward. Two
        successful fills initialize the pages in GK3's flip chain and remove
        any out-of-tree preview or highlight transfer emitted immediately
        before the root traversal. The matching damage selector requests a
        complete transformed tree on every interaction-driven traversal, so
        no partial producer is asked to reconstruct pixels erased here. The
        steady-state pre-Flip presenter remains one cached ``BltFast`` and no
        fill occurs while the screen is idle.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x9c\x60")
        # Only the first two successful generations for this exact root need
        # initialization. The root wrapper resets this counter when ownership
        # changes. Clearing an already-initialized page on every subsequent
        # no-damage traversal races the pre-Flip cache replay and can leave an
        # otherwise live Restore browser completely black.
        code.raw(b"\x83\x3d" + struct.pack("<I", count_va) + b"\x02")
        code.jump_if(Condition.ABOVE_OR_EQUAL, "done")
        code.raw(b"\x8b\x35" + struct.pack("<I", back_surface_va) + b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "done")
        # IDirectDrawSurface4::Blt(NULL, NULL, NULL,
        # DDBLT_COLORFILL | DDBLT_WAIT, &black_bltfx) fills the complete page.
        code.raw(b"\x8b\x1e")
        code.raw(b"\x68" + struct.pack("<I", bltfx_va))
        code.raw(b"\x68" + struct.pack("<I", self._ddblt_colorfill_wait))
        code.raw(b"\x6a\x00\x6a\x00\x6a\x00\x56\xff\x53\x14")
        code.raw(b"\xa3" + struct.pack("<I", result_va) + b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\xff\x05" + struct.pack("<I", count_va))
        code.label("done")
        code.raw(b"\x61\x9d\xc3")
        return code.build()

    @staticmethod
    def build_loadsave_frame_presenter(
        *,
        wrapper_va: int,
        current_layer_va: int,
        root_ptr_va: int,
        fixed_canvas_owner_va: int,
        cache_surface_va: int,
        cache_ready_va: int,
        source_rect_va: int,
        back_surface_va: int,
        present_result_va: int,
        present_count_va: int,
        frame_present_count_va: int,
    ) -> bytes:
        """Replay the canonical Load/Save composition before native Flip.

        DirectDraw can rotate storage behind a stable back-surface interface.
        The exact pre-Flip callback is therefore the sole physical-page owner:
        copy the canonical off-screen composition to that current page, then
        let the outer compositor add the current tooltip and cursor above it.
        One same-size hardware BltFast is independent of page count and avoids
        the legacy tree's incorrect z-order under repeated complete redraws.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x9c\x60")
        code.raw(b"\x8b\x1d" + struct.pack("<I", fixed_canvas_owner_va))
        code.raw(b"\x85\xdb")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x3b\x1d" + struct.pack("<I", root_ptr_va))
        code.jump_if(Condition.NOT_EQUAL, "done")
        # An unwrapped modal may leave the previous render root published.
        # The visible top layer, not that stale pointer, owns presentation.
        code.call_absolute(current_layer_va)
        code.raw(b"\x3b\xc3")
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\x83\x3d" + struct.pack("<I", cache_ready_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x35" + struct.pack("<I", cache_surface_va) + b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x3d" + struct.pack("<I", back_surface_va) + b"\x85\xff")
        code.jump_if(Condition.EQUAL, "done")
        # The cache is already a complete, immutable frame at this edge. WAIT
        # avoids a needless skipped presentation while DirectDraw is briefly
        # busy, without adding any frame limiter or resolution-specific path.
        code.raw(b"\x8b\x07\x6a\x10")
        code.raw(b"\x68" + struct.pack("<I", source_rect_va))
        code.raw(b"\x56\x6a\x00\x6a\x00\x57\xff\x50\x1c")
        code.raw(b"\xa3" + struct.pack("<I", present_result_va) + b"\x85\xc0")
        # A failed destination transfer does not invalidate the source cache.
        # Keep it ready so a recoverable driver error is retried next Flip.
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\xff\x05" + struct.pack("<I", present_count_va))
        code.raw(b"\xff\x05" + struct.pack("<I", frame_present_count_va))
        code.label("done")
        code.raw(b"\x61\x9d\xc3")
        return code.build()

    def build_loadsave_rect_transform(self) -> bytes:
        """Map one screen-space RECT uniformly about the display center."""
        code = bytearray(b"\x53\x56\x8b\xf1")
        for displacement, dimension_va in (
            (0, self._physical_width_va),
            (4, self._physical_width_va + 4),
            (8, self._physical_width_va),
            (12, self._physical_width_va + 4),
        ):
            code += b"\x8b\x46" + bytes([displacement])
            code += b"\x8b\x15" + struct.pack("<I", dimension_va)
            code += b"\xd1\xfa\x2b\xc2"
            code += b"\x0f\xaf\x05" + struct.pack("<I", self._physical_width_va + 4)
            code += b"\x99\xbb\x00\x03\x00\x00\xf7\xfb"
            code += b"\x8b\x15" + struct.pack("<I", dimension_va) + b"\xd1\xfa\x03\xc2"
            code += b"\x89\x46" + bytes([displacement])
        code += b"\x5e\x5b\xc3"
        return bytes(code)

    def build_loadsave_layout_wrapper(
        self,
        *,
        wrapper_va: int,
        rect_transform_va: int,
        layout_root_va: int,
        selection_rects_va: int,
        initial_preview_transform_va: int,
        initial_button_transform_va: int,
    ) -> bytes:
        """Scale Load/Save cached geometry immediately after construction."""
        # The native virtual is thiscall with two stack arguments and RET 8.
        # A 640x480 root is the unmodified layout marker; once transformed its
        # width changes, making repeated virtual calls naturally idempotent.
        code = X86Emitter(base_va=wrapper_va)
        code += b"\x55\x8b\xec\x56\x8b\xf1"
        code += b"\xff\x75\x0c\xff\x75\x08\x8b\xce"
        code.call_absolute(self._native_loadsave_layout_va)
        code += b"\x60"
        code += b"\x8b\x46\x24\x2b\x46\x1c\x3d\x80\x02\x00\x00"
        code.jump_if(Condition.NOT_EQUAL, "done")
        code += b"\x8b\x46\x28\x2b\x46\x20\x3d\xe0\x01\x00\x00"
        code.jump_if(Condition.NOT_EQUAL, "done")

        for offset in (0x1C, 0x27C, 0x28C, 0x29C):
            code += b"\x8d\x8e" + struct.pack("<I", offset)
            code.call_absolute(rect_transform_va)

        code += b"\x3b\x35" + struct.pack("<I", layout_root_va)
        code.jump_if(Condition.EQUAL, "done")
        code += b"\x89\x35" + struct.pack("<I", layout_root_va)

        # Native construction can already select a save and attach its real
        # preview before this root is published. Fit that nonempty rectangle
        # once with the rest of the constructed layout. An empty 65535 sentinel
        # must stay untouched; later selection attachments have their own hook.
        code += b"\x8d\x8e\xf0\x02\x00\x00\x8b\x41\x08\x2b\x01"
        code.jump_if(Condition.LESS_OR_EQUAL, "preview_done")
        code += b"\x8b\x41\x0c\x2b\x41\x04"
        code.jump_if(Condition.LESS_OR_EQUAL, "preview_done")
        code.call_absolute(initial_preview_transform_va)
        code.label("preview_done")
        for offset in (0x140, 0x1DC):
            code += b"\x8d\x8e" + struct.pack("<I", offset + 0x1C)
            code.call_absolute(initial_button_transform_va)

        code += b"\x8b\xbe\x20\x03\x00\x00"
        code += b"\x8b\x9e\x24\x03\x00\x00"
        code.label("cover_check")
        code += b"\x3b\xfb"
        code.jump_if(Condition.ABOVE_OR_EQUAL, "after_covers")
        code += b"\x8b\x0f\x85\xc9"
        code.jump_if(Condition.EQUAL, "cover_done")
        code += b"\x83\xc1\x1c"
        code.call_absolute(rect_transform_va)
        code.label("cover_done")
        code += b"\x83\xc7\x04"
        code.jump_short("cover_check")
        code.label("after_covers")

        for offset, preserved_offset in (
            (0x2AC, None),
            (0x2C4, 0),
            (0x2C8, 16),
            (0x2CC, 32),
        ):
            child_done = f"child_done_{offset:x}"
            code += b"\x8b\x8e" + struct.pack("<I", offset) + b"\x85\xc9"
            code.jump_if(Condition.EQUAL, child_done)
            code += b"\x83\xc1\x1c"
            code.call_absolute(rect_transform_va)
            if preserved_offset is not None:
                code += b"\x56\x57\x8b\xf1"
                code += b"\xbf" + struct.pack("<I", selection_rects_va + preserved_offset)
                code += b"\xb9\x04\x00\x00\x00\xf3\xa5\x5f\x5e"
            code.label(child_done)

        code += b"\x8b\xbe\xb4\x02\x00\x00"
        code += b"\x8b\x9e\xb8\x02\x00\x00"
        code.label("record_check")
        code += b"\x3b\xfb"
        code.jump_if(Condition.ABOVE_OR_EQUAL, "done")
        for offset in (0x20, 0x34, 0x3C):
            text_done = f"text_done_{offset:x}"
            code += b"\x8b\x4f" + bytes([offset]) + b"\x85\xc9"
            code.jump_if(Condition.EQUAL, text_done)
            code += b"\x83\xc1\x1c"
            code.call_absolute(rect_transform_va)
            code.label(text_done)
        code += b"\x83\xc7\x4c"
        code.jump_short("record_check")

        code.label("done")
        code += b"\x61\x5e\x5d\xc2\x08\x00"
        return code.build()

    def build_loadsave_initial_preview_transform(self) -> bytes:
        """Fit an already attached preview with selection-time edge rounding.

        ECX is the native preview RECT and ESI the newly fitted root. Native
        construction centers the 640x480 root on the physical framebuffer;
        subtract that old origin before scaling, then add the fitted origin.
        This agrees with later attachment even for fractional/odd-size fits.
        """
        code = X86Emitter(base_va=0)
        code.raw(b"\x60\x8b\xf9\x31\xdb")
        code.label("edge")
        code.raw(b"\x8b\xeb\x83\xe5\x04")
        code.raw(b"\x8b\x85" + struct.pack("<I", self._physical_width_va))
        code.raw(b"\xd1\xf8\xba\x40\x01\x00\x00\x85\xed")
        code.jump_short_if(Condition.EQUAL, "origin")
        code.raw(b"\xba\xf0\x00\x00\x00")
        code.label("origin")
        code.raw(b"\x2b\xc2\x8b\x14\x1f\x2b\xd0\x8b\xc2")
        code.raw(b"\x0f\xaf\x05" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\x99\xb9\x00\x03\x00\x00\xf7\xf9\x03\x44\x2e\x1c\x89\x04\x1f")
        code.raw(b"\x83\xc3\x04\x83\xfb\x10")
        code.jump_short_if(Condition.LESS, "edge")
        code.raw(b"\x61\xc3")
        return code.build()

    def build_loadsave_preview_attach(
        self, *, wrapper_va: int, layout_root_va: int, preview_rect_va: int
    ) -> bytes:
        """Fit the real selected bitmap after native attachment, never its placeholder."""
        code = X86Emitter(base_va=wrapper_va)
        # Preserve the native two-argument thiscall and its result. The native
        # setter may only move an existing image, retaining its previous size:
        # always derive extents from the bitmap, not the already fitted child.
        code += b"\x55\x8b\xec\x83\xec\x10\x56\x8b\xf1"
        code += b"\xff\x75\x0c\xff\x75\x08\xff\x92\xc4\x00\x00\x00"
        code += b"\x9c\x60\x8d\x9e\x2c\xfd\xff\xff"
        code += b"\x3b\x1d" + struct.pack("<I", layout_root_va)
        code.jump_if(Condition.NOT_EQUAL, "done")
        code += b"\xff\x75\x0c\x8b\x0d" + struct.pack("<I", self.profile.address("bitmap.manager"))
        code.call_absolute(self.profile.address("bitmap.dimensions"))
        code += b"\x8b\x10\x89\x55\xf8\x8b\x50\x04\x89\x55\xfc"
        code += b"\x8b\x7d\x08\x8b\x07\x89\x45\xf0\x01\x45\xf8"
        code += b"\x8b\x47\x04\x89\x45\xf4\x01\x45\xfc"
        code += b"\xb9\x00\x03\x00\x00"
        for local, origin in ((0xF0, 0x1C), (0xF4, 0x20), (0xF8, 0x1C), (0xFC, 0x20)):
            # Authored point is relative to the already fitted root; scale
            # each edge independently to preserve its rounding convention.
            code += b"\x8b\x45" + bytes([local]) + b"\x2b\x43" + bytes([origin])
            code += b"\x0f\xaf\x05" + struct.pack("<I", self._physical_width_va + 4)
            code += b"\x99\xf7\xf9\x03\x43" + bytes([origin])
            code += b"\x89\x45" + bytes([local])
        # Native SetRect schedules old/new damage. Do not silently mutate
        # child bounds or resize the source surface used by other consumers.
        code += b"\x8d\x45\xf0\x50\x8b\xce\x8b\x06\xff\x90\xa8\x00\x00\x00"
        code += b"\x8d\x75\xf0\xbf" + struct.pack("<I", preview_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        code.label("done")
        code += b"\x61\x9d\x5e\xc9\xc2\x08\x00"
        return code.build()

    def build_loadsave_background_helper(
        self,
        *,
        wrapper_va: int,
        control_predicate_va: int,
        rect_transform_va: int,
        root_ptr_va: int,
        source_rect_va: int,
        dest_rect_va: int,
        scroll_raw_top_va: int,
        scroll_origin_seen_va: int,
        preview_trace_va: int,
    ) -> bytes:
        """Replace the clipped 640x480 Load/Save background transfer."""
        # ECX points at the outer blitter wrapper's PUSHAD frame. The initial
        # HD background submission uses the complete 2560x1920 source extent
        # at the root's near edge and must be reconstructed as the fitted root.
        # Later dirty redraws already carry physical destination slices; those
        # must stay clipped or a cursor-sized update repaints the entire shared
        # Save background while only one child is eligible to redraw over it.
        code = X86Emitter(base_va=wrapper_va)
        code += b"\x8b\xe9"
        code += b"\x8b\x35" + struct.pack("<I", root_ptr_va) + b"\x85\xf6"
        code.jump_if(Condition.EQUAL, "failed")
        code += b"\x8b\x7d\x28\x85\xff"
        code.jump_if(Condition.EQUAL, "failed")

        # GK3 brackets the native root with four black cover surfaces.  They
        # already cover the complete area outside the larger mapped root and
        # must keep their physical rectangles; mapping them would create
        # negative DirectDraw destinations and abort the layer traversal.
        for dest_offset, root_offset, condition in (
            (8, 0x1C, Condition.LESS_OR_EQUAL),
            (0, 0x24, Condition.GREATER_OR_EQUAL),
            (12, 0x20, Condition.LESS_OR_EQUAL),
            (4, 0x28, Condition.GREATER_OR_EQUAL),
        ):
            code += b"\x8b\x47" + bytes([dest_offset])
            code += b"\x3b\x46" + bytes([root_offset])
            code.jump_if(condition, "cover")

        code += b"\x8b\x45\x24\x85\xc0"
        code.jump_if(Condition.EQUAL, "failed")

        # Diagnostic: retain the last bounded 4:3 image transfer. Save-game
        # previews are the only Load/Save sources in this range; the 2560x1920
        # screen background and compact UI sprites fall outside it.
        code += b"\x8b\x48\x38\x81\xf9\xa0\x00\x00\x00"
        code.jump_if(Condition.LESS, "preview_trace_done")
        code += b"\x81\xf9\x00\x04\x00\x00"
        code.jump_if(Condition.GREATER, "preview_trace_done")
        code += b"\x8b\x50\x3c\x83\xfa\x78"
        code.jump_if(Condition.LESS, "preview_trace_done")
        code += b"\x8b\xc1\x6b\xc0\x03\xc1\xe2\x02\x3b\xc2"
        code.jump_if(Condition.NOT_EQUAL, "preview_trace_done")
        for source_offset, trace_offset in ((0, 0), (4, 4), (8, 8), (12, 12)):
            code += b"\x8b\x47" + bytes([source_offset])
            code += b"\xa3" + struct.pack("<I", preview_trace_va + trace_offset)
        code += b"\x8b\x45\x24\x8b\x48\x38"
        code += b"\x89\x0d" + struct.pack("<I", preview_trace_va + 16)
        code += b"\x8b\x48\x3c\x89\x0d" + struct.pack("<I", preview_trace_va + 20)
        code += b"\xff\x05" + struct.pack("<I", preview_trace_va + 24)
        code.label("preview_trace_done")
        code += b"\x8b\x45\x24"

        # Match the concrete preview before looking at source dimensions. Save
        # files can carry either the original 640x480 image or a replacement
        # at a much larger resolution, but both are drawn through the one
        # preview child embedded at +0x2D4. Normal traversal supplies its
        # transformed near edge, while one legacy late-child redraw supplies
        # (0,0) but retains the exact transformed preview extent. Require that
        # live width/height first and admit only those two near-edge forms. A
        # full background, arbitrary dirty slice, or cursor scratch transfer
        # cannot satisfy the complete geometry identity. Always sample the
        # complete live source into the embedded child rectangle so changing
        # preview resolution changes detail, not layout.
        code += b"\x8b\x4f\x08\x2b\x0f"
        code += b"\x8b\x96\xf8\x02\x00\x00\x2b\x96\xf0\x02\x00\x00\x3b\xca"
        code.jump_if(Condition.NOT_EQUAL, "background_check")
        code += b"\x8b\x4f\x0c\x2b\x4f\x04"
        code += b"\x8b\x96\xfc\x02\x00\x00\x2b\x96\xf4\x02\x00\x00\x3b\xca"
        code.jump_if(Condition.NOT_EQUAL, "background_check")
        code += b"\x8b\x0f\x3b\x8e\xf0\x02\x00\x00"
        code.jump_short_if(Condition.NOT_EQUAL, "preview_origin_check")
        code += b"\x8b\x4f\x04\x3b\x8e\xf4\x02\x00\x00"
        code.jump_short_if(Condition.EQUAL, "preview")
        code.label("preview_origin_check")
        code += b"\x8b\x0f\x0b\x4f\x04"
        code.jump_if(Condition.NOT_EQUAL, "background_check")
        code.label("preview")
        code += b"\x31\xc9\x89\x0d" + struct.pack("<I", source_rect_va)
        code += b"\x89\x0d" + struct.pack("<I", source_rect_va + 4)
        code += b"\x8b\x48\x38\x89\x0d" + struct.pack("<I", source_rect_va + 8)
        code += b"\x8b\x48\x3c\x89\x0d" + struct.pack("<I", source_rect_va + 12)
        code += b"\x8d\xb6\xf0\x02\x00\x00\xbf" + struct.pack("<I", dest_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        code += b"\xc7\x45\x28" + struct.pack("<I", dest_rect_va)
        code += b"\xc7\x45\x2c" + struct.pack("<I", source_rect_va)
        code += b"\xc7\x05" + struct.pack("<I", scroll_origin_seen_va)
        code += b"\x00\x00\x00\x00"
        code += b"\xb8\x01\x00\x00\x00\xc3"

        code.label("background_check")
        # Stock artwork still submits its complete authored 640x480 rectangle
        # at the mapped root origin. Unlike the dense source, that extent is
        # smaller than the fitted root. Admit only this complete transfer;
        # clipped dirty slices and the concrete preview above stay separate.
        code += b"\x81\x78\x38\x80\x02\x00\x00"
        code.jump_if(Condition.NOT_EQUAL, "dense_background_check")
        code += b"\x81\x78\x3c\xe0\x01\x00\x00"
        code.jump_if(Condition.NOT_EQUAL, "child_check")
        for offset, root_offset in ((0, 0x1C), (4, 0x20)):
            code += b"\x8b\x4f" + bytes([offset])
            code += b"\x3b\x4e" + bytes([root_offset])
            code.jump_if(Condition.NOT_EQUAL, "cover")
        for first, second, extent in ((0, 8, 640), (4, 12, 480)):
            code += b"\x8b\x4f" + bytes([second]) + b"\x2b\x4f" + bytes([first])
            code += b"\x81\xf9" + struct.pack("<I", extent)
            code.jump_if(Condition.NOT_EQUAL, "cover")
        code += b"\x8b\x55\x2c\x85\xd2"
        code.jump_if(Condition.EQUAL, "cover")
        for offset, extent in ((0, 0), (4, 0), (8, 640), (12, 480)):
            code += (
                b"\x83\x7a" + bytes([offset, 0])
                if extent == 0
                else b"\x81\x7a" + bytes([offset]) + struct.pack("<I", extent)
            )
            code.jump_if(Condition.NOT_EQUAL, "cover")
        code.jump_short("full_background")
        code.label("dense_background_check")
        code += b"\x81\x78\x38\x00\x0a\x00\x00"
        code.jump_if(Condition.NOT_EQUAL, "child_check")
        code += b"\x81\x78\x3c\x80\x07\x00\x00"
        code.jump_if(Condition.NOT_EQUAL, "child_check")
        # The raw initial extent is larger than the fitted root on at least one
        # axis after screen clipping. A physical dirty slice is bounded by both
        # fitted dimensions and should pass through with native source clipping.
        code += b"\x8b\x4f\x08\x2b\x0f\x8b\x56\x24\x2b\x56\x1c\x3b\xca"
        code.jump_short_if(Condition.GREATER, "full_background")
        code += b"\x8b\x4f\x0c\x2b\x4f\x04\x8b\x56\x28\x2b\x56\x20\x3b\xca"
        code.jump_if(Condition.LESS_OR_EQUAL, "cover")
        code.label("full_background")
        code += b"\x83\xc6\x1c\xbf" + struct.pack("<I", dest_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        code.label("full_source")
        code += b"\x31\xc0\xa3" + struct.pack("<I", source_rect_va)
        code += b"\xa3" + struct.pack("<I", source_rect_va + 4)
        code += b"\x8b\x45\x24\x8b\x48\x38"
        code += b"\x89\x0d" + struct.pack("<I", source_rect_va + 8)
        code += b"\x8b\x48\x3c\x89\x0d" + struct.pack("<I", source_rect_va + 12)
        code += b"\xc7\x45\x28" + struct.pack("<I", dest_rect_va)
        code += b"\xc7\x45\x2c" + struct.pack("<I", source_rect_va)
        code += b"\xc7\x05" + struct.pack("<I", scroll_origin_seen_va)
        code += b"\x00\x00\x00\x00"
        code += b"\xb8\x01\x00\x00\x00\xc3"

        # Child objects have already had their top-left anchors moved by the
        # construction-time layout transform, but GK3 still submits their
        # authored pixel extents.  Stretch those extents by physical height so
        # the preview, buttons, and compact row surfaces occupy their enlarged
        # object rectangles.  Large covers, background slices, and font atlases
        # remain native; glyph spacing needs a separate TextBox-level mapping.
        code.label("child_check")
        code.call_absolute(control_predicate_va)
        code.jump_if(Condition.BELOW, "scrollbar")
        # Cursor composition uses two scratch surfaces here: GK3 first copies
        # the 64x64 backing store into a 128x128 work surface and then submits
        # that work surface to the screen with an already-physical rectangle.
        # Neither transfer is a Load/Save widget. Scaling the latter turns a
        # clipped cursor restore into an oversized brown block. The
        # actual cursor sprite is owned by the earlier concrete-drawable branch
        # in the shared dispatcher, so both exact scratch sizes stay native.
        code += b"\x8b\x48\x38\x3b\x48\x3c"
        code.jump_if(Condition.NOT_EQUAL, "not_cursor_backing")
        code += b"\x83\xf9\x40"
        code.jump_if(Condition.EQUAL, "cover")
        code += b"\x81\xf9\x80\x00\x00\x00"
        code.jump_if(Condition.EQUAL, "cover")
        code.label("not_cursor_backing")

        # The thumb is a dynamically composed 22-pixel-wide surface, whose
        # height depends on the visible/total row ratio (not a 22x23 tile).
        # Its native child remains in screen-centered logical coordinates.
        # Match that concrete child and all destination edges before mapping.
        code += b"\x8b\x45\x24\x83\x78\x38\x16"
        code.jump_if(Condition.NOT_EQUAL, "size_check")
        code += b"\x8b\x9e\xac\x02\x00\x00\x85\xdb"
        code.jump_short_if(Condition.EQUAL, "size_check")
        code += b"\x8b\x9b\xd4\x00\x00\x00\x85\xdb"
        code.jump_short_if(Condition.EQUAL, "size_check")
        code += b"\x81\x3b" + struct.pack("<I", self.profile.address("scrollbar_thumb.vtable"))
        code.jump_short_if(Condition.NOT_EQUAL, "size_check")
        for offset in range(0, 16, 4):
            code += b"\x8b\x4f" + bytes([offset])
            code += b"\x3b\x4b" + bytes([0x1C + offset])
            code.jump_short_if(Condition.NOT_EQUAL, "tile_check")
        code += b"\x8b\xf7\xbf" + struct.pack("<I", dest_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        code += b"\xb9" + struct.pack("<I", dest_rect_va)
        code.call_absolute(rect_transform_va)
        code += b"\xc7\x45\x28" + struct.pack("<I", dest_rect_va)
        code += b"\xb8\x01\x00\x00\x00\xc3"

        code.label("tile_check")
        code += b"\x83\x78\x3c\x17"
        code.jump_if(Condition.BELOW_OR_EQUAL, "scrollbar")
        code.label("size_check")
        code += b"\x8b\x45\x24\x8b\x50\x3c"
        # The concrete embedded buttons can now own 4x artwork wider than the
        # old compact-surface threshold. Match their active resource identity,
        # not merely a larger dimension range (which would admit backgrounds).
        code.raw(b"\x8b\x1d" + struct.pack("<I", self.profile.address("bitmap.manager")))
        code.raw(b"\x85\xdb")
        code.jump_if(Condition.EQUAL, "compact_size")
        code.raw(b"\x8b\x93\x20\x01\x00\x00\x85\xd2")
        code.jump_if(Condition.EQUAL, "compact_size")
        for offset in (0x16C, 0x208):
            next_button = f"next_button_{offset:x}"
            code.raw(b"\x0f\xb7\x8e" + struct.pack("<I", offset))
            code.raw(b"\x3b\x8b\x24\x01\x00\x00")
            code.jump_if(Condition.ABOVE_OR_EQUAL, next_button)
            code.raw(b"\x8b\x0c\x8a\x85\xc9")
            code.jump_if(Condition.EQUAL, next_button)
            code.raw(b"\x3b\x41\x30")
            code.jump_if(Condition.EQUAL, "scale_extent")
            code.label(next_button)
        code.label("compact_size")
        code.raw(b"\x8b\x50\x3c")
        code += b"\x81\x78\x38\x00\x01\x00\x00"
        code.jump_if(Condition.ABOVE, "cover")
        code += b"\x81\xfa\x00\x01\x00\x00"
        code.jump_if(Condition.ABOVE, "cover")
        code.label("scale_extent")
        code += b"\x8b\xf7\xbf" + struct.pack("<I", dest_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        for first, second in ((0, 8), (4, 12)):
            code += b"\xa1" + struct.pack("<I", dest_rect_va + second)
            code += b"\x2b\x05" + struct.pack("<I", dest_rect_va + first)
            code += b"\x0f\xaf\x05" + struct.pack("<I", self._physical_width_va + 4)
            code += b"\x99\xb9\x00\x03\x00\x00\xf7\xf9"
            code += b"\x03\x05" + struct.pack("<I", dest_rect_va + first)
            code += b"\xa3" + struct.pack("<I", dest_rect_va + second)
        code += b"\xc7\x45\x28" + struct.pack("<I", dest_rect_va)
        code += b"\xb8\x01\x00\x00\x00\xc3"

        # Compact track/arrow transfers form a separate track-relative stream.
        # They are not the variable-height composed thumb matched above.
        code.label("scrollbar")
        code += b"\x8b\x9e\xac\x02\x00\x00\x85\xdb"
        code.jump_if(Condition.EQUAL, "cover")
        code += b"\x83\x3d" + struct.pack("<I", scroll_origin_seen_va) + b"\x00"
        code.jump_short_if(Condition.NOT_EQUAL, "scroll_origin_ready")
        code += b"\x8b\x4f\x04\x89\x0d" + struct.pack("<I", scroll_raw_top_va)
        code += b"\xc7\x05" + struct.pack("<I", scroll_origin_seen_va)
        code += b"\x01\x00\x00\x00"
        code.label("scroll_origin_ready")
        code += b"\x8b\x43\x1c\xa3" + struct.pack("<I", dest_rect_va)
        code += b"\x8b\x43\x24\xa3" + struct.pack("<I", dest_rect_va + 8)
        for source_offset, dest_offset in ((4, 4), (12, 12)):
            code += b"\x8b\x47" + bytes([source_offset])
            code += b"\x2b\x05" + struct.pack("<I", scroll_raw_top_va)
            code += b"\x8b\x4b\x28\x2b\x4b\x20\x0f\xaf\xc1\x99"
            code += b"\xb9\x81\x01\x00\x00\xf7\xf9\x03\x43\x20"
            code += b"\xa3" + struct.pack("<I", dest_rect_va + dest_offset)
        code += b"\xc7\x45\x28" + struct.pack("<I", dest_rect_va)
        code += b"\xb8\x01\x00\x00\x00\xc3"

        code.label("cover")
        code += b"\xb8\x02\x00\x00\x00\xc3"
        code.label("failed")
        code += b"\x31\xc0\xc3"
        return code.build()
