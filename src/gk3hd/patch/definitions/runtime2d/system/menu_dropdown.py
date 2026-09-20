"""Compile graphics-options dropdown layout, hover, and presentation."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.layout import (
    SYSTEM_CONTROL_DROPDOWN_HIGHLIGHT_TRACE_OFFSET,
    SYSTEM_CONTROL_DROPDOWN_SEED_BUDGET_OFFSET,
)
from gk3hd.patch.definitions.runtime2d.system.menu_exports import DropdownRuntimeExports
from gk3hd.patch.definitions.runtime2d.system.shared import SystemCompilerContext

if TYPE_CHECKING:
    from gk3hd.patch.binary.payload import SegmentPayloadBuilder


@dataclass(frozen=True, slots=True, kw_only=True)
class DropdownFeatureCompiler(SystemCompilerContext):
    """Preserve the complete graphics-resolution popup and its row feedback.

    Outcome:
        Every enumerated resolution row remains visible, contiguous, hoverable,
        and above its parent Graphics panel at reference-relative scale.

    Before:
        The stock popup grows from runtime driver modes but retains authored
        damage and hit geometry. Modern mode counts can therefore clip rows,
        retain only part of a highlight, or present the list on one flip page.

    After:
        One popup lifetime owns fitted bounds, full-list damage, row-highlight
        geometry, input, and withdrawal across both DirectDraw pages.

    Strategy:
        Wrap visibility and Draw, fit the live row collection inside its parent
        root, transform solid-highlight spans through the published affine, and
        present the complete list only while its concrete object is live.

    Boundaries:
        Driver mode enumeration stays with ``enable_modern_resolutions``. The
        parent toolbar, tooltip, cursor, and display-mode policies retain their
        existing owners.
    """

    def emit_runtime(
        self,
        payload: SegmentPayloadBuilder,
        *,
        system_va: int,
        control_va: int,
    ) -> DropdownRuntimeExports:
        """Compile the graphics-options dropdown as one bounded subdomain."""
        draw_va = control_va + self._off_resolution_dropdown_draw_wrapper
        visibility_va = control_va + self._off_resolution_dropdown_visibility_wrapper
        present_va = control_va + self._off_resolution_dropdown_present_helper
        fit_va = control_va + self._off_resolution_dropdown_fit_helper
        highlight_va = control_va + self._off_resolution_dropdown_highlight_wrapper
        draw = self.build_resolution_dropdown_draw_wrapper(
            wrapper_va=draw_va,
            input_active_va=system_va + self._off_input_active,
            root_ptr_va=system_va + self._off_root_ptr,
            pending_ptr_va=control_va + self._off_control_dropdown_pending_ptr,
            fit_helper_va=fit_va,
            target_va=self._native_resolution_dropdown_draw_va,
        )
        visibility = self.build_resolution_dropdown_visibility_wrapper(
            wrapper_va=visibility_va,
            input_active_va=system_va + self._off_input_active,
            root_ptr_va=system_va + self._off_root_ptr,
            pending_ptr_va=control_va + self._off_control_dropdown_pending_ptr,
            seed_budget_va=control_va + SYSTEM_CONTROL_DROPDOWN_SEED_BUDGET_OFFSET,
            saved_root_bottom_va=control_va + self._off_control_dropdown_saved_root_bottom,
            root_bottom_valid_va=control_va + self._off_control_dropdown_root_bottom_valid,
            fit_helper_va=fit_va,
            target_va=self._native_resolution_dropdown_visibility_va,
        )
        present = self.build_resolution_dropdown_present_helper(
            wrapper_va=present_va,
            pending_ptr_va=control_va + self._off_control_dropdown_pending_ptr,
            root_ptr_va=system_va + self._off_root_ptr,
            saved_root_bottom_va=control_va + self._off_control_dropdown_saved_root_bottom,
            root_bottom_valid_va=control_va + self._off_control_dropdown_root_bottom_valid,
            render_depth_va=system_va + self._off_render_depth,
            full_damage_region_va=control_va + self._off_control_full_damage_region,
            full_damage_rect_va=control_va + self._off_control_full_damage_rect,
            target_va=self._native_resolution_dropdown_draw_va,
        )
        fit = self.build_resolution_dropdown_fit_helper(
            wrapper_va=fit_va,
            root_ptr_va=system_va + self._off_root_ptr,
        )
        highlight = self.build_resolution_dropdown_highlight_wrapper(
            wrapper_va=highlight_va,
            pending_ptr_va=control_va + self._off_control_dropdown_pending_ptr,
            source_rect_va=system_va + self._off_source_rect,
            target_rect_va=system_va + self._off_target_rect,
            full_damage_region_va=control_va + self._off_control_full_damage_region,
            transform_count_va=control_va + self._off_control_cursor_state + 156,
            trace_va=control_va + SYSTEM_CONTROL_DROPDOWN_HIGHLIGHT_TRACE_OFFSET,
            target_va=self._native_solid_color_draw_va,
        )
        for label, offset, code, limit in (
            (
                "resolution dropdown draw",
                self._off_resolution_dropdown_draw_wrapper,
                draw,
                self._off_resolution_dropdown_visibility_wrapper,
            ),
            (
                "resolution dropdown visibility",
                self._off_resolution_dropdown_visibility_wrapper,
                visibility,
                self._off_resolution_dropdown_visibility_limit,
            ),
            (
                "resolution dropdown present",
                self._off_resolution_dropdown_present_helper,
                present,
                self._off_resolution_dropdown_present_limit,
            ),
            (
                "resolution dropdown fit",
                self._off_resolution_dropdown_fit_helper,
                fit,
                self._off_resolution_dropdown_fit_limit,
            ),
            (
                "resolution dropdown highlight",
                self._off_resolution_dropdown_highlight_wrapper,
                highlight,
                self._off_resolution_dropdown_highlight_limit,
            ),
        ):
            payload.place(label=label, offset=offset, payload=code, limit=limit)
        return DropdownRuntimeExports(
            draw_wrapper_va=draw_va,
            visibility_wrapper_va=visibility_va,
            highlight_wrapper_va=highlight_va,
            present_helper_va=present_va,
        )

    def build_resolution_dropdown_draw_wrapper(
        self,
        *,
        wrapper_va: int,
        input_active_va: int,
        root_ptr_va: int,
        pending_ptr_va: int,
        fit_helper_va: int,
        target_va: int,
    ) -> bytes:
        """Defer the toolbar's sibling combo-list until the toolbar is drawn.

        This ordering is independent of presentation scale. The list is a
        sibling inserted before ``InGameToolbar`` in the room layer, while the
        toolbar's complete-damage traversal necessarily covers their shared
        rectangle. Drawing the sibling afterward preserves the native z-order
        at both authored and transformed resolutions. The fit helper itself is
        an identity operation when the authored list already fits.
        """
        # The expanded resolution list is inserted into the room layer as a
        # sibling before InGameToolbar::Draw. Rendering immediately lets the
        # later scaled panel cover it. Retain only this live pointer; the
        # toolbar post-draw helper consumes and clears it in the same traversal.
        # Generic list boxes elsewhere retain their native behavior.
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x83\x3d" + struct.pack("<I", input_active_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\xa1" + struct.pack("<I", root_ptr_va) + b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("ingame_toolbar.vtable")))
        code.jump_if(Condition.NOT_EQUAL, "native")
        # Keep the complete driver-mode list on screen before deferring it.
        # The helper preserves ECX, so the pending pointer remains the popup.
        code.call_absolute(fit_helper_va)
        code.raw(b"\x89\x0d" + struct.pack("<I", pending_ptr_va))
        code.raw(b"\xc2\x08\x00")
        code.label("native")
        code.jump_absolute(target_va)
        return code.build()

    def build_resolution_dropdown_present_helper(
        self,
        *,
        wrapper_va: int,
        pending_ptr_va: int,
        root_ptr_va: int,
        saved_root_bottom_va: int,
        root_bottom_valid_va: int,
        render_depth_va: int,
        full_damage_region_va: int,
        full_damage_rect_va: int,
        target_va: int,
    ) -> bytes:
        """Draw one complete deferred resolution list over a changed toolbar."""
        # This helper receives the toolbar Draw arguments and owns RET 8. The
        # popup is a sibling rather than a toolbar child, so retain its exact
        # object for the complete visible lifetime: the pre-Flip frame owner
        # must be able to repaint it onto every DirectDraw peer after staging
        # replaces the page. Validate both allocation and concrete class on
        # every use; the toolbar destructor clears the pointer synchronously.
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x8b\x0d" + struct.pack("<I", pending_ptr_va) + b"\x85\xc9")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x68\x78\x01\x00\x00\x51\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "withdraw")
        code.raw(b"\x8b\x0d" + struct.pack("<I", pending_ptr_va))
        code.raw(
            b"\x81\x39" + struct.pack("<I", self.profile.address("resolution_dropdown.vtable"))
        )
        code.jump_if(Condition.NOT_EQUAL, "withdraw")
        code.raw(b"\x80\x79\x18\x00")
        code.jump_if(Condition.EQUAL, "withdraw")

        # Complete the reusable one-RECT region from the live framebuffer.
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va))
        code.raw(b"\xa3" + struct.pack("<I", full_damage_rect_va + 8))
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\xa3" + struct.pack("<I", full_damage_rect_va + 12))
        # The helper maps both the popup clip and its row anchors. The shared
        # toolbar blitter recognizes its short-lived layout-active flag and
        # scales only each transfer's still-native extent about that already-
        # physical top-left. Restore authored geometry before input resumes.
        code.raw(b"\xff\x05" + struct.pack("<I", render_depth_va))
        # The toolbar traversal which reached this post-draw hook is already
        # damage-gated by the final page owner, so this does not create idle
        # work. Its sibling popup must nevertheless receive complete damage on
        # every such traversal: otherwise the parent can repaint through rows
        # outside the caller's small native collection, producing a visually
        # split list after hover/tooltip changes. Compose all rows once, then
        # let the modal cache publish that exact generation to the peer page.
        code.raw(b"\xb8" + struct.pack("<I", full_damage_region_va))
        code.raw(b"\x51\x50\xff\x74\x24\x0c")
        code.call_absolute(target_va)
        code.raw(b"\x59")
        code.raw(b"\xff\x0d" + struct.pack("<I", render_depth_va))
        code.jump_short("done")
        code.label("withdraw")
        code.raw(b"\xc7\x05" + struct.pack("<I", pending_ptr_va) + b"\x00\x00\x00\x00")
        # Native Escape can retire the sibling without our SetVisible hook.
        # Withdraw the temporary root union here as well as on explicit Hide;
        # clearing only the popup pointer leaves its extra rows in every later
        # toolbar layout and accumulates a permanent panel-height error.
        code.raw(b"\x83\x3d" + struct.pack("<I", root_bottom_valid_va) + b"\x00")
        code.jump_short_if(Condition.EQUAL, "done")
        code.raw(b"\xa1" + struct.pack("<I", root_ptr_va) + b"\x85\xc0")
        code.jump_short_if(Condition.EQUAL, "clear_bottom")
        code.raw(b"\x8b\x15" + struct.pack("<I", saved_root_bottom_va) + b"\x89\x50\x28")
        code.label("clear_bottom")
        code.raw(b"\xc7\x05" + struct.pack("<I", root_bottom_valid_va) + bytes(4))
        code.label("done")
        code.raw(b"\xc2\x08\x00")
        return code.build()

    def build_resolution_dropdown_visibility_wrapper(
        self,
        *,
        wrapper_va: int,
        input_active_va: int,
        root_ptr_va: int,
        pending_ptr_va: int,
        seed_budget_va: int,
        saved_root_bottom_va: int,
        root_bottom_valid_va: int,
        fit_helper_va: int,
        target_va: int,
    ) -> bytes:
        """Own the resolution popup from visibility change through destruction.

        ``ResolutionList::Draw`` is too late to establish popup geometry: its
        visible byte has already changed, so one front-buffer frame can expose
        the original downward-opening rectangle before the first Draw fits it.
        The concrete class's inherited ``SetVisible(bool)`` slot is the actual
        lifetime boundary. Fit and retain the popup synchronously on Show;
        withdraw only that same identity on Hide. Native invalidation then
        observes the final rectangle and no capture-loop timing is involved.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x80\x7c\x24\x04\x00")
        code.jump_short_if(Condition.EQUAL, "hide")

        # ResolutionList is used by the in-room Graphics panel. Require the
        # exact toolbar scope before publishing it to the pre-Flip presenter;
        # the fit helper independently requires the live root pointer.
        code.raw(b"\x83\x3d" + struct.pack("<I", input_active_va) + b"\x00")
        code.jump_short_if(Condition.EQUAL, "native")
        # The fit helper uses PUSHAD/POPAD, so ECX remains the popup for both
        # publication and the tail call to native SetVisible(bool).
        code.call_absolute(fit_helper_va)
        # ResolutionList is a room-layer sibling, not a toolbar child. Expand
        # the owning toolbar root explicitly so its affine, damage collection,
        # retention cache, and final ownership predicate include every fitted
        # row. Retain the exact preceding bottom only once across repeated Show
        # notifications; no authored or output-resolution constant is needed.
        code.raw(b"\xa1" + struct.pack("<I", root_ptr_va) + b"\x85\xc0")
        code.jump_short_if(Condition.EQUAL, "publish")
        code.raw(b"\x83\x3d" + struct.pack("<I", root_bottom_valid_va) + b"\x00")
        code.jump_short_if(Condition.NOT_EQUAL, "root_bottom_saved")
        code.raw(b"\x8b\x50\x28\x89\x15" + struct.pack("<I", saved_root_bottom_va))
        code.raw(b"\xc7\x05" + struct.pack("<I", root_bottom_valid_va) + b"\x01\x00\x00\x00")
        code.label("root_bottom_saved")
        code.raw(b"\x8b\x51\x28\x39\x50\x28")
        code.jump_short_if(Condition.GREATER_OR_EQUAL, "publish")
        code.raw(b"\x89\x50\x28")
        code.label("publish")
        code.raw(b"\x89\x0d" + struct.pack("<I", pending_ptr_va))
        code.jump_short("seed")

        code.label("hide")
        code.raw(b"\x39\x0d" + struct.pack("<I", pending_ptr_va))
        code.jump_short_if(Condition.NOT_EQUAL, "native")
        code.raw(b"\xc7\x05" + struct.pack("<I", pending_ptr_va) + b"\x00\x00\x00\x00")
        # Withdraw the sibling from the root union at the same exact lifetime
        # boundary. Clearing validity even if the root is already gone avoids a
        # stale saved bottom being inherited by the next toolbar allocation.
        code.raw(b"\x83\x3d" + struct.pack("<I", root_bottom_valid_va) + b"\x00")
        code.jump_short_if(Condition.EQUAL, "seed")
        code.raw(b"\xa1" + struct.pack("<I", root_ptr_va) + b"\x85\xc0")
        code.jump_short_if(Condition.EQUAL, "clear_root_bottom")
        code.raw(b"\x8b\x15" + struct.pack("<I", saved_root_bottom_va) + b"\x89\x50\x28")
        code.label("clear_root_bottom")
        code.raw(b"\xc7\x05" + struct.pack("<I", root_bottom_valid_va) + b"\x00\x00\x00\x00")
        code.label("seed")
        # Visibility changes alter a sibling outside the toolbar's ordinary
        # small damage collection. Rebuild both DirectDraw peers completely so
        # Show cannot omit every list row and Hide cannot leave a stale list on
        # the alternate page. The pre-Flip owner consumes this two-frame budget.
        code.raw(b"\xc7\x05" + struct.pack("<I", seed_budget_va) + b"\x02\x00\x00\x00")
        code.label("native")
        code.jump_absolute(target_va)
        return code.build()

    def build_resolution_dropdown_fit_helper(
        self,
        *,
        wrapper_va: int,
        root_ptr_va: int,
    ) -> bytes:
        """Move a long resolution list upward only when its scaled bottom overflows."""
        # ECX is the popup. GK3 inserts it as a sibling of InGameToolbar and
        # gives it one direct text child per driver mode. The toolbar affine
        # scales every transfer about the authored 252x75 base and maps that
        # anchor from the live room stage to the framebuffer. Calculate the
        # popup's final bottom through that exact affine. If it would cross the
        # framebuffer, translate the popup and every row by the inverse-scaled
        # overflow. The live rectangles stay translated until destruction, so
        # native hit testing and rendered pixels agree.
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x60\x8b\xf1")
        code.raw(b"\x8b\x3d" + struct.pack("<I", root_ptr_va) + b"\x85\xff")
        code.jump_if(Condition.EQUAL, "done")

        # EBP is the signed vertical center of the stable 75-pixel toolbar
        # base. The root's bottom grows to include Advanced/Graphics panels,
        # so averaging its current top and bottom would make this anchor follow
        # the expanded union and under-correct the popup overflow.
        code.raw(b"\x8b\x6f\x20\x83\xc5\x25")
        # The direct renderer keeps toolbar coordinates in framebuffer space,
        # so its stable authored-base centre is already the presented anchor.
        code.raw(b"\x8b\xdd")
        code.raw(b"\x8b\x46\x28\x2b\xc5")
        code.raw(b"\x0f\xaf\x05" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\x99\xb9\x00\x03\x00\x00\xf7\xf9\x03\xc3")
        code.raw(b"\x2b\x05" + struct.pack("<I", self._physical_width_va + 4))
        code.jump_if(Condition.LESS_OR_EQUAL, "done")

        # EAX is physical overflow. Convert it back to an authored-coordinate
        # translation with ceil(overlap * 768 / physical_height), ensuring the
        # recomputed far edge never remains one rounding pixel off screen.
        code.raw(b"\x69\xc0\x00\x03\x00\x00")
        code.raw(b"\x8b\x1d" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\x8d\x44\x18\xff\x31\xd2\xf7\xf3\x8b\xe8")
        code.raw(b"\x29\x6e\x20\x29\x6e\x28")
        code.raw(b"\x8b\x7e\x4c\x8b\x5e\x50\x31\xc9")
        code.label("child_loop")
        code.raw(b"\x3b\xcb")
        code.jump_if(Condition.ABOVE_OR_EQUAL, "done")
        code.raw(b"\x8b\x34\x8f\x85\xf6")
        code.jump_if(Condition.EQUAL, "next_child")
        code.raw(b"\x29\x6e\x20\x29\x6e\x28")
        code.label("next_child")
        code.raw(b"\x41")
        code.jump("child_loop")
        code.label("done")
        code.raw(b"\x61\xc3")
        return code.build()

    def build_resolution_dropdown_highlight_wrapper(
        self,
        *,
        wrapper_va: int,
        pending_ptr_va: int,
        source_rect_va: int,
        target_rect_va: int,
        full_damage_region_va: int,
        transform_count_va: int,
        trace_va: int,
        target_va: int,
    ) -> bytes:
        """Present the resolution list's solid hover child through its live affine.

        The list background and labels are bitmap objects and naturally reach
        the shared final-blit hook. Its current-row highlight is instead the
        one embedded ``SolidColorObject`` at ``ResolutionList + 0x134``; native
        code submits that child through the separate color-primitive queue.
        Hook the primitive's virtual Draw slot, but transform only that exact
        live child identity. This keeps every other solid UI object native and
        avoids classifying fills by color, dimensions, screen location, or an
        output resolution.

        The native method reads its rectangle synchronously while building the
        queued primitive. Temporarily publish the physical rectangle, give it
        the same complete damage region as the retained toolbar, then restore
        authored geometry before input hit testing resumes.
        """
        # SolidColorObject::Draw is thiscall(destination handle, damage region)
        # and owns RET 8. Keep four private stack DWORDs for its authored RECT
        # and four for the source/target X/Y centres shared by all four edges.
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x55\x8b\xec\x83\xec\x20\x53\x56\x57\x8b\xd9")
        code.raw(b"\xa1" + struct.pack("<I", pending_ptr_va) + b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\x05\x34\x01\x00\x00\x3b\xd8")
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.raw(b"\x81\x3b" + struct.pack("<I", self.profile.address("solid_color.vtable")))
        code.jump_if(Condition.NOT_EQUAL, "native")

        # Retain the values consumed by this exact draw. Source/target are live
        # traversal state, so a process read after Flip cannot otherwise prove
        # which affine the queued primitive used.
        code.raw(b"\xff\x05" + struct.pack("<I", trace_va))
        for source_va, destination_va in (
            (None, trace_va + 4),
            (source_rect_va + 4, trace_va + 8),
            (source_rect_va + 12, trace_va + 12),
            (target_rect_va + 4, trace_va + 16),
            (target_rect_va + 12, trace_va + 20),
        ):
            if source_va is None:
                code.raw(b"\x8b\x43\x20")
            else:
                code.raw(b"\xa1" + struct.pack("<I", source_va))
            code.raw(b"\xa3" + struct.pack("<I", destination_va))

        # Retain the object's authored rectangle. The pending-list identity is
        # durable for the popup lifetime, but its hit-test geometry must remain
        # in the stage domain outside this one synchronous draw transaction.
        code.raw(b"\x8d\x73\x1c\x8d\x7d\xf0\xb9\x04\x00\x00\x00\xf3\xa5")

        # Compute the X/Y source and target centres once. Besides keeping the
        # injected policy compact, this makes one draw use one coherent affine
        # snapshot even if the render thread publishes the next frame between
        # individual edge calculations.
        for first, second, local_offset in (
            (0, 8, 0xEC),
            (4, 12, 0xE8),
            (0, 8, 0xE4),
            (4, 12, 0xE0),
        ):
            rect_va = source_rect_va if local_offset in (0xEC, 0xE8) else target_rect_va
            code.raw(b"\xa1" + struct.pack("<I", rect_va + first))
            code.raw(b"\x03\x05" + struct.pack("<I", rect_va + second))
            code.raw(b"\xd1\xf8\x89\x45" + bytes([local_offset]))

        # Map every edge through those exact centres. Extents use the universal
        # reference-height ratio; target anchors already include the independent
        # live stage-to-screen ratio.
        for displacement, source_local, target_local in (
            (0, 0xEC, 0xE4),
            (4, 0xE8, 0xE0),
            (8, 0xEC, 0xE4),
            (12, 0xE8, 0xE0),
        ):
            code.raw(b"\x8b\x43" + bytes([0x1C + displacement]))
            code.raw(b"\x2b\x45" + bytes([source_local]))
            code.raw(b"\x0f\xaf\x05" + struct.pack("<I", self._physical_width_va + 4))
            code.raw(b"\x99\xb9\x00\x03\x00\x00\xf7\xf9")
            code.raw(b"\x03\x45" + bytes([target_local]))
            code.raw(b"\x89\x43" + bytes([0x1C + displacement]))

        code.raw(b"\x8b\x43\x20\xa3" + struct.pack("<I", trace_va + 24))
        code.raw(b"\x8b\x43\x28\xa3" + struct.pack("<I", trace_va + 28))

        code.raw(b"\x68" + struct.pack("<I", full_damage_region_va))
        code.raw(b"\xff\x75\x08\x8b\xcb")
        code.call_absolute(target_va)
        code.raw(b"\x8b\xf0")
        for displacement, local_offset in ((0, 0xF0), (4, 0xF4), (8, 0xF8), (12, 0xFC)):
            code.raw(b"\x8b\x45" + bytes([local_offset]))
            code.raw(b"\x89\x43" + bytes([0x1C + displacement]))
        code.raw(b"\xff\x05" + struct.pack("<I", transform_count_va) + b"\x8b\xc6")
        code.jump("done")

        code.label("native")
        code.raw(b"\xff\x75\x0c\xff\x75\x08\x8b\xcb")
        code.call_absolute(target_va)
        code.label("done")
        code.raw(b"\x5f\x5e\x5b\xc9\xc2\x08\x00")
        return code.build()
