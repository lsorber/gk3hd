"""Compile the sole shared final-2D-blit dispatcher."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.geometry import AUTHORED_FRAME_HEIGHT, AUTHORED_FRAME_WIDTH
from gk3hd.patch.definitions.runtime2d.layout import (
    BINOCULAR_SEGMENT,
    BINOCULAR_SOURCE_HELPER_OFFSET,
    CONSOLE_SEGMENT,
    CONSOLE_TRANSFER_OFFSET,
    FINGERPRINT_LAYOUT_ACTIVE_OFFSET,
    FINGERPRINT_SEGMENT,
    FINGERPRINT_TOOL_MATCH_OFFSET,
    FONT_BANK_SEGMENT,
    FONT_BANK_SOURCE_GUARD_OFFSET,
    GPS_SEGMENT,
    GPS_TRANSFER_OFFSET,
    INVENTORY_NAVIGATION_SEGMENT,
    INVENTORY_NAVIGATION_SOURCE_OFFSET,
    SIDNEY_NATIVE_BLT_TRAMPOLINE_OFFSET,
    SIDNEY_PRESENTATION_SEGMENT,
    UI_FRAMES_SEGMENT,
    UI_FRAMES_SOURCE_OFFSET,
)
from gk3hd.patch.definitions.runtime2d.system.shared import SystemCompilerContext


@dataclass(frozen=True, slots=True, kw_only=True)
class BlitDispatchCompiler(SystemCompilerContext):
    """Dispatch final 2D transfers by explicit feature ownership.

    Outcome:
        Every fixed-interface transfer is transformed exactly once while native,
        cursor-owned, and already-physical transfers pass through unchanged.
    Before:
        GK3 funnels unrelated roots, cursor save-under, fonts, resources, and
        delayed damage through the same final blitter without a coordinate tag.
    After:
        Concrete lifetime, class, surface, and resource state selects one named
        feature policy; ambiguous transfers fail closed to the native call.
    Strategy:
        Install one dispatcher at the shared entry and call feature-owned helpers
        rather than stacking per-screen redirects or output-size heuristics.
    Boundaries:
        This owner classifies and routes transfers only. Feature geometry, input,
        page presentation, and resource recognition remain with their owners.
    """

    def build_blt_wrapper(
        self,
        *,
        wrapper_va: int,
        downstream_va: int,
        render_depth_va: int,
        input_active_va: int,
        transform_mode_va: int,
        root_ptr_va: int,
        clear_pending_va: int,
        transform_count_va: int,
        composite_surface_va: int,
        source_rect_va: int,
        target_rect_va: int,
        dest_rect_va: int,
        bltfx_va: int,
        left_bar_rect_va: int,
        right_bar_rect_va: int,
        hud_font_active_va: int,
        hud_font_point_va: int,
        hud_transform_count_va: int,
        hud_last_rect_va: int,
        hd_font_active_va: int,
        hd_font_source_rect_va: int,
        hd_font_source_transform_count_va: int,
        toolbar_blt_helper_va: int,
        loadsave_background_helper_va: int,
        cursor_surface_classifier_va: int,
        tooltip_draw_depth_va: int,
        tooltip_transfer_affine_va: int,
        binocs_local_blt_helper_va: int,
    ) -> bytes:
        """Build the one final-blit classifier installed at GK3's shared sink."""
        # Entry matches the shared HD blitter's thiscall arguments.  PUSHAD
        # leaves saved ECX (the destination wrapper) at +18 and destination
        # RECT* at +28.
        code = X86Emitter(base_va=wrapper_va)
        code.call_absolute(self.symbols.va(UI_FRAMES_SEGMENT.logical_name, UI_FRAMES_SOURCE_OFFSET))
        # Native scrollbar composition can enter here without SIDNEY's outer
        # hook. Normalize tagged navigation sources once at this shared sink.
        code.call_absolute(
            self.symbols.va(
                INVENTORY_NAVIGATION_SEGMENT.logical_name, INVENTORY_NAVIGATION_SOURCE_OFFSET
            )
        )
        code += b"\x60"
        code.call_absolute(
            self.symbols.va(BINOCULAR_SEGMENT.logical_name, BINOCULAR_SOURCE_HELPER_OFFSET)
        )

        # CursorManager can synchronously restore its private save-under or
        # submit its cursor while any system-layer root is traversing. Those
        # transfers already use physical coordinates and are fully owned by
        # CursorManager. Exact learned surface identity is therefore the whole
        # policy: bypass every fixed-interface transform and preserve GK3's
        # native save-under/draw ordering at every output resolution.
        code += b"\x8b\x4c\x24\x18"
        code += b"\x8b\x54\x24\x24"
        code += b"\x8b\x74\x24\x28"
        code.call_absolute(cursor_surface_classifier_va)
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "after_cursor_surface")
        code.jump("native")
        code.label("after_cursor_surface")

        # Fingerprint's moving tool is a UI image, not CursorManager. Its owner
        # handles native/dense extents and final clipping downstream. Do not let
        # the generic popup affine enlarge a native source's clipped fragment
        # first: that loses the original anchor and can exceed display bounds.
        code.raw(
            b"\x83\x3d"
            + struct.pack(
                "<I",
                self.symbols.va(FINGERPRINT_SEGMENT.logical_name, FINGERPRINT_LAYOUT_ACTIVE_OFFSET),
            )
            + b"\x01"
        )
        code.jump_if(Condition.NOT_EQUAL, "after_fingerprint_tool")
        code.raw(b"\x8b\x44\x24\x24")
        code.call_absolute(
            self.symbols.va(FINGERPRINT_SEGMENT.logical_name, FINGERPRINT_TOOL_MATCH_OFFSET)
        )
        code.jump_if(Condition.BELOW, "native")
        code.label("after_fingerprint_tool")

        # A source-faithful 4x raster atlas retains logical GK3 metrics while
        # its source coordinates are exactly four times denser. The
        # synchronous high-level glyph scope selects only the registered
        # source handle; no replacement font or glyph re-layout is involved.
        code.raw(b"\x83\x3d" + struct.pack("<I", hd_font_active_va) + b"\x00")
        code.jump_short_if(Condition.EQUAL, "after_hd_font_source")
        code.raw(bytes.fromhex("8bcc"))
        code.call_absolute(
            self.symbols.va(FONT_BANK_SEGMENT.logical_name, FONT_BANK_SOURCE_GUARD_OFFSET)
        )
        code.raw(bytes.fromhex("85c0"))
        code.jump_short_if(Condition.EQUAL, "after_hd_font_source")
        code += b"\x8b\x74\x24\x2c\x85\xf6"
        code.jump_if(Condition.EQUAL, "after_hd_font_source")
        code += b"\xbf" + struct.pack("<I", hd_font_source_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        for offset in range(0, 16, 4):
            code += b"\xc1\x25" + struct.pack("<I", hd_font_source_rect_va + offset) + b"\x02"
        code += b"\xc7\x44\x24\x2c" + struct.pack("<I", hd_font_source_rect_va)
        code += b"\xff\x05" + struct.pack("<I", hd_font_source_transform_count_va)
        code.label("after_hd_font_source")

        # Console owns both the final framebuffer destination and the matching
        # software-alpha background capture. Run after source-density helpers
        # and cursor exclusion, never by redirecting the shared entry again.
        code.raw(b"\x8b\xcc")
        code.call_absolute(self.symbols.va(CONSOLE_SEGMENT.logical_name, CONSOLE_TRANSFER_OFFSET))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "console_native")

        # GPS members are room siblings with authored world/map geometry.
        # Their synchronous Draw scope owns only the display destination;
        # source density was already handled above. Never apply another UI fit.
        code.raw(b"\x8b\xcc")
        code.call_absolute(self.symbols.va(GPS_SEGMENT.logical_name, GPS_TRANSFER_OFFSET))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "native")

        # ToolTip::Draw owns a global overlay even when InGameToolbar remains
        # the active transformed root. Its top-left is computed from the live
        # physical pointer/screen bounds, while its border, text advances, and
        # extents remain authored for a 768-line output. Apply one local affine
        # about that already-physical anchor to every nested final transfer.
        # This keeps glyph spacing, border thickness, and background coverage
        # coherent without moving the tooltip or naming an output resolution.
        code += b"\x83\x3d" + struct.pack("<I", tooltip_draw_depth_va) + b"\x00"
        code.jump_if(Condition.NOT_EQUAL, "tooltip_transform")

        # ActionMenu's class-specific Draw wrapper publishes final physical
        # top-left anchors and contiguous hit rectangles. Its four/five icon
        # transfers remain 32x32, however. Recognize only that concrete root
        # and bounded sprite extent, then grow the destination about its
        # already-physical anchor without touching nested room/status traffic.
        code += b"\xa1" + struct.pack("<I", root_ptr_va) + b"\x85\xc0"
        code.jump_if(Condition.EQUAL, "after_scoped_extent")
        code += b"\x81\x38" + struct.pack("<I", self.profile.address("action_menu.vtable"))
        code.jump_if(Condition.NOT_EQUAL, "after_scoped_extent")
        # A retained ActionMenu root is not ownership of every small blit.
        # Actor blinking can update a 256x256 face texture in the same frame;
        # those texture-local rectangles must never inherit display scaling.
        # As for the generic UI path below, require the display-sized target.
        code += b"\x8b\x54\x24\x18"
        code += b"\xa1" + struct.pack("<I", self._physical_width_va)
        code += b"\x39\x42\x38"
        code.jump_if(Condition.NOT_EQUAL, "native")
        code += b"\xa1" + struct.pack("<I", self._physical_width_va + 4)
        code += b"\x39\x42\x3c"
        code.jump_if(Condition.NOT_EQUAL, "native")
        code += b"\x8b\x74\x24\x28\x85\xf6"
        code.jump_if(Condition.EQUAL, "after_scoped_extent")
        code += b"\x8b\x46\x08\x2b\x06\x85\xc0"
        code.jump_if(Condition.LESS_OR_EQUAL, "after_scoped_extent")
        code += b"\x83\xf8\x40"
        code.jump_if(Condition.ABOVE, "after_scoped_extent")
        code += b"\x8b\x46\x0c\x2b\x46\x04\x85\xc0"
        code.jump_if(Condition.LESS_OR_EQUAL, "after_scoped_extent")
        code += b"\x83\xf8\x40"
        code.jump_if(Condition.ABOVE, "after_scoped_extent")

        code.label("scale_scoped_extent")
        code += b"\xbf" + struct.pack("<I", dest_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        for first, second in ((0, 8), (4, 12)):
            code += b"\xa1" + struct.pack("<I", dest_rect_va + second)
            code += b"\x2b\x05" + struct.pack("<I", dest_rect_va + first)
            code += b"\x0f\xaf\x05" + struct.pack("<I", self._physical_width_va + 4)
            code += b"\x99\xb9\x00\x03\x00\x00\xf7\xf9"
            code += b"\x03\x05" + struct.pack("<I", dest_rect_va + first)
            code += b"\xa3" + struct.pack("<I", dest_rect_va + second)
        code += b"\xc7\x44\x24\x28" + struct.pack("<I", dest_rect_va)
        code += b"\xff\x05" + struct.pack("<I", transform_count_va)
        code.jump("native")
        code.label("after_scoped_extent")

        # The status-font wrapper scales its X/Y point before GK3 performs
        # clipping.  Its nested final Blt enters a dedicated branch below that
        # combines that physical point with the glyph's still-native extent.
        code += b"\x83\x3d" + struct.pack("<I", hud_font_active_va) + b"\x00"
        code.jump_if(Condition.NOT_EQUAL, "early_hud_candidate")
        code += b"\x83\x3d" + struct.pack("<I", render_depth_va) + b"\x00"
        code.jump_if(Condition.NOT_EQUAL, "active_scope")
        code += b"\x83\x3d" + struct.pack("<I", input_active_va) + b"\x00"
        code.jump_if(Condition.EQUAL, "native")
        code += b"\x83\x3d" + struct.pack("<I", transform_mode_va) + b"\x00"
        code.jump_if(Condition.EQUAL, "native")
        code.label("active_scope")
        # Toolbar resources retain native extents even though GK3 centers their
        # anchors in the physical framebuffer. They may render through a page-
        # local destination wrapper, so recognize their exact owning class
        # before the primary-surface dimension gate and scale their final RECT
        # in a dedicated branch below.
        code += b"\x83\x3d" + struct.pack("<I", transform_mode_va)
        code += bytes([self._mode_popup])
        code.jump_if(Condition.NOT_EQUAL, "active_not_toolbar")
        code += b"\xa1" + struct.pack("<I", root_ptr_va) + b"\x85\xc0"
        code.jump_if(Condition.EQUAL, "active_not_toolbar")
        code += b"\x81\x38" + struct.pack("<I", self.profile.address("ingame_toolbar.vtable"))
        code.jump_if(Condition.NOT_EQUAL, "active_not_toolbar")
        code += b"\x8b\xcc"
        code.call_absolute(toolbar_blt_helper_va)
        # The helper owns every transfer submitted by this concrete toolbar
        # root. A zero return means page-local scratch/native traffic, not a
        # generic popup that should overwrite the toolbar's published affine.
        code.jump("native")
        code.label("active_not_toolbar")
        code += b"\x8b\x54\x24\x18"
        code += b"\xa1" + struct.pack("<I", self._physical_width_va)
        code += b"\x39\x42\x38"
        code.jump_if(Condition.NOT_EQUAL, "native")
        code += b"\xa1" + struct.pack("<I", self._physical_width_va + 4)
        code += b"\x39\x42\x3c"
        code.jump_if(Condition.NOT_EQUAL, "native")
        code += b"\x8b\x74\x24\x28\x85\xf6"
        code.jump_if(Condition.EQUAL, "native")

        # Several generic UI trees queue dirty child draws that execute after
        # their root Draw method returns.  The Show/Hide lifetime state above
        # deliberately keeps those transfers in scope.  The room/status line
        # is also emitted during some of those traversals, however, and must
        # stay anchored to the physical top-left rather than inherit a fitted
        # inventory/menu canvas.  Route only the tightly bounded status band
        # to its dedicated recognizer before selecting the layer transform.
        code += b"\x83\x7e\x04\x20"
        code.jump_if(Condition.ABOVE_OR_EQUAL, "active_not_hud")
        code += b"\x83\x7e\x0c\x20"
        code.jump_if(Condition.GREATER, "active_not_hud")
        code += b"\x81\x7e\x08\x00\x04\x00\x00"
        code.jump_if(Condition.GREATER, "active_not_hud")
        code.jump("native")
        code.label("active_not_hud")
        code += b"\x83\x3d" + struct.pack("<I", transform_mode_va)
        code += bytes([self._mode_physical_canvas])
        code.jump_if(Condition.EQUAL, "native")
        code += (
            b"\x83\x3d" + struct.pack("<I", transform_mode_va) + bytes([self._mode_loadsave_layout])
        )
        code.jump_if(Condition.EQUAL, "loadsave_layout_transform")
        code += b"\x83\x3d" + struct.pack("<I", transform_mode_va) + bytes([self._mode_popup])
        code.jump_if(Condition.EQUAL, "popup_transform")
        code += b"\x83\x3d" + struct.pack("<I", transform_mode_va)
        code += bytes([self._mode_local_root_canvas])
        code.jump_if(Condition.EQUAL, "popup_transform")
        code += b"\x83\x3d" + struct.pack("<I", transform_mode_va)
        code += bytes([self._mode_bottom_anchored_reference_canvas])
        code.jump_if(Condition.EQUAL, "reference_canvas_transform")
        code += (
            b"\x83\x3d"
            + struct.pack("<I", transform_mode_va)
            + bytes([self._mode_reference_anchor])
        )
        code.jump_if(Condition.EQUAL, "cleared")
        code += (
            b"\x83\x3d"
            + struct.pack("<I", transform_mode_va)
            + bytes([self._mode_reference_canvas])
        )
        code.jump_if(Condition.EQUAL, "reference_canvas_transform")
        code += b"\x83\x3d" + struct.pack("<I", transform_mode_va)
        code += bytes([self._mode_reference_canvas_all])
        code.jump_if(Condition.EQUAL, "reference_canvas_transform")
        code += b"\x83\x3d" + struct.pack("<I", transform_mode_va) + bytes([self._mode_loadsave])
        code.jump_if(Condition.EQUAL, "loadsave_layout_transform")

        # Clear only the exposed pillar bands once per composite root traversal.
        # The root can use dirty redraws, so clearing the complete surface here
        # would erase center pixels that this particular pass does not revisit.
        code += b"\x83\x3d" + struct.pack("<I", clear_pending_va) + b"\x00"
        code.jump_if(Condition.EQUAL, "cleared")
        code += b"\xc7\x05" + struct.pack("<I", clear_pending_va) + b"\x00\x00\x00\x00"
        code += b"\x8b\x72\x2c\x85\xf6"
        code.jump_if(Condition.EQUAL, "cleared")
        code += b"\x89\x35" + struct.pack("<I", composite_surface_va)
        code += b"\x8b\x1e"
        code += b"\xa1" + struct.pack("<I", self._physical_width_va + 4)
        code += b"\xc1\xe0\x02\x99\xb9\x03\x00\x00\x00\xf7\xf9"
        code += b"\x8b\x0d" + struct.pack("<I", self._physical_width_va)
        code += b"\x2b\xc8\xd1\xf9\x85\xc9"
        code.jump_if(Condition.LESS_OR_EQUAL, "cleared")
        code += b"\x31\xc0"
        code += b"\xa3" + struct.pack("<I", left_bar_rect_va)
        code += b"\xa3" + struct.pack("<I", left_bar_rect_va + 4)
        code += b"\x89\x0d" + struct.pack("<I", left_bar_rect_va + 8)
        code += b"\x8b\x15" + struct.pack("<I", self._physical_width_va + 4)
        code += b"\x89\x15" + struct.pack("<I", left_bar_rect_va + 12)
        code += b"\x8b\x15" + struct.pack("<I", self._physical_width_va)
        code += b"\x2b\xd1\x89\x15" + struct.pack("<I", right_bar_rect_va)
        code += b"\xa3" + struct.pack("<I", right_bar_rect_va + 4)
        code += b"\x8b\x15" + struct.pack("<I", self._physical_width_va)
        code += b"\x89\x15" + struct.pack("<I", right_bar_rect_va + 8)
        code += b"\x8b\x15" + struct.pack("<I", self._physical_width_va + 4)
        code += b"\x89\x15" + struct.pack("<I", right_bar_rect_va + 12)
        for rect_va in (left_bar_rect_va, right_bar_rect_va):
            code += b"\x68" + struct.pack("<I", bltfx_va)
            code += b"\x68" + struct.pack("<I", self._ddblt_colorfill_wait)
            code += b"\x6a\x00\x6a\x00"
            code += b"\x68" + struct.pack("<I", rect_va)
            code += b"\x56\xff\x53\x14"
        code.label("cleared")

        # Keep both the original physical source viewport and its 4:3 target
        # for the input inverse, then copy the caller-owned destination RECT.
        code += b"\x31\xc0"
        code += b"\xa3" + struct.pack("<I", source_rect_va)
        code += b"\xa3" + struct.pack("<I", source_rect_va + 4)
        code += b"\x8b\x0d" + struct.pack("<I", self._physical_width_va)
        code += b"\x89\x0d" + struct.pack("<I", source_rect_va + 8)
        code += b"\x8b\x1d" + struct.pack("<I", self._physical_width_va + 4)
        code += b"\x89\x1d" + struct.pack("<I", source_rect_va + 12)
        code += b"\x8b\x74\x24\x28\xbf" + struct.pack("<I", dest_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"

        # Compare W/H with 4/3 and construct the largest centered 4:3 target.
        # REP MOVSD consumes ECX, so reload both live dimensions from the
        # source rectangle retained for input before doing the aspect test.
        code += b"\x8b\x0d" + struct.pack("<I", source_rect_va + 8)
        code += b"\x8b\x1d" + struct.pack("<I", source_rect_va + 12)
        code += b"\x8b\xc1\x6b\xc0\x03"
        code += b"\x8b\xd3\xc1\xe2\x02\x3b\xc2"
        code.jump_if(Condition.LESS, "narrow_offset")

        # Width is limiting only in a narrow/portrait mode.  Wide modes fit
        # physical height and produce the familiar 240-pixel bars at 1080p.
        code += b"\x8b\xc3\xc1\xe0\x02\x99\xbf\x03\x00\x00\x00\xf7\xff"
        code += b"\x8b\xd1\x2b\xd0\xd1\xfa"
        code += b"\x89\x15" + struct.pack("<I", target_rect_va)
        code += b"\xc7\x05" + struct.pack("<I", target_rect_va + 4) + b"\x00\x00\x00\x00"
        code += b"\x03\xc2\xa3" + struct.pack("<I", target_rect_va + 8)
        code += b"\x89\x1d" + struct.pack("<I", target_rect_va + 12)
        code.jump("target_ready")

        code.label("narrow_offset")
        code += b"\x8b\xc1\x6b\xc0\x03\xc1\xf8\x02"
        code += b"\x8b\xd3\x2b\xd0\xd1\xfa"
        code += b"\xc7\x05" + struct.pack("<I", target_rect_va) + b"\x00\x00\x00\x00"
        code += b"\x89\x15" + struct.pack("<I", target_rect_va + 4)
        code += b"\x89\x0d" + struct.pack("<I", target_rect_va + 8)
        code += b"\x03\xc2\xa3" + struct.pack("<I", target_rect_va + 12)
        code.label("target_ready")

        # A wide, shallow top-band transfer belongs to GK3's dirty-region
        # restore rather than the Death composition.  It must retain native
        # coordinates; fitting it left narrow strips of dgVoodoo's debug
        # backing surface visible above the artwork.
        code += b"\xa1" + struct.pack("<I", dest_rect_va + 8)
        code += b"\x2b\x05" + struct.pack("<I", dest_rect_va)
        code += b"\x8b\x15" + struct.pack("<I", self._physical_width_va)
        code += b"\xc1\xea\x02\x3b\xc2"
        code.jump_if(Condition.BELOW, "small_height_check")
        code += b"\xa1" + struct.pack("<I", dest_rect_va + 12)
        code += b"\x2b\x05" + struct.pack("<I", dest_rect_va + 4)
        code += b"\x8b\x15" + struct.pack("<I", self._physical_width_va + 4)
        code += b"\xc1\xea\x03\x3b\xc2"
        code.jump_if(Condition.ABOVE_OR_EQUAL, "large_transform")
        code += b"\xa1" + struct.pack("<I", dest_rect_va + 4)
        code += b"\x3b\xc2"
        code.jump_if(Condition.ABOVE_OR_EQUAL, "large_transform")
        code.jump("native")

        code.label("small_height_check")
        code += b"\xa1" + struct.pack("<I", dest_rect_va + 12)
        code += b"\x2b\x05" + struct.pack("<I", dest_rect_va + 4)
        code += b"\x8b\x15" + struct.pack("<I", self._physical_width_va + 4)
        code += b"\xc1\xea\x02\x3b\xc2"
        code.jump_if(Condition.BELOW, "small_transform")

        # Large children (principally DEATHSCREEN itself) already occupy the
        # physical screen, so map both of their axes into the fitted viewport.
        code.label("large_transform")
        # Large TitleLayer traffic is the already normalized physical cache,
        # not a reference-canvas control, and must retain native coordinates.
        code += (
            b"\x83\x3d"
            + struct.pack("<I", transform_mode_va)
            + bytes([self._mode_reference_anchor])
        )
        code.jump_if(Condition.EQUAL, "native")
        for displacement in (0, 8):
            code += b"\xa1" + struct.pack("<I", dest_rect_va + displacement)
            code += b"\x8b\x0d" + struct.pack("<I", target_rect_va + 8)
            code += b"\x2b\x0d" + struct.pack("<I", target_rect_va)
            code += b"\x0f\xaf\xc1\x99"
            code += b"\x8b\x0d" + struct.pack("<I", self._physical_width_va)
            code += b"\xf7\xf9"
            code += b"\x03\x05" + struct.pack("<I", target_rect_va)
            code += b"\xa3" + struct.pack("<I", dest_rect_va + displacement)
        for displacement in (4, 12):
            code += b"\xa1" + struct.pack("<I", dest_rect_va + displacement)
            code += b"\x8b\x0d" + struct.pack("<I", target_rect_va + 12)
            code += b"\x2b\x0d" + struct.pack("<I", target_rect_va + 4)
            code += b"\x0f\xaf\xc1\x99"
            code += b"\x8b\x0d" + struct.pack("<I", self._physical_width_va + 4)
            code += b"\xf7\xf9"
            code += b"\x03\x05" + struct.pack("<I", target_rect_va + 4)
            code += b"\xa3" + struct.pack("<I", dest_rect_va + displacement)
        code.jump("transformed")

        # Buttons keep native-size rectangles even in a wide mode.  Map their
        # anchors into the 4:3 viewport, then scale their extents uniformly by
        # target_height/768.  This reproduces their 1024x768 apparent size.
        code.label("small_transform")
        # Binocs' arrow commands form one local D-pad widget. Let its dedicated
        # helper preserve those intra-widget offsets before applying the
        # generic independent-control affine to every other small transfer.
        code.raw(b"\x8b\xcc")
        code.call_absolute(binocs_local_blt_helper_va)
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "transformed")
        code += b"\x8b\x35" + struct.pack("<I", dest_rect_va + 8)
        code += b"\x2b\x35" + struct.pack("<I", dest_rect_va)
        code += b"\x8b\x3d" + struct.pack("<I", dest_rect_va + 12)
        code += b"\x2b\x3d" + struct.pack("<I", dest_rect_va + 4)
        code += b"\x8b\x0d" + struct.pack("<I", target_rect_va + 12)
        code += b"\x2b\x0d" + struct.pack("<I", target_rect_va + 4)
        code += b"\x8b\xc6\x0f\xaf\xc1\x99\xb9\x00\x03\x00\x00\xf7\xf9\x8b\xf0"
        code += b"\x8b\x0d" + struct.pack("<I", target_rect_va + 12)
        code += b"\x2b\x0d" + struct.pack("<I", target_rect_va + 4)
        code += b"\x8b\xc7\x0f\xaf\xc1"
        code += b"\x99\xb9\x00\x03\x00\x00\xf7\xf9\x8b\xf8"
        for displacement, opposite, source_size_va, target_size_va, target_edge_va, size_reg in (
            (0, 8, self._physical_width_va, target_rect_va + 8, target_rect_va, b"\x8b\xd6"),
            (
                4,
                12,
                self._physical_width_va + 4,
                target_rect_va + 12,
                target_rect_va + 4,
                b"\x8b\xd7",
            ),
        ):
            code += b"\xa1" + struct.pack("<I", dest_rect_va + displacement)
            code += b"\x03\x05" + struct.pack("<I", dest_rect_va + opposite)
            code += b"\xd1\xf8"
            code += b"\x8b\x0d" + struct.pack("<I", target_size_va)
            code += b"\x2b\x0d" + struct.pack("<I", target_edge_va)
            code += b"\x0f\xaf\xc1\x99"
            code += b"\x8b\x0d" + struct.pack("<I", source_size_va)
            code += b"\xf7\xf9"
            code += b"\x03\x05" + struct.pack("<I", target_edge_va)
            code += size_reg + b"\xd1\xfa\x2b\xc2"
            code += b"\xa3" + struct.pack("<I", dest_rect_va + displacement)
        code += b"\x8b\xc6\x03\x05" + struct.pack("<I", dest_rect_va)
        code += b"\xa3" + struct.pack("<I", dest_rect_va + 8)
        code += b"\x8b\xc7\x03\x05" + struct.pack("<I", dest_rect_va + 4)
        code += b"\xa3" + struct.pack("<I", dest_rect_va + 12)

        # GK3 bottom/right-anchors some controls against the physical screen
        # before this affine grows their authored extent.  At sufficiently
        # large modes that expansion can put the far edge just outside the
        # destination surface, causing native DirectDraw to reject the entire
        # Blt instead of clipping it (CloseUp's Exit is the canonical case).
        # Translate, rather than squash, the complete scaled rectangle back
        # inside the live framebuffer.  This retains reference scale and is
        # independent of any named output resolution.
        for axis, first, second, physical_size_va in (
            ("x", 0, 8, self._physical_width_va),
            ("y", 4, 12, self._physical_width_va + 4),
        ):
            code += b"\xa1" + struct.pack("<I", dest_rect_va + first) + b"\x85\xc0"
            code.jump_if(Condition.GREATER_OR_EQUAL, f"small_{axis}_near_inside")
            code += b"\x8b\x0d" + struct.pack("<I", dest_rect_va + second)
            code += b"\x2b\xc8\x89\x0d" + struct.pack("<I", dest_rect_va + second)
            code += b"\x31\xc0\xa3" + struct.pack("<I", dest_rect_va + first)
            code.label(f"small_{axis}_near_inside")
            code += b"\xa1" + struct.pack("<I", dest_rect_va + second)
            code += b"\x3b\x05" + struct.pack("<I", physical_size_va)
            code.jump_if(Condition.LESS_OR_EQUAL, f"small_{axis}_far_inside")
            code += b"\x2b\x05" + struct.pack("<I", physical_size_va)
            code += b"\x29\x05" + struct.pack("<I", dest_rect_va + first)
            code += b"\xa1" + struct.pack("<I", physical_size_va)
            code += b"\xa3" + struct.pack("<I", dest_rect_va + second)
            code.label(f"small_{axis}_far_inside")

        code.jump("transformed")

        code.label("reference_canvas_transform")
        # Inventory children retain literal 1024x768 coordinates. CloseUp uses
        # the same authored X domain, while its native layout bottom-anchors Y
        # against the live framebuffer. Model that as the final 768 rows of the
        # physical surface. Construct one centered 4:3 target, leave large
        # independently-scaled artwork alone, and map only fixed controls.
        code += b"\x31\xc0"
        code += b"\xa3" + struct.pack("<I", source_rect_va)
        code += (
            b"\xc7\x05"
            + struct.pack("<I", source_rect_va + 8)
            + struct.pack("<I", AUTHORED_FRAME_WIDTH)
        )
        code += b"\x83\x3d" + struct.pack("<I", transform_mode_va)
        code += bytes([self._mode_bottom_anchored_reference_canvas])
        code.jump_if(Condition.NOT_EQUAL, "reference_canvas_origin_top")
        code += b"\xa1" + struct.pack("<I", self._physical_width_va + 4)
        code += b"\x2d" + struct.pack("<I", AUTHORED_FRAME_HEIGHT)
        code += b"\xa3" + struct.pack("<I", source_rect_va + 4)
        code += b"\xa1" + struct.pack("<I", self._physical_width_va + 4)
        code += b"\xa3" + struct.pack("<I", source_rect_va + 12)
        code.jump("reference_canvas_source_ready")
        code.label("reference_canvas_origin_top")
        code += b"\x31\xc0"
        code += b"\xa3" + struct.pack("<I", source_rect_va + 4)
        code += (
            b"\xc7\x05"
            + struct.pack("<I", source_rect_va + 12)
            + struct.pack("<I", AUTHORED_FRAME_HEIGHT)
        )
        code.label("reference_canvas_source_ready")
        code += b"\x8b\x0d" + struct.pack("<I", self._physical_width_va)
        code += b"\x8b\x1d" + struct.pack("<I", self._physical_width_va + 4)
        code += b"\x8b\xc1\x6b\xc0\x03\x8b\xd3\xc1\xe2\x02\x3b\xc2"
        code.jump_if(Condition.LESS, "reference_canvas_narrow_target")
        # Wide display: height limits the 4:3 viewport.
        code += b"\x8b\xc3\xc1\xe0\x02\x99\xbf\x03\x00\x00\x00\xf7\xff"
        code += b"\x8b\xd1\x2b\xd0\xd1\xfa"
        code += b"\x89\x15" + struct.pack("<I", target_rect_va)
        code += b"\xc7\x05" + struct.pack("<I", target_rect_va + 4) + b"\x00\x00\x00\x00"
        code += b"\x03\xc2\xa3" + struct.pack("<I", target_rect_va + 8)
        code += b"\x89\x1d" + struct.pack("<I", target_rect_va + 12)
        code.jump("reference_canvas_target_ready")
        # Narrow/portrait display: width limits the 4:3 viewport.
        code.label("reference_canvas_narrow_target")
        code += b"\x8b\xc1\x6b\xc0\x03\xc1\xf8\x02"
        code += b"\x8b\xd3\x2b\xd0\xd1\xfa"
        code += b"\xc7\x05" + struct.pack("<I", target_rect_va) + b"\x00\x00\x00\x00"
        code += b"\x89\x15" + struct.pack("<I", target_rect_va + 4)
        code += b"\x89\x0d" + struct.pack("<I", target_rect_va + 8)
        code += b"\x03\xc2\xa3" + struct.pack("<I", target_rect_va + 12)
        code.label("reference_canvas_target_ready")

        code += b"\x8b\x74\x24\x28"
        code += b"\x8b\x46\x08\x2b\x06"
        code += b"\x8b\x15" + struct.pack("<I", self._physical_width_va) + b"\xc1\xea\x02\x3b\xc2"
        code.jump_if(Condition.BELOW, "reference_canvas_small")
        code += b"\x8b\x46\x0c\x2b\x46\x04"
        code += (
            b"\x8b\x15" + struct.pack("<I", self._physical_width_va + 4) + b"\xc1\xea\x02\x3b\xc2"
        )
        code.jump_if(Condition.ABOVE_OR_EQUAL, "reference_canvas_large_check")
        code.jump("reference_canvas_small")
        code.label("reference_canvas_large_check")
        code += b"\x83\x3d" + struct.pack("<I", transform_mode_va)
        code += bytes([self._mode_reference_canvas_all])
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.label("reference_canvas_small")
        code += b"\xbf" + struct.pack("<I", dest_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        for index, axis, denominator in (
            (0, 0, AUTHORED_FRAME_WIDTH),
            (1, 1, AUTHORED_FRAME_HEIGHT),
            (2, 0, AUTHORED_FRAME_WIDTH),
            (3, 1, AUTHORED_FRAME_HEIGHT),
        ):
            target_edge_va = target_rect_va + axis * 4
            target_far_va = target_rect_va + 8 + axis * 4
            code += b"\xa1" + struct.pack("<I", dest_rect_va + index * 4)
            code += b"\x2b\x05" + struct.pack("<I", source_rect_va + axis * 4)
            code += b"\x8b\x0d" + struct.pack("<I", target_far_va)
            code += b"\x2b\x0d" + struct.pack("<I", target_edge_va)
            code += b"\x0f\xaf\xc1\x99\xb9" + struct.pack("<I", denominator) + b"\xf7\xf9"
            code += b"\x03\x05" + struct.pack("<I", target_edge_va)
            code += b"\xa3" + struct.pack("<I", dest_rect_va + index * 4)
        code.jump("transformed")

        code.label("popup_transform")
        # Popup roots already have the correct screen-space anchor but retain
        # 1024-era pixel extents.  Build a height-scaled target around the
        # root's native center, then map every child destination through it.
        code += b"\x8b\x35" + struct.pack("<I", root_ptr_va) + b"\x85\xf6"
        code.jump_if(Condition.EQUAL, "native")
        for displacement in range(0, 16, 4):
            code += b"\x8b\x46" + bytes([0x1C + displacement])
            code += b"\xa3" + struct.pack("<I", source_rect_va + displacement)

        for first, second in ((0, 8), (4, 12)):
            # EBP = signed center of this source axis.
            code += b"\x8b\x2d" + struct.pack("<I", source_rect_va + first)
            code += b"\x03\x2d" + struct.pack("<I", source_rect_va + second)
            code += b"\xd1\xfd"
            for displacement in (first, second):
                code += b"\xa1" + struct.pack("<I", source_rect_va + displacement)
                code += b"\x2b\xc5"
                code += b"\x0f\xaf\x05" + struct.pack("<I", self._physical_width_va + 4)
                code += b"\x99\xb9\x00\x03\x00\x00\xf7\xf9\x03\xc5"
                code += b"\xa3" + struct.pack("<I", target_rect_va + displacement)

        code += b"\x8b\x74\x24\x28\xbf" + struct.pack("<I", dest_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        for displacement, first, second in (
            (0, 0, 8),
            (8, 0, 8),
            (4, 4, 12),
            (12, 4, 12),
        ):
            code += b"\xa1" + struct.pack("<I", dest_rect_va + displacement)
            code += b"\x2b\x05" + struct.pack("<I", source_rect_va + first)
            code += b"\x8b\x0d" + struct.pack("<I", target_rect_va + second)
            code += b"\x2b\x0d" + struct.pack("<I", target_rect_va + first)
            code += b"\x0f\xaf\xc1\x99"
            code += b"\x8b\x0d" + struct.pack("<I", source_rect_va + second)
            code += b"\x2b\x0d" + struct.pack("<I", source_rect_va + first)
            code += b"\xf7\xf9"
            code += b"\x03\x05" + struct.pack("<I", target_rect_va + first)
            code += b"\xa3" + struct.pack("<I", dest_rect_va + displacement)

        # ConfirmQuit owns a complete local tree; the result above is final.
        # General popups fall through to the Load/Save classifier because that
        # historical mode also covers roots with independently physical cover
        # and background transfers.
        code += b"\x83\x3d" + struct.pack("<I", transform_mode_va)
        code += bytes([self._mode_local_root_canvas])
        code.jump_if(Condition.EQUAL, "transformed")

        code.label("loadsave_layout_transform")
        code += b"\x8b\xcc"
        code.call_absolute(loadsave_background_helper_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.EQUAL, "popup_transform")
        code += b"\x83\xf8\x02"
        code.jump_if(Condition.EQUAL, "native")
        code.jump("transformed")

        code.label("early_hud_candidate")
        # ``hud_font_active`` brackets one synchronous high-level glyph call.
        # Cursor-owned transfers were already rejected by exact surface
        # identity above, so the remaining nested transfer is the glyph.
        code += b"\x83\x3d" + struct.pack("<I", hud_font_active_va) + b"\x02"
        code.jump_if(Condition.EQUAL, "loadsave_font_extent")

        # GK3 has now constructed the final glyph destination RECT.  Preserve
        # its native width/height, then map each near/far edge from the original
        # logical point.  This yields the exact floor(edge * H / 768) transform
        # without scaling the already-physical near edge twice.
        code += b"\x8b\x74\x24\x28\x85\xf6"
        code.jump_if(Condition.EQUAL, "native")
        code += b"\xbf" + struct.pack("<I", dest_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        code += b"\x8b\x1d" + struct.pack("<I", self._physical_width_va + 4)
        code += b"\xbd\x00\x03\x00\x00"
        for axis, first, second in ((0, 0, 8), (4, 4, 12)):
            code += b"\xa1" + struct.pack("<I", dest_rect_va + second)
            code += b"\x2b\x05" + struct.pack("<I", dest_rect_va + first)
            code += b"\x8b\xc8"
            code += b"\xa1" + struct.pack("<I", hud_font_point_va + axis)
            code += b"\x0f\xaf\xc3\x99\xf7\xfd"
            code += b"\xa3" + struct.pack("<I", dest_rect_va + first)
            code += b"\xa1" + struct.pack("<I", hud_font_point_va + axis)
            code += b"\x03\xc1\x0f\xaf\xc3\x99\xf7\xfd"
            code += b"\xa3" + struct.pack("<I", dest_rect_va + second)
        code.jump("hud_transformed")

        code.label("loadsave_font_extent")
        # Load/Save's high-level hook has already mapped the glyph point about
        # its live TextBox.  At this boundary GK3 has added the native glyph
        # extent; scale only that width/height about the mapped near edge.  A
        # late transform of the complete rectangle would occur after damage
        # tracking and leaves stale text on alternating DirectDraw pages.
        code += b"\x8b\x74\x24\x28\x85\xf6"
        code.jump_if(Condition.EQUAL, "native")
        code += b"\xbf" + struct.pack("<I", dest_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        for axis, first, second in ((0, 0, 8), (4, 4, 12)):
            code += b"\xa1" + struct.pack("<I", dest_rect_va + second)
            code += b"\x2b\x05" + struct.pack("<I", dest_rect_va + first)
            code += b"\x0f\xaf\x05" + struct.pack("<I", self._physical_width_va + 4)
            code += b"\x99\xb9\x00\x03\x00\x00\xf7\xf9"
            code += b"\x8b\x15" + struct.pack("<I", hud_font_point_va + axis)
            code += b"\x89\x15" + struct.pack("<I", dest_rect_va + first)
            code += b"\x03\xc2\xa3" + struct.pack("<I", dest_rect_va + second)
        code.jump("hud_transformed")

        code.label("hud_transformed")
        # Retain one narrow diagnostic of the final glyph affine. This makes
        # it possible to distinguish a missed high-level scope from a later
        # presentation fault without tracing the shared DirectDraw sink.
        code += b"\xbe" + struct.pack("<I", dest_rect_va)
        code += b"\xbf" + struct.pack("<I", hud_last_rect_va)
        code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
        code += b"\xff\x05" + struct.pack("<I", hud_transform_count_va)
        code.jump("transformed")

        code.label("transformed")
        code += b"\xc7\x44\x24\x28" + struct.pack("<I", dest_rect_va)
        code += b"\xff\x05" + struct.pack("<I", transform_count_va)

        code.label("native")
        code += b"\x61"
        code.jump_absolute(downstream_va)

        code.label("tooltip_transform")
        code.raw(b"\x8b\xcc")
        code.jump_absolute(tooltip_transfer_affine_va)

        # Console's entry bridge preserves the original alpha-compositor return
        # PC. Its owned transfer is complete: re-entering public Blt would lose
        # the bridge marker and apply the scope again. Use the canonical native
        # continuation, after all source helpers and exact cursor exclusions.
        code.label("console_native")
        code.raw(b"\x61")
        code.jump_absolute(
            self.symbols.va(
                SIDNEY_PRESENTATION_SEGMENT.logical_name, SIDNEY_NATIVE_BLT_TRAMPOLINE_OFFSET
            )
        )

        # Status glyphs are owned exclusively by the high-level font hook and
        # its ``hud_font_active`` branch above.  A former late fallback sent
        # arbitrary primary-surface transfers in the top 32 pixels through the
        # HUD affine.  Cursor save-under restoration can legitimately target
        # that band, so the fallback produced a cursor-sized hole or stale
        # pointer over the room text on alternating pages.  Unscoped traffic
        # and non-font top-band transfers must remain byte-for-byte native.
        return code.build()
