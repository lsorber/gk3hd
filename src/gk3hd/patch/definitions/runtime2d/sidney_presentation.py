"""Compile fitted SIDNEY presentation and inverse input handling."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import REL32_INSTRUCTION_SIZE, BranchOpcode, decode_rel32_branch
from gk3hd.patch.definitions.runtime2d.geometry import AUTHORED_FRAME_HEIGHT, AUTHORED_FRAME_WIDTH
from gk3hd.patch.definitions.runtime2d.layout import (
    BINOCULAR_INPUT_HELPER_OFFSET,
    BINOCULAR_SEGMENT,
    INVENTORY_ACTIVE_ROOT_OFFSET,
    INVENTORY_ALPHA_CONSTRUCTOR_OFFSET,
    INVENTORY_SEGMENT,
    LOAD_SAVE_FONT_POINT_HELPER_OFFSET,
    LOAD_SAVE_HUD_FONT_ACTIVE_OFFSET,
    LOAD_SAVE_SEGMENT,
    LOAD_SAVE_TEXT_ACTIVE_OFFSET,
    RESOURCE_DRIVING_MAP_INPUT_ACTIVE_OFFSET,
    RESOURCE_SEGMENT,
    SIDNEY_ALPHA_CONSTRUCTOR_OFFSET,
    SIDNEY_BUTTON_DISPATCH_ADAPTER_OFFSET,
    SIDNEY_CONSTRUCTION_SEGMENT,
    SIDNEY_DRIVING_MAP_INPUT_DEPTH_OFFSET,
    SIDNEY_FINGERPRINT_STATE_OFFSET,
    SIDNEY_FRAME_SOURCE_OFFSET,
    SIDNEY_FRAME_STATE_OFFSET,
    SIDNEY_INPUT_DISPATCHER_OFFSET,
    SIDNEY_NATIVE_BLT_TRAMPOLINE_OFFSET,
    SIDNEY_PORTRAIT_SOURCE_OFFSET,
    SIDNEY_PORTRAIT_STATE_OFFSET,
    SIDNEY_PRESENTATION_SEGMENT,
    SIDNEY_SYSTEM_INPUT_HELPER_OFFSET,
    SIDNEY_TOOLBAR_INPUT_DEPTH_OFFSET,
    SIDNEY_TOOLBAR_INPUT_HELPER_OFFSET,
    SYSTEM_ACTION_PRESENTED_ROOT_OFFSET,
    SYSTEM_CONTROL_CURSOR_CLASSIFIER_OFFSET,
    SYSTEM_CONTROL_SEGMENT,
    SYSTEM_CONTROL_TOOLBAR_INPUT_SOURCE_RECT_OFFSET,
    SYSTEM_CONTROL_TOOLBAR_INPUT_TARGET_RECT_OFFSET,
    SYSTEM_CONTROL_TOOLBAR_INPUT_VALID_OFFSET,
    SYSTEM_SEGMENT,
    TIMEBLOCK_LAYER_OFFSET,
    TIMEBLOCK_LOGICAL_RECT_OFFSET,
    TIMEBLOCK_SEGMENT,
    TIMEBLOCK_TARGET_RECT_OFFSET,
    install_runtime_segment,
)
from gk3hd.patch.definitions.runtime2d.sidney_alpha import (
    build_alpha_wrapper,
    build_caret_wrapper,
    build_solid_fill_wrapper,
)
from gk3hd.patch.definitions.runtime2d.sidney_composition import (
    build_backdrop_helper,
    build_blt_wrapper,
    build_cursor_blt_trace_helper,
    build_damage_selector,
    build_destructor_wrapper,
    build_native_blt_trampoline,
    build_pillarbox_helper,
    build_root_draw_bridge,
    build_root_draw_wrapper,
    build_status_replay_helper,
)
from gk3hd.patch.definitions.runtime2d.sidney_images import SURFACES_SIZE, build_source
from gk3hd.patch.definitions.runtime2d.sidney_input import (
    build_button_dispatch_adapter,
    build_button_dispatch_stub,
    build_button_dispatch_thunk,
    build_input_dispatch_wrapper,
    build_periodic_cursor_select_thunk,
    build_periodic_cursor_select_wrapper,
    build_pointer_motion_dispatch_thunk,
    build_pointer_motion_dispatch_wrapper,
    build_reference_anchor_input_wrapper,
    build_reference_canvas_input_wrapper,
    build_tbt_input_wrapper,
)
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.guard_stale_mouse_move_targets import MouseMoveDispatchABI
    from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols
    from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI


@dataclass(frozen=True, slots=True, kw_only=True)
class SidneyPresentationCompiler:
    """Height-fit SIDNEY without narrowing ordinary widescreen rooms.

    Outcome:
        The complete SIDNEY laptop, status text, cursor, and all hit targets use
        one stable 4:3 composition with black outer pillars when necessary.
    Before:
        Logical SIDNEY rectangles reach a physical framebuffer directly, while
        status glyphs, cursor coordinates, and seven pointer paths use different
        coordinate domains and page lifetimes.
    After:
        SIDNEY stays in 1024x768 model space; its complete traversal, status
        replay, final cursor, and inverse input agree with one live affine.
    Strategy:
        Scope only SIDNEY's root and map ``x' = pillar + x*height/768`` and the
        analogous Y transform (identity at 1024x768). Record status glyphs during
        traversal and replay them after the complete bounded repaint; leave final
        cursor ownership with CursorManager. The shared input dispatcher applies
        the exact inverse to all pointer entries while preserving MouseManager's
        physical state. Separate published affines cover driving-map, timeblock,
        and legacy staged-room picking without activating SIDNEY presentation.
    Boundaries:
        Construction owns the authored model. Ordinary 3D never enters this scope
        and retains its full-width field of view; other fixed screens own their
        own lifetime tags and presentation policies.
    """

    id: ClassVar[str] = "runtime2d.sidney_presentation"

    # The authored laptop is intrinsically 4:3. Black outer bands are one
    # invariant of fitting that complete interface, not a selectable compiler
    # mode. Retain the value in the runtime ABI for capture-time proof.
    _side_policy_black: ClassVar[int] = 2

    symbols: RuntimeSymbols
    profile: BuildProfile
    room_rendering_abi: RoomRenderingABI
    mouse_move_abi: MouseMoveDispatchABI

    _section_name: ClassVar[str] = SIDNEY_PRESENTATION_SEGMENT.logical_name
    _section_size: ClassVar[int] = SIDNEY_PRESENTATION_SEGMENT.size
    _section_characteristics: ClassVar[int] = SIDNEY_PRESENTATION_SEGMENT.characteristics
    _magic: ClassVar[bytes] = SIDNEY_PRESENTATION_SEGMENT.magic
    _off_layout_version: ClassVar[int] = 0x08
    _layout_version: ClassVar[int] = 102

    _off_active_depth: ClassVar[int] = 0x0C
    _off_toolbar_input_depth: ClassVar[int] = SIDNEY_TOOLBAR_INPUT_DEPTH_OFFSET
    _off_transformed_blit_count: ClassVar[int] = 0x1C
    _off_root_draw_wrapper: ClassVar[int] = 0x20
    _off_destructor_wrapper: ClassVar[int] = 0x50
    _off_blt_wrapper: ClassVar[int] = 0xA00
    _off_status_trace_count: ClassVar[int] = 0xD00
    _off_status_trace_records: ClassVar[int] = 0xD10
    _status_trace_capacity: ClassVar[int] = 64
    _status_trace_stride: ClassVar[int] = 40
    _off_blt_rect_scratch: ClassVar[int] = 0xC00
    _off_root_ptr: ClassVar[int] = 0x120
    _off_input_transform_count: ClassVar[int] = 0x124
    _off_input_source_x: ClassVar[int] = 0x128
    _off_input_logical_x: ClassVar[int] = 0x12C
    _off_side_policy: ClassVar[int] = 0x130
    _off_full_damage_count: ClassVar[int] = 0x134
    _off_native_damage_count: ClassVar[int] = 0x138
    # The otherwise unused DWORD before the full-damage REGION retains the
    # Y result paired with input_logical_x for cross-resolution input RCA.
    _off_input_logical_y: ClassVar[int] = 0x13C
    _off_full_damage_region: ClassVar[int] = 0x140
    _off_full_damage_rect: ClassVar[int] = 0x150
    # Bounded evidence for exact 128x128 cursor composition/save-under Blts.
    # The ring records concrete wrapper identities and rectangles without
    # classifying arbitrary small interface sprites as cursor traffic.
    _off_cursor_blt_trace_count: ClassVar[int] = 0x168
    # Keep the growing shared dispatcher in the final private page. Earlier
    # revisions squeezed it between the root bridge and final-blit wrapper;
    # that made an unrelated event-contract improvement depend on a brittle
    # 0x2c0-byte ceiling despite the segment having a complete free page.
    _off_input_wrapper: ClassVar[int] = SIDNEY_INPUT_DISPATCHER_OFFSET
    # Reference-anchor controls use two affines: their centers follow the
    # fitted 4:3 viewport while their extents retain 1024x768 apparent scale.
    # A dedicated input owner mirrors that per-control geometry exactly; the
    # global system inverse cannot represent both scales at once.
    _off_reference_anchor_input_helper: ClassVar[int] = 0x2880
    _off_reference_anchor_input_helper_limit: ClassVar[int] = 0x2C00
    # Reference-canvas roots retain authored 1024x768 object rectangles.  Their
    # input inverse is derived from the live framebuffer, not the system
    # blitter's mutable per-transfer scratch rectangles.  Keeping this helper
    # separate from the hybrid reference-anchor policy makes both ownership
    # contracts explicit and prevents nested cursor/font Blts from changing
    # where a subsequent click lands.
    _off_reference_canvas_input_helper: ClassVar[int] = 0x2C00
    _off_reference_canvas_input_helper_limit: ClassVar[int] = 0x2E00
    # Adapt native UI calls after MouseManager's physical bookkeeping, not
    # the complete mouse methods that retain drag origins across events.
    _off_button_dispatch_adapter: ClassVar[int] = SIDNEY_BUTTON_DISPATCH_ADAPTER_OFFSET
    _off_button_dispatch_thunk: ClassVar[int] = 0x2EC0
    _off_input_stubs: ClassVar[int] = 0x2F00
    _input_stub_size: ClassVar[int] = 15
    _off_backdrop_pending: ClassVar[int] = 0x200
    _off_backdrop_left_rect: ClassVar[int] = 0x210
    _off_backdrop_right_rect: ClassVar[int] = 0x220
    _off_backdrop_bltfx: ClassVar[int] = 0x230
    _off_backdrop_helper: ClassVar[int] = 0x2A0
    _off_damage_selector: ClassVar[int] = 0x4C0
    _off_damage_selector_limit: ClassVar[int] = 0x5C0
    _off_root_draw_bridge_limit: ClassVar[int] = 0x740
    _off_cursor_blt_trace_helper: ClassVar[int] = 0x740
    _off_caret_fill_wrapper: ClassVar[int] = 0x800
    _off_solid_fill_wrapper: ClassVar[int] = 0x950
    _off_extension_helper: ClassVar[int] = 0xC10
    _off_cursor_blt_trace_records: ClassVar[int] = 0x1710
    _cursor_blt_trace_capacity: ClassVar[int] = 8
    _cursor_blt_trace_stride: ClassVar[int] = 60
    # MouseManager owns a second, five-argument pointer-motion traversal after
    # the common +B8/+BC/+50 dispatch. Keep its adapter and one-POINT thunk in
    # the free executable tail after bounded cursor telemetry. This closes the
    # coordinate transaction without moving durable physical cursor or delta
    # state into an authored interface domain.
    _off_motion_dispatch_wrapper: ClassVar[int] = 0x1900
    _off_motion_dispatch_thunk: ClassVar[int] = 0x1A60
    _off_periodic_cursor_select_wrapper: ClassVar[int] = 0x1A80
    _off_periodic_cursor_select_thunk: ClassVar[int] = 0x1AE0
    _off_motion_dispatch_limit: ClassVar[int] = 0x1B00
    _off_extension_surface_ptr: ClassVar[int] = 0x400
    _off_extension_left_dest_rect: ClassVar[int] = 0x410
    _off_extension_right_dest_rect: ClassVar[int] = 0x430
    _off_extension_bltfx: ClassVar[int] = 0x450
    _off_native_blt_trampoline: ClassVar[int] = SIDNEY_NATIVE_BLT_TRAMPOLINE_OFFSET
    _off_status_replay_helper: ClassVar[int] = 0x1B20
    _off_tbt_input_helper: ClassVar[int] = 0x2000
    # Pack the immutable input adapters after the fixed event-stub table. The
    # system adapter occupies its exact 0xf0-byte contract; the toolbar then
    # receives a cohesive 0x140-byte slot before the shared dispatcher.
    _off_system_input_helper: ClassVar[int] = SIDNEY_SYSTEM_INPUT_HELPER_OFFSET
    _off_toolbar_input_helper: ClassVar[int] = SIDNEY_TOOLBAR_INPUT_HELPER_OFFSET
    _off_root_draw_bridge: ClassVar[int] = 0x6D0
    _ddbltfx_size: ClassVar[int] = 0x64
    _ddblt_colorfill_wait: ClassVar[int] = 0x01000400

    _construction_width_offset: ClassVar[int] = 0x18
    _hd_2d_driving_map_input_active_offset: ClassVar[int] = RESOURCE_DRIVING_MAP_INPUT_ACTIVE_OFFSET
    _system_blt_wrapper_offset: ClassVar[int] = 0x300
    _system_cursor_bounds_wrapper_offset: ClassVar[int] = 0xDC0
    _system_input_active_offset: ClassVar[int] = 0x10
    _system_root_ptr_offset: ClassVar[int] = 0x1C
    _system_source_rect_offset: ClassVar[int] = 0x20
    _system_target_rect_offset: ClassVar[int] = 0x30
    _system_transform_mode_offset: ClassVar[int] = 0xE0
    # SystemScreenCompiler retains the currently presented ActionMenu root in
    # the shared system segment. Unlike a
    # child-array position, this identity survives Inventory redraws and is
    # cleared by the concrete ActionMenu destructor.
    _system_composite_mode: ClassVar[int] = 1
    _system_popup_mode: ClassVar[int] = 2
    _system_reference_anchor_mode: ClassVar[int] = 5
    _system_reference_canvas_mode: ClassVar[int] = 6
    _system_reference_canvas_all_mode: ClassVar[int] = 7
    _system_physical_canvas_mode: ClassVar[int] = 8
    _system_bottom_anchored_reference_canvas_mode: ClassVar[int] = 9

    # Cursor presentation and page damage use one physical coordinate space.
    # SystemScreenCompiler owns the cursor-bounds hook; SIDNEY must preserve
    # that hook while continuing to bypass already-physical save-under blits.
    # These two direct calls restore and refresh the software cursor's
    # save-under cache.  Their rectangles are already in physical presentation
    # coordinates even while the SIDNEY root traversal is active.
    # These are the instructions immediately after the three final-blitter
    # calls owned by the resource and system feature compilers. Their stack
    # rectangles have already traversed the shared dispatch chain before they
    # arrive at presentation's entry hook and must not re-enter that chain.
    _cursor_atlas_size: ClassVar[int] = 128

    # SIDNEY's text-resource cache can retain a freed object pointer in its
    # eight-byte entry array.  Depending on how far the freed block has been
    # reused, either the entry itself, the object's vtable, or the string
    # pointer at object+0x24 can already be invalid.  Validate the complete
    # native read boundary and clear a bad vector slot so the cache destructor
    # cannot call through the same stale object later.

    # GK3's global shutdown can retain an already-freed object in its owner
    # list.  The debug allocator replaces the object's vtable with "DNEW",
    # after which the unguarded virtual release at this site faults through
    # 0x57454E44 + 0x10.  Skipping that second release lets the caller remove
    # and clear the stale list entry normally.
    _freed_object_marker: ClassVar[int] = 0x57454E44  # ASCII "DNEW"

    _button_dispatch_sites: ClassVar[tuple[tuple[str, int], ...]] = (
        ("left_press", 1),
        ("right_press", 1),
        ("middle_press", 1),
        ("left_release", 3),
        ("right_release", 3),
        ("middle_release", 3),
        ("left_click", 4),
        ("right_click", 2),
        ("middle_click", 4),
        ("drag_begin", 5),
    )
    _shared_dispatch_site_names: ClassVar[tuple[str, str, str]] = (
        "runtime2d.final_blt_call_1",
        "runtime2d.final_blt_call_2",
        "runtime2d.final_blt_call_3",
    )

    def _site_va(self, name: str) -> int:
        return self.profile.site(name).va

    def _site_bytes(self, name: str) -> bytes:
        return self.profile.site(name).original

    @property
    def _current_layer_va(self) -> int:
        return self.profile.address("ui.current_layer")

    @property
    def _engine_width_init_site_va(self) -> int:
        return self._site_va("display.width_initializer")

    @property
    def _engine_width_init_prefix(self) -> bytes:
        return self._site_bytes("display.width_initializer")

    @property
    def _physical_width_global_va(self) -> int:
        return self.profile.address("display.dimensions")

    @property
    def _sidney_root_destructor_slot_va(self) -> int:
        return self.profile.address("sidney.root_destructor_slot")

    @property
    def _original_root_destructor_va(self) -> int:
        return self.profile.address("sidney.root_destructor")

    @property
    def _sidney_root_draw_slot_va(self) -> int:
        return self.profile.address("sidney.root_draw_slot")

    @property
    def _original_root_draw_va(self) -> int:
        return self.profile.address("ui.container_draw")

    @property
    def _blt_hook_site_va(self) -> int:
        return self._site_va("runtime2d.final_blt_entry")

    @property
    def _blt_hook_back_va(self) -> int:
        return self.profile.address("runtime2d.final_blt_continue")

    @property
    def _blt_hook_orig(self) -> bytes:
        return self._site_bytes("runtime2d.final_blt_entry")

    @property
    def _high_blt_hook_site_va(self) -> int:
        return self._site_va("runtime2d.high_blt_entry")

    @property
    def _high_blt_hook_orig(self) -> bytes:
        return self._site_bytes("runtime2d.high_blt_entry")

    @property
    def _mid_blt_hook_site_va(self) -> int:
        return self._site_va("runtime2d.mid_blt_entry")

    @property
    def _mid_blt_hook_orig(self) -> bytes:
        return self._site_bytes("runtime2d.mid_blt_entry")

    @property
    def _cursor_blt_call_site_va(self) -> int:
        return self._site_va("cursor.final_blt_call")

    @property
    def _cursor_blt_call_orig(self) -> bytes:
        return self._site_bytes("cursor.final_blt_call")

    @property
    def _cursor_save_under_return_vas(self) -> tuple[int, int]:
        return (
            self.profile.address("cursor.save_under_return_1"),
            self.profile.address("cursor.save_under_return_2"),
        )

    @property
    def _shared_dispatch_return_vas(self) -> tuple[int, int, int]:
        first, second, third = self._shared_dispatch_site_names
        return (
            self._site_va(first) + 5,
            self._site_va(second) + 5,
            self._site_va(third) + 5,
        )

    @property
    def _cursor_bounds_hook_site_va(self) -> int:
        return self._site_va("cursor.bounds_hook")

    @property
    def _cursor_bounds_hook_orig(self) -> bytes:
        return self._site_bytes("cursor.bounds_hook")

    @property
    def _stale_lookup_hook_site_va(self) -> int:
        return self._site_va("sidney.stale_lookup")

    @property
    def _stale_lookup_hook_back_va(self) -> int:
        return self.profile.address("sidney.stale_lookup_continue")

    @property
    def _stale_lookup_skip_va(self) -> int:
        return self.profile.address("sidney.stale_lookup_skip")

    @property
    def _stale_lookup_hook_orig(self) -> bytes:
        return self._site_bytes("sidney.stale_lookup")

    @property
    def _is_bad_read_ptr_iat_va(self) -> int:
        return self.profile.address("win32.IsBadReadPtr")

    @property
    def _stale_release_hook_site_va(self) -> int:
        return self._site_va("shutdown.stale_release")

    @property
    def _stale_release_hook_back_va(self) -> int:
        return self.profile.address("shutdown.stale_release_continue")

    @property
    def _stale_release_hook_orig(self) -> bytes:
        return self._site_bytes("shutdown.stale_release")

    @property
    def _stale_update_hook_site_va(self) -> int:
        return self._site_va("shutdown.stale_update")

    @property
    def _stale_update_hook_back_va(self) -> int:
        return self.profile.address("shutdown.stale_update_continue")

    @property
    def _stale_update_hook_orig(self) -> bytes:
        return self._site_bytes("shutdown.stale_update")

    def _construction_width_va(self) -> int:
        return self.symbols.va(
            SIDNEY_CONSTRUCTION_SEGMENT.logical_name, self._construction_width_offset
        )

    def _driving_map_input_active_va(self) -> int:
        return self.symbols.va(
            RESOURCE_SEGMENT.logical_name, self._hd_2d_driving_map_input_active_offset
        )

    def _tbt_input_vas(self) -> tuple[int, int, int]:
        section_va = self.symbols.va(TIMEBLOCK_SEGMENT.logical_name)
        return (
            section_va + TIMEBLOCK_LAYER_OFFSET,
            section_va + TIMEBLOCK_LOGICAL_RECT_OFFSET,
            section_va + TIMEBLOCK_TARGET_RECT_OFFSET,
        )

    def _system_input_vas(self) -> tuple[int, int, int, int, int, int, int, int, int]:
        section_va = self.symbols.va(SYSTEM_SEGMENT.logical_name)
        return (
            section_va + self._system_input_active_offset,
            section_va + self._system_root_ptr_offset,
            section_va + self._system_source_rect_offset,
            section_va + self._system_target_rect_offset,
            section_va + self._system_transform_mode_offset,
            self.symbols.va(SYSTEM_SEGMENT.logical_name, SYSTEM_ACTION_PRESENTED_ROOT_OFFSET),
            self.symbols.va(
                SYSTEM_CONTROL_SEGMENT.logical_name,
                SYSTEM_CONTROL_TOOLBAR_INPUT_SOURCE_RECT_OFFSET,
            ),
            self.symbols.va(
                SYSTEM_CONTROL_SEGMENT.logical_name,
                SYSTEM_CONTROL_TOOLBAR_INPUT_TARGET_RECT_OFFSET,
            ),
            self.symbols.va(
                SYSTEM_CONTROL_SEGMENT.logical_name,
                SYSTEM_CONTROL_TOOLBAR_INPUT_VALID_OFFSET,
            ),
        )

    def _system_blt_wrapper_va(self) -> int:
        """Return the sole general-interface final-blit dispatcher."""
        return self.symbols.va(SYSTEM_SEGMENT.logical_name, self._system_blt_wrapper_offset)

    def _system_cursor_bounds_wrapper_va(self) -> int:
        """Return the shared cursor damage/save-under bounds implementation."""
        return self.symbols.va(
            SYSTEM_SEGMENT.logical_name, self._system_cursor_bounds_wrapper_offset
        )

    @staticmethod
    def _hook_target(site_va: int, hook: bytes) -> int | None:
        instruction = hook[:REL32_INSTRUCTION_SIZE]
        if len(instruction) != REL32_INSTRUCTION_SIZE:
            return None
        try:
            opcode = BranchOpcode(instruction[0])
        except ValueError:
            return None
        return decode_rel32_branch(
            opcode=opcode,
            site_va=site_va,
            instruction=instruction,
        )

    def precheck(self, pe: PEFile) -> None:
        """Validate only cross-owner SIDNEY composition dependencies.

        The mutation plan in :meth:`apply` atomically validates its own root,
        input, stale-lifetime, and final-blit sites on Runtime2D's disposable
        clone. Keeping a second handwritten copy here previously obscured the
        real contract and could disagree with the plan. These remaining sites
        are deliberately not owned here: construction publishes dimensions,
        System owns the shared cursor-bounds hook, and the three blit anchors
        are displaced instructions consumed by SIDNEY's generated bridges.
        """
        # Construction is an explicit predecessor in the fixed compiler graph,
        # but it never redirects GK3's global display-width initializer.
        self._construction_width_va()
        expected_width_init = self._engine_width_init_prefix + struct.pack(
            "<I", self._physical_width_global_va
        )
        if (
            pe.read_bytes(pe.va_to_offset(self._engine_width_init_site_va), 10)
            != expected_width_init
        ):
            msg = f"SIDNEY presentation precheck failed at 0x{self._engine_width_init_site_va:08X}"
            raise PatchError(msg)

        for site_va, original in (
            (self._high_blt_hook_site_va, self._high_blt_hook_orig),
            (self._mid_blt_hook_site_va, self._mid_blt_hook_orig),
            (self._cursor_blt_call_site_va, self._cursor_blt_call_orig),
        ):
            if pe.read_bytes(pe.va_to_offset(site_va), len(original)) != original:
                msg = f"SIDNEY presentation precheck failed at 0x{site_va:08X}"
                raise PatchError(msg)
        cursor_bounds_hook = pe.read_bytes(
            pe.va_to_offset(self._cursor_bounds_hook_site_va),
            len(self._cursor_bounds_hook_orig),
        )
        if self._hook_target(self._cursor_bounds_hook_site_va, cursor_bounds_hook) != (
            self._system_cursor_bounds_wrapper_va()
        ):
            msg = f"SIDNEY presentation precheck failed at 0x{self._cursor_bounds_hook_site_va:08X}"
            raise PatchError(msg)

    def apply(self, pe: PEFile) -> None:
        """Emit scoped SIDNEY draw, input, status, and side-fill behavior."""
        self._construction_width_va()
        section = install_runtime_segment(pe, SIDNEY_PRESENTATION_SEGMENT)

        section_offset = section.pointer_to_raw_data
        section_va = pe.rva_to_va(section.virtual_address)
        existing = pe.read_bytes(section_offset, len(self._magic))
        if existing not in (self._magic, b"\x00" * len(self._magic)):
            msg = "SIDNEY presentation section magic mismatch"
            raise PatchError(msg)
        driving_map_active_va = self._driving_map_input_active_va()
        tbt_input_vas = self._tbt_input_vas()
        system_input_vas = self._system_input_vas()

        active_depth_va = section_va + self._off_active_depth
        transformed_blit_count_va = section_va + self._off_transformed_blit_count
        root_draw_wrapper_va = section_va + self._off_root_draw_wrapper
        destructor_wrapper_va = section_va + self._off_destructor_wrapper
        blt_wrapper_va = section_va + self._off_blt_wrapper
        blt_rect_scratch_va = section_va + self._off_blt_rect_scratch
        cursor_blt_trace_count_va = section_va + self._off_cursor_blt_trace_count
        cursor_blt_trace_helper_va = section_va + self._off_cursor_blt_trace_helper
        cursor_blt_trace_records_va = section_va + self._off_cursor_blt_trace_records
        damage_selector_va = section_va + self._off_damage_selector
        full_damage_region_va = section_va + self._off_full_damage_region
        full_damage_rect_va = section_va + self._off_full_damage_rect
        full_damage_count_va = section_va + self._off_full_damage_count
        native_damage_count_va = section_va + self._off_native_damage_count
        status_trace_count_va = section_va + self._off_status_trace_count
        status_trace_records_va = section_va + self._off_status_trace_records
        root_ptr_va = section_va + self._off_root_ptr
        input_transform_count_va = section_va + self._off_input_transform_count
        input_source_x_va = section_va + self._off_input_source_x
        input_logical_x_va = section_va + self._off_input_logical_x
        input_logical_y_va = section_va + self._off_input_logical_y
        input_wrapper_va = section_va + self._off_input_wrapper
        reference_anchor_input_wrapper_va = section_va + self._off_reference_anchor_input_helper
        reference_canvas_input_wrapper_va = section_va + self._off_reference_canvas_input_helper
        tbt_input_wrapper_va = section_va + self._off_tbt_input_helper
        system_input_wrapper_va = section_va + self._off_system_input_helper
        toolbar_input_wrapper_va = section_va + self._off_toolbar_input_helper
        toolbar_input_depth_va = section_va + self._off_toolbar_input_depth
        backdrop_pending_va = section_va + self._off_backdrop_pending
        backdrop_left_rect_va = section_va + self._off_backdrop_left_rect
        backdrop_right_rect_va = section_va + self._off_backdrop_right_rect
        backdrop_bltfx_va = section_va + self._off_backdrop_bltfx
        extension_surface_ptr_va = section_va + self._off_extension_surface_ptr
        extension_left_dest_rect_va = section_va + self._off_extension_left_dest_rect
        extension_right_dest_rect_va = section_va + self._off_extension_right_dest_rect
        extension_bltfx_va = section_va + self._off_extension_bltfx
        extension_helper_va = section_va + self._off_extension_helper
        native_blt_trampoline_va = section_va + self._off_native_blt_trampoline
        status_replay_helper_va = section_va + self._off_status_replay_helper
        root_draw_bridge_va = section_va + self._off_root_draw_bridge
        # The presentation, input, and extension helpers derive their transform
        # from the live engine globals. Section data therefore has no patch-time
        # resolution contract: one executable remains valid after a resolution
        # change in GK3's Graphics menu.
        zero_rect = b"\x00" * 16
        backdrop_left_rect = zero_rect
        backdrop_right_rect = zero_rect
        backdrop_bltfx = bytearray(self._ddbltfx_size)
        struct.pack_into("<I", backdrop_bltfx, 0, self._ddbltfx_size)
        extension_left_dest_rect = zero_rect
        extension_right_dest_rect = zero_rect
        extension_bltfx = bytearray(self._ddbltfx_size)
        struct.pack_into("<I", extension_bltfx, 0, self._ddbltfx_size)

        root_wrapper = build_root_draw_wrapper(
            wrapper_va=root_draw_wrapper_va,
            active_depth_va=active_depth_va,
            root_ptr_va=root_ptr_va,
            status_trace_count_va=status_trace_count_va,
            backdrop_pending_va=backdrop_pending_va,
            enable_backdrop=False,
            # The bridge is part of the core fit, not merely a side policy: it
            # replays the status line through the same affine in every mode.
            draw_target_va=root_draw_bridge_va,
        )
        destructor_wrapper = build_destructor_wrapper(
            self,
            wrapper_va=destructor_wrapper_va,
            active_depth_va=active_depth_va,
            transformed_blit_count_va=transformed_blit_count_va,
            root_ptr_va=root_ptr_va,
            backdrop_pending_va=backdrop_pending_va,
            extension_surface_ptr_va=extension_surface_ptr_va,
            portrait_surfaces_va=section_va + SIDNEY_PORTRAIT_STATE_OFFSET,
            fingerprint_surfaces_va=self.symbols.va(
                SIDNEY_CONSTRUCTION_SEGMENT.logical_name, SIDNEY_FINGERPRINT_STATE_OFFSET
            ),
            frame_state_va=self.symbols.va(
                SIDNEY_CONSTRUCTION_SEGMENT.logical_name, SIDNEY_FRAME_STATE_OFFSET
            ),
        )
        blt_wrapper = build_blt_wrapper(
            self,
            wrapper_va=blt_wrapper_va,
            active_depth_va=active_depth_va,
            transformed_blit_count_va=transformed_blit_count_va,
            rect_scratch_va=blt_rect_scratch_va,
            cursor_blt_trace_helper_va=cursor_blt_trace_helper_va,
            extension_surface_ptr_va=extension_surface_ptr_va,
            status_trace_count_va=status_trace_count_va,
            status_trace_records_va=status_trace_records_va,
            system_blt_wrapper_va=self._system_blt_wrapper_va(),
            portrait_source_va=section_va + SIDNEY_PORTRAIT_SOURCE_OFFSET,
            frame_source_va=self.symbols.va(
                SIDNEY_CONSTRUCTION_SEGMENT.logical_name, SIDNEY_FRAME_SOURCE_OFFSET
            ),
            cursor_surface_classifier_va=self.symbols.va(
                SYSTEM_CONTROL_SEGMENT.logical_name, SYSTEM_CONTROL_CURSOR_CLASSIFIER_OFFSET
            ),
        )
        tbt_input_wrapper = build_tbt_input_wrapper(
            self,
            input_transform_count_va=input_transform_count_va,
            input_source_x_va=input_source_x_va,
            input_logical_x_va=input_logical_x_va,
            input_logical_y_va=input_logical_y_va,
            logical_rect_va=tbt_input_vas[1],
            target_rect_va=tbt_input_vas[2],
            persistent_root_va=tbt_input_vas[0],
        )
        system_input_wrapper = build_tbt_input_wrapper(
            self,
            input_transform_count_va=input_transform_count_va,
            input_source_x_va=input_source_x_va,
            input_logical_x_va=input_logical_x_va,
            input_logical_y_va=input_logical_y_va,
            logical_rect_va=system_input_vas[2],
            target_rect_va=system_input_vas[3],
            persistent_root_va=None,
        )
        toolbar_input_wrapper = build_tbt_input_wrapper(
            self,
            input_transform_count_va=input_transform_count_va,
            input_source_x_va=input_source_x_va,
            input_logical_x_va=input_logical_x_va,
            input_logical_y_va=input_logical_y_va,
            logical_rect_va=system_input_vas[6],
            target_rect_va=system_input_vas[7],
            persistent_root_va=None,
            rect_valid_va=system_input_vas[8],
            scope_depth_va=toolbar_input_depth_va,
            toolbar_height_va=self._physical_width_global_va + 4,
        )
        reference_anchor_input_wrapper = build_reference_anchor_input_wrapper(
            self,
            wrapper_va=reference_anchor_input_wrapper_va,
            system_root_ptr_va=system_input_vas[1],
            system_input_wrapper_va=system_input_wrapper_va,
            input_transform_count_va=input_transform_count_va,
            input_source_x_va=input_source_x_va,
            input_logical_x_va=input_logical_x_va,
        )
        reference_canvas_input_wrapper = build_reference_canvas_input_wrapper(
            self,
            wrapper_va=reference_canvas_input_wrapper_va,
            system_transform_mode_va=system_input_vas[4],
            input_transform_count_va=input_transform_count_va,
            input_source_x_va=input_source_x_va,
            input_logical_x_va=input_logical_x_va,
            input_logical_y_va=input_logical_y_va,
        )
        input_wrapper = build_input_dispatch_wrapper(
            self,
            wrapper_va=input_wrapper_va,
            root_ptr_va=root_ptr_va,
            input_transform_count_va=input_transform_count_va,
            input_source_x_va=input_source_x_va,
            input_logical_x_va=input_logical_x_va,
            driving_map_active_va=driving_map_active_va,
            driving_map_input_depth_va=(section_va + SIDNEY_DRIVING_MAP_INPUT_DEPTH_OFFSET),
            tbt_layer_va=tbt_input_vas[0],
            tbt_target_rect_va=tbt_input_vas[2],
            tbt_input_wrapper_va=tbt_input_wrapper_va,
            system_active_va=system_input_vas[0],
            system_root_ptr_va=system_input_vas[1],
            system_transform_mode_va=system_input_vas[4],
            system_input_wrapper_va=system_input_wrapper_va,
            toolbar_input_wrapper_va=toolbar_input_wrapper_va,
            reference_anchor_input_wrapper_va=reference_anchor_input_wrapper_va,
            reference_canvas_input_wrapper_va=reference_canvas_input_wrapper_va,
            binocs_input_wrapper_va=self.symbols.va(
                BINOCULAR_SEGMENT.logical_name,
                BINOCULAR_INPUT_HELPER_OFFSET,
            ),
            system_action_presented_root_va=system_input_vas[5],
            # Load/Save publishes physical object rectangles.
            # InGameToolbar deliberately does not: its final Blt rectangles
            # are scaled while the native 252x75 object graph remains intact,
            # so visible pointer coordinates must traverse the exact inverse.
            system_native_input_vtables=(
                self.profile.address("loadgame.vtable"),
                self.profile.address("savegame.vtable"),
            ),
        )
        motion_dispatch_wrapper_va = section_va + self._off_motion_dispatch_wrapper
        motion_dispatch_thunk_va = section_va + self._off_motion_dispatch_thunk
        motion_dispatch_thunk = build_pointer_motion_dispatch_thunk(
            self,
            wrapper_va=motion_dispatch_thunk_va,
        )
        motion_dispatch_wrapper = build_pointer_motion_dispatch_wrapper(
            wrapper_va=motion_dispatch_wrapper_va,
            input_wrapper_va=input_wrapper_va,
            thunk_va=motion_dispatch_thunk_va,
            native_dispatch_va=self.profile.address("mouse_move.motion_dispatch"),
            physical_width_va=self._physical_width_global_va,
            tbt_layer_va=tbt_input_vas[0],
            current_layer_va=self._current_layer_va,
            driving_map_active_va=driving_map_active_va,
            inventory_active_va=self.symbols.va(
                INVENTORY_SEGMENT.logical_name,
                INVENTORY_ACTIVE_ROOT_OFFSET,
            ),
            toolbar_input_valid_va=system_input_vas[8],
            system_active_va=system_input_vas[0],
            system_transform_mode_va=system_input_vas[4],
            toolbar_transform_mode=self._system_popup_mode,
            reference_canvas_transform_mode=self._system_reference_canvas_mode,
            system_root_ptr_va=system_input_vas[1],
            toolbar_vtable_va=self.profile.address("ingame_toolbar.vtable"),
            death_vtable_va=self.profile.address("death.vtable"),
            zodiac_vtable_va=self.profile.address("zodiac.vtable"),
            is_bad_read_ptr_va=self.profile.address("win32.IsBadReadPtr"),
        )
        periodic_cursor_select_wrapper_va = section_va + self._off_periodic_cursor_select_wrapper
        periodic_cursor_select_thunk_va = section_va + self._off_periodic_cursor_select_thunk
        periodic_cursor_select_thunk = build_periodic_cursor_select_thunk(
            self,
            wrapper_va=periodic_cursor_select_thunk_va,
        )
        periodic_cursor_select_wrapper = build_periodic_cursor_select_wrapper(
            wrapper_va=periodic_cursor_select_wrapper_va,
            input_wrapper_va=input_wrapper_va,
            thunk_va=periodic_cursor_select_thunk_va,
        )
        # Keep ALL MouseManager slots native. Converting its complete button
        # method also converted retained drag origins, so the next physical
        # pointer poll turned a stationary click into a large drag.
        button_adapter_va = section_va + self._off_button_dispatch_adapter
        button_thunk_va = section_va + self._off_button_dispatch_thunk
        button_adapter = build_button_dispatch_adapter(
            wrapper_va=button_adapter_va,
            input_wrapper_va=input_wrapper_va,
            thunk_va=button_thunk_va,
        )
        button_thunk = build_button_dispatch_thunk(wrapper_va=button_thunk_va)
        input_stubs = tuple(
            (
                index,
                build_button_dispatch_stub(
                    stub_va=section_va + self._off_input_stubs + index * self._input_stub_size,
                    wrapper_va=button_adapter_va,
                    original_va=self._site_va(f"input.{name}_dispatch_call")
                    + 5
                    + struct.unpack("<i", self._site_bytes(f"input.{name}_dispatch_call")[1:])[0],
                    argument_count=argument_count,
                    map_drag_anchor=name == "drag_begin",
                ),
            )
            for index, (name, argument_count) in enumerate(self._button_dispatch_sites)
        )
        extension_helper = build_pillarbox_helper(
            self,
            surface_ptr_va=extension_surface_ptr_va,
            left_rect_va=extension_left_dest_rect_va,
            right_rect_va=extension_right_dest_rect_va,
            bltfx_va=extension_bltfx_va,
        )
        native_blt_trampoline = build_native_blt_trampoline(
            self,
            wrapper_va=native_blt_trampoline_va,
        )
        status_replay_helper = build_status_replay_helper(
            self,
            wrapper_va=status_replay_helper_va,
            status_trace_count_va=status_trace_count_va,
            status_trace_records_va=status_trace_records_va,
            native_blt_trampoline_va=native_blt_trampoline_va,
        )
        cursor_blt_trace_helper = build_cursor_blt_trace_helper(
            self,
            wrapper_va=cursor_blt_trace_helper_va,
            trace_count_va=cursor_blt_trace_count_va,
            trace_records_va=cursor_blt_trace_records_va,
        )
        damage_selector = build_damage_selector(
            self,
            wrapper_va=damage_selector_va,
            full_region_va=full_damage_region_va,
            full_damage_count_va=full_damage_count_va,
            native_damage_count_va=native_damage_count_va,
        )
        root_draw_bridge = build_root_draw_bridge(
            self,
            wrapper_va=root_draw_bridge_va,
            extension_helper_va=extension_helper_va,
            status_replay_helper_va=status_replay_helper_va,
            damage_selector_va=damage_selector_va,
        )
        backdrop_helper = build_backdrop_helper(
            self,
            pending_va=backdrop_pending_va,
            left_rect_va=backdrop_left_rect_va,
            right_rect_va=backdrop_right_rect_va,
            bltfx_va=backdrop_bltfx_va,
        )
        payload = SegmentPayloadBuilder(
            owner=self.id,
            segment=SIDNEY_PRESENTATION_SEGMENT.logical_name,
            size=SIDNEY_PRESENTATION_SEGMENT.size,
        )
        alpha_wrapper = build_alpha_wrapper(
            wrapper_va=section_va + SIDNEY_ALPHA_CONSTRUCTOR_OFFSET,
            target_va=self.symbols.va(
                INVENTORY_SEGMENT.logical_name, INVENTORY_ALPHA_CONSTRUCTOR_OFFSET
            ),
            active_depth_va=active_depth_va,
            hud_font_active_va=self.symbols.va(
                LOAD_SAVE_SEGMENT.logical_name, LOAD_SAVE_HUD_FONT_ACTIVE_OFFSET
            ),
            physical_width_va=self._physical_width_global_va,
            cursor_classifier_va=self.symbols.va(
                SYSTEM_CONTROL_SEGMENT.logical_name, SYSTEM_CONTROL_CURSOR_CLASSIFIER_OFFSET
            ),
        )
        caret_wrapper = build_caret_wrapper(
            wrapper_va=section_va + self._off_caret_fill_wrapper,
            target_va=self.profile.address("bitmap.fill_rectangle"),
            resolve_bitmap_va=self.profile.address("bitmap.resolve_resource"),
            active_depth_va=active_depth_va,
            physical_width_va=self._physical_width_global_va,
            save_text_active_va=self.symbols.va(
                LOAD_SAVE_SEGMENT.logical_name, LOAD_SAVE_TEXT_ACTIVE_OFFSET
            ),
            save_edit_vtable_va=self.profile.address("savegame_edit.vtable"),
            save_point_helper_va=self.symbols.va(
                LOAD_SAVE_SEGMENT.logical_name, LOAD_SAVE_FONT_POINT_HELPER_OFFSET
            ),
        )
        solid_fill_wrapper = build_solid_fill_wrapper(
            wrapper_va=section_va + self._off_solid_fill_wrapper,
            target_va=self.profile.address("bitmap.solid_fill"),
            active_depth_va=active_depth_va,
            physical_width_va=self._physical_width_global_va,
        )
        payload.place(label="magic", offset=0, payload=self._magic)
        payload.place(
            label="layout version",
            offset=self._off_layout_version,
            payload=struct.pack("<I", self._layout_version),
        )
        payload.reserve(
            label="scope and toolbar depths",
            offset=self._off_active_depth,
            size=self._off_root_draw_wrapper - self._off_active_depth,
        )
        payload.reserve(
            label="root and input trace state",
            offset=self._off_root_ptr,
            size=self._off_side_policy - self._off_root_ptr,
        )
        payload.place(
            label="side policy",
            offset=self._off_side_policy,
            payload=struct.pack("<I", self._side_policy_black),
        )
        payload.reserve(label="damage counters", offset=self._off_full_damage_count, size=8)
        payload.reserve(label="input Y trace", offset=self._off_input_logical_y, size=4)
        payload.place(
            label="complete damage collection",
            offset=self._off_full_damage_region,
            payload=struct.pack(
                "<IIII",
                0,
                full_damage_rect_va,
                full_damage_rect_va + 16,
                0,
            )
            + struct.pack(
                "<iiii",
                0,
                0,
                AUTHORED_FRAME_WIDTH,
                AUTHORED_FRAME_HEIGHT,
            ),
        )
        payload.reserve(
            label="cursor blit trace count",
            offset=self._off_cursor_blt_trace_count,
            size=4,
        )
        payload.reserve(label="backdrop pending", offset=self._off_backdrop_pending, size=4)
        payload.place(
            label="backdrop left rectangle",
            offset=self._off_backdrop_left_rect,
            payload=backdrop_left_rect,
        )
        payload.place(
            label="backdrop right rectangle",
            offset=self._off_backdrop_right_rect,
            payload=backdrop_right_rect,
        )
        payload.place(
            label="backdrop fill descriptor",
            offset=self._off_backdrop_bltfx,
            payload=bytes(backdrop_bltfx),
        )
        payload.reserve(
            label="extension surface",
            offset=self._off_extension_surface_ptr,
            size=4,
        )
        payload.place(
            label="extension left rectangle",
            offset=self._off_extension_left_dest_rect,
            payload=extension_left_dest_rect,
        )
        payload.place(
            label="extension right rectangle",
            offset=self._off_extension_right_dest_rect,
            payload=extension_right_dest_rect,
        )
        payload.place(
            label="extension fill descriptor",
            offset=self._off_extension_bltfx,
            payload=bytes(extension_bltfx),
        )
        for label, offset, code, limit in (
            ("root draw", self._off_root_draw_wrapper, root_wrapper, self._off_destructor_wrapper),
            ("destructor", self._off_destructor_wrapper, destructor_wrapper, self._off_root_ptr),
            (
                "backdrop",
                self._off_backdrop_helper,
                backdrop_helper,
                self._off_extension_surface_ptr,
            ),
            (
                "damage selector",
                self._off_damage_selector,
                damage_selector,
                self._off_damage_selector_limit,
            ),
            (
                "root draw bridge",
                self._off_root_draw_bridge,
                root_draw_bridge,
                self._off_root_draw_bridge_limit,
            ),
            (
                "cursor blit trace",
                self._off_cursor_blt_trace_helper,
                cursor_blt_trace_helper,
                self._off_caret_fill_wrapper,
            ),
            (
                "editbox caret fill",
                self._off_caret_fill_wrapper,
                caret_wrapper,
                self._off_solid_fill_wrapper,
            ),
            (
                "solid framebuffer fill",
                self._off_solid_fill_wrapper,
                solid_fill_wrapper,
                self._off_blt_wrapper,
            ),
            ("final blit", self._off_blt_wrapper, blt_wrapper, self._off_blt_rect_scratch),
            (
                "outer-band extension",
                self._off_extension_helper,
                extension_helper,
                self._off_status_trace_count,
            ),
            (
                "native blit trampoline",
                self._off_native_blt_trampoline,
                native_blt_trampoline,
                self._off_status_replay_helper,
            ),
            (
                "status replay",
                self._off_status_replay_helper,
                status_replay_helper,
                SIDNEY_ALPHA_CONSTRUCTOR_OFFSET,
            ),
            (
                "software-alpha composition",
                SIDNEY_ALPHA_CONSTRUCTOR_OFFSET,
                alpha_wrapper,
                SIDNEY_PORTRAIT_SOURCE_OFFSET,
            ),
            (
                "TimeBlock input",
                self._off_tbt_input_helper,
                tbt_input_wrapper,
                self._off_system_input_helper,
            ),
            (
                "system input",
                self._off_system_input_helper,
                system_input_wrapper,
                self._off_toolbar_input_helper,
            ),
            (
                "toolbar input",
                self._off_toolbar_input_helper,
                toolbar_input_wrapper,
                self._off_input_wrapper,
            ),
            (
                "input dispatcher",
                self._off_input_wrapper,
                input_wrapper,
                self._off_reference_anchor_input_helper,
            ),
            (
                "reference-anchor input",
                self._off_reference_anchor_input_helper,
                reference_anchor_input_wrapper,
                self._off_reference_anchor_input_helper_limit,
            ),
            (
                "reference-canvas input",
                self._off_reference_canvas_input_helper,
                reference_canvas_input_wrapper,
                self._off_reference_canvas_input_helper_limit,
            ),
            (
                "button UI dispatch adapter",
                self._off_button_dispatch_adapter,
                button_adapter,
                self._off_button_dispatch_thunk,
            ),
            (
                "button UI dispatch thunk",
                self._off_button_dispatch_thunk,
                button_thunk,
                self._off_input_stubs,
            ),
        ):
            payload.place(label=label, offset=offset, payload=code, limit=limit)
        payload.reserve(label="final-blit scratch", offset=self._off_blt_rect_scratch, size=16)
        payload.reserve(
            label="illustration surfaces and source scratch",
            offset=SIDNEY_PORTRAIT_STATE_OFFSET,
            size=SURFACES_SIZE + 24,
        )
        payload.place(
            label="illustration source sampling",
            offset=SIDNEY_PORTRAIT_SOURCE_OFFSET,
            payload=build_source(
                fingerprint_surfaces_va=self.symbols.va(
                    SIDNEY_CONSTRUCTION_SEGMENT.logical_name, SIDNEY_FINGERPRINT_STATE_OFFSET
                ),
                wrapper_va=section_va + SIDNEY_PORTRAIT_SOURCE_OFFSET,
                surfaces_va=section_va + SIDNEY_PORTRAIT_STATE_OFFSET,
                scratch_va=section_va + SIDNEY_PORTRAIT_STATE_OFFSET + SURFACES_SIZE,
            ),
            limit=SIDNEY_PORTRAIT_STATE_OFFSET,
        )
        payload.reserve(label="status trace count", offset=self._off_status_trace_count, size=4)
        payload.reserve(
            label="status trace records",
            offset=self._off_status_trace_records,
            size=self._status_trace_capacity * self._status_trace_stride,
        )
        payload.reserve(
            label="cursor blit trace records",
            offset=self._off_cursor_blt_trace_records,
            size=self._cursor_blt_trace_capacity * self._cursor_blt_trace_stride,
        )
        payload.place(
            label="pointer-motion tail adapter",
            offset=self._off_motion_dispatch_wrapper,
            payload=motion_dispatch_wrapper,
            limit=self._off_motion_dispatch_thunk,
        )
        payload.place(
            label="pointer-motion native thunk",
            offset=self._off_motion_dispatch_thunk,
            payload=motion_dispatch_thunk,
            limit=self._off_periodic_cursor_select_wrapper,
        )
        payload.place(
            label="periodic cursor-selection adapter",
            offset=self._off_periodic_cursor_select_wrapper,
            payload=periodic_cursor_select_wrapper,
            limit=self._off_periodic_cursor_select_thunk,
        )
        payload.place(
            label="periodic cursor-selection native thunk",
            offset=self._off_periodic_cursor_select_thunk,
            payload=periodic_cursor_select_thunk,
            limit=self._off_motion_dispatch_limit,
        )
        for index, stub in input_stubs:
            payload.place(
                label=f"input event stub {index}",
                offset=self._off_input_stubs + index * self._input_stub_size,
                payload=stub,
                limit=self._section_size,
            )
        pe.write_bytes(section_offset, payload.build())

        mutations = ExecutableMutationPlan(owner=self.id)
        solid_fill_site = self.profile.site("bitmap.solid_fill_call")
        mutations.branch(
            label="SIDNEY solid framebuffer fill",
            opcode=BranchOpcode.CALL,
            site_va=solid_fill_site.va,
            expected=solid_fill_site.original,
            target_va=section_va + self._off_solid_fill_wrapper,
            size=len(solid_fill_site.original),
        )
        caret_site = self.profile.site("editbox.caret_fill_call")
        mutations.branch(
            label="SIDNEY editbox caret fill",
            opcode=BranchOpcode.CALL,
            site_va=caret_site.va,
            expected=caret_site.original,
            target_va=section_va + self._off_caret_fill_wrapper,
            size=len(caret_site.original),
        )
        mutations.pointer(
            label="SIDNEY root draw",
            slot_va=self._sidney_root_draw_slot_va,
            expected=self._original_root_draw_va,
            target_va=root_draw_wrapper_va,
        )
        mutations.pointer(
            label="SIDNEY root destructor",
            slot_va=self._sidney_root_destructor_slot_va,
            expected=self._original_root_destructor_va,
            target_va=destructor_wrapper_va,
        )
        mutations.branch(
            label="SIDNEY final blit",
            opcode=BranchOpcode.JUMP,
            site_va=self._blt_hook_site_va,
            expected=self._blt_hook_orig,
            target_va=blt_wrapper_va,
            size=len(self._blt_hook_orig),
        )
        for index, (name, _argument_count) in enumerate(self._button_dispatch_sites):
            site = self.profile.site(f"input.{name}_dispatch_call")
            mutations.branch(
                label=f"button UI dispatch: {name}",
                opcode=BranchOpcode.CALL,
                site_va=site.va,
                expected=site.original,
                target_va=section_va + self._off_input_stubs + index * self._input_stub_size,
                size=len(site.original),
            )
        mutations.pointer(
            label="mouse-move UI dispatch adapter",
            slot_va=self.mouse_move_abi.ui_dispatch_adapter_slot_va,
            expected=0,
            target_va=input_wrapper_va,
        )
        motion_dispatch_site = self.profile.site("mouse_move.motion_dispatch_call")
        mutations.branch(
            label="toolbar trailing pointer dispatch",
            opcode=BranchOpcode.CALL,
            site_va=motion_dispatch_site.va,
            expected=motion_dispatch_site.original,
            target_va=motion_dispatch_wrapper_va,
            size=len(motion_dispatch_site.original),
        )
        for label, site_name in (
            ("periodic fixed-interface cursor selection", "mouse_move.periodic_cursor_select_call"),
            ("idle fixed-interface cursor selection", "mouse_move.idle_cursor_select_call"),
        ):
            site = self.profile.site(site_name)
            mutations.branch(
                label=label,
                opcode=BranchOpcode.CALL,
                site_va=site.va,
                expected=site.original,
                target_va=periodic_cursor_select_wrapper_va,
                size=len(site.original),
            )
        mutations.apply(pe)

    def postcheck(self, pe: PEFile) -> None:
        """Require this owner's segment after deterministic compilation.

        :class:`Runtime2DCompiler` independently rebuilds every logical segment
        and executable redirect, then compares the complete installed image.
        Reconstructing SIDNEY's wrappers and hook graph again here duplicated
        that generic proof and let verification drift into a second compiler.
        """
        if pe.get_section(self._section_name) is None:
            msg = f"{self.id} postcheck failed: section missing"
            raise PatchError(msg)
