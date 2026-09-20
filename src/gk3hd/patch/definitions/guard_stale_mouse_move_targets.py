"""Guard and coalesce native mouse-move dispatch at its ownership boundary."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter, decode_rel32_branch
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile


@dataclass(frozen=True, slots=True)
class MouseMoveDispatchABI:
    """Optional UI-traversal adapter owned by the fixed-interface runtime."""

    ui_dispatch_adapter_slot_va: int


@dataclass(frozen=True, slots=True)
class StaleMouseMoveCompiler:
    """Reject obsolete or unsafe mouse movement at GK3's dispatch boundary.

    Outcome:
        Cursor movement cannot call a destroyed UI target or replay an older
        point over a newer cursor position.

    Before:
        Play, Restore, and transient screens may destroy the mouse manager or
        current event target while queued ``WM_MOUSEMOVE`` messages remain.
        GK3 then calls virtual slots ``+0x58`` and ``+0x50`` through stale heap
        pointers, or publishes a superseded point after the final one.

    After:
        Invalid targets and obsolete queued moves are dropped individually;
        valid movement follows the original dispatch unchanged. A newly
        published room accepts movement only after its first valid 3D
        projection establishes the nested input graph.

    Strategy:
        Validate both virtual-dispatch edges, their nested interactive call,
        and preceding hit-test callbacks. When the fixed-interface adapter is
        linked, compare the queued point with USER32's current client point and
        restore GK3's stack-local ``POINT`` after the query.

    Boundaries:
        The patch does not synthesize or clamp movement, alter clicks, or draw
        the cursor. Coordinate inversion is supplied through the optional typed
        adapter owned by ``scale_fixed_interfaces``.
    """

    profile: BuildProfile

    id: ClassVar[str] = "stabilize_mouse_input"

    _section_name: ClassVar[str] = ".gk3ui"
    section_name: ClassVar[str] = _section_name
    # The frame-based handler returns EXCEPTION_DISPOSITION values 0/1; -1 is
    # valid only for a vectored handler and makes Windows raise
    # STATUS_INVALID_DISPOSITION.  Helpers and late telemetry occupy separate
    # ranges so diagnostic writes can never self-modify executable payloads.
    _section_size: ClassVar[int] = 0xE00
    _section_characteristics: ClassVar[int] = 0xE0000020
    _magic: ClassVar[bytes] = b"GK3MOVE1"
    _layout_version: ClassVar[int] = 34
    _off_layout_version: ClassVar[int] = 0x08
    _off_dropped_count: ClassVar[int] = 0x0C
    _off_changed_during_validation_count: ClassVar[int] = 0x10
    _off_forwarded_count: ClassVar[int] = 0x14
    _off_nested_dropped_count: ClassVar[int] = 0x18
    _off_wndproc_dropped_count: ClassVar[int] = 0x1C
    # MouseManager has already committed its durable physical cursor state
    # when it reaches the common UI traversal. A zero value preserves the
    # standalone native path; scale_fixed_interfaces publishes a transactional
    # coordinate adapter here.
    _off_ui_dispatch_adapter: ClassVar[int] = 0x1EC
    _off_tree_dropped_count: ClassVar[int] = 0x1F0
    _off_wndproc_exception_count: ClassVar[int] = 0x1F4
    _off_last_projection_width: ClassVar[int] = 0x1F8
    _off_last_current_layer_vtable: ClassVar[int] = 0x1FC
    # Keep all late diagnostics after every executable helper. Earlier layouts
    # accidentally placed these cells in the exception-handler payload; a
    # normal trace write could then self-modify the code intended to recover
    # the very movement fault being diagnosed.
    _off_last_event_target_vtable: ClassVar[int] = 0xA00
    _off_last_current_layer: ClassVar[int] = 0xA04
    _off_exception_projection_width: ClassVar[int] = 0xA08
    _off_exception_current_layer_vtable: ClassVar[int] = 0xA0C
    _off_exception_event_target_vtable: ClassVar[int] = 0xA10
    _off_exception_current_layer: ClassVar[int] = 0xA14
    _off_exception_eip: ClassVar[int] = 0xA18
    _off_exception_address: ClassVar[int] = 0xA1C
    _off_exception_access_address: ClassVar[int] = 0xA20
    _off_exception_registers: ClassVar[int] = 0xA24
    _off_exception_stack: ClassVar[int] = 0xA44
    _off_obsolete_wndproc_point_count: ClassVar[int] = 0xA54
    _off_popup_message_dropped_count: ClassVar[int] = 0xA58
    # Exact callback traces expose the native object/POINT/descriptor boundary
    # without interpreting mutable UI trees from a later capture sample. Each
    # record contains call count, last object/x/y/result, non-zero count, and
    # the last non-zero object/x/y/result in that order.
    _off_tree_b8_trace: ClassVar[int] = 0xA60
    _off_tree_bc_trace: ClassVar[int] = 0xA88
    _off_wrapper: ClassVar[int] = 0x20
    _off_ui_dispatch_bridge: ClassVar[int] = 0x1D0
    _off_nested_wrapper: ClassVar[int] = 0x200
    _off_wndproc_wrapper: ClassVar[int] = 0x280
    # Keep following helpers on 0x20/0x40 boundaries so generated payloads
    # cannot overlap.
    _off_tree_b8_wrapper: ClassVar[int] = 0x5C0
    _off_tree_bc_wrapper: ClassVar[int] = 0x6C0
    _off_tree_b4_wrapper: ClassVar[int] = 0x7C0
    _off_wndproc_exception_handler: ClassVar[int] = 0x860
    _off_interactive_point_helper: ClassVar[int] = 0x940
    # This wrapper replaces the full nine-byte virtual-call sequence and must
    # validate both the receiver and vtable. Keep it in the free tail after
    # the popup-query counter rather than compressing that ownership proof.
    _off_popup_message_wrapper: ClassVar[int] = 0xB84
    _off_popup_query_wrapper: ClassVar[int] = 0xB00
    _off_popup_query_dropped_count: ClassVar[int] = 0xB80
    _off_direct_message_wrapper: ClassVar[int] = 0xC00
    _off_selected_message_wrapper: ClassVar[int] = 0xD00
    _off_direct_message_dropped_count: ClassVar[int] = 0xD80
    _off_selected_message_dropped_count: ClassVar[int] = 0xD84
    # FUN_004bebf0 forwards a POINT to the currently focused UI object.  It
    # has no stack frame of its own, which is why GK3's crash report shows the
    # outer 0x00533CEC WndProc return rather than this invalid virtual call.
    _target_site_name: ClassVar[str] = "mouse_move.target_dispatch"
    _target_prefix_name: ClassVar[str] = "mouse_move.target_dispatch_prefix"
    _target_suffix_name: ClassVar[str] = "mouse_move.target_dispatch_suffix"
    _ui_dispatch_site_name: ClassVar[str] = "mouse_move.ui_dispatch_call"
    _ui_dispatch_prefix_name: ClassVar[str] = "mouse_move.ui_dispatch_prefix"
    _ui_dispatch_suffix_name: ClassVar[str] = "mouse_move.ui_dispatch_suffix"

    # FUN_00525399's active path makes a second virtual call after the common
    # dispatcher returns.  Hook that exact six-byte call as the last boundary
    # against a vtable that is retired between outer validation and use.
    _nested_site_name: ClassVar[str] = "mouse_move.nested_dispatch"
    _nested_prefix_name: ClassVar[str] = "mouse_move.nested_dispatch_prefix"
    _nested_suffix_name: ClassVar[str] = "mouse_move.nested_dispatch_suffix"
    _interactive_point_site_name: ClassVar[str] = "mouse_move.interactive_point_cache"

    # WM_MOUSEMOVE reaches the common dispatcher through this earlier virtual
    # call on GK3's global mouse manager.  The repeated EIP=0 crash reports
    # return to 0x00533CEC because this exact slot +0x58 call was null; guarding
    # only the later event-target slot therefore could not catch the failure.
    _wndproc_site_name: ClassVar[str] = "mouse_move.wndproc_dispatch"
    _wndproc_prefix_name: ClassVar[str] = "mouse_move.wndproc_dispatch_prefix"
    _wndproc_suffix_name: ClassVar[str] = "mouse_move.wndproc_dispatch_suffix"
    _popup_message_site_name: ClassVar[str] = "mouse_move.popup_message_dispatch"
    _popup_query_site_name: ClassVar[str] = "mouse_move.popup_query_dispatch"
    _direct_message_site_names: ClassVar[tuple[str, ...]] = (
        "mouse_move.message_primary_dispatch",
        "mouse_move.message_secondary_dispatch",
        "mouse_move.message_list_dispatch",
    )
    _selected_message_site_name: ClassVar[str] = "mouse_move.message_selected_dispatch"
    _scene_owner_offset: ClassVar[int] = 0x444
    _scene_dispatcher_offset: ClassVar[int] = 0x44
    _event_target_offset: ClassVar[int] = 0x14

    # The mouse manager performs hit testing before FUN_004BEBF0.  During a
    # modal teardown, one of these retained child pointers can already contain
    # the 0x00258000 freed-block marker, so guarding only the later +0x50 call
    # cannot help.  All sites share the same one-argument or no-argument ABI.
    _tree_hook_shapes: ClassVar[tuple[tuple[str, int, int], ...]] = (
        ("mouse_move.tree_b8_1", 0xB8, 4),
        ("mouse_move.tree_b8_2", 0xB8, 4),
        ("mouse_move.tree_b8_3", 0xB8, 4),
        ("mouse_move.tree_b8_4", 0xB8, 4),
        ("mouse_move.tree_bc_1", 0xBC, 4),
        ("mouse_move.tree_bc_2", 0xBC, 4),
        ("mouse_move.tree_bc_3", 0xBC, 4),
        ("mouse_move.tree_b4_1", 0xB4, 0),
        ("mouse_move.tree_b4_2", 0xB4, 0),
    )

    # Every captured EIP=0 failure left this MSVC heap replacement value in
    # the first word of the retired mouse-manager or event-target block.
    _freed_object_marker: ClassVar[int] = 0x00258000
    _interactive_object_span: ClassVar[int] = 0x1B0
    _interactive_vtable_span: ClassVar[int] = 0xB8

    @property
    def _tree_hook_specs(self) -> tuple[tuple[int, bytes, int, int], ...]:
        """Resolve hit-test sites while keeping their ABI shapes in patch policy."""
        return tuple(
            (site.va, site.original, slot, stack_cleanup)
            for name, slot, stack_cleanup in self._tree_hook_shapes
            for site in (self.profile.site(name),)
        )

    @property
    def _hook_site_va(self) -> int:
        return self.profile.site(self._target_site_name).va

    @property
    def _hook_orig(self) -> bytes:
        return self.profile.site(self._target_site_name).original

    @property
    def _hook_back_va(self) -> int:
        return self.profile.address("mouse_move.target_dispatch_continue")

    @property
    def _nested_hook_site_va(self) -> int:
        return self.profile.site(self._nested_site_name).va

    @property
    def _nested_hook_orig(self) -> bytes:
        return self.profile.site(self._nested_site_name).original

    @property
    def _wndproc_hook_site_va(self) -> int:
        return self.profile.site(self._wndproc_site_name).va

    @property
    def _wndproc_hook_orig(self) -> bytes:
        return self.profile.site(self._wndproc_site_name).original

    @property
    def _wndproc_hook_back_va(self) -> int:
        return self.profile.address("mouse_move.wndproc_dispatch_continue")

    @property
    def _popup_message_site_va(self) -> int:
        return self.profile.site(self._popup_message_site_name).va

    @property
    def _popup_message_orig(self) -> bytes:
        return self.profile.site(self._popup_message_site_name).original

    @property
    def _popup_query_site_va(self) -> int:
        return self.profile.site(self._popup_query_site_name).va

    @property
    def _popup_query_orig(self) -> bytes:
        return self.profile.site(self._popup_query_site_name).original

    @property
    def _direct_message_sites(self) -> tuple[tuple[int, bytes], ...]:
        return tuple(
            (site.va, site.original)
            for name in self._direct_message_site_names
            for site in (self.profile.site(name),)
        )

    @property
    def _selected_message_site_va(self) -> int:
        return self.profile.site(self._selected_message_site_name).va

    @property
    def _selected_message_orig(self) -> bytes:
        return self.profile.site(self._selected_message_site_name).original

    @property
    def _interactive_point_site_va(self) -> int:
        return self.profile.site(self._interactive_point_site_name).va

    @property
    def _interactive_point_orig(self) -> bytes:
        return self.profile.site(self._interactive_point_site_name).original

    @property
    def _ui_dispatch_site_va(self) -> int:
        return self.profile.site(self._ui_dispatch_site_name).va

    @property
    def _ui_dispatch_orig(self) -> bytes:
        return self.profile.site(self._ui_dispatch_site_name).original

    @property
    def _mouse_manager_global_va(self) -> int:
        return self.profile.address("mouse_move.mouse_manager")

    @property
    def _engine_loop_global_va(self) -> int:
        return self.profile.address("mouse_move.engine_loop")

    @property
    def _is_bad_read_ptr_iat_va(self) -> int:
        return self.profile.address("win32.IsBadReadPtr")

    @property
    def _is_bad_code_ptr_iat_va(self) -> int:
        return self.profile.address("win32.IsBadCodePtr")

    @property
    def _screen_to_client_iat_va(self) -> int:
        return self.profile.address("win32.ScreenToClient")

    @property
    def _get_cursor_pos_iat_va(self) -> int:
        return self.profile.address("win32.GetCursorPos")

    @property
    def _interactive_move_method_va(self) -> int:
        return self.profile.address("mouse_move.interactive_handler")

    @staticmethod
    def _hook_target(site_va: int, payload: bytes) -> int | None:
        return decode_rel32_branch(
            opcode=BranchOpcode.JUMP,
            site_va=site_va,
            instruction=payload[:5],
        )

    @staticmethod
    def _call_target(site_va: int, payload: bytes) -> int | None:
        return decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=site_va,
            instruction=payload[:5],
        )

    def _build_wrapper(
        self,
        *,
        wrapper_va: int,
        dropped_count_va: int,
    ) -> bytes:
        code = X86Emitter(base_va=wrapper_va)

        # Validate the object pointer before reading its vtable.  IsBadReadPtr
        # is already imported by GK3, so this adds no dependency or loader work.
        code += b"\x8b\x4e\x14\x85\xc9"  # mov ecx,[esi+14h]; test ecx,ecx
        code.jump_if(Condition.EQUAL, "invalid")
        code += b"\x6a\x04\x51\xff\x15" + struct.pack("<I", self._is_bad_read_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "invalid")

        # A freed but committed heap block is still readable.  Validate its
        # replacement first word and the complete vtable span through +0x50.
        code += b"\x8b\x4e\x14\x8b\x01\x85\xc0"
        code.jump_if(Condition.EQUAL, "invalid")
        code += b"\x6a\x54\x50\xff\x15" + struct.pack("<I", self._is_bad_read_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "invalid")

        # Read the outer move method.  Most UI targets need only this common
        # slot, but FUN_00525399 conditionally dispatches a second method from
        # slot +0xB4 after reading fields through object+0x1AC.  A recycled
        # target can retain executable +0x50 while +0xB4 is already zero, so
        # validate that larger known contract before taking the snapshot.
        code += b"\x8b\x4e\x14\x8b\x01\x8b\x50\x50\x85\xd2"
        code.jump_if(Condition.EQUAL, "invalid")
        code += b"\x81\xfa" + struct.pack("<I", self._interactive_move_method_va)
        code.jump_if(Condition.NOT_EQUAL, "snapshot")
        code += b"\x68" + struct.pack("<I", self._interactive_object_span)
        code += b"\x51\xff\x15" + struct.pack("<I", self._is_bad_read_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "invalid")
        code += b"\x8b\x4e\x14\x8b\x01\x8b\x50\x50"
        code += b"\x81\xfa" + struct.pack("<I", self._interactive_move_method_va)
        code.jump_if(Condition.NOT_EQUAL, "invalid")
        code += b"\x68" + struct.pack("<I", self._interactive_vtable_span)
        code += b"\x50\xff\x15" + struct.pack("<I", self._is_bad_read_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "invalid")

        code.label("snapshot")
        code += b"\x8b\x4e\x14\x8b\x01\x8b\x50\x50"
        code += b"\x51\x50\x52"  # save object, vtable, outer method

        # Retain zero for ordinary targets and for an inactive nested path.
        # Otherwise retain the +0xB4 method beside the outer snapshot and
        # validate it before validating +0x50.
        code += b"\x33\xd2\x81\x3c\x24" + struct.pack("<I", self._interactive_move_method_va)
        code.jump_if(Condition.NOT_EQUAL, "nested_saved")
        code += b"\x8b\x4c\x24\x08\x80\x79\x18\x00"
        code.jump_if(Condition.EQUAL, "nested_saved")
        code += b"\x8b\x44\x24\x04\x8b\x90\xb4\x00\x00\x00"
        code.label("nested_saved")
        code += b"\x52"  # nested method (or zero), outer method, vtable, object

        code += b"\x81\x7c\x24\x04" + struct.pack("<I", self._interactive_move_method_va)
        code.jump_if(Condition.NOT_EQUAL, "validate_outer")
        code += b"\x8b\x4c\x24\x0c\x80\x79\x18\x00"
        code.jump_if(Condition.EQUAL, "validate_outer")
        code += b"\x83\x3c\x24\x00"
        code.jump_if(Condition.EQUAL, "changed")
        code += b"\xff\x34\x24\xff\x15" + struct.pack("<I", self._is_bad_code_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "changed")

        code.label("validate_outer")
        code += b"\xff\x74\x24\x04\xff\x15" + struct.pack("<I", self._is_bad_code_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "changed")

        # No API is called after this consistency check, so the final virtual
        # dispatch has no wide validation window.  If the manager's target,
        # its vtable, or slot +0x50 changed meanwhile, discard this obsolete
        # move instead of combining generations of a recycled heap object.
        code += b"\x8b\x4e\x14\x3b\x4c\x24\x0c"
        code.jump_if(Condition.NOT_EQUAL, "changed")
        code += b"\x8b\x01\x3b\x44\x24\x08"
        code.jump_if(Condition.NOT_EQUAL, "changed")
        code += b"\x8b\x50\x50\x3b\x54\x24\x04"
        code.jump_if(Condition.NOT_EQUAL, "changed")
        code += b"\x81\xfa" + struct.pack("<I", self._interactive_move_method_va)
        code.jump_if(Condition.NOT_EQUAL, "nested_consistent")
        code += b"\x80\x79\x18\x00"
        code.jump_if(Condition.EQUAL, "nested_zero")
        code += b"\x8b\x90\xb4\x00\x00\x00\x3b\x14\x24"
        code.jump_if(Condition.NOT_EQUAL, "changed")
        code.jump("nested_consistent")
        code.label("nested_zero")
        code += b"\x83\x3c\x24\x00"
        code.jump_if(Condition.NOT_EQUAL, "changed")
        code.label("nested_consistent")

        # Discard the nested snapshot, restore the outer method and object,
        # discard the saved vtable, and reproduce the displaced thiscall.
        code += b"\x83\xc4\x04\x58\x83\xc4\x04\x59"
        code += b"\xff\x05" + struct.pack(
            "<I", wrapper_va - self._off_wrapper + self._off_forwarded_count
        )
        # Coordinate adaptation runs around the complete common UI traversal,
        # before it chooses this target. This boundary therefore remains a
        # pure safety check and always reproduces the validated native call.
        code += b"\x57\xff\xd0"
        code.jump_absolute(self._hook_back_va)

        code.label("changed")
        code += b"\xff\x05" + struct.pack(
            "<I", wrapper_va - self._off_wrapper + self._off_changed_during_validation_count
        )
        code += b"\x83\xc4\x10"  # discard nested method, outer method, vtable, and object

        code.label("invalid")
        code += b"\xff\x05" + struct.pack("<I", dropped_count_va)
        code.jump_absolute(self._hook_back_va)
        return code.build()

    def _build_ui_dispatch_bridge(self, *, wrapper_va: int, adapter_slot_va: int) -> bytes:
        """Tail-dispatch UI traversal through an optional coordinate adapter.

        The patched call site has already pushed its POINT and placed the UI
        dispatcher in ECX. A tail jump preserves that native thiscall frame.
        The adapter receives the original traversal address in EAX, allowing
        one implementation to wrap it transactionally; a zero slot jumps to
        the byte-for-byte native traversal.
        """
        code = X86Emitter(base_va=wrapper_va)
        code += b"\x8b\x15" + struct.pack("<I", adapter_slot_va)
        code += b"\x85\xd2"
        code.jump_if(Condition.EQUAL, "native")
        code += b"\xb8" + struct.pack("<I", self.profile.address("mouse_move.ui_dispatch"))
        code += b"\xff\xe2"
        code.label("native")
        code.jump_absolute(self.profile.address("mouse_move.ui_dispatch"))
        return code.build()

    def _build_interactive_point_helper(
        self,
        *,
        wrapper_va: int,
        adapter_slot_va: int,
    ) -> bytes:
        """Keep the interactive target's retained point in physical space.

        The common traversal legitimately receives a temporary logical POINT
        for fixed-interface hit testing. FUN_00525399 also retains that POINT
        beyond the call, and later right-click construction reuses it as a
        physical toolbar center. Reproduce the native writes first, preserve
        their comparison flags, and only while the optional adapter is active
        replace the cache from MouseManager's durable physical position.
        """
        code = X86Emitter(base_va=wrapper_va)
        # Reproduce the displaced POINT load, active-branch comparison, and
        # two native retained-coordinate writes exactly.
        code += b"\x8b\x44\x24\x0c\x38\x9e\xac\x01\x00\x00\x9c"
        code += b"\x8b\x08\x89\x8e\xa0\x01\x00\x00"
        code += b"\x8b\x40\x04\x89\x86\xa4\x01\x00\x00"
        code += b"\x83\x3d" + struct.pack("<I", adapter_slot_va) + b"\x00"
        code.jump_if(Condition.EQUAL, "done")
        code += b"\x8b\x0d" + struct.pack("<I", self._mouse_manager_global_va)
        code += b"\x85\xc9"
        code.jump_if(Condition.EQUAL, "done")
        code += b"\x8b\x81\x24\x05\x00\x00\x89\x86\xa0\x01\x00\x00"
        code += b"\x8b\x81\x28\x05\x00\x00\x89\x86\xa4\x01\x00\x00"
        code.label("done")
        code += b"\x9d"
        code.jump_absolute(self.profile.address("mouse_move.interactive_point_cache_continue"))
        return code.build()

    def _build_nested_wrapper(self, *, nested_dropped_count_va: int) -> bytes:
        """Validate and reproduce FUN_00525399's conditional slot +0xB4 call."""
        code = X86Emitter(base_va=0)
        code += b"\x85\xc0"  # test incoming vtable in EAX
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x8b\x90\xb4\x00\x00\x00\x85\xd2"
        code.jump_if(Condition.EQUAL, "dropped")

        # Preserve one coherent object/vtable/method snapshot across the API
        # call, then recheck it with no further calls before dispatch.
        code += b"\x51\x50\x52\x52\xff\x15" + struct.pack("<I", self._is_bad_code_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "cleanup")
        code += b"\x8b\x4c\x24\x08\x8b\x01\x3b\x44\x24\x04"
        code.jump_if(Condition.NOT_EQUAL, "cleanup")
        code += b"\x8b\x90\xb4\x00\x00\x00\x3b\x14\x24"
        code.jump_if(Condition.NOT_EQUAL, "cleanup")
        code += b"\x83\xc4\x08\x59\xff\xd2\xc3"

        code.label("cleanup")
        # Only branches after the three snapshot pushes need cleanup.  The
        # first two null branches precede those pushes and target the counter
        # directly; resolve them separately below.
        code += b"\x83\xc4\x0c"
        code.label("dropped")
        code += b"\xff\x05" + struct.pack("<I", nested_dropped_count_va)
        code.ret()
        return code.build()

    def _build_tree_callback_wrapper(
        self,
        *,
        slot_offset: int,
        argument_bytes: int,
        tree_dropped_count_va: int,
        trace_va: int | None = None,
    ) -> bytes:
        """Safely reproduce one pre-dispatch child virtual callback.

        EAX is the vtable and ECX is its object at every patched call site.
        The one-argument hit-test methods originally consume the caller's
        existing POINT argument.  The wrapper passes a copy to the real method
        and then uses ``RET 4`` to consume the original exactly once.
        """
        code = X86Emitter(base_va=0)
        code += b"\x85\xc9"  # null object
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x85\xc0"  # null vtable
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x3d" + struct.pack("<I", self._freed_object_marker)
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x51\x50"
        code += b"\x68" + struct.pack("<I", slot_offset + 4)
        code += b"\x50\xff\x15" + struct.pack("<I", self._is_bad_read_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "vtable_invalid")
        code += b"\x8b\x04\x24\x8b\x4c\x24\x04"
        code += b"\x8b\x90" + struct.pack("<I", slot_offset) + b"\x85\xd2"
        code.jump_if(Condition.EQUAL, "vtable_invalid")

        # A retired heap object can retain a readable vtable whose callback
        # cell contains a small non-zero replacement value. Validate one
        # coherent object/vtable/method snapshot before the indirect call;
        # null checks alone do not reject values such as 0x00000002.
        code += b"\x52\x52\xff\x15" + struct.pack("<I", self._is_bad_code_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "snapshot_invalid")
        code += b"\x8b\x4c\x24\x08\x8b\x01\x3b\x44\x24\x04"
        code.jump_if(Condition.NOT_EQUAL, "snapshot_invalid")
        code += b"\x8b\x90" + struct.pack("<I", slot_offset) + b"\x3b\x14\x24"
        code.jump_if(Condition.NOT_EQUAL, "snapshot_invalid")
        code += b"\x83\xc4\x08\x59"

        # No API call or mutable global access separates this final method
        # load from dispatch. Forward the caller's POINT when this is one of
        # the +B8/+BC hit-test callbacks; +B4 takes no arguments. Coordinate
        # adaptation already brackets their common FUN_004BEBF0 owner.
        if argument_bytes and trace_va is not None:
            # Snapshot the exact receiver and POINT values before entering the
            # stock method. The callee consumes only the copied POINT pointer;
            # our three stack words survive so its return value can be paired
            # with the same call rather than with mutable, later UI state.
            code += b"\x51"  # exact receiver
            code += b"\x8b\x44\x24\x08"  # original POINT*
            code += b"\xff\x70\x04\xff\x30"  # y, then x
            code += b"\xff\x74\x24\x10\xff\xd2"  # copied POINT*; call method
            code += b"\xff\x05" + struct.pack("<I", trace_va)
            code += b"\xa3" + struct.pack("<I", trace_va + 0x10)
            code += b"\x5a\x89\x15" + struct.pack("<I", trace_va + 0x08)
            code += b"\x5a\x89\x15" + struct.pack("<I", trace_va + 0x0C)
            code += b"\x59\x89\x0d" + struct.pack("<I", trace_va + 0x04)
            code += b"\x85\xc0"
            code.jump_if(Condition.EQUAL, "returned")
            code += b"\xff\x05" + struct.pack("<I", trace_va + 0x14)
            for source_offset, destination_offset in (
                (0x04, 0x18),
                (0x08, 0x1C),
                (0x0C, 0x20),
                (0x10, 0x24),
            ):
                code += b"\x8b\x15" + struct.pack("<I", trace_va + source_offset)
                code += b"\x89\x15" + struct.pack("<I", trace_va + destination_offset)
            code.label("returned")
        else:
            if argument_bytes:
                code += b"\xff\x74\x24\x04"
            code += b"\xff\xd2"
        code += b"\xc2" + struct.pack("<H", argument_bytes) if argument_bytes else b"\xc3"

        code.label("snapshot_invalid")
        code += b"\x83\xc4\x0c"
        code.jump("dropped")

        code.label("vtable_invalid")
        code += b"\x83\xc4\x08"

        code.label("dropped")
        code += b"\xff\x05" + struct.pack("<I", tree_dropped_count_va)
        code += b"\x33\xc0"  # no hit / no callback result
        code += b"\xc2" + struct.pack("<H", argument_bytes) if argument_bytes else b"\xc3"
        return code.build()

    def _build_popup_message_wrapper(
        self,
        *,
        dropped_count_va: int,
    ) -> bytes:
        """Guard the transient popup's one-argument message callback.

        ``FUN_004BEC27`` reads the popup object at manager ``+0x20`` before
        reaching the patched sequence. The wrapper revalidates its vtable and
        slot ``+0x0C`` callback, then reconstructs the displaced pointer to the
        caller's message argument. A stale event has no handled result.
        """
        code = X86Emitter(base_va=0)
        # The hook replaces the complete displaced sequence, including its
        # leading ``mov eax,[ecx]``. Validate the receiver first and only then
        # load its vtable; EAX on entry belongs to earlier caller work and is
        # not an object-identity witness. Treating it as the vtable rejected
        # every valid message and prevented scripted transitions such as
        # Grace opening SIDNEY after sitting at the laptop.
        code += b"\x51\x6a\x04\x51\xff\x15" + struct.pack("<I", self._is_bad_read_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "object_invalid")
        code += b"\x8b\x0c\x24\x8b\x01\x50\x6a\x10\x50\xff\x15"
        code += struct.pack("<I", self._is_bad_read_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "snapshot_invalid")
        code += b"\x8b\x04\x24\x8b\x4c\x24\x04"
        code += b"\x8b\x50\x0c\x85\xd2"
        code.jump_if(Condition.EQUAL, "snapshot_invalid")
        code += b"\x52\xff\x15" + struct.pack("<I", self._is_bad_code_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "snapshot_invalid")
        code += b"\x8b\x4c\x24\x04\x8b\x01\x3b\x04\x24"
        code.jump_if(Condition.NOT_EQUAL, "snapshot_invalid")
        code += b"\x8b\x50\x0c\x83\xc4\x08"
        code += b"\x8d\x45\x08\x50\xff\xd2\xc3"

        code.label("snapshot_invalid")
        code += b"\x83\xc4\x08"
        code.jump("dropped")
        code.label("object_invalid")
        code += b"\x83\xc4\x04"
        code.label("dropped")
        code += b"\xff\x05" + struct.pack("<I", dropped_count_va)
        code += b"\x33\xc0\xc3"
        return code.build()

    def _build_popup_query_wrapper(
        self,
        *,
        dropped_count_va: int,
    ) -> bytes:
        """Guard the transient popup's no-argument capture query at slot +0x60."""
        code = X86Emitter(base_va=0)
        # The displaced sequence begins with ``mov eax,[ecx]``. The caller has
        # just read object+4, so preserve that exact receiver and validate its
        # vtable through the queried slot before reproducing the native call.
        code += b"\x8b\x01\x51\x50\x68\x64\x00\x00\x00\x50\xff\x15"
        code += struct.pack("<I", self._is_bad_read_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "invalid")
        code += b"\x8b\x04\x24\x8b\x50\x60\x85\xd2"
        code.jump_if(Condition.EQUAL, "invalid")
        code += b"\x52\xff\x15" + struct.pack("<I", self._is_bad_code_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "invalid")
        code += b"\x8b\x4c\x24\x04\x8b\x01\x3b\x04\x24"
        code.jump_if(Condition.NOT_EQUAL, "invalid")
        code += b"\x8b\x50\x60\x83\xc4\x08\xff\xd2\xc3"

        code.label("invalid")
        code += b"\x83\xc4\x08"
        code += b"\xff\x05" + struct.pack("<I", dropped_count_va)
        # A published popup owns the event even while its callback is being
        # retired. Returning false would make FUN_004BEE27 descend into lower
        # roots whose pointers are deliberately absent during that teardown.
        code += b"\x6a\x01\x58\xc3"
        return code.build()

    def _build_direct_message_wrapper(self, *, dropped_count_va: int) -> bytes:
        """Validate a direct root before invoking its one-argument slot +0x0C."""
        code = X86Emitter(base_va=0)
        code += b"\x85\xc9"
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x51\x6a\x04\x51\xff\x15" + struct.pack("<I", self._is_bad_read_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "object_invalid")
        code += b"\x8b\x0c\x24\x8b\x01\x50\x6a\x10\x50\xff\x15"
        code += struct.pack("<I", self._is_bad_read_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "snapshot_invalid")
        code += b"\x8b\x04\x24\x8b\x50\x0c\x85\xd2"
        code.jump_if(Condition.EQUAL, "snapshot_invalid")
        code += b"\x52\xff\x15" + struct.pack("<I", self._is_bad_code_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "snapshot_invalid")
        code += b"\x8b\x4c\x24\x04\x8b\x01\x3b\x04\x24"
        code.jump_if(Condition.NOT_EQUAL, "snapshot_invalid")
        code += b"\x8b\x50\x0c\x83\xc4\x08"
        code += b"\xff\x74\x24\x04\xff\xd2\xc2\x04\x00"

        code.label("snapshot_invalid")
        code += b"\x83\xc4\x08"
        code.jump("dropped")
        code.label("object_invalid")
        code += b"\x83\xc4\x04"
        code.label("dropped")
        code += b"\xff\x05" + struct.pack("<I", dropped_count_va)
        code += b"\x33\xc0\xc2\x04\x00"
        return code.build()

    def _build_selected_message_wrapper(
        self,
        *,
        wrapper_va: int,
        direct_wrapper_va: int,
        dropped_count_va: int,
    ) -> bytes:
        """Validate the selected-entry indirection, then reuse direct dispatch."""
        code = X86Emitter(base_va=wrapper_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x50\x6a\x04\x50\xff\x15" + struct.pack("<I", self._is_bad_read_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "entry_invalid")
        code += b"\x8b\x04\x24\x8b\x08\x83\xc4\x04"
        code.jump_absolute(direct_wrapper_va)

        code.label("entry_invalid")
        code += b"\x83\xc4\x04"
        code.label("dropped")
        code += b"\xff\x05" + struct.pack("<I", dropped_count_va)
        code += b"\x33\xc0\xc2\x04\x00"
        return code.build()

    def _tree_wrapper_va(self, section_va: int, slot_offset: int) -> int:
        return (
            section_va
            + {
                0xB8: self._off_tree_b8_wrapper,
                0xBC: self._off_tree_bc_wrapper,
                0xB4: self._off_tree_b4_wrapper,
            }[slot_offset]
        )

    def _build_wndproc_wrapper(
        self,
        *,
        wndproc_dropped_count_va: int,
        obsolete_wndproc_point_count_va: int,
        ui_dispatch_adapter_slot_va: int,
        wndproc_exception_count_va: int,
        last_projection_width_va: int,
        last_current_layer_vtable_va: int,
        last_event_target_vtable_va: int,
        last_current_layer_va: int,
        exception_projection_width_va: int,
        exception_current_layer_vtable_va: int,
        exception_event_target_vtable_va: int,
        exception_current_layer_va: int,
        exception_handler_va: int,
    ) -> tuple[bytes, int]:
        """Validate the global manager before reproducing its slot +0x58 call."""
        wrapper_va = self._wndproc_wrapper_va_from_counter(wndproc_dropped_count_va)
        code = X86Emitter(base_va=wrapper_va)
        # The POINT pointer pushed by the original WndProc is already below
        # our stack.  Keep fixed object/method snapshot slots above it so every
        # rejected path can discard all twelve bytes with one cleanup.
        code += b"\x51\x6a\x00"  # saved manager, initially-null saved method
        code += b"\x85\xc9"
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x6a\x04\x51\xff\x15" + struct.pack("<I", self._is_bad_read_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "dropped")

        # A freed heap block can remain committed, so separately validate the
        # replacement first word and the vtable span containing slot +0x58.
        code += b"\x8b\x4c\x24\x04\x8b\x01\x85\xc0"
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x6a\x5c\x50\xff\x15" + struct.pack("<I", self._is_bad_read_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "dropped")
        code += b"\x8b\x4c\x24\x04\x8b\x01\x8b\x50\x58\x85\xd2"
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x89\x14\x24\x52\xff\x15" + struct.pack("<I", self._is_bad_code_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "dropped")

        # Windows can queue several WM_MOUSEMOVE messages while a retained
        # DirectDraw page is being presented.  Once the fixed-interface input
        # adapter is installed, forwarding an intermediate point can commit an
        # obsolete cursor position after a newer point has already been drawn
        # on another page.  Compare the queued client point with USER32's live
        # cursor position before any native cursor state is mutated.
        #
        # The original POINT is WndProc's stack local.  Save both words while
        # GetCursorPos/ScreenToClient use that same storage as scratch, then
        # restore it on every path.  This keeps valid native dispatch byte-for-
        # byte equivalent and leaves the caller's frame pristine on rejection.
        code += b"\x83\x3d" + struct.pack("<I", ui_dispatch_adapter_slot_va) + b"\x00"
        code.jump_if(Condition.EQUAL, "point_is_current")
        code += b"\x8b\x44\x24\x08"  # original POINT*
        code += b"\xff\x30\xff\x70\x04"  # save x, then y
        code += b"\x8b\x44\x24\x10\x50"
        code += b"\xff\x15" + struct.pack("<I", self._get_cursor_pos_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.EQUAL, "accept_queried_point")
        code += b"\x8b\x44\x24\x10\x50"
        code += b"\xff\x75\x08"  # WndProc HWND
        code += b"\xff\x15" + struct.pack("<I", self._screen_to_client_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.EQUAL, "accept_queried_point")
        code += b"\x8b\x44\x24\x10\x8b\x08\x3b\x4c\x24\x04"
        code.jump_if(Condition.NOT_EQUAL, "reject_queried_point")
        code += b"\x8b\x48\x04\x3b\x0c\x24"
        code.jump_if(Condition.NOT_EQUAL, "reject_queried_point")
        code.label("accept_queried_point")
        code += b"\x33\xd2"  # keep the event
        code.jump("restore_queried_point")
        code.label("reject_queried_point")
        code += b"\x6a\x01\x5a"  # drop the obsolete event
        code.label("restore_queried_point")
        code += b"\x8b\x44\x24\x10"
        code += b"\x8b\x4c\x24\x04\x89\x08"
        code += b"\x8b\x0c\x24\x89\x48\x04"
        code += b"\x83\xc4\x08\x85\xd2"
        code.jump_if(Condition.EQUAL, "point_is_current")
        code += b"\xff\x05" + struct.pack("<I", obsolete_wndproc_point_count_va)
        code.jump("dropped")
        code.label("point_is_current")

        # The native 0x0049AA00 pointer-move method does significant cursor
        # bookkeeping before it reaches FUN_004BEBF0.  The repeated fatal
        # signature shows its ownership chain already contains a freed target
        # at entry (ESI=dispatcher, ECX=target, EAX=freed vtable, [EAX+50]=0).
        # Validate that exact chain here, before native code has a chance to
        # dereference any of it.  The inner hook remains useful as a final
        # boundary if the active target is legitimately replaced later.
        code += b"\xa1" + struct.pack("<I", self._engine_loop_global_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x68" + struct.pack("<I", self._scene_owner_offset + 4)
        code += b"\x50\xff\x15" + struct.pack("<I", self._is_bad_read_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "dropped")
        code += b"\xa1" + struct.pack("<I", self._engine_loop_global_va)
        code += b"\x8b\x80" + struct.pack("<I", self._scene_owner_offset)
        code += b"\x85\xc0"
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x6a" + bytes([self._scene_dispatcher_offset + 4])
        code += b"\x50\xff\x15" + struct.pack("<I", self._is_bad_read_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "dropped")
        code += b"\xa1" + struct.pack("<I", self._engine_loop_global_va)
        code += b"\x8b\x80" + struct.pack("<I", self._scene_owner_offset)
        code += b"\x8b\x40" + bytes([self._scene_dispatcher_offset])
        code += b"\x85\xc0"
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x6a" + bytes([self._event_target_offset + 4])
        code += b"\x50\xff\x15" + struct.pack("<I", self._is_bad_read_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "dropped")
        code += b"\xa1" + struct.pack("<I", self._engine_loop_global_va)
        code += b"\x8b\x80" + struct.pack("<I", self._scene_owner_offset)
        code += b"\x8b\x40" + bytes([self._scene_dispatcher_offset])
        code += b"\x8b\x40" + bytes([self._event_target_offset])
        code += b"\x85\xc0"
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x6a\x04\x50\xff\x15" + struct.pack("<I", self._is_bad_read_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "dropped")
        code += b"\xa1" + struct.pack("<I", self._engine_loop_global_va)
        code += b"\x8b\x80" + struct.pack("<I", self._scene_owner_offset)
        code += b"\x8b\x40" + bytes([self._scene_dispatcher_offset])
        code += b"\x8b\x40" + bytes([self._event_target_offset])
        code += b"\x8b\x00\xa3" + struct.pack("<I", last_event_target_vtable_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x6a\x54\x50\xff\x15" + struct.pack("<I", self._is_bad_read_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "dropped")
        code += b"\xa1" + struct.pack("<I", self._engine_loop_global_va)
        code += b"\x8b\x80" + struct.pack("<I", self._scene_owner_offset)
        code += b"\x8b\x40" + bytes([self._scene_dispatcher_offset])
        code += b"\x8b\x40" + bytes([self._event_target_offset])
        code += b"\x8b\x00\x8b\x50\x50\x85\xd2"
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x52\xff\x15" + struct.pack("<I", self._is_bad_code_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "dropped")

        # RoomLayer is published before its 3D scene and nested input tree are
        # ready. A display-mode transition can deliver WM_MOUSEMOVE in that
        # construction interval: every retained pointer above is readable and
        # executable, but the native callback later traverses partial children
        # and raises an access violation. Catching that exception after native
        # code has mutated state leaves Restore reporting "Unknown error".
        #
        # GK3 resets its projection width to zero for a new room and publishes
        # it at the first valid 3D frame. Drop only movement owned by the
        # concrete RoomLayer while that engine-owned readiness value is zero.
        # Title, Restore, and other 2D layers keep their native hover path.
        code += b"\xa1" + struct.pack("<I", self.profile.address("input.projection_dimensions"))
        code += b"\xa3" + struct.pack("<I", last_projection_width_va)
        code += b"\xc7\x05" + struct.pack("<I", last_current_layer_vtable_va)
        code += b"\x00\x00\x00\x00"
        code += b"\xc7\x05" + struct.pack("<I", last_current_layer_va)
        code += b"\x00\x00\x00\x00"
        # Resolve the layer through GK3's own helper instead of mirroring its
        # ownership graph here.  The helper first consults the explicit
        # ``+0x58`` current-layer field, then falls back to the final entry in
        # the layer stack. A missing layer is a publication gap, not a valid
        # 2D owner: reject that queued movement before native traversal can
        # mutate the surrounding Restore/load transaction.
        code.call_absolute(self.profile.address("ui.current_layer"))
        code += b"\x85\xc0"
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x6a\x04\x50\xff\x15" + struct.pack("<I", self._is_bad_read_ptr_iat_va)
        code += b"\x85\xc0"
        code.jump_if(Condition.NOT_EQUAL, "dropped")
        # Win32 APIs may clobber EAX. Resolve again rather than retaining a
        # raw layer pointer across the validation call; both observations
        # remain owned by the game's native stack/fallback semantics.
        code.call_absolute(self.profile.address("ui.current_layer"))
        code += b"\x85\xc0"
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\xa3" + struct.pack("<I", last_current_layer_va)
        code += b"\x8b\x08\x89\x0d" + struct.pack("<I", last_current_layer_vtable_va)
        # Once 3D projection is live, any concrete current layer owns native
        # movement. During zero-projection publication, only RoomLayer and the
        # startup splash are known partial graphs; other concrete 2D layers
        # retain their native hover path.
        code += b"\x83\x3d" + struct.pack("<I", last_projection_width_va) + b"\x00"
        code.jump_if(Condition.NOT_EQUAL, "input_ready")
        code += b"\x81\xf9" + struct.pack(
            "<I", self.profile.address("transition.room_layer_vtable")
        )
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x81\xf9" + struct.pack(
            "<I", self.profile.address("transition.startup_splash_layer_vtable")
        )
        code.jump_if(Condition.EQUAL, "dropped")
        code.label("input_ready")

        # Recheck the global owner, vtable, and method without another API
        # call.  This prevents validation of one heap generation followed by
        # dispatch through another if the retained address was recycled.
        code += b"\x8b\x4c\x24\x04\x3b\x0d" + struct.pack("<I", self._mouse_manager_global_va)
        code.jump_if(Condition.NOT_EQUAL, "dropped")
        code += b"\x8b\x01\x85\xc0"
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x3d" + struct.pack("<I", self._freed_object_marker)
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x8b\x50\x58\x85\xd2"
        code.jump_if(Condition.EQUAL, "dropped")
        code += b"\x3b\x14\x24"
        code.jump_if(Condition.NOT_EQUAL, "dropped")

        # Discard the saved method and restore ECX to the validated manager.
        # The retained POINT is copied below because the two-word x86 SEH
        # registration record must sit between it and the native call.
        code += b"\x83\xc4\x04\x59"

        # Register a tiny frame-based exception handler around only this
        # WM_MOUSEMOVE method.  The method and its pre-dispatch tree walk use
        # several retained raw pointers; if one is freed after validation, the
        # handler resumes at ``exception_recovery`` and drops this move.  It
        # ignores non-access-violation exceptions, allowing GK3's normal fatal
        # reporting to retain ownership of unrelated failures.
        code += b"\x68" + struct.pack("<I", exception_handler_va)
        code += b"\x64\xff\x35\x00\x00\x00\x00"  # push dword ptr fs:[0]
        code += b"\x64\x89\x25\x00\x00\x00\x00"  # mov fs:[0],esp
        code += b"\xff\x74\x24\x08"  # copy original POINT below the registration
        code += b"\xff\xd2"

        # The native thiscall consumed the POINT copy.  Restore the previous
        # exception registration, then discard [prev, handler, original POINT].
        code += b"\x8b\x04\x24\x64\xa3\x00\x00\x00\x00\x83\xc4\x0c"
        code.jump_absolute(self._wndproc_hook_back_va)

        exception_recovery = code.offset
        # The custom handler restores ESP to the registration frame before
        # continuing here, so cleanup is identical to the successful path.
        code += b"\x8b\x04\x24\x64\xa3\x00\x00\x00\x00\x83\xc4\x0c"
        for source_va, target_va in (
            (last_projection_width_va, exception_projection_width_va),
            (last_current_layer_vtable_va, exception_current_layer_vtable_va),
            (last_event_target_vtable_va, exception_event_target_vtable_va),
            (last_current_layer_va, exception_current_layer_va),
        ):
            code += b"\xa1" + struct.pack("<I", source_va)
            code += b"\xa3" + struct.pack("<I", target_va)
        code += b"\xff\x05" + struct.pack("<I", wndproc_exception_count_va)
        code.jump_absolute(self._wndproc_hook_back_va)

        code.label("dropped")
        code += b"\x83\xc4\x0c"  # saved method, manager, and original POINT argument
        code += b"\xff\x05" + struct.pack("<I", wndproc_dropped_count_va)
        code.jump_absolute(self._wndproc_hook_back_va)
        # Return the recovery offset beside the payload.  Keeping it in this
        # immutable build result avoids hidden compiler state: verification
        # remains deterministic even when callers reuse a compiler instance.
        return code.build(), exception_recovery

    def _build_wndproc_exception_handler(
        self,
        *,
        recovery_va: int,
        exception_eip_va: int,
        exception_address_va: int,
        exception_access_address_va: int,
        exception_registers_va: int,
        exception_stack_va: int,
    ) -> bytes:
        """Resume after an access violation raised inside one mouse move.

        Windows invokes an x86 registration handler as
        ``handler(ExceptionRecord, EstablisherFrame, Context, Dispatcher)``.
        Updating EIP/ESP in ``CONTEXT`` and returning
        ``ExceptionContinueExecution`` (0) requests continuation at our cleanup
        label.  Any other exception returns ``ExceptionContinueSearch`` (1).

        Those values are deliberately different from a vectored exception
        handler's ``EXCEPTION_CONTINUE_EXECUTION`` (-1) and
        ``EXCEPTION_CONTINUE_SEARCH`` (0).  Mixing the two ABIs was the source
        of the intermittent STATUS_INVALID_DISPOSITION fatal during Restore.
        """
        code = X86Emitter(base_va=0)
        code += b"\x8b\x44\x24\x04"  # ExceptionRecord*
        code += b"\x81\x38\x05\x00\x00\xc0"  # EXCEPTION_ACCESS_VIOLATION
        code.jump_if(Condition.NOT_EQUAL, "search")
        # Retain the exact failing instruction and accessed address before
        # rewriting CONTEXT.Eip. These are diagnostics only: they make an
        # otherwise swallowed transient move fault attributable to one native
        # or injected instruction without changing the recovery policy.
        code += b"\x8b\x48\x0c\x89\x0d" + struct.pack("<I", exception_address_va)
        code += b"\x8b\x48\x18\x89\x0d" + struct.pack("<I", exception_access_address_va)
        code += b"\x8b\x44\x24\x0c"  # CONTEXT*
        code += b"\x8b\x88\xb8\x00\x00\x00\x89\x0d" + struct.pack("<I", exception_eip_va)
        # CONTEXT.Eax..Edi and Ebp identify the invalid ownership edge. Keep
        # them in a fixed order documented by the capture probe, followed by
        # CONTEXT.Esp and its first four return-stack words.
        for index, context_offset in enumerate((0xB0, 0xAC, 0xA8, 0xA4, 0xA0, 0x9C, 0xB4, 0xC4)):
            code += b"\x8b\x88" + struct.pack("<I", context_offset)
            code += b"\x89\x0d" + struct.pack("<I", exception_registers_va + index * 4)
        code += b"\x8b\x90\xc4\x00\x00\x00"
        for index in range(4):
            code += b"\x8b\x4a" + bytes([index * 4])
            code += b"\x89\x0d" + struct.pack("<I", exception_stack_va + index * 4)
        code += b"\xc7\x80\xb8\x00\x00\x00" + struct.pack("<I", recovery_va)
        code += b"\x8b\x4c\x24\x08"  # EstablisherFrame / saved registration ESP
        code += b"\x89\x88\xc4\x00\x00\x00"
        code += b"\x33\xc0\xc3"  # ExceptionContinueExecution
        code.label("search")
        code += b"\x6a\x01\x58\xc3"  # ExceptionContinueSearch
        return code.build()

    def _wndproc_wrapper_va_from_counter(self, counter_va: int) -> int:
        return counter_va - self._off_wndproc_dropped_count + self._off_wndproc_wrapper

    def _build_payloads(
        self,
        section_va: int,
    ) -> tuple[tuple[int, bytes, int, str], ...]:
        """Generate every immutable helper with its exclusive ABI boundary."""
        wndproc_wrapper_va = section_va + self._off_wndproc_wrapper
        exception_handler_va = section_va + self._off_wndproc_exception_handler
        wndproc_wrapper, exception_recovery = self._build_wndproc_wrapper(
            wndproc_dropped_count_va=section_va + self._off_wndproc_dropped_count,
            obsolete_wndproc_point_count_va=(section_va + self._off_obsolete_wndproc_point_count),
            ui_dispatch_adapter_slot_va=section_va + self._off_ui_dispatch_adapter,
            wndproc_exception_count_va=section_va + self._off_wndproc_exception_count,
            last_projection_width_va=section_va + self._off_last_projection_width,
            last_current_layer_vtable_va=section_va + self._off_last_current_layer_vtable,
            last_event_target_vtable_va=section_va + self._off_last_event_target_vtable,
            last_current_layer_va=section_va + self._off_last_current_layer,
            exception_projection_width_va=section_va + self._off_exception_projection_width,
            exception_current_layer_vtable_va=section_va + self._off_exception_current_layer_vtable,
            exception_event_target_vtable_va=section_va + self._off_exception_event_target_vtable,
            exception_current_layer_va=section_va + self._off_exception_current_layer,
            exception_handler_va=exception_handler_va,
        )
        tree_dropped_count_va = section_va + self._off_tree_dropped_count
        return (
            (
                self._off_wrapper,
                self._build_wrapper(
                    wrapper_va=section_va + self._off_wrapper,
                    dropped_count_va=section_va + self._off_dropped_count,
                ),
                self._off_ui_dispatch_bridge,
                "target wrapper",
            ),
            (
                self._off_ui_dispatch_bridge,
                self._build_ui_dispatch_bridge(
                    wrapper_va=section_va + self._off_ui_dispatch_bridge,
                    adapter_slot_va=section_va + self._off_ui_dispatch_adapter,
                ),
                self._off_ui_dispatch_adapter,
                "UI-dispatch bridge",
            ),
            (
                self._off_nested_wrapper,
                self._build_nested_wrapper(
                    nested_dropped_count_va=section_va + self._off_nested_dropped_count,
                ),
                self._off_wndproc_wrapper,
                "nested wrapper",
            ),
            (
                self._off_wndproc_wrapper,
                wndproc_wrapper,
                self._off_tree_b8_wrapper,
                "WndProc wrapper",
            ),
            (
                self._off_tree_b8_wrapper,
                self._build_tree_callback_wrapper(
                    slot_offset=0xB8,
                    argument_bytes=4,
                    tree_dropped_count_va=tree_dropped_count_va,
                    trace_va=section_va + self._off_tree_b8_trace,
                ),
                self._off_tree_bc_wrapper,
                "tree +0xB8 wrapper",
            ),
            (
                self._off_tree_bc_wrapper,
                self._build_tree_callback_wrapper(
                    slot_offset=0xBC,
                    argument_bytes=4,
                    tree_dropped_count_va=tree_dropped_count_va,
                    trace_va=section_va + self._off_tree_bc_trace,
                ),
                self._off_tree_b4_wrapper,
                "tree +0xBC wrapper",
            ),
            (
                self._off_tree_b4_wrapper,
                self._build_tree_callback_wrapper(
                    slot_offset=0xB4,
                    argument_bytes=0,
                    tree_dropped_count_va=tree_dropped_count_va,
                ),
                self._off_wndproc_exception_handler,
                "tree +0xB4 wrapper",
            ),
            (
                self._off_wndproc_exception_handler,
                self._build_wndproc_exception_handler(
                    recovery_va=wndproc_wrapper_va + exception_recovery,
                    exception_eip_va=section_va + self._off_exception_eip,
                    exception_address_va=section_va + self._off_exception_address,
                    exception_access_address_va=section_va + self._off_exception_access_address,
                    exception_registers_va=section_va + self._off_exception_registers,
                    exception_stack_va=section_va + self._off_exception_stack,
                ),
                self._off_interactive_point_helper,
                "WndProc exception handler",
            ),
            (
                self._off_interactive_point_helper,
                self._build_interactive_point_helper(
                    wrapper_va=section_va + self._off_interactive_point_helper,
                    adapter_slot_va=section_va + self._off_ui_dispatch_adapter,
                ),
                self._off_popup_message_wrapper,
                "interactive point-cache helper",
            ),
            (
                self._off_popup_message_wrapper,
                self._build_popup_message_wrapper(
                    dropped_count_va=section_va + self._off_popup_message_dropped_count,
                ),
                self._off_direct_message_wrapper,
                "popup message wrapper",
            ),
            (
                self._off_popup_query_wrapper,
                self._build_popup_query_wrapper(
                    dropped_count_va=section_va + self._off_popup_query_dropped_count,
                ),
                self._off_popup_query_dropped_count,
                "popup query wrapper",
            ),
            (
                self._off_direct_message_wrapper,
                self._build_direct_message_wrapper(
                    dropped_count_va=section_va + self._off_direct_message_dropped_count,
                ),
                self._off_selected_message_wrapper,
                "direct message wrapper",
            ),
            (
                self._off_selected_message_wrapper,
                self._build_selected_message_wrapper(
                    wrapper_va=section_va + self._off_selected_message_wrapper,
                    direct_wrapper_va=section_va + self._off_direct_message_wrapper,
                    dropped_count_va=section_va + self._off_selected_message_dropped_count,
                ),
                self._off_direct_message_dropped_count,
                "selected message wrapper",
            ),
        )

    def _validate_payload_slots(self, payloads: tuple[tuple[int, bytes, int, str], ...]) -> None:
        """Reject generated helpers that escape or overlap their stable ABI slots."""
        for offset, payload, limit, label in payloads:
            if not (0 <= offset < limit <= self._section_size):
                msg = f"{self.id} {label} has an invalid section slot"
                raise PatchError(msg)
            if offset + len(payload) > limit:
                msg = f"{self.id} {label} exceeds its section slot"
                raise PatchError(msg)

    def _build_payload(self, *, section_va: int) -> bytes:
        """Build the complete mouse-guard section as one bounded image."""
        payloads = self._build_payloads(section_va)
        self._validate_payload_slots(payloads)
        section = SegmentPayloadBuilder(
            owner=self.id,
            segment=self._section_name,
            size=self._section_size,
        )
        section.place(label="magic", offset=0, payload=self._magic)
        section.place(
            label="layout version",
            offset=self._off_layout_version,
            payload=struct.pack("<I", self._layout_version),
        )
        for offset, payload, limit, label in payloads:
            section.place(label=label, offset=offset, payload=payload, limit=limit)
        return section.build()

    def _mutation_plan(self, *, section_va: int) -> ExecutableMutationPlan:
        """Declare all mouse-dispatch redirects as one atomic transaction."""
        plan = ExecutableMutationPlan(owner=self.id)
        for label, opcode, site_va, original, wrapper_va in (
            (
                "mouse target dispatch",
                BranchOpcode.JUMP,
                self._hook_site_va,
                self._hook_orig,
                section_va + self._off_wrapper,
            ),
            (
                "UI traversal",
                BranchOpcode.CALL,
                self._ui_dispatch_site_va,
                self._ui_dispatch_orig,
                section_va + self._off_ui_dispatch_bridge,
            ),
            (
                "interactive point cache",
                BranchOpcode.JUMP,
                self._interactive_point_site_va,
                self._interactive_point_orig,
                section_va + self._off_interactive_point_helper,
            ),
            (
                "nested mouse dispatch",
                BranchOpcode.CALL,
                self._nested_hook_site_va,
                self._nested_hook_orig,
                section_va + self._off_nested_wrapper,
            ),
            (
                "WndProc mouse dispatch",
                BranchOpcode.JUMP,
                self._wndproc_hook_site_va,
                self._wndproc_hook_orig,
                section_va + self._off_wndproc_wrapper,
            ),
            (
                "popup message dispatch",
                BranchOpcode.CALL,
                self._popup_message_site_va,
                self._popup_message_orig,
                section_va + self._off_popup_message_wrapper,
            ),
            (
                "popup query dispatch",
                BranchOpcode.CALL,
                self._popup_query_site_va,
                self._popup_query_orig,
                section_va + self._off_popup_query_wrapper,
            ),
            (
                "selected message dispatch",
                BranchOpcode.CALL,
                self._selected_message_site_va,
                self._selected_message_orig,
                section_va + self._off_selected_message_wrapper,
            ),
        ):
            plan.branch(
                label=label,
                opcode=opcode,
                site_va=site_va,
                expected=original,
                target_va=wrapper_va,
                size=len(original),
            )
        for index, (site_va, original) in enumerate(self._direct_message_sites, start=1):
            plan.branch(
                label=f"direct message dispatch {index}",
                opcode=BranchOpcode.CALL,
                site_va=site_va,
                expected=original,
                target_va=section_va + self._off_direct_message_wrapper,
                size=len(original),
            )
        for site_va, original, slot_offset, _argument_bytes in self._tree_hook_specs:
            plan.branch(
                label=f"tree callback at 0x{site_va:08X}",
                opcode=BranchOpcode.CALL,
                site_va=site_va,
                expected=original,
                target_va=self._tree_wrapper_va(section_va, slot_offset),
                size=len(original),
            )
        return plan

    def _check_anchors(self, pe: PEFile) -> None:
        for name, label in (
            (self._target_prefix_name, "mouse dispatcher prefix"),
            (self._target_suffix_name, "mouse dispatcher suffix"),
            (self._ui_dispatch_prefix_name, "UI traversal prefix"),
            (self._ui_dispatch_suffix_name, "UI traversal suffix"),
            (self._nested_prefix_name, "nested move-call prefix"),
            (self._nested_suffix_name, "nested move-call suffix"),
            (self._wndproc_prefix_name, "WndProc move-call prefix"),
            (self._wndproc_suffix_name, "WndProc move-call suffix"),
        ):
            site = self.profile.site(name)
            va = site.va
            expected = site.original
            if pe.read_bytes(pe.va_to_offset(va), len(expected)) != expected:
                msg = f"{self.id} precheck failed: unexpected {label}"
                raise PatchError(msg)

    def precheck(self, pe: PEFile) -> None:
        """Validate pristine dispatch sites and semantic anchors."""
        self._check_anchors(pe)
        if pe.get_section(self._section_name) is not None:
            msg = f"{self.id} requires a pristine executable"
            raise PatchError(msg)
        if (
            pe.read_bytes(pe.va_to_offset(self._hook_site_va), len(self._hook_orig))
            != self._hook_orig
        ):
            msg = f"{self.id} precheck failed: unexpected mouse dispatch bytes"
            raise PatchError(msg)
        if (
            pe.read_bytes(pe.va_to_offset(self._ui_dispatch_site_va), len(self._ui_dispatch_orig))
            != self._ui_dispatch_orig
        ):
            msg = f"{self.id} precheck failed: unexpected UI traversal call"
            raise PatchError(msg)
        if (
            pe.read_bytes(
                pe.va_to_offset(self._interactive_point_site_va),
                len(self._interactive_point_orig),
            )
            != self._interactive_point_orig
        ):
            msg = f"{self.id} precheck failed: unexpected interactive point cache"
            raise PatchError(msg)
        if (
            pe.read_bytes(pe.va_to_offset(self._nested_hook_site_va), len(self._nested_hook_orig))
            != self._nested_hook_orig
        ):
            msg = f"{self.id} precheck failed: unexpected nested mouse dispatch bytes"
            raise PatchError(msg)
        if (
            pe.read_bytes(pe.va_to_offset(self._wndproc_hook_site_va), len(self._wndproc_hook_orig))
            != self._wndproc_hook_orig
        ):
            msg = f"{self.id} precheck failed: unexpected WndProc mouse dispatch bytes"
            raise PatchError(msg)
        if (
            pe.read_bytes(
                pe.va_to_offset(self._popup_message_site_va), len(self._popup_message_orig)
            )
            != self._popup_message_orig
        ):
            msg = f"{self.id} precheck failed: unexpected popup message dispatch bytes"
            raise PatchError(msg)
        if (
            pe.read_bytes(pe.va_to_offset(self._popup_query_site_va), len(self._popup_query_orig))
            != self._popup_query_orig
        ):
            msg = f"{self.id} precheck failed: unexpected popup query dispatch bytes"
            raise PatchError(msg)
        for site_va, original in self._direct_message_sites:
            if pe.read_bytes(pe.va_to_offset(site_va), len(original)) != original:
                msg = f"{self.id} precheck failed: unexpected direct message dispatch bytes"
                raise PatchError(msg)
        if (
            pe.read_bytes(
                pe.va_to_offset(self._selected_message_site_va), len(self._selected_message_orig)
            )
            != self._selected_message_orig
        ):
            msg = f"{self.id} precheck failed: unexpected selected message dispatch bytes"
            raise PatchError(msg)
        for site_va, original, _slot, _argument_bytes in self._tree_hook_specs:
            if pe.read_bytes(pe.va_to_offset(site_va), len(original)) != original:
                msg = f"{self.id} precheck failed: unexpected tree callback at 0x{site_va:08X}"
                raise PatchError(msg)

    def input_abi(self, pe: PEFile) -> MouseMoveDispatchABI:
        """Resolve the installed downstream pointer-adapter slot."""
        section = pe.get_section(self._section_name)
        if section is None or section.size_of_raw_data < self._section_size:
            msg = f"{self.id} input ABI requires the installed guard"
            raise PatchError(msg)
        section_offset = section.pointer_to_raw_data
        if pe.read_bytes(section_offset, len(self._magic)) != self._magic:
            msg = f"{self.id} input ABI has invalid section magic"
            raise PatchError(msg)
        if pe.read_bytes(section_offset + self._off_layout_version, 4) != struct.pack(
            "<I", self._layout_version
        ):
            msg = f"{self.id} input ABI has an incompatible layout"
            raise PatchError(msg)
        section_va = pe.rva_to_va(section.virtual_address)
        return MouseMoveDispatchABI(
            ui_dispatch_adapter_slot_va=section_va + self._off_ui_dispatch_adapter,
        )

    def apply(self, pe: PEFile) -> None:
        """Install guarded dispatch wrappers and redirect their call sites."""
        if pe.get_section(self._section_name) is not None:
            msg = f"{self.id} section already exists"
            raise PatchError(msg)
        section = pe.add_section(
            self._section_name, b"\x00" * self._section_size, self._section_characteristics
        )
        if section.size_of_raw_data < self._section_size:
            msg = f"{self.id} apply failed: section too small"
            raise PatchError(msg)
        pe.set_section_characteristics(self._section_name, self._section_characteristics)
        section_va = pe.rva_to_va(section.virtual_address)
        pe.write_bytes(section.pointer_to_raw_data, self._build_payload(section_va=section_va))
        self._mutation_plan(section_va=section_va).apply(pe)

    def postcheck(self, pe: PEFile) -> None:
        """Verify every wrapper, redirect, counter, and layout marker."""
        self._check_anchors(pe)
        section = pe.get_section(self._section_name)
        if section is None or section.size_of_raw_data < self._section_size:
            msg = f"{self.id} postcheck failed: section missing or too small"
            raise PatchError(msg)
        if section.characteristics != self._section_characteristics:
            msg = f"{self.id} postcheck failed: section is not executable"
            raise PatchError(msg)
        section_offset = section.pointer_to_raw_data
        section_va = pe.rva_to_va(section.virtual_address)
        if pe.read_bytes(section_offset, len(self._magic)) != self._magic:
            msg = f"{self.id} postcheck failed: bad section magic"
            raise PatchError(msg)
        version = struct.pack("<I", self._layout_version)
        if pe.read_bytes(section_offset + self._off_layout_version, len(version)) != version:
            msg = f"{self.id} postcheck failed: layout mismatch"
            raise PatchError(msg)
        # Compare only this compiler's immutable regions. The fixed-interface
        # runtime intentionally publishes its adapter into +0x1EC after this
        # dependency installs; zero-filled ABI/state cells are therefore not
        # immutable mouse-guard payload.
        payloads = self._build_payloads(section_va)
        self._validate_payload_slots(payloads)
        for offset, payload, _limit, label in payloads:
            if pe.read_bytes(section_offset + offset, len(payload)) != payload:
                msg = f"{self.id} postcheck failed: {label} mismatch"
                raise PatchError(msg)
        self._mutation_plan(section_va=section_va).verify(pe)
