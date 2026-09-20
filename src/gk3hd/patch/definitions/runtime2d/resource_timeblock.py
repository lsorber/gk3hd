"""Emit TimeBlock model restoration, fitting, clearing, and blits."""

# These emitters are one physical part of ResourceDispatchCompiler and consume
# its private recovered ABI directly; copying that ABI into a second public
# configuration object would add state and permit the two views to drift.
# ruff: noqa: SLF001

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.layout import (
    TIMEBLOCK_OVERLAY_SURFACE_OFFSET,
    TIMEBLOCK_RAW_HEIGHT_OFFSET,
    TIMEBLOCK_SEGMENT,
)
from gk3hd.patch.definitions.runtime2d.timeblock_overlay import emit_card_height

if TYPE_CHECKING:
    from gk3hd.patch.definitions.runtime2d.resources import ResourceDispatchCompiler


def build_blit(
    owner: ResourceDispatchCompiler,
    *,
    wrapper_va: int,
    tbt_surface_va: int,
    transform_count_va: int,
    background_count_va: int,
    logical_rect_va: int,
    target_rect_va: int,
    dest_rect_va: int,
    source_rect_va: int,
    control_seen_va: int,
    control_logical_rect_va: int,
    control_source_rect_va: int,
    control_target_rect_va: int,
    control_replay_count_va: int,
    control_count_va: int,
    control_slots_va: int,
    handled_flag_va: int,
    handled_result_va: int,
    layer_va: int,
    draw_scope_active_va: int,
    cursor_state_va: int,
    cursor_bypass_count_va: int,
) -> bytes:
    """Transform TBT composition calls made inside the outer PUSHAD frame."""
    # At this helper's entry, the caller's PUSHAD frame is four bytes above
    # the return address: source wrapper, destination RECT, and source RECT
    # are consequently at +28, +2C, and +30.
    code = X86Emitter(base_va=wrapper_va)
    code += b"\x8b\x44\x24\x28"
    code += b"\x3b\x05" + struct.pack("<I", tbt_surface_va)
    code.jump_if(Condition.EQUAL, "validate_background")
    # Restore reconstruction can attach an adapter wrapper which differs
    # from resource+0x30 recorded during bitmap lookup. The unique active
    # TimeBlock Draw scope below is a stronger ownership boundary than
    # accepting a second pointer guess; exact dimensions still prove that
    # this call is the one replacement background, not a child or cursor.
    code += b"\x83\x3d" + struct.pack("<I", draw_scope_active_va) + b"\x00"
    code.jump_if(Condition.EQUAL, "transform_identity")

    # Require the authored 4x width and one of the two exact source bitmap
    # heights below. A permissive size window adds no compatibility and
    # weakens provenance.
    code.label("validate_background")
    code += b"\x81\x78\x38" + struct.pack("<I", owner._replacement_screen_width)
    code.jump_if(Condition.NOT_EQUAL, "transform_identity")
    code += b"\x81\x78\x3c" + struct.pack("<I", owner._replacement_screen_height)
    code.jump_if(Condition.EQUAL, "background_dimensions_proven")
    # The exceptional TBT306P bitmap is 2560x1924. Its measured height feeds
    # presentation and sampling; it is not an inclusive container boundary.
    code += b"\x81\x78\x3c" + struct.pack("<I", owner._tall_tbt_background_height)
    code.jump_if(Condition.NOT_EQUAL, "transform_identity")
    code += b"\x83\x3d" + struct.pack("<I", draw_scope_active_va) + b"\x00"
    code.jump_if(Condition.EQUAL, "transform_identity")
    code.label("background_dimensions_proven")
    # Keep the wrapper actually received by the final blitter. Normal
    # construction stores the same value; the restore-only adapter path
    # converges here after the exact scoped proof above.
    code += b"\xa3" + struct.pack("<I", tbt_surface_va)

    # The source identity is exact, but still require a physical-screen
    # destination and non-null RECTs before activating composition scope.
    code += b"\x8b\x54\x24\x1c"
    code += b"\x8b\x0d" + struct.pack("<I", owner._physical_width_va)
    code += b"\x39\x4a\x38"
    code.jump_if(Condition.NOT_EQUAL, "transform_identity")
    code += b"\x8b\x1d" + struct.pack("<I", owner._physical_width_va + 4)
    code += b"\x39\x5a\x3c"
    code.jump_if(Condition.NOT_EQUAL, "transform_identity")
    code += b"\x83\x7c\x24\x2c\x00"
    code.jump_if(Condition.EQUAL, "transform_identity")
    code += b"\x83\x7c\x24\x30\x00"
    code.jump_if(Condition.EQUAL, "transform_identity")

    # Derive exact quarter-size logical dimensions from the HD background.
    code += b"\xbe" + struct.pack("<I", owner._fixed_screen_width)
    raw_height_va = owner.symbols.va(TIMEBLOCK_SEGMENT.logical_name, TIMEBLOCK_RAW_HEIGHT_OFFSET)
    code += b"\x8b\x3d" + struct.pack("<I", raw_height_va) + b"\xc1\xef\x02"
    code += b"\x89\xc8\x29\xf0\xd1\xf8"  # centered logical left
    code += b"\xa3" + struct.pack("<I", logical_rect_va)
    # Native center = screen midpoint minus the truncated authored half-height.
    code += b"\x89\xd8\xd1\xf8\x89\xfa\xd1\xfa\x29\xd0"
    code += b"\xa3" + struct.pack("<I", logical_rect_va + 4)
    code += b"\xa1" + struct.pack("<I", logical_rect_va)
    code += b"\x01\xf0\xa3" + struct.pack("<I", logical_rect_va + 8)
    code += b"\x8b\x05" + struct.pack("<I", logical_rect_va + 4)
    code += b"\x01\xf8\xa3" + struct.pack("<I", logical_rect_va + 12)

    # The stock interface is a centered 640x480 composition inside the
    # 1024x768 reference screen.  Preserve that apparent scale instead of
    # promoting it to a fullscreen 1440x1080 canvas: use the same uniform
    # min(width/1024, height/768) scale as other fixed UI.  At 1920x1080
    # this produces the intended 900x675 target.
    code += b"\x8b\xc1\x6b\xc0\x03\x8b\xd3\xc1\xe2\x02\x3b\xc2"
    code.jump_short_if(Condition.LESS, "tbt_width_limited")
    # Exact 640x480 logical bounds let these ratios stay compact:
    # 640/768 = 5/6 and 480/768 = 5/8.
    code += b"\x6b\xc3\x05\x99\x6a\x06\x5f\xf7\xff\x89\xc6"
    code += b"\x6b\xc3\x05\xc1\xf8\x03\x89\xc3"
    code.jump_short("tbt_scale_ready")
    code.label("tbt_width_limited")
    # Narrow/portrait display: 640/1024 = 5/8 and 480/1024 = 15/32.
    code += b"\x6b\xc1\x05\xc1\xf8\x03\x89\xc6"
    code += b"\x6b\xc1\x0f\xc1\xf8\x05\x89\xc3"
    code.label("tbt_scale_ready")
    emit_card_height(
        code,
        raw_height_va=raw_height_va,
        screen_size_va=owner._physical_width_va,
        destination="ebx",
    )
    emit_card_height(
        code,
        raw_height_va=raw_height_va,
        screen_size_va=owner._physical_width_va,
        destination="edi",
        purpose="centering",
    )
    code += b"\x89\xf2"  # EDX = target width
    code += b"\x89\xc8\x29\xd0\xd1\xf8"
    code += b"\xa3" + struct.pack("<I", target_rect_va)
    code += b"\x8b\x05" + struct.pack("<I", owner._physical_width_va + 4)
    code += b"\x29\xf8\xd1\xf8\xa3" + struct.pack("<I", target_rect_va + 4)
    code += b"\x8b\x05" + struct.pack("<I", target_rect_va)
    code += b"\x01\xd0\xa3" + struct.pack("<I", target_rect_va + 8)
    code += b"\x8b\x05" + struct.pack("<I", target_rect_va + 4)
    code += b"\x01\xd8\xa3" + struct.pack("<I", target_rect_va + 12)

    # Present every source pixel. The complete card is the canonical model;
    # lower controls are replayed afterward when native child ordering placed
    # them before this recurring opaque background.
    code += b"\xbe" + struct.pack("<I", target_rect_va)
    code += b"\xbf" + struct.pack("<I", dest_rect_va)
    code += b"\xb9\x04\x00\x00\x00\xf3\xa5"
    code += b"\x31\xc0\xa3" + struct.pack("<I", source_rect_va)
    code += b"\xa3" + struct.pack("<I", source_rect_va + 4)
    code += b"\xb8" + struct.pack("<I", owner._replacement_screen_width)
    code += b"\xa3" + struct.pack("<I", source_rect_va + 8)
    code += b"\xa1" + struct.pack("<I", raw_height_va)
    code += b"\xa3" + struct.pack("<I", source_rect_va + 12)

    # Keep the fitted union as diagnostics and as the visual oracle's exact
    # exclusion mask. Replay itself uses each original control transaction,
    # never a synthetic rectangle derived from this union.
    code += b"\x83\x3d" + struct.pack("<I", control_seen_va) + b"\x01"
    code.jump_if(Condition.NOT_EQUAL, "background_no_union")
    for index, axis in enumerate((0, 1, 0, 1)):
        logical_edge_va = logical_rect_va + axis * 4
        target_edge_va = target_rect_va + axis * 4
        logical_far_va = logical_rect_va + 8 + axis * 4
        target_far_va = target_rect_va + 8 + axis * 4
        code += b"\xa1" + struct.pack("<I", control_logical_rect_va + index * 4)
        code += b"\x2b\x05" + struct.pack("<I", logical_edge_va)
        code += b"\x89\xc2\xc1\xe2\x02"
        code += b"\x89\x15" + struct.pack("<I", control_source_rect_va + index * 4)
        code += b"\x8b\x0d" + struct.pack("<I", target_far_va)
        code += b"\x2b\x0d" + struct.pack("<I", target_edge_va)
        code += b"\x0f\xaf\xc1\x99"
        code += b"\x8b\x0d" + struct.pack("<I", logical_far_va)
        code += b"\x2b\x0d" + struct.pack("<I", logical_edge_va)
        code += b"\xf7\xf9"
        code += b"\x03\x05" + struct.pack("<I", target_edge_va)
        code += b"\xa3" + struct.pack("<I", control_target_rect_va + index * 4)
    code.label("background_no_union")

    code += b"\xc7\x44\x24\x2c" + struct.pack("<I", dest_rect_va)
    code += b"\xc7\x44\x24\x30" + struct.pack("<I", source_rect_va)
    code += b"\xff\x05" + struct.pack("<I", background_count_va)
    code += b"\xff\x05" + struct.pack("<I", transform_count_va)

    # With no recorded controls the outer dispatcher retains its original
    # tail-call path. Once controls exist, own the one ordered sequence:
    # complete background first, then up to two exact native control blits.
    code += b"\x83\x3d" + struct.pack("<I", control_count_va) + b"\x00"
    code.jump_if(Condition.EQUAL, "background_outer_tail")
    code += b"\xc7\x05" + struct.pack("<I", handled_flag_va) + b"\x01\x00\x00\x00"
    code += b"\x8b\x4c\x24\x1c\x8b\x44\x24\x28"
    code += b"\x68" + struct.pack("<I", source_rect_va)
    code += b"\x68" + struct.pack("<I", dest_rect_va)
    code += b"\x50"
    # We are already downstream of the public final-blitter hook. Calling its
    # patched entry again recursively re-enters ResourceDispatch until the
    # process exhausts its stack. The shared trampoline executes the displaced
    # native prologue and continuation directly, preserving the exact native
    # thiscall/ret-0x0c contract without another policy traversal.
    code.call_absolute(owner._native_blt_trampoline_va)
    code += b"\xa3" + struct.pack("<I", handled_result_va)
    code += b"\x85\xc0"
    code.jump_if(Condition.EQUAL, "background_handled")
    for slot_index in range(2):
        slot_va = control_slots_va + slot_index * 0x28
        code += b"\x83\x3d" + struct.pack("<I", control_count_va)
        code += bytes([slot_index + 1])
        code.jump_if(Condition.BELOW, "background_handled")
        code += b"\x8b\x4c\x24\x1c"
        code += b"\xa1" + struct.pack("<I", slot_va + 4)
        code += b"\x68" + struct.pack("<I", slot_va + 0x18)
        code += b"\x68" + struct.pack("<I", slot_va + 8)
        code += b"\x50"
        code.call_absolute(owner._native_blt_trampoline_va)
        code += b"\xa3" + struct.pack("<I", handled_result_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.EQUAL, "background_handled")
        code += b"\xff\x05" + struct.pack("<I", control_replay_count_va)
    code.label("background_handled")
    code += b"\xc3"
    code.label("background_outer_tail")
    code += b"\xc3"

    code.label("transform_identity")
    # The root's synchronous Draw scope proves lifetime and presentation
    # ownership. A cached address/visible byte does not: after Play/Restore
    # that allocation can contain unrelated objects. Do not call back into
    # the UI dispatcher from this shared blitter (also used during teardown
    # and by the cursor worker); the root already checked ownership safely.
    code += b"\x83\x3d" + struct.pack("<I", draw_scope_active_va) + b"\x00"
    code.jump_if(Condition.EQUAL, "native")
    code += b"\xa1" + struct.pack("<I", layer_va)
    code += b"\x85\xc0"
    code.jump_if(Condition.EQUAL, "native")
    code += b"\x81\x38" + struct.pack("<I", owner.profile.address("timeblock.vtable"))
    code.jump_if(Condition.NOT_EQUAL, "native")
    code += b"\x80\xb8\xc0\x03\x00\x00\x00"
    code.jump_if(Condition.EQUAL, "native")

    code += b"\x8b\x54\x24\x1c"
    code += b"\xa1" + struct.pack("<I", owner._physical_width_va)
    code += b"\x39\x42\x38"
    code.jump_if(Condition.NOT_EQUAL, "native")
    code += b"\xa1" + struct.pack("<I", owner._physical_width_va + 4)
    code += b"\x39\x42\x3c"
    code.jump_if(Condition.NOT_EQUAL, "native")
    code += b"\x8b\x74\x24\x2c\x85\xf6"
    code.jump_if(Condition.EQUAL, "native")

    # Cursor traffic is issued while the TBT layer is visible but does not
    # belong to its logical 640x480 composition. Bypass only the three exact
    # producer-learned wrapper identities (atlas, private composition, and
    # delayed save-under). Cursor-state +76 is merely the generic *current*
    # BitmapDrawable scope: treating it as cursor ownership bypassed every
    # ordinary TimeBlock child and prevented its bottom controls from being
    # fitted or observed. Wrapper identity remains valid when cursor backing
    # grows beyond its stock 128x128 extent without conflating other children.
    code += b"\x8b\x44\x24\x28"
    for state_offset in (80, 72, 88):
        code += b"\x3b\x05" + struct.pack("<I", cursor_state_va + state_offset)
        code.jump_if(Condition.EQUAL, "cursor_bypass")
    code.jump_short("child_not_cursor")
    code.label("cursor_bypass")
    code += b"\xff\x05" + struct.pack("<I", cursor_bypass_count_va)
    code += b"\xc3"
    code.label("child_not_cursor")

    # The current animation frame was quartered by the dimension getter before
    # Game::blit clipped it. Expand only that exact source back to physical texels.
    overlay_surface_va = owner.symbols.va(
        TIMEBLOCK_SEGMENT.logical_name, TIMEBLOCK_OVERLAY_SURFACE_OFFSET
    )
    code += b"\x3b\x05" + struct.pack("<I", overlay_surface_va)
    code.jump_if(Condition.NOT_EQUAL, "overlay_source_done")
    code += b"\x8b\x74\x24\x30\x85\xf6"
    code.jump_if(Condition.EQUAL, "overlay_source_done")
    for offset in range(0, 16, 4):
        code += b"\x8b\x56" + bytes([offset]) + b"\xc1\xe2\x02"
        code += b"\x89\x15" + struct.pack("<I", source_rect_va + offset)
    code += b"\xc7\x44\x24\x30" + struct.pack("<I", source_rect_va)
    code.label("overlay_source_done")
    code += b"\x8b\x74\x24\x2c"

    code += b"\x83\x78\x38\x41"
    code.jump_if(Condition.BELOW, "native")
    for index in (0, 1):
        code += b"\x8b\x46" + bytes([index * 4])
        code += b"\x3b\x05" + struct.pack("<I", logical_rect_va + index * 4)
        code.jump_if(Condition.LESS, "native")
        code += b"\x8b\x46" + bytes([(index + 2) * 4])
        code += b"\x3b\x05" + struct.pack("<I", logical_rect_va + (index + 2) * 4)
        code.jump_if(Condition.GREATER, "native")

    # EBP is scratch inside the outer dispatcher's PUSHAD frame. It survives
    # the affine below and marks whether this exact child should update one of
    # the two replay records after its fitted destination has been calculated.
    code += b"\x31\xed"
    # Learn the live bottom-control union before changing ESI's destination
    # rectangle.  The exact logical card bounds above exclude pillar clears,
    # while the >=65-pixel source proof excludes cursor/save-under traffic.
    # Buttons begin in the final 45 authored rows on every stock TimeBlock,
    # but their actual X/Y bounds—not that band—define the protected region.
    code += b"\xa1" + struct.pack("<I", logical_rect_va + 12)
    code += b"\x83\xe8\x2d\x3b\x46\x04"
    code.jump_if(Condition.GREATER, "child_control_done")
    code += b"\x45"
    code += b"\x83\x3d" + struct.pack("<I", control_seen_va) + b"\x00"
    code.jump_if(Condition.NOT_EQUAL, "child_control_extend")
    for index in range(4):
        code += b"\x8b\x46" + bytes([index * 4])
        code += b"\xa3" + struct.pack("<I", control_logical_rect_va + index * 4)
    code += b"\xc7\x05" + struct.pack("<I", control_seen_va) + b"\x01\x00\x00\x00"
    code.jump_short("child_control_done")
    code.label("child_control_extend")
    for index, condition in (
        (0, Condition.GREATER_OR_EQUAL),
        (1, Condition.GREATER_OR_EQUAL),
        (2, Condition.LESS_OR_EQUAL),
        (3, Condition.LESS_OR_EQUAL),
    ):
        code += b"\x8b\x46" + bytes([index * 4])
        code += b"\x3b\x05" + struct.pack("<I", control_logical_rect_va + index * 4)
        code.jump_short_if(condition, f"child_control_edge_{index}_done")
        code += b"\xa3" + struct.pack("<I", control_logical_rect_va + index * 4)
        code.label(f"child_control_edge_{index}_done")
    code.label("child_control_done")

    # Transform each destination edge from the centered logical 640x480
    # coordinate system into the fitted viewport.  Signed division handles
    # clipped edges safely.
    for index, axis in enumerate((0, 1, 0, 1)):
        logical_edge_va = logical_rect_va + axis * 4
        target_edge_va = target_rect_va + axis * 4
        logical_size_va = logical_rect_va + 8 + axis * 4
        target_size_va = target_rect_va + 8 + axis * 4
        code += b"\x8b\x46" + bytes([index * 4])
        code += b"\x2b\x05" + struct.pack("<I", logical_edge_va)
        code += b"\x8b\x0d" + struct.pack("<I", target_size_va)
        code += b"\x2b\x0d" + struct.pack("<I", target_edge_va)
        code += b"\x0f\xaf\xc1\x99"
        code += b"\x8b\x0d" + struct.pack("<I", logical_size_va)
        code += b"\x2b\x0d" + struct.pack("<I", logical_edge_va)
        code += b"\xf7\xf9"
        code += b"\x03\x05" + struct.pack("<I", target_edge_va)
        code += b"\xa3" + struct.pack("<I", dest_rect_va + index * 4)

    # Retain the exact native transaction for each distinct bottom button.
    # The destination is our fitted scratch, while the source wrapper/RECT are
    # copied verbatim from GK3. Logical-left is the stable identity key: hover
    # redraws replace the appropriate slot without accumulating stale frames.
    code += b"\x85\xed"
    code.jump_if(Condition.EQUAL, "child_record_done")
    code += b"\x8b\x44\x24\x30\x85\xc0"
    code.jump_if(Condition.EQUAL, "child_record_done")
    code += b"\x8b\x0d" + struct.pack("<I", control_count_va)
    code += b"\x85\xc9"
    code.jump_short_if(Condition.EQUAL, "child_record_first")
    code += b"\x8b\x06"
    code += b"\x3b\x05" + struct.pack("<I", control_slots_va)
    code.jump_short_if(Condition.EQUAL, "child_record_slot_zero")
    code += b"\x83\xf9\x01"
    code.jump_short_if(Condition.EQUAL, "child_record_new_second")
    code += b"\x3b\x05" + struct.pack("<I", control_slots_va + 0x28)
    code.jump_short_if(Condition.EQUAL, "child_record_slot_one")
    # A TimeBlock has at most Continue and Save. If native state replaces one
    # in place, prefer the second slot rather than growing an unbounded cache.
    code.jump_short("child_record_slot_one")
    code.label("child_record_first")
    code += b"\xc7\x05" + struct.pack("<I", control_count_va) + b"\x01\x00\x00\x00"
    code.label("child_record_slot_zero")
    code += b"\xbf" + struct.pack("<I", control_slots_va)
    code.jump_short("child_record_copy")
    code.label("child_record_new_second")
    code += b"\xc7\x05" + struct.pack("<I", control_count_va) + b"\x02\x00\x00\x00"
    code.label("child_record_slot_one")
    code += b"\xbf" + struct.pack("<I", control_slots_va + 0x28)
    code.label("child_record_copy")
    code += b"\x8b\x06\x89\x07"
    code += b"\x8b\x44\x24\x28\x89\x47\x04"
    for index in range(4):
        code += b"\xa1" + struct.pack("<I", dest_rect_va + index * 4)
        code += b"\x89\x47" + bytes([8 + index * 4])
    code += b"\x8b\x44\x24\x30"
    for index in range(4):
        code += b"\x8b\x50" + bytes([index * 4])
        code += b"\x89\x57" + bytes([0x18 + index * 4])
    code.label("child_record_done")
    code += b"\xc7\x44\x24\x2c" + struct.pack("<I", dest_rect_va)
    code += b"\xff\x05" + struct.pack("<I", transform_count_va)
    code.label("native")
    code += b"\xc3"
    return code.build()


def build_root_draw(
    owner: ResourceDispatchCompiler,
    *,
    wrapper_va: int,
    overlay_draw_va: int,
    clear_budget_va: int,
    clear_count_va: int,
    bltfx_va: int,
    clear_flip_count_va: int,
    successful_flip_count_va: int,
    layer_va: int,
    draw_scope_active_va: int,
    raw_width_va: int,
    raw_height_va: int,
    control_seen_va: int,
    control_count_va: int,
) -> bytes:
    """Draw through authored bounds without mutating the persistent model."""
    code = X86Emitter(base_va=wrapper_va)

    # Construction, restore deserialization, and hidden-layer maintenance
    # can all invoke this vtable slot. Only the engine's published top
    # layer is a presentation traversal. Everything earlier remains
    # byte-for-byte native so loading a save directly on a TimeBlock cannot
    # observe UI projection state.
    code += b"\x51"
    code.call_absolute(owner.profile.address("ui.current_layer"))
    code += b"\x59\x39\xc8"
    code.jump_if(Condition.NOT_EQUAL, "native_unscoped")
    code += b"\x3b\x0d" + struct.pack("<I", layer_va)
    code.jump_if(Condition.NOT_EQUAL, "identify_live_replacement")
    code += b"\x83\x3d" + struct.pack("<I", raw_width_va) + b"\x00"
    code.jump_if(Condition.EQUAL, "identify_live_replacement")
    code += b"\x83\x3d" + struct.pack("<I", raw_height_va) + b"\x00"
    code.jump_if(Condition.NOT_EQUAL, "owned")

    # A normal constructor reaches the dedicated centering hook and has
    # already published this ownership tuple. Restore reconstruction can
    # instead deserialize and publish the TimeBlock root without revisiting
    # that call site. This vtable slot is the class's unique Draw override,
    # and current-layer equality above proves live presentation ownership;
    # complete the proof with the exact root and resolved background dimensions.
    # Doing this here removes the constructor-timing dependency without a
    # fuzzy size window or a save-specific path.
    code.label("identify_live_replacement")
    code += b"\x8b\x41\x24\x2b\x41\x1c"
    code += b"\x3d" + struct.pack("<I", owner._replacement_screen_width)
    code.jump_short_if(Condition.EQUAL, "restore_root_width_proven")
    # Original saves serialize authored bounds even when the restored bitmap
    # resolves to a dense replacement. Accept that exact model width too;
    # the live resolved surface must still prove both replacement dimensions.
    code += b"\x3d" + struct.pack("<I", owner._fixed_screen_width)
    code.jump_if(Condition.NOT_EQUAL, "native_unscoped")
    code.label("restore_root_width_proven")
    # The native BitmapDrawable draw reads its background handle at +0x2C.
    # Resolve that handle rather than guessing bitmap height from container
    # bounds: TBT306P really has 481 rows, unlike the other 480-row cards.
    code += b"\x51\xff\x71\x2c\x8b\x0d" + struct.pack("<I", owner._bitmap_surface_manager_va)
    code.call_absolute(owner._resolve_bitmap_resource_va)
    code += b"\x59\x85\xc0"
    code.jump_if(Condition.EQUAL, "native_unscoped")
    code += b"\x8b\x40\x30\x85\xc0"
    code.jump_if(Condition.EQUAL, "native_unscoped")
    code += b"\x81\x78\x38" + struct.pack("<I", owner._replacement_screen_width)
    code.jump_if(Condition.NOT_EQUAL, "native_unscoped")
    code += b"\x8b\x50\x3c\x81\xfa" + struct.pack("<I", owner._replacement_screen_height)
    code.jump_short_if(Condition.EQUAL, "restore_bitmap_proven")
    code += b"\x81\xfa" + struct.pack("<I", owner._tall_tbt_background_height)
    code.jump_if(Condition.NOT_EQUAL, "native_unscoped")
    code.label("restore_bitmap_proven")
    code += b"\x89\x0d" + struct.pack("<I", layer_va)
    # Persist the measured bitmap height, including the exceptional final row.
    code += b"\xc7\x05" + struct.pack("<I", raw_width_va)
    code += struct.pack("<I", owner._replacement_screen_width)
    code += b"\x89\x15" + struct.pack("<I", raw_height_va)
    # The constructor hook normally arms the two page clears. A root first
    # identified here needs the identical initialization before its first
    # complete traversal, otherwise a stale pre-restore page can remain in
    # the fitted outer region.
    code += b"\xc7\x05" + struct.pack("<I", clear_budget_va)
    code += b"\x02\x00\x00\x00"
    # A newly identified TimeBlock owns a fresh control union. Dirty root
    # traversals for that same layer may omit unchanged children, so this
    # lifetime boundary—not every Draw call—is the only safe reset point.
    code += b"\xc7\x05" + struct.pack("<I", control_seen_va)
    code += b"\x00\x00\x00\x00"
    code += b"\xc7\x05" + struct.pack("<I", control_count_va)
    code += b"\x00\x00\x00\x00"
    code.label("owned")

    # FUN_004D4F22 is TimeBlockLayer's unique thiscall Draw override. Its
    # +0x18 bit is the ordinary drawable visibility flag; +0x3C0 selects
    # the 2D child-composition branch. Checking both avoids presentation
    # work while the alternate 3D path owns the screen.
    code += b"\x80\x79\x18\x00"
    code.jump_if(Condition.EQUAL, "native_unscoped")
    code += b"\x80\xb9\xc0\x03\x00\x00\x00"
    code.jump_if(Condition.EQUAL, "native_unscoped")

    # The HD setup arms exactly two clears: one for each page of GK3's
    # double-buffered flip chain. Once both pages have received a complete
    # initial traversal, cursor and other dirty repaints preserve them.
    code += b"\x83\x3d" + struct.pack("<I", clear_budget_va) + b"\x00"
    code.jump_if(Condition.EQUAL, "present")
    # Draw receives GK3's 16-bit destination bitmap handle as its first
    # stack argument.  Resolve it through the same stock manager/helper used
    # by FUN_0046709A.  FUN_0054D330 then proves that the returned resource
    # owns its low-level surface wrapper at +0x30; FUN_0054F980 proves that
    # wrapper owns IDirectDrawSurface at +0x2C.  PUSHAD protects the Draw
    # object and caller registers across both native calls.
    code += b"\x60"
    code += b"\x8b\x44\x24\x24"
    code += b"\x8b\x0d" + struct.pack("<I", owner._bitmap_surface_manager_va)
    code += b"\x50"
    code.call_absolute(owner._resolve_bitmap_resource_va)
    code += b"\x85\xc0"
    code.jump_short_if(Condition.EQUAL, "clear_done")
    code += b"\x8b\x40\x30\x85\xc0"
    code.jump_short_if(Condition.EQUAL, "clear_done")
    code += b"\x8b\x70\x2c\x85\xf6"
    code.jump_short_if(Condition.EQUAL, "clear_done")
    # A Draw call is not a page identity, and DirectDraw keeps the same
    # back-surface interface pointer while Flip exchanges its underlying
    # page memory. With one clear left, wait for a later successful native
    # Flip generation instead of guessing from calls or pointer identity.
    code += b"\x83\x3d" + struct.pack("<I", clear_budget_va) + b"\x01"
    code.jump_short_if(Condition.NOT_EQUAL, "clear_page")
    code += b"\xa1" + struct.pack("<I", successful_flip_count_va)
    code += b"\x3b\x05" + struct.pack("<I", clear_flip_count_va)
    code.jump_short_if(Condition.EQUAL, "clear_done")
    code.label("clear_page")
    code += b"\x8b\x1e"

    # Fill only the page this traversal is about to draw.  Clearing both
    # global flip-chain pages would blank the page not participating in the
    # current traversal, while delaying this fill until a child blit would
    # erase parent-rendered TimeBlock art.  Here every pixel starts black
    # before the complete native traversal reconstructs the current page.
    code += b"\x68" + struct.pack("<I", bltfx_va)
    code += b"\x68" + struct.pack("<I", owner._ddblt_colorfill_wait)
    code += b"\x6a\x00\x6a\x00\x6a\x00\x56\xff\x53\x14"
    # Consume a page from the budget only after DD_OK.  A transient lost
    # surface or another DirectDraw failure therefore leaves the clear
    # armed for the next complete root traversal instead of falsely
    # recording a page whose old room pixels may still be visible.
    code += b"\x85\xc0"
    code.jump_short_if(Condition.NOT_EQUAL, "clear_done")
    # Publish generation only after DD_OK. A failed fill remains eligible
    # and cannot poison the page-generation test on the next traversal.
    code += b"\xa1" + struct.pack("<I", successful_flip_count_va)
    code += b"\xa3" + struct.pack("<I", clear_flip_count_va)
    code += b"\xff\x0d" + struct.pack("<I", clear_budget_va)
    code += b"\xff\x05" + struct.pack("<I", clear_count_va)
    code.label("clear_done")
    code += b"\x61"

    # The 4x bitmap dimensions are valid resource/model state. They are
    # too large only for the authored child traversal, whose coordinates
    # remain 640x480. Expose logical right/bottom edges synchronously around
    # Draw, then restore the raw model before returning. A direct restore
    # into a TimeBlock can therefore validate the resource-sized object.
    code.label("present")
    # Preserve this particular model's extents, not the bitmap's extents.
    # Restore may have loaded a 640-wide authored root while construction
    # creates a 2560-wide root. Both must leave Draw exactly as they entered.
    code += b"\x8b\x41\x24\x2b\x41\x1c\x50"
    code += b"\x8b\x41\x28\x2b\x41\x20\x50"
    code += b"\xa1" + struct.pack("<I", raw_width_va)
    code += b"\xc1\xe8\x02\x03\x41\x1c\x89\x41\x24"
    code += b"\xa1" + struct.pack("<I", raw_height_va)
    code += b"\xc1\xe8\x02\x03\x41\x20\x89\x41\x28"
    # Reuse GK3's own recursive centering operation so every descendant
    # receives the same temporary translation as its root.  Its normal
    # visible-object path also invalidates the rectangle vacated by every
    # moved child.  That is appropriate for a persistent UI move, but this
    # translation is scoped entirely inside Draw: the later inverse move
    # would otherwise queue black damage bands wherever the fitted output
    # extends above or left of the authored rectangle.  Temporarily mark
    # the root invisible while moving it. TimeBlockLayer's container move
    # propagates that state to descendants, suppressing those invalidations
    # without replacing the engine's tree traversal. Preserve the exact
    # visibility byte rather than assuming its true value is one.
    #
    # The screen RECT pointer is engine-owned live state, not a compiled
    # resolution constant.
    code += b"\x0f\xb6\x41\x18\x50\xc6\x41\x18\x00"
    code += b"\x51\xff\x35" + struct.pack("<I", owner._screen_rect_ptr_va)
    code.call_absolute(owner._native_center_va)
    code += b"\x59\x58\x88\x41\x18"

    # Copy both arguments exactly as the stock caller supplied them.  The
    # native thiscall removes those copies with RET 8; this wrapper removes
    # the originals when it returns.  Saving ECX separately keeps the object
    # pointer out of the native function's volatile-register contract.
    code += b"\xc7\x05" + struct.pack("<I", draw_scope_active_va)
    code += b"\x01\x00\x00\x00"
    # Retain the union learned for this layer. GK3 calls this root for partial
    # damage too, and such a traversal can contain only the recurring opaque
    # background; clearing the union here would erase unchanged controls.
    code += b"\x51\xff\x74\x24\x14\xff\x74\x24\x14"
    code.call_absolute(overlay_draw_va)
    code += b"\x59"
    code += b"\xc7\x05" + struct.pack("<I", draw_scope_active_va)
    code += b"\x00\x00\x00\x00"
    code += b"\x58\x03\x41\x20\x89\x41\x28"
    code += b"\x58\x03\x41\x1c\x89\x41\x24"
    # Centering the restored model bounds applies the inverse size shift,
    # returning root and descendants to their persistent native size.
    # Keep the inverse move non-invalidating for the same reason as the
    # forward move above.
    code += b"\x0f\xb6\x41\x18\x50\xc6\x41\x18\x00"
    code += b"\x51\xff\x35" + struct.pack("<I", owner._screen_rect_ptr_va)
    code.call_absolute(owner._native_center_va)
    code += b"\x59\x58\x88\x41\x18"
    code += b"\xc2\x08\x00"

    # Unowned traversals retain the exact original call and model state.
    code.label("native_unscoped")
    code += b"\x51\xff\x74\x24\x0c\xff\x74\x24\x0c"
    code.call_absolute(owner._tbt_draw_original_va)
    code += b"\x59\xc2\x08\x00"
    return code.build()


def build_center(
    owner: ResourceDispatchCompiler,
    *,
    wrapper_va: int,
    layer_va: int,
    clear_budget_va: int,
    raw_width_va: int,
    raw_height_va: int,
    control_seen_va: int,
    control_count_va: int,
) -> bytes:
    """Tag exact replacement ownership without changing construction geometry."""
    code = X86Emitter(base_va=wrapper_va)
    # This hook replaces the single centering call made by TimeBlock's
    # constructor.  At that point the bitmap-entry probe has not run yet,
    # so concrete surface identity is unavailable by design.  The unique
    # call-site supplies class ownership; require the exact dimensions of
    # the 4x replacement root as its independent data contract.  This also
    # leaves EAX/EDX holding the measured width/height recorded below.
    code += b"\x8b\x41\x24\x2b\x41\x1c"  # current width
    code += b"\x3d" + struct.pack("<I", owner._replacement_screen_width)
    code.jump_short_if(Condition.NOT_EQUAL, "native")
    code += b"\x8b\x51\x28\x2b\x51\x20"  # current height
    code += b"\x81\xfa" + struct.pack("<I", owner._replacement_screen_height)
    code.jump_short_if(Condition.EQUAL, "native_height_proven")
    # TBT306P genuinely has 481 source rows; do not discard its final row.
    code += b"\x81\xfa" + struct.pack("<I", owner._tall_tbt_background_height)
    code.jump_short_if(Condition.NOT_EQUAL, "native")
    code.label("native_height_proven")
    # Record replacement ownership and dimensions, but let construction
    # finish entirely natively. The loader can therefore observe the exact
    # bitmap-sized object graph it expects; Draw owns the later temporary
    # authored-geometry projection.
    code += b"\x89\x0d" + struct.pack("<I", layer_va)
    code += b"\xa3" + struct.pack("<I", raw_width_va)
    code += b"\x89\x15" + struct.pack("<I", raw_height_va)
    code += b"\xc7\x05" + struct.pack("<I", control_seen_va)
    code += b"\x00\x00\x00\x00"
    code += b"\xc7\x05" + struct.pack("<I", control_count_va)
    code += b"\x00\x00\x00\x00"
    # Only a recognized 4x TBT replacement reaches this point.  Arm one
    # draw-entry clear per distinct DirectDraw flip page. Budget state two
    # makes the first clear unconditional; that successful clear publishes
    # the new cycle's first page identity.
    code += b"\x6a\x02\x58\xa3" + struct.pack("<I", clear_budget_va)
    code.label("native")
    code.jump_absolute(owner._native_center_va)
    return code.build()
