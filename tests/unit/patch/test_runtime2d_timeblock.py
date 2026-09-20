"""Machine-code contracts for TimeBlock model and presentation ownership."""

from __future__ import annotations

import struct
from dataclasses import replace
from typing import cast

from gk3hd.patch.binary.x86 import BranchOpcode, decode_rel32_branch
from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.guard_stale_mouse_move_targets import MouseMoveDispatchABI
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameABI
from gk3hd.patch.definitions.runtime2d.layout import (
    FINGERPRINT_ALPHA_SEGMENT,
    SIDNEY_PRESENTATION_SEGMENT,
    SYSTEM_ACTION_PRESENTED_ROOT_OFFSET,
    SYSTEM_CONTROL_SEGMENT,
    SYSTEM_SEGMENT,
    TIMEBLOCK_RAW_HEIGHT_OFFSET,
    TIMEBLOCK_SEGMENT,
    RuntimeSegmentAddress,
    RuntimeSymbols,
)
from gk3hd.patch.definitions.runtime2d.resource_driving_map import (
    build_draw_scope as build_driving_map_draw_scope,
)
from gk3hd.patch.definitions.runtime2d.resource_selection import (
    build_bitmap_identity_probe,
    build_resource_blit_dispatcher,
)
from gk3hd.patch.definitions.runtime2d.resource_timeblock import build_blit as build_timeblock_blit
from gk3hd.patch.definitions.runtime2d.resource_timeblock import (
    build_center as build_timeblock_center,
)
from gk3hd.patch.definitions.runtime2d.resource_timeblock import (
    build_root_draw as build_timeblock_root_draw,
)
from gk3hd.patch.definitions.runtime2d.resources import ResourceDispatchCompiler
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.sidney_input import (
    build_button_dispatch_adapter,
    build_button_dispatch_stub,
    build_button_dispatch_thunk,
    build_tbt_input_wrapper,
)
from gk3hd.patch.definitions.runtime2d.sidney_presentation import SidneyPresentationCompiler


def _compiler() -> ResourceDispatchCompiler:
    """Build the resource emitter with its one cross-segment native entry."""
    return ResourceDispatchCompiler(
        symbols=RuntimeSymbols(
            segments=(
                RuntimeSegmentAddress(FINGERPRINT_ALPHA_SEGMENT, 0, 0, 0x007E0000),
                RuntimeSegmentAddress(SIDNEY_PRESENTATION_SEGMENT, 0, 0, 0x007C0000),
                RuntimeSegmentAddress(TIMEBLOCK_SEGMENT, 0, 0, 0x007D0000),
            )
        ),
        profile=GOG_BUILD,
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00790000,
            room_presentation_active_va=0x00790008,
            pre_flip_presenter_slot_va=0x00790004,
            post_flip_presenter_slot_va=0x0079000C,
        ),
    )


def _presentation_compiler() -> SidneyPresentationCompiler:
    """Build the shared input emitter with inert external ABI addresses."""
    return SidneyPresentationCompiler(
        symbols=cast("RuntimeSymbols", object()),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        mouse_move_abi=MouseMoveDispatchABI(ui_dispatch_adapter_slot_va=0x00790014),
    )


def test_timeblock_input_reads_the_renderers_current_segment_and_offsets() -> None:
    resource = _compiler()
    presentation = replace(_presentation_compiler(), symbols=resource.symbols)
    base = resource.symbols.va(TIMEBLOCK_SEGMENT.logical_name)
    assert presentation._tbt_input_vas() == (
        base + resource._off_tbt_layer,
        base + resource._off_tbt_logical_rect,
        base + resource._off_tbt_target_rect,
    )


def test_button_dispatch_adapts_only_ui_calls_not_mouse_manager_slots() -> None:
    """Down/up anchors must stay physical for the native drag threshold."""
    compiler = _presentation_compiler()
    assert len(compiler._button_dispatch_sites) == 10
    assert ("drag_begin", 5) in compiler._button_dispatch_sites
    for name, count in compiler._button_dispatch_sites:
        site = GOG_BUILD.site(f"input.{name}_dispatch_call")
        assert site.original[0] == BranchOpcode.CALL
        assert 1 <= count <= 5
        target = decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=site.va,
            instruction=site.original,
        )
        assert target is not None
        stub = build_button_dispatch_stub(
            stub_va=0x00800000,
            wrapper_va=0x00801000,
            original_va=target,
            argument_count=count,
        )
        assert stub[:10] == b"\xb8" + struct.pack("<I", target) + b"\xba" + struct.pack("<I", count)
        assert len(stub) == 15


def test_button_dispatch_preserves_context_and_callee_cleanup() -> None:
    """Variable-arity native events share one reversible POINT scope."""
    adapter = build_button_dispatch_adapter(
        wrapper_va=0x00800000,
        input_wrapper_va=0x00801000,
        thunk_va=0x00802000,
    )
    assert bytes.fromhex("89 4d e0 89 45 e4 89 55 e8") in adapter
    assert bytes.fromhex("8b ca 8d 75 08 8d 7d ec fc f3 a5") in adapter
    # LEAVE; skip the original return and count*4 arguments; JMP saved return.
    assert adapter.endswith(bytes.fromhex("8b 4d e8 8b 55 04 c9 8d 64 8c 04 ff e2"))
    thunk = build_button_dispatch_thunk(wrapper_va=0x00802000)
    assert bytes.fromhex("ff 74 8e 08 49") in thunk  # push arguments in reverse
    assert bytes.fromhex("8b 0e ff 56 04 5e c2 04 00") in thunk
    assert bytes.fromhex("8b 10 89 56 e4 8b 50 04 89 56 e8") in thunk


def test_drag_begin_maps_private_anchor_but_preserves_mouse_manager_storage() -> None:
    site = GOG_BUILD.site("input.drag_begin_dispatch_call")
    assert site.va == 0x49AC02
    assert (
        decode_rel32_branch(opcode=BranchOpcode.CALL, site_va=site.va, instruction=site.original)
        == 0x4BF061
    )
    # Native bookkeeping immediately afterward must still read the physical
    # cursor. Drag-begin uses a private inverse-mapped second POINT for native
    # slider hit testing, without changing MouseManager's physical anchor.
    assert site.context_after == bytes.fromhex("a1 10 6f 70 00 89 03")
    stub = build_button_dispatch_stub(
        stub_va=0x00800000,
        wrapper_va=0x00801000,
        original_va=0x4BF061,
        argument_count=5,
        map_drag_anchor=True,
    )
    assert stub[5:10] == bytes.fromhex("ba 05 00 00 80")
    adapter = build_button_dispatch_adapter(
        wrapper_va=0x00800000,
        input_wrapper_va=0x00801000,
        thunk_va=0x00802000,
    )
    # Private POINT at EBP-0x3c replaces only context argument two (EBP-0x10).
    assert bytes.fromhex("8d 45 c4 89 45 f0") in adapter


def test_room_input_reads_action_ownership_from_the_system_segment() -> None:
    """Moving ActionMenu state cannot silently redirect room input into cursor scratch."""
    system_va = 0x007A0000
    control_va = 0x007B0000
    symbols = RuntimeSymbols(
        segments=(
            RuntimeSegmentAddress(SYSTEM_SEGMENT, 0, 0, system_va),
            RuntimeSegmentAddress(SYSTEM_CONTROL_SEGMENT, 0, 0, control_va),
        )
    )
    compiler = SidneyPresentationCompiler(
        symbols=symbols,
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        mouse_move_abi=MouseMoveDispatchABI(ui_dispatch_adapter_slot_va=0x00790014),
    )

    assert compiler._system_input_vas()[5] == system_va + SYSTEM_ACTION_PRESENTED_ROOT_OFFSET
    assert compiler._system_input_vas()[5] < control_va


def _call_targets(payload: bytes, base_va: int) -> list[int]:
    """Decode every exact rel32 CALL in one generated wrapper."""
    targets: list[int] = []
    for offset in range(len(payload) - 4):
        target = decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=base_va + offset,
            instruction=payload[offset : offset + 5],
        )
        if target is not None:
            targets.append(target)
    return targets


def test_driving_map_exact_draw_uses_complete_damage() -> None:
    """The live map redraws coherently instead of replaying partial layers."""
    compiler = _compiler()
    wrapper_va = 0x007A0000
    scope_va = 0x007B0000
    input_active_va = 0x007B0004
    children_scaled_va = 0x007B000C
    child_rect_count_va = 0x007B0034
    child_rects_va = 0x007B0040
    full_region_va = 0x007B0010
    full_rect_va = 0x007B0020
    payload = build_driving_map_draw_scope(
        compiler,
        wrapper_va=wrapper_va,
        scope_active_va=scope_va,
        input_active_va=input_active_va,
        base_child_va=0x007B0030,
        children_scaled_va=children_scaled_va,
        child_rect_count_va=child_rect_count_va,
        child_rects_va=child_rects_va,
        full_draw_count_va=0x007B0008,
        full_damage_region_va=full_region_va,
        full_damage_rect_va=full_rect_va,
        system_render_state_vas=(0x007C0010, 0x007C0014, 0x007C0018),
    )

    assert b"\x83\x3d" + struct.pack("<I", input_active_va) + b"\x00" in payload
    for address in (0x007C0010, 0x007C0014, 0x007C0018):
        clear = payload.index(b"\xc7\x05" + struct.pack("<I", address) + bytes(4))
        restore = payload.index(b"\x8f\x05" + struct.pack("<I", address))
        assert clear < restore
    assert b"\xff\x74\x24\x18" in payload
    assert b"\x68" + struct.pack("<I", full_region_va) in payload
    assert b"\x89\x15" + struct.pack("<I", full_rect_va + 8) in payload
    assert b"\x0f\xaf\x05" + struct.pack("<I", compiler._physical_width_va) in payload
    assert b"\x0f\xaf\x05" + struct.pack("<I", compiler._physical_width_va + 4) in payload
    assert b"\x3b\x0d" + struct.pack("<I", 0x007B0030) in payload
    assert b"\xa1" + struct.pack("<I", child_rect_count_va) in payload
    assert b"\xc1\xe0\x04\x05" + struct.pack("<I", child_rects_va) in payload
    assert b"\xc7\x05" + struct.pack("<I", children_scaled_va) + b"\x01\x00\x00\x00" in payload


def test_driving_map_blitter_keeps_one_physical_affine_for_base_and_locations() -> None:
    """Map locations keep live extents; dense texels do not resize them."""
    compiler = _compiler()
    state = iter(range(0x007B0000, 0x007B0200, 4))
    driving_surface_va = next(state)
    map_child_rect_count_va = 0x007B0304
    map_child_rects_va = 0x007B0310
    payload = build_resource_blit_dispatcher(
        compiler,
        wrapper_va=0x007A0000,
        dest_rect_va=next(state),
        source_rect_va=next(state),
        slider_trace_count_va=next(state),
        slider_last_record_va=next(state),
        slider_transform_count_va=next(state),
        closeup_transform_count_va=next(state),
        closeup_raw_width_va=next(state),
        closeup_raw_height_va=next(state),
        closeup_target_width_va=next(state),
        closeup_target_height_va=next(state),
        closeup_rect_va=next(state),
        closeup_active_surface_va=next(state),
        museum_surface_va=next(state),
        closeup_observed_source_va=next(state),
        resource_lookup_active_va=next(state),
        progress_draw_depth_va=next(state),
        progress_transform_count_va=next(state),
        driving_map_surface_va=driving_surface_va,
        driving_map_transform_count_va=next(state),
        driving_map_rect_va=next(state),
        driving_map_scope_active_va=next(state),
        driving_map_seen_va=next(state),
        driving_map_child_rect_count_va=map_child_rect_count_va,
        driving_map_child_rects_va=map_child_rects_va,
        driving_map_source_grid_rect_va=0x007B0400,
        tbt_blit_wrapper_va=0x007C0000,
        tbt_handled_flag_va=next(state),
        tbt_handled_result_va=next(state),
        fingerprint_blit_wrapper_va=0x007C1000,
    )

    assert b"\x3b\x05" + struct.pack("<I", driving_surface_va) in payload
    # The same dispatcher centers close-ups using separate half extents, as
    # native CenterDrawable does, including odd-sized fingerprint cards.
    assert b"\xd1\xf8\x8b\xcf\xd1\xf9\x29\xc8" in payload
    assert b"\xd1\xf8\x8b\xcb\xd1\xf9\x29\xc8" in payload
    # A tagged museum panel accepts the original complete 640x480 canvas as
    # well as its 4x replacement; a stock tag must not skip physical placement.
    museum_gate = payload.index(
        b"\x8b\x46\x38\x3d" + struct.pack("<I", compiler._fixed_screen_width)
    )
    assert (
        b"\x81\xfb" + struct.pack("<I", compiler._fixed_screen_height)
        in payload[museum_gate : museum_gate + 30]
    )
    assert b"\x8b\x47\x08\x2b\x07\x3d\x80\x00\x00\x00" in payload
    assert b"\x8b\x0d" + struct.pack("<I", map_child_rect_count_va) in payload
    assert b"\xba" + struct.pack("<I", map_child_rects_va) in payload
    assert b"\x8b\x46\x08\x2b\x06\xc1\xf8\x02\x03\x06\x89\x46\x08" in payload
    assert b"\x8b\x0d" + struct.pack("<I", compiler._physical_width_va) in payload
    assert 0x007B0400 in _call_targets(payload, 0x007A0000)


def test_bitmap_probe_leaves_button_geometry_to_the_shared_dimension_adapter() -> None:
    """Exact resource dimensions, not late model rewrites, own font buttons."""
    compiler = _compiler()
    state = iter(range(0x007B0000, 0x007B0200, 4))
    driving_map_input_active_va = next(state)
    payload = build_bitmap_identity_probe(
        compiler,
        wrapper_va=0x007A0000,
        resource_va=next(state),
        child_va=next(state),
        handle_va=next(state),
        surface_va=next(state),
        driving_map_input_active_va=driving_map_input_active_va,
        resource_lookup_active_va=next(state),
        tbt_resource_va=next(state),
        tbt_surface_va=next(state),
        museum_surface_va=next(state),
        resolve_bitmap_resource_target_va=0x007C1000,
    )

    assert b"\x81\x78\x08RC_S" not in payload
    assert b"\xc1\xf9\x02\x03\x4f\x1c\x89\x4f\x24" not in payload
    assert (
        b"\xc7\x05" + struct.pack("<I", driving_map_input_active_va) + b"\x01\x00\x00\x00"
    ) in payload


def test_timeblock_construction_records_dimensions_without_rewriting_model() -> None:
    """The constructor hook must not retain authored presentation geometry."""
    compiler = _compiler()
    wrapper_va = 0x007A0000
    payload = build_timeblock_center(
        compiler,
        wrapper_va=wrapper_va,
        layer_va=0x007A1000,
        clear_budget_va=0x007A1004,
        raw_width_va=0x007A1008,
        raw_height_va=0x007A100C,
        control_seen_va=0x007A1010,
        control_count_va=0x007A1014,
    )

    # MOV [ECX+24h]/[ECX+28h] were the permanent-bound writes that made a
    # direct TimeBlock save fail deserialization. Construction now only records
    # ownership/data and tail-calls GK3's native centering helper.
    assert b"\x89\x41\x24" not in payload
    assert b"\x89\x51\x28" not in payload
    # The unique TimeBlock constructor call-site establishes class ownership;
    # its root must independently match the exact 2560x1920 replacement asset.
    assert b"\x8b\x41\x24\x2b\x41\x1c\x3d\x00\x0a\x00\x00" in payload
    assert b"\x8b\x51\x28\x2b\x51\x20\x81\xfa\x80\x07\x00\x00" in payload
    # The former fuzzy root-size classifier is intentionally absent.
    assert b"\x3d\xc4\x09\x00\x00" not in payload
    assert b"\x3d\x28\x0a\x00\x00" not in payload
    assert _call_targets(payload, wrapper_va) == []
    assert decode_rel32_branch(
        opcode=BranchOpcode.JUMP,
        site_va=wrapper_va + len(payload) - 5,
        instruction=payload[-5:],
    ) == GOG_BUILD.address("ui.center_drawable")


def test_timeblock_draw_owns_reversible_geometry_and_native_fallback() -> None:
    """Only active Draw scopes authored bounds, with an exact native fallback."""
    compiler = _compiler()
    wrapper_va = 0x007A2000
    layer_va = 0x007A5000
    raw_width_va = 0x007A5004
    raw_height_va = 0x007A5008
    draw_scope_active_va = 0x007A500C
    clear_budget_va = 0x007A5010
    control_seen_va = 0x007A5184
    payload = build_timeblock_root_draw(
        compiler,
        wrapper_va=wrapper_va,
        overlay_draw_va=0x007A6000,
        clear_budget_va=clear_budget_va,
        clear_count_va=0x007A5014,
        bltfx_va=0x007A5100,
        clear_flip_count_va=0x007A5180,
        successful_flip_count_va=0x00790000,
        layer_va=layer_va,
        draw_scope_active_va=draw_scope_active_va,
        raw_width_va=raw_width_va,
        raw_height_va=raw_height_va,
        control_seen_va=control_seen_va,
        control_count_va=0x007A5188,
    )
    targets = _call_targets(payload, wrapper_va)

    assert GOG_BUILD.address("ui.current_layer") in targets
    assert targets.count(GOG_BUILD.address("ui.center_drawable")) == 2
    # One active scoped call plus one unowned exact-native fallback.
    assert targets.count(GOG_BUILD.address("timeblock.draw")) == 1
    assert 0x007A6000 in targets
    assert struct.pack("<I", raw_width_va) in payload
    assert struct.pack("<I", raw_height_va) in payload
    # Restore reconstruction can bypass the constructor-only ownership tag.
    # The unique active Draw boundary must recover ownership from exact live
    # resolved bitmap dimensions, retain the actual bitmap model, and initialize
    # both DirectDraw pages itself.
    assert b"\x8b\x41\x24\x2b\x41\x1c\x3d\x00\x0a\x00\x00" in payload
    assert b"\x51\xff\x71\x2c\x8b\x0d" in payload
    assert GOG_BUILD.address("bitmap.resolve_resource") in targets
    assert b"\x8b\x50\x3c\x81\xfa\x80\x07\x00\x00" in payload
    assert b"\x81\xfa\x84\x07\x00\x00" in payload
    assert b"\x89\x0d" + struct.pack("<I", layer_va) in payload
    assert b"\xc7\x05" + struct.pack("<I", raw_width_va) + b"\x00\x0a\x00\x00" in payload
    assert b"\x89\x15" + struct.pack("<I", raw_height_va) in payload
    assert b"\xc7\x05" + struct.pack("<I", raw_height_va) not in payload
    assert b"\xc7\x05" + struct.pack("<I", clear_budget_va) + b"\x02\x00\x00\x00" in payload
    assert b"\xc7\x05" + struct.pack("<I", draw_scope_active_va) + b"\x01\x00\x00\x00" in payload
    assert b"\xc7\x05" + struct.pack("<I", draw_scope_active_va) + b"\x00\x00\x00\x00" in payload
    assert b"\xc7\x05" + struct.pack("<I", control_seen_va) + b"\x00\x00\x00\x00" in payload
    # Both scoped tree moves suppress the native visible-move invalidation and
    # restore the exact saved visibility byte immediately after centering.
    hide = b"\x0f\xb6\x41\x18\x50\xc6\x41\x18\x00"
    restore = b"\x59\x58\x88\x41\x18"
    assert payload.count(hide) == 2
    assert payload.count(restore) == 2


def test_timeblock_cursor_bypass_uses_exact_runtime_ownership() -> None:
    """Scaled cursor backing must never be classified by stock dimensions."""
    compiler = _compiler()
    cursor_state_va = 0x00801000
    payload = build_timeblock_blit(
        compiler,
        wrapper_va=0x007A2000,
        tbt_surface_va=0x007A3000,
        transform_count_va=0x007A3004,
        background_count_va=0x007A3008,
        logical_rect_va=0x007A3010,
        target_rect_va=0x007A3020,
        dest_rect_va=0x007A3030,
        source_rect_va=0x007A3040,
        control_seen_va=0x007A3060,
        control_logical_rect_va=0x007A3070,
        control_source_rect_va=0x007A3080,
        control_target_rect_va=0x007A3090,
        control_replay_count_va=0x007A30A0,
        control_count_va=0x007A30A4,
        control_slots_va=0x007A3100,
        handled_flag_va=0x007A30A8,
        handled_result_va=0x007A30AC,
        layer_va=0x007A3050,
        draw_scope_active_va=0x007A3058,
        cursor_state_va=cursor_state_va,
        cursor_bypass_count_va=0x007A3054,
    )

    # Generic BitmapDrawable scope (+76) includes ordinary TimeBlock children
    # and is therefore not cursor ownership. Only the producer-learned exact
    # atlas/composition/save-under wrapper identities may bypass fitting.
    assert b"\x83\x3d" + struct.pack("<I", cursor_state_va + 76) + b"\x00" not in payload
    for state_offset in (80, 72, 88):
        assert b"\x3b\x05" + struct.pack("<I", cursor_state_va + state_offset) in payload
    # The obsolete 128x128 width/height classifier caused UHD backing traffic
    # to leak through the TimeBlock affine.
    assert b"\x81\x78\x38\x80\x00\x00\x00" not in payload
    assert b"\x81\x78\x3c\x80\x00\x00\x00" not in payload

    # A former TimeBlock pointer can refer to recycled allocation data after
    # Play/Restore. Only the root's synchronous presentation scope permits
    # borrowing it, without querying the dispatcher from the shared blitter.
    identity = payload.index(b"\xa1" + struct.pack("<I", 0x007A3050))
    scope = b"\x83\x3d" + struct.pack("<I", 0x007A3058) + b"\x00"
    assert payload[identity - 13 : identity - 6] == scope
    assert payload[identity - 6 : identity - 4] == b"\x0f\x84"
    class_check = payload.index(
        b"\x81\x38" + struct.pack("<I", GOG_BUILD.address("timeblock.vtable"))
    )
    visible = payload.index(b"\x80\xb8\xc0\x03\x00\x00\x00")
    assert identity < class_check < visible
    assert payload[class_check + 6 : class_check + 8] == b"\x0f\x85"
    assert GOG_BUILD.address("ui.current_layer") not in _call_targets(payload, 0x007A2000)


def test_timeblock_blitter_requires_exact_replacement_surface_dimensions() -> None:
    """TBT accepts only exact constructor or scoped restore surface contracts."""
    compiler = _compiler()
    tbt_surface_va = 0x007A3000
    draw_scope_active_va = 0x007A3058
    payload = build_timeblock_blit(
        compiler,
        wrapper_va=0x007A2000,
        tbt_surface_va=tbt_surface_va,
        transform_count_va=0x007A3004,
        background_count_va=0x007A3008,
        logical_rect_va=0x007A3010,
        target_rect_va=0x007A3020,
        dest_rect_va=0x007A3030,
        source_rect_va=0x007A3040,
        control_seen_va=0x007A3060,
        control_logical_rect_va=0x007A3070,
        control_source_rect_va=0x007A3080,
        control_target_rect_va=0x007A3090,
        control_replay_count_va=0x007A30A0,
        control_count_va=0x007A30A4,
        control_slots_va=0x007A3100,
        handled_flag_va=0x007A30A8,
        handled_result_va=0x007A30AC,
        layer_va=0x007A3050,
        draw_scope_active_va=draw_scope_active_va,
        cursor_state_va=0x00801000,
        cursor_bypass_count_va=0x007A3054,
    )

    assert b"\x81\x78\x38\x00\x0a\x00\x00" in payload
    assert b"\x81\x78\x3c\x80\x07\x00\x00" in payload
    assert b"\x81\x78\x3c\x84\x07\x00\x00" in payload
    assert b"\x83\x3d" + struct.pack("<I", draw_scope_active_va) + b"\x00" in payload
    assert b"\xa3" + struct.pack("<I", tbt_surface_va) in payload
    # Presentation uses the exact bitmap model, never the reconstructed
    # container's extra four-pixel lower layout extent.
    assert b"\xbe\x80\x02\x00\x00" in payload
    raw_height_va = compiler.symbols.va(TIMEBLOCK_SEGMENT.logical_name, TIMEBLOCK_RAW_HEIGHT_OFFSET)
    assert b"\x8b\x3d" + struct.pack("<I", raw_height_va) + b"\xc1\xef\x02" in payload
    assert b"\xa1" + struct.pack("<I", raw_height_va) in payload
    # The obsolete source bottom 1740 was the full-width 45-row crop.
    assert b"\xb9\xcc\x06\x00\x00" not in payload
    assert b"\x81\x78\x38\xc4\x09\x00\x00" not in payload
    assert b"\x81\x78\x3c\x8a\x07\x00\x00" not in payload


def test_timeblock_background_replays_only_observed_bottom_controls() -> None:
    """Complete dense card art is followed by exact native control replays."""
    compiler = _compiler()
    wrapper_va = 0x007A2000
    control_seen_va = 0x007A3060
    control_logical_rect_va = 0x007A3070
    control_replay_count_va = 0x007A30A0
    payload = build_timeblock_blit(
        compiler,
        wrapper_va=wrapper_va,
        tbt_surface_va=0x007A3000,
        transform_count_va=0x007A3004,
        background_count_va=0x007A3008,
        logical_rect_va=0x007A3010,
        target_rect_va=0x007A3020,
        dest_rect_va=0x007A3030,
        source_rect_va=0x007A3040,
        control_seen_va=control_seen_va,
        control_logical_rect_va=control_logical_rect_va,
        control_source_rect_va=0x007A3080,
        control_target_rect_va=0x007A3090,
        control_replay_count_va=control_replay_count_va,
        control_count_va=0x007A30A4,
        control_slots_va=0x007A3100,
        handled_flag_va=0x007A30A8,
        handled_result_va=0x007A30AC,
        layer_va=0x007A3050,
        draw_scope_active_va=0x007A3058,
        cursor_state_va=0x00801000,
        cursor_bypass_count_va=0x007A3054,
    )

    assert b"\x83\x3d" + struct.pack("<I", control_seen_va) + b"\x01" in payload
    assert b"\x83\xe8\x2d\x3b\x46\x04" in payload
    for offset in range(0, 16, 4):
        assert struct.pack("<I", control_logical_rect_va + offset) in payload
    # One complete background plus two bounded control slots invoke the
    # pristine blitter; no synthetic split rectangle or crop is emitted.
    assert _call_targets(payload, wrapper_va).count(compiler._native_blt_trampoline_va) == 3
    assert payload.count(b"\xff\x05" + struct.pack("<I", control_replay_count_va)) == 2


def test_timeblock_input_returns_temporary_draw_points_to_persistent_root_space() -> None:
    """Native hit testing receives the durable child RECT coordinate domain."""
    compiler = _presentation_compiler()
    root_ptr_va = 0x007A6000
    logical_rect_va = 0x007A6010
    payload = build_tbt_input_wrapper(
        compiler,
        input_transform_count_va=0x007A6040,
        input_source_x_va=0x007A6044,
        input_logical_x_va=0x007A6048,
        input_logical_y_va=0x007A604C,
        logical_rect_va=logical_rect_va,
        target_rect_va=0x007A6020,
        persistent_root_va=root_ptr_va,
    )

    root_load = b"\x8b\x15" + struct.pack("<I", root_ptr_va) + b"\x85\xd2"
    assert payload.count(root_load) == 2
    assert b"\x2b\x05" + struct.pack("<I", logical_rect_va) + b"\x03\x42\x1c" in payload
    assert b"\x2b\x05" + struct.pack("<I", logical_rect_va + 4) + b"\x03\x42\x20" in payload
    assert compiler._off_tbt_input_helper + len(payload) <= compiler._off_system_input_helper
    assert (
        compiler._off_input_stubs + len(compiler._button_dispatch_sites) * compiler._input_stub_size
        <= compiler._section_size
    )
