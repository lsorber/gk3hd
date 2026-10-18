"""Private native menu destination scope for the OpenXR prototype.

These are producer/lifecycle primitives, not a player-facing patch. Optional
helpers own a bounded CPU cache and qualify child transfers and live frame
identity before publication. The caller still binds the verified hooks and XR
batch. No completed game page is copied into the cache.
"""

from __future__ import annotations

import struct

from gk3hd.patch.binary.x86 import Condition, X86Emitter

_RGB565_MAX = 0xFFFF


def append_opaque_overlay(
    code: X86Emitter, *, cache_va: int, rectangle_va: int, failed_label: str
) -> None:
    """Append a qualified opaque crop with matching physical input coordinates.

    EDI is the sized caller frame. The caller owns current-page validation,
    capacity reservation and rollback. Cropping must use the accepted cache
    extent rather than the preceding frame's requested canvas dimensions.
    """
    code.raw(bytes.fromhex("8b 8f bc 00 00 00 6b c9 28 8d 8c 0f c0 00 00 00"))
    code.raw(b"\xa1" + struct.pack("<I", cache_va + 4) + bytes.fromhex("89 01"))
    for offset, value in ((4, 2), (8, 0)):
        code.raw(b"\xc7\x41" + bytes((offset,)) + struct.pack("<I", value))
    code.raw(bytes.fromhex("c7 41 24 00 00 80 3f"))
    for index, (destination, extent) in enumerate(((12, None), (16, None), (20, 8), (24, 12))):
        code.raw(b"\xa1" + struct.pack("<I", rectangle_va + index * 4))
        if extent is None:
            code.raw(bytes.fromhex("31 d2 85 c0 0f 4c c2"))
        else:
            code.raw(b"\x3b\x05" + struct.pack("<I", cache_va + extent))
            code.raw(b"\x0f\x4f\x05" + struct.pack("<I", cache_va + extent))
        code.raw(b"\x89\x41" + bytes((destination,)))
        if extent is None:
            code.raw(b"\x89\x41" + bytes((28 + index * 4,)))
    for near, far in ((12, 20), (16, 24)):
        code.raw(b"\x8b\x41" + bytes((far,)) + b"\x3b\x41" + bytes((near,)))
        code.jump_if(Condition.LESS_OR_EQUAL, failed_label)
    code.raw(bytes.fromhex("ff 87 bc 00 00 00"))


def build_menu_destination_scope(
    *,
    wrapper_va: int,
    state_va: int,
    target_va: int,
    class_vtable: int,
    toolbar: bool,
    resolve_resource_va: int,
    resource_manager_va: int,
    back_surface_va: int,
    directdraw_owner_va: int,
    readable_iat_va: int,
    prepare_va: int | None = None,
    blt_va: int | None = None,
    blt_fast_va: int | None = None,
    generation_va: int | None = None,
    unwind_va: int | None = None,
    coverage_va: int | None = None,
    mirror_va: int | None = None,
    capture_only: bool = False,
) -> bytes:
    """Capture a complete native traversal with qualified desktop mirroring.

    Entry/return are the native thiscall Draw(root, bitmap handle, damage),
    RET 8. Caller state is enabled/surface/width/height/DirectDraw owner at
    +0/+4/+8/+12/+16, initially zero. Busy/resource/original/root/traversals
    at +20..+36 are private. +0x100 is an 80-byte destination wrapper,
    +0x150 a four-word damage collection, +0x160 its complete canvas RECT,
    and +0x180 the final physical menu RECT. Traversals counts only completed
    scoped native calls, not successful individual blits or XR submissions.

    With a mirror helper, draw into the owned cache once, then copy only its
    qualified opaque crops to the normal destination. Unavailable resources,
    failed child transfers, footprint checks or mirroring retain the ordinary
    Draw with its original destination/damage, without publishing the cache.
    Without a mirror helper, the diagnostic primitive retains the normal Draw
    followed by a separate capture traversal. The temporary
    resource binding is restored before returning. The private wrapper has no
    borrowed inline critical section. A supplied prepare helper owns allocation,
    clearing and format checks; otherwise the caller provides the cache.
    Optional paired Blt/BltFast result thunks qualify child transfers through a
    private Surface1 vtable, restored before return. +0x70 is ready only after
    at least one successful child transfer and no failures, with publication
    count at +0x74. Otherwise no publication is produced. Frame freshness,
    destructor binding and presentation remain the caller's responsibility.
    A supplied successful-Flip generation is recorded at +0x78 when ready.
    An optional x86 SEH handler protects only the bound cache traversal. Its stack
    registration is retained at +0x88 while bound. The caller must verify that
    the executable permits this handler (or register it with its SafeSEH table).
    A supplied coverage helper must qualify the final native footprint after
    bindings are restored; failure prevents publication of the new pixels.

    Capture-only mode is for a caller that already performed ordinary Draw.
    It never draws or mirrors into the desktop, including failure paths. The
    caller owns preservation of its original result and complete source order.
    """
    if (blt_va is None) != (blt_fast_va is None):
        msg = "menu child-transfer qualification requires both result thunks"
        raise ValueError(msg)
    if coverage_va is not None and blt_va is None:
        msg = "menu footprint qualification requires qualified child transfers"
        raise ValueError(msg)
    if mirror_va is not None and blt_va is None:
        msg = "single menu traversal requires qualified child transfers"
        raise ValueError(msg)
    if capture_only and (mirror_va is not None or blt_va is None):
        msg = "capture-only requires qualified transfers without desktop mirroring"
        raise ValueError(msg)
    single = capture_only or mirror_va is not None
    e = X86Emitter(base_va=wrapper_va)

    def absolute(opcode: bytes, address: int) -> None:
        e.raw(opcode + struct.pack("<I", address))

    def state(opcode: bytes, offset: int) -> None:
        absolute(opcode, state_va + offset)

    # Retain the native root and preserve the actual Draw's return state across
    # validation, capture and copying. Helpers cannot replace EAX or flags.
    if not single:
        e.raw(bytes.fromhex("51 ff 74 24 0c ff 74 24 0c"))
        e.call_absolute(target_va)
        e.raw(bytes.fromhex("59 50 9c 60"))
    else:
        e.raw(bytes.fromhex("51 50 9c 60"))

    def native_inputs(stack_shift: int) -> None:
        # Re-enter the native function with the incoming register/flag state,
        # not the validation helpers' scratch values. ECX is the root this.
        for opcode, offset in (
            (b"\x8b\x7c\x24", 0),
            (b"\x8b\x74\x24", 4),
            (b"\x8b\x6c\x24", 8),
            (b"\x8b\x5c\x24", 16),
            (b"\x8b\x54\x24", 20),
            (b"\x8b\x4c\x24", 24),
            (b"\x8b\x44\x24", 28),
        ):
            e.raw(opcode + bytes((offset + stack_shift,)))
        e.raw(b"\xff\x74\x24" + bytes((32 + stack_shift,)) + b"\x9d")

    def native_result(stack_shift: int) -> None:
        # PUSHAD's EAX and the extra native-result word must both agree.
        for offset in (28, 36):
            e.raw(b"\x89\x44\x24" + bytes((offset + stack_shift,)))
        e.raw(b"\x89\x54\x24" + bytes((20 + stack_shift,)))
        e.raw(bytes.fromhex("9c 58") + b"\x89\x44\x24" + bytes((32 + stack_shift,)))

    state(b"\xc7\x05", 0x70)
    e.raw(bytes(4))
    state(b"\x83\x3d", 0)
    e.raw(b"\x01")
    e.jump_if(Condition.NOT_EQUAL, "return")
    state(b"\x83\x3d", 20)
    e.raw(b"\x00")
    e.jump_if(Condition.NOT_EQUAL, "return")
    e.raw(b"\x81\x39" + struct.pack("<I", class_vtable))
    e.jump_if(Condition.NOT_EQUAL, "return")
    e.raw(bytes.fromhex("80 79 18 00"))
    e.jump_if(Condition.EQUAL, "return")
    absolute(b"\xa1", directdraw_owner_va)
    e.raw(bytes.fromhex("85 c0"))
    e.jump_if(Condition.EQUAL, "return")
    state(b"\x89\x0d", 32)
    absolute(b"\x8b\x0d", resource_manager_va)
    e.raw(bytes.fromhex("85 c9"))
    e.jump_if(Condition.EQUAL, "return")
    e.raw(bytes.fromhex("68 24 01 00 00 51"))
    absolute(b"\xff\x15", readable_iat_va)
    e.raw(bytes.fromhex("85 c0"))
    e.jump_if(Condition.NOT_EQUAL, "return")
    absolute(b"\x8b\x0d", resource_manager_va)
    e.raw(bytes.fromhex("83 b9 20 01 00 00 00"))
    e.jump_if(Condition.EQUAL, "return")
    # The single-pass frame additionally retains the root above saved EAX.
    e.raw(b"\xff\x74\x24" + bytes((0x30 if single else 0x2C,)))
    e.call_absolute(resolve_resource_va)
    e.raw(bytes.fromhex("85 c0"))
    e.jump_if(Condition.EQUAL, "return")
    state(b"\xa3", 24)
    e.raw(bytes.fromhex("6a 34 50"))
    absolute(b"\xff\x15", readable_iat_va)
    e.raw(bytes.fromhex("85 c0"))
    e.jump_if(Condition.NOT_EQUAL, "return")
    state(b"\xa1", 24)
    e.raw(bytes.fromhex("8b 70 30 85 f6"))
    e.jump_if(Condition.EQUAL, "return")
    state(b"\x89\x35", 28)
    e.raw(bytes.fromhex("6a 50 56"))
    absolute(b"\xff\x15", readable_iat_va)
    e.raw(bytes.fromhex("85 c0"))
    e.jump_if(Condition.NOT_EQUAL, "return")
    state(b"\x8b\x35", 28)
    absolute(b"\xa1", back_surface_va)
    e.raw(bytes.fromhex("85 c0"))
    e.jump_if(Condition.EQUAL, "return")
    e.raw(bytes.fromhex("3b 46 2c"))
    e.jump_if(Condition.NOT_EQUAL, "return")
    if prepare_va is not None:
        # ESI is the validated original destination wrapper. The optional
        # helper preserves it and all other registers except its boolean EAX.
        e.call_absolute(prepare_va)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "return")
    state(b"\x83\x3d", 4)
    e.raw(b"\x00")
    e.jump_if(Condition.EQUAL, "return")
    absolute(b"\xa1", directdraw_owner_va)
    state(b"\x3b\x05", 16)
    e.jump_if(Condition.NOT_EQUAL, "return")
    absolute(b"\xa1", back_surface_va)
    state(b"\x3b\x05", 4)
    e.jump_if(Condition.EQUAL, "return")
    for dimension, field in ((8, 0x38), (12, 0x3C)):
        state(b"\xa1", dimension)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.LESS_OR_EQUAL, "return")
        e.raw(bytes.fromhex("3d 00 20 00 00"))
        e.jump_if(Condition.ABOVE, "return")
        e.raw(b"\x3b\x46" + bytes((field,)))
        e.jump_if(Condition.NOT_EQUAL, "return")
    if blt_va is not None and blt_fast_va is not None:
        # Never change a renderer-wide COM table. This independent CPU object
        # borrows a private table only during the synchronous native traversal.
        state(b"\xa1", 4)
        e.raw(bytes.fromhex("6a 04 50"))
        absolute(b"\xff\x15", readable_iat_va)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "return")
        state(b"\xa1", 4)
        e.raw(bytes.fromhex("8b 30 85 f6"))
        e.jump_if(Condition.EQUAL, "return")
        state(b"\x89\x35", 0x60)
        e.raw(bytes.fromhex("68 90 00 00 00 56"))
        absolute(b"\xff\x15", readable_iat_va)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "return")
        state(b"\x8b\x35", 0x60)
        for slot, saved in ((0x14, 0x80), (0x1C, 0x84)):
            e.raw(b"\x8b\x46" + bytes((slot,)))
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.EQUAL, "return")
            state(b"\xa3", saved)
        state(b"\xbf", 0x380)
        e.raw(bytes.fromhex("b9 24 00 00 00 fc f3 a5"))
        for slot, thunk in ((0x14, blt_va), (0x1C, blt_fast_va)):
            state(b"\xc7\x05", 0x380 + slot)
            e.raw(struct.pack("<I", thunk))
        for offset in (0x64, 0x68):
            state(b"\xc7\x05", offset)
            e.raw(bytes(4))
        state(b"\x8b\x35", 28)
    state(b"\xbf", 0x100)
    e.raw(bytes.fromhex("b9 14 00 00 00 fc f3 a5"))
    state(b"\xc7\x05", 0x128)
    e.raw(bytes(4))
    state(b"\xa1", 4)
    state(b"\xa3", 0x12C)
    # Use complete native damage in the source's coordinate system. The
    # existing root wrapper still owns every final transform and native child.
    state(b"\xa1", 8)
    state(b"\xa3", 0x168)
    state(b"\xa1", 12)
    state(b"\xa3", 0x16C)
    state(b"\x8b\x35", 32)
    e.raw(bytes.fromhex("83 c6 1c"))
    state(b"\xbf", 0x180)
    e.raw(bytes.fromhex("b9 04 00 00 00 f3 a5"))
    if toolbar:
        # Match the native room-toolbar affine, including signed truncation.
        # Expansion changes its bottom, never the base 252x75 centre.
        for first, second, center in ((0, 8, 126), (4, 12, 37)):
            state(b"\x8b\x1d", 0x180 + first)
            e.raw(b"\x83\xc3" + bytes((center,)))
            for edge in (first, second):
                state(b"\xa1", 0x180 + edge)
                e.raw(bytes.fromhex("2b c3"))
                state(b"\x0f\xaf\x05", 12)
                e.raw(bytes.fromhex("99 b9 00 03 00 00 f7 f9 03 c3"))
                state(b"\xa3", 0x180 + edge)
    if unwind_va is not None:
        # [previous, handler, state] is local to this synchronous traversal.
        # Ordinary fallback runs outside this exception registration.
        state(b"\x68", 0)
        e.push_imm32(unwind_va)
        e.raw(bytes.fromhex("64 ff 35 00 00 00 00 64 89 25 00 00 00 00"))
        state(b"\x89\x25", 0x88)
    state(b"\xc7\x05", 20)
    e.raw(struct.pack("<I", 1))
    state(b"\x8b\x35", 24)
    state(b"\xbf", 0x100)
    e.raw(bytes.fromhex("89 7e 30"))
    if blt_va is not None:
        state(b"\xa1", 4)
        state(b"\xbf", 0x380)
        e.raw(bytes.fromhex("89 38"))
    state(b"\x68", 0x150)
    destination_offset = (0x34 if single else 0x30) + (12 if unwind_va is not None else 0)
    e.raw(b"\xff\x74\x24" + bytes((destination_offset,)))
    state(b"\x8b\x0d", 32)
    if single:
        native_inputs(8 + (12 if unwind_va is not None else 0))
    e.call_absolute(target_va)
    if single:
        native_result(12 if unwind_va is not None else 0)
    if blt_va is not None:
        state(b"\xa1", 4)
        state(b"\x8b\x35", 0x60)
        e.raw(bytes.fromhex("89 30"))
    state(b"\x8b\x35", 24)
    state(b"\xa1", 28)
    e.raw(bytes.fromhex("89 46 30"))
    state(b"\xc7\x05", 20)
    e.raw(bytes(4))
    if unwind_va is not None:
        e.raw(bytes.fromhex("8b 14 24 64 89 15 00 00 00 00 83 c4 0c"))
        state(b"\xc7\x05", 0x88)
        e.raw(bytes(4))
    state(b"\xff\x05", 36)
    if blt_va is not None:
        state(b"\x83\x3d", 0x64)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "return")
        state(b"\x83\x3d", 0x68)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "return")
        if coverage_va is not None:
            e.call_absolute(coverage_va)
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.EQUAL, "return")
        if mirror_va is not None:
            e.call_absolute(mirror_va)
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.EQUAL, "return")
        state(b"\xc7\x05", 0x70)
        e.raw(struct.pack("<I", 1))
        state(b"\xff\x05", 0x74)
        if generation_va is not None:
            absolute(b"\xa1", generation_va)
            state(b"\xa3", 0x78)
    if single:
        e.jump("finished")
    e.label("return")
    if single:
        # Bindings have either never changed or are already restored. A stale
        # cache, failed child, footprint or mirror uses the ordinary destination
        # and original damage. No partially qualified surface is published.
        if not capture_only:
            e.raw(bytes.fromhex("ff 74 24 34 ff 74 24 34"))
            native_inputs(8)
            e.call_absolute(target_va)
            native_result(0)
        e.label("finished")
        e.raw(bytes.fromhex("61 9d 58 59 c2 08 00"))
    else:
        e.raw(bytes.fromhex("61 9d 58 c2 08 00"))
    return e.build()


def build_menu_cache_unwind(*, wrapper_va: int, state_va: int, qualified: bool) -> bytes:
    """Restore private bindings on x86 SEH unwind without swallowing exceptions.

    Native EXCEPTION_ROUTINE is cdecl with four arguments. Return disposition
    ExceptionContinueSearch (1), NOT the filter macro EXCEPTION_CONTINUE_SEARCH
    (0). First-pass dispatch leaves the scope intact: an inner handler may
    resume execution. Actual unwind through this exact stack registration
    restores the resource and private COM table, withdraws readiness/root,
    and clears busy. No COM calls, allocations, lock operations or context
    edits run during unwind. Cache release is deferred to normal validation.
    +0x8C counts completed cleanups; a duplicate/delayed unwind cannot clean up
    another scope's registration. The OS owns exception-chain removal.
    """
    e = X86Emitter(base_va=wrapper_va)

    def state(opcode: bytes, offset: int, suffix: bytes = b"") -> None:
        e.raw(opcode + struct.pack("<I", state_va + offset) + suffix)

    e.raw(bytes.fromhex("9c 60 8b 44 24 28 f7 40 04 06 00 00 00"))
    e.jump_if(Condition.EQUAL, "return")
    e.raw(bytes.fromhex("8b 54 24 2c"))  # Trusted establisher stack registration.
    state(b"\x3b\x15", 0x88)
    e.jump_if(Condition.NOT_EQUAL, "return")
    e.raw(b"\x81\x7a\x08" + struct.pack("<I", state_va))
    e.jump_if(Condition.NOT_EQUAL, "return")
    state(b"\x83\x3d", 20, b"\x01")
    e.jump_if(Condition.NOT_EQUAL, "return")
    if qualified:
        state(b"\xa1", 4)
        state(b"\x8b\x35", 0x60)
        e.raw(bytes.fromhex("89 30"))
    state(b"\x8b\x35", 24)
    state(b"\xa1", 28)
    e.raw(bytes.fromhex("89 46 30"))
    for offset, value in ((0x70, 0), (32, 0), (20, 0), (0x88, 0), (0x64, 1)):
        state(b"\xc7\x05", offset, struct.pack("<I", value))
    state(b"\xff\x05", 0x8C)
    e.label("return")
    e.raw(bytes.fromhex("c7 44 24 1c 01 00 00 00 61 9d c3"))
    return e.build()


def menu_destination_state(state_va: int) -> bytes:
    """Initialize the disabled scope and its private complete-damage collection."""
    result = bytearray(0x500)
    struct.pack_into("<4I", result, 0x150, 0, state_va + 0x160, state_va + 0x170, 0)
    # An explicit RGB565 system-memory surface, not a borrowed format or page.
    for offset, value in (
        (0, 108),
        (4, 0x1007),
        (0x48, 32),
        (0x4C, 0x40),
        (0x54, 16),
        (0x58, 0xF800),
        (0x5C, 0x7E0),
        (0x60, 0x1F),
        (0x68, 0x840),
    ):
        struct.pack_into("<I", result, 0x200 + offset, value)
    struct.pack_into("<I", result, 0x280, 108)
    struct.pack_into("<I", result, 0x300, 100)
    return bytes(result)


def build_menu_cache_release(*, wrapper_va: int, state_va: int) -> bytes:
    """Release an idle owned cache exactly once, preserving registers/flags.

    Caller must bind this to frame withdrawal/destruction. Clear ownership before
    the COM callback, so reentrant Release cannot release the same object twice.
    A scope that currently has the surface bound must finish before withdrawal.
    """
    e = X86Emitter(base_va=wrapper_va)
    e.raw(bytes.fromhex("9c 60"))
    e.raw(b"\x83\x3d" + struct.pack("<I", state_va + 20) + b"\x00")
    e.jump_if(Condition.NOT_EQUAL, "return")
    e.raw(b"\x8b\x35" + struct.pack("<I", state_va + 4))
    for offset in (4, 8, 12, 16, 40, 0x70):
        e.raw(b"\xc7\x05" + struct.pack("<I", state_va + offset) + bytes(4))
    e.raw(bytes.fromhex("85 f6"))
    e.jump_if(Condition.EQUAL, "return")
    e.raw(b"\xff\x05" + struct.pack("<I", state_va + 48))
    e.raw(bytes.fromhex("8b 06 56 ff 50 08"))
    e.label("return")
    e.raw(bytes.fromhex("61 9d c3"))
    return e.build()


def build_menu_cache_blt_result(*, wrapper_va: int, state_va: int, fast: bool) -> bytes:
    """Retain each native child HRESULT and qualify only the scoped CPU cache.

    Both Surface1 Blt/BltFast are stdcall with six arguments including this.
    Preserve the original result, flags and registers; failed or skipped
    transfers cannot silently become a ready interactive menu.
    """
    e = X86Emitter(base_va=wrapper_va)
    for _ in range(6):
        e.raw(bytes.fromhex("ff 74 24 18"))
    e.raw(b"\xff\x15" + struct.pack("<I", state_va + (0x84 if fast else 0x80)))
    e.raw(bytes.fromhex("9c 60"))
    e.raw(b"\x83\x3d" + struct.pack("<I", state_va + 20) + b"\x01")
    e.jump_if(Condition.NOT_EQUAL, "return")
    e.raw(bytes.fromhex("8b 44 24 28"))
    e.raw(b"\x3b\x05" + struct.pack("<I", state_va + 4))
    e.jump_if(Condition.NOT_EQUAL, "return")
    e.raw(b"\xff\x05" + struct.pack("<I", state_va + 0x68))
    e.raw(bytes.fromhex("83 7c 24 1c 00"))
    e.jump_if(Condition.EQUAL, "return")
    e.raw(b"\xc7\x05" + struct.pack("<I", state_va + 0x64) + struct.pack("<I", 1))
    e.label("return")
    e.raw(bytes.fromhex("61 9d c2 18 00"))
    return e.build()


def build_menu_cache_destructor(
    *, wrapper_va: int, state_va: int, release_va: int, target_va: int
) -> bytes:
    """Withdraw this exact root, then tail-enter its existing native destructor.

    The target is the verified current runtime wrapper, not the stock function.
    A delayed destructor for an older menu must not release a newer root's cache.
    Stack, ECX, flags and native destructor arguments remain unchanged.
    """
    e = X86Emitter(base_va=wrapper_va)
    e.raw(bytes.fromhex("9c 60"))
    e.raw(b"\x3b\x0d" + struct.pack("<I", state_va + 32))
    e.jump_if(Condition.NOT_EQUAL, "native")
    e.raw(b"\x83\x3d" + struct.pack("<I", state_va + 20) + b"\x00")
    e.jump_if(Condition.NOT_EQUAL, "native")
    # Unpublish the root before Release can reenter patched virtuals.
    e.raw(b"\xc7\x05" + struct.pack("<I", state_va + 32) + bytes(4))
    e.call_absolute(release_va)
    e.label("native")
    e.raw(bytes.fromhex("61 9d"))
    e.jump_absolute(target_va)
    return e.build()


def build_menu_cache_validate(
    *,
    wrapper_va: int,
    state_va: int,
    release_va: int,
    class_vtable: int,
    directdraw_owner_va: int,
    dimensions_va: int,
    generation_va: int,
    readable_iat_va: int,
) -> bytes:
    """Accept only a live visible root captured for the current native page.

    Called before an XR batch consumes the source, not before native drawing.
    A stale page withdraws ready but retains a reusable surface. Hidden, missing,
    destroyed/foreign roots or owner/extent changes release it. No root pointer
    is dereferenced without a readable concrete-object check. Return EAX=1/0,
    preserving other registers/flags; busy scopes cannot publish or be released.
    """
    e = X86Emitter(base_va=wrapper_va)

    def state(opcode: bytes, offset: int, suffix: bytes = b"") -> None:
        e.raw(opcode + struct.pack("<I", state_va + offset) + suffix)

    e.raw(bytes.fromhex("9c 60"))
    state(b"\x83\x3d", 20, b"\x00")
    e.jump_if(Condition.NOT_EQUAL, "not_ready")
    state(b"\x83\x3d", 0, b"\x01")
    e.jump_if(Condition.NOT_EQUAL, "withdraw")
    state(b"\x8b\x35", 4)
    e.raw(bytes.fromhex("85 f6"))
    e.jump_if(Condition.EQUAL, "withdraw")
    e.raw(b"\xa1" + struct.pack("<I", directdraw_owner_va))
    e.raw(bytes.fromhex("85 c0"))
    e.jump_if(Condition.EQUAL, "withdraw")
    state(b"\x3b\x05", 16)
    e.jump_if(Condition.NOT_EQUAL, "withdraw")
    for dimension, accepted in ((0, 8), (4, 12)):
        e.raw(b"\xa1" + struct.pack("<I", dimensions_va + dimension))
        state(b"\x3b\x05", accepted)
        e.jump_if(Condition.NOT_EQUAL, "withdraw")
    state(b"\x8b\x35", 32)
    e.raw(bytes.fromhex("85 f6"))
    e.jump_if(Condition.EQUAL, "withdraw")
    e.raw(bytes.fromhex("6a 1c 56"))
    e.raw(b"\xff\x15" + struct.pack("<I", readable_iat_va))
    e.raw(bytes.fromhex("85 c0"))
    e.jump_if(Condition.NOT_EQUAL, "withdraw")
    e.raw(b"\x81\x3e" + struct.pack("<I", class_vtable))
    e.jump_if(Condition.NOT_EQUAL, "withdraw")
    e.raw(bytes.fromhex("80 7e 18 00"))
    e.jump_if(Condition.EQUAL, "withdraw")
    state(b"\x83\x3d", 0x70, b"\x01")
    e.jump_if(Condition.NOT_EQUAL, "not_ready")
    e.raw(b"\xa1" + struct.pack("<I", generation_va))
    state(b"\x3b\x05", 0x78)
    e.jump_if(Condition.NOT_EQUAL, "not_ready")
    e.raw(bytes.fromhex("c7 44 24 1c 01 00 00 00"))
    e.jump("return")
    e.label("withdraw")
    state(b"\xc7\x05", 32, bytes(4))
    e.call_absolute(release_va)
    e.label("not_ready")
    state(b"\xc7\x05", 0x70, bytes(4))
    e.raw(bytes.fromhex("c7 44 24 1c 00 00 00 00"))
    e.label("return")
    e.raw(bytes.fromhex("61 9d c3"))
    return e.build()


def build_menu_cache_prepare(
    *,
    wrapper_va: int,
    state_va: int,
    release_va: int,
    directdraw_owner_va: int,
    source_key: int | None = None,
) -> bytes:
    """Reuse/create and clear a bounded independent RGB565 menu destination.

    ESI is a previously validated original destination wrapper. Return EAX=1
    only after descriptor qualification and a successful current clear; retain
    every other register and entry flags. +40 is preparation success, NOT ready
    or evidence of a completed native draw. Creation/release counts are +44/+48;
    requested dimensions live at +0x50, descriptors at +0x200/+0x280, and black
    DDBLTFX at +0x300.

    A source-format mismatch, create/describe/clear failure or owner/size change
    cannot reuse old pixels. Release on failure, retry lazily next traversal.
    No source-page Lock/Blt is performed. Hidden/destructed roots still require
    caller-owned withdrawal, since a hidden root need not call Draw at all.

    An optional caller-authored RGB565 source key is installed and used for the
    clear. This lets glyph-only HUD capture reuse the same isolated allocation
    contract without treating black as transparent. Key setup failure withdraws
    the cache, just like creation, format or clear failure. +0x360 owns its
    DDCOLORKEY storage and does not overlap the private COM table at +0x380.
    """
    if source_key is not None and not 0 <= source_key <= _RGB565_MAX:
        msg = "isolated cache source key must be an RGB565 value"
        raise ValueError(msg)
    e = X86Emitter(base_va=wrapper_va)

    def state(opcode: bytes, offset: int, suffix: bytes = b"") -> None:
        e.raw(opcode + struct.pack("<I", state_va + offset) + suffix)

    def compare(offset: int, value: int) -> None:
        state(b"\x81\x3d", offset, struct.pack("<I", value))
        e.jump_if(Condition.NOT_EQUAL, "failed")

    def describe() -> None:
        # Reset the complete output descriptor before each COM call.
        e.raw(b"\x57")
        state(b"\xbf", 0x280)
        e.raw(bytes.fromhex("31 c0 b9 1b 00 00 00 fc f3 ab"))
        e.raw(b"\x5f")
        state(b"\xc7\x05", 0x280, struct.pack("<I", 108))
        state(b"\x68", 0x280)
        e.raw(bytes.fromhex("57 8b 07 ff 50 58 85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "failed")
        compare(0x280, 108)
        # Require actual dimensions and pixel format, not only an HRESULT.
        state(b"\xa1", 0x284)
        e.raw(bytes.fromhex("25 06 10 00 00 3d 06 10 00 00"))
        e.jump_if(Condition.NOT_EQUAL, "failed")
        for output, requested in ((0x288, 0x54), (0x28C, 0x50)):
            state(b"\xa1", output)
            state(b"\x3b\x05", requested)
            e.jump_if(Condition.NOT_EQUAL, "failed")
        for offset, value in (
            (0x2C8, 32),
            (0x2CC, 0x40),
            (0x2D4, 16),
            (0x2D8, 0xF800),
            (0x2DC, 0x7E0),
            (0x2E0, 0x1F),
            (0x2E4, 0),
        ):
            compare(offset, value)

    e.raw(bytes.fromhex("9c 60"))
    state(b"\x83\x3d", 20, b"\x00")
    e.jump_if(Condition.NOT_EQUAL, "busy")
    state(b"\xc7\x05", 40, bytes(4))
    state(b"\x83\x3d", 0, b"\x01")
    e.jump_if(Condition.NOT_EQUAL, "failed")
    e.raw(b"\x8b\x1d" + struct.pack("<I", directdraw_owner_va))
    e.raw(bytes.fromhex("85 db"))
    e.jump_if(Condition.EQUAL, "failed")
    # Keep the original wrapper in EBP across COM calls. Requested dimensions
    # are distinct from the last accepted cache, so a resize cannot masquerade
    # as a match by overwriting the old width/height first.
    e.raw(bytes.fromhex("8b ee"))
    for field, requested in ((0x38, 0x50), (0x3C, 0x54)):
        e.raw(b"\x8b\x45" + bytes((field,)) + bytes.fromhex("85 c0"))
        e.jump_if(Condition.LESS_OR_EQUAL, "failed")
        e.raw(bytes.fromhex("3d 00 20 00 00"))
        e.jump_if(Condition.ABOVE, "failed")
        state(b"\xa3", requested)
    state(b"\xa1", 0x50)
    state(b"\xf7\x25", 0x54)
    e.raw(bytes.fromhex("85 d2"))
    e.jump_if(Condition.NOT_EQUAL, "failed")
    e.raw(bytes.fromhex("3d 00 00 00 01"))
    e.jump_if(Condition.ABOVE, "failed")
    e.raw(bytes.fromhex("8b 7d 2c 85 ff"))
    e.jump_if(Condition.EQUAL, "failed")
    describe()
    state(b"\x8b\x3d", 4)
    e.raw(bytes.fromhex("85 ff"))
    e.jump_if(Condition.EQUAL, "create")
    state(b"\x3b\x1d", 16)
    e.jump_if(Condition.NOT_EQUAL, "replace")
    for accepted, requested in ((8, 0x50), (12, 0x54)):
        state(b"\xa1", accepted)
        state(b"\x3b\x05", requested)
        e.jump_if(Condition.NOT_EQUAL, "replace")
    e.jump("qualify_cache")
    e.label("replace")
    e.call_absolute(release_va)
    e.label("create")
    for requested, descriptor in ((0x50, 0x20C), (0x54, 0x208)):
        state(b"\xa1", requested)
        state(b"\xa3", descriptor)
    e.raw(bytes.fromhex("6a 00"))
    state(b"\x68", 4)
    state(b"\x68", 0x200)
    e.raw(bytes.fromhex("53 8b 03 ff 50 18 85 c0"))
    e.jump_if(Condition.NOT_EQUAL, "failed")
    state(b"\x8b\x3d", 4)
    e.raw(bytes.fromhex("85 ff"))
    e.jump_if(Condition.EQUAL, "failed")
    state(b"\xff\x05", 44)
    state(b"\x89\x1d", 16)
    for requested, accepted in ((0x50, 8), (0x54, 12)):
        state(b"\xa1", requested)
        state(b"\xa3", accepted)
    e.label("qualify_cache")
    # Refuse a broken CreateSurface implementation that returned the page.
    e.raw(bytes.fromhex("3b 7d 2c"))
    e.jump_if(Condition.EQUAL, "failed")
    describe()
    state(b"\xf7\x05", 0x284, struct.pack("<I", 1))
    e.jump_if(Condition.EQUAL, "failed")
    state(b"\xa1", 0x2E8)
    e.raw(bytes.fromhex("25 40 40 00 00 3d 40 00 00 00"))
    e.jump_if(Condition.NOT_EQUAL, "failed")
    if source_key is not None:
        for offset in (0x350, 0x360, 0x364):
            state(b"\xc7\x05", offset, struct.pack("<I", source_key))
        state(b"\x68", 0x360)
        e.raw(bytes.fromhex("6a 08 57 8b 07 ff 50 74 85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "failed")
    # Every scope starts clean. Black is ordinary opaque content within the
    # qualified menu RECT, not a transparency key or source-coverage heuristic.
    state(b"\x68", 0x300)
    e.raw(bytes.fromhex("68 00 04 00 01 6a 00 6a 00 6a 00 57 8b 07 ff 50 14 85 c0"))
    e.jump_if(Condition.NOT_EQUAL, "failed")
    state(b"\xc7\x05", 40, struct.pack("<I", 1))
    e.raw(bytes.fromhex("c7 44 24 1c 01 00 00 00"))
    e.jump("return")
    e.label("failed")
    e.call_absolute(release_va)
    e.label("busy")
    e.raw(bytes.fromhex("c7 44 24 1c 00 00 00 00"))
    e.label("return")
    e.raw(bytes.fromhex("61 9d c3"))
    return e.build()
