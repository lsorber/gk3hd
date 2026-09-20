"""Compile class-scoped transforms for bounded system screens."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.geometry import AUTHORED_FRAME_HEIGHT, AUTHORED_FRAME_WIDTH
from gk3hd.patch.definitions.runtime2d.layout import (
    CONSOLE_DAMAGE_OFFSET,
    CONSOLE_OWNER_OFFSET,
    CONSOLE_SEGMENT,
    FINGERPRINT_DAMAGE_SELECTOR_OFFSET,
    FINGERPRINT_SEGMENT,
    SYSTEM_ACTION_PRESENTED_ROOT_OFFSET,
    SYSTEM_CONTROL_CLOSEUP_DEST_HANDLE_OFFSET,
    SYSTEM_CONTROL_CLOSEUP_LAST_OWNER_OFFSET,
    SYSTEM_CONTROL_CLOSEUP_PRESENT_COUNT_OFFSET,
    SYSTEM_CONTROL_CLOSEUP_SEED_BUDGET_OFFSET,
    SYSTEM_CONTROL_CLOSEUP_STATE_END_OFFSET,
    SYSTEM_CONTROL_CONFIRM_QUIT_COPY_COUNT_OFFSET,
    SYSTEM_CONTROL_CONFIRM_QUIT_COPY_PENDING_OFFSET,
    SYSTEM_CONTROL_CONFIRM_QUIT_COPY_RESULT_OFFSET,
    SYSTEM_CONTROL_CONFIRM_QUIT_CURSOR_REFCOUNT_OFFSET,
    SYSTEM_CONTROL_CONFIRM_QUIT_CURSOR_SUSPENDED_OFFSET,
    SYSTEM_CONTROL_CONFIRM_QUIT_ROOM_REPAIR_COLLECTION_OFFSET,
    SYSTEM_CONTROL_CONFIRM_QUIT_ROOM_REPAIR_RECT_OFFSET,
    SYSTEM_CONTROL_CONFIRM_QUIT_ROOM_REPAIR_STATE_END_OFFSET,
    SYSTEM_CONTROL_CONFIRM_QUIT_SEEDED_ROOT_OFFSET,
    SYSTEM_CONTROL_CONFIRM_QUIT_STATE_END_OFFSET,
    SYSTEM_CONTROL_CURSOR_RESOURCE_ROOM_ROOT_OFFSET,
)
from gk3hd.patch.definitions.runtime2d.system.lifecycle import ScreenLifecycleTargets
from gk3hd.patch.definitions.runtime2d.system.shared import SystemCompilerContext

if TYPE_CHECKING:
    from gk3hd.patch.binary.mutations import ExecutableMutationPlan
    from gk3hd.patch.binary.payload import SegmentPayloadBuilder


def _emit_state_transitions(
    code: X86Emitter, transitions: tuple[tuple[int, tuple[int, ...], int], ...]
) -> None:
    """Withdraw only an acquired state; dormant lifecycle callbacks own nothing."""
    for index, (address, previous, following) in enumerate(transitions):
        for value in previous[:-1]:
            code.raw(b"\x81\x3d" + struct.pack("<II", address, value))
            code.jump_short_if(Condition.EQUAL, f"transition_write_{index}")
        code.raw(b"\x81\x3d" + struct.pack("<II", address, previous[-1]))
        code.jump_short_if(Condition.NOT_EQUAL, f"transition_done_{index}")
        code.label(f"transition_write_{index}")
        code.raw(b"\xc7\x05" + struct.pack("<II", address, following))
        code.label(f"transition_done_{index}")


@dataclass(frozen=True, slots=True)
class PrimaryFixedScreenExports:
    """Lifecycle entries exported by the compact primary-system segment."""

    death: ScreenLifecycleTargets
    death_button_layout_va: int
    finished_draw_va: int
    finished_destructor_va: int
    pause_draw_va: int


@dataclass(frozen=True, slots=True)
class FixedScreenLifecycleExports:
    """Typed lifecycle entries exported by fixed control-tail screens."""

    title: ScreenLifecycleTargets
    confirm_quit: ScreenLifecycleTargets
    closeup: ScreenLifecycleTargets
    fingerprint: ScreenLifecycleTargets
    title_cache_wrapper_va: int
    physical_backdrop_wrapper_va: int
    console_draw_scope_va: int
    confirm_quit_post_flip_presenter_va: int
    closeup_frame_presenter_va: int


@dataclass(frozen=True, slots=True, kw_only=True)
class FixedScreenFeatureCompiler(SystemCompilerContext):
    """Fit bounded system-screen roots without narrowing ordinary rooms.

    Outcome:
        Title, Death, Finished, confirmation, close-up, and related fixed roots
        retain their authored composition and interactive scale.
    Before:
        GK3 stretches 640x480 roots independently on each axis or combines a
        physical anchor with authored child extents.
    After:
        Each concrete root publishes one named coordinate mode for its complete
        traversal and lifetime; unrelated layers remain outside the scope.
    Strategy:
        Wrap class Draw, Show, Hide, and destruction edges, prepare bounded
        damage, and pass final transfers through the shared dispatcher.
    Boundaries:
        Menu, Load/Save, binocular, cursor, room-status, and resource-specific
        behavior belongs to their dedicated feature owners.
    """

    def emit_state(self, payload: SegmentPayloadBuilder) -> None:
        """Own retained data used only by title and fixed-root presentation."""
        # Four RECT/trace words cover the dense title background cache. Its
        # final byte is the next named control-header field, so the 0x40-byte
        # reservation cannot overlap dropdown state.
        payload.reserve(
            label="title cache state",
            offset=self._off_title_cache_dest_rect,
            size=0x40,
        )
        payload.reserve(
            label="CloseUp canvas state",
            offset=SYSTEM_CONTROL_CLOSEUP_DEST_HANDLE_OFFSET,
            size=SYSTEM_CONTROL_CLOSEUP_STATE_END_OFFSET
            - SYSTEM_CONTROL_CLOSEUP_DEST_HANDLE_OFFSET,
        )
        payload.reserve(
            label="ConfirmQuit peer-page copy state",
            offset=SYSTEM_CONTROL_CONFIRM_QUIT_COPY_PENDING_OFFSET,
            size=SYSTEM_CONTROL_CONFIRM_QUIT_STATE_END_OFFSET
            - SYSTEM_CONTROL_CONFIRM_QUIT_COPY_PENDING_OFFSET,
        )
        payload.reserve(
            label="ConfirmQuit underlying-room repair state",
            offset=SYSTEM_CONTROL_CONFIRM_QUIT_ROOM_REPAIR_COLLECTION_OFFSET,
            size=SYSTEM_CONTROL_CONFIRM_QUIT_ROOM_REPAIR_STATE_END_OFFSET
            - SYSTEM_CONTROL_CONFIRM_QUIT_ROOM_REPAIR_COLLECTION_OFFSET,
        )

    def emit_primary_lifecycles(
        self,
        payload: SegmentPayloadBuilder,
        *,
        system_va: int,
        control_va: int,
    ) -> PrimaryFixedScreenExports:
        """Compile Death and Finished lifecycles into the primary segment."""
        death = ScreenLifecycleTargets(
            draw_va=system_va + self._off_root_draw_wrapper,
            show_va=system_va + self._off_show_wrapper,
            hide_va=system_va + self._off_hide_wrapper,
            destructor_va=system_va + self._off_destructor_wrapper,
        )
        finished_draw_va = system_va + self._off_finished_root_draw_wrapper
        finished_destructor_va = system_va + self._off_finished_destructor_wrapper
        root_wrapper = self.build_root_draw_wrapper(
            wrapper_va=death.draw_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            transform_mode=self._mode_composite,
            input_enabled=True,
            target_va=self._native_draw_va,
            full_damage_region_va=control_va + self._off_control_full_damage_region,
            full_damage_rect_va=control_va + self._off_control_full_damage_rect,
        )
        show_wrapper = self.build_state_wrapper(
            state_va=system_va + self._off_input_active,
            value=1,
            target_va=self._native_show_va,
            wrapper_va=death.show_va,
        )
        hide_wrapper = self.build_state_wrapper(
            state_va=system_va + self._off_input_active,
            value=0,
            target_va=self._native_hide_va,
            wrapper_va=death.hide_va,
        )
        destructor_wrapper = self.build_destructor_wrapper(
            wrapper_va=death.destructor_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            target_va=self._native_destructor_va,
        )
        finished_root_wrapper = self.build_root_draw_wrapper(
            wrapper_va=finished_draw_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            transform_mode=self._mode_composite,
            input_enabled=False,
            target_va=self._native_draw_va,
        )
        finished_destructor_wrapper = self.build_destructor_wrapper(
            wrapper_va=finished_destructor_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            target_va=self._native_finished_destructor_va,
        )
        for label, offset, code, limit in (
            ("Death root", self._off_root_draw_wrapper, root_wrapper, self._off_show_wrapper),
            ("Death show", self._off_show_wrapper, show_wrapper, self._off_hide_wrapper),
            ("Death hide", self._off_hide_wrapper, hide_wrapper, self._off_destructor_wrapper),
            (
                "Death destructor",
                self._off_destructor_wrapper,
                destructor_wrapper,
                self._off_finished_root_draw_wrapper,
            ),
            (
                "Finished root",
                self._off_finished_root_draw_wrapper,
                finished_root_wrapper,
                self._off_finished_destructor_wrapper,
            ),
            (
                "Finished destructor",
                self._off_finished_destructor_wrapper,
                finished_destructor_wrapper,
                self._off_blt_wrapper,
            ),
        ):
            payload.place(label=label, offset=offset, payload=code, limit=limit)
        death_button_layout_va = system_va + self._off_death_button_layout
        pause_draw_va = system_va + self._off_pause_draw_scope
        payload.place(
            label="Pause centered draw scope",
            offset=self._off_pause_draw_scope,
            payload=self.build_pause_draw_scope(
                wrapper_va=pause_draw_va, system_va=system_va, control_va=control_va
            ),
            limit=self._off_binocs_root_draw_wrapper,
        )
        payload.place(
            label="Death reference-rounded button anchors",
            offset=self._off_death_button_layout,
            payload=self.build_death_button_layout(wrapper_va=death_button_layout_va),
            limit=self._off_toolbar_blt_helper,
        )
        return PrimaryFixedScreenExports(
            death=death,
            death_button_layout_va=death_button_layout_va,
            finished_draw_va=finished_draw_va,
            finished_destructor_va=finished_destructor_va,
            pause_draw_va=pause_draw_va,
        )

    def build_pause_draw_scope(self, *, wrapper_va: int, system_va: int, control_va: int) -> bytes:
        """Scale the centered Pause banner without retaining modal input state.

        Pause has no interactive children. Its keyboard-driven Show/Hide and
        native dimmed backdrop remain untouched; only this concrete Draw owns
        the local-root affine. Restore every shared field after traversal so
        returning to the room cannot inherit a stale modal coordinate space.
        """
        code = X86Emitter(base_va=wrapper_va)
        fields = (
            self._off_root_ptr,
            self._off_render_depth,
            self._off_input_active,
            self._off_clear_pending,
            self._off_transform_mode,
        )
        for offset in fields:
            code.raw(b"\xff\x35" + struct.pack("<I", system_va + offset))
        code.raw(b"\x89\x0d" + struct.pack("<I", system_va + self._off_root_ptr))
        for offset, value in zip(fields[1:], (1, 0, 0, self._mode_local_root_canvas), strict=True):
            code.raw(b"\xc7\x05" + struct.pack("<II", system_va + offset, value))
        for offset in (0, 4):
            code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va + offset))
            code.raw(
                b"\xa3"
                + struct.pack("<I", control_va + self._off_control_full_damage_rect + 8 + offset)
            )
        # Five saved words: after pushing arg2, the original arg1 is at +0x1c.
        code.raw(b"\x68" + struct.pack("<I", control_va + self._off_control_full_damage_region))
        code.raw(b"\xff\x74\x24\x1c")
        code.call_absolute(self._native_draw_va)
        for offset in reversed(fields):
            code.raw(b"\x8f\x05" + struct.pack("<I", system_va + offset))
        code.raw(b"\xc2\x08\x00")
        return code.build()

    def build_death_button_layout(self, *, wrapper_va: int) -> bytes:
        """Position Death buttons from the rounded 1024 reference, not 640.

        Native layout scales both authored edges from 640x480 and then keeps
        only their integer centre. Repeating that rounding at each resolution
        shifts the labels relative to the 1024 reference. At these three call
        sites the button still has its freshly assigned authored rectangle.
        Round its edges to 1024 first, map that centre to the physical domain,
        and preserve logical extents for the existing draw/input transforms.
        The virtual SetRect call retains native invalidation and child layout.
        No framebuffer globals are temporarily changed.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x55\x8b\xec\x83\xec\x10\x60\x8b\x75\x08")
        for edge, buffer, physical, reference in (
            (0x1C, 0xF0, self._physical_width_va, 1024),
            (0x20, 0xF4, self._physical_width_va + 4, 768),
        ):
            code.raw(b"\x8b\x5e" + bytes([edge + 8]))
            code.raw(b"\x2b\x5e" + bytes([edge]))
            # Both 640->1024 and 480->768 are exactly 8/5. Native positive
            # coordinate conversion truncates each edge before averaging.
            code.raw(b"\x8b\x46" + bytes([edge]))
            code.raw(b"\xc1\xe0\x03\x99\xb9\x05\x00\x00\x00\xf7\xf9\x8b\xf8")
            code.raw(b"\x8b\x46" + bytes([edge + 8]))
            code.raw(b"\xc1\xe0\x03\x99\xf7\xf9\x03\xc7\xd1\xf8")
            code.raw(b"\x0f\xaf\x05" + struct.pack("<I", physical))
            code.raw(b"\x99\xb9" + struct.pack("<I", reference) + b"\xf7\xf9")
            code.raw(b"\x8b\xd3\xd1\xfa\x2b\xc2\x89\x45" + bytes([buffer]))
            code.raw(b"\x03\xc3\x89\x45" + bytes([buffer + 8]))
        code.raw(b"\x8b\x06\x8d\x55\xf0\x52\x8b\xce\xff\x90\xa8\x00\x00\x00")
        code.raw(b"\x61\xc9\xc3")
        return code.build()

    def emit_control_lifecycles(
        self,
        payload: SegmentPayloadBuilder,
        *,
        system_va: int,
        control_va: int,
    ) -> FixedScreenLifecycleExports:
        """Compile and place Title, ConfirmQuit, CloseUp, and Fingerprint roots."""
        title = ScreenLifecycleTargets(
            draw_va=control_va + self._off_title_root_draw_wrapper,
            show_va=control_va + self._off_title_show_wrapper,
            hide_va=control_va + self._off_title_hide_wrapper,
            destructor_va=control_va + self._off_title_destructor_wrapper,
        )
        confirm_quit = ScreenLifecycleTargets(
            draw_va=control_va + self._off_confirm_quit_root_draw_wrapper,
            show_va=control_va + self._off_confirm_quit_show_wrapper,
            hide_va=control_va + self._off_confirm_quit_hide_wrapper,
            destructor_va=control_va + self._off_confirm_quit_destructor_wrapper,
        )
        closeup = ScreenLifecycleTargets(
            draw_va=control_va + self._off_closeup_root_draw_wrapper,
            show_va=control_va + self._off_closeup_show_wrapper,
            hide_va=control_va + self._off_closeup_hide_wrapper,
            destructor_va=control_va + self._off_closeup_destructor_wrapper,
        )
        fingerprint = ScreenLifecycleTargets(
            draw_va=control_va + self._off_fingerprint_root_draw_wrapper,
            show_va=control_va + self._off_fingerprint_show_wrapper,
            hide_va=control_va + self._off_fingerprint_hide_wrapper,
            destructor_va=control_va + self._off_fingerprint_destructor_wrapper,
        )
        title_cache_wrapper_va = control_va + self._off_title_cache_blt_wrapper
        confirm_quit_post_flip_presenter_va = (
            control_va + self._off_confirm_quit_post_flip_presenter
        )
        confirm_quit_room_repair_helper_va = control_va + self._off_confirm_quit_room_repair_helper
        confirm_quit_show_prepare_helper_va = (
            control_va + self._off_confirm_quit_show_prepare_helper
        )
        physical_backdrop_wrapper_va = control_va + self._off_physical_backdrop_wrapper
        confirm_quit_cursor_resume_helper_va = (
            control_va + self._off_confirm_quit_cursor_resume_helper
        )
        confirm_quit_cursor_suspend_helper_va = (
            control_va + self._off_confirm_quit_cursor_suspend_helper
        )
        closeup_frame_presenter_va = control_va + self._off_closeup_frame_presenter

        title_root = self.build_root_draw_wrapper(
            wrapper_va=title.draw_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            transform_mode=self._mode_reference_anchor,
            input_enabled=True,
            target_va=self._native_title_draw_va,
            full_damage_region_va=control_va + self._off_control_full_damage_region,
            full_damage_rect_va=control_va + self._off_control_full_damage_rect,
        )
        title_show = self.build_state_wrapper(
            state_va=system_va + self._off_input_active,
            value=1,
            target_va=self._native_show_va,
            wrapper_va=title.show_va,
        )
        title_hide = self.build_state_wrapper(
            state_va=system_va + self._off_input_active,
            value=0,
            target_va=self._native_hide_va,
            wrapper_va=title.hide_va,
        )
        title_destructor = self.build_destructor_wrapper(
            wrapper_va=title.destructor_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            target_va=self._native_title_destructor_va,
        )
        confirm_root = self.build_root_draw_wrapper(
            wrapper_va=confirm_quit.draw_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            # This centered native-size tree must scale around its own root,
            # not the global widescreen canvas.
            transform_mode=self._mode_local_root_canvas,
            input_enabled=True,
            target_va=self._native_draw_va,
            full_damage_region_va=control_va + self._off_control_full_damage_region,
            full_damage_rect_va=control_va + self._off_control_full_damage_rect,
            # The native Draw constructs the complete dimmed backdrop and
            # panel on one DirectDraw page. Arm the peer copy only after that
            # complete traversal has returned successfully to this wrapper.
            post_draw_request_va=(control_va + SYSTEM_CONTROL_CONFIRM_QUIT_COPY_PENDING_OFFSET),
            post_draw_request_owner_va=(
                control_va + SYSTEM_CONTROL_CONFIRM_QUIT_SEEDED_ROOT_OFFSET
            ),
            pre_draw_va=confirm_quit_cursor_suspend_helper_va,
            # The paused cursor worker's last handle may address its private
            # save-under surface. The modal's own Draw argument is the exact
            # destination needed by its final-page cursor presenter.
            presentation_destination_handle_va=(control_va + self._off_control_cursor_state + 132),
        )
        confirm_reset_vas = (
            control_va + SYSTEM_CONTROL_CONFIRM_QUIT_COPY_PENDING_OFFSET,
            control_va + SYSTEM_CONTROL_CONFIRM_QUIT_COPY_RESULT_OFFSET,
            control_va + SYSTEM_CONTROL_CONFIRM_QUIT_SEEDED_ROOT_OFFSET,
        )
        confirm_show = self.build_state_wrapper(
            state_va=system_va + self._off_input_active,
            value=1,
            target_va=self._native_show_va,
            wrapper_va=confirm_quit.show_va,
            # Reset the peer-page lease at the start of every Show lifetime,
            # even if GK3 reuses the same object without an intervening Hide.
            extra_reset_vas=confirm_reset_vas,
            pre_call_va=confirm_quit_show_prepare_helper_va,
            # Pause the room cursor for every visible lifetime; its native
            # save-under worker resumes only after both modal pages are ready.
            extra_write_dwords=(
                (control_va + SYSTEM_CONTROL_CONFIRM_QUIT_CURSOR_SUSPENDED_OFFSET, 3),
            ),
        )
        confirm_hide = self.build_state_wrapper(
            state_va=system_va + self._off_input_active,
            value=0,
            target_va=self._native_hide_va,
            wrapper_va=confirm_quit.hide_va,
            extra_reset_vas=confirm_reset_vas,
            # GK3 also hides/destroys unshown cached dialogs during Restore.
            # Only a real suspension owns a saved cursor count to restore;
            # arming cleanup unconditionally disables subsequent tooltips.
            state_transitions=(
                (control_va + SYSTEM_CONTROL_CONFIRM_QUIT_CURSOR_SUSPENDED_OFFSET, (1, 4), 2),
            ),
        )
        confirm_destructor = self.build_destructor_wrapper(
            wrapper_va=confirm_quit.destructor_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            target_va=self._native_confirm_quit_destructor_va,
            extra_clear_vas=confirm_reset_vas,
            state_transitions=(
                (control_va + SYSTEM_CONTROL_CONFIRM_QUIT_CURSOR_SUSPENDED_OFFSET, (1, 4), 2),
            ),
        )
        confirm_quit_post_flip_presenter = self.build_confirm_quit_post_flip_presenter(
            wrapper_va=confirm_quit_post_flip_presenter_va,
            pending_va=control_va + SYSTEM_CONTROL_CONFIRM_QUIT_COPY_PENDING_OFFSET,
            result_va=control_va + SYSTEM_CONTROL_CONFIRM_QUIT_COPY_RESULT_OFFSET,
            copy_count_va=control_va + SYSTEM_CONTROL_CONFIRM_QUIT_COPY_COUNT_OFFSET,
            seeded_root_va=control_va + SYSTEM_CONTROL_CONFIRM_QUIT_SEEDED_ROOT_OFFSET,
            shared_root_ptr_va=system_va + self._off_root_ptr,
            cursor_suspended_va=(control_va + SYSTEM_CONTROL_CONFIRM_QUIT_CURSOR_SUSPENDED_OFFSET),
            cursor_resume_helper_va=confirm_quit_cursor_resume_helper_va,
        )
        confirm_quit_room_repair_helper = self.build_confirm_quit_room_repair_helper(
            wrapper_va=confirm_quit_room_repair_helper_va,
            room_root_va=control_va + SYSTEM_CONTROL_CURSOR_RESOURCE_ROOM_ROOT_OFFSET,
            cursor_rect_va=control_va + self._off_control_cursor_state + 24,
            destination_handle_va=control_va + self._off_control_cursor_state + 132,
            destination_wrapper_va=control_va + self._off_control_cursor_state + 136,
            collection_va=control_va + SYSTEM_CONTROL_CONFIRM_QUIT_ROOM_REPAIR_COLLECTION_OFFSET,
            repair_rect_va=control_va + SYSTEM_CONTROL_CONFIRM_QUIT_ROOM_REPAIR_RECT_OFFSET,
            primary_surface_ptr_va=self.profile.address("transition.primary_surface_ptr"),
            back_surface_ptr_va=self.profile.address("transition.back_surface_ptr"),
        )
        confirm_quit_cursor_resume_helper = self.build_confirm_quit_cursor_resume_helper(
            wrapper_va=confirm_quit_cursor_resume_helper_va,
            cursor_refcount_va=(control_va + SYSTEM_CONTROL_CONFIRM_QUIT_CURSOR_REFCOUNT_OFFSET),
            cursor_suspended_va=(control_va + SYSTEM_CONTROL_CONFIRM_QUIT_CURSOR_SUSPENDED_OFFSET),
        )
        confirm_quit_cursor_suspend_helper = self.build_confirm_quit_cursor_suspend_helper(
            wrapper_va=confirm_quit_cursor_suspend_helper_va,
            cursor_refcount_va=(control_va + SYSTEM_CONTROL_CONFIRM_QUIT_CURSOR_REFCOUNT_OFFSET),
            cursor_suspended_va=(control_va + SYSTEM_CONTROL_CONFIRM_QUIT_CURSOR_SUSPENDED_OFFSET),
        )
        confirm_quit_show_prepare_helper = self.build_confirm_quit_show_prepare_helper(
            wrapper_va=confirm_quit_show_prepare_helper_va,
            repair_helper_va=confirm_quit_room_repair_helper_va,
            cursor_refcount_va=(control_va + SYSTEM_CONTROL_CONFIRM_QUIT_CURSOR_REFCOUNT_OFFSET),
            cursor_suspended_va=(control_va + SYSTEM_CONTROL_CONFIRM_QUIT_CURSOR_SUSPENDED_OFFSET),
            cursor_resume_helper_va=confirm_quit_cursor_resume_helper_va,
        )
        physical_backdrop = self.build_physical_backdrop_wrapper(
            wrapper_va=physical_backdrop_wrapper_va,
            transform_mode_va=system_va + self._off_transform_mode,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
        )
        console_draw_scope_va = control_va + self._off_console_draw_scope
        console_draw_scope = self.build_console_draw_scope(
            wrapper_va=console_draw_scope_va,
            owner_va=self.symbols.va(CONSOLE_SEGMENT.logical_name, CONSOLE_OWNER_OFFSET),
            damage_helper_va=self.symbols.va(CONSOLE_SEGMENT.logical_name, CONSOLE_DAMAGE_OFFSET),
            state_vas=(
                system_va + self._off_render_depth,
                system_va + self._off_input_active,
                system_va + self._off_transform_mode,
                system_va + self._off_root_ptr,
            ),
        )
        title_cache = self.build_title_cache_blt_wrapper(
            wrapper_va=title_cache_wrapper_va,
            dest_rect_va=control_va + self._off_title_cache_dest_rect,
            source_rect_va=control_va + self._off_title_cache_source_rect,
            trace_va=control_va + self._off_title_cache_trace,
        )
        closeup_root = self.build_root_draw_wrapper(
            wrapper_va=closeup.draw_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            transform_mode=self._mode_bottom_anchored_reference_canvas,
            input_enabled=True,
            target_va=self._native_draw_va,
            full_damage_region_va=control_va + self._off_control_full_damage_region,
            full_damage_rect_va=control_va + self._off_control_full_damage_rect,
            fixed_canvas_owner_va=self.room_rendering_abi.fixed_canvas_owner_va,
            presentation_destination_handle_va=(
                control_va + SYSTEM_CONTROL_CLOSEUP_DEST_HANDLE_OFFSET
            ),
        )
        action_presented_root_va = system_va + SYSTEM_ACTION_PRESENTED_ROOT_OFFSET
        closeup_show = self.build_state_wrapper(
            state_va=system_va + self._off_input_active,
            value=1,
            target_va=self._native_show_va,
            wrapper_va=closeup.show_va,
            fixed_canvas_owner_va=self.room_rendering_abi.fixed_canvas_owner_va,
            extra_reset_vas=(action_presented_root_va,),
        )
        closeup_reset_vas = (
            action_presented_root_va,
            control_va + SYSTEM_CONTROL_CLOSEUP_DEST_HANDLE_OFFSET,
            control_va + SYSTEM_CONTROL_CLOSEUP_LAST_OWNER_OFFSET,
            control_va + SYSTEM_CONTROL_CLOSEUP_SEED_BUDGET_OFFSET,
        )
        closeup_hide = self.build_state_wrapper(
            state_va=system_va + self._off_input_active,
            value=0,
            target_va=self._native_hide_va,
            wrapper_va=closeup.hide_va,
            fixed_canvas_owner_va=self.room_rendering_abi.fixed_canvas_owner_va,
            extra_reset_vas=closeup_reset_vas,
        )
        closeup_destructor = self.build_destructor_wrapper(
            wrapper_va=closeup.destructor_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            target_va=self._native_closeup_destructor_va,
            extra_clear_vas=closeup_reset_vas,
            fixed_canvas_owner_va=self.room_rendering_abi.fixed_canvas_owner_va,
        )
        closeup_presenter = self.build_closeup_frame_presenter(
            wrapper_va=closeup_frame_presenter_va,
            target_va=closeup.draw_va,
            fixed_canvas_owner_va=self.room_rendering_abi.fixed_canvas_owner_va,
            shared_root_ptr_va=system_va + self._off_root_ptr,
            destination_handle_va=control_va + SYSTEM_CONTROL_CLOSEUP_DEST_HANDLE_OFFSET,
            full_damage_region_va=control_va + self._off_control_full_damage_region,
            last_owner_va=control_va + SYSTEM_CONTROL_CLOSEUP_LAST_OWNER_OFFSET,
            seed_budget_va=control_va + SYSTEM_CONTROL_CLOSEUP_SEED_BUDGET_OFFSET,
            present_count_va=control_va + SYSTEM_CONTROL_CLOSEUP_PRESENT_COUNT_OFFSET,
        )
        fingerprint_layout_targets = self._fingerprint_layout_targets()
        fingerprint_root = self.build_root_draw_wrapper(
            wrapper_va=fingerprint.draw_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            transform_mode=self._mode_popup,
            input_enabled=True,
            target_va=self._native_draw_va,
            pre_draw_va=fingerprint_layout_targets[0],
            post_draw_va=fingerprint_layout_targets[1],
            damage_selector_va=self.symbols.va(
                FINGERPRINT_SEGMENT.logical_name, FINGERPRINT_DAMAGE_SELECTOR_OFFSET
            ),
            full_damage_region_va=control_va + self._off_control_full_damage_region,
            full_damage_rect_va=control_va + self._off_control_full_damage_rect,
        )
        fingerprint_show = self.build_state_wrapper(
            state_va=system_va + self._off_input_active,
            value=1,
            target_va=self._native_show_va,
            wrapper_va=fingerprint.show_va,
        )
        fingerprint_hide = self.build_state_wrapper(
            state_va=system_va + self._off_input_active,
            value=0,
            target_va=self._native_hide_va,
            wrapper_va=fingerprint.hide_va,
        )
        fingerprint_destructor = self.build_destructor_wrapper(
            wrapper_va=fingerprint.destructor_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            target_va=self._native_fingerprint_destructor_va,
        )
        for label, offset, code, limit in (
            (
                "ConfirmQuit root",
                self._off_confirm_quit_root_draw_wrapper,
                confirm_root,
                self._off_confirm_quit_show_wrapper,
            ),
            (
                "ConfirmQuit show",
                self._off_confirm_quit_show_wrapper,
                confirm_show,
                self._off_confirm_quit_hide_wrapper,
            ),
            (
                "ConfirmQuit hide",
                self._off_confirm_quit_hide_wrapper,
                confirm_hide,
                self._off_confirm_quit_destructor_wrapper,
            ),
            (
                "ConfirmQuit destructor",
                self._off_confirm_quit_destructor_wrapper,
                confirm_destructor,
                self._off_confirm_quit_destructor_wrapper_limit,
            ),
            (
                "CloseUp frame presenter",
                self._off_closeup_frame_presenter,
                closeup_presenter,
                self._off_closeup_frame_presenter_limit,
            ),
            (
                "ConfirmQuit post-Flip peer-page copy",
                self._off_confirm_quit_post_flip_presenter,
                confirm_quit_post_flip_presenter,
                self._off_confirm_quit_post_flip_presenter_limit,
            ),
            (
                "ConfirmQuit underlying-room cursor repair",
                self._off_confirm_quit_room_repair_helper,
                confirm_quit_room_repair_helper,
                self._off_confirm_quit_room_repair_helper_limit,
            ),
            (
                "SystemScreen physical backdrop scope",
                self._off_physical_backdrop_wrapper,
                physical_backdrop,
                self._off_physical_backdrop_wrapper_limit,
            ),
            (
                "Console independent drawing scope",
                self._off_console_draw_scope,
                console_draw_scope,
                self._off_console_draw_scope_limit,
            ),
            (
                "ConfirmQuit reused-show preparation",
                self._off_confirm_quit_show_prepare_helper,
                confirm_quit_show_prepare_helper,
                self._off_confirm_quit_show_prepare_helper_limit,
            ),
            (
                "ConfirmQuit cursor worker resume",
                self._off_confirm_quit_cursor_resume_helper,
                confirm_quit_cursor_resume_helper,
                self._off_confirm_quit_cursor_resume_helper_limit,
            ),
            (
                "ConfirmQuit cursor worker suspend",
                self._off_confirm_quit_cursor_suspend_helper,
                confirm_quit_cursor_suspend_helper,
                self._off_confirm_quit_cursor_suspend_helper_limit,
            ),
            (
                "Title root",
                self._off_title_root_draw_wrapper,
                title_root,
                self._off_title_root_draw_limit,
            ),
            ("Title show", self._off_title_show_wrapper, title_show, self._off_title_hide_wrapper),
            (
                "Title hide",
                self._off_title_hide_wrapper,
                title_hide,
                self._off_title_destructor_wrapper,
            ),
            ("Title destructor", self._off_title_destructor_wrapper, title_destructor, 0x280),
            (
                "CloseUp root",
                self._off_closeup_root_draw_wrapper,
                closeup_root,
                self._off_closeup_root_draw_limit,
            ),
            (
                "CloseUp show",
                self._off_closeup_show_wrapper,
                closeup_show,
                self._off_closeup_hide_wrapper,
            ),
            (
                "CloseUp hide",
                self._off_closeup_hide_wrapper,
                closeup_hide,
                self._off_closeup_destructor_wrapper,
            ),
            (
                "CloseUp destructor",
                self._off_closeup_destructor_wrapper,
                closeup_destructor,
                self._off_closeup_destructor_limit,
            ),
            (
                "Fingerprint root",
                self._off_fingerprint_root_draw_wrapper,
                fingerprint_root,
                self._off_fingerprint_show_wrapper,
            ),
            (
                "Fingerprint show",
                self._off_fingerprint_show_wrapper,
                fingerprint_show,
                self._off_fingerprint_hide_wrapper,
            ),
            (
                "Fingerprint hide",
                self._off_fingerprint_hide_wrapper,
                fingerprint_hide,
                self._off_fingerprint_destructor_wrapper,
            ),
            (
                "Fingerprint destructor",
                self._off_fingerprint_destructor_wrapper,
                fingerprint_destructor,
                self._off_fingerprint_destructor_limit,
            ),
        ):
            payload.place(label=label, offset=offset, payload=code, limit=limit)
        payload.place(
            label="title cache Blt wrapper",
            offset=self._off_title_cache_blt_wrapper,
            payload=title_cache,
            limit=self._off_title_cache_blt_limit,
        )
        return FixedScreenLifecycleExports(
            title=title,
            confirm_quit=confirm_quit,
            closeup=closeup,
            fingerprint=fingerprint,
            title_cache_wrapper_va=title_cache_wrapper_va,
            physical_backdrop_wrapper_va=physical_backdrop_wrapper_va,
            console_draw_scope_va=console_draw_scope_va,
            confirm_quit_post_flip_presenter_va=confirm_quit_post_flip_presenter_va,
            closeup_frame_presenter_va=closeup_frame_presenter_va,
        )

    def plan_hooks(
        self,
        plan: ExecutableMutationPlan,
        *,
        death: ScreenLifecycleTargets,
        death_button_layout_va: int,
        finished_draw_va: int,
        finished_destructor_va: int,
        pause_draw_va: int,
        title: ScreenLifecycleTargets,
        confirm_quit: ScreenLifecycleTargets,
        closeup: ScreenLifecycleTargets,
        fingerprint: ScreenLifecycleTargets,
        title_cache_wrapper_va: int,
        physical_backdrop_wrapper_va: int,
        console_draw_scope_va: int,
        confirm_quit_post_flip_presenter_va: int,
    ) -> None:
        """Own bounded-screen lifecycle and title-cache redirects."""
        plan.pointer(
            label="Pause centered draw scope",
            slot_va=self.profile.address("pause.vtable") + 0xA0,
            expected=self._native_draw_va,
            target_va=pause_draw_va,
        )
        for name in ("retry", "restore", "quit"):
            site = self.profile.site(f"death.{name}_layout")
            plan.branch(
                label=f"Death {name} reference-rounded anchor",
                opcode=BranchOpcode.CALL,
                site_va=site.va,
                expected=site.original,
                target_va=death_button_layout_va,
            )
        families = (
            (
                "Death",
                (
                    self._death_draw_slot_va,
                    self._death_show_slot_va,
                    self._death_hide_slot_va,
                    self._death_destructor_slot_va,
                ),
                ScreenLifecycleTargets(
                    draw_va=self._native_draw_va,
                    show_va=self._native_show_va,
                    hide_va=self._native_hide_va,
                    destructor_va=self._native_destructor_va,
                ),
                death,
            ),
            (
                "Title",
                (
                    self._title_draw_slot_va,
                    self._title_show_slot_va,
                    self._title_hide_slot_va,
                    self._title_destructor_slot_va,
                ),
                ScreenLifecycleTargets(
                    draw_va=self._native_title_draw_va,
                    show_va=self._native_show_va,
                    hide_va=self._native_hide_va,
                    destructor_va=self._native_title_destructor_va,
                ),
                title,
            ),
            (
                "ConfirmQuit",
                (
                    self._confirm_quit_draw_slot_va,
                    self._confirm_quit_show_slot_va,
                    self._confirm_quit_hide_slot_va,
                    self._confirm_quit_destructor_slot_va,
                ),
                ScreenLifecycleTargets(
                    draw_va=self._native_draw_va,
                    show_va=self._native_show_va,
                    hide_va=self._native_hide_va,
                    destructor_va=self._native_confirm_quit_destructor_va,
                ),
                confirm_quit,
            ),
            (
                "CloseUp",
                (
                    self._closeup_draw_slot_va,
                    self._closeup_show_slot_va,
                    self._closeup_hide_slot_va,
                    self._closeup_destructor_slot_va,
                ),
                ScreenLifecycleTargets(
                    draw_va=self._native_draw_va,
                    show_va=self._native_show_va,
                    hide_va=self._native_hide_va,
                    destructor_va=self._native_closeup_destructor_va,
                ),
                closeup,
            ),
            (
                "Fingerprint",
                (
                    self._fingerprint_draw_slot_va,
                    self._fingerprint_show_slot_va,
                    self._fingerprint_hide_slot_va,
                    self._fingerprint_destructor_slot_va,
                ),
                ScreenLifecycleTargets(
                    draw_va=self._native_draw_va,
                    show_va=self._native_show_va,
                    hide_va=self._native_hide_va,
                    destructor_va=self._native_fingerprint_destructor_va,
                ),
                fingerprint,
            ),
        )
        for label, slots, expected, targets in families:
            for edge, slot_va, expected_va, target_va in zip(
                ("draw", "show", "hide", "destructor"),
                slots,
                (
                    expected.draw_va,
                    expected.show_va,
                    expected.hide_va,
                    expected.destructor_va,
                ),
                (
                    targets.draw_va,
                    targets.show_va,
                    targets.hide_va,
                    targets.destructor_va,
                ),
                strict=True,
            ):
                plan.pointer(
                    label=f"{label} {edge}",
                    slot_va=slot_va,
                    expected=expected_va,
                    target_va=target_va,
                )
        plan.pointer(
            label="Finished draw",
            slot_va=self._finished_draw_slot_va,
            expected=self._native_draw_va,
            target_va=finished_draw_va,
        )
        plan.pointer(
            label="Finished destructor",
            slot_va=self._finished_destructor_slot_va,
            expected=self._native_finished_destructor_va,
            target_va=finished_destructor_va,
        )
        # TransitionFrameABI deliberately exposes one optional callback after
        # a successful Flip. ConfirmQuit is its sole owner: the page which was
        # just presented contains the complete native dim/backdrop composition,
        # while the returned back page is the only safe copy destination.
        plan.pointer(
            label="ConfirmQuit post-Flip peer-page copy",
            slot_va=self.transition_abi.post_flip_presenter_slot_va,
            expected=0,
            target_va=confirm_quit_post_flip_presenter_va,
        )
        backdrop_site = self.profile.site("ui.backdrop_draw_entry")
        plan.pointer(
            label="Console independent drawing scope",
            slot_va=self._slot("console", 0xA0),
            expected=self._native_draw_va,
            target_va=console_draw_scope_va,
        )
        plan.branch(
            label="SystemScreen physical backdrop scope",
            opcode=BranchOpcode.JUMP,
            site_va=backdrop_site.va,
            expected=backdrop_site.original,
            target_va=physical_backdrop_wrapper_va,
            size=len(backdrop_site.original),
        )
        plan.branch(
            label="title cache blit",
            opcode=BranchOpcode.JUMP,
            site_va=self._title_cache_blt_call_va,
            expected=self._title_cache_blt_original,
            target_va=title_cache_wrapper_va,
            size=len(self._title_cache_blt_original),
        )

    def build_console_draw_scope(
        self,
        *,
        wrapper_va: int,
        owner_va: int,
        damage_helper_va: int,
        state_vas: tuple[int, int, int, int],
    ) -> bytes:
        """Isolate the console overlay from the retained underlying screen.

        MiniConsole remains visible while a command opens a CloseUp or another
        modal root. Its native coordinates must not inherit that root's affine.
        Save scope on the stack so nested calls restore their exact parent;
        Console's feature owner handles its independent fixed-pixel metrics.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\xff\x35" + struct.pack("<I", owner_va))
        code.raw(b"\x89\x0d" + struct.pack("<I", owner_va))
        for address in state_vas:
            code.raw(b"\xff\x35" + struct.pack("<I", address))
            code.raw(b"\xc7\x05" + struct.pack("<I", address) + bytes(4))
        # Five saved DWORDs precede the original return address and arguments.
        code.raw(b"\x8b\x44\x24\x1c")
        code.call_absolute(damage_helper_va)
        code.raw(b"\x50\xff\x74\x24\x1c")
        code.call_absolute(self._native_draw_va)
        for address in reversed(state_vas):
            code.raw(b"\x8f\x05" + struct.pack("<I", address))
        code.raw(b"\x8f\x05" + struct.pack("<I", owner_va))
        code.raw(b"\xc2\x08\x00")
        return code.build()

    def build_physical_backdrop_wrapper(
        self,
        *,
        wrapper_va: int,
        transform_mode_va: int,
        render_depth_va: int,
        input_active_va: int,
    ) -> bytes:
        """Keep SystemScreen's cached dimmed framebuffer slices physical.

        The native screen captures four regions around its panel and later
        restores them through the shared blitter. These are physical page
        copies, not authored dialog artwork. Suspending only the synchronous
        render scope prevents an inherited modal/inventory affine from
        stretching the side slices offscreen and leaving a bright band.
        Native capture, dimming, and cache lifetime remain untouched.

        Binoculars own the visible world/mask composition, including the last
        valid panorama when a zoom scene cannot load. The underlying RoomLayer
        still has cached borders around its old 1024x768 panel: replaying those
        clips the retained panorama until another successful 3D draw replaces
        them. Suppress only that room backdrop while binoculars are current;
        other layers and the binocular artwork retain their native paths.
        """
        site = self.profile.site("ui.backdrop_draw_entry")
        trampoline_va = wrapper_va + 0xC0
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x9c\x81\x39")
        code.raw(struct.pack("<I", self.profile.address("transition.room_layer_vtable")))
        code.jump_short_if(Condition.NOT_EQUAL, "native_flags")
        code.raw(b"\x60")
        code.call_absolute(self.profile.address("ui.current_layer"))
        code.raw(b"\x85\xc0")
        code.jump_short_if(Condition.EQUAL, "native_registers")
        code.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("binocular.vtable")))
        code.jump_short_if(Condition.NOT_EQUAL, "native_registers")
        code.raw(b"\x61\x9d\xc2\x08\x00")
        code.label("native_registers")
        code.raw(b"\x61")
        code.label("native_flags")
        code.raw(b"\x9d")
        code.raw(b"\x55\x8b\xec\x56\x8b\xf1")
        state_vas = (transform_mode_va, render_depth_va, input_active_va)
        for address in state_vas:
            code.raw(b"\xff\x35" + struct.pack("<I", address))
            code.raw(b"\xc7\x05" + struct.pack("<I", address) + bytes(4))
        # Native DrawBackdrop(destination, damage) owns RET 8.
        code.raw(b"\xff\x75\x0c\xff\x75\x08\x8b\xce")
        code.call_absolute(trampoline_va)
        for address in reversed(state_vas):
            code.raw(b"\x8f\x05" + struct.pack("<I", address))
        code.raw(b"\x5e\xc9\xc2\x08\x00")
        prefix = code.build()
        if len(prefix) > trampoline_va - wrapper_va:
            message = "physical backdrop scope overlaps its native trampoline"
            raise ValueError(message)
        trampoline = X86Emitter(base_va=trampoline_va)
        trampoline.raw(site.original)
        trampoline.jump_absolute(site.va + len(site.original))
        return prefix.ljust(trampoline_va - wrapper_va, b"\x90") + trampoline.build()

    def build_confirm_quit_cursor_suspend_helper(
        self,
        *,
        wrapper_va: int,
        cursor_refcount_va: int,
        cursor_suspended_va: int,
    ) -> bytes:
        """Suspend CursorPlatform at ConfirmQuit's first authoritative Draw."""
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x83\x3d" + struct.pack("<I", cursor_suspended_va) + b"\x03")
        code.jump_if(Condition.NOT_EQUAL, "done")
        # The public setter notifies GK3's cursor client and requests a room
        # redraw, which would erase ConfirmQuit's already-captured dim layer.
        # Mutate the same field under its critical section to pause only the worker.
        code.raw(b"\xbe" + struct.pack("<I", self.profile.address("cursor.platform_instance")))
        code.raw(b"\x83\x7e\x78\x00")
        code.jump_if(Condition.EQUAL, "locked")
        code.raw(b"\x8d\x46\x60\x50\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.EnterCriticalSection")))
        code.label("locked")
        code.raw(b"\x8b\x46\x30")
        code.raw(b"\xa3" + struct.pack("<I", cursor_refcount_va))
        code.raw(b"\xc7\x46\x30\x00\x00\x00\x00")
        code.raw(b"\x83\x7e\x78\x00")
        code.jump_if(Condition.EQUAL, "unlocked")
        code.raw(b"\x8d\x46\x60\x50\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.LeaveCriticalSection")))
        code.label("unlocked")
        code.raw(b"\x31\xc0")
        for offset in range(0x0C, 0x1C, 4):
            code.raw(
                b"\xa3"
                + struct.pack("<I", self.profile.address("cursor.platform_instance") + offset)
            )
        code.raw(b"\xc7\x05" + struct.pack("<I", cursor_suspended_va) + b"\x01\x00\x00\x00")
        code.label("done")
        code.raw(b"\xc3")
        return code.build()

    def build_confirm_quit_show_prepare_helper(
        self,
        *,
        wrapper_va: int,
        repair_helper_va: int,
        cursor_refcount_va: int,
        cursor_suspended_va: int,
        cursor_resume_helper_va: int,
    ) -> bytes:
        """Prepare every retained ConfirmQuit Show like its first construction."""
        code = X86Emitter(base_va=wrapper_va)
        # Hide the platform cursor before the native screen captures its four
        # dimmed background slices. The surrounding Show wrapper preserves
        # the concrete ECX receiver and arms the first-Draw cursor pause.
        code.call_absolute(cursor_resume_helper_va)
        code.raw(b"\x51\x6a\x00")
        code.raw(b"\xb9" + struct.pack("<I", self.profile.address("cursor.platform_instance")))
        code.call_absolute(self.profile.address("cursor.platform_set_count"))
        code.raw(b"\x59")
        code.call_absolute(repair_helper_va)
        code.raw(b"\xc7\x05" + struct.pack("<I", cursor_refcount_va) + b"\x00\x00\x00\x00")
        code.raw(b"\xc7\x05" + struct.pack("<I", cursor_suspended_va) + b"\x03\x00\x00\x00")
        code.raw(b"\xc3")
        return code.build()

    def build_confirm_quit_cursor_resume_helper(
        self,
        *,
        wrapper_va: int,
        cursor_refcount_va: int,
        cursor_suspended_va: int,
    ) -> bytes:
        """Resume the worker after modal seeding, or restore it after dismissal."""
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x83\x3d" + struct.pack("<I", cursor_suspended_va) + b"\x01")
        code.jump_if(Condition.EQUAL, "modal_ready")
        code.raw(b"\x83\x3d" + struct.pack("<I", cursor_suspended_va) + b"\x02")
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\x9c\x60")
        # Withdraw the token before entering native code so a re-entrant Flip
        # cannot restore the same reference count twice.
        code.raw(b"\xc7\x05" + struct.pack("<I", cursor_suspended_va) + b"\x00\x00\x00\x00")
        code.raw(b"\x31\xc0")
        for offset in range(0x0C, 0x1C, 4):
            code.raw(
                b"\xa3"
                + struct.pack("<I", self.profile.address("cursor.platform_instance") + offset)
            )
        code.raw(b"\xff\x35" + struct.pack("<I", cursor_refcount_va))
        code.raw(b"\xb9" + struct.pack("<I", self.profile.address("cursor.platform_instance")))
        code.call_absolute(self.profile.address("cursor.platform_set_count"))
        code.raw(b"\x61\x9d")
        code.jump("done")
        code.label("modal_ready")
        # The public setter notifies the underlying room and would overwrite
        # the newly dimmed pages. Resume only the worker's saved count under
        # its own lock, matching the suspension edge. Its next transaction
        # captures the completed modal background and erases old cursor pixels.
        code.raw(b"\x9c\x60")
        code.raw(b"\xbe" + struct.pack("<I", self.profile.address("cursor.platform_instance")))
        code.raw(b"\x83\x7e\x78\x00")
        code.jump_if(Condition.EQUAL, "modal_locked")
        code.raw(b"\x8d\x46\x60\x50\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.EnterCriticalSection")))
        code.label("modal_locked")
        code.raw(b"\xa1" + struct.pack("<I", cursor_refcount_va) + b"\x89\x46\x30")
        # A resumed modal still owns its saved count: native Hide restores the
        # temporary zero captured during Show preparation. Keep a distinct live
        # token so dismissal repairs that count, while an unshown cached dialog
        # (token zero) cannot perform cleanup with an uninitialized saved value.
        code.raw(b"\xc7\x05" + struct.pack("<I", cursor_suspended_va) + b"\x04\x00\x00\x00")
        code.raw(b"\x83\x7e\x78\x00")
        code.jump_if(Condition.EQUAL, "modal_unlocked")
        code.raw(b"\x8d\x46\x60\x50\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.LeaveCriticalSection")))
        code.label("modal_unlocked")
        code.raw(b"\x61\x9d")
        code.label("done")
        code.raw(b"\xc3")
        return code.build()

    def build_root_draw_wrapper(
        self,
        *,
        wrapper_va: int,
        render_depth_va: int,
        input_active_va: int,
        clear_pending_va: int,
        root_ptr_va: int,
        transform_mode_va: int,
        transform_mode: int,
        input_enabled: bool,
        target_va: int,
        full_damage_region_va: int | None = None,
        full_damage_rect_va: int | None = None,
        damage_selector_va: int | None = None,
        full_damage_uses_root_rect: bool = False,
        full_damage_budget_va: int | None = None,
        full_damage_on_every_call: bool = False,
        post_clear_surface_va: int | None = None,
        post_clear_bltfx_va: int | None = None,
        post_clear_rect_vas: tuple[int, int] | None = None,
        pre_draw_va: int | None = None,
        post_draw_va: int | None = None,
        post_draw_pass_args: bool = False,
        post_draw_request_va: int | None = None,
        post_draw_request_owner_va: int | None = None,
        previous_mode_va: int | None = None,
        fixed_canvas_owner_va: int | None = None,
        presentation_owner_reset_vas: tuple[int, ...] = (),
        presentation_destination_handle_va: int | None = None,
    ) -> bytes:
        """Bracket one concrete root traversal with its transform and lifetime state."""
        # FUN_004DCA32 is a thiscall with two stack arguments and RET 8.
        if (full_damage_region_va is None) != (full_damage_rect_va is None):
            msg = "full damage requires both the region and RECT addresses"
            raise ValueError(msg)
        if damage_selector_va is not None and full_damage_region_va is None:
            msg = "a damage selector requires the complete damage region"
            raise ValueError(msg)
        if (full_damage_budget_va is not None or full_damage_uses_root_rect) and (
            full_damage_region_va is None
        ):
            msg = "bounded full-damage policy requires a complete damage region"
            raise ValueError(msg)
        if full_damage_on_every_call and full_damage_budget_va is None:
            msg = "always-complete seeded damage requires its consumption budget"
            raise ValueError(msg)
        if (post_draw_request_va is None) != (post_draw_request_owner_va is None):
            msg = "a post-draw request requires both pending and seeded-owner state"
            raise ValueError(msg)
        code = X86Emitter(base_va=wrapper_va)
        if previous_mode_va is not None:
            # Some nested popups inherit a logical parent coordinate space.
            # Preserve that identity before this root publishes its own mode.
            code += b"\xa1" + struct.pack("<I", transform_mode_va)
            code += b"\xa3" + struct.pack("<I", previous_mode_va)
        if fixed_canvas_owner_va is not None:
            # LoadGame/SaveGame can enter through their shared base traversal
            # without dispatching the concrete Show virtual. Draw is the first
            # universal, object-specific ownership edge, so publish the exact
            # root here before any of its retained canvas is composed.
            if presentation_owner_reset_vas:
                code += b"\x3b\x0d" + struct.pack("<I", fixed_canvas_owner_va)
                code.jump_if(Condition.EQUAL, "presentation_owner_ready")
                code += b"\x31\xc0"
                for address in presentation_owner_reset_vas:
                    code += b"\xa3" + struct.pack("<I", address)
                code.label("presentation_owner_ready")
            code += b"\x89\x0d" + struct.pack("<I", fixed_canvas_owner_va)
        if presentation_destination_handle_va is not None:
            # Draw arg1 is GK3's encoded destination bitmap handle. Retain it
            # for the final-page replay; the helper resolves no COM pointer and
            # therefore cannot retain one across a Flip.
            code += b"\x8b\x44\x24\x04"
            code += b"\xa3" + struct.pack("<I", presentation_destination_handle_va)
        if full_damage_rect_va is not None:
            if full_damage_uses_root_rect:
                # A modal room toolbar owns only its live root union. Whenever
                # that union changes (opening, expanding, or collapsing a
                # panel), seed both rotating pages completely. Stable geometry
                # then goes back to GK3's ordinary native collection.
                if full_damage_budget_va is not None:
                    for offset in range(0, 16, 4):
                        code += b"\x8b\x41" + bytes([0x1C + offset])
                        code += b"\x3b\x05" + struct.pack("<I", full_damage_rect_va + offset)
                        code.jump_short_if(Condition.NOT_EQUAL, "root_damage_changed")
                    code.jump_short("root_damage_ready")
                    code.label("root_damage_changed")
                    code += (
                        b"\xc7\x05" + struct.pack("<I", full_damage_budget_va) + b"\x02\x00\x00\x00"
                    )
                    code.label("root_damage_ready")
                for offset in range(0, 16, 4):
                    code += b"\x8b\x41" + bytes([0x1C + offset])
                    code += b"\xa3" + struct.pack("<I", full_damage_rect_va + offset)
            else:
                # Complete the static RECT from live dimensions. A retained
                # full-screen root needs this region whenever its transformed
                # children cannot consume native authored damage coordinates.
                # Its left/top words are initialized once and never lent to a
                # local-root producer; modal bounds use a separate collection.
                code += b"\xa1" + struct.pack("<I", self._physical_width_va)
                code += b"\xa3" + struct.pack("<I", full_damage_rect_va + 8)
                code += b"\xa1" + struct.pack("<I", self._physical_width_va + 4)
                code += b"\xa3" + struct.pack("<I", full_damage_rect_va + 12)
        code += b"\x89\x0d" + struct.pack("<I", root_ptr_va)
        # These values are deliberately small non-negative enum/Boolean
        # constants. PUSH imm8 / POP EAX / MOV moffs32,EAX is two bytes shorter
        # than MOV dword ptr [abs],imm32 while preserving the same DWORD store.
        # Keeping the common prologue dense leaves class wrappers inside their
        # fixed binary ABI slots without another trampoline or relocated state.
        for address, value in (
            (input_active_va, int(input_enabled)),
            (clear_pending_va, 1),
            (transform_mode_va, transform_mode),
        ):
            code += b"\x6a" + bytes([value]) + b"\x58\xa3" + struct.pack("<I", address)
        code += b"\xff\x05" + struct.pack("<I", render_depth_va)
        if pre_draw_va is not None:
            # The fingerprint helper temporarily changes only draw rectangles;
            # PUSHAD keeps this wrapper's thiscall arguments and root intact.
            code += b"\x60"
            code += b"\x8b\x0d" + struct.pack("<I", root_ptr_va)
            code.call_absolute(pre_draw_va)
            code += b"\x61"
        if full_damage_region_va is None:
            code += b"\x51\xff\x74\x24\x0c\xff\x74\x24\x0c"
        else:
            # Title's HD affine moves every child away from the logical damage
            # coordinates supplied by the cursor compositor.  Replace that
            # partial collection with one full-screen RECT so the stock title
            # traversal erases every prior cursor image before presentation.
            code += b"\x8b\x44\x24\x08"
            if full_damage_budget_va is not None and not full_damage_on_every_call:
                code += b"\x83\x3d" + struct.pack("<I", full_damage_budget_va) + b"\x00"
                code.jump_short_if(Condition.EQUAL, "damage_ready")
                code += b"\xb8" + struct.pack("<I", full_damage_region_va)
            elif full_damage_on_every_call:
                # A caller may explicitly require every accepted traversal to
                # be complete. This is intentionally opt-in: direct rendering
                # normally seeds both pages after a geometry change and then
                # preserves GK3's incremental damage for steady-state frames.
                code += b"\xb8" + struct.pack("<I", full_damage_region_va)
            elif damage_selector_va is None:
                # A transformed modern root needs a complete traversal because
                # GK3's authored damage rectangles no longer cover its final
                # pixels. At the exact reference canvas, preserve stock damage.
                code += b"\x81\x3d" + struct.pack("<I", self._physical_width_va)
                code += struct.pack("<I", AUTHORED_FRAME_WIDTH)
                code.jump_short_if(Condition.ABOVE, "use_full")
                code += b"\x81\x3d" + struct.pack("<I", self._physical_width_va + 4)
                code += struct.pack("<I", AUTHORED_FRAME_HEIGHT)
                code.jump_short_if(Condition.BELOW_OR_EQUAL, "damage_ready")
                code.label("use_full")
                code += b"\xb8" + struct.pack("<I", full_damage_region_va)
            else:
                # EAX is the caller's native damage collection and ECX remains
                # the concrete root. The selector returns either that pointer
                # or the static complete region initialized above.
                code.call_absolute(damage_selector_va)
            code.label("damage_ready")
            code += b"\x51\x50\xff\x74\x24\x0c"
        code.call_absolute(target_va)
        if post_draw_va is not None:
            # Preserve the native Draw return value while restoring the raw
            # hit-test rectangles before input dispatch resumes.
            code += b"\x50\x60"
            if post_draw_pass_args:
                # After PUSHAD, the wrapper's original Draw arguments are at
                # +0x2c/+0x30. Push arg2 first; the stack movement leaves arg1
                # at +0x30 for the second push. The helper owns RET 8.
                code += b"\xff\x74\x24\x30\xff\x74\x24\x30"
            code += b"\x8b\x0d" + struct.pack("<I", root_ptr_va)
            code.call_absolute(post_draw_va)
            code += b"\x61\x58"
        if post_draw_request_va is not None:
            # The request is semantic completion state, not Show/lifetime
            # state. Arm it only until this exact root has been copied once;
            # steady-state native Draw calls must not create a permanent
            # full-frame front-to-back transaction.
            if post_draw_request_owner_va is None:
                msg = "a post-draw request requires seeded-owner state"
                raise ValueError(msg)
            code += b"\xa1" + struct.pack("<I", root_ptr_va)
            code += b"\x3b\x05" + struct.pack("<I", post_draw_request_owner_va)
            code.jump_short_if(Condition.EQUAL, "post_draw_request_ready")
            code += b"\xc7\x05" + struct.pack("<I", post_draw_request_va) + b"\x01\x00\x00\x00"
            code.label("post_draw_request_ready")
        if post_clear_surface_va is not None:
            if post_clear_bltfx_va is None or post_clear_rect_vas is None:
                msg = "post-draw pillar clearing requires its Blt state"
                raise ValueError(msg)
            # Binocs contains a live 3D pass which can repaint the exposed
            # widescreen pillars after the first scoped 2D transfer cleared
            # them.  Re-clear only those two bands after the complete Binocs
            # root traversal; ordinary room draws never enter this wrapper.
            code += b"\x60"
            code += b"\x8b\x35" + struct.pack("<I", post_clear_surface_va)
            code += b"\x85\xf6"
            code.jump_short_if(Condition.EQUAL, "cleared")
            code += b"\x8b\x1e"
            # A 4:3 target produces two zero-width side rectangles. Windows
            # 25H2's DWM8And16BitMitigation faults inside apphelp.dll when its
            # DirectDraw Blt callout receives that degenerate geometry. Both
            # bands share the same fitted width, so proving the left rectangle
            # non-empty also proves the right; skip the transaction entirely
            # when there are no pillars to clear.
            code += b"\xa1" + struct.pack("<I", post_clear_rect_vas[0])
            code += b"\x3b\x05" + struct.pack("<I", post_clear_rect_vas[0] + 8)
            code.jump_short_if(Condition.ABOVE_OR_EQUAL, "cleared")
            # Hoist the shared BltFx pointer and null-source arguments outside
            # both submissions. This keeps the geometry guard and complete
            # policy inside Binocs' original fixed binary ABI slot.
            code += b"\xbf" + struct.pack("<I", post_clear_bltfx_va)
            code += b"\x31\xc0"
            for rect_va in post_clear_rect_vas:
                code += b"\x57"
                code += b"\x68" + struct.pack("<I", self._ddblt_colorfill_wait)
                code += b"\x50\x50"
                code += b"\x68" + struct.pack("<I", rect_va)
                code += b"\x56\xff\x53\x14"
            code.label("cleared")
            code += b"\x61"
        if full_damage_budget_va is not None:
            code += b"\x83\x3d" + struct.pack("<I", full_damage_budget_va) + b"\x00"
            code.jump_short_if(Condition.EQUAL, "seed_consumed")
            code += b"\xff\x0d" + struct.pack("<I", full_damage_budget_va)
            code.label("seed_consumed")
        code += b"\x59\xff\x0d" + struct.pack("<I", render_depth_va)
        code += b"\xc2\x08\x00"
        return code.build()

    def build_title_cache_blt_wrapper(
        self,
        *,
        wrapper_va: int,
        dest_rect_va: int,
        source_rect_va: int,
        trace_va: int,
    ) -> bytes:
        """Fit title artwork without distorting it; preserve other cache resizes.

        Entry is a JMP that replaces the resource loader's DirectDraw ``Blt``
        and its following two ``push 0`` instructions. All six COM arguments
        are already on the stack; EDI is the display-sized destination wrapper,
        ``[ESI+0x30]`` is the decoded source wrapper, and EDX is the destination
        surface vtable.

        The stock null-rectangle operation remains byte-for-byte equivalent
        when both extents match. For a denser source, complete private RECTs
        force native DirectDraw to scale into the cache instead of copying only
        the surfaces' intersection. Only TitleLayer's identified resize caller
        gets a centered aspect-preserving rectangle and black margins. Other
        resource users retain their original full-destination stretch.
        """
        code = X86Emitter(base_va=wrapper_va)
        code += b"\x8b\x46\x30"  # decoded source GK3 surface wrapper
        # Retain the exact live classification inputs and call result. This is
        # bounded production telemetry like the neighboring cursor records and
        # turns native-driver differences into inspectable evidence.
        code += b"\xff\x05" + struct.pack("<I", trace_va)
        code += b"\x8b\x4f\x38\x89\x0d" + struct.pack("<I", trace_va + 4)
        code += b"\x8b\x4f\x3c\x89\x0d" + struct.pack("<I", trace_va + 8)
        code += b"\x8b\x48\x38\x89\x0d" + struct.pack("<I", trace_va + 12)
        code += b"\x8b\x48\x3c\x89\x0d" + struct.pack("<I", trace_va + 16)
        code += b"\x8b\x48\x38\x3b\x4f\x38"
        code.jump_short_if(Condition.NOT_EQUAL, "stretch")
        code += b"\x8b\x48\x3c\x3b\x4f\x3c"
        code.jump_if(Condition.EQUAL, "call")

        code.label("stretch")
        code += b"\xc7\x05" + struct.pack("<I", trace_va + 20) + b"\x01\x00\x00\x00"
        # Construct {0, 0, width, height} without touching any callee-saved
        # register. EAX retains the source wrapper throughout this block.
        code += b"\x31\xc9\x89\x0d" + struct.pack("<I", dest_rect_va)
        code += b"\x89\x0d" + struct.pack("<I", dest_rect_va + 4)
        code += b"\x8b\x4f\x38\x89\x0d" + struct.pack("<I", dest_rect_va + 8)
        code += b"\x8b\x4f\x3c\x89\x0d" + struct.pack("<I", dest_rect_va + 12)
        code += b"\x31\xc9\x89\x0d" + struct.pack("<I", source_rect_va)
        code += b"\x89\x0d" + struct.pack("<I", source_rect_va + 4)
        code += b"\x8b\x48\x38\x89\x0d" + struct.pack("<I", source_rect_va + 8)
        code += b"\x8b\x48\x3c\x89\x0d" + struct.pack("<I", source_rect_va + 12)
        # The resource resize routine has an EBP frame. Its return address
        # identifies the title backdrop, not arbitrary 4:3 textures or UI art.
        code += b"\x81\x7d\x04" + struct.pack(
            "<I", self.profile.address("title.cache_resize_return")
        )
        code.jump_if(Condition.NOT_EQUAL, "rectangles")
        code += b"\x60"  # preserve all pending-call registers, including EDX
        code += b"\x8b\x58\x38\x8b\x48\x3c"  # EBX=source width, ECX=height
        code += b"\x85\xdb"
        code.jump_if(Condition.EQUAL, "restore")
        code += b"\x85\xc9"
        code.jump_if(Condition.EQUAL, "restore")
        # Fit by width first; integer floor keeps the result inside the cache.
        code += b"\x8b\x47\x38\xf7\xe1\xf7\xf3\x3b\x47\x3c"
        code.jump_short_if(Condition.ABOVE, "fit_height")
        code += b"\x8b\x57\x3c\x2b\xd0\xd1\xea\x03\xc2"
        code += b"\x89\x15" + struct.pack("<I", dest_rect_va + 4)
        code += b"\xa3" + struct.pack("<I", dest_rect_va + 12)
        code.jump_short("clear")
        code.label("fit_height")
        code += b"\x8b\x47\x3c\xf7\xe3\xf7\xf1"
        code += b"\x8b\x57\x38\x2b\xd0\xd1\xea\x03\xc2"
        code += b"\x89\x15" + struct.pack("<I", dest_rect_va)
        code += b"\xa3" + struct.pack("<I", dest_rect_va + 8)
        code.label("clear")
        # Clear the entire private cache before copying the centered artwork.
        # DDSBLTFX is zeroed (black fill), with dwSize=100. No primary-surface
        # clear or title/control coordinate change is involved.
        code += b"\x8b\x5f\x2c\x83\xec\x64\x8b\xfc\x31\xc0"
        code += b"\xb9\x19\x00\x00\x00\xf3\xab"
        code += b"\xc7\x04\x24\x64\x00\x00\x00"
        code += b"\x54\x68\x00\x04\x00\x01\x6a\x00\x6a\x00\x6a\x00\x53"
        code += b"\x8b\x03\xff\x50\x14\x83\xc4\x64"
        code.label("restore")
        code += b"\x61"
        code.label("rectangles")
        # This JMP replaces the COM CALL, so its return address has not been
        # pushed yet. At wrapper entry the pending Blt stack is therefore
        # ``this, dest RECT, source surface, source RECT, flags, effects``.
        # Replace only the two null RECTs. The stock flags and every surface
        # pointer retain their original values.
        code += b"\xc7\x44\x24\x04" + struct.pack("<I", dest_rect_va)
        code += b"\xc7\x44\x24\x0c" + struct.pack("<I", source_rect_va)

        code.label("call")
        code += b"\xff\x52\x14\xa3" + struct.pack("<I", trace_va + 24) + b"\x6a\x00\x6a\x00"
        code.jump_absolute(self._title_cache_blt_continue_va)
        return code.build()

    @staticmethod
    def build_state_wrapper(
        *,
        state_va: int,
        value: int,
        target_va: int,
        wrapper_va: int,
        root_ptr_va: int | None = None,
        transform_mode_va: int | None = None,
        transform_mode: int = 0,
        reset_va: int | None = None,
        extra_reset_vas: tuple[int, ...] = (),
        extra_write_dwords: tuple[tuple[int, int], ...] = (),
        state_transitions: tuple[tuple[int, tuple[int, ...], int], ...] = (),
        fixed_canvas_owner_va: int | None = None,
        pre_call_va: int | None = None,
    ) -> bytes:
        """Publish or withdraw one fixed-root lifetime around the native method."""
        code = X86Emitter(base_va=wrapper_va)
        if pre_call_va is not None:
            code.call_absolute(pre_call_va)
        code += b"\xc7\x05" + struct.pack("<I", state_va) + struct.pack("<I", value)
        if fixed_canvas_owner_va is not None:
            if value:
                # Show publishes the concrete retained-screen object. Using
                # its identity makes a late Hide from an older object unable
                # to release a newer screen's physical-page lease.
                code += b"\x89\x0d" + struct.pack("<I", fixed_canvas_owner_va)
            else:
                code += b"\x3b\x0d" + struct.pack("<I", fixed_canvas_owner_va)
                code.jump_if(Condition.NOT_EQUAL, "suspend_owner_retained")
                code += b"\xc7\x05" + struct.pack("<I", fixed_canvas_owner_va) + b"\x00\x00\x00\x00"
                code.label("suspend_owner_retained")
        if reset_va is not None:
            code += b"\xc7\x05" + struct.pack("<I", reset_va) + b"\x00\x00\x00\x00"
        for address in extra_reset_vas:
            code += b"\xc7\x05" + struct.pack("<I", address) + b"\x00\x00\x00\x00"
        for address, written_value in extra_write_dwords:
            code += b"\xc7\x05" + struct.pack("<I", address) + struct.pack("<I", written_value)
        _emit_state_transitions(code, state_transitions)
        if root_ptr_va is not None:
            code += b"\x89\x0d" + struct.pack("<I", root_ptr_va)
        if transform_mode_va is not None:
            code += (
                b"\xc7\x05"
                + struct.pack("<I", transform_mode_va)
                + struct.pack("<I", transform_mode)
            )
        code.jump_absolute(target_va)
        return code.build()

    def build_destructor_wrapper(
        self,
        *,
        wrapper_va: int,
        render_depth_va: int,
        input_active_va: int,
        clear_pending_va: int,
        root_ptr_va: int,
        transform_mode_va: int,
        target_va: int,
        extra_clear_vas: tuple[int, ...] = (),
        extra_write_dwords: tuple[tuple[int, int], ...] = (),
        state_transitions: tuple[tuple[int, tuple[int, ...], int], ...] = (),
        extra_release_vas: tuple[int, ...] = (),
        publication_owner_va: int | None = None,
        pre_clear_vas: tuple[int, ...] = (),
        fixed_canvas_owner_va: int | None = None,
    ) -> bytes:
        """Withdraw only state owned by the destructed concrete root."""
        code = X86Emitter(base_va=wrapper_va)
        if publication_owner_va is not None:
            # A successful callback can construct a replacement modal before
            # the old object's destructor runs. Only the object which still
            # owns this exact publication may withdraw shared cache/tooltip
            # state; every delayed non-owner tail-enters its stock destructor.
            code.raw(b"\x3b\x0d" + struct.pack("<I", publication_owner_va))
            code.jump_if(Condition.NOT_EQUAL, "native")
        if pre_clear_vas:
            # Withdraw the identities consumed by re-entrant native teardown
            # before Release or ToolTip::Clear can call patched virtuals. COM
            # surfaces remain published until their explicit Release below.
            code.raw(b"\x31\xc0")
            for address in pre_clear_vas:
                code.raw(b"\xa3" + struct.pack("<I", address))
        # COM Release calls into foreign/native code and may clobber volatile
        # ECX. Preserve the concrete object's ``this`` across every patch-owned
        # teardown operation before tail-entering its stock destructor.
        code.raw(b"\x51")
        # Release optional patch-owned COM objects before clearing their
        # publication slots.
        for index, address in enumerate(extra_release_vas):
            code.raw(b"\xa1" + struct.pack("<I", address) + b"\x85\xc0")
            code.jump_if(Condition.EQUAL, f"released_{index}")
            code.raw(b"\x8b\x10\x50\xff\x52\x08")
            code.raw(b"\xc7\x05" + struct.pack("<I", address) + b"\x00\x00\x00\x00")
            code.label(f"released_{index}")
        code.raw(b"\x59")
        if fixed_canvas_owner_va is not None:
            # Clear only the lease held by this exact object. This conditional
            # edge is safe if GK3 destroys an older instance after a new
            # Load/Save screen has already reused the shared wrappers.
            code.raw(b"\x3b\x0d" + struct.pack("<I", fixed_canvas_owner_va))
            code.jump_short_if(Condition.NOT_EQUAL, "suspend_owner_retained")
            # EAX is scratch at a destructor boundary. The compact store keeps
            # this exact lifetime policy inside the class's wrapper slot.
            code.raw(b"\x31\xc0\xa3" + struct.pack("<I", fixed_canvas_owner_va))
            code.label("suspend_owner_retained")
        code += b"\x33\xc0"
        for address in (
            render_depth_va,
            input_active_va,
            clear_pending_va,
            root_ptr_va,
            transform_mode_va,
        ):
            code += b"\xa3" + struct.pack("<I", address)
        for address in extra_clear_vas:
            code += b"\xa3" + struct.pack("<I", address)
        for address, value in extra_write_dwords:
            code += b"\xc7\x05" + struct.pack("<I", address) + struct.pack("<I", value)
        _emit_state_transitions(code, state_transitions)
        code.label("native")
        code.jump_absolute(target_va)
        return code.build()

    def build_closeup_frame_presenter(
        self,
        *,
        wrapper_va: int,
        target_va: int,
        fixed_canvas_owner_va: int,
        shared_root_ptr_va: int,
        destination_handle_va: int,
        full_damage_region_va: int,
        last_owner_va: int,
        seed_budget_va: int,
        present_count_va: int,
    ) -> bytes:
        """Initialize both physical pages from one concrete CloseUp root.

        CloseUp construction can share the final 3D frame which opened it.
        Its one native traversal is then overwritten on the first page before
        ordinary presentation begins. Replaying the complete live tree
        at the pre-Flip owner for exactly two generations repairs GK3's two
        alternating pages without turning the static interface into a
        permanent full-frame redraw.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x9c\x60")
        code.raw(b"\x8b\x35" + struct.pack("<I", fixed_canvas_owner_va))
        code.raw(b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "done")
        # The system root is republished by every concrete fixed traversal.
        # Requiring exact equality prevents a delayed owner from drawing after
        # a replacement Load/Save or other fixed canvas becomes current.
        code.raw(b"\x3b\x35" + struct.pack("<I", shared_root_ptr_va))
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\x81\x3e" + struct.pack("<I", self.profile.address("closeup.vtable")))
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\x83\x3d" + struct.pack("<I", destination_handle_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "done")

        code.raw(b"\x3b\x35" + struct.pack("<I", last_owner_va))
        code.jump_if(Condition.EQUAL, "seed_ready")
        code.raw(b"\x89\x35" + struct.pack("<I", last_owner_va))
        code.raw(b"\xc7\x05" + struct.pack("<I", seed_budget_va) + b"\x02\x00\x00\x00")
        code.label("seed_ready")
        code.raw(b"\x83\x3d" + struct.pack("<I", seed_budget_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "done")
        # Draw(destination, complete damage). The wrapped thiscall owns RET 8
        # and republishes the same root/destination identity idempotently.
        code.raw(b"\x68" + struct.pack("<I", full_damage_region_va))
        code.raw(b"\xff\x35" + struct.pack("<I", destination_handle_va))
        code.raw(b"\x8b\xce")
        code.call_absolute(target_va)
        code.raw(b"\xff\x0d" + struct.pack("<I", seed_budget_va))
        code.raw(b"\xff\x05" + struct.pack("<I", present_count_va))
        code.label("done")
        code.raw(b"\x61\x9d\xc3")
        return code.build()

    def build_confirm_quit_room_repair_helper(
        self,
        *,
        wrapper_va: int,
        room_root_va: int,
        cursor_rect_va: int,
        destination_handle_va: int,
        destination_wrapper_va: int,
        collection_va: int,
        repair_rect_va: int,
        primary_surface_ptr_va: int,
        back_surface_ptr_va: int,
    ) -> bytes:
        """Repair a cursor footprint only when the outgoing layer is that room."""
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x9c\x60")
        code.raw(b"\x8b\x35" + struct.pack("<I", room_root_va) + b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(
            b"\x81\x3e" + struct.pack("<I", self.profile.address("transition.room_layer_vtable"))
        )
        code.jump_if(Condition.NOT_EQUAL, "done")
        # The remembered room survives while the driving map or another
        # full-screen layer covers it. Redrawing that hidden room here can
        # clear the map's back page before the retained Quit dialog dims it.
        # A concrete vtable proves type, not ownership of the visible frame.
        code.call_absolute(self.profile.address("ui.current_layer"))
        code.raw(b"\x3b\xc6")
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\x8b\x1d" + struct.pack("<I", destination_handle_va) + b"\x85\xdb")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\xa1" + struct.pack("<I", cursor_rect_va))
        code.raw(b"\x3b\x05" + struct.pack("<I", cursor_rect_va + 8))
        code.jump_if(Condition.GREATER_OR_EQUAL, "done")
        code.raw(b"\xa1" + struct.pack("<I", cursor_rect_va + 4))
        code.raw(b"\x3b\x05" + struct.pack("<I", cursor_rect_va + 12))
        code.jump_if(Condition.GREATER_OR_EQUAL, "done")

        # Snapshot the prior completed framebuffer footprint into a stable,
        # one-RECT DamageCollection owned by the injected control segment.
        code.raw(b"\x60")
        code.raw(b"\xbe" + struct.pack("<I", cursor_rect_va))
        code.raw(b"\xbf" + struct.pack("<I", repair_rect_va))
        code.raw(b"\xb9\x04\x00\x00\x00\xf3\xa5\x61")
        code.raw(b"\x31\xc0")
        code.raw(b"\xa3" + struct.pack("<I", collection_va))
        code.raw(b"\xa3" + struct.pack("<I", collection_va + 12))
        code.raw(b"\xc7\x05" + struct.pack("<I", collection_va + 4))
        code.raw(struct.pack("<I", repair_rect_va))
        code.raw(b"\xc7\x05" + struct.pack("<I", collection_va + 8))
        code.raw(struct.pack("<I", repair_rect_va + 16))

        # Draw the still-live underlying RoomLayer into ConfirmQuit's exact
        # destination before the modal dimmer runs. The one-rectangle native
        # traversal retires C_ZOOM without rebuilding or guessing scene pixels.
        code.raw(b"\x68" + struct.pack("<I", collection_va))
        code.raw(b"\x53\x8b\xce\x8b\x06\xff\x90\xa0\x00\x00\x00")

        # The published handle above resolves to the current physical back
        # page. Seed its repaired undimmed room into the displayed peer before
        # ConfirmQuit applies the dimmer; its post-Flip presenter will later
        # seed the finished modal composition in the opposite direction.
        code.raw(b"\x8b\x3d" + struct.pack("<I", destination_wrapper_va) + b"\x85\xff")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x7f\x2c\x85\xff")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\xa1" + struct.pack("<I", primary_surface_ptr_va) + b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x15" + struct.pack("<I", back_surface_ptr_va) + b"\x85\xd2")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x3b\xf8")
        code.jump_if(Condition.EQUAL, "repair_was_primary")
        code.raw(b"\x3b\xfa")
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.jump_short("copy_repaired_peer")
        code.label("repair_was_primary")
        code.raw(b"\x92")
        code.label("copy_repaired_peer")
        code.raw(b"\x6a\x10\x6a\x00\x52\x6a\x00\x6a\x00\x8b\x08\x50\xff\x51\x1c")
        code.label("done")
        code.raw(b"\x61\x9d\xc3")
        return code.build()

    def build_confirm_quit_post_flip_presenter(
        self,
        *,
        wrapper_va: int,
        pending_va: int,
        result_va: int,
        copy_count_va: int,
        seeded_root_va: int,
        shared_root_ptr_va: int,
        cursor_suspended_va: int,
        cursor_resume_helper_va: int,
    ) -> bytes:
        """Seed ConfirmQuit's returned back page from its completed front page.

        ConfirmQuit dims the prior room and constructs its panel only once.
        With a two-page native flip chain, that complete composition reaches
        the front page while the newly returned back page still contains the
        retired toolbar/room. The transition Flip wrapper calls this helper
        only after ``DD_OK``. Copying front to returned back at that boundary
        initializes the peer without redrawing a partial retained tree or ever
        writing to the page currently scanned out.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x9c\x60")
        code.raw(b"\x83\x3d" + struct.pack("<I", pending_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "done")

        # Do not let a delayed callback seed a replacement screen. Both the
        # global current layer and the root published by the completed Draw
        # must still identify the exact ConfirmQuit object and class.
        code.call_absolute(self.profile.address("ui.current_layer"))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "withdraw")
        code.raw(b"\x8b\xf0")
        code.raw(b"\x3b\x05" + struct.pack("<I", shared_root_ptr_va))
        code.jump_if(Condition.NOT_EQUAL, "withdraw")
        code.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("confirm_quit.vtable")))
        code.jump_if(Condition.NOT_EQUAL, "withdraw")

        # IDirectDrawSurface4::BltFast(back, 0, 0, front, NULL,
        # DDBLTFAST_WAIT). The same native transaction is already proven by
        # the 2D-to-3D page seeder. Source and destination COM interfaces are
        # resolved only after Flip and are never retained across generations.
        code.raw(b"\xa1" + struct.pack("<I", self.profile.address("transition.back_surface_ptr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(
            b"\x8b\x15" + struct.pack("<I", self.profile.address("transition.primary_surface_ptr"))
        )
        code.raw(b"\x85\xd2")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x6a\x10\x6a\x00\x52\x6a\x00\x6a\x00\x8b\x08\x50\xff\x51\x1c")
        code.raw(b"\xa3" + struct.pack("<I", result_va))
        code.raw(b"\x85\xc0")
        # A transient DirectDraw failure keeps the request armed so the next
        # successful Flip retries it instead of accepting a half-seeded pair.
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\xc7\x05" + struct.pack("<I", pending_va) + b"\x00\x00\x00\x00")
        code.raw(b"\x89\x35" + struct.pack("<I", seeded_root_va))
        code.raw(b"\xff\x05" + struct.pack("<I", copy_count_va))
        code.call_absolute(cursor_resume_helper_va)
        code.jump("done")

        code.label("withdraw")
        code.raw(b"\xc7\x05" + struct.pack("<I", pending_va) + b"\x00\x00\x00\x00")
        code.label("done")
        # Destruction changes the lifetime token from active to pending. Wait
        # until the first successful room Flip has replaced the dialog before
        # allowing the asynchronous cursor worker to capture a new save-under.
        code.raw(b"\x83\x3d" + struct.pack("<I", cursor_suspended_va) + b"\x02")
        code.jump_if(Condition.NOT_EQUAL, "return")
        code.call_absolute(cursor_resume_helper_va)
        code.label("return")
        code.raw(b"\x61\x9d\xc3")
        return code.build()
