"""Emit exact-resource classifiers and dense-source blit transforms."""

# These emitters are one physical part of ResourceDispatchCompiler and consume
# its private recovered ABI directly; copying that ABI into a second public
# configuration object would add state and permit the two views to drift.
# ruff: noqa: SLF001

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.geometry import AUTHORED_FRAME_HEIGHT
from gk3hd.patch.definitions.runtime2d.layout import (
    FINGERPRINT_ALPHA_NORMALIZE_OFFSET,
    FINGERPRINT_ALPHA_SEGMENT,
)

if TYPE_CHECKING:
    from gk3hd.patch.definitions.runtime2d.resources import ResourceDispatchCompiler


def build_resource_blit_dispatcher(
    owner: ResourceDispatchCompiler,
    *,
    wrapper_va: int,
    dest_rect_va: int,
    source_rect_va: int,
    slider_trace_count_va: int,
    slider_last_record_va: int,
    slider_transform_count_va: int,
    closeup_transform_count_va: int,
    closeup_raw_width_va: int,
    closeup_raw_height_va: int,
    closeup_target_width_va: int,
    closeup_target_height_va: int,
    closeup_rect_va: int,
    closeup_active_surface_va: int,
    museum_surface_va: int,
    closeup_observed_source_va: int,
    resource_lookup_active_va: int,
    progress_draw_depth_va: int,
    progress_transform_count_va: int,
    driving_map_surface_va: int,
    driving_map_transform_count_va: int,
    driving_map_rect_va: int,
    driving_map_scope_active_va: int,
    driving_map_seen_va: int,
    driving_map_child_rect_count_va: int,
    driving_map_child_rects_va: int,
    driving_map_source_grid_rect_va: int,
    tbt_blit_wrapper_va: int,
    tbt_handled_flag_va: int,
    tbt_handled_result_va: int,
    fingerprint_blit_wrapper_va: int,
) -> bytes:
    """Classify one final blit and restore its recognized authored geometry."""
    # Entry is a replacement CALL target for FUN_0054F980:
    #   ECX     destination surface wrapper
    #   [ESP+4] source surface wrapper
    #   [ESP+8] destination RECT
    #   [ESP+C] source RECT
    # Preserve every general register while constructing private RECTs.
    code = X86Emitter(base_va=wrapper_va)
    code += b"\x60"
    code += b"\x83\x3d" + struct.pack("<I", resource_lookup_active_va) + b"\x00"
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.call_absolute(tbt_blit_wrapper_va)
    # TimeBlock's opaque background can follow its independently submitted
    # controls. Its helper owns that one ordered background+control sequence
    # and publishes the HRESULT, so the shared dispatcher must return without
    # issuing the original background a second time.
    code += b"\x83\x3d" + struct.pack("<I", tbt_handled_flag_va) + b"\x00"
    code.jump_if(Condition.NOT_EQUAL, "timeblock_handled")
    code.call_absolute(fingerprint_blit_wrapper_va)
    code += b"\x8b\x44\x24\x24"  # source wrapper after PUSHAD

    # The top-level 2D composition owner clears map scope before drawing.
    # Seeing the tagged, fullscreen DM_BASE transfer activates that scope
    # for the rest of the same traversal, which includes all separately
    # drawn location tiles. X coordinates are fitted from physical width
    # into a centered 4:3 viewport; Y coordinates are already correct.
    #
    code += b"\x3b\x05" + struct.pack("<I", driving_map_surface_va)
    code.jump_if(Condition.NOT_EQUAL, "map_check_active")
    code += b"\x8b\x54\x24\x18"
    code += b"\x8b\x0d" + struct.pack("<I", owner._physical_width_va)
    code += b"\x39\x48\x38"
    code.jump_if(Condition.NOT_EQUAL, "map_check_active")
    code += b"\x39\x4a\x38"
    code.jump_if(Condition.NOT_EQUAL, "map_check_active")
    code += b"\x8b\x1d" + struct.pack("<I", owner._physical_width_va + 4)
    code += b"\x39\x58\x3c"
    code.jump_if(Condition.NOT_EQUAL, "map_check_active")
    code += b"\x39\x5a\x3c"
    code.jump_if(Condition.NOT_EQUAL, "map_check_active")
    code += b"\x8b\x74\x24\x28\x8b\x7c\x24\x2c"
    code += b"\x83\x3e\x00"
    code.jump_short_if(Condition.NOT_EQUAL, "map_check_active")
    code += b"\x83\x7e\x04\x00"
    code.jump_short_if(Condition.NOT_EQUAL, "map_check_active")
    code += b"\x39\x4e\x08"
    code.jump_if(Condition.NOT_EQUAL, "map_check_active")
    code += b"\x39\x5e\x0c"
    code.jump_if(Condition.NOT_EQUAL, "map_check_active")
    code += b"\x83\x3f\x00"
    code.jump_short_if(Condition.NOT_EQUAL, "map_check_active")
    code += b"\x83\x7f\x04\x00"
    code.jump_short_if(Condition.NOT_EQUAL, "map_check_active")
    code += b"\x39\x4f\x08"
    code.jump_if(Condition.NOT_EQUAL, "map_check_active")
    code += b"\x39\x5f\x0c"
    code.jump_if(Condition.NOT_EQUAL, "map_check_active")
    code += b"\xc7\x05" + struct.pack("<I", driving_map_seen_va) + b"\x01\x00\x00\x00"
    code += b"\xc7\x05" + struct.pack("<I", driving_map_scope_active_va)
    code += b"\x01\x00\x00\x00"
    code.label("map_check_active")
    code += b"\x83\x3d" + struct.pack("<I", driving_map_scope_active_va) + b"\x00"
    code.jump_if(Condition.EQUAL, "map_done")
    code += b"\x8b\x54\x24\x18"
    code += b"\xa1" + struct.pack("<I", owner._physical_width_va)
    code += b"\x39\x42\x38"
    code.jump_if(Condition.NOT_EQUAL, "map_done")
    code += b"\xa1" + struct.pack("<I", owner._physical_width_va + 4)
    code += b"\x39\x42\x3c"
    code.jump_if(Condition.NOT_EQUAL, "map_done")
    code += b"\x8b\x74\x24\x28\x85\xf6"
    code.jump_if(Condition.EQUAL, "map_done")
    code += b"\xbf" + struct.pack("<I", driving_map_rect_va)
    code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
    code += b"\xc7\x44\x24\x28" + struct.pack("<I", driving_map_rect_va)
    code += b"\xbe" + struct.pack("<I", driving_map_rect_va)
    # The concrete map root keeps all children in GK3's physical X/Y layout
    # domain so native clipping and hit testing remain coherent. Presentation
    # therefore changes only X: compress the complete physical-width model
    # into a centered height-derived 4:3 viewport. Location patches are opaque
    # map-aligned rasters, not repeatable/tiled textures. Their 4x replacements
    # make GK3 construct a destination four times larger than the already-
    # physical model. Match each blit to the root's exact child rectangle. A
    # source surface more than twice that model extent proves a replacement;
    # use the full surface and the saved model bounds so prior screen clipping
    # cannot discard an edge location. Unmatched calls retain the conservative
    # quarter-collapse fallback.
    # DM_BASE is excluded by exact surface identity and stays full-page.
    code += b"\x8b\x44\x24\x24"
    code += b"\x3b\x05" + struct.pack("<I", driving_map_surface_va)
    code.jump_if(Condition.EQUAL, "map_apply_affine")
    code += b"\x8b\x7c\x24\x2c\x85\xff"
    code.jump_if(Condition.EQUAL, "map_apply_affine")
    code += b"\x8b\x0d" + struct.pack("<I", driving_map_child_rect_count_va)
    code += b"\xba" + struct.pack("<I", driving_map_child_rects_va) + b"\x85\xc9"
    code.jump_if(Condition.EQUAL, "map_collapse_dense")
    code.label("map_child_loop")
    code += b"\x8b\x06\x3b\x02"
    code.jump_short_if(Condition.NOT_EQUAL, "map_child_next")
    code += b"\x8b\x46\x04\x3b\x42\x04"
    code.jump_short_if(Condition.NOT_EQUAL, "map_child_next")
    code += b"\x8b\x44\x24\x24\x8b\x48\x38"
    code += b"\x8b\x5a\x08\x2b\x1a\x03\xdb\x3b\xcb"
    code.jump_if(Condition.BELOW_OR_EQUAL, "map_apply_affine")
    code += b"\x8b\x58\x3c\x31\xc0"
    code += b"\xa3" + struct.pack("<I", source_rect_va)
    code += b"\xa3" + struct.pack("<I", source_rect_va + 4)
    code += b"\x89\x0d" + struct.pack("<I", source_rect_va + 8)
    code += b"\x89\x1d" + struct.pack("<I", source_rect_va + 12)
    code += b"\xc7\x44\x24\x2c" + struct.pack("<I", source_rect_va)
    code += b"\x8b\x42\x08\x89\x46\x08"
    code += b"\x8b\x42\x0c\x89\x46\x0c"
    code.jump("map_apply_affine")
    code.label("map_child_next")
    code += b"\x83\xc2\x10\x49"
    code.jump_if(Condition.NOT_EQUAL, "map_child_loop")
    code.label("map_collapse_dense")
    code += b"\x8b\x47\x08\x2b\x07\x3d\x80\x00\x00\x00"
    code.jump_if(Condition.BELOW_OR_EQUAL, "map_apply_affine")
    code += b"\x8b\x46\x08\x2b\x06\xc1\xf8\x02\x03\x06\x89\x46\x08"
    code += b"\x8b\x46\x0c\x2b\x46\x04\xc1\xf8\x02\x03\x46\x04\x89\x46\x0c"
    code.label("map_apply_affine")
    code.call_absolute(driving_map_source_grid_rect_va)
    code += b"\xff\x05" + struct.pack("<I", driving_map_transform_count_va)
    code.jump("native")
    code.label("map_done")
    code += b"\x8b\x44\x24\x24"

    # Record the final-screen geometry of PROGRESS_SLIDER before changing
    # it.  Its explicit clipping semantics differ from the dialog base and
    # are verified separately before joining the transform dispatch.
    code += b"\x81\x78\x38" + struct.pack("<I", owner._slider_width // 4)
    code.jump_if(Condition.NOT_EQUAL, "hd_slider_check")
    code += b"\x81\x78\x3c" + struct.pack("<I", owner._slider_height // 4)
    code.jump_if(Condition.NOT_EQUAL, "progress_gate")
    code.jump("slider_record")
    code.label("hd_slider_check")
    code += b"\x81\x78\x38" + struct.pack("<I", owner._slider_width)
    code.jump_if(Condition.NOT_EQUAL, "progress_gate")
    code += b"\x81\x78\x3c" + struct.pack("<I", owner._slider_height)
    code.jump_if(Condition.NOT_EQUAL, "progress_gate")
    code.label("slider_record")
    code += b"\xff\x05" + struct.pack("<I", slider_trace_count_va)
    code += b"\xa3" + struct.pack("<I", slider_last_record_va)
    code += b"\x8b\x48\x38\x89\x0d" + struct.pack("<I", slider_last_record_va + 4)
    code += b"\x8b\x48\x3c\x89\x0d" + struct.pack("<I", slider_last_record_va + 8)
    code += b"\x8b\x74\x24\x28\x8b\x7c\x24\x2c"
    for index in range(4):
        code += b"\x8b\x46" + bytes([index * 4])
        code += b"\xa3" + struct.pack("<I", slider_last_record_va + 12 + index * 4)
    for index in range(4):
        code += b"\x8b\x47" + bytes([index * 4])
        code += b"\xa3" + struct.pack("<I", slider_last_record_va + 28 + index * 4)

    # The native slider destination is authored inside the 593x201 parent.
    # The controller now owns a live-height-scaled logical cache, so map
    # near edges down and far edges up through H/768. Its HD source still
    # covers four times as many texels in each axis. Preserve the normalized
    # random pan position within the source's valid range:
    #   x: [0,1663] -> [0,124], y: [0,1734] -> [0,1584].
    #
    # Importantly, the restore loop reveals the bar by advancing the right
    # edge while leaving its left edge fixed. Expand that live extent, not
    # the full authored 513x50 viewport. Using an unconditional 2052x200
    # source rectangle made DirectDraw resample the entire strip into every
    # partially revealed destination, visibly "unsquashing" the artwork as
    # loading progressed.
    code += b"\x8b\x44\x24\x24"
    code += b"\x81\x78\x38" + struct.pack("<I", owner._slider_width)
    code.jump_if(Condition.NOT_EQUAL, "slider_done")
    code += b"\xb9" + struct.pack("<I", AUTHORED_FRAME_HEIGHT)
    for index in range(2):
        code += b"\x8b\x46" + bytes([index * 4])
        code += b"\x0f\xaf\x05" + struct.pack("<I", owner._physical_width_va + 4)
        code += b"\x31\xd2\xf7\xf1"
        code += b"\xa3" + struct.pack("<I", dest_rect_va + index * 4)
    for index in range(2, 4):
        code += b"\x8b\x46" + bytes([index * 4])
        code += b"\x0f\xaf\x05" + struct.pack("<I", owner._physical_width_va + 4)
        code += b"\x05" + struct.pack("<I", AUTHORED_FRAME_HEIGHT - 1)
        code += b"\x31\xd2\xf7\xf1"
        code += b"\xa3" + struct.pack("<I", dest_rect_va + index * 4)
    code += b"\xc7\x44\x24\x28" + struct.pack("<I", dest_rect_va)
    code += b"\x8b\x07\x69\xc0\x7c\x00\x00\x00\x99"
    code += b"\xb9\x7f\x06\x00\x00\xf7\xf9"
    code += b"\xa3" + struct.pack("<I", source_rect_va)
    code += b"\x8b\x4f\x08\x2b\x0f\xc1\xe1\x02\x03\xc1"
    code += b"\xa3" + struct.pack("<I", source_rect_va + 8)
    code += b"\x8b\x47\x04\x69\xc0\x30\x06\x00\x00\x99"
    code += b"\xb9\xc6\x06\x00\x00\xf7\xf9"
    code += b"\xa3" + struct.pack("<I", source_rect_va + 4)
    code += b"\x8b\x4f\x0c\x2b\x4f\x04\xc1\xe1\x02\x03\xc1"
    code += b"\xa3" + struct.pack("<I", source_rect_va + 12)
    code += b"\xc7\x44\x24\x2c" + struct.pack("<I", source_rect_va)
    code += b"\xff\x05" + struct.pack("<I", slider_transform_count_va)
    code.label("slider_done")
    code.jump("progress_gate")

    code.label("progress_gate")
    code += b"\x8b\x74\x24\x24"  # source wrapper after PUSHAD
    # Within the controller's exact initial-Show/Update scope, the unique
    # dense background is first copied into the owner's logical-size cache.
    # Replace GK3's upper-left crop with the complete source at that first
    # composition boundary. The later cache-to-screen copy already has the
    # correct model dimensions and remains entirely native.
    code += b"\x83\x3d" + struct.pack("<I", progress_draw_depth_va) + b"\x00"
    code.jump_if(Condition.EQUAL, "primary_gate")
    code += b"\x81\x7e\x38" + struct.pack("<I", owner._progress_width)
    code.jump_if(Condition.NOT_EQUAL, "primary_gate")
    code += b"\x81\x7e\x3c" + struct.pack("<I", owner._progress_height)
    code.jump_if(Condition.NOT_EQUAL, "primary_gate")
    code += b"\x31\xc0"
    code += b"\xa3" + struct.pack("<I", source_rect_va)
    code += b"\xa3" + struct.pack("<I", source_rect_va + 4)
    code += b"\xc7\x05" + struct.pack("<I", source_rect_va + 8)
    code += struct.pack("<I", owner._progress_width)
    code += b"\xc7\x05" + struct.pack("<I", source_rect_va + 12)
    code += struct.pack("<I", owner._progress_height)
    code += b"\xc7\x44\x24\x2c" + struct.pack("<I", source_rect_va)
    code += b"\xff\x05" + struct.pack("<I", progress_transform_count_va)
    code.jump("native")

    code.label("primary_gate")
    code += b"\x8b\x54\x24\x18"  # destination wrapper / saved ECX
    code += b"\xa1" + struct.pack("<I", owner._physical_width_va)
    code += b"\x39\x42\x38"
    code.jump_if(Condition.NOT_EQUAL, "native")
    code += b"\xa1" + struct.pack("<I", owner._physical_width_va + 4)
    code += b"\x39\x42\x3c"
    code.jump_if(Condition.NOT_EQUAL, "native")
    code += b"\x8b\x74\x24\x24"  # reload source wrapper after trace

    # SIDNEY backgrounds use the exact-resource logical dimensions/source
    # adapter before clipping. A late full-image fallback here misinterprets
    # dirty strips below the page as complete 640x480 images and overdraws the
    # destination. The shared UI adapter now owns that conversion exactly once.
    code.label("closeup_gate")

    # A CloseupLayer can own either stock-size evidence art or an exact 4x
    # replacement.  Compare the source wrapper with identities recorded at
    # the two safe ownership boundaries (CloseupLayer attach and bitmap
    # resource entry), then choose the corresponding logical denominator.
    # No caller-frame walk is necessary on this hot shared-blitter path.
    code += b"\x8b\x46\x38"
    code += b"\x8b\x5e\x3c"
    code += b"\x85\xc0"
    code.jump_if(Condition.EQUAL, "native")
    code += b"\x85\xdb"
    code.jump_if(Condition.EQUAL, "native")
    # CloseupLayer's tag bridge records the exact low-level source wrapper,
    # which is already the first final-blitter argument in ESI.  This direct
    # comparison is safe for every sprite call; walking a caller-specific
    # saved-frame chain here is not.
    # A museum panel is also owned by CloseupLayer, so both identity slots
    # normally contain the same source wrapper.  Test the more specific
    # MS3I identity first; otherwise the generic close-up branch wins and
    # incorrectly presents the panel at the inventory/evidence size.
    code += b"\x3b\x35" + struct.pack("<I", museum_surface_va)
    code.jump_if(Condition.EQUAL, "museum_size_gate")
    code += b"\x3b\x35" + struct.pack("<I", closeup_active_surface_va)
    code.jump_if(Condition.EQUAL, "closeup_identity_proven")
    code += b"\x89\x35" + struct.pack("<I", closeup_observed_source_va)
    code.jump("native")

    code.label("closeup_identity_proven")
    code += b"\x8b\x46\x38"
    code += b"\x3d" + struct.pack("<I", owner._closeup_max_width)
    code.jump_if(Condition.ABOVE, "closeup_stock_identity_match")
    code += b"\x81\xfb" + struct.pack("<I", owner._closeup_max_height)
    code.jump_if(Condition.ABOVE, "closeup_stock_identity_match")
    # Stock CloseUp art fits inside GK3's authored 640x480 canvas. Exact 4x
    # replacements are not all near-full-screen: documents and wallets can be
    # much narrower while still carrying four source pixels per logical pixel.
    # Require at least one dimension beyond the stock ceiling and require both
    # dimensions to be divisible by four. This derives the class from the pack
    # contract instead of an asset-specific size range.
    code += b"\x3d" + struct.pack("<I", owner._closeup_stock_max_width)
    code.jump_if(Condition.ABOVE, "closeup_replacement_size")
    code += b"\x81\xfb" + struct.pack("<I", owner._closeup_stock_max_height)
    code.jump_if(Condition.BELOW_OR_EQUAL, "closeup_stock_identity_match")
    code.label("closeup_replacement_size")
    code += b"\xa8\x03"
    code.jump_if(Condition.NOT_EQUAL, "closeup_stock_identity_match")
    code += b"\xf6\xc3\x03"
    code.jump_if(Condition.NOT_EQUAL, "closeup_stock_identity_match")
    code += b"\xb9" + struct.pack("<I", owner._replacement_reference_height)
    code.jump("scale_closeup")

    code.label("closeup_stock_identity_match")
    code += b"\xb9" + struct.pack("<I", owner._reference_height)
    code.jump("scale_closeup")

    # MS3I is identified independently of the CloseupLayer tag. Every panel
    # replacement is exactly the complete 2560x1920 canvas, so keep that exact
    # proof rather than inheriting the generic variable-aspect classifier.
    # Like the stock 640x480 panel at
    # 1024x768, divide the replacement by the 4x *reference* height. This
    # uses its extra pixels as detail while preserving the authored visual
    # size and centered placement at every physical resolution.
    code.label("museum_size_gate")
    code += b"\x8b\x46\x38"
    # The museum tag also identifies the original 640x480 panel. Skipping it
    # leaves the bottom-anchored control transform applied to physical artwork
    # at high resolutions. Both supported densities need explicit ownership.
    code += b"\x3d" + struct.pack("<I", owner._fixed_screen_width)
    code.jump_if(Condition.NOT_EQUAL, "museum_replacement_size")
    code += b"\x81\xfb" + struct.pack("<I", owner._fixed_screen_height)
    code.jump_if(Condition.EQUAL, "closeup_stock_identity_match")
    code.jump("native")
    code.label("museum_replacement_size")
    code += b"\x3d" + struct.pack("<I", owner._closeup_max_width)
    code.jump_if(Condition.NOT_EQUAL, "native")
    code += b"\x81\xfb" + struct.pack("<I", owner._closeup_max_height)
    code.jump_if(Condition.NOT_EQUAL, "native")
    code += b"\xb9" + struct.pack("<I", owner._replacement_reference_height)
    code.label("scale_closeup")
    code += b"\x8b\x46\x38"
    code += b"\xa3" + struct.pack("<I", closeup_raw_width_va)
    code += b"\x89\x1d" + struct.pack("<I", closeup_raw_height_va)
    code += b"\x0f\xaf\x05" + struct.pack("<I", owner._physical_width_va + 4)
    code += b"\x31\xd2"
    code += b"\xf7\xf1\x89\xc7"
    code += b"\x89\x3d" + struct.pack("<I", closeup_target_width_va)
    code += b"\x89\xd8"
    code += b"\x0f\xaf\x05" + struct.pack("<I", owner._physical_width_va + 4)
    code += b"\x31\xd2\xf7\xf1\x89\xc3"
    code += b"\x89\x1d" + struct.pack("<I", closeup_target_height_va)

    code += b"\xa1" + struct.pack("<I", owner._physical_width_va)
    # Native CenterDrawable subtracts separately truncated half extents. Halving
    # the difference instead moves odd-sized documents one pixel left/up.
    code += b"\xd1\xf8\x8b\xcf\xd1\xf9\x29\xc8"
    code += b"\xa3" + struct.pack("<I", closeup_rect_va)
    code += b"\x01\xf8"
    code += b"\xa3" + struct.pack("<I", closeup_rect_va + 8)
    code += b"\xa1" + struct.pack("<I", owner._physical_width_va + 4)
    code += b"\xd1\xf8\x8b\xcb\xd1\xf9\x29\xc8"
    code += b"\xa3" + struct.pack("<I", closeup_rect_va + 4)
    code += b"\x01\xd8"
    code += b"\xa3" + struct.pack("<I", closeup_rect_va + 12)

    code += b"\x31\xc0"
    code += b"\xa3" + struct.pack("<I", source_rect_va)
    code += b"\xa3" + struct.pack("<I", source_rect_va + 4)
    code += b"\x8b\x46\x38"
    code += b"\xa3" + struct.pack("<I", source_rect_va + 8)
    code += b"\x8b\x46\x3c"
    code += b"\xa3" + struct.pack("<I", source_rect_va + 12)
    code += b"\xc7\x44\x24\x28" + struct.pack("<I", closeup_rect_va)
    code += b"\xc7\x44\x24\x2c" + struct.pack("<I", source_rect_va)
    code += b"\xff\x05" + struct.pack("<I", closeup_transform_count_va)
    code.jump("native")

    code.label("native")
    code += b"\x61"
    code.jump_absolute(owner._native_blt_va)
    code.label("timeblock_handled")
    code += b"\xc7\x05" + struct.pack("<I", tbt_handled_flag_va) + b"\x00\x00\x00\x00"
    code += b"\x61"
    code += b"\xa1" + struct.pack("<I", tbt_handled_result_va)
    code += b"\xc2\x0c\x00"
    return code.build()


def build_closeup_identity_tag(
    owner: ResourceDispatchCompiler,
    *,
    wrapper_va: int,
    active_handle_va: int,
    active_surface_va: int,
    museum_surface_va: int,
    closeup_sprite_va: int,
    resource_lookup_active_va: int,
) -> bytes:
    """Publish the exact close-up resource identity around native centering."""
    # CloseupLayer has already attached its bitmap resource when it calls
    # the native centering helper.  Record the resource's surface wrapper
    # so the shared final blitter can distinguish a close-up from other 4x
    # resources with identical dimensions (LOADSAVE, TBT, DM, and others).
    code = X86Emitter(base_va=wrapper_va)
    code += b"\x60"
    code += b"\x8b\x44\x24\x18"  # sprite / saved ECX after PUSHAD
    code += b"\x85\xc0"
    code.jump_if(Condition.EQUAL, "native")
    code += b"\xa3" + struct.pack("<I", closeup_sprite_va)
    code += b"\x8b\x40\x2c\x85\xc0"
    code.jump_if(Condition.EQUAL, "native")
    # CloseupLayer stores an encoded bitmap handle, not the resolved bitmap
    # resource used by FUN_0046709A.  Resolve that handle here, at the safe
    # ownership boundary, then retain resource+0x30: the exact low-level
    # source wrapper later received by the shared final blitter.
    code += b"\x8b\x40\x20"
    code += b"\xa3" + struct.pack("<I", active_handle_va)
    code += b"\xc7\x05" + struct.pack("<I", active_surface_va) + b"\x00\x00\x00\x00"
    # This slot describes the currently attached CloseupLayer resource,
    # not any historical MS3I allocation.  Clearing it here prevents a
    # freed surface address from being mistaken for a later museum panel.
    code += b"\xc7\x05" + struct.pack("<I", museum_surface_va) + b"\x00\x00\x00\x00"
    code += b"\x8b\x0d" + struct.pack("<I", owner._resource_manager_va)
    code += b"\xc7\x05" + struct.pack("<I", resource_lookup_active_va) + b"\x01\x00\x00\x00"
    code += b"\x50"
    code.call_absolute(owner._resolve_bitmap_resource_va)
    code += b"\xc7\x05" + struct.pack("<I", resource_lookup_active_va) + b"\x00\x00\x00\x00"
    code += b"\x85\xc0"
    code.jump_if(Condition.EQUAL, "native")
    # The bitmap-entry probe is useful for resources created through the
    # normal drawable path, but cached CloseupLayer resources can bypass
    # that entry after startup.  We still have the authoritative resource
    # pointer here, so tag MS3I at this ownership boundary as well.
    code += b"\x81\x78\x08" + owner._museum_resource_prefix
    code.jump_short_if(Condition.NOT_EQUAL, "surface_ready")
    code += b"\x8b\x50\x30"
    code += b"\x89\x15" + struct.pack("<I", museum_surface_va)
    code.label("surface_ready")
    code += b"\x8b\x40\x30"
    code += b"\xa3" + struct.pack("<I", active_surface_va)
    code.label("native")
    code += b"\x61"
    code.jump_absolute(owner._native_center_va)
    return code.build()


def build_bitmap_identity_probe(
    owner: ResourceDispatchCompiler,
    *,
    wrapper_va: int,
    resource_va: int,
    child_va: int,
    handle_va: int,
    surface_va: int,
    driving_map_input_active_va: int,
    resource_lookup_active_va: int,
    tbt_resource_va: int,
    tbt_surface_va: int,
    museum_surface_va: int,
    resolve_bitmap_resource_target_va: int,
) -> bytes:
    """Publish exact bitmap resources and surfaces at their creation boundary."""
    code = X86Emitter(base_va=wrapper_va)
    code += b"\x60"
    code += b"\x83\x3d" + struct.pack("<I", resource_lookup_active_va) + b"\x00"
    code.jump_if(Condition.NOT_EQUAL, "native")
    code += b"\x8b\x44\x24\x18\x8b\x40\x2c"
    code += b"\x85\xc0"
    code.jump_if(Condition.EQUAL, "native")
    code += b"\x8b\x0d" + struct.pack("<I", owner._resource_manager_va)
    code += b"\xc7\x05" + struct.pack("<I", resource_lookup_active_va) + b"\x01\x00\x00\x00"
    code += b"\x50"
    code.call_absolute(resolve_bitmap_resource_target_va)
    code += b"\xc7\x05" + struct.pack("<I", resource_lookup_active_va) + b"\x00\x00\x00\x00"
    code += b"\x85\xc0"
    code.jump_if(Condition.EQUAL, "native")

    # Exact print overlays keep logical hit bounds even with dense source art.
    code.raw(b"\x8b\x4c\x24\x18")
    code.call_absolute(
        owner.symbols.va(FINGERPRINT_ALPHA_SEGMENT.logical_name, FINGERPRINT_ALPHA_NORMALIZE_OFFSET)
    )

    # Museum panels need no unsafe caller-frame reconstruction in the
    # shared final blitter.  Resource entry is the authoritative point at
    # which both the MS3I name and its low-level source wrapper coexist.
    code += b"\x81\x78\x08" + owner._museum_resource_prefix
    code.jump_short_if(Condition.NOT_EQUAL, "check_driving_map")
    code += b"\x8b\x50\x30"
    code += b"\x89\x15" + struct.pack("<I", museum_surface_va)

    code.label("check_driving_map")
    code += b"\x81\x78\x08" + b"DM_B"
    code.jump_if(Condition.NOT_EQUAL, "check_tbt")
    code += b"\x81\x78\x0c" + b"ASE\x00"
    code.jump_if(Condition.NOT_EQUAL, "check_tbt")
    code += b"\xa3" + struct.pack("<I", resource_va)
    code += b"\x8b\x40\x30\xa3" + struct.pack("<I", surface_va)
    code += b"\x8b\x44\x24\x18\xa3" + struct.pack("<I", child_va)
    code += b"\x8b\x40\x2c\xa3" + struct.pack("<I", handle_va)
    # DM_BASE is created synchronously while the travel command is still
    # unwinding. Publish map input ownership here, before the MouseManager's
    # remaining dispatch slots run, so that first event cannot leave a stale
    # room hover/caption in the newly constructed map. The exact bitmap-node
    # destructor withdraws this lifetime flag.
    code += b"\xc7\x05" + struct.pack("<I", driving_map_input_active_va)
    code += b"\x01\x00\x00\x00"
    code.jump("native")
    code.label("check_tbt")
    code += b"\x66\x81\x78\x08TB"
    code.jump_if(Condition.NOT_EQUAL, "native")
    code += b"\x80\x78\x0aT"
    code.jump_if(Condition.NOT_EQUAL, "native")
    code += b"\xa3" + struct.pack("<I", tbt_resource_va)
    code += b"\x8b\x40\x30\xa3" + struct.pack("<I", tbt_surface_va)

    code.label("native")
    code += b"\x61" + owner._bitmap_entry_original
    code.jump_absolute(owner._bitmap_entry_va + 5)
    return code.build()
