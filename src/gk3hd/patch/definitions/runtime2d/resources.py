"""Compile fixed-interface resource policies into the shared runtime."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode
from gk3hd.patch.definitions.runtime2d.geometry import (
    AUTHORED_FRAME_HEIGHT,
    RESTORE_PROGRESS_LOGICAL_HEIGHT,
    RESTORE_PROGRESS_LOGICAL_WIDTH,
)
from gk3hd.patch.definitions.runtime2d.layout import (
    FINGERPRINT_SEGMENT,
    RESOURCE_DRIVING_MAP_INPUT_ACTIVE_OFFSET,
    RESOURCE_DRIVING_MAP_SEEN_OFFSET,
    RESOURCE_PROGRESS_DRAW_DEPTH_OFFSET,
    RESOURCE_PROGRESS_TRANSFORM_COUNT_OFFSET,
    RESOURCE_SEGMENT,
    SIDNEY_NATIVE_BLT_TRAMPOLINE_OFFSET,
    SIDNEY_PRESENTATION_SEGMENT,
    SYSTEM_CONTROL_CURSOR_STATE_OFFSET,
    SYSTEM_CONTROL_FULL_DAMAGE_RECT_OFFSET,
    SYSTEM_CONTROL_FULL_DAMAGE_REGION_OFFSET,
    SYSTEM_CONTROL_SEGMENT,
    SYSTEM_INPUT_ACTIVE_OFFSET,
    SYSTEM_RENDER_DEPTH_OFFSET,
    SYSTEM_SEGMENT,
    SYSTEM_TRANSFORM_MODE_OFFSET,
    TIMEBLOCK_LAYER_OFFSET,
    TIMEBLOCK_LOGICAL_RECT_OFFSET,
    TIMEBLOCK_OVERLAY_SURFACE_OFFSET,
    TIMEBLOCK_RAW_HEIGHT_OFFSET,
    TIMEBLOCK_SEGMENT,
    TIMEBLOCK_TARGET_RECT_OFFSET,
    install_runtime_segment,
)
from gk3hd.patch.definitions.runtime2d.resource_driving_map import (
    build_destructor as build_driving_map_destructor,
)
from gk3hd.patch.definitions.runtime2d.resource_driving_map import (
    build_draw_scope as build_driving_map_draw_scope,
)
from gk3hd.patch.definitions.runtime2d.resource_driving_map import (
    build_marker_ellipse as build_driving_map_marker_ellipse,
)
from gk3hd.patch.definitions.runtime2d.resource_driving_map import (
    build_source_grid_rect,
    correct_location_origins,
)
from gk3hd.patch.definitions.runtime2d.resource_selection import (
    build_bitmap_identity_probe,
    build_closeup_identity_tag,
    build_resource_blit_dispatcher,
)
from gk3hd.patch.definitions.runtime2d.resource_timeblock import build_blit as build_timeblock_blit
from gk3hd.patch.definitions.runtime2d.resource_timeblock import (
    build_center as build_timeblock_center,
)
from gk3hd.patch.definitions.runtime2d.resource_timeblock import (
    build_root_draw as build_timeblock_root_draw,
)
from gk3hd.patch.definitions.runtime2d.timeblock_overlay import (
    build_border_draw,
    build_overlay_draw,
)
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameABI
    from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols


@dataclass(frozen=True, slots=True, kw_only=True)
class ResourceDispatchCompiler:
    """Restore authored model geometry for recognized dense 2D resources.

    Outcome:
        Replacement rasters contribute extra source detail without changing the
        apparent size, clipping, reveal animation, or input of their UI objects.
    Before:
        GK3 treats bitmap pixel dimensions as logical dimensions. Exact 4x art is
        therefore centered, clipped, and hit-tested as an object four times too
        large; independently drawn overlays can also leave the parent affine.
    After:
        Recognized resources keep complete dense sources but present into their
        stock logical rectangles. Unrecognized 2D art and all 3D textures remain
        byte-for-byte on GK3's original path.
    Strategy:
        Own the two calls in the clipped-sprite sink and classify by exact resource
        identity plus dimensions, never by output resolution. Restore progress
        keeps a 513x50 destination and expands only its currently revealed source
        prefix, preserving left-to-right disclosure. ``MS3I`` museum panels and
        tagged evidence views retain centered 640x480 scale. ``DM_BASE`` and its
        bitmap/GDI marker overlays share one 4:3 affine and inverse; the exact
        DrivingMapLayer redraws against complete physical damage. ``TBT*``
        temporarily exposes quarter-size model bounds during the top-level draw
        and seeds both pillar regions. SIDNEY backgrounds use the shared UI
        resource adapter before clipping, not this late geometry dispatcher.
        The shared dispatcher remains the sole low-level blit owner.
    Boundaries:
        This feature does not globally reinterpret equal-sized surfaces, alter
        ordinary room field of view, or recognize named HD/UHD output modes.
        Feature root lifetime, cursor transactions, and generic input dispatch
        remain with their dedicated owners.
    """

    symbols: RuntimeSymbols
    profile: BuildProfile
    transition_abi: TransitionFrameABI

    id: ClassVar[str] = "runtime2d.resources"

    _section_name: ClassVar[str] = RESOURCE_SEGMENT.logical_name
    _section_size: ClassVar[int] = RESOURCE_SEGMENT.size
    _section_characteristics: ClassVar[int] = RESOURCE_SEGMENT.characteristics
    _magic: ClassVar[bytes] = RESOURCE_SEGMENT.magic
    _layout_version: ClassVar[int] = 67
    _timeblock_section_name: ClassVar[str] = TIMEBLOCK_SEGMENT.logical_name
    _timeblock_layout_version: ClassVar[int] = 10
    _off_layout_version: ClassVar[int] = 0x08
    _off_dest_rect: ClassVar[int] = 0x10
    _off_source_rect: ClassVar[int] = 0x20
    _off_slider_trace_count: ClassVar[int] = 0x60
    _off_slider_last_record: ClassVar[int] = 0x64
    _off_slider_transform_count: ClassVar[int] = 0x94
    _off_closeup_transform_count: ClassVar[int] = 0xA0
    _off_closeup_raw_width: ClassVar[int] = 0xA4
    _off_closeup_raw_height: ClassVar[int] = 0xA8
    _off_closeup_target_width: ClassVar[int] = 0xAC
    _off_closeup_target_height: ClassVar[int] = 0xB0
    _off_closeup_rect: ClassVar[int] = 0xB4
    _off_closeup_active_handle: ClassVar[int] = 0xD0
    _off_closeup_observed_source: ClassVar[int] = 0xD4
    _off_closeup_observed_drawable: ClassVar[int] = 0xD8
    _off_closeup_observed_resource: ClassVar[int] = 0xDC
    _off_resource_lookup_active: ClassVar[int] = 0xE0
    _off_closeup_active_surface: ClassVar[int] = 0xE4
    _off_museum_surface: ClassVar[int] = 0xE8
    _off_closeup_sprite: ClassVar[int] = 0xEC
    _off_wrapper: ClassVar[int] = 0x100
    # Keep the unrelated close-up resolver in a disjoint tail page instead of
    # compressing either policy into a fragile branch-distance budget.
    _off_closeup_tag_wrapper: ClassVar[int] = 0x1800
    _off_closeup_tag_wrapper_limit: ClassVar[int] = 0x2000
    _off_bitmap_entry_probe: ClassVar[int] = 0xA00
    _off_bitmap_entry_probe_limit: ClassVar[int] = 0xC00
    _off_bitmap_probe_resource: ClassVar[int] = 0xE00
    _off_bitmap_probe_child: ClassVar[int] = 0xE04
    _off_bitmap_probe_handle: ClassVar[int] = 0xE08
    _off_bitmap_probe_surface: ClassVar[int] = 0xE0C
    _off_driving_map_transform_count: ClassVar[int] = 0xE10
    _off_driving_map_rect: ClassVar[int] = 0xE14
    _off_driving_map_scope_active: ClassVar[int] = 0xE24
    _off_driving_map_seen: ClassVar[int] = RESOURCE_DRIVING_MAP_SEEN_OFFSET
    _off_driving_map_input_active: ClassVar[int] = RESOURCE_DRIVING_MAP_INPUT_ACTIVE_OFFSET
    # TimeBlock owns a separate runtime page. Its final blitter has the largest
    # budget; root lifetime and construction each retain explicit upper bounds.
    _off_tbt_blit_wrapper: ClassVar[int] = 0x100
    _off_tbt_root_draw_wrapper: ClassVar[int] = 0x900
    _off_tbt_center_wrapper: ClassVar[int] = 0xB00
    _off_tbt_center_wrapper_limit: ClassVar[int] = 0xC00
    _off_tbt_overlay_draw: ClassVar[int] = 0xE00
    _off_tbt_border_draw: ClassVar[int] = 0x1000
    # The map root wrapper owns a complete physical damage transaction; keep it
    # in the otherwise unused tail instead of squeezing it into the
    # historical 0x920--0x980 slot.  Explicit slot bounds make future growth
    # fail closed during patch construction rather than corrupting a peer.
    _off_driving_map_draw_wrapper: ClassVar[int] = 0x1210
    _off_driving_map_destructor_wrapper: ClassVar[int] = 0x1500
    # Marker fitting needs two temporary raster dimensions and an exact hidden
    # sentinel proof. Give that bounded helper the remaining resource-code page
    # instead of byte-packing it beside unrelated retained state.
    _off_driving_map_ellipse_wrapper: ClassVar[int] = 0x1600
    _off_tbt_resource: ClassVar[int] = 0xC00
    _off_tbt_surface: ClassVar[int] = 0xC04
    _off_tbt_transform_count: ClassVar[int] = 0xC08
    _off_tbt_background_count: ClassVar[int] = 0xC0C
    _off_tbt_logical_rect: ClassVar[int] = TIMEBLOCK_LOGICAL_RECT_OFFSET
    _off_tbt_target_rect: ClassVar[int] = TIMEBLOCK_TARGET_RECT_OFFSET
    # Physical bitmap dimensions determine sampling and authored presentation.
    # Draw separately preserves each model's extents: original saves can carry
    # authored bounds while a newly constructed model carries dense bounds.
    _off_tbt_raw_width: ClassVar[int] = 0xC30
    _off_tbt_raw_height: ClassVar[int] = TIMEBLOCK_RAW_HEIGHT_OFFSET
    _off_tbt_dest_rect: ClassVar[int] = 0xC38
    _off_tbt_layer: ClassVar[int] = TIMEBLOCK_LAYER_OFFSET
    _off_tbt_draw_scope_active: ClassVar[int] = 0xC4C
    _off_tbt_clear_flip_count: ClassVar[int] = 0xC50
    # GK3 owns the map root. Retain its draw counter and formerly published
    # generation fields as one stable diagnostic ABI; the exact vtable wrapper
    # now supplies complete damage synchronously on every live map draw.
    _off_driving_map_children_scaled: ClassVar[int] = 0xEB4
    _off_driving_map_ellipse_count: ClassVar[int] = 0xEB8
    _off_driving_map_full_draw_count: ClassVar[int] = 0xEBC
    _off_driving_map_root_this: ClassVar[int] = 0xEC0
    _off_driving_map_root_this_candidate: ClassVar[int] = 0xEC4
    _off_driving_map_child_rect_count: ClassVar[int] = 0xEC8
    _off_driving_map_child_rects: ClassVar[int] = 0x1000
    _off_driving_map_source_grid_rect: ClassVar[int] = 0x1100
    _off_progress_draw_depth: ClassVar[int] = RESOURCE_PROGRESS_DRAW_DEPTH_OFFSET
    _off_progress_transform_count: ClassVar[int] = RESOURCE_PROGRESS_TRANSFORM_COUNT_OFFSET
    # TimeBlock's native tree submits bottom controls separately from its
    # recurring dense background. Retain the exact logical union plus the two
    # derived affine rectangles so only those controls are protected from the
    # later opaque transfer; this replaces the former full-width 45-row crop.
    _off_tbt_control_seen: ClassVar[int] = 0xC54
    _off_tbt_control_logical_rect: ClassVar[int] = 0xC58
    _off_tbt_control_source_rect: ClassVar[int] = 0xC68
    _off_tbt_control_target_rect: ClassVar[int] = 0xC78
    _off_tbt_control_replay_count: ClassVar[int] = 0xC88
    _off_tbt_clear_budget: ClassVar[int] = 0xC8C
    _off_tbt_clear_count: ClassVar[int] = 0xC90
    _off_tbt_cursor_bypass_count: ClassVar[int] = 0xC94
    _off_tbt_handled_flag: ClassVar[int] = 0xC98
    _off_tbt_handled_result: ClassVar[int] = 0xC9C
    _off_tbt_source_rect: ClassVar[int] = 0xCA0
    _off_tbt_control_count: ClassVar[int] = 0xCB0
    _off_tbt_bltfx: ClassVar[int] = 0xD00
    _off_tbt_control_slots: ClassVar[int] = 0xD80
    _fingerprint_blit_wrapper_offset: ClassVar[int] = 0x200
    _fingerprint_resource_probe_wrapper_offset: ClassVar[int] = 0x900
    _system_blit_wrapper_offset: ClassVar[int] = 0x300
    _ddbltfx_size: ClassVar[int] = 0x64
    _ddblt_colorfill_wait: ClassVar[int] = 0x01000400
    # These are the only original final-blitter mutations owned by this patch.
    # Optional fingerprint and system behavior is composed across their
    # semantic runtime segments and
    # selected below; no extension patch installs a second call-site hook.
    _call_site_names: ClassVar[tuple[str, ...]] = (
        "runtime2d.final_blt_call_1",
        "runtime2d.final_blt_call_2",
        # Equal-size fast path used by several fixed-pixel UI surfaces.
        "runtime2d.final_blt_call_3",
    )
    # Drawable Draw methods receive a 16-bit destination bitmap handle.  This
    # manager resolves it to the same surface wrapper consumed by GK3's native
    # DirectDraw blitter (FUN_00534560 is the stock lookup helper).
    _museum_resource_prefix: ClassVar[bytes] = b"MS3I"

    # TimeBlockLayer owns a unique root Draw override.  Hooking its vtable slot
    # is the narrow timing boundary needed to clear stale room pixels without
    # constraining the field of view of ordinary 3D rooms.
    @property
    def _call_sites(self) -> tuple[tuple[int, bytes], ...]:
        return tuple(
            (site.va, site.original)
            for name in self._call_site_names
            for site in (self.profile.site(name),)
        )

    def _site_va(self, name: str) -> int:
        return self.profile.site(name).va

    def _site_bytes(self, name: str) -> bytes:
        return self.profile.site(name).original

    @property
    def _native_blt_va(self) -> int:
        return self.profile.address("runtime2d.final_blt")

    @property
    def _native_blt_trampoline_va(self) -> int:
        """Return the canonical native path that bypasses our public hook."""
        return self.symbols.va(
            SIDNEY_PRESENTATION_SEGMENT.logical_name,
            SIDNEY_NATIVE_BLT_TRAMPOLINE_OFFSET,
        )

    @property
    def _physical_width_va(self) -> int:
        return self.profile.address("display.dimensions")

    @property
    def _closeup_center_call_va(self) -> int:
        return self._site_va("runtime2d.closeup_center_call")

    @property
    def _closeup_center_original(self) -> bytes:
        return self._site_bytes("runtime2d.closeup_center_call")

    @property
    def _native_center_va(self) -> int:
        return self.profile.address("ui.center_drawable")

    @property
    def _resource_manager_va(self) -> int:
        return self.profile.address("resource.manager")

    @property
    def _bitmap_surface_manager_va(self) -> int:
        return self.profile.address("engine.loop")

    @property
    def _resolve_bitmap_resource_va(self) -> int:
        return self.profile.address("bitmap.resolve_resource")

    @property
    def _bitmap_entry_va(self) -> int:
        return self._site_va("bitmap.drawable_entry")

    @property
    def _bitmap_entry_original(self) -> bytes:
        return self._site_bytes("bitmap.drawable_entry")

    @property
    def _driving_map_draw_slot_va(self) -> int:
        return self.profile.address("driving_map.vtable") + 0xA0

    @property
    def _bitmap_node_destructor_slot_va(self) -> int:
        return self.profile.address("bitmap_node.destructor_slot")

    @property
    def _bitmap_node_destructor_original_va(self) -> int:
        return self.profile.address("bitmap_node.destructor")

    @property
    def _driving_map_ellipse_call_va(self) -> int:
        return self._site_va("driving_map.ellipse_call")

    @property
    def _driving_map_ellipse_call_original(self) -> bytes:
        return self._site_bytes("driving_map.ellipse_call")

    @property
    def _ellipse_iat_va(self) -> int:
        return self.profile.address("win32.Ellipse")

    @property
    def _tbt_center_call_va(self) -> int:
        return self._site_va("timeblock.center_call")

    @property
    def _tbt_center_call_original(self) -> bytes:
        return self._site_bytes("timeblock.center_call")

    @property
    def _tbt_vtable_va(self) -> int:
        return self.profile.address("timeblock.vtable")

    @property
    def _tbt_draw_slot_va(self) -> int:
        return self._tbt_vtable_va + 0xA0

    @property
    def _tbt_draw_original_va(self) -> int:
        return self.profile.address("timeblock.draw")

    @property
    def _screen_rect_ptr_va(self) -> int:
        return self.profile.address("ui.screen_rect_ptr")

    # Resource dimensions describe the exact 4x replacement pack; they are not
    # output-mode branches. Presentation always derives from GK3's live width
    # and height after these source surfaces regain their authored dimensions.
    _replacement_scale: ClassVar[int] = 4
    _reference_height: ClassVar[int] = AUTHORED_FRAME_HEIGHT
    _replacement_reference_height: ClassVar[int] = _reference_height * _replacement_scale
    _fixed_screen_width: ClassVar[int] = 640
    _fixed_screen_height: ClassVar[int] = 480
    _replacement_screen_width: ClassVar[int] = _fixed_screen_width * _replacement_scale
    _replacement_screen_height: ClassVar[int] = _fixed_screen_height * _replacement_scale
    # TBT306P is the one 640x481 background, both constructed and restored.
    _tall_tbt_background_height: ClassVar[int] = _replacement_screen_height + _replacement_scale
    # CloseUpLayer's stock presentation never exceeds GK3's authored 640x480
    # canvas. The supported replacement pack is exactly 4x, but individual
    # evidence objects preserve their own aspect ratio and therefore range
    # from narrow documents to nearly full-screen art. Classifying only the
    # largest replacements (the former 2200x1400 floor) silently enlarged
    # stock art whenever a valid narrower 4x source was selected.
    _closeup_stock_max_width: ClassVar[int] = _fixed_screen_width
    _closeup_stock_max_height: ClassVar[int] = _fixed_screen_height
    _closeup_max_width: ClassVar[int] = _replacement_screen_width
    _closeup_max_height: ClassVar[int] = _replacement_screen_height
    _progress_width: ClassVar[int] = RESTORE_PROGRESS_LOGICAL_WIDTH * _replacement_scale
    _progress_height: ClassVar[int] = RESTORE_PROGRESS_LOGICAL_HEIGHT * _replacement_scale
    _slider_width: ClassVar[int] = 2176
    _slider_height: ClassVar[int] = 1784

    def _fingerprint_blit_target_va(self) -> int:
        """Resolve the fingerprint compositor through the exported runtime ABI."""
        return self.symbols.va(
            FINGERPRINT_SEGMENT.logical_name, self._fingerprint_blit_wrapper_offset
        )

    def _outer_blit_target_va(self) -> int:
        """Resolve the sole outer system-screen dispatcher."""
        return self.symbols.va(SYSTEM_SEGMENT.logical_name, self._system_blit_wrapper_offset)

    def _bitmap_resource_resolver_target_va(self) -> int:
        """Resolve the fingerprint-aware bitmap lookup wrapper."""
        return self.symbols.va(
            FINGERPRINT_SEGMENT.logical_name,
            self._fingerprint_resource_probe_wrapper_offset,
        )

    def precheck(self, pe: PEFile) -> None:
        """Validate semantic predecessors before atomic clone compilation.

        The native mutation plan in :meth:`apply` is the single source of
        truth for every owned byte/pointer site. ``Runtime2DCompiler`` executes
        this feature on a disposable image first, so duplicating those exact
        checks here could only drift from the transaction it was meant to
        protect. The Ellipse import remains a distinct semantic dependency:
        its IAT target is consumed by generated code but is not itself mutated.
        """
        if any(
            pe.get_section(name) is not None
            for name in (self._section_name, self._timeblock_section_name)
        ):
            msg = f"{self.id} requires pristine resource and TimeBlock segments"
            raise PatchError(msg)
        ellipse_iat_rva = pe.find_import_iat_rva("GDI32.dll", "Ellipse")
        if ellipse_iat_rva is None or pe.rva_to_va(ellipse_iat_rva) != self._ellipse_iat_va:
            msg = f"{self.id} precheck failed: unexpected Ellipse import"
            raise PatchError(msg)

    def apply(self, pe: PEFile) -> None:
        """Emit resource classifiers, transforms, and scoped draw wrappers."""
        section = install_runtime_segment(pe, RESOURCE_SEGMENT)
        timeblock_section = install_runtime_segment(pe, TIMEBLOCK_SEGMENT)

        section_offset = section.pointer_to_raw_data
        section_va = pe.rva_to_va(section.virtual_address)
        timeblock_section_offset = timeblock_section.pointer_to_raw_data
        timeblock_section_va = pe.rva_to_va(timeblock_section.virtual_address)
        wrapper_va = section_va + self._off_wrapper
        closeup_tag_wrapper_va = section_va + self._off_closeup_tag_wrapper
        tbt_blit_wrapper_va = timeblock_section_va + self._off_tbt_blit_wrapper
        # All peers are resolved through RuntimeSymbols before assembly, so
        # this central dispatcher is emitted once with its final call chain.
        wrapper = build_resource_blit_dispatcher(
            self,
            wrapper_va=wrapper_va,
            dest_rect_va=section_va + self._off_dest_rect,
            source_rect_va=section_va + self._off_source_rect,
            slider_trace_count_va=section_va + self._off_slider_trace_count,
            slider_last_record_va=section_va + self._off_slider_last_record,
            slider_transform_count_va=section_va + self._off_slider_transform_count,
            closeup_transform_count_va=section_va + self._off_closeup_transform_count,
            closeup_raw_width_va=section_va + self._off_closeup_raw_width,
            closeup_raw_height_va=section_va + self._off_closeup_raw_height,
            closeup_target_width_va=section_va + self._off_closeup_target_width,
            closeup_target_height_va=section_va + self._off_closeup_target_height,
            closeup_rect_va=section_va + self._off_closeup_rect,
            closeup_active_surface_va=section_va + self._off_closeup_active_surface,
            museum_surface_va=section_va + self._off_museum_surface,
            closeup_observed_source_va=section_va + self._off_closeup_observed_source,
            resource_lookup_active_va=section_va + self._off_resource_lookup_active,
            progress_draw_depth_va=section_va + self._off_progress_draw_depth,
            progress_transform_count_va=section_va + self._off_progress_transform_count,
            driving_map_surface_va=section_va + self._off_bitmap_probe_surface,
            driving_map_transform_count_va=(section_va + self._off_driving_map_transform_count),
            driving_map_rect_va=section_va + self._off_driving_map_rect,
            driving_map_scope_active_va=section_va + self._off_driving_map_scope_active,
            driving_map_seen_va=section_va + self._off_driving_map_seen,
            driving_map_child_rect_count_va=(section_va + self._off_driving_map_child_rect_count),
            driving_map_child_rects_va=section_va + self._off_driving_map_child_rects,
            driving_map_source_grid_rect_va=section_va + self._off_driving_map_source_grid_rect,
            tbt_blit_wrapper_va=tbt_blit_wrapper_va,
            tbt_handled_flag_va=timeblock_section_va + self._off_tbt_handled_flag,
            tbt_handled_result_va=timeblock_section_va + self._off_tbt_handled_result,
            fingerprint_blit_wrapper_va=self._fingerprint_blit_target_va(),
        )
        if self._off_wrapper + len(wrapper) > self._off_bitmap_entry_probe:
            msg = f"{self.id} wrapper overlaps its bitmap-entry probe"
            raise PatchError(msg)
        closeup_tag_wrapper = build_closeup_identity_tag(
            self,
            wrapper_va=closeup_tag_wrapper_va,
            active_handle_va=section_va + self._off_closeup_active_handle,
            active_surface_va=section_va + self._off_closeup_active_surface,
            museum_surface_va=section_va + self._off_museum_surface,
            closeup_sprite_va=section_va + self._off_closeup_sprite,
            resource_lookup_active_va=section_va + self._off_resource_lookup_active,
        )
        bitmap_entry_probe_va = section_va + self._off_bitmap_entry_probe
        bitmap_entry_probe = build_bitmap_identity_probe(
            self,
            wrapper_va=bitmap_entry_probe_va,
            resource_va=section_va + self._off_bitmap_probe_resource,
            child_va=section_va + self._off_bitmap_probe_child,
            handle_va=section_va + self._off_bitmap_probe_handle,
            surface_va=section_va + self._off_bitmap_probe_surface,
            driving_map_input_active_va=(section_va + self._off_driving_map_input_active),
            resource_lookup_active_va=section_va + self._off_resource_lookup_active,
            tbt_resource_va=timeblock_section_va + self._off_tbt_resource,
            tbt_surface_va=timeblock_section_va + self._off_tbt_surface,
            museum_surface_va=section_va + self._off_museum_surface,
            resolve_bitmap_resource_target_va=self._bitmap_resource_resolver_target_va(),
        )
        driving_map_draw_wrapper_va = section_va + self._off_driving_map_draw_wrapper
        driving_map_draw_wrapper = build_driving_map_draw_scope(
            self,
            wrapper_va=driving_map_draw_wrapper_va,
            system_render_state_vas=(
                self.symbols.va(SYSTEM_SEGMENT.logical_name, SYSTEM_TRANSFORM_MODE_OFFSET),
                self.symbols.va(SYSTEM_SEGMENT.logical_name, SYSTEM_RENDER_DEPTH_OFFSET),
                self.symbols.va(SYSTEM_SEGMENT.logical_name, SYSTEM_INPUT_ACTIVE_OFFSET),
            ),
            scope_active_va=section_va + self._off_driving_map_scope_active,
            input_active_va=section_va + self._off_driving_map_input_active,
            base_child_va=section_va + self._off_bitmap_probe_child,
            children_scaled_va=section_va + self._off_driving_map_children_scaled,
            child_rect_count_va=section_va + self._off_driving_map_child_rect_count,
            child_rects_va=section_va + self._off_driving_map_child_rects,
            full_draw_count_va=section_va + self._off_driving_map_full_draw_count,
            full_damage_region_va=self.symbols.va(
                SYSTEM_CONTROL_SEGMENT.logical_name,
                SYSTEM_CONTROL_FULL_DAMAGE_REGION_OFFSET,
            ),
            full_damage_rect_va=self.symbols.va(
                SYSTEM_CONTROL_SEGMENT.logical_name,
                SYSTEM_CONTROL_FULL_DAMAGE_RECT_OFFSET,
            ),
        )
        driving_map_destructor_wrapper_va = section_va + self._off_driving_map_destructor_wrapper
        driving_map_destructor_wrapper = build_driving_map_destructor(
            self,
            wrapper_va=driving_map_destructor_wrapper_va,
            child_va=section_va + self._off_bitmap_probe_child,
            resource_va=section_va + self._off_bitmap_probe_resource,
            surface_va=section_va + self._off_bitmap_probe_surface,
            input_active_va=section_va + self._off_driving_map_input_active,
            children_scaled_va=section_va + self._off_driving_map_children_scaled,
            child_rect_count_va=section_va + self._off_driving_map_child_rect_count,
            ellipse_count_va=section_va + self._off_driving_map_ellipse_count,
            root_this_va=section_va + self._off_driving_map_root_this,
        )
        driving_map_ellipse_wrapper_va = section_va + self._off_driving_map_ellipse_wrapper
        driving_map_ellipse_wrapper = build_driving_map_marker_ellipse(
            self,
            scope_active_va=section_va + self._off_driving_map_scope_active,
            input_active_va=section_va + self._off_driving_map_input_active,
            ellipse_count_va=section_va + self._off_driving_map_ellipse_count,
        )
        tbt_blit_wrapper = build_timeblock_blit(
            self,
            wrapper_va=tbt_blit_wrapper_va,
            tbt_surface_va=timeblock_section_va + self._off_tbt_surface,
            transform_count_va=timeblock_section_va + self._off_tbt_transform_count,
            background_count_va=timeblock_section_va + self._off_tbt_background_count,
            logical_rect_va=timeblock_section_va + self._off_tbt_logical_rect,
            target_rect_va=timeblock_section_va + self._off_tbt_target_rect,
            dest_rect_va=timeblock_section_va + self._off_tbt_dest_rect,
            source_rect_va=timeblock_section_va + self._off_tbt_source_rect,
            control_seen_va=timeblock_section_va + self._off_tbt_control_seen,
            control_logical_rect_va=(timeblock_section_va + self._off_tbt_control_logical_rect),
            control_source_rect_va=(timeblock_section_va + self._off_tbt_control_source_rect),
            control_target_rect_va=(timeblock_section_va + self._off_tbt_control_target_rect),
            control_replay_count_va=(timeblock_section_va + self._off_tbt_control_replay_count),
            control_count_va=timeblock_section_va + self._off_tbt_control_count,
            control_slots_va=timeblock_section_va + self._off_tbt_control_slots,
            handled_flag_va=timeblock_section_va + self._off_tbt_handled_flag,
            handled_result_va=timeblock_section_va + self._off_tbt_handled_result,
            layer_va=timeblock_section_va + self._off_tbt_layer,
            draw_scope_active_va=timeblock_section_va + self._off_tbt_draw_scope_active,
            cursor_state_va=self.symbols.va(
                SYSTEM_CONTROL_SEGMENT.logical_name,
                SYSTEM_CONTROL_CURSOR_STATE_OFFSET,
            ),
            cursor_bypass_count_va=(timeblock_section_va + self._off_tbt_cursor_bypass_count),
        )
        tbt_root_draw_wrapper_va = timeblock_section_va + self._off_tbt_root_draw_wrapper
        tbt_overlay_draw_va = timeblock_section_va + self._off_tbt_overlay_draw
        tbt_root_draw_wrapper = build_timeblock_root_draw(
            self,
            wrapper_va=tbt_root_draw_wrapper_va,
            overlay_draw_va=tbt_overlay_draw_va,
            clear_budget_va=timeblock_section_va + self._off_tbt_clear_budget,
            clear_count_va=timeblock_section_va + self._off_tbt_clear_count,
            bltfx_va=timeblock_section_va + self._off_tbt_bltfx,
            clear_flip_count_va=timeblock_section_va + self._off_tbt_clear_flip_count,
            successful_flip_count_va=self.transition_abi.successful_flip_count_va,
            layer_va=timeblock_section_va + self._off_tbt_layer,
            draw_scope_active_va=timeblock_section_va + self._off_tbt_draw_scope_active,
            raw_width_va=timeblock_section_va + self._off_tbt_raw_width,
            raw_height_va=timeblock_section_va + self._off_tbt_raw_height,
            control_seen_va=timeblock_section_va + self._off_tbt_control_seen,
            control_count_va=timeblock_section_va + self._off_tbt_control_count,
        )
        tbt_center_wrapper_va = timeblock_section_va + self._off_tbt_center_wrapper
        tbt_center_wrapper = build_timeblock_center(
            self,
            wrapper_va=tbt_center_wrapper_va,
            layer_va=timeblock_section_va + self._off_tbt_layer,
            clear_budget_va=timeblock_section_va + self._off_tbt_clear_budget,
            raw_width_va=timeblock_section_va + self._off_tbt_raw_width,
            raw_height_va=timeblock_section_va + self._off_tbt_raw_height,
            control_seen_va=timeblock_section_va + self._off_tbt_control_seen,
            control_count_va=timeblock_section_va + self._off_tbt_control_count,
        )
        payload = SegmentPayloadBuilder(
            owner=self.id,
            segment=RESOURCE_SEGMENT.logical_name,
            size=RESOURCE_SEGMENT.size,
        )
        payload.place(label="magic", offset=0, payload=self._magic)
        payload.place(
            label="layout version",
            offset=self._off_layout_version,
            payload=struct.pack("<I", self._layout_version),
        )
        payload.reserve(label="blit rectangles", offset=self._off_dest_rect, size=32)
        payload.reserve(label="slider trace", offset=self._off_slider_trace_count, size=48)
        payload.reserve(
            label="slider transform count",
            offset=self._off_slider_transform_count,
            size=4,
        )
        payload.reserve(
            label="close-up and resource state",
            offset=self._off_closeup_transform_count,
            size=0x50,
        )
        for label, offset, code, limit in (
            ("resource blitter", self._off_wrapper, wrapper, self._off_bitmap_entry_probe),
            (
                "driving-map source grid",
                self._off_driving_map_source_grid_rect,
                build_source_grid_rect(physical_width_va=self._physical_width_va),
                self._off_driving_map_draw_wrapper,
            ),
            (
                "bitmap identity probe",
                self._off_bitmap_entry_probe,
                bitmap_entry_probe,
                self._off_bitmap_entry_probe_limit,
            ),
            (
                "driving-map draw",
                self._off_driving_map_draw_wrapper,
                driving_map_draw_wrapper,
                self._off_driving_map_destructor_wrapper,
            ),
            (
                "driving-map destructor",
                self._off_driving_map_destructor_wrapper,
                driving_map_destructor_wrapper,
                self._off_driving_map_ellipse_wrapper,
            ),
            (
                "driving-map Ellipse",
                self._off_driving_map_ellipse_wrapper,
                driving_map_ellipse_wrapper,
                self._off_closeup_tag_wrapper,
            ),
            (
                "close-up identity tag",
                self._off_closeup_tag_wrapper,
                closeup_tag_wrapper,
                self._off_closeup_tag_wrapper_limit,
            ),
        ):
            payload.place(label=label, offset=offset, payload=code, limit=limit)
        payload.reserve(
            label="bitmap and fitted-resource state",
            offset=self._off_bitmap_probe_resource,
            size=0xAC,
        )
        payload.reserve(
            label="driving-map model and draw diagnostics",
            offset=self._off_driving_map_children_scaled,
            size=24,
        )
        payload.reserve(
            label="driving-map child rectangles",
            offset=self._off_driving_map_child_rects,
            size=0x100,
        )
        payload.reserve(
            label="Restore progress state",
            offset=self._off_progress_draw_depth,
            size=8,
        )
        pe.write_bytes(section_offset, payload.build())

        # TimeBlock is a cohesive subfeature with enough generated code and
        # retained state to warrant its own bounded runtime page.  Keeping its
        # state beside its wrappers also makes out-of-process diagnostics use
        # one unambiguous ABI base.
        timeblock_payload = SegmentPayloadBuilder(
            owner=f"{self.id}.timeblock",
            segment=TIMEBLOCK_SEGMENT.logical_name,
            size=TIMEBLOCK_SEGMENT.size,
        )
        timeblock_payload.place(label="magic", offset=0, payload=TIMEBLOCK_SEGMENT.magic)
        timeblock_payload.place(
            label="TimeBlock overlay draw",
            offset=self._off_tbt_overlay_draw,
            payload=build_overlay_draw(
                wrapper_va=tbt_overlay_draw_va,
                native_draw_va=timeblock_section_va + self._off_tbt_border_draw,
                sequence_vtable_va=self.profile.address("sequence.series_vtable"),
                surface_va=timeblock_section_va + TIMEBLOCK_OVERLAY_SURFACE_OFFSET,
                manager_va=self._bitmap_surface_manager_va,
                resolve_va=self._resolve_bitmap_resource_va,
            ),
            limit=self._off_tbt_border_draw,
        )
        timeblock_payload.place(
            label="TimeBlock physical surround",
            offset=self._off_tbt_border_draw,
            payload=build_border_draw(
                wrapper_va=timeblock_section_va + self._off_tbt_border_draw,
                native_draw_va=self._tbt_draw_original_va,
                screen_size_va=self._physical_width_va,
                target_rect_va=timeblock_section_va + self._off_tbt_target_rect,
                raw_height_va=timeblock_section_va + self._off_tbt_raw_height,
            ),
            limit=TIMEBLOCK_SEGMENT.size,
        )
        timeblock_payload.place(
            label="layout version",
            offset=self._off_layout_version,
            payload=struct.pack("<I", self._timeblock_layout_version),
        )
        for label, offset, code, limit in (
            (
                "TimeBlock blitter",
                self._off_tbt_blit_wrapper,
                tbt_blit_wrapper,
                self._off_tbt_root_draw_wrapper,
            ),
            (
                "TimeBlock root draw",
                self._off_tbt_root_draw_wrapper,
                tbt_root_draw_wrapper,
                self._off_tbt_center_wrapper,
            ),
            (
                "TimeBlock center",
                self._off_tbt_center_wrapper,
                tbt_center_wrapper,
                self._off_tbt_center_wrapper_limit,
            ),
        ):
            timeblock_payload.place(label=label, offset=offset, payload=code, limit=limit)
        timeblock_payload.reserve(
            label="TimeBlock model and presentation state",
            offset=self._off_tbt_resource,
            size=0x54,
        )
        timeblock_payload.reserve(
            label="TimeBlock control-partition state",
            offset=self._off_tbt_control_seen,
            size=0x38,
        )
        timeblock_payload.reserve(
            label="TimeBlock clear and cursor counters",
            offset=self._off_tbt_clear_budget,
            size=12,
        )
        timeblock_payload.reserve(
            label="TimeBlock handled-call state",
            offset=self._off_tbt_handled_flag,
            size=8,
        )
        timeblock_payload.reserve(
            label="TimeBlock private source rectangle",
            offset=self._off_tbt_source_rect,
            size=16,
        )
        timeblock_payload.reserve(
            label="TimeBlock control count",
            offset=self._off_tbt_control_count,
            size=4,
        )
        timeblock_payload.reserve(
            label="TimeBlock current overlay surface",
            offset=TIMEBLOCK_OVERLAY_SURFACE_OFFSET,
            size=4,
        )
        # DDBLTFX is a 0x64-byte ABI structure.  Only dwSize and dwFillColor
        # (already zero) are needed for DDBLT_COLORFILL|DDBLT_WAIT.
        tbt_bltfx = bytearray(self._ddbltfx_size)
        struct.pack_into("<I", tbt_bltfx, 0, self._ddbltfx_size)
        timeblock_payload.place(
            label="TimeBlock fill descriptor",
            offset=self._off_tbt_bltfx,
            payload=bytes(tbt_bltfx),
        )
        timeblock_payload.reserve(
            label="TimeBlock exact control replay slots",
            offset=self._off_tbt_control_slots,
            size=0x50,
        )
        pe.write_bytes(timeblock_section_offset, timeblock_payload.build())

        # System screens, when installed, are the outer scope classifier; they
        # tail into this HD dispatcher for resource-specific transforms.
        outer_wrapper_va = self._outer_blit_target_va()
        mutations = ExecutableMutationPlan(owner=self.id)
        for index, (site_va, original) in enumerate(self._call_sites, start=1):
            mutations.branch(
                label=f"final blitter call {index}",
                opcode=BranchOpcode.CALL,
                site_va=site_va,
                expected=original,
                target_va=outer_wrapper_va,
                size=len(original),
            )
        mutations.branch(
            label="close-up centering",
            opcode=BranchOpcode.CALL,
            site_va=self._closeup_center_call_va,
            expected=self._closeup_center_original,
            target_va=closeup_tag_wrapper_va,
            size=len(self._closeup_center_original),
        )
        mutations.branch(
            label="bitmap identity probe",
            opcode=BranchOpcode.JUMP,
            site_va=self._bitmap_entry_va,
            expected=self._bitmap_entry_original,
            target_va=bitmap_entry_probe_va,
            size=len(self._bitmap_entry_original),
        )
        mutations.pointer(
            label="driving-map draw",
            slot_va=self._driving_map_draw_slot_va,
            expected=self.profile.address("ui.container_draw"),
            target_va=driving_map_draw_wrapper_va,
        )
        # Correct the constructor, not the final blit: the same node then owns
        # aligned unlit/highlight art, hit testing and location transitions.
        # These original opaque crops match DM_BASE exactly at these origins.
        correct_location_origins(mutations, self.profile)
        mutations.pointer(
            label="driving-map destructor",
            slot_va=self._bitmap_node_destructor_slot_va,
            expected=self._bitmap_node_destructor_original_va,
            target_va=driving_map_destructor_wrapper_va,
        )
        # Keep the original six-byte call-site footprint.  The wrapper's IAT
        # tail jump preserves the native imported function and stack cleanup.
        mutations.branch(
            label="driving-map Ellipse",
            opcode=BranchOpcode.CALL,
            site_va=self._driving_map_ellipse_call_va,
            expected=self._driving_map_ellipse_call_original,
            target_va=driving_map_ellipse_wrapper_va,
            size=len(self._driving_map_ellipse_call_original),
        )
        mutations.branch(
            label="TimeBlock centering",
            opcode=BranchOpcode.CALL,
            site_va=self._tbt_center_call_va,
            expected=self._tbt_center_call_original,
            target_va=tbt_center_wrapper_va,
            size=len(self._tbt_center_call_original),
        )
        # Redirect only TimeBlockLayer's own Draw slot.  The base Draw method
        # remains untouched for rooms and every other 2D interface class.
        mutations.pointer(
            label="TimeBlock root draw",
            slot_va=self._tbt_draw_slot_va,
            expected=self._tbt_draw_original_va,
            target_va=tbt_root_draw_wrapper_va,
        )
        mutations.apply(pe)

    def postcheck(self, pe: PEFile) -> None:
        """Require this owner's segment after deterministic compilation.

        :class:`Runtime2DCompiler` independently rebuilds every logical segment
        and executable redirect, then compares the complete installed image.
        Reconstructing each resource wrapper again here duplicated that generic
        proof and let verification drift into a second implementation.
        """
        if any(
            pe.get_section(name) is None
            for name in (self._section_name, self._timeblock_section_name)
        ):
            msg = f"{self.id} postcheck failed: resource or TimeBlock segment missing"
            raise PatchError(msg)
