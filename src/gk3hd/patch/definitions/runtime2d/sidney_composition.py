"""Emit SIDNEY fitted composition, status replay, and outer bands."""

# These emitters are one physical part of SidneyPresentationCompiler and
# consume its private recovered ABI directly. A copied public configuration
# would add mutable duplication and allow the two ABI views to drift.
# ruff: noqa: SLF001

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.geometry import AUTHORED_FRAME_HEIGHT, AUTHORED_FRAME_WIDTH
from gk3hd.patch.definitions.runtime2d.layout import (
    CONSOLE_OWNER_OFFSET,
    CONSOLE_SEGMENT,
    SPRITE_CACHE_SEGMENT,
    SPRITE_CACHE_TRANSFER_OFFSET,
)
from gk3hd.patch.definitions.runtime2d.sidney_images import FINGERPRINT_SURFACES_SIZE, SURFACES_SIZE

if TYPE_CHECKING:
    from gk3hd.patch.definitions.runtime2d.sidney_presentation import SidneyPresentationCompiler


def build_root_draw_wrapper(
    *,
    wrapper_va: int,
    active_depth_va: int,
    root_ptr_va: int,
    status_trace_count_va: int,
    backdrop_pending_va: int,
    enable_backdrop: bool,
    draw_target_va: int,
) -> bytes:
    """Enter SIDNEY scope, publish its root, and traverse through the bridge."""
    # The original thiscall takes two stack arguments and returns with
    # RET 8.  Preserve ECX across it so the wrapper can close its scope.
    code = X86Emitter(base_va=wrapper_va)
    code += b"\x89\x0d" + struct.pack("<I", root_ptr_va)
    code += b"\xc7\x05" + struct.pack("<I", status_trace_count_va) + b"\x00\x00\x00\x00"
    code += b"\xff\x05" + struct.pack("<I", active_depth_va)
    if enable_backdrop:
        code += b"\xc7\x05" + struct.pack("<I", backdrop_pending_va) + b"\x01\x00\x00\x00"
    code += b"\x51"
    code += b"\xff\x74\x24\x0c"  # push original arg 2
    code += b"\xff\x74\x24\x0c"  # push original arg 1
    code.call_absolute(draw_target_va)
    code += b"\x59"
    code += b"\xff\x0d" + struct.pack("<I", active_depth_va)
    code += b"\xc2\x08\x00"
    return code.build()


def build_destructor_wrapper(
    owner: SidneyPresentationCompiler,
    *,
    wrapper_va: int,
    active_depth_va: int,
    transformed_blit_count_va: int,
    root_ptr_va: int,
    backdrop_pending_va: int,
    extension_surface_ptr_va: int,
    portrait_surfaces_va: int,
    fingerprint_surfaces_va: int,
    frame_state_va: int,
) -> bytes:
    """Withdraw SIDNEY-owned state before delegating native destruction."""
    code = X86Emitter(base_va=wrapper_va)
    code += b"\x33\xc0"
    for address in (
        active_depth_va,
        transformed_blit_count_va,
        root_ptr_va,
        backdrop_pending_va,
        extension_surface_ptr_va,
        *(portrait_surfaces_va + offset for offset in range(0, SURFACES_SIZE, 4)),
        *(fingerprint_surfaces_va + offset for offset in range(0, FINGERPRINT_SURFACES_SIZE, 4)),
        *(frame_state_va + index * 12 for index in range(4)),
    ):
        code += b"\xa3" + struct.pack("<I", address)
    code.jump_absolute(owner._original_root_destructor_va)
    return code.build()


def build_blt_wrapper(
    owner: SidneyPresentationCompiler,
    *,
    wrapper_va: int,
    active_depth_va: int,
    transformed_blit_count_va: int,
    rect_scratch_va: int,
    cursor_blt_trace_helper_va: int,
    extension_surface_ptr_va: int,
    status_trace_count_va: int,
    status_trace_records_va: int,
    system_blt_wrapper_va: int,
    portrait_source_va: int,
    frame_source_va: int,
    cursor_surface_classifier_va: int,
) -> bytes:
    """Map SIDNEY-local final blits through its fitted presentation affine."""
    # 0x54F980 is a thiscall whose second stack argument ([ESP+8]) is the
    # destination RECT.  Both horizontal edges must move so the operation
    # scales rather than crops the source.  Some callers pass persistent
    # sprite state here (notably the software cursor save/restore path), so
    # never rewrite the caller-owned RECT in place.  The renderer is
    # single-threaded and this helper does not recurse, making one private
    # scratch RECT sufficient for the duration of the tail-called blit.
    code = X86Emitter(base_va=wrapper_va)
    code.call_absolute(cursor_blt_trace_helper_va)
    # CursorManager can redraw its already-physical composition during this
    # traversal. Its backing surface scales with the display (360x360 at4K),
    # so the old 128x128 size guess missed it and fitted its destination twice.
    # Use the same exact source/destination ownership predicate as SystemScreen,
    # before this outer wrapper changes any coordinates or source rectangles.
    code.raw(b"\x60\x8b\x4c\x24\x18\x8b\x54\x24\x24\x8b\x74\x24\x28")
    code.call_absolute(cursor_surface_classifier_va)
    code.raw(b"\x85\xc0\x61")  # POPAD preserves the predicate's flags.
    code.jump_if(Condition.NOT_EQUAL, "native")
    # These shared software-alpha calls are not intrinsically cursor traffic.
    # Console needs their paired background capture/presentation, and the exact
    # cursor surface classifier above has already excluded real cursor copies.
    code.raw(
        b"\x83\x3d"
        + struct.pack("<I", owner.symbols.va(CONSOLE_SEGMENT.logical_name, CONSOLE_OWNER_OFFSET))
        + b"\x00"
    )
    code.jump_if(Condition.EQUAL, "not_console")
    code.jump_absolute(system_blt_wrapper_va)
    code.label("not_console")
    code += b"\x83\x3d" + struct.pack("<I", active_depth_va) + b"\x00"
    code.jump_if(Condition.EQUAL, "inactive")
    for return_va in owner._cursor_save_under_return_vas:
        code += b"\x81\x3c\x24" + struct.pack("<I", return_va)
        code.jump_if(Condition.EQUAL, "native")
    # Root traversal can also update small offscreen/save-under surfaces.
    # Only the physical screen surface receives the presentation
    # transform; modifying a cursor backing surface produces invalid
    # DirectDraw rectangles and stale cursor trails.
    code += b"\xa1" + struct.pack("<I", owner._physical_width_global_va)
    code += b"\x39\x41\x38"
    code.jump_if(Condition.NOT_EQUAL, "native")
    code += b"\xa1" + struct.pack("<I", owner._physical_width_global_va + 4)
    code += b"\x39\x41\x3c"
    code.jump_if(Condition.NOT_EQUAL, "native")
    code += b"\x8b\x41\x2c"
    code += b"\xa3" + struct.pack("<I", extension_surface_ptr_va)
    code.call_absolute(portrait_source_va)
    code.call_absolute(frame_source_va)
    code += b"\x60"  # pushad: preserve all general registers
    code += b"\x8b\x74\x24\x28"  # destination RECT after pushad
    code += b"\x85\xf6"
    code.jump_short_if(Condition.EQUAL, "restore")
    # Defer the narrow status-line glyph blits.  They must be presented
    # after SIDNEY and any optional side fill, and their destination RECTs
    # need the same height-fit affine as the rest of the 1024x768 view.
    code += b"\x83\x7e\x04\x20\x73\x06"
    code += b"\x83\x7e\x0c\x20"
    code.jump_short_if(Condition.BELOW_OR_EQUAL, "trace_status")
    code += b"\xbf" + struct.pack("<I", rect_scratch_va)
    code += b"\xb9\x04\x00\x00\x00"
    code += b"\xf3\xa5"  # copy four DWORDs from caller RECT to scratch
    code += b"\xbe" + struct.pack("<I", rect_scratch_va)
    code += b"\x89\x74\x24\x28"  # replace destination argument with scratch RECT
    # Horizontal edges are scaled and centered; vertical edges receive
    # the same uniform scale with no offset.  RECT fields alternate X/Y,
    # so a four-element loop keeps this hot wrapper compact enough for its
    # original reserved code slot.
    # Derive the height-fit scale and pillar offset from live engine
    # dimensions so changing resolution never requires repatching. Scale
    # divides physical height by 768; the offset centers height times 4:3.
    code += b"\x8b\x1d" + struct.pack("<I", owner._physical_width_global_va + 4)
    code += b"\x8b\xc3\xc1\xe0\x02\x99\xbf\x03\x00\x00\x00\xf7\xff"
    code += b"\x8b\x2d" + struct.pack("<I", owner._physical_width_global_va)
    code += b"\x2b\xe8\xd1\xfd"
    code += b"\xb9\x00\x03\x00\x00"
    code += b"\xbf\x04\x00\x00\x00"
    code.label("transform_loop")
    code += b"\x8b\x06\x0f\xaf\xc3\x99\xf7\xf9"
    code += b"\xf7\xc7\x01\x00\x00\x00\x75\x02"
    code += b"\x03\xc5"
    code += b"\x89\x06\x83\xc6\x04\x4f"
    code.jump_short_if(Condition.NOT_EQUAL, "transform_loop")
    code += b"\xff\x05" + struct.pack("<I", transformed_blit_count_va)
    code.label("restore")
    code += b"\x61"  # popad
    code.label("native")
    code.jump_absolute(
        owner.symbols.va(SPRITE_CACHE_SEGMENT.logical_name, SPRITE_CACHE_TRANSFER_OFFSET)
    )
    code.label("trace_status")
    code += b"\xa1" + struct.pack("<I", status_trace_count_va)
    code += b"\x83\xf8" + bytes([owner._status_trace_capacity])
    code.jump_short_if(Condition.ABOVE_OR_EQUAL, "suppress_status")
    code += b"\xff\x05" + struct.pack("<I", status_trace_count_va)
    code += b"\x6b\xc0" + bytes([owner._status_trace_stride])
    code += b"\x05" + struct.pack("<I", status_trace_records_va)
    code += b"\x8b\x54\x24\x18\x89\x10"  # destination wrapper / saved ECX
    code += b"\x8b\x54\x24\x24\x89\x50\x04"  # source wrapper / first argument
    for index in range(4):
        code += b"\x8b\x56" + bytes([index * 4])
        code += b"\x89\x50" + bytes([8 + index * 4])
    code += b"\x8b\x54\x24\x2c\x85\xd2"
    code.jump_short_if(Condition.EQUAL, "source_rect_done")
    for index in range(4):
        code += b"\x8b\x4a" + bytes([index * 4])
        code += b"\x89\x48" + bytes([24 + index * 4])
    code.label("source_rect_done")
    code.label("suppress_status")
    code += b"\x61\xb8\x01\x00\x00\x00\xc2\x0c\x00"

    # SIDNEY owns the entry hook at 0x54F980 because some of its status
    # transfers reach the final blitter indirectly.  General interface
    # trees (Inventory, Graphics, and similar controls) can do the same,
    # so an inactive SIDNEY scope must offer those calls to the shared
    # system-screen dispatcher instead of falling straight into native
    # code.  Copy the three thiscall stack arguments before CALLing it:
    # the shared dispatcher and every downstream native path use callee
    # cleanup, while the untouched originals still belong to our caller.
    #
    # The dispatcher eventually tail-enters this same entry hook through
    # the HD chain.  On that second visit the stack return address is the
    # instruction immediately after our CALL; recognizing it sends the
    # operation to the displaced native prologue and prevents recursion.
    code.label("inactive")
    code += b"\x81\x3c\x24"
    code.absolute_label("bridge_return")
    code.jump_if(Condition.EQUAL, "native")
    for return_va in (
        *owner._shared_dispatch_return_vas,
        *owner._cursor_save_under_return_vas,
    ):
        # Cursor cache rectangles are already physical and must not be
        # reinterpreted as ordinary UI-child presentation rectangles.
        code += b"\x81\x3c\x24" + struct.pack("<I", return_va)
        code.jump_if(Condition.EQUAL, "native")
    code += b"\xff\x74\x24\x0c" * 3
    code.call_absolute(system_blt_wrapper_va)
    code.label("bridge_return")
    code += b"\xc2\x0c\x00"
    return code.build()


def build_status_replay_helper(
    owner: SidneyPresentationCompiler,
    *,
    wrapper_va: int,
    status_trace_count_va: int,
    status_trace_records_va: int,
    native_blt_trampoline_va: int,
) -> bytes:
    """Replay status blits that the scoped SIDNEY traversal deferred.

    The saved records contain the original destination wrapper, source
    wrapper, destination RECT, and source RECT.  Before replay, transform
    every destination edge using the same live height-fit affine as the
    ordinary SIDNEY blit wrapper.  Replaying through the native trampoline
    deliberately bypasses this patch's entry hook; a replay through
    0x0054F980 would be captured and suppressed again.
    """
    code = X86Emitter(base_va=wrapper_va)
    code += b"\x60\x33\xff"
    # Clamp a corrupt/legacy count before indexing the fixed record array.
    # Store the clamped value back so EBP is free to hold the live pillar
    # offset during all four signed IDIV operations below.
    code += b"\xa1" + struct.pack("<I", status_trace_count_va)
    code += b"\x83\xf8" + bytes([owner._status_trace_capacity]) + b"\x76\x05"
    code += b"\xb8" + struct.pack("<I", owner._status_trace_capacity)
    code += b"\xa3" + struct.pack("<I", status_trace_count_va)
    code.label("replay_loop")
    code += b"\x3b\x3d" + struct.pack("<I", status_trace_count_va)
    code.jump_if(Condition.GREATER_OR_EQUAL, "done")
    code += b"\x6b\xf7" + bytes([owner._status_trace_stride])
    code += b"\x81\xc6" + struct.pack("<I", status_trace_records_va)

    # The stock 1024 framebuffer is also SIDNEY's clip rectangle. Its
    # NEW E-MAIL animation deliberately starts glyphs to the right of
    # x=1024, where they are invisible until entering the canvas. A wider
    # physical destination would expose those authored off-canvas frames,
    # so discard fully external records before applying the affine. Late
    # asynchronous glyphs are clipped earlier by the high-level font hook;
    # this is the equivalent ownership rule for recursive root draws.
    code += b"\x83\x7e\x10\x00"
    code.jump_if(Condition.LESS_OR_EQUAL, "next_record")
    code += b"\x81\x7e\x08\x00\x04\x00\x00"
    code.jump_if(Condition.GREATER_OR_EQUAL, "next_record")

    # Derive the runtime scale and centered pillar once per record.
    # EBX keeps H, EBP keeps the pillar, and ECX keeps the 768 divisor;
    # CDQ/IDIV may therefore use EDX without destroying persistent state.
    code += b"\x8b\x1d" + struct.pack("<I", owner._physical_width_global_va + 4)
    code += b"\x8b\xc3\xc1\xe0\x02\x99\xb9\x03\x00\x00\x00\xf7\xf9"
    code += b"\x8b\x2d" + struct.pack("<I", owner._physical_width_global_va)
    code += b"\x2b\xe8\xd1\xfd"
    code += b"\xb9\x00\x03\x00\x00"
    for rect_offset, add_pillar in ((8, True), (12, False), (16, True), (20, False)):
        code += b"\x8b\x46" + bytes([rect_offset])
        code += b"\x0f\xaf\xc3\x99\xf7\xf9"
        if add_pillar:
            code += b"\x03\xc5"
        code += b"\x89\x46" + bytes([rect_offset])

    # Reconstruct the native thiscall: ECX is the destination wrapper and
    # the three stack arguments are source wrapper, destination, source.
    code += b"\x8b\x0e\x8d\x46\x18\x50\x8d\x46\x08\x50\xff\x76\x04"
    code.call_absolute(native_blt_trampoline_va)
    code.label("next_record")
    code += b"\x47"
    code.jump("replay_loop")
    code.label("done")
    code += b"\x61\xc3"
    return code.build()


def build_cursor_blt_trace_helper(
    owner: SidneyPresentationCompiler,
    *,
    wrapper_va: int,
    trace_count_va: int,
    trace_records_va: int,
) -> bytes:
    """Record exact cursor work-surface transfers during SIDNEY draws.

    Entry is an ordinary call from the final-blitter hook: ECX is the
    destination wrapper and the source/destination/source-RECT arguments
    remain on its caller's stack. Only a concrete 128x128 source is kept,
    matching CursorManager's private composition and save-under surfaces.
    """
    code = X86Emitter(base_va=wrapper_va)
    code += b"\x60"
    code += b"\x8b\x74\x24\x28\x85\xf6"  # source wrapper
    code.jump_if(Condition.EQUAL, "done")
    code += b"\x81\x7e\x38" + struct.pack("<I", owner._cursor_atlas_size)
    code.jump_if(Condition.NOT_EQUAL, "done")
    code += b"\x81\x7e\x3c" + struct.pack("<I", owner._cursor_atlas_size)
    code.jump_if(Condition.NOT_EQUAL, "done")

    code += b"\xa1" + struct.pack("<I", trace_count_va)
    code += b"\xff\x05" + struct.pack("<I", trace_count_va)
    code += b"\x83\xe0" + bytes([owner._cursor_blt_trace_capacity - 1])
    code += b"\x6b\xc0" + bytes([owner._cursor_blt_trace_stride])
    code += b"\x05" + struct.pack("<I", trace_records_va)
    code += b"\x8b\xf8"
    code += b"\x8b\x44\x24\x18\x89\x07"  # destination wrapper / saved ECX
    code += b"\x89\x77\x04"
    code += b"\x8b\x44\x24\x24\x89\x47\x08"  # original hook caller
    code += b"\x8b\x44\x24\x18\x8b\x48\x38\x89\x4f\x0c"
    code += b"\x8b\x48\x3c\x89\x4f\x10"
    code += b"\x8b\x4e\x38\x89\x4f\x14\x8b\x4e\x3c\x89\x4f\x18"

    # Clear both optional RECT fields before copying them so a reused ring
    # slot never exposes geometry from an earlier transfer.
    code += b"\x31\xc0"
    for offset in range(28, owner._cursor_blt_trace_stride, 4):
        code += b"\x89\x47" + bytes([offset])
    code += b"\x8b\x74\x24\x2c\x85\xf6\x57"
    code.jump_short_if(Condition.EQUAL, "source_rect")
    code += b"\x8d\x7f\x1c\xb9\x04\x00\x00\x00\xf3\xa5"
    code.label("source_rect")
    # REP MOVSD advances EDI by sixteen bytes after the +28 destination
    # field. Restore the record base on BOTH paths before addressing +44;
    # otherwise the source RECT lands at +88, overrunning the 60-byte record
    # and eventually overwriting the following pointer-motion machine code.
    code += b"\x5f"
    code += b"\x8b\x74\x24\x30\x85\xf6"
    code.jump_short_if(Condition.EQUAL, "done")
    code += b"\x8d\x7f\x2c\xb9\x04\x00\x00\x00\xf3\xa5"
    code.label("done")
    code += b"\x61\xc3"
    return code.build()


def build_damage_selector(
    owner: SidneyPresentationCompiler,
    *,
    wrapper_va: int,
    full_region_va: int,
    full_damage_count_va: int,
    native_damage_count_va: int,
) -> bytes:
    """Select complete logical damage only outside the reference mode."""
    code = X86Emitter(base_va=wrapper_va)
    # The executable derives this choice from live dimensions; changing
    # resolution in GK3's menu never requires repatching.
    code += b"\x81\x3d" + struct.pack("<I", owner._physical_width_global_va)
    code += struct.pack("<I", AUTHORED_FRAME_WIDTH)
    code.jump_if(Condition.NOT_EQUAL, "full")
    code += b"\x81\x3d" + struct.pack("<I", owner._physical_width_global_va + 4)
    code += struct.pack("<I", AUTHORED_FRAME_HEIGHT)
    code.jump_if(Condition.NOT_EQUAL, "full")
    code += b"\xff\x05" + struct.pack("<I", native_damage_count_va)
    code += b"\xc3"
    code.label("full")
    code += b"\xff\x05" + struct.pack("<I", full_damage_count_va)
    code += b"\xb8" + struct.pack("<I", full_region_va) + b"\xc3"
    return code.build()


def build_root_draw_bridge(
    owner: SidneyPresentationCompiler,
    *,
    wrapper_va: int,
    extension_helper_va: int,
    status_replay_helper_va: int,
    damage_selector_va: int,
) -> bytes:
    """Preserve native damage, fill outer bands, and replay status.

    Black pillar bars run after the current center has supplied the
    concrete screen surface. Suppressed status blits are always replayed
    last.
    """
    code = X86Emitter(base_va=wrapper_va)
    # Keep GK3's requested damage at the reference mode and select the
    # complete logical SIDNEY region at every other live resolution.
    code += b"\x8b\x44\x24\x08\x51"
    code.call_absolute(damage_selector_va)
    code += b"\x59"
    code += b"\x51\x50\xff\x74\x24\x0c"
    # Status text must be last: the pillar fill and SIDNEY's center
    # composition can otherwise overwrite its dirty rectangles.
    code.call_absolute(owner._original_root_draw_va)
    code += b"\x59"
    code.call_absolute(extension_helper_va)
    code.call_absolute(status_replay_helper_va)
    code += b"\xc2\x08\x00"
    return code.build()


def build_pillarbox_helper(
    owner: SidneyPresentationCompiler,
    *,
    surface_ptr_va: int,
    left_rect_va: int,
    right_rect_va: int,
    bltfx_va: int,
) -> bytes:
    """Fill only the live widescreen area outside SIDNEY's fitted 4:3 view."""
    code = X86Emitter(base_va=0)
    code += b"\x60"  # pushad: the root draw bridge owns no scratch registers
    code += b"\x8b\x35" + struct.pack("<I", surface_ptr_va)
    code += b"\x85\xf6"
    code.jump_if(Condition.EQUAL, "done")

    # Fit a 4:3 width from physical height, then center the remaining pillar.
    code += b"\xa1" + struct.pack("<I", owner._physical_width_global_va + 4)
    code += b"\xc1\xe0\x02\x99\xb9\x03\x00\x00\x00\xf7\xf9"
    code += b"\x8b\x3d" + struct.pack("<I", owner._physical_width_global_va)
    code += b"\x2b\xf8\xd1\xff\x85\xff"
    code.jump_if(Condition.LESS_OR_EQUAL, "done")

    # Construct [0, 0, pillar, H] and [W-pillar, 0, W, H] in the section.
    # The core presenter now defers and height-fits the status glyphs, so
    # the optional pillar policy can safely clear the full outer bands.
    # Keeping these rectangles private avoids mutating persistent UI state.
    code += b"\x33\xc0\xa3" + struct.pack("<I", left_rect_va)
    code += b"\xa3" + struct.pack("<I", left_rect_va + 4)
    code += b"\x89\x3d" + struct.pack("<I", left_rect_va + 8)
    code += b"\xa1" + struct.pack("<I", owner._physical_width_global_va + 4)
    code += b"\xa3" + struct.pack("<I", left_rect_va + 12)
    code += b"\xa1" + struct.pack("<I", owner._physical_width_global_va)
    code += b"\x8b\xc8\x2b\xcf\x89\x0d" + struct.pack("<I", right_rect_va)
    # Preserve physical W as RECT.right before reusing EAX to zero top.
    code += b"\xa3" + struct.pack("<I", right_rect_va + 8)
    code += b"\x33\xc0\xa3" + struct.pack("<I", right_rect_va + 4)
    code += b"\x8b\x0d" + struct.pack("<I", owner._physical_width_global_va + 4)
    code += b"\x89\x0d" + struct.pack("<I", right_rect_va + 12)

    code += b"\x8b\x1e"  # IDirectDrawSurface vtable
    for rect_va in (left_rect_va, right_rect_va):
        # IDirectDrawSurface4::Blt(surface, rect, NULL, NULL,
        # DDBLT_COLORFILL|DDBLT_WAIT, &fx).  A zero dwFillColor is black.
        code += b"\x68" + struct.pack("<I", bltfx_va)
        code += b"\x68" + struct.pack("<I", owner._ddblt_colorfill_wait)
        code += b"\x6a\x00\x6a\x00"
        code += b"\x68" + struct.pack("<I", rect_va) + b"\x56\xff\x53\x14"

    code.label("done")
    code += b"\x61\xc3"
    return code.build()


def build_native_blt_trampoline(
    owner: SidneyPresentationCompiler,
    *,
    wrapper_va: int,
) -> bytes:
    """Use final glyph sampling without re-entering presentation transforms."""
    # This is not another hook owner.  It is a private continuation used
    # only by status replay after the public 0x0054F980 entry was replaced.
    code = X86Emitter(base_va=wrapper_va)
    code.jump_absolute(
        owner.symbols.va(SPRITE_CACHE_SEGMENT.logical_name, SPRITE_CACHE_TRANSFER_OFFSET)
    )
    return code.build()


def build_backdrop_helper(
    owner: SidneyPresentationCompiler,
    *,
    pending_va: int,
    left_rect_va: int,
    right_rect_va: int,
    bltfx_va: int,
) -> bytes:
    """Color-fill SIDNEY's logical side bands on its screen surface once per frame."""
    code = X86Emitter(base_va=0)
    code += b"\x60"  # pushad; ECX is the engine's destination-surface wrapper
    code += b"\x83\x3d" + struct.pack("<I", pending_va) + b"\x00"
    code.jump_short_if(Condition.EQUAL, "done")
    code += b"\xc7\x05" + struct.pack("<I", pending_va) + b"\x00\x00\x00\x00"
    code += b"\x8b\x71\x2c"  # underlying IDirectDrawSurface
    code += b"\x85\xf6"
    code.jump_short_if(Condition.EQUAL, "done")
    code += b"\x8b\x1e"  # surface vtable

    for rect_va in (left_rect_va, right_rect_va):
        code += b"\x68" + struct.pack("<I", bltfx_va)
        code += b"\x68" + struct.pack("<I", owner._ddblt_colorfill_wait)
        code += b"\x6a\x00"  # source RECT
        code += b"\x6a\x00"  # source surface
        code += b"\x68" + struct.pack("<I", rect_va)
        code += b"\x56"  # this
        code += b"\xff\x53\x14"  # IDirectDrawSurface::Blt

    code.label("done")
    code += b"\x61\xc3"  # popad; ret
    return code.build()
