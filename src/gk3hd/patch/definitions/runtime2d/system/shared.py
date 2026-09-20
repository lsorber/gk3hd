"""Shared addresses, layout constants, and invariants for system features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.x86 import REL32_INSTRUCTION_SIZE, BranchOpcode, decode_rel32_branch
from gk3hd.patch.definitions.runtime2d.layout import (
    FINGERPRINT_SEGMENT,
    LOAD_SAVE_FONT_POINT_HELPER_OFFSET,
    LOAD_SAVE_HUD_FONT_ACTIVE_OFFSET,
    LOAD_SAVE_HUD_FONT_ALPHA_TRANSFORM_COUNT_OFFSET,
    LOAD_SAVE_HUD_FONT_POINT_OFFSET,
    LOAD_SAVE_SEGMENT,
    LOAD_SAVE_TEXT_ACTIVE_OFFSET,
    RESOURCE_SEGMENT,
    SIDNEY_NATIVE_BLT_TRAMPOLINE_OFFSET,
    SYSTEM_ACTION_LAYOUT_STATE_OFFSET,
    SYSTEM_CONTROL_ACTION_LIFETIME_HELPER_OFFSET,
    SYSTEM_CONTROL_CURSOR_CLASSIFIER_OFFSET,
    SYSTEM_CONTROL_CURSOR_CLASSIFIER_TRACE_OFFSET,
    SYSTEM_CONTROL_CURSOR_STATE_OFFSET,
    SYSTEM_CONTROL_CURSOR_STATE_SIZE,
    SYSTEM_CONTROL_HD_FONT_ACTIVE_OFFSET,
    SYSTEM_CONTROL_HD_FONT_HANDLE_COUNT_OFFSET,
    SYSTEM_CONTROL_HD_FONT_HANDLES_OFFSET,
    SYSTEM_CONTROL_HD_FONT_NORMALIZE_COUNT_OFFSET,
    SYSTEM_CONTROL_HD_FONT_SOURCE_RECT_OFFSET,
    SYSTEM_CONTROL_HD_FONT_SOURCE_TRANSFORM_COUNT_OFFSET,
    SYSTEM_CONTROL_ROOM_STATUS_DAMAGE_REGION_OFFSET,
    SYSTEM_CONTROL_ROOM_STATUS_DAMAGE_VALID_OFFSET,
    SYSTEM_CONTROL_ROOM_STATUS_DEFER_COUNT_OFFSET,
    SYSTEM_CONTROL_ROOM_STATUS_DEST_HANDLE_OFFSET,
    SYSTEM_CONTROL_ROOM_STATUS_OBJECT_PTR_OFFSET,
    SYSTEM_CONTROL_ROOM_STATUS_PENDING_RECT_OFFSET,
    SYSTEM_CONTROL_ROOM_STATUS_PENDING_VALID_OFFSET,
    SYSTEM_CONTROL_ROOM_STATUS_PRESENT_COUNT_OFFSET,
    SYSTEM_CONTROL_ROOM_STATUS_PRESENT_DEPTH_OFFSET,
    SYSTEM_CONTROL_ROOM_STATUS_SEED_BUDGET_OFFSET,
    SYSTEM_CONTROL_ROOM_STATUS_SEED_REPLAY_COUNT_OFFSET,
    SYSTEM_CONTROL_SEGMENT,
    SYSTEM_CONTROL_TITLE_CACHE_DEST_RECT_OFFSET,
    SYSTEM_CONTROL_TITLE_CACHE_SOURCE_RECT_OFFSET,
    SYSTEM_CONTROL_TITLE_CACHE_TRACE_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_DRAW_COUNT_OFFSET,
    SYSTEM_CONTROL_TOOLTIP_DRAW_DEPTH_OFFSET,
    SYSTEM_DEST_RECT_OFFSET,
    SYSTEM_INPUT_ACTIVE_OFFSET,
    SYSTEM_RENDER_DEPTH_OFFSET,
    SYSTEM_ROOT_POINTER_OFFSET,
    SYSTEM_SEGMENT,
    SYSTEM_TRANSFORM_MODE_OFFSET,
)
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameABI
    from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols
    from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI


@dataclass(frozen=True, slots=True, kw_only=True)
class SystemCompilerContext:
    """Provide immutable build and runtime addresses to one feature owner."""

    symbols: RuntimeSymbols
    profile: BuildProfile
    room_rendering_abi: RoomRenderingABI
    transition_abi: TransitionFrameABI

    id: ClassVar[str] = "runtime2d.system"

    _section_name: ClassVar[str] = SYSTEM_SEGMENT.logical_name
    _section_size: ClassVar[int] = SYSTEM_SEGMENT.size
    _section_characteristics: ClassVar[int] = SYSTEM_SEGMENT.characteristics
    _magic: ClassVar[bytes] = SYSTEM_SEGMENT.magic
    _layout_version: ClassVar[int] = 213
    _off_layout_version: ClassVar[int] = 0x08
    _off_render_depth: ClassVar[int] = SYSTEM_RENDER_DEPTH_OFFSET
    _off_input_active: ClassVar[int] = SYSTEM_INPUT_ACTIVE_OFFSET
    _off_clear_pending: ClassVar[int] = 0x14
    _off_transform_count: ClassVar[int] = 0x18
    _off_root_ptr: ClassVar[int] = SYSTEM_ROOT_POINTER_OFFSET
    _off_source_rect: ClassVar[int] = 0x20
    _off_target_rect: ClassVar[int] = 0x30
    _off_dest_rect: ClassVar[int] = SYSTEM_DEST_RECT_OFFSET
    _off_bltfx: ClassVar[int] = 0x50
    _off_composite_surface: ClassVar[int] = 0xB4
    _off_left_bar_rect: ClassVar[int] = 0xC0
    _off_right_bar_rect: ClassVar[int] = 0xD0
    _off_transform_mode: ClassVar[int] = SYSTEM_TRANSFORM_MODE_OFFSET
    _off_hud_transform_count: ClassVar[int] = 0xE4
    _off_cursor_active: ClassVar[int] = 0xE8
    _off_cursor_transform_count: ClassVar[int] = 0xEC
    _off_hud_last_rect: ClassVar[int] = 0xF0
    _off_root_draw_wrapper: ClassVar[int] = 0x100
    _off_show_wrapper: ClassVar[int] = 0x180
    _off_hide_wrapper: ClassVar[int] = 0x1C0
    _off_destructor_wrapper: ClassVar[int] = 0x200
    _off_finished_root_draw_wrapper: ClassVar[int] = 0x240
    _off_finished_destructor_wrapper: ClassVar[int] = 0x2A0
    _off_blt_wrapper: ClassVar[int] = 0x300
    _off_death_button_layout: ClassVar[int] = 0x310
    _off_toolbar_blt_helper: ClassVar[int] = 0x400
    _off_pause_draw_scope: ClassVar[int] = 0x900
    _off_binocs_root_draw_wrapper: ClassVar[int] = 0xA00
    _off_binocs_show_wrapper: ClassVar[int] = 0xA80
    _off_binocs_hide_wrapper: ClassVar[int] = 0xAC0
    _off_binocs_destructor_wrapper: ClassVar[int] = 0xB00
    _off_loadgame_root_draw_wrapper: ClassVar[int] = 0xB40
    _off_loadgame_show_wrapper: ClassVar[int] = 0xBC0
    _off_loadgame_hide_wrapper: ClassVar[int] = 0xC00
    _off_loadgame_destructor_wrapper: ClassVar[int] = 0xC40
    # ActionMenu's 36-byte layout scratch fits the legacy data gap which no
    # longer contains its enlarged retained-modal destructor.
    _off_action_layout_state: ClassVar[int] = SYSTEM_ACTION_LAYOUT_STATE_OFFSET
    _off_cursor_scope_wrapper: ClassVar[int] = 0xD40
    _off_cursor_bounds_wrapper: ClassVar[int] = 0xDC0
    _off_loadsave_root_draw_wrapper: ClassVar[int] = 0xE40
    _off_loadsave_show_wrapper: ClassVar[int] = 0xEC0
    _off_loadsave_hide_wrapper: ClassVar[int] = 0xF00
    _off_loadsave_destructor_wrapper: ClassVar[int] = 0xF40

    # Less common root scopes live in a second logical payload. Each
    # class-specific vtable wrapper brackets only one recursive traversal; no
    # ordinary 3D layer enters this scope.
    _control_section_name: ClassVar[str] = SYSTEM_CONTROL_SEGMENT.logical_name
    # Keep one third page for the cursor's final-blit ownership predicate. It
    # deliberately encodes all atlas, fragment, point, and framebuffer checks
    # in executable policy instead of relying on a transient Boolean scope.
    _control_section_size: ClassVar[int] = SYSTEM_CONTROL_SEGMENT.size
    _control_magic: ClassVar[bytes] = SYSTEM_CONTROL_SEGMENT.magic
    _control_layout_version: ClassVar[int] = 229
    _off_control_layout_version: ClassVar[int] = 0x08
    # The shared final blitter accepts independent destination and source
    # rectangles.  Keep one private source RECT for transfers that cross the
    # physical framebuffer edge: cropping both rectangles by the same ratio
    # avoids DirectDraw rejecting the whole operation or squashing its bitmap.
    _off_control_clipped_source_rect: ClassVar[int] = 0x0C
    # Title's transformed children cannot repair a native cursor-sized damage
    # list reliably.  Store one vector-like region collection and its sole RECT
    # in otherwise-unused control-section data, before the first wrapper.
    _off_control_full_damage_region: ClassVar[int] = 0x20
    _off_control_full_damage_rect: ClassVar[int] = 0x30
    _off_control_hd_font_active: ClassVar[int] = SYSTEM_CONTROL_HD_FONT_ACTIVE_OFFSET
    _off_control_hd_font_handle_count: ClassVar[int] = SYSTEM_CONTROL_HD_FONT_HANDLE_COUNT_OFFSET
    _off_control_hd_font_handles: ClassVar[int] = SYSTEM_CONTROL_HD_FONT_HANDLES_OFFSET
    _off_control_hd_font_source_rect: ClassVar[int] = SYSTEM_CONTROL_HD_FONT_SOURCE_RECT_OFFSET
    _off_control_hd_font_normalize_count: ClassVar[int] = (
        SYSTEM_CONTROL_HD_FONT_NORMALIZE_COUNT_OFFSET
    )
    _off_control_hd_font_source_transform_count: ClassVar[int] = (
        SYSTEM_CONTROL_HD_FONT_SOURCE_TRANSFORM_COUNT_OFFSET
    )
    # Four large-backing records classify the toolbar's most recent panel and
    # separately layered combo-list transfers without turning the injected
    # patch into a general-purpose logger. Each record contains wrapper
    # identities, dimensions, and the incoming destination RECT. The shared
    # constants are also consumed by the capture harness.
    _off_control_dropdown_pending_ptr: ClassVar[int] = 0x170
    _off_control_dropdown_saved_root_bottom: ClassVar[int] = 0x174
    _off_control_dropdown_root_bottom_valid: ClassVar[int] = 0x178
    # Title's full-damage root wrapper is larger than the compact state
    # wrappers kept at the start of this section. Give it a dedicated tail slot.
    _off_title_root_draw_wrapper: ClassVar[int] = 0x1A00
    _off_title_root_draw_limit: ClassVar[int] = 0x1B00
    _off_title_show_wrapper: ClassVar[int] = 0x180
    _off_title_hide_wrapper: ClassVar[int] = 0x1C0
    _off_title_destructor_wrapper: ClassVar[int] = 0x200
    # CloseUp owns one cohesive page handoff (root publication, Show/Hide
    # lease, and exact destructor teardown). Repack the historically fragmented
    # 0x280..0x400 class range with explicit measured bounds; no trampoline or
    # unrelated tooltip/cache state is shared with this lifetime.
    _off_closeup_root_draw_wrapper: ClassVar[int] = 0x280
    _off_closeup_root_draw_limit: ClassVar[int] = 0x310
    _off_closeup_show_wrapper: ClassVar[int] = 0x310
    _off_closeup_hide_wrapper: ClassVar[int] = 0x330
    _off_closeup_destructor_wrapper: ClassVar[int] = 0x380
    _off_closeup_destructor_limit: ClassVar[int] = 0x400
    _off_fingerprint_root_draw_wrapper: ClassVar[int] = 0x400
    _off_fingerprint_show_wrapper: ClassVar[int] = 0x4A0
    _off_fingerprint_hide_wrapper: ClassVar[int] = 0x4E0
    _off_fingerprint_destructor_wrapper: ClassVar[int] = 0x520
    _off_fingerprint_destructor_limit: ClassVar[int] = 0x548
    # system+0x300 remains the stable internal dispatcher address used by the
    # HD patch. Its JMP resolves this private implementation address. Use the
    # free aligned gap after fingerprint teardown for the display-target guard,
    # leaving all action-layout and published data/cursor offsets untouched.
    _off_control_blt_wrapper: ClassVar[int] = 0x5C0
    # The original 4 KiB control slice is densely occupied by the shared Blt
    # dispatcher. A second page keeps class-specific layout helpers separate
    # from that stable public ABI.
    # The shared blitter owns all final-transfer classification, including the
    # exact ToolTip producer scope. Give that cohesive dispatcher the complete
    # aligned range it needs; the action helper still has ample room before its
    # independent 0x1360 class wrapper.
    _off_action_layout_helper: ClassVar[int] = 0x1180
    _off_control_action_root_draw_wrapper: ClassVar[int] = 0x1360
    # Root traversal grew when class-owned modal transforms were added. Keep
    # its complete executable policy contiguous up to cursor state; its private
    # data lives in the separate system-segment gap declared above.
    # The cursor drawable publishes its unclipped screen point and atlas frame
    # here. Concrete final-copy hooks use that origin to map every clipped
    # fragment into one continuous scaled cursor, without touching ordinary UI
    # or the cursor manager's native save-under tiles.  This is a shared
    # diagnostic ABI, not private scratch; import its range from layout.py so
    # the capture reader cannot silently drift from the emitted executable.
    _off_control_cursor_state: ClassVar[int] = SYSTEM_CONTROL_CURSOR_STATE_OFFSET
    _control_cursor_state_size: ClassVar[int] = SYSTEM_CONTROL_CURSOR_STATE_SIZE
    _off_room_status_object_ptr: ClassVar[int] = SYSTEM_CONTROL_ROOM_STATUS_OBJECT_PTR_OFFSET
    _off_room_status_dest_handle: ClassVar[int] = SYSTEM_CONTROL_ROOM_STATUS_DEST_HANDLE_OFFSET
    _off_room_status_defer_count: ClassVar[int] = SYSTEM_CONTROL_ROOM_STATUS_DEFER_COUNT_OFFSET
    _off_room_status_present_count: ClassVar[int] = SYSTEM_CONTROL_ROOM_STATUS_PRESENT_COUNT_OFFSET
    _off_room_status_present_depth: ClassVar[int] = SYSTEM_CONTROL_ROOM_STATUS_PRESENT_DEPTH_OFFSET
    _off_room_status_damage_valid: ClassVar[int] = SYSTEM_CONTROL_ROOM_STATUS_DAMAGE_VALID_OFFSET
    _off_room_status_damage_region: ClassVar[int] = SYSTEM_CONTROL_ROOM_STATUS_DAMAGE_REGION_OFFSET
    _off_room_status_pending_valid: ClassVar[int] = SYSTEM_CONTROL_ROOM_STATUS_PENDING_VALID_OFFSET
    _off_room_status_pending_rect: ClassVar[int] = SYSTEM_CONTROL_ROOM_STATUS_PENDING_RECT_OFFSET
    _off_room_status_seed_budget: ClassVar[int] = SYSTEM_CONTROL_ROOM_STATUS_SEED_BUDGET_OFFSET
    _off_room_status_seed_replay_count: ClassVar[int] = (
        SYSTEM_CONTROL_ROOM_STATUS_SEED_REPLAY_COUNT_OFFSET
    )
    _off_cursor_classifier_trace: ClassVar[int] = SYSTEM_CONTROL_CURSOR_CLASSIFIER_TRACE_OFFSET
    # CursorManager's stock 64x64 logical maximum produces 64x64/128x128 native
    # save-under and composition surfaces. Those surfaces clip a height-scaled
    # cursor at sufficiently dense modes, leaving stale pixels which are later
    # restored at the physical origin. Scale a private copy at the platform
    # allocator boundary so constructor and save-restore allocations remain
    # coherent without serializing physical dimensions as logical game state.
    _off_control_cursor_capacity_wrapper: ClassVar[int] = 0x1500
    _off_control_cursor_capacity_limit: ClassVar[int] = 0x1600
    # ConfirmQuitLayer owns a centered physical root with native child extents,
    # but is a separate modal lifetime. Keep its four class wrappers in the
    # otherwise-free page before Title's root.
    _off_confirm_quit_root_draw_wrapper: ClassVar[int] = 0x1600
    _off_confirm_quit_show_wrapper: ClassVar[int] = 0x1700
    _off_confirm_quit_hide_wrapper: ClassVar[int] = 0x1750
    _off_confirm_quit_destructor_wrapper: ClassVar[int] = 0x17A0
    _off_confirm_quit_destructor_wrapper_limit: ClassVar[int] = 0x1860
    _off_physical_backdrop_wrapper: ClassVar[int] = 0x1860
    _off_physical_backdrop_wrapper_limit: ClassVar[int] = 0x1960
    _off_console_draw_scope: ClassVar[int] = 0x1960
    _off_console_draw_scope_limit: ClassVar[int] = 0x1A00
    # TitleLayer creates a physical cache before its root Draw traversal. A
    # dense replacement bitmap and that cache coexist only at the resource
    # loader's DirectDraw call, so title presentation owns one narrow upstream
    # hook here instead of trying to infer lost source pixels at final Blt time.
    _off_title_cache_dest_rect: ClassVar[int] = SYSTEM_CONTROL_TITLE_CACHE_DEST_RECT_OFFSET
    _off_title_cache_source_rect: ClassVar[int] = SYSTEM_CONTROL_TITLE_CACHE_SOURCE_RECT_OFFSET
    _off_title_cache_trace: ClassVar[int] = SYSTEM_CONTROL_TITLE_CACHE_TRACE_OFFSET
    _off_title_cache_blt_wrapper: ClassVar[int] = 0x2240
    _off_title_cache_blt_limit: ClassVar[int] = 0x2440
    # The high-level font hook owns room HUD, Load/Save records, and SIDNEY's
    # late notification. Keep that shared policy in the control segment rather
    # than crowding the Load/Save-private page merely because that was its first
    # consumer. The next named owner at 0x2900 provides a generous hard limit.
    _off_control_font_wrapper: ClassVar[int] = 0x2440
    _off_control_font_wrapper_limit: ClassVar[int] = 0x2900
    _off_control_cursor_manager_draw_wrapper: ClassVar[int] = 0x2D00
    _off_control_cursor_manager_draw_limit: ClassVar[int] = 0x2DE0
    # ToolTip's concrete SetVisible virtual owns the delayed hidden-to-visible
    # animation callback. Observe that exact class boundary and request one
    # ordinary presentation for a fixed ActionMenu in the gap before Draw.
    _off_tooltip_visibility_wrapper: ClassVar[int] = 0x2DE0
    _off_tooltip_visibility_wrapper_limit: ClassVar[int] = 0x2E80
    # One semantic cursor-surface classifier is called by both the common
    # fixed-interface blitter and the room-toolbar helper. Keeping it in the
    # remaining control tail avoids two large inlined copies and, more
    # importantly, gives every transformed root the same ownership policy.
    _off_control_cursor_surface_classifier: ClassVar[int] = SYSTEM_CONTROL_CURSOR_CLASSIFIER_OFFSET
    _off_control_cursor_surface_classifier_limit: ClassVar[int] = 0x3F00
    # ToolTip is a global physical overlay which can draw synchronously while
    # InGameToolbar remains the active root. Its exact class wrapper publishes
    # that producer to the same proven pre-Flip owner as the other room
    # overlays. Keep producer and presenter adjacent so the ownership handoff
    # is explicit and neither has to infer a DirectDraw page.
    # The event wrapper recognizes one new visible producer before handing its
    # stable generations to the frame owner. Keep the complete wrapper in the
    # free aligned gap after cursor diagnostics.
    _off_tooltip_draw_wrapper: ClassVar[int] = 0x2E80
    _off_tooltip_draw_wrapper_limit: ClassVar[int] = 0x2EFA
    # Retained tooltip composition owns a complete visibility/damage state
    # machine.  Keep it in the unused final control page instead of forcing
    # that policy into the historical diagnostic gap below 0x3000.  The
    # explicit limit is intentionally generous so future instruction changes
    # fail locally without encroaching on an unrelated helper.
    _off_tooltip_frame_presenter: ClassVar[int] = 0x4300
    _off_tooltip_frame_presenter_limit: ClassVar[int] = 0x4800
    # Cached tooltip-panel creation and presentation needs more than the old
    # color-fill helper's tiny slot. Keep it after the complete retained state
    # block in the final control page, with an explicit boundary before EOF.
    _off_tooltip_background_helper: ClassVar[int] = 0x4A00
    _off_tooltip_background_helper_limit: ClassVar[int] = 0x4F00
    # CloseUp replays its retained tree for two pages. ConfirmQuit's backdrop
    # is not part of that tree, so its adjacent wrapper performs one safe
    # front-to-returned-back copy immediately after the first successful Flip.
    _off_closeup_frame_presenter: ClassVar[int] = 0x4134
    _off_closeup_frame_presenter_limit: ClassVar[int] = 0x4200
    _off_confirm_quit_post_flip_presenter: ClassVar[int] = 0x4200
    _off_confirm_quit_post_flip_presenter_limit: ClassVar[int] = 0x4300
    # CursorManager's room-loop update precedes retained-page selection. Keep
    # the exact resource-transition invalidator in the otherwise-free tail.
    _off_control_cursor_resource_rebuild_wrapper: ClassVar[int] = 0x5100
    _off_control_cursor_resource_rebuild_limit: ClassVar[int] = 0x5300
    _off_confirm_quit_room_repair_helper: ClassVar[int] = 0x5300
    _off_confirm_quit_room_repair_helper_limit: ClassVar[int] = 0x5400
    _off_confirm_quit_show_prepare_helper: ClassVar[int] = 0x5400
    _off_confirm_quit_show_prepare_helper_limit: ClassVar[int] = 0x5500
    # Both room-modal destructors release the retained composition and tooltip
    # surfaces as one lifetime transaction. Keep that complete policy in
    # dedicated tail slots instead of compressing it into historical gaps near
    # unrelated early wrappers. This also leaves future COM teardown changes
    # subject to explicit, independently validated code-size limits.
    _off_ingame_toolbar_destructor_wrapper: ClassVar[int] = 0x5660
    _off_toolbar_preview_surface: ClassVar[int] = 0x5500
    _off_toolbar_preview_prepare: ClassVar[int] = 0x5520
    _off_toolbar_preview_prepare_limit: ClassVar[int] = 0x55B0
    _off_toolbar_cursor_warp: ClassVar[int] = 0x55B0
    _off_ingame_toolbar_destructor_wrapper_limit: ClassVar[int] = 0x5700
    _off_control_action_destructor_wrapper: ClassVar[int] = 0x5700
    _off_control_action_destructor_wrapper_limit: ClassVar[int] = 0x5800
    _off_confirm_quit_cursor_resume_helper: ClassVar[int] = 0x5800
    _off_confirm_quit_cursor_resume_helper_limit: ClassVar[int] = 0x5900
    _off_confirm_quit_cursor_suspend_helper: ClassVar[int] = 0x5900
    _off_confirm_quit_cursor_suspend_helper_limit: ClassVar[int] = 0x5B00
    # MouseManager's stock tooltip search omits transient room-child modals.
    # Resolve an ActionMenu in its published physical geometry or an
    # InGameToolbar through its immutable input affine, then tail-enter the
    # stock resolver for every miss and unrelated lifetime. This is interaction
    # policy, not presentation policy, so it remains outside the draw wrappers.
    _off_modal_tooltip_resolver_wrapper: ClassVar[int] = 0x5E00
    # The 82-byte fixed-layer epilogue leaves a bounded tail for the toolbar's
    # 132-byte layout commit; neither needs another runtime segment.
    _off_toolbar_layout: ClassVar[int] = 0x5D60
    _off_modal_tooltip_resolver_wrapper_limit: ClassVar[int] = 0x6000
    # The native ActionMenu destructor can trail a successful action callback.
    # Validate current-layer membership at the render-thread ownership edge so
    # neither fixed-modal tooltip policy nor staged modal caches survive into
    # the replacement layer merely because the old allocation still exists.
    _off_action_lifetime_helper: ClassVar[int] = SYSTEM_CONTROL_ACTION_LIFETIME_HELPER_OFFSET
    _off_action_lifetime_helper_limit: ClassVar[int] = 0x5D00
    # A delayed ToolTip edge is published by the fixed layer's UI update after
    # its normal render pair. The first non-reentrant owner is therefore that
    # layer's epilogue: consume one explicit token there and render both
    # rotating DirectDraw pages once. No message-pump or hot render-loop hook
    # is needed.
    _off_tooltip_fixed_layer_epilogue_wrapper: ClassVar[int] = 0x5D00
    _off_tooltip_fixed_layer_epilogue_wrapper_limit: ClassVar[int] = 0x5D60
    _off_tooltip_transfer_affine: ClassVar[int] = 0x4000
    _off_tooltip_transfer_affine_limit: ClassVar[int] = 0x4100
    # ToolTip's native backing and border calls remain correct at the authored
    # height. Two tiny call-compatible gates suppress only those decorations
    # while the staged modern compositor owns the scaled panel.
    # Cursor publication and the two compact tooltip gates share one named
    # executable interval. The cursor owner has the complete range through
    # +0x2CB0; the two map-aware tail gates then occupy independently bounded
    # slots before CursorManager. Their conditional branch is deliberately
    # short, so this layout is measured rather than dependent on padding.
    _off_tooltip_base_decoration_wrapper: ClassVar[int] = 0x2CB0
    _off_tooltip_base_decoration_wrapper_limit: ClassVar[int] = 0x2CD8
    _off_tooltip_border_decoration_wrapper: ClassVar[int] = 0x2CD8
    _off_tooltip_border_decoration_wrapper_limit: ClassVar[int] = 0x2D00
    _off_tooltip_draw_depth: ClassVar[int] = SYSTEM_CONTROL_TOOLTIP_DRAW_DEPTH_OFFSET
    _off_tooltip_draw_count: ClassVar[int] = SYSTEM_CONTROL_TOOLTIP_DRAW_COUNT_OFFSET
    _tooltip_base_site_name: ClassVar[str] = "tooltip.base_draw_call"
    _tooltip_border_site_names: ClassVar[tuple[str, ...]] = (
        "tooltip.border_top_call",
        "tooltip.border_left_call",
        "tooltip.border_right_call",
        "tooltip.border_bottom_call",
    )
    _action_tooltip_resolve_site_names: ClassVar[tuple[str, ...]] = (
        "tooltip.action_resolve_idle_call",
        "tooltip.action_resolve_event_call",
        "tooltip.action_resolve_activation_call",
    )
    _tooltip_fixed_layer_epilogue_site_name: ClassVar[str] = "tooltip.fixed_layer_epilogue"
    # Load/Save needs a full-damage traversal while the in-room toolbar must
    # leave the widescreen room alone. Keep those distinct policies in named
    # tail slots instead of coupling them merely because the native classes
    # happen to share one stock Draw implementation.
    _off_control_loadsave_root_draw_wrapper: ClassVar[int] = 0x1B00
    _off_control_ingame_toolbar_draw_wrapper: ClassVar[int] = 0x1C00
    _off_resolution_dropdown_draw_wrapper: ClassVar[int] = 0x1D00
    # The popup visibility owner also leases the toolbar root extent. Give that
    # cohesive lifecycle transaction the remainder of this local code page;
    # the unrelated generic damage recorder lives after its own state ABI.
    _off_resolution_dropdown_visibility_wrapper: ClassVar[int] = 0x1D40
    _off_resolution_dropdown_visibility_limit: ClassVar[int] = 0x1E00
    _off_resolution_dropdown_fit_helper: ClassVar[int] = 0x1E00
    # The native Flip patch exposes one callback slot. Keep the linked room
    # cursor presenter in its own control-tail range before the popup helper.
    _off_control_cursor_frame_presenter: ClassVar[int] = 0x1F40
    _off_control_cursor_frame_presenter_limit: ClassVar[int] = 0x2240
    # The damage-aware frame presenter outgrew the formerly adjacent dropdown
    # slot. The runtime is pre-1.0, so give each owner a complete page rather
    # than compressing either policy into an unsafe instruction budget.
    _off_resolution_dropdown_highlight_wrapper: ClassVar[int] = 0x3000
    _off_resolution_dropdown_highlight_limit: ClassVar[int] = 0x3200
    # Dropdown composition gained a two-page seed policy. Keep that complete
    # owner in the otherwise-free aligned slot instead of squeezing executable
    # logic into the gap between two unrelated helpers.
    _off_resolution_dropdown_present_helper: ClassVar[int] = 0x3200
    _off_resolution_dropdown_present_limit: ClassVar[int] = 0x3300
    # Cursor preparation owns complete drawable geometry. Keep it in the free
    # control tail beyond the dropdown/toolbar helpers; cursor clipping now
    # legitimately consumes the old adjacent slot in the final compositor.
    _off_control_cursor_prep_wrapper: ClassVar[int] = 0x3300
    _off_control_cursor_prep_limit: ClassVar[int] = 0x3400
    # Retained room HUD is a distinct overlay owner from both toolbar and
    # cursor. Its exact TextBox wrapper publishes the transaction, while the
    # presenter performs its sole native Draw on the current back page.
    _off_room_text_draw_wrapper: ClassVar[int] = 0x3400
    _off_room_text_draw_wrapper_limit: ClassVar[int] = 0x3560
    _off_control_font_metrics_wrapper: ClassVar[int] = 0x3560
    _off_control_font_metrics_wrapper_limit: ClassVar[int] = 0x37C0
    # TextBox's native Draw paints its translucent backing before submitting
    # glyphs. The room-status presenter scales the glyph transaction, so keep
    # the backing affine in the same class-owned scope rather than recognizing
    # generic solid fills by coordinates or colour.
    _off_room_status_fill_wrapper: ClassVar[int] = 0x37C0
    _off_room_status_fill_wrapper_limit: ClassVar[int] = 0x3880
    _off_control_loadsave_text_draw_wrapper: ClassVar[int] = 0x3880
    _off_control_loadsave_text_draw_wrapper_limit: ClassVar[int] = 0x3900
    _off_resolution_dropdown_fit_limit: ClassVar[int] = 0x1EC0
    # The final cursor compositor carries complete ownership and clipping
    # proofs. Keep it in the otherwise-unused tail page rather than crowding
    # the earlier fixed-interface helpers.
    _off_control_cursor_final_wrapper: ClassVar[int] = 0x2900
    _off_control_cursor_final_limit: ClassVar[int] = 0x2CB0
    _loadsave_section_name: ClassVar[str] = LOAD_SAVE_SEGMENT.logical_name
    _loadsave_section_size: ClassVar[int] = LOAD_SAVE_SEGMENT.size
    _loadsave_magic: ClassVar[bytes] = LOAD_SAVE_SEGMENT.magic
    _loadsave_layout_version: ClassVar[int] = 101
    _off_loadsave_preview_attach: ClassVar[int] = 0xB50
    _off_loadsave_layout_root: ClassVar[int] = 0x0C
    _off_loadsave_scroll_raw_top: ClassVar[int] = 0x14
    _off_loadsave_scroll_origin_seen: ClassVar[int] = 0x18
    _off_loadsave_layout_wrapper: ClassVar[int] = 0x100
    _off_loadsave_rect_transform: ClassVar[int] = 0x300
    _off_hud_font_active: ClassVar[int] = LOAD_SAVE_HUD_FONT_ACTIVE_OFFSET
    _off_hud_font_transform_count: ClassVar[int] = 0x24
    _off_hud_font_last_point: ClassVar[int] = LOAD_SAVE_HUD_FONT_POINT_OFFSET
    _off_hud_font_alpha_transform_count: ClassVar[int] = (
        LOAD_SAVE_HUD_FONT_ALPHA_TRANSFORM_COUNT_OFFSET
    )
    # Last successful save-record glyph rewrite.  Keeping the incoming and
    # outgoing points in the runtime image makes resolution regressions
    # diagnosable without timing-sensitive debugger attachment.
    _off_loadsave_record_font_count: ClassVar[int] = 0x30
    _off_loadsave_record_font_input: ClassVar[int] = 0x34
    _off_loadsave_record_font_output: ClassVar[int] = 0x44
    _off_loadsave_record_text_active: ClassVar[int] = LOAD_SAVE_TEXT_ACTIVE_OFFSET
    # Load/Save's transformed object tree cannot consume GK3's authored-space
    # dirty regions safely. These fields retain page-copy and complete-damage
    # telemetry for runtime verification.
    _off_loadsave_full_damage_count: ClassVar[int] = 0x6C
    _off_loadsave_native_damage_ptr: ClassVar[int] = 0x74
    _off_loadsave_native_damage_count: ClassVar[int] = 0x78
    _off_loadsave_native_damage_rects: ClassVar[int] = 0x7C
    # Load/Save merges native dirty rectangles into one canonical off-screen
    # composition, then replays it to the concrete page selected by Flip.
    _off_loadsave_destination_handle: ClassVar[int] = 0xE00
    _off_loadsave_frame_present_count: ClassVar[int] = 0xE04
    _off_loadsave_cache_surface: ClassVar[int] = 0xE08
    _off_loadsave_cache_owner: ClassVar[int] = 0xE0C
    _off_loadsave_cache_ready: ClassVar[int] = 0xE10
    _off_loadsave_cache_create_result: ClassVar[int] = 0xE14
    _off_loadsave_cache_capture_result: ClassVar[int] = 0xE18
    _off_loadsave_cache_present_result: ClassVar[int] = 0xE1C
    _off_loadsave_cache_capture_count: ClassVar[int] = 0xE20
    _off_loadsave_cache_present_count: ClassVar[int] = 0xE24
    _off_loadsave_cache_source_rect: ClassVar[int] = 0xE28
    _off_loadsave_cache_scratch_rect: ClassVar[int] = 0xE38
    _off_loadsave_cache_descriptor: ClassVar[int] = 0xE48
    _off_loadsave_page_clear_result: ClassVar[int] = 0xEC4
    _off_loadsave_page_clear_count: ClassVar[int] = 0xEC8
    _off_loadsave_cache_update_helper: ClassVar[int] = 0xF00
    _off_loadsave_frame_presenter: ClassVar[int] = 0x1400
    # Load/Save redraws can cover the software cursor without scheduling a new
    # input event. Re-submit the live CursorManager only after cache capture,
    # so the canonical retained canvas remains cursor-free.
    _off_loadsave_post_draw_cursor_presenter: ClassVar[int] = 0x1600
    _off_loadsave_post_draw_cursor_presenter_limit: ClassVar[int] = 0x1800
    # RestoreProgressController attaches its background once during concrete
    # construction. Keep the model-geometry wrapper beside the retained
    # Load/Save presenters whose later draws consume that rectangle.
    _off_restore_progress_background_attach_wrapper: ClassVar[int] = 0x1800
    _off_restore_progress_background_attach_wrapper_limit: ClassVar[int] = 0x1900
    _off_restore_progress_initial_show_wrapper: ClassVar[int] = 0x1900
    _off_restore_progress_initial_show_wrapper_limit: ClassVar[int] = 0x1A00
    _off_restore_progress_canvas_update_wrapper: ClassVar[int] = 0x1A00
    _off_restore_progress_canvas_update_wrapper_limit: ClassVar[int] = 0x1B00
    _off_loadsave_page_clear_helper: ClassVar[int] = 0x1B00
    _off_loadsave_page_clear_helper_limit: ClassVar[int] = 0x1B80
    # Captured thumb motion bypasses the root's authored-point traversal.
    _off_loadsave_scroll_thumb_move_stub: ClassVar[int] = 0x1B80
    _off_loadsave_scroll_thumb_move_limit: ClassVar[int] = 0x1C00
    # Load/Save publishes the outer ScrollBar in framebuffer coordinates but
    # leaves its nested 22-pixel arrow/thumb/track model untouched. Two ABI-
    # specific adapters and compact vtable stubs map the POINT only after the
    # outer component has won native root hit-testing.
    _off_loadsave_scroll_input_1: ClassVar[int] = 0x1C00
    _off_loadsave_scroll_input_3: ClassVar[int] = 0x1D00
    _off_loadsave_scroll_input_stubs: ClassVar[int] = 0x1E00
    _loadsave_scroll_input_stub_stride: ClassVar[int] = 0x10
    _off_loadsave_scroll_arrow_left_down_stub: ClassVar[int] = 0x1E90
    _off_loadsave_scroll_arrow_release_stub: ClassVar[int] = 0x1EA0
    _off_loadsave_scroll_arrow_release_dispatch: ClassVar[int] = 0x1ED0
    _off_loadsave_scroll_input_mapped_point: ClassVar[int] = 0x1F28
    _off_loadsave_scroll_input_depth: ClassVar[int] = 0x1F30
    _off_loadsave_scroll_hit_test: ClassVar[int] = 0x1F40
    _off_loadsave_scroll_arrow_input: ClassVar[int] = 0x1F60
    _off_loadsave_scroll_input_tail_limit: ClassVar[int] = 0x2000
    # Construction preserves canonical dynamic child geometry before native
    # selection updates overwrite it. The preview trace retains RECT + source
    # width/height + count; the selection counter records root-level repairs.
    # This data-only gap follows the RECT transformer and precedes helpers.
    _off_loadsave_preview_rect: ClassVar[int] = 0x400
    _off_loadsave_selection_rects: ClassVar[int] = 0x410
    _off_loadsave_preview_trace: ClassVar[int] = 0x440
    _off_loadsave_selection_repair_count: ClassVar[int] = 0x460
    _off_loadsave_selection_repair_pending: ClassVar[int] = 0x464
    _off_loadsave_dynamic_state_end: ClassVar[int] = 0x480
    _off_loadsave_initial_preview_transform: ClassVar[int] = 0x480
    _off_loadsave_damage_selector: ClassVar[int] = 0x500
    # Dynamic preview and selection-row redraws arrive in root-relative authored
    # coordinates. The preceding selector has ample slack, so this slot grows
    # backwards while the tightly packed, proven font slots remain fixed.
    _off_loadsave_background_helper: ClassVar[int] = 0x680
    _off_loadsave_font_rect_helper: ClassVar[int] = LOAD_SAVE_FONT_POINT_HELPER_OFFSET

    _hd_wrapper_offset: ClassVar[int] = 0x100
    _sidney_native_blt_trampoline_offset: ClassVar[int] = SIDNEY_NATIVE_BLT_TRAMPOLINE_OFFSET
    _sidney_active_depth_offset: ClassVar[int] = 0x0C
    _sidney_root_ptr_offset: ClassVar[int] = 0x120
    _fingerprint_layout_prepare_offset: ClassVar[int] = 0xA00
    _fingerprint_layout_restore_offset: ClassVar[int] = 0xC00

    # FUN_00499722 uses a second copy of the same call when a cursor sprite is
    # split across GK3's clip-region list.  Both paths carry the identical
    # five-argument thiscall contract and must share the same cursor scope;
    # otherwise clipped draws are mistaken for ordinary reference-canvas UI
    # and leave a transformed second cursor behind.

    # Class ownership was recovered from the engine's runtime type registry:
    # TitleLayer -> constructor 0x00523EC3 / vtable 0x0069238C;
    # CloseUpLayer -> vtable 0x00674798; FingerprintLayer -> constructor
    # 0x0048E035 / vtable 0x00678264.  Hooking these concrete slots avoids the
    # generic container Draw method shared by almost every 2D and 3D overlay.

    def _slot(self, owner: str, offset: int = 0) -> int:
        return self.profile.address(f"{owner}.vtable") + offset

    def _site_va(self, name: str) -> int:
        return self.profile.site(name).va

    def _site_bytes(self, name: str) -> bytes:
        return self.profile.site(name).original

    @property
    def _physical_width_va(self) -> int:
        return self.profile.address("display.dimensions")

    @property
    def _death_destructor_slot_va(self) -> int:
        return self._slot("death")

    @property
    def _death_draw_slot_va(self) -> int:
        return self._slot("death", 0xA0)

    @property
    def _death_show_slot_va(self) -> int:
        return self._slot("death", 0xD8)

    @property
    def _death_hide_slot_va(self) -> int:
        return self._slot("death", 0xDC)

    @property
    def _finished_destructor_slot_va(self) -> int:
        return self._slot("finished")

    @property
    def _finished_draw_slot_va(self) -> int:
        return self._slot("finished", 0xA0)

    @property
    def _binocs_destructor_slot_va(self) -> int:
        return self._slot("binocular")

    @property
    def _binocs_draw_slot_va(self) -> int:
        return self._slot("binocular", 0xA0)

    @property
    def _binocs_show_slot_va(self) -> int:
        return self._slot("binocular", 0xD8)

    @property
    def _binocs_hide_slot_va(self) -> int:
        return self._slot("binocular", 0xDC)

    @property
    def _loadgame_destructor_slot_va(self) -> int:
        return self._slot("loadgame")

    @property
    def _loadgame_draw_slot_va(self) -> int:
        return self._slot("loadgame", 0xA0)

    @property
    def _loadgame_show_slot_va(self) -> int:
        return self._slot("loadgame", 0xD8)

    @property
    def _loadgame_hide_slot_va(self) -> int:
        return self._slot("loadgame", 0xDC)

    @property
    def _ingame_toolbar_destructor_slot_va(self) -> int:
        return self._slot("ingame_toolbar")

    @property
    def _ingame_toolbar_draw_slot_va(self) -> int:
        return self._slot("ingame_toolbar", 0xA0)

    @property
    def _tooltip_draw_slot_va(self) -> int:
        return self._slot("tooltip", 0xA0)

    @property
    def _tooltip_visibility_slot_va(self) -> int:
        return self._slot("tooltip", 0xB0)

    @property
    def _resolution_dropdown_draw_slot_va(self) -> int:
        return self._slot("resolution_dropdown", 0xA0)

    @property
    def _resolution_dropdown_visibility_slot_va(self) -> int:
        return self._slot("resolution_dropdown", 0xB0)

    @property
    def _solid_color_draw_slot_va(self) -> int:
        return self._slot("solid_color", 0xA0)

    @property
    def _room_text_draw_slot_va(self) -> int:
        """Return the shared TextBox Draw slot used by the room-status owner."""
        return self._slot("room_text", 0xA0)

    @property
    def _action_destructor_slot_va(self) -> int:
        return self._slot("action_menu")

    @property
    def _action_draw_slot_va(self) -> int:
        return self._slot("action_menu", 0xA0)

    @property
    def _savegame_destructor_slot_va(self) -> int:
        return self._slot("savegame")

    @property
    def _savegame_draw_slot_va(self) -> int:
        return self._slot("savegame", 0xA0)

    @property
    def _savegame_show_slot_va(self) -> int:
        return self._slot("savegame", 0xD8)

    @property
    def _savegame_hide_slot_va(self) -> int:
        return self._slot("savegame", 0xDC)

    @property
    def _loadgame_layout_slot_va(self) -> int:
        return self._slot("loadgame", 0x30)

    @property
    def _savegame_layout_slot_va(self) -> int:
        return self._slot("savegame", 0x30)

    @property
    def _title_destructor_slot_va(self) -> int:
        return self._slot("title")

    @property
    def _title_draw_slot_va(self) -> int:
        return self._slot("title", 0xA0)

    @property
    def _title_show_slot_va(self) -> int:
        return self._slot("title", 0xD8)

    @property
    def _title_hide_slot_va(self) -> int:
        return self._slot("title", 0xDC)

    @property
    def _confirm_quit_destructor_slot_va(self) -> int:
        return self._slot("confirm_quit")

    @property
    def _confirm_quit_draw_slot_va(self) -> int:
        return self._slot("confirm_quit", 0xA0)

    @property
    def _confirm_quit_show_slot_va(self) -> int:
        return self._slot("confirm_quit", 0xD8)

    @property
    def _confirm_quit_hide_slot_va(self) -> int:
        return self._slot("confirm_quit", 0xDC)

    @property
    def _closeup_destructor_slot_va(self) -> int:
        return self._slot("closeup")

    @property
    def _closeup_draw_slot_va(self) -> int:
        return self._slot("closeup", 0xA0)

    @property
    def _closeup_show_slot_va(self) -> int:
        return self._slot("closeup", 0xD8)

    @property
    def _closeup_hide_slot_va(self) -> int:
        return self._slot("closeup", 0xDC)

    @property
    def _fingerprint_destructor_slot_va(self) -> int:
        return self._slot("fingerprint")

    @property
    def _fingerprint_draw_slot_va(self) -> int:
        return self._slot("fingerprint", 0xA0)

    @property
    def _fingerprint_show_slot_va(self) -> int:
        return self._slot("fingerprint", 0xD8)

    @property
    def _fingerprint_hide_slot_va(self) -> int:
        return self._slot("fingerprint", 0xDC)

    @property
    def _native_destructor_va(self) -> int:
        return self.profile.address("ui.destructor")

    @property
    def _native_draw_va(self) -> int:
        return self.profile.address("ui.container_draw")

    @property
    def _native_show_va(self) -> int:
        return self.profile.address("ui.show")

    @property
    def _native_hide_va(self) -> int:
        return self.profile.address("ui.hide")

    @property
    def _native_finished_destructor_va(self) -> int:
        return self.profile.address("finished.destructor")

    @property
    def _native_binocs_destructor_va(self) -> int:
        return self.profile.address("binocular.destructor")

    @property
    def _native_binocs_draw_va(self) -> int:
        return self.profile.address("binocular.draw")

    @property
    def _native_loadgame_destructor_va(self) -> int:
        return self.profile.address("loadgame.destructor")

    @property
    def _native_ingame_toolbar_destructor_va(self) -> int:
        return self.profile.address("ingame_toolbar.destructor")

    @property
    def _native_tooltip_draw_va(self) -> int:
        return self.profile.address("tooltip.draw")

    @property
    def _native_tooltip_visibility_va(self) -> int:
        return self.profile.address("tooltip.set_visible")

    @property
    def _native_resolution_dropdown_draw_va(self) -> int:
        return self.profile.address("resolution_dropdown.draw")

    @property
    def _native_resolution_dropdown_visibility_va(self) -> int:
        return self.profile.address("resolution_dropdown.set_visible")

    @property
    def _native_solid_color_draw_va(self) -> int:
        return self.profile.address("solid_color.draw")

    @property
    def _native_action_destructor_va(self) -> int:
        return self.profile.address("action_menu.destructor")

    @property
    def _native_loadsave_layout_va(self) -> int:
        return self.profile.address("loadsave.layout")

    @property
    def _native_savegame_destructor_va(self) -> int:
        return self.profile.address("savegame.destructor")

    @property
    def _native_title_destructor_va(self) -> int:
        return self.profile.address("title.destructor")

    @property
    def _native_title_draw_va(self) -> int:
        return self.profile.address("title.draw")

    @property
    def _native_confirm_quit_destructor_va(self) -> int:
        return self.profile.address("confirm_quit.destructor")

    @property
    def _title_cache_blt_call_va(self) -> int:
        return self._site_va("resource.cache_blt_call")

    @property
    def _title_cache_blt_original(self) -> bytes:
        return self._site_bytes("resource.cache_blt_call")

    @property
    def _title_cache_blt_continue_va(self) -> int:
        return self.profile.address("resource.cache_blt_continue")

    @property
    def _native_closeup_destructor_va(self) -> int:
        return self.profile.address("closeup.destructor")

    @property
    def _native_fingerprint_destructor_va(self) -> int:
        return self.profile.address("fingerprint.destructor")

    @property
    def _cursor_platform_initialize_call_site_va(self) -> int:
        return self._site_va("cursor.platform_initialize_call")

    @property
    def _cursor_platform_initialize_call_original(self) -> bytes:
        return self._site_bytes("cursor.platform_initialize_call")

    @property
    def _cursor_platform_restore_call_site_va(self) -> int:
        return self._site_va("cursor.platform_restore_call")

    @property
    def _cursor_platform_restore_call_original(self) -> bytes:
        return self._site_bytes("cursor.platform_restore_call")

    @property
    def _cursor_platform_initialize_va(self) -> int:
        return self.profile.address("cursor.platform_initialize")

    @property
    def _cursor_drawable_blt_call_site_va(self) -> int:
        return self._site_va("cursor.drawable_blt_call")

    @property
    def _cursor_drawable_blt_call_original(self) -> bytes:
        return self._site_bytes("cursor.drawable_blt_call")

    @property
    def _cursor_drawable_blt_va(self) -> int:
        return self.profile.address("cursor.drawable_blt")

    @property
    def _cursor_resolved_blt_call_site_va(self) -> int:
        return self._site_va("cursor.resolved_blt_call")

    @property
    def _cursor_resolved_blt_call_original(self) -> bytes:
        return self._site_bytes("cursor.resolved_blt_call")

    @property
    def _cursor_manager_draw_slot_va(self) -> int:
        """Return CursorManager's complete Draw-transaction vtable slot."""
        return self._site_va("cursor.manager_draw_slot")

    @property
    def _cursor_manager_draw_slot_original(self) -> bytes:
        """Return the pristine CursorManager Draw pointer."""
        return self._site_bytes("cursor.manager_draw_slot")

    @property
    def _restore_progress_background_attach_call_va(self) -> int:
        """Return the controller's exact background-attachment call site."""
        return self._site_va("restore_progress.background_attach_call")

    @property
    def _restore_progress_background_attach_call_original(self) -> bytes:
        """Return the pristine background-attachment call instruction."""
        return self._site_bytes("restore_progress.background_attach_call")

    @property
    def _native_restore_progress_background_attach_va(self) -> int:
        """Return GK3's native resource-to-UI attachment routine."""
        return self.profile.address("restore_progress.background_attach")

    @property
    def _restore_progress_initial_show_call_va(self) -> int:
        """Return the constructor's exact first-presentation call site."""
        return self._site_va("restore_progress.initial_show_call")

    @property
    def _restore_progress_initial_show_call_original(self) -> bytes:
        """Return the pristine indirect first-presentation sequence."""
        return self._site_bytes("restore_progress.initial_show_call")

    @property
    def _restore_progress_canvas_update_call_va(self) -> int:
        """Return the controller's exact later-presentation call site."""
        return self._site_va("restore_progress.canvas_update_call")

    @property
    def _restore_progress_canvas_update_call_original(self) -> bytes:
        """Return the pristine progress-canvas Update call."""
        return self._site_bytes("restore_progress.canvas_update_call")

    @property
    def _native_mid_blt_va(self) -> int:
        """Return GK3's final point/RECT BltFast implementation."""
        return self.profile.address("runtime2d.final_fast_blt")

    @property
    def _native_final_stretch_blt_va(self) -> int:
        """Return GK3's final RECT/RECT stretch implementation."""
        return self.profile.address("runtime2d.final_stretch_blt")

    @property
    def _cursor_bounds_hook_site_va(self) -> int:
        return self._site_va("cursor.bounds_hook")

    @property
    def _cursor_bounds_hook_original(self) -> bytes:
        return self._site_bytes("cursor.bounds_hook")

    @property
    def _cursor_bounds_hook_back_va(self) -> int:
        return self.profile.address("cursor.bounds_continue")

    @property
    def _cursor_frame_begin_call_site_va(self) -> int:
        return self._site_va("cursor.frame_begin_call")

    @property
    def _cursor_frame_begin_call_original(self) -> bytes:
        return self._site_bytes("cursor.frame_begin_call")

    @property
    def _font_blt_call_site_va(self) -> int:
        return self._site_va("font.clipped_blt_call")

    @property
    def _font_blt_call_original(self) -> bytes:
        return self._site_bytes("font.clipped_blt_call")

    @property
    def _font_metrics_site_va(self) -> int:
        return self._site_va("font.initialize_metrics")

    @property
    def _font_metrics_original(self) -> bytes:
        return self._site_bytes("font.initialize_metrics")

    @property
    def _font_metrics_continue_va(self) -> int:
        return self._font_metrics_site_va + len(self._font_metrics_original)

    @property
    def _room_text_fill_call_site_va(self) -> int:
        return self._site_va("room_text.fill_call")

    @property
    def _room_text_fill_call_original(self) -> bytes:
        return self._site_bytes("room_text.fill_call")

    @property
    def _cursor_draw_scope_site_va(self) -> int:
        return self._site_va("cursor.draw_call_scope")

    @property
    def _cursor_draw_scope_original(self) -> bytes:
        return self._site_bytes("cursor.draw_call_scope")

    @property
    def _cursor_draw_scope_continue_va(self) -> int:
        return self.profile.address("cursor.draw_call_continue")

    @property
    def _font_blt_target_va(self) -> int:
        return self.profile.address("runtime2d.clipped_blt")

    @property
    def _resolve_bitmap_resource_va(self) -> int:
        return self.profile.address("bitmap.resolve_resource")

    _mode_composite: ClassVar[int] = 1
    _mode_popup: ClassVar[int] = 2
    _mode_loadsave: ClassVar[int] = 3
    _mode_loadsave_layout: ClassVar[int] = 4
    # Title controls already receive physical anchor positions from GK3, but
    # retain native extents. Reference-canvas controls retain both authored
    # anchors and extents. CloseUp is a third, genuinely hybrid domain: its X
    # coordinates remain authored while GK3 bottom-anchors Y to the live mode.
    # Keeping those ownership domains explicit avoids heuristic per-control
    # corrections in the shared blitter.
    _mode_reference_anchor: ClassVar[int] = 5
    _mode_reference_canvas: ClassVar[int] = 6
    _mode_reference_canvas_all: ClassVar[int] = 7
    # A few class-specific helpers issue final blits with coordinates they have
    # already mapped themselves. Selecting this named pass-through mode keeps
    # the shared dispatcher from applying a second affine. Inventory uses it
    # only for the post-alpha scratch-to-output transfer; its persistent object
    # and hit rectangles deliberately remain in authored 1024x768 space.
    _mode_physical_canvas: ClassVar[int] = 8
    _mode_bottom_anchored_reference_canvas: ClassVar[int] = 9
    # A centered modal root whose complete child tree remains in one native
    # local canvas. Unlike the general popup mode, every transfer belongs to
    # this affine; Load/Save's background/cover classifier must not intervene.
    _mode_local_root_canvas: ClassVar[int] = 10

    _ddbltfx_size: ClassVar[int] = 0x64
    _ddblt_wait: ClassVar[int] = 0x01000000
    _ddblt_colorfill_wait: ClassVar[int] = 0x01000400
    _ddsd_size: ClassVar[int] = 0x6C
    _ddsd_caps_height_width: ClassVar[int] = 0x00000007
    _tooltip_panel_caps: ClassVar[int] = 0x00000040  # DDSCAPS_OFFSCREENPLAIN
    # GK3's software-cursor atlas has this authored extent. Other compositors
    # use the constant only where exact source identity is not yet available.
    _cursor_atlas_size: ClassVar[int] = 128

    def _hd_wrapper_va(self) -> int:
        return self.symbols.va(RESOURCE_SEGMENT.logical_name, self._hd_wrapper_offset)

    def _fingerprint_layout_targets(self) -> tuple[int, int]:
        """Return the draw-only fingerprint layout hooks in the current ABI."""
        section_va = self.symbols.va(FINGERPRINT_SEGMENT.logical_name)
        return (
            section_va + self._fingerprint_layout_prepare_offset,
            section_va + self._fingerprint_layout_restore_offset,
        )

    @staticmethod
    def _hook_target(site_va: int, payload: bytes) -> int | None:
        if len(payload) != REL32_INSTRUCTION_SIZE:
            return None
        try:
            opcode = BranchOpcode(payload[0])
        except ValueError:
            return None
        return decode_rel32_branch(opcode=opcode, site_va=site_va, instruction=payload)

    def _original_call_target(self, name: str) -> int:
        """Decode one profiled pristine CALL or fail before emitting policy."""
        target = self._hook_target(self._site_va(name), self._site_bytes(name))
        if target is None:
            msg = f"{self.id} profile site {name!r} is not a five-byte branch"
            raise PatchError(msg)
        return target
