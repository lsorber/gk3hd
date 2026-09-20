"""Compile the transient room-status text affine."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.layout import (
    SYSTEM_CONTROL_ROOM_STATUS_AUTHORED_RECT_OFFSET,
    SYSTEM_CONTROL_ROOM_STATUS_AUTHORED_STATE_END_OFFSET,
    SYSTEM_CONTROL_ROOM_STATUS_DAMAGE_RECT_OFFSET,
    SYSTEM_CONTROL_ROOM_STATUS_DAMAGE_REGION_OFFSET,
    SYSTEM_CONTROL_ROOM_STATUS_PENDING_STATE_END_OFFSET,
    SYSTEM_CONTROL_ROOM_STATUS_PENDING_VALID_OFFSET,
    SYSTEM_CONTROL_ROOM_STATUS_STATE_SIZE,
)
from gk3hd.patch.definitions.runtime2d.system.shared import SystemCompilerContext

if TYPE_CHECKING:
    from gk3hd.patch.binary.mutations import ExecutableMutationPlan
    from gk3hd.patch.binary.payload import SegmentPayloadBuilder


@dataclass(frozen=True, slots=True, kw_only=True)
class RoomStatusFeatureCompiler(SystemCompilerContext):
    """Scale transient room-status text within its native draw transaction.

    Outcome:
        The room/time/score label scales like the 1024 reference and retains
        GK3's native fade and background restoration.
    Before:
        The TextBox's glyphs and backing fill use authored 1024x768 geometry on
        a larger physical room framebuffer.
    After:
        Only RoomLayer's concrete status TextBox maps its glyph and fill
        geometry by the live output-height/reference-height ratio.
    Strategy:
        Identify RoomLayer's first direct child, bracket its synchronous native
        Draw call with one depth flag, and consume that flag at the fill hook.
    Boundaries:
        The renderer owns page presentation. This feature does not defer,
        replay, cache, copy, filter damage, or repair frame history.
    """

    def emit_state(self, payload: SegmentPayloadBuilder, *, control_va: int) -> None:
        """Own every zero/data region used by transient room-status drawing."""
        payload.reserve(
            label="room-status draw state",
            offset=self._off_room_status_object_ptr,
            size=SYSTEM_CONTROL_ROOM_STATUS_STATE_SIZE,
        )
        payload.reserve(
            label="room-status authored rectangle",
            offset=SYSTEM_CONTROL_ROOM_STATUS_AUTHORED_RECT_OFFSET,
            size=SYSTEM_CONTROL_ROOM_STATUS_AUTHORED_STATE_END_OFFSET
            - SYSTEM_CONTROL_ROOM_STATUS_AUTHORED_RECT_OFFSET,
        )
        damage_rect_va = control_va + SYSTEM_CONTROL_ROOM_STATUS_DAMAGE_RECT_OFFSET
        payload.place(
            label="room-status presentation damage vector",
            offset=SYSTEM_CONTROL_ROOM_STATUS_DAMAGE_REGION_OFFSET,
            payload=struct.pack("<IIII", 0, damage_rect_va, damage_rect_va, 0),
        )
        payload.reserve(
            label="room-status pending damage state",
            offset=SYSTEM_CONTROL_ROOM_STATUS_PENDING_VALID_OFFSET,
            size=SYSTEM_CONTROL_ROOM_STATUS_PENDING_STATE_END_OFFSET
            - SYSTEM_CONTROL_ROOM_STATUS_PENDING_VALID_OFFSET,
        )

    def plan_hooks(
        self,
        plan: ExecutableMutationPlan,
        *,
        draw_wrapper_va: int,
        fill_wrapper_va: int,
    ) -> None:
        """Own the room-status class and backing-fill interception points."""
        plan.pointer(
            label="room-status draw",
            slot_va=self._room_text_draw_slot_va,
            expected=self.profile.address("room_text.draw"),
            target_va=draw_wrapper_va,
        )
        plan.branch(
            label="room-status backing fill",
            opcode=BranchOpcode.CALL,
            site_va=self._room_text_fill_call_site_va,
            expected=self._room_text_fill_call_original,
            target_va=fill_wrapper_va,
            size=len(self._room_text_fill_call_original),
        )

    def build_room_text_draw_wrapper(
        self,
        *,
        wrapper_va: int,
        object_ptr_va: int,
        present_depth_va: int,
        draw_count_va: int,
    ) -> bytes:
        """Draw only the concrete room-status TextBox in a scaled scope.

        RoomLayer's first direct child is the status TextBox. Its identity is
        retained while a modal layer temporarily becomes ``ui.current_layer``;
        every unrelated TextBox remains byte-for-byte native. The accepted
        call stays synchronous and merely brackets GK3's original Draw with a
        depth flag consumed by the status fill affine. The high-level font
        hook independently owns glyph scaling before clipping.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x55\x8b\xec\x83\xec\x04\x53\x56\x57\x8b\xd9")
        code.raw(b"\x31\xc0\x89\x45\xfc")

        # Establish the exact owner from RoomLayer's live child vector. This
        # class proof avoids coordinate, output-size, and text heuristics.
        code.call_absolute(self.profile.address("ui.current_layer"))
        code.raw(b"\x85\xc0\x8b\xf0")
        code.jump_if(Condition.EQUAL, "current_not_room")
        code.raw(b"\x6a\x54\x56\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "current_not_room")
        code.raw(
            b"\x81\x3e" + struct.pack("<I", self.profile.address("transition.room_layer_vtable"))
        )
        code.jump_if(Condition.NOT_EQUAL, "current_not_room")

        # While RoomLayer is current, its first child is authoritative. Never
        # retain an address after the live room has replaced that object.
        code.raw(b"\x83\x7e\x50\x00")
        code.jump_if(Condition.LESS_OR_EQUAL, "room_other_text")
        code.raw(b"\x8b\x76\x4c\x85\xf6")
        code.jump_if(Condition.EQUAL, "room_other_text")
        code.raw(b"\x6a\x04\x56\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "room_other_text")
        code.raw(b"\x39\x1e")
        code.jump_if(Condition.NOT_EQUAL, "room_other_text")
        code.raw(b"\x89\x1d" + struct.pack("<I", object_ptr_va))
        code.jump("status")

        code.label("current_not_room")
        # A modal replaces current_layer while the room status remains a live
        # drawable sibling. The call itself proves that the retained TextBox
        # is still live; a later RoomLayer draw replaces this identity with its
        # own first child. Do not tie persistent ownership to the transient
        # room-presentation depth flag.
        code.raw(b"\x3b\x1d" + struct.pack("<I", object_ptr_va))
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.jump("status")

        code.label("room_other_text")
        code.jump("native")

        code.label("status")
        code.raw(b"\xff\x05" + struct.pack("<I", present_depth_va))
        code.raw(b"\xff\x75\x0c\xff\x75\x08\x8b\xcb")
        code.call_absolute(self.profile.address("room_text.draw"))
        code.raw(b"\x89\x45\xfc")
        code.raw(b"\xff\x0d" + struct.pack("<I", present_depth_va))
        code.raw(b"\xff\x05" + struct.pack("<I", draw_count_va))
        code.jump("done")

        code.label("native")
        code.raw(b"\xff\x75\x0c\xff\x75\x08\x8b\xcb")
        code.call_absolute(self.profile.address("room_text.draw"))
        code.raw(b"\x89\x45\xfc")

        code.label("done")
        code.raw(b"\x8b\x45\xfc\x5f\x5e\x5b\xc9\xc2\x08\x00")
        return code.build()

    def build_room_status_fill_wrapper(
        self,
        *,
        wrapper_va: int,
        present_depth_va: int,
        fill_count_va: int,
    ) -> bytes:
        """Map the status backing rectangle through the glyph affine."""
        code = X86Emitter(base_va=wrapper_va)
        # Native signature: thiscall(Renderer, destination handle, colour,
        # RECT*, opacity). Keep a private RECT so caller-owned damage remains
        # in the domain expected by GK3's native retained-background owner.
        code.raw(b"\x55\x8b\xec\x83\xec\x10\x53\x56\x57\x8b\xd9")
        code.raw(b"\x83\x3d" + struct.pack("<I", present_depth_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\x8b\x75\x10\x85\xf6")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\xff\x05" + struct.pack("<I", fill_count_va))

        # floor(near * H / 768), ceil(far * H / 768).
        for source_offset, local_offset, far_edge in (
            (0, 0xF0, False),
            (4, 0xF4, False),
            (8, 0xF8, True),
            (12, 0xFC, True),
        ):
            if source_offset == 0:
                code.raw(b"\x8b\x06")
            else:
                code.raw(b"\x8b\x46" + bytes([source_offset]))
            code.raw(b"\x0f\xaf\x05" + struct.pack("<I", self._physical_width_va + 4))
            if far_edge:
                code.raw(b"\x05\xff\x02\x00\x00")
            code.raw(b"\x99\xb9\x00\x03\x00\x00\xf7\xf9")
            code.raw(b"\x89\x45" + bytes([local_offset]))

        code.raw(b"\xff\x75\x14\x8d\x45\xf0\x50\xff\x75\x0c\xff\x75\x08\x8b\xcb")
        code.call_absolute(self.profile.address("runtime2d.fill_rect"))
        code.jump("done")
        code.label("native")
        code.raw(b"\xff\x75\x14\xff\x75\x10\xff\x75\x0c\xff\x75\x08\x8b\xcb")
        code.call_absolute(self.profile.address("runtime2d.fill_rect"))
        code.label("done")
        code.raw(b"\x5f\x5e\x5b\xc9\xc2\x10\x00")
        return code.build()
