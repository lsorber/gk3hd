"""Emit fixed-interface pointer dispatch and inverse-affine adapters."""

# These emitters are one physical part of SidneyPresentationCompiler and
# consume its private recovered ABI directly. A copied public configuration
# would add mutable duplication and allow the two ABI views to drift.
# ruff: noqa: SLF001

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.geometry import AUTHORED_FRAME_HEIGHT, AUTHORED_FRAME_WIDTH
from gk3hd.patch.definitions.runtime2d.resource_driving_map import emit_fitted_height

if TYPE_CHECKING:
    from gk3hd.patch.definitions.runtime2d.sidney_presentation import SidneyPresentationCompiler


def build_pointer_motion_dispatch_thunk(
    owner: SidneyPresentationCompiler,
    *,
    wrapper_va: int,
) -> bytes:
    """Call GK3's five-argument motion traversal from a one-POINT adapter.

    ECX points at the stack-local context assembled by
    :func:`build_pointer_motion_dispatch_wrapper`; ``[ESP+4]`` is the current
    POINT after the selected fixed-interface affine. The native dispatcher
    receives that POINT plus the original physical delta, flags, callback, and
    object offset. No context escapes this synchronous call.
    """
    code = X86Emitter(base_va=wrapper_va)
    # Context DWORDs are dispatcher, delta, flags, callback, and object offset.
    code.raw(b"\xff\x71\x10\xff\x71\x0c\xff\x71\x08\xff\x71\x04")
    # Four copied arguments put the adapter-owned POINT at [ESP+0x14].
    code.raw(b"\xff\x74\x24\x14\x8b\x09")
    code.call_absolute(owner.profile.address("mouse_move.motion_dispatch"))
    code.raw(b"\xc2\x04\x00")
    return code.build()


def build_pointer_motion_dispatch_wrapper(
    *,
    wrapper_va: int,
    input_wrapper_va: int,
    thunk_va: int,
    native_dispatch_va: int,
    physical_width_va: int,
    tbt_layer_va: int,
    current_layer_va: int,
    driving_map_active_va: int,
    inventory_active_va: int,
    toolbar_input_valid_va: int,
    system_active_va: int,
    system_transform_mode_va: int,
    toolbar_transform_mode: int,
    reference_canvas_transform_mode: int,
    system_root_ptr_va: int,
    toolbar_vtable_va: int,
    death_vtable_va: int,
    zodiac_vtable_va: int,
    is_bad_read_ptr_va: int,
) -> bytes:
    """Adapt only the current POINT in GK3's second motion traversal.

    The hook replaces MouseManager's call to ``FUN_004BF0E8``. Its five native
    arguments are ``current POINT*``, ``delta POINT*``, flags, callback, and
    child-object offset. A stack-local context preserves the latter four and
    the native dispatcher while the shared one-POINT input owner applies its
    reversible affine to the current point and software-cursor cache.
    """
    code = X86Emitter(base_va=wrapper_va)
    # Dense TimeBlock roots retain physical bitmap-sized model bounds even
    # at 1024x768. Both motion traversals need the same persistent-root inverse
    # as button edges. Compare ownership without dereferencing a retained root.
    code.raw(b"\x83\x3d" + struct.pack("<I", tbt_layer_va) + b"\x00")
    code.jump_short_if(Condition.EQUAL, "reference_size")
    code.raw(b"\x50\x51\x52")
    code.call_absolute(current_layer_va)
    code.raw(b"\x3b\x05" + struct.pack("<I", tbt_layer_va) + b"\x5a\x59\x58")
    code.jump_if(Condition.EQUAL, "adapted")
    code.label("reference_size")
    # Map hit boxes are normalized even at 1024; retain the map's input
    # ownership scope so delayed tooltip resolution cannot inherit toolbar state.
    code.raw(b"\x83\x3d" + struct.pack("<I", driving_map_active_va) + b"\x00")
    code.jump_if(Condition.NOT_EQUAL, "classify")
    # Reference-sized rendering has no affine to invert. Check this before
    # consulting any asynchronously published toolbar state so 1024x768 is a
    # literal native tail call even while a popup is being created or retired.
    code.raw(b"\x81\x3d" + struct.pack("<I", physical_width_va))
    code.raw(struct.pack("<I", AUTHORED_FRAME_WIDTH))
    code.jump_if(Condition.ABOVE, "classify")
    code.raw(b"\x81\x3d" + struct.pack("<I", physical_width_va + 4))
    code.raw(struct.pack("<I", AUTHORED_FRAME_HEIGHT))
    code.jump_if(Condition.BELOW_OR_EQUAL, "native")

    code.label("classify")
    # Death draws each native button through the same fitted-anchor affine
    # as Title. Its trailing motion traversal must not replace the mapped
    # hover result with an untransformed physical hit test. Query the live
    # layer, not a retained Death root beneath Restore/ConfirmQuit.
    code.raw(b"\x50\x51\x52")
    code.call_absolute(current_layer_va)
    code.raw(b"\x85\xc0")
    code.jump_short_if(Condition.NOT_EQUAL, "death_compare")
    code.raw(b"\x40")  # null -> 1: clear ZF without dereferencing the root
    code.jump_short("death_checked")
    code.label("death_compare")
    code.raw(b"\x81\x38" + struct.pack("<I", death_vtable_va))
    code.jump_short_if(Condition.EQUAL, "death_checked")
    # LSR's section hit regions also remain in reference coordinates. Both
    # motion traversals must agree, or the later pass selects the base page
    # instead of the handwritten section under the pointer.
    code.raw(b"\x81\x38" + struct.pack("<I", zodiac_vtable_va))
    code.label("death_checked")
    code.raw(b"\x5a\x59\x58")
    code.jump_if(Condition.EQUAL, "adapted")
    # Pointer motion has a second five-argument traversal after the common
    # event slot. The driving map needs the same horizontal inverse in both;
    # otherwise rectangle hit testing succeeds in one pass but this trailing
    # physical-coordinate pass immediately restores the unlit location.
    code.raw(b"\x83\x3d" + struct.pack("<I", driving_map_active_va) + b"\x00")
    code.jump_if(Condition.NOT_EQUAL, "adapted")

    # Inventory also retains an authored object tree behind its fitted final
    # presentation. Its active-root publication is durable across CloseUp, so
    # require the complete scalar ownership tuple before adapting the trailing
    # hover traversal. Without this second inverse, the earlier traversal finds
    # the item but this pass replaces it with the full-physical room backdrop.
    code.raw(b"\xa1" + struct.pack("<I", inventory_active_va) + b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "toolbar_check")
    code.raw(b"\x83\x3d" + struct.pack("<I", system_active_va) + b"\x00")
    code.jump_if(Condition.EQUAL, "toolbar_check")
    code.raw(b"\x83\x3d" + struct.pack("<I", system_transform_mode_va))
    code.raw(bytes([reference_canvas_transform_mode]))
    code.jump_if(Condition.NOT_EQUAL, "toolbar_check")
    code.raw(b"\x3b\x05" + struct.pack("<I", system_root_ptr_va))
    code.jump_if(Condition.EQUAL, "adapted")

    code.label("toolbar_check")
    # InGameToolbar is the other secondary traversal that needs an inverse.
    # The toolbar renderer publishes this token only after it has produced the
    # exact source/target rectangles consumed by the inverse below. It is the
    # strongest asynchronous ownership boundary and must precede even the
    # generic SystemScreen state, which transient non-toolbar popups also use.
    code.raw(b"\x83\x3d" + struct.pack("<I", toolbar_input_valid_va) + b"\x00")
    code.jump_if(Condition.EQUAL, "native")
    # Confirm the durable scalar ownership state before touching the root
    # pointer. Only a live popup may proceed to the exact-vtable check.
    code.raw(b"\x83\x3d" + struct.pack("<I", system_active_va) + b"\x00")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x83\x3d" + struct.pack("<I", system_transform_mode_va))
    code.raw(bytes([toolbar_transform_mode]))
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(b"\xa1" + struct.pack("<I", system_root_ptr_va) + b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "native")
    # The mode and active flag deliberately outlive short synchronous owner
    # transitions, so validate the four-byte vtable read at this asynchronous
    # mouse boundary. Preserve the native this pointer in ECX; POP retains the
    # flags from TEST for the invalid-pointer branch.
    code.raw(b"\x51\x50\x6a\x04\x50\xff\x15" + struct.pack("<I", is_bad_read_ptr_va))
    code.raw(b"\x85\xc0\x58\x59")
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(b"\x81\x38" + struct.pack("<I", toolbar_vtable_va))
    code.jump_if(Condition.NOT_EQUAL, "native")

    code.jump("adapted")

    code.label("native")
    code.jump_absolute(native_dispatch_va)

    code.label("adapted")
    code.raw(b"\x55\x8b\xec\x83\xec\x20")
    # This hook replaces a native thiscall whose caller keeps EDI as its live
    # current-POINT pointer after return.  Most affine owners already preserve
    # the nonvolatile register set internally, but the identity classifier and
    # future owners are independent implementation details.  Enforce the ABI
    # here at the actual replacement boundary instead of relying on every
    # nested adapter to preserve registers accidentally.
    # Store the nonvolatile registers in fixed frame slots rather than below
    # the mutable stack top. Native pointer dispatch can synchronously enter a
    # window-message callback; restoring with POP would then depend on every
    # nested target returning with precisely the same transient stack depth.
    code.raw(b"\x89\x5d\xe8\x89\x75\xe4\x89\x7d\xe0")
    code.raw(b"\x89\x4d\xec")  # context.dispatcher
    for source_offset, destination_offset in (
        (0x0C, 0xF0),
        (0x10, 0xF4),
        (0x14, 0xF8),
        (0x18, 0xFC),
    ):
        code.raw(b"\x8b\x45" + bytes([source_offset]))
        code.raw(b"\x89\x45" + bytes([destination_offset]))
    code.raw(b"\x8d\x4d\xec")  # this = stack-local context
    code.raw(b"\xb8" + struct.pack("<I", thunk_va))
    code.raw(b"\xff\x75\x08")
    code.call_absolute(input_wrapper_va)
    code.raw(b"\x8b\x7d\xe0\x8b\x75\xe4\x8b\x5d\xe8\xc9\xc2\x14\x00")
    return code.build()


def build_periodic_cursor_select_thunk(
    owner: SidneyPresentationCompiler,
    *,
    wrapper_va: int,
) -> bytes:
    """Call GK3's two-argument cursor selector from a one-POINT adapter."""
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\xff\x71\x04")  # original activation flag
    code.raw(b"\xff\x74\x24\x08")  # adapter-owned POINT after the flag push
    code.raw(b"\x8b\x09")  # original CursorDispatcher this
    code.call_absolute(owner.profile.address("mouse_move.cursor_select"))
    code.raw(b"\xc2\x04\x00")
    return code.build()


def build_periodic_cursor_select_wrapper(
    *,
    wrapper_va: int,
    input_wrapper_va: int,
    thunk_va: int,
) -> bytes:
    """Inverse-map DirectInput's independent cursor-selection POINT."""
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x55\x8b\xec\x83\xec\x14")
    code.raw(b"\x89\x5d\xf4\x89\x75\xf0\x89\x7d\xec")
    code.raw(b"\x89\x4d\xf8")  # context.dispatcher
    code.raw(b"\x8b\x45\x0c\x89\x45\xfc")  # context.activation
    code.raw(b"\x8d\x4d\xf8")
    code.raw(b"\xb8" + struct.pack("<I", thunk_va))
    code.raw(b"\xff\x75\x08")
    code.call_absolute(input_wrapper_va)
    code.raw(b"\x8b\x7d\xec\x8b\x75\xf0\x8b\x5d\xf4\xc9\xc2\x08\x00")
    return code.build()


def build_reference_anchor_input_wrapper(
    owner: SidneyPresentationCompiler,
    *,
    wrapper_va: int,
    system_root_ptr_va: int,
    system_input_wrapper_va: int,
    input_transform_count_va: int,
    input_source_x_va: int,
    input_logical_x_va: int,
) -> bytes:
    """Map every pixel of a reference-anchored Button into its live RECT.

    Title, CloseUp and Death position each control centre through the fitted 4:3
    viewport, then independently scale its extent by ``target_height/768``.
    That is intentionally not one global affine. Walk only direct generic
    Button children of the exact current root, reconstruct the same final
    rectangle (including renderer edge clamping), and map a contained point
    locally. Points outside those controls retain the generic system inverse
    so hover release and background semantics stay native.
    """
    # EAX carries the concrete native event target from the per-slot stub;
    # ECX and [ESP+4] retain the native this/POINT contract. All temporary
    # geometry is stack-local so synchronously nested window dispatch cannot
    # corrupt an outer event's source point or return value.
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x55\x8b\xec\x83\xec\x48\x60")
    code.raw(b"\x8b\x75\x08\x85\xf6")
    code.jump_if(Condition.EQUAL, "fallback")
    code.raw(b"\x8b\x06\x89\x45\xfc\x8b\x46\x04\x89\x45\xf8")

    # Build the largest centered 4:3 target in the physical framebuffer.
    # Locals -0x0c..-0x18 retain left, top, width, and height.
    code.raw(b"\xa1" + struct.pack("<I", owner._physical_width_global_va))
    code.raw(b"\x6b\xc0\x03")
    code.raw(b"\x8b\x15" + struct.pack("<I", owner._physical_width_global_va + 4))
    code.raw(b"\xc1\xe2\x02\x3b\xc2")
    code.jump_if(Condition.LESS, "narrow_target")
    code.raw(b"\xa1" + struct.pack("<I", owner._physical_width_global_va + 4))
    code.raw(b"\x89\x45\xe8\xc1\xe0\x02\x99\xb9\x03\x00\x00\x00\xf7\xf9")
    code.raw(b"\x89\x45\xec")
    code.raw(b"\x8b\x15" + struct.pack("<I", owner._physical_width_global_va))
    code.raw(b"\x2b\xd0\xd1\xfa\x89\x55\xf4\x31\xd2\x89\x55\xf0")
    code.jump("target_ready")

    code.label("narrow_target")
    code.raw(b"\xa1" + struct.pack("<I", owner._physical_width_global_va))
    code.raw(b"\x89\x45\xec\x6b\xc0\x03\x99\xb9\x04\x00\x00\x00\xf7\xf9")
    code.raw(b"\x89\x45\xe8")
    code.raw(b"\x8b\x15" + struct.pack("<I", owner._physical_width_global_va + 4))
    code.raw(b"\x2b\xd0\xd1\xfa\x89\x55\xf0\x31\xd2\x89\x55\xf4")
    code.label("target_ready")

    code.raw(b"\x8b\x15" + struct.pack("<I", system_root_ptr_va) + b"\x85\xd2")
    code.jump_if(Condition.EQUAL, "fallback")
    code.raw(b"\x8b\x7a\x4c\x8b\x5a\x50\x85\xdb")
    code.jump_if(Condition.LESS_OR_EQUAL, "fallback")

    code.label("child_loop")
    code.raw(b"\x8b\x0f\x83\xc7\x04\x85\xc9")
    code.jump_if(Condition.EQUAL, "next_child")
    code.raw(b"\x81\x39" + struct.pack("<I", owner.profile.address("ui.button_vtable")))
    code.jump_if(Condition.NOT_EQUAL, "next_child")
    code.raw(b"\x80\x79\x18\x00")
    code.jump_if(Condition.EQUAL, "next_child")
    # Retain the authored child RECT in locals -0x1c..-0x28.
    code.raw(b"\x8b\x41\x1c\x89\x45\xe4\x8b\x41\x20\x89\x45\xe0")
    code.raw(b"\x8b\x41\x24\x89\x45\xdc\x8b\x41\x28\x89\x45\xd8")
    # Reload right after the bottom-edge load above; reusing EAX here
    # would accidentally calculate ``bottom - left`` as the width.
    code.raw(b"\x8b\x45\xdc\x2b\x45\xe4")
    code.jump_if(Condition.LESS_OR_EQUAL, "next_child")
    code.raw(b"\x8b\x55\xd8\x2b\x55\xe0")
    code.jump_if(Condition.LESS_OR_EQUAL, "next_child")

    # Final width = authored width * target height / 768. Store it
    # temporarily in final-right (-0x34) until the actual edges are known.
    code.raw(b"\x0f\xaf\x45\xe8\x99\xb9\x00\x03\x00\x00\xf7\xf9\x85\xc0")
    code.jump_if(Condition.LESS_OR_EQUAL, "next_child")
    code.raw(b"\x89\x45\xcc")
    # final centre.x = target.left + authored centre.x * target.width / W
    code.raw(b"\x8b\x45\xe4\x03\x45\xdc\xd1\xf8\x0f\xaf\x45\xec\x99")
    code.raw(b"\xf7\x3d" + struct.pack("<I", owner._physical_width_global_va))
    code.raw(b"\x03\x45\xf4\x8b\x55\xcc\xd1\xfa\x2b\xc2\x89\x45\xd4")
    code.raw(b"\x03\x45\xcc\x89\x45\xcc")

    # Final height and centre use the same uniform apparent-size scale.
    code.raw(b"\x8b\x45\xd8\x2b\x45\xe0\x0f\xaf\x45\xe8\x99")
    code.raw(b"\xb9\x00\x03\x00\x00\xf7\xf9\x85\xc0")
    code.jump_if(Condition.LESS_OR_EQUAL, "next_child")
    code.raw(b"\x89\x45\xc8")
    code.raw(b"\x8b\x45\xe0\x03\x45\xd8\xd1\xf8\x0f\xaf\x45\xe8\x99")
    code.raw(b"\xf7\x3d" + struct.pack("<I", owner._physical_width_global_va + 4))
    code.raw(b"\x03\x45\xf0\x8b\x55\xc8\xd1\xfa\x2b\xc2\x89\x45\xd0")
    code.raw(b"\x03\x45\xc8\x89\x45\xc8")

    # Mirror the renderer's translate-without-squashing edge clamp. A
    # bottom/right point at far-1 therefore maps to the authored far-1.
    for first_offset, second_offset, physical_size_va, prefix in (
        (0xD4, 0xCC, owner._physical_width_global_va, "x"),
        (0xD0, 0xC8, owner._physical_width_global_va + 4, "y"),
    ):
        code.raw(b"\x8b\x45" + bytes([first_offset]) + b"\x85\xc0")
        code.jump_if(Condition.GREATER_OR_EQUAL, f"{prefix}_near_inside")
        code.raw(b"\x8b\x55" + bytes([second_offset]) + b"\x2b\xd0")
        code.raw(b"\x89\x55" + bytes([second_offset]) + b"\x31\xc0")
        code.raw(b"\x89\x45" + bytes([first_offset]))
        code.label(f"{prefix}_near_inside")
        code.raw(b"\x8b\x45" + bytes([second_offset]))
        code.raw(b"\x3b\x05" + struct.pack("<I", physical_size_va))
        code.jump_if(Condition.LESS_OR_EQUAL, f"{prefix}_far_inside")
        code.raw(b"\x2b\x05" + struct.pack("<I", physical_size_va))
        code.raw(b"\x29\x45" + bytes([first_offset]))
        code.raw(b"\xa1" + struct.pack("<I", physical_size_va))
        code.raw(b"\x89\x45" + bytes([second_offset]))
        code.label(f"{prefix}_far_inside")

    # RECT containment uses exclusive far edges, matching GK3 and Win32.
    code.raw(b"\x8b\x45\xfc\x3b\x45\xd4")
    code.jump_if(Condition.LESS, "next_child")
    code.raw(b"\x3b\x45\xcc")
    code.jump_if(Condition.GREATER_OR_EQUAL, "next_child")
    code.raw(b"\x8b\x45\xf8\x3b\x45\xd0")
    code.jump_if(Condition.LESS, "next_child")
    code.raw(b"\x3b\x45\xc8")
    code.jump_if(Condition.GREATER_OR_EQUAL, "next_child")
    # Retain the physical candidate; publish its authored counterpart only
    # after the local inverse below has actually computed it.
    code.raw(b"\x8b\x45\xfc\xa3" + struct.pack("<I", input_source_x_va))

    # Map local final-pixel offsets back into the original child RECT.
    code.raw(b"\x8b\x45\xfc\x2b\x45\xd4\x8b\x4d\xdc\x2b\x4d\xe4")
    code.raw(b"\x0f\xaf\xc1\x99\x8b\x4d\xcc\x2b\x4d\xd4\xf7\xf9")
    code.raw(b"\x03\x45\xe4\x89\x06")
    code.raw(b"\xa3" + struct.pack("<I", input_logical_x_va))
    code.raw(b"\x8b\x45\xf8\x2b\x45\xd0\x8b\x4d\xd8\x2b\x4d\xe0")
    code.raw(b"\x0f\xaf\xc1\x99\x8b\x4d\xc8\x2b\x4d\xd0\xf7\xf9")
    code.raw(b"\x03\x45\xe0\x89\x46\x04")
    code.raw(b"\xff\x05" + struct.pack("<I", input_transform_count_va))
    # Button hover/click code consumes both the event POINT and the durable
    # MouseManager cursor cache. Scope them to the same authored child
    # pixel; a point-only inverse makes the two native hit tests disagree.
    cursor_position_va = owner.profile.address("input.cursor_position")
    code.raw(b"\xa1" + struct.pack("<I", cursor_position_va) + b"\x89\x45\xc0")
    code.raw(b"\xa1" + struct.pack("<I", cursor_position_va + 4) + b"\x89\x45\xbc")
    code.raw(b"\x8b\x06\xa3" + struct.pack("<I", cursor_position_va))
    code.raw(b"\x8b\x46\x04\xa3" + struct.pack("<I", cursor_position_va + 4))
    code.jump("matched")

    code.label("next_child")
    code.raw(b"\x4b")
    code.jump_if(Condition.NOT_EQUAL, "child_loop")
    code.label("fallback")
    code.raw(b"\x61\x8b\xe5\x5d\xba" + struct.pack("<I", system_input_wrapper_va))
    code.raw(b"\xff\xe2")

    code.label("matched")
    code.raw(b"\x61\xff\x75\x08\xff\xd0\x89\x45\xc4")
    code.raw(b"\x8b\x4d\xc0\x89\x0d" + struct.pack("<I", cursor_position_va))
    code.raw(b"\x8b\x4d\xbc\x89\x0d" + struct.pack("<I", cursor_position_va + 4))
    code.raw(b"\x8b\x55\x08\x8b\x4d\xfc\x89\x0a\x8b\x4d\xf8\x89\x4a\x04")
    code.raw(b"\x8b\x45\xc4\x8b\xe5\x5d\xc2\x04\x00")
    return code.build()


def _emit_reference_canvas_point_inverse(
    owner: SidneyPresentationCompiler,
    code: X86Emitter,
    *,
    system_transform_mode_va: int,
    input_logical_x_va: int,
    input_logical_y_va: int,
) -> None:
    """Emit the one authoritative inverse for a fitted 1024x768 POINT.

    EBX/EBP hold the presented X/Y and ESI points at caller-owned storage.
    Keeping this arithmetic shared prevents early child selection and later
    event dispatch from drifting at non-reference resolutions.
    """
    # Select the same limiting axis as the compositor by comparing W*3 with
    # H*4. Signed arithmetic preserves hover-release coordinates just outside
    # the fitted viewport instead of clamping them into a live control.
    code.raw(b"\xa1" + struct.pack("<I", owner._physical_width_global_va))
    code.raw(b"\x6b\xc0\x03")
    code.raw(b"\x8b\x15" + struct.pack("<I", owner._physical_width_global_va + 4))
    code.raw(b"\xc1\xe2\x02\x3b\xc2")
    code.jump_if(Condition.LESS, "width_limited")

    # Height-limited/widescreen target. Use the concrete integer width so the
    # inverse agrees with the renderer when H is not divisible by three.
    code.raw(b"\xa1" + struct.pack("<I", owner._physical_width_global_va + 4))
    code.raw(b"\xc1\xe0\x02\x99\xb9\x03\x00\x00\x00\xf7\xf9")
    code.raw(b"\x8b\xc8")
    code.raw(b"\x8b\x15" + struct.pack("<I", owner._physical_width_global_va))
    code.raw(b"\x2b\xd0\xd1\xfa")
    code.raw(b"\x8b\xc3\x2b\xc2\x69\xc0\x00\x04\x00\x00\x99\xf7\xf9")
    code.raw(b"\x89\x06\xa3" + struct.pack("<I", input_logical_x_va))
    code.raw(b"\x8b\xc5\x69\xc0\x00\x03\x00\x00\x99")
    code.raw(b"\x8b\x0d" + struct.pack("<I", owner._physical_width_global_va + 4))
    code.raw(b"\xf7\xf9\x89\x46\x04\xa3" + struct.pack("<I", input_logical_y_va))
    code.jump("mapped")

    # Width-limited/portrait target.
    code.label("width_limited")
    code.raw(b"\xa1" + struct.pack("<I", owner._physical_width_global_va))
    code.raw(b"\x6b\xc0\x03\xc1\xf8\x02\x8b\xc8")
    code.raw(b"\x8b\x15" + struct.pack("<I", owner._physical_width_global_va + 4))
    code.raw(b"\x2b\xd0\xd1\xfa")
    code.raw(b"\x8b\xc3\x69\xc0\x00\x04\x00\x00\x99")
    code.raw(b"\xf7\x3d" + struct.pack("<I", owner._physical_width_global_va))
    code.raw(b"\x89\x06\xa3" + struct.pack("<I", input_logical_x_va))
    code.raw(b"\x8b\xc5\x2b\xc2\x69\xc0\x00\x03\x00\x00\x99\xf7\xf9")
    code.raw(b"\x89\x46\x04\xa3" + struct.pack("<I", input_logical_y_va))

    code.label("mapped")
    # CloseUp retains the authored X domain but bottom-anchors native Y by the
    # framebuffer growth beyond 768 rows. Reapply that model-space offset only
    # for its explicitly published transform mode.
    code.raw(b"\x83\x3d" + struct.pack("<I", system_transform_mode_va))
    code.raw(bytes([owner._system_bottom_anchored_reference_canvas_mode]))
    code.jump_if(Condition.NOT_EQUAL, "native_coordinates_ready")
    code.raw(b"\xa1" + struct.pack("<I", owner._physical_width_global_va + 4))
    code.raw(b"\x2d" + struct.pack("<I", AUTHORED_FRAME_HEIGHT))
    code.raw(b"\x01\x46\x04")
    code.label("native_coordinates_ready")


def build_reference_canvas_input_wrapper(
    owner: SidneyPresentationCompiler,
    *,
    wrapper_va: int,
    system_transform_mode_va: int,
    input_transform_count_va: int,
    input_source_x_va: int,
    input_logical_x_va: int,
    input_logical_y_va: int,
) -> bytes:
    """Map a fitted 1024x768 canvas without reading render scratch state.

    Inventory and any future reference-canvas owner keep their object and
    hit rectangles in authored coordinates.  The renderer constructs the
    largest centered 4:3 viewport from the live framebuffer, so this input
    owner reconstructs that same viewport for every event and applies its
    exact inverse.  SystemScreen's shared source/target RECTs intentionally
    remain per-Blt diagnostics: cursor, font, and nested child transfers
    are allowed to overwrite them without changing pointer semantics.
    """
    # EAX is the native event target, ECX is its this pointer, and [ESP+4]
    # is POINT*.  Keep the presented POINT and MouseManager cache physical
    # outside the native call so nested dispatch observes one coordinate
    # domain and the caller receives its original event unchanged.
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x83\x7c\x24\x04\x00")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x53\x56\x57\x55\x51")
    code.raw(b"\x8b\xf8\x8b\x74\x24\x18\x8b\x1e\x8b\x6e\x04")
    code.raw(b"\x89\x1d" + struct.pack("<I", input_source_x_va))

    _emit_reference_canvas_point_inverse(
        owner,
        code,
        system_transform_mode_va=system_transform_mode_va,
        input_logical_x_va=input_logical_x_va,
        input_logical_y_va=input_logical_y_va,
    )
    code.raw(b"\xff\x05" + struct.pack("<I", input_transform_count_va))
    cursor_position_va = owner.profile.address("input.cursor_position")
    code.raw(b"\xff\x35" + struct.pack("<I", cursor_position_va))
    code.raw(b"\xff\x35" + struct.pack("<I", cursor_position_va + 4))
    code.raw(b"\x8b\x06\xa3" + struct.pack("<I", cursor_position_va))
    code.raw(b"\x8b\x46\x04\xa3" + struct.pack("<I", cursor_position_va + 4))
    code.raw(b"\x8b\x4c\x24\x08\xff\x74\x24\x20\xff\xd7")
    # Preserve the native result while restoring cursor Y, cursor X, the
    # saved this pointer, and finally the caller-owned physical POINT.
    code.raw(b"\x8b\xc8\x58\xa3" + struct.pack("<I", cursor_position_va + 4))
    code.raw(b"\x58\xa3" + struct.pack("<I", cursor_position_va) + b"\x8b\xc1")
    code.raw(b"\x83\xc4\x04\x89\x1e\x89\x6e\x04\x5d\x5f\x5e\x5b\xc2\x04\x00")
    code.label("native")
    code.raw(b"\xff\xe0")
    return code.build()


def build_input_dispatch_wrapper(
    owner: SidneyPresentationCompiler,
    *,
    wrapper_va: int,
    root_ptr_va: int,
    input_transform_count_va: int,
    input_source_x_va: int,
    input_logical_x_va: int,
    driving_map_active_va: int,
    driving_map_input_depth_va: int,
    tbt_layer_va: int,
    tbt_target_rect_va: int,
    tbt_input_wrapper_va: int,
    system_active_va: int,
    system_root_ptr_va: int,
    system_transform_mode_va: int,
    system_input_wrapper_va: int,
    toolbar_input_wrapper_va: int,
    reference_anchor_input_wrapper_va: int,
    reference_canvas_input_wrapper_va: int,
    binocs_input_wrapper_va: int,
    system_action_presented_root_va: int,
    system_native_input_vtables: tuple[int, ...],
) -> bytes:
    """Route one pointer event to the active domain's exact inverse affine."""
    # Six button-edge slots and the post-bookkeeping pointer traversal
    # enter this common wrapper with their native target in EAX. Transform
    # the POINT for the duration of that complete native event, then put
    # the presented coordinate back before returning to the outer mouse
    # state machine. The exact inverse subtracts the live X offset,
    # multiplies both coordinates by 768, and divides by physical height.
    # This helper contains direct rel32 calls into GK3.
    # Assemble it at its actual load address; a zero base silently adds the
    # section VA to every call target (for example 0x00474B2D became
    # 0x00BB5F2D at runtime during Restore).
    code = X86Emitter(base_va=wrapper_va)
    # Most authored-framebuffer interfaces need no inverse. TimeBlock is the
    # exception: dense backgrounds retain a larger persistent model, and Draw
    # only temporarily translates its children into authored space. At 1024,
    # consult that exact live owner without entering transient system roots.
    code += b"\x83\x3d" + struct.pack("<I", driving_map_active_va) + b"\x00"
    code.jump_if(Condition.NOT_EQUAL, "classify")
    code += b"\x81\x3d" + struct.pack("<I", owner._physical_width_global_va)
    code += struct.pack("<I", AUTHORED_FRAME_WIDTH)
    code.jump_if(Condition.ABOVE, "classify")
    code += b"\x81\x3d" + struct.pack("<I", owner._physical_width_global_va + 4)
    code += struct.pack("<I", AUTHORED_FRAME_HEIGHT)
    code.jump_if(Condition.BELOW_OR_EQUAL, "tbt_dispatch")
    code.label("classify")
    # Retained SIDNEY/map roots remain alive beneath modal dialogs. Their
    # lifetime flags cannot override the top layer's input domain: doing so
    # horizontally remaps ConfirmQuit clicks before its popup inverse can run.
    # Preserve the event target and this pointer across the native layer query.
    code += b"\x83\x3d" + struct.pack("<I", system_active_va) + b"\x00"
    code.jump_short_if(Condition.EQUAL, "retained_roots")
    code += b"\x50\x51"
    code.call_absolute(owner._current_layer_va)
    code += b"\x3b\x05" + struct.pack("<I", system_root_ptr_va) + b"\x59\x58"
    code.jump_if(Condition.EQUAL, "system_dispatch")
    code.label("retained_roots")
    code += b"\x83\x3d" + struct.pack("<I", root_ptr_va) + b"\x00"
    code.jump_if(Condition.EQUAL, "sidney_not_current")
    # Add Data retains SIDNEY underneath Inventory. Its inverse must not
    # remap Inventory's already-physical ActionMenu button rectangles.
    code += b"\x50\x51"
    code.call_absolute(owner._current_layer_va)
    code += b"\x3b\x05" + struct.pack("<I", root_ptr_va) + b"\x59\x58"
    code.jump_if(Condition.EQUAL, "sidney_transform")
    code.label("sidney_not_current")

    code += b"\x83\x3d" + struct.pack("<I", driving_map_active_va) + b"\x00"
    code.jump_if(Condition.NOT_EQUAL, "map_transform")

    system_fallback = "tbt_dispatch"
    # ActionMenu publishes final physical object rectangles, but GK3's
    # Button methods also feed POINT-relative coordinates into each
    # original 32x32 icon's opacity mask. Adapt that source lookup before
    # normal physical hit testing. The root is a room child, so its exact
    # ownership guard must precede the SystemScreen-active guard.
    code += b"\x83\x3d" + struct.pack("<I", system_action_presented_root_va) + b"\x00"
    code.jump_if(Condition.NOT_EQUAL, "action_transform")
    code += b"\x83\x3d" + struct.pack("<I", system_active_va) + b"\x00"
    code.jump_if(Condition.EQUAL, system_fallback)
    code.label("system_dispatch")
    code += b"\x83\x3d" + struct.pack("<I", system_transform_mode_va)
    code += bytes([owner._system_reference_anchor_mode])
    code.jump_short_if(Condition.NOT_EQUAL, "not_reference_anchor")
    # Both dedicated paths are terminal dispatches.  Keeping the absolute
    # tail jump beside its comparison avoids a long conditional branch and
    # leaves the shared classifier compact enough for its fixed ABI slot.
    code += b"\xba" + struct.pack("<I", reference_anchor_input_wrapper_va) + b"\xff\xe2"
    code.label("not_reference_anchor")
    # A reference canvas has a stable semantic transform, not a stable
    # final-Blit rectangle.  Reconstruct its inverse from the framebuffer
    # instead of consuming mutable system render scratch.
    code += b"\x83\x3d" + struct.pack("<I", system_transform_mode_va)
    code += bytes([owner._system_reference_canvas_mode])
    code.jump_short_if(Condition.EQUAL, "reference_canvas")
    code += b"\x83\x3d" + struct.pack("<I", system_transform_mode_va)
    code += bytes([owner._system_reference_canvas_all_mode])
    code.jump_short_if(Condition.EQUAL, "reference_canvas")
    code += b"\x83\x3d" + struct.pack("<I", system_transform_mode_va)
    code += bytes([owner._system_bottom_anchored_reference_canvas_mode])
    code.jump_short_if(Condition.NOT_EQUAL, "not_reference_canvas")
    code.label("reference_canvas")
    code += b"\xba" + struct.pack("<I", reference_canvas_input_wrapper_va) + b"\xff\xe2"
    code.label("not_reference_canvas")
    # Some roots publish their final presentation rectangles directly
    # after Draw so native hit testing is pixel exact. Those physical
    # rectangles must never pass through the generic affine inverse.
    code += b"\x83\x3d" + struct.pack("<I", system_transform_mode_va)
    code += bytes([owner._system_physical_canvas_mode])
    code.jump_if(Condition.EQUAL, system_fallback)
    # Death's small controls use the renderer's fitted-anchor affine, not
    # physical input rectangles. Binocs additionally groups its D-pad in a
    # local affine and retains its dedicated inverse.
    code += b"\x83\x3d" + struct.pack("<I", system_transform_mode_va)
    code += bytes([owner._system_composite_mode])
    code.jump_if(Condition.NOT_EQUAL, "not_composite")
    code += b"\x8b\x15" + struct.pack("<I", system_root_ptr_va) + b"\x85\xd2"
    code.jump_if(Condition.EQUAL, system_fallback)
    code += b"\x81\x3a" + struct.pack("<I", owner.profile.address("death.vtable"))
    code.jump_short_if(Condition.NOT_EQUAL, "composite_not_death")
    # Death may remain published while a newly opened modal has not drawn
    # yet. Only its actual top-layer ownership authorizes this inverse.
    code += b"\x50\x51"
    code.call_absolute(owner._current_layer_va)
    code += b"\x3b\x05" + struct.pack("<I", system_root_ptr_va) + b"\x59\x58"
    code.jump_if(Condition.NOT_EQUAL, system_fallback)
    code += b"\xba" + struct.pack("<I", reference_anchor_input_wrapper_va) + b"\xff\xe2"
    code.label("composite_not_death")
    code += b"\x81\x3a" + struct.pack("<I", owner.profile.address("binocular.vtable"))
    code.jump_if(Condition.NOT_EQUAL, system_fallback)
    code += b"\xba" + struct.pack("<I", binocs_input_wrapper_va) + b"\xff\xe2"
    code.label("not_composite")
    # Compact popup controls are visible children of the current room.
    code += b"\x83\x3d" + struct.pack("<I", system_transform_mode_va)
    code += bytes([owner._system_popup_mode])
    code.jump_if(Condition.NOT_EQUAL, "system_modal_check")
    code += b"\x8b\x15" + struct.pack("<I", system_root_ptr_va) + b"\x85\xd2"
    code.jump_if(Condition.EQUAL, system_fallback)
    code += b"\x80\x7a\x18\x00"
    code.jump_if(Condition.EQUAL, system_fallback)
    # Load/Save roots publish physical object rectangles and bypass the
    # popup inverse. Reload root before each vtable comparison.
    code += b"\x8b\x15" + struct.pack("<I", system_root_ptr_va)
    code += b"\x81\x3a" + struct.pack("<I", owner.profile.address("ingame_toolbar.vtable"))
    code.jump_if(Condition.EQUAL, "toolbar_transform")
    for vtable in system_native_input_vtables:
        code += b"\x81\x3a" + struct.pack("<I", vtable)
        code.jump_if(Condition.EQUAL, system_fallback)
    code += b"\xba" + struct.pack("<I", system_input_wrapper_va) + b"\xff\xe2"

    code.label("toolbar_transform")
    code += b"\xba" + struct.pack("<I", toolbar_input_wrapper_va) + b"\xff\xe2"

    code.label("system_modal_check")
    # Restore and other modal layers can cover Death without invoking its
    # hide slot. Confirm Death is still current before mapping its input.
    code += b"\x50\x51\xba" + struct.pack("<I", owner._current_layer_va)
    code += b"\xff\xd2\x3b\x05" + struct.pack("<I", system_root_ptr_va)
    code += b"\x59\x58"
    code.jump_if(Condition.NOT_EQUAL, system_fallback)
    # LoadGame/SaveGame layout construction has already converted every
    # control and hit rectangle to final framebuffer coordinates.  Once the
    # live top-layer check above proves that one of those concrete roots owns
    # this event, retain the physical POINT.  Applying the generic canvas
    # inverse here would compare (for example) a 3840-wide scrollbar around
    # x=2260 with an incorrectly remapped pointer around x=633.
    for vtable in system_native_input_vtables:
        code += b"\x8b\x15" + struct.pack("<I", system_root_ptr_va)
        code += b"\x81\x3a" + struct.pack("<I", vtable)
        code.jump_if(Condition.EQUAL, "native")
    code += b"\xba" + struct.pack("<I", system_input_wrapper_va) + b"\xff\xe2"

    code.label("tbt_dispatch")
    # TimeBlock construction publishes its retained layer pointer before
    # Restore has finished deserializing and before that layer owns input.
    # Visibility alone consequently routed queued window events through an
    # uninitialized inverse and made direct TimeBlock saves fail to load.
    # Match the modal-system policy above: only GK3's current top layer may
    # own a coordinate transform. Preserve EAX (the native event target)
    # and ECX (its object) across the authoritative query.
    code += b"\x50\x51"
    code.call_absolute(owner._current_layer_va)
    code += b"\x3b\x05" + struct.pack("<I", tbt_layer_va)
    code += b"\x59\x58"
    code.jump_if(Condition.NOT_EQUAL, "native")
    # A published layer pointer precedes its first fitted transfer. Do not
    # enter the inverse wrapper until that transfer has produced a concrete
    # nonempty target in both axes; its internal zero-denominator fallback
    # is defensive, not an ownership signal.
    code += b"\x8b\x15" + struct.pack("<I", tbt_target_rect_va + 8)
    code += b"\x3b\x15" + struct.pack("<I", tbt_target_rect_va)
    code.jump_if(Condition.LESS_OR_EQUAL, "native")
    code += b"\x8b\x15" + struct.pack("<I", tbt_target_rect_va + 12)
    code += b"\x3b\x15" + struct.pack("<I", tbt_target_rect_va + 4)
    code.jump_if(Condition.LESS_OR_EQUAL, "native")
    code += b"\x8b\x15" + struct.pack("<I", tbt_layer_va)
    code += b"\x85\xd2"
    code.jump_if(Condition.EQUAL, "native")
    code += b"\x80\xba\xc0\x03\x00\x00\x00"
    code.jump_if(Condition.EQUAL, "native")
    code += b"\xba" + struct.pack("<I", tbt_input_wrapper_va) + b"\xff\xe2"

    code.label("action_transform")
    code += b"\x83\x7c\x24\x04\x00"
    code.jump_if(Condition.EQUAL, "native")
    code += b"\x53\x56\x57\x55\x51"  # preserve original point and this/ECX
    code += b"\x8b\xf8\x8b\x74\x24\x18\x8b\x1e\x8b\x6e\x04"
    code += b"\x89\x1d" + struct.pack("<I", input_source_x_va)
    code += b"\x89\x1d" + struct.pack("<I", input_logical_x_va)
    # EBX becomes the containing button's left edge below. Save this event's
    # original X separately: the caller's saved EBX is not the physical POINT,
    # and shared telemetry can be overwritten by a nested callback.
    code += b"\x53"
    action_size_va = system_action_presented_root_va - 0x20
    action_top_va = system_action_presented_root_va - 0x10
    # Leave events outside the physical ActionMenu root untouched. This
    # preserves stock capture/dismiss semantics and confines the adapter
    # to the exact children whose icon masks were enlarged for display.
    code += b"\x8b\x15" + struct.pack("<I", system_action_presented_root_va)
    code += b"\x85\xd2"
    code.jump_if(Condition.EQUAL, "action_call")
    code += b"\x3b\x5a\x1c"
    code.jump_if(Condition.LESS, "action_call")
    code += b"\x3b\x5a\x24"
    code.jump_if(Condition.GREATER_OR_EQUAL, "action_call")
    code += b"\x3b\x6a\x20"
    code.jump_if(Condition.LESS, "action_call")
    code += b"\x3b\x6a\x28"
    code.jump_if(Condition.GREATER_OR_EQUAL, "action_call")
    code += b"\x8b\x0d" + struct.pack("<I", action_size_va)
    code += b"\x83\xf9\x20"
    code.jump_if(Condition.LESS_OR_EQUAL, "action_call")

    # Find the containing presented child, then scale only its local
    # offset from [0,size) into the original [0,32) bitmap-mask domain.
    # The mapped POINT remains inside that same physical object rectangle,
    # so all normal rectangle/capture and tooltip tests keep their physical
    # ownership. EDX owns the published root; read its final left edge
    # because the adjacent layout cursor slot is iteration scratch.
    code += b"\x8b\xc3\x2b\x42\x1c"
    code += b"\x99\xf7\xf9"  # EAX=child index, EDX=local physical X
    code += b"\x2b\xda\x6b\xc2\x20\x99\xf7\xf9\x03\xc3"
    code += b"\x89\x06\xa3" + struct.pack("<I", input_logical_x_va)
    code += b"\x8b\xc5\x2b\x05" + struct.pack("<I", action_top_va)
    code += b"\x6b\xc0\x20\x99\xf7\xf9\x03\x05" + struct.pack("<I", action_top_va)
    code += b"\x89\x46\x04"
    code.label("action_call")
    code += b"\xff\x05" + struct.pack("<I", input_transform_count_va)
    # Only the callback's POINT enters the authored sprite-mask domain.
    # MouseManager's durable cursor cache remains physical for the tooltip
    # and cursor producers which run after nested dispatch returns.
    code += b"\x8b\x4c\x24\x04\xff\x74\x24\x1c\xff\xd7"
    code += b"\x5a\x89\x16\x89\x6e\x04"
    code += b"\x83\xc4\x04"
    # Restore from this invocation's registers, not telemetry cells: a
    # synchronous nested event may overwrite diagnostics before return.
    code += b"\x5d\x5f\x5e\x5b\xc2\x04\x00"

    code.label("sidney_transform")
    code += b"\x83\x7c\x24\x04\x00"
    code.jump_if(Condition.EQUAL, "native")
    code += b"\x53\x56\x57\x55\x51"  # preserve ebx, esi, edi, ebp, this/ECX
    code += b"\x8b\xf8"  # native event target supplied by the slot stub
    code += b"\x8b\x74\x24\x18"  # POINT* after five pushes
    code += b"\x8b\x1e"  # source X, retained across native dispatch
    code += b"\x8b\x6e\x04"  # source Y
    code += b"\x89\x1d" + struct.pack("<I", input_source_x_va)
    # Derive the live horizontal offset by centering a height-fitted 4:3 view.
    code += b"\xa1" + struct.pack("<I", owner._physical_width_global_va + 4)
    code += b"\xc1\xe0\x02\x99\xb9\x03\x00\x00\x00\xf7\xf9"
    code += b"\x8b\x15" + struct.pack("<I", owner._physical_width_global_va)
    code += b"\x2b\xd0\xd1\xfa"
    # X inverse.
    code += b"\x8b\xc3\x2b\xc2\x69\xc0\x00\x03\x00\x00"
    code += b"\x99"
    code += b"\x8b\x0d" + struct.pack("<I", owner._physical_width_global_va + 4)
    code += b"\xf7\xf9"
    code += b"\x89\x06"
    code += b"\xa3" + struct.pack("<I", input_logical_x_va)
    # Y inverse.
    code += b"\x8b\xc5\x69\xc0\x00\x03\x00\x00\x99"
    code += b"\x8b\x0d" + struct.pack("<I", owner._physical_width_global_va + 4)
    code += b"\xf7\xf9\x89\x46\x04"
    code += b"\xff\x05" + struct.pack("<I", input_transform_count_va)
    code += b"\x59"  # restore this/ECX
    code += b"\xff\x74\x24\x14"  # pass the original POINT pointer
    code += b"\xff\xd7"  # call the native event target in EDI
    code += b"\x89\x1e\x89\x6e\x04"  # restore presented POINT
    code += b"\x5d\x5f\x5e\x5b\xc2\x04\x00"

    code.label("map_transform")
    # Invert presentation's floor-rounded source-grid edges, including the
    # vertical letterbox. A continuous inverse disagrees by a screen pixel
    # at some location edges. Select the source cell first, then its native
    # physical model coordinate, so drawing and picking share exact bounds.
    code += b"\x83\x7c\x24\x04\x00"
    code.jump_if(Condition.EQUAL, "native")
    code += b"\x53\x56\x57\x55\x51"
    code += b"\x8b\xf8\x8b\x74\x24\x18\x8b\x1e\x8b\x6e\x04"
    code += b"\x89\x1d" + struct.pack("<I", input_source_x_va)
    emit_fitted_height(code, physical_width_va=owner._physical_width_global_va)
    code += b"\x8b\xc8"  # fitted height
    code += b"\x8b\x15" + struct.pack("<I", owner._physical_width_global_va + 4)
    code += b"\x2b\xd0\xd1\xfa\x8b\xc5\x2b\xc2"
    _emit_map_inverse_axis(
        code, physical_va=owner._physical_width_global_va + 4, native=480, label="map_y"
    )
    code += b"\x89\x46\x04"
    code += b"\x8b\xc1"
    code += b"\xc1\xe0\x02\x99\x6a\x03\xf7\x3c\x24\x83\xc4\x04"
    code += b"\x8b\x15" + struct.pack("<I", owner._physical_width_global_va)
    code += b"\x2b\xd0\xd1\xfa"
    code += b"\x8b\xc3\x2b\xc2"
    _emit_map_inverse_axis(
        code, physical_va=owner._physical_width_global_va, native=640, label="map_x"
    )
    code += b"\x89\x06"
    code += b"\xa3" + struct.pack("<I", input_logical_x_va)
    code += b"\xff\x05" + struct.pack("<I", input_transform_count_va)

    # Map location buttons consult both the callback POINT and MouseManager's
    # durable cursor cache. Scope them to the same logical X for the complete
    # native dispatch; otherwise delayed hover/tooltip ownership sees physical
    # widescreen X and selects a visibly shifted location.
    cursor_position_va = owner.profile.address("input.cursor_position")
    code += b"\xff\x35" + struct.pack("<I", cursor_position_va)
    code += b"\xff\x35" + struct.pack("<I", cursor_position_va + 4)
    code += b"\x8b\x06\xa3" + struct.pack("<I", cursor_position_va)
    code += b"\x8b\x46\x04\xa3" + struct.pack("<I", cursor_position_va + 4)
    code += b"\xff\x05" + struct.pack("<I", driving_map_input_depth_va)
    code += b"\x8b\x4c\x24\x08\xff\x74\x24\x20\xff\xd7"
    code += b"\xff\x0d" + struct.pack("<I", driving_map_input_depth_va)
    code += b"\x8b\xc8\x58\xa3" + struct.pack("<I", cursor_position_va + 4)
    code += b"\x58\xa3" + struct.pack("<I", cursor_position_va) + b"\x8b\xc1"
    code += b"\x83\xc4\x04\x89\x1e\x89\x6e\x04"
    code += b"\x5d\x5f\x5e\x5b\xc2\x04\x00"

    code.label("native")
    code += b"\xff\xe0"  # inactive/null: tail-call the native target in EAX
    return code.build()


def _emit_map_inverse_axis(code: X86Emitter, *, physical_va: int, native: int, label: str) -> None:
    """Map local EAX through floor-rounded H/480 cells; ECX holds fitted H."""
    # floor(((p + 1) * 480 - 1) / H) is the exact inverse cell of
    # floor(k * H / 480). Keep bars outside the map even for negative p.
    code += b"\x40\x69\xc0\xe0\x01\x00\x00\x48\x99\xf7\xf9"
    code += b"\x85\xd2"
    code.jump_short_if(Condition.GREATER_OR_EQUAL, label)
    code += b"\x48"
    code.label(label)
    code += b"\x0f\xaf\x05" + struct.pack("<I", physical_va)
    code += b"\x99\x68" + struct.pack("<I", native)
    code += b"\xf7\x3c\x24\x83\xc4\x04"


def _emit_toolbar_inverse_axis(
    code: X86Emitter, *, source_va: int, height_va: int, anchor: int, point: bytes
) -> None:
    """Invert the compositor's exact height scale about its fixed base anchor."""
    code.raw(b"\x8b\x0d" + struct.pack("<I", height_va) + b"\x85\xc9")
    code.jump_if(Condition.LESS_OR_EQUAL, "invalid_rect")
    code.raw(b"\x8b\x15" + struct.pack("<I", source_va))
    code.raw(b"\x83\xc2" + bytes([anchor]) + b"\x52")
    code.raw(point + b"\x2b\xc2\x69\xc0\x00\x03\x00\x00\x99\xf7\xf9\x5a\x03\xc2")


def build_tbt_input_wrapper(
    owner: SidneyPresentationCompiler,
    *,
    input_transform_count_va: int,
    input_source_x_va: int,
    input_logical_x_va: int,
    input_logical_y_va: int,
    logical_rect_va: int,
    target_rect_va: int,
    persistent_root_va: int | None,
    rect_valid_va: int | None = None,
    scope_depth_va: int | None = None,
    toolbar_height_va: int | None = None,
) -> bytes:
    """Apply one fitted inverse, optionally returning to persistent root space."""
    code = X86Emitter(base_va=0)
    code += b"\x83\x7c\x24\x04\x00"
    code.jump_if(Condition.EQUAL, "native")
    code += b"\x53\x56\x57\x55\x51"
    code += b"\x8b\xf8\x8b\x74\x24\x18\x8b\x1e\x8b\x6e\x04"
    if rect_valid_va is not None:
        # Toolbar drawing owns mutable per-Blt scratch elsewhere. Its first
        # completed transfer publishes this immutable pair; relocation and the
        # concrete class destructor clear it. Before publication, retain native
        # coordinates for one event instead of reading torn geometry.
        code += b"\x83\x3d" + struct.pack("<I", rect_valid_va) + b"\x00"
        code.jump_if(Condition.EQUAL, "invalid_rect")
    code += b"\x89\x1d" + struct.pack("<I", input_source_x_va)

    # A toolbar expands far beyond its initial 75-row rectangle. Its rounded
    # endpoint ratio is not its drawing scale: use the exact display-height
    # ratio and fixed base anchor, so later rows do not accumulate hit drift.
    if toolbar_height_va is not None:
        _emit_toolbar_inverse_axis(
            code,
            source_va=logical_rect_va,
            height_va=toolbar_height_va,
            anchor=126,
            point=b"\x8b\xc3",
        )
    else:
        # Map other fitted screens proportionally between their rectangles.
        code += b"\x8b\xc3\x2b\x05" + struct.pack("<I", target_rect_va)
        code += b"\x8b\x0d" + struct.pack("<I", logical_rect_va + 8)
        code += b"\x2b\x0d" + struct.pack("<I", logical_rect_va)
        code += b"\x0f\xaf\xc1\x99"
        code += b"\x8b\x0d" + struct.pack("<I", target_rect_va + 8)
        code += b"\x2b\x0d" + struct.pack("<I", target_rect_va)
        code += b"\x85\xc9"
        code.jump_if(Condition.EQUAL, "invalid_rect")
        code += b"\xf7\xf9"
        code += b"\x03\x05" + struct.pack("<I", logical_rect_va)
        if persistent_root_va is not None:
            # TimeBlock Draw moves its complete tree into the temporary
            # authored rectangle, traverses it, then restores the replacement-
            # sized model before input can arrive. Convert the presented point
            # first into that temporary rectangle, then subtract Draw's exact
            # root translation so native hit testing sees the persistent child
            # RECTs it actually owns.
            code += b"\x8b\x15" + struct.pack("<I", persistent_root_va)
            code += b"\x85\xd2"
            code.jump_if(Condition.EQUAL, "invalid_rect")
            code += b"\x2b\x05" + struct.pack("<I", logical_rect_va)
            code += b"\x03\x42\x1c"
    code += b"\x89\x06\xa3" + struct.pack("<I", input_logical_x_va)

    # logical.y uses the corresponding vertical rectangles.
    if toolbar_height_va is not None:
        _emit_toolbar_inverse_axis(
            code,
            source_va=logical_rect_va + 4,
            height_va=toolbar_height_va,
            anchor=37,
            point=b"\x8b\xc5",
        )
    else:
        code += b"\x8b\xc5\x2b\x05" + struct.pack("<I", target_rect_va + 4)
        code += b"\x8b\x0d" + struct.pack("<I", logical_rect_va + 12)
        code += b"\x2b\x0d" + struct.pack("<I", logical_rect_va + 4)
        code += b"\x0f\xaf\xc1\x99"
        code += b"\x8b\x0d" + struct.pack("<I", target_rect_va + 12)
        code += b"\x2b\x0d" + struct.pack("<I", target_rect_va + 4)
        code += b"\x85\xc9"
        code.jump_if(Condition.EQUAL, "invalid_rect")
        code += b"\xf7\xf9"
        code += b"\x03\x05" + struct.pack("<I", logical_rect_va + 4)
        if persistent_root_va is not None:
            code += b"\x8b\x15" + struct.pack("<I", persistent_root_va)
            code += b"\x85\xd2"
            code.jump_if(Condition.EQUAL, "invalid_rect")
            code += b"\x2b\x05" + struct.pack("<I", logical_rect_va + 4)
            code += b"\x03\x42\x20"
    code += b"\x89\x46\x04\xa3" + struct.pack("<I", input_logical_y_va)

    code += b"\xff\x05" + struct.pack("<I", input_transform_count_va)

    # Generic Button dispatch consults both the event POINT and the durable
    # MouseManager cursor cache. Scope both to the same inverse-mapped
    # coordinate, exactly as the class-specific title/action adapters do.
    # The saved globals live on this invocation's stack so a synchronously
    # nested window event cannot corrupt the outer restoration value.
    cursor_position_va = owner.profile.address("input.cursor_position")
    code += b"\xff\x35" + struct.pack("<I", cursor_position_va)
    code += b"\xff\x35" + struct.pack("<I", cursor_position_va + 4)
    code += b"\x8b\x06\xa3" + struct.pack("<I", cursor_position_va)
    code += b"\x8b\x46\x04\xa3" + struct.pack("<I", cursor_position_va + 4)
    # The delayed tooltip resolver can run either inside this button-event
    # scope or later from MouseManager's idle path. Publish a re-entrant
    # depth only for the toolbar adapter, allowing the idle owner to reuse
    # this exact inverse without mapping an already-logical nested POINT a
    # second time.
    if scope_depth_va is not None:
        code += b"\xff\x05" + struct.pack("<I", scope_depth_va)
    code += b"\x8b\x4c\x24\x08"  # saved this/ECX below the cursor pair
    code += b"\xff\x74\x24\x20\xff\xd7"
    if scope_depth_va is not None:
        code += b"\xff\x0d" + struct.pack("<I", scope_depth_va)
    # Preserve the native return while restoring global Y then X.
    code += b"\x8b\xc8\x58\xa3" + struct.pack("<I", cursor_position_va + 4)
    code += b"\x58\xa3" + struct.pack("<I", cursor_position_va) + b"\x8b\xc1"
    code += b"\x83\xc4\x04"  # discard the separately reloaded saved ECX
    code += b"\x89\x1e\x89\x6e\x04\x5d\x5f\x5e\x5b\xc2\x04\x00"
    code.label("invalid_rect")
    # A system layer can become input-active one tick before its fitted
    # target rectangle is populated (or remain active for one teardown
    # tick after it is cleared).  Preserve the original event coordinates
    # and dispatch natively instead of dividing by a zero-width/height
    # transient rectangle.
    # EDI holds the native target, but POP EDI restores the caller's unrelated
    # register (often an object pointer). Keep the target in volatile EAX
    # before unwinding, or this fallback jumps into object data after a layout
    # change invalidates the toolbar snapshot.
    code += b"\x89\x1e\x89\x6e\x04\x8b\xc7\x59\x5d\x5f\x5e\x5b"
    code.label("native")
    code += b"\xff\xe0"
    return code.build()


def build_button_dispatch_stub(
    *,
    stub_va: int,
    wrapper_va: int,
    original_va: int,
    argument_count: int,
    map_drag_anchor: bool = False,
) -> bytes:
    """Publish one native UI dispatch ABI, below MouseManager bookkeeping."""
    code = X86Emitter(base_va=stub_va)
    code += b"\xb8" + struct.pack("<I", original_va)
    code += b"\xba" + struct.pack("<I", argument_count | (0x80000000 if map_drag_anchor else 0))
    code.jump_absolute(wrapper_va)
    return code.build()


def build_button_dispatch_adapter(
    *,
    wrapper_va: int,
    input_wrapper_va: int,
    thunk_va: int,
) -> bytes:
    """Inverse-map UI dispatch without altering MouseManager's drag anchors.

    EAX is the native target; EDX is its argument count (one through five).
    Every selected call has POINT* first. Drag-begin additionally carries an
    absolute press anchor: map a private copy, never MouseManager's durable
    physical anchor. Motion's second argument is a delta and stays untouched.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x55\x8b\xec\x83\xec\x40")
    code.raw(b"\x89\x5d\xdc\x89\x75\xd8\x89\x7d\xd4")
    code.raw(b"\x89\x55\xcc\x81\xe2\xff\xff\xff\x7f")
    # Context -0x20: receiver, target, count, then up to five arguments.
    code.raw(b"\x89\x4d\xe0\x89\x45\xe4\x89\x55\xe8")
    code.raw(b"\x8b\xca\x8d\x75\x08\x8d\x7d\xec\xfc\xf3\xa5")
    code.raw(b"\x83\x7d\xcc\x00")
    code.jump_short_if(Condition.GREATER_OR_EQUAL, "current_point")
    # A zero-arity thunk copies the inverse-mapped POINT into private storage
    # below this context. The inverse restores the physical anchor on return.
    code.raw(b"\xc7\x45\xe8\x00\x00\x00\x00")
    code.raw(b"\x8d\x4d\xe0\xb8" + struct.pack("<I", thunk_va))
    code.raw(b"\xff\x75\x0c")
    code.call_absolute(input_wrapper_va)
    code.raw(b"\x8b\x45\xcc\x25\xff\xff\xff\x7f\x89\x45\xe8")
    code.raw(b"\x8d\x45\xc4\x89\x45\xf0")
    code.label("current_point")
    code.raw(b"\x8d\x4d\xe0\xb8" + struct.pack("<I", thunk_va))
    code.raw(b"\xff\x75\x08")
    code.call_absolute(input_wrapper_va)
    code.raw(b"\x8b\x7d\xd4\x8b\x75\xd8\x8b\x5d\xdc")
    # Callee-clean the original ABI while preserving the native EAX result.
    code.raw(b"\x8b\x4d\xe8\x8b\x55\x04\xc9\x8d\x64\x8c\x04\xff\xe2")
    return code.build()


def build_button_dispatch_thunk(*, wrapper_va: int) -> bytes:
    """Forward a stack context while its first POINT has the selected affine."""
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x56\x8b\xf1\x8b\x4e\x08")
    code.raw(b"\x85\xc9")
    code.jump_short_if(Condition.EQUAL, "copy_anchor")
    code.label("arguments")
    code.raw(b"\xff\x74\x8e\x08\x49")
    code.jump_short_if(Condition.NOT_EQUAL, "arguments")
    code.raw(b"\x8b\x0e\xff\x56\x04\x5e\xc2\x04\x00")
    code.label("copy_anchor")
    code.raw(b"\x8b\x44\x24\x08\x8b\x10\x89\x56\xe4")
    code.raw(b"\x8b\x50\x04\x89\x56\xe8\x5e\xc2\x04\x00")
    return code.build()
