"""Private native TextBox source-capture primitives for the OpenXR HUD.

These helpers are not installed by the public patch catalog. A caller must own
the independent keyed destination, exact live HUD identity, successful child
transfers, current-frame publication and destruction/withdrawal. Rendering into
an opaque source is not itself proof that a usable HUD image was produced.
"""

from __future__ import annotations

import struct

from gk3hd.patch.binary.x86 import Condition, X86Emitter

HUD_STATE_SIZE = 68
HUD_ENABLED = 0
HUD_OWNER = 4
HUD_BUSY = 8
HUD_REGISTRATION = 12
HUD_GLYPH_OPACITY = 16
HUD_BACKGROUND_OPACITY = 20
HUD_SAVED_OPTIONS = 24
HUD_SAVED_BACKGROUND = 44
HUD_COMPLETED = 48
HUD_ABORTED = 52
HUD_CAPTURED_OWNER = 56
HUD_READY = 60
HUD_SAVED_FONT_SCOPE = 64

_TEXT_OPTIONS = 0x5C
_TEXT_BACKGROUND = 0x88
_ONE = 0x3F800000


def _restore(e: X86Emitter, state_va: int, *, font_scope_va: int | None = None) -> None:
    """Restore only the widget temporarily borrowed by the synchronous scope."""
    if font_scope_va is not None:
        e.raw(b"\xa1" + struct.pack("<I", state_va + HUD_SAVED_FONT_SCOPE))
        e.raw(b"\xa3" + struct.pack("<I", font_scope_va))
    e.raw(b"\x8b\x35" + struct.pack("<I", state_va + HUD_OWNER))
    for source, destination in (
        *((HUD_SAVED_OPTIONS + index * 4, _TEXT_OPTIONS + index * 4) for index in range(5)),
        (HUD_SAVED_BACKGROUND, _TEXT_BACKGROUND),
    ):
        e.raw(b"\xa1" + struct.pack("<I", state_va + source))
        e.raw(b"\x89\x86" + struct.pack("<I", destination))
    for offset in (HUD_BUSY, HUD_REGISTRATION):
        e.raw(b"\xc7\x05" + struct.pack("<I", state_va + offset) + bytes(4))


def build_hud_text_scope(
    *,
    wrapper_va: int,
    state_va: int,
    target_va: int,
    class_vtable: int,
    capture_active_va: int,
    unwind_va: int,
    backing: bool = False,
    font_scope_va: int | None = None,
) -> bytes:
    """Capture independent opaque glyphs or backing, restoring native options.

    Entry is native thiscall Draw(TextBox, bitmap handle, damage), RET 8. Only
    an enabled, visible exact owner during its caller's bound source capture
    may be borrowed. An ordinary/foreign/recursive call tails into the original
    target with unchanged inputs. Authored mode zero is opaque; mode one carries
    source/destination fade weights. Other effects or invalid alpha are not
    inferred. The final publisher must consume HUD_READY only together with
    its independently qualified destination and current native generation.

    The default source draws opaque glyphs without backing. The backing variant
    draws the native opaque fill with zero glyph contribution, preserving native
    color conversion rather than guessing a background color. Publish these
    sources separately with their respective authored opacity, backing first.

    A qualified caller may independently select the room-status glyph/fill
    affine for capture, even when native menu insertion changes sibling order.
    Its previous scope is restored, not decremented or left active afterward.

    A local x86 SEH registration restores all five font-option words, backing
    opacity and the borrowed affine during unwind, without swallowing the exception. Installing
    callers must verify compatible executable exception metadata first.
    """
    e = X86Emitter(base_va=wrapper_va)

    def state(opcode: bytes, offset: int, suffix: bytes = b"") -> None:
        e.raw(opcode + struct.pack("<I", state_va + offset) + suffix)

    e.raw(bytes.fromhex("9c 60"))
    for address in (state_va + HUD_ENABLED, capture_active_va):
        e.raw(b"\x83\x3d" + struct.pack("<I", address) + b"\x01")
        e.jump_if(Condition.NOT_EQUAL, "native")
    state(b"\x83\x3d", HUD_BUSY, b"\x00")
    e.jump_if(Condition.NOT_EQUAL, "native")
    state(b"\x3b\x0d", HUD_OWNER)
    e.jump_if(Condition.NOT_EQUAL, "native")
    state(b"\xc7\x05", HUD_READY, bytes(4))
    e.raw(b"\x81\x39" + struct.pack("<I", class_vtable))
    e.jump_if(Condition.NOT_EQUAL, "native")
    e.raw(bytes.fromhex("80 79 18 00"))
    e.jump_if(Condition.EQUAL, "native")
    e.raw(bytes.fromhex("83 79 5c 01"))
    e.jump_if(Condition.ABOVE, "native")
    e.raw(b"\xb8" + struct.pack("<I", _ONE))
    e.jump_if(Condition.EQUAL, "fade")
    e.jump("glyph_ready")
    e.label("fade")
    e.raw(bytes.fromhex("8b 41 60"))
    e.raw(b"\x3d" + struct.pack("<I", _ONE))
    e.jump_if(Condition.ABOVE, "native")
    # XR source-over can represent native (source, 1-source), not arbitrary
    # destination darkening. Compute the single-precision complement with a
    # local, masked round-to-nearest SSE environment; restore XMM0/MXCSR even
    # when the native mode is unsupported. Neither x87 nor caller FP flags
    # are borrowed by the capture. A failed match remains entirely native.
    e.raw(
        bytes.fromhex(
            "68 00 00 80 3f 83 ec 18 f3 0f 7f 04 24 0f ae 5c 24 10 "
            "8b 54 24 10 81 e2 bf 1f ff ff 81 ca 80 1f 00 00 89 54 24 14 "
            "0f ae 54 24 14 f3 0f 10 44 24 18 f3 0f 5c 41 60 66 0f 7e c2 "
            "0f ae 54 24 10 f3 0f 6f 04 24 83 c4 1c 3b 51 64"
        )
    )
    e.jump_if(Condition.NOT_EQUAL, "native")
    # EAX still holds the accepted native source weight.
    e.label("glyph_ready")
    state(b"\xa3", HUD_GLYPH_OPACITY)
    e.raw(bytes.fromhex("8b 81 88 00 00 00"))
    e.raw(b"\x3d" + struct.pack("<I", _ONE))
    e.jump_if(Condition.ABOVE, "native")
    state(b"\xa3", HUD_BACKGROUND_OPACITY)
    for source, destination in (
        *((_TEXT_OPTIONS + index * 4, HUD_SAVED_OPTIONS + index * 4) for index in range(5)),
        (_TEXT_BACKGROUND, HUD_SAVED_BACKGROUND),
    ):
        e.raw(b"\x8b\x81" + struct.pack("<I", source))
        state(b"\xa3", destination)

    if font_scope_va is not None:
        e.raw(b"\xa1" + struct.pack("<I", font_scope_va))
        state(b"\xa3", HUD_SAVED_FONT_SCOPE)

    e.push_imm32(state_va)
    e.push_imm32(unwind_va)
    e.raw(bytes.fromhex("64 ff 35 00 00 00 00 64 89 25 00 00 00 00"))
    state(b"\x89\x25", HUD_REGISTRATION)
    state(b"\xc7\x05", HUD_BUSY, struct.pack("<I", 1))
    # The isolated source has original opaque glyph pixels, not a fade already
    # mixed with a desktop background. Opacity belongs to later XR composition.
    for offset, value in (
        (_TEXT_OPTIONS, 1 if backing else 0),
        (_TEXT_OPTIONS + 4, 0 if backing else _ONE),
        (_TEXT_OPTIONS + 8, _ONE if backing else 0),
    ):
        e.raw(b"\xc7\x81" + struct.pack("<II", offset, value))
    e.raw(bytes.fromhex("c7 81 88 00 00 00") + struct.pack("<I", _ONE if backing else 0))
    if font_scope_va is not None:
        e.raw(b"\xc7\x05" + struct.pack("<II", font_scope_va, 1))
    # Restore native register/flag inputs from PUSHAD beneath the registration.
    for offset, opcode in (
        (12, b"\x8b\x7c\x24"),
        (16, b"\x8b\x74\x24"),
        (20, b"\x8b\x6c\x24"),
        (28, b"\x8b\x5c\x24"),
        (32, b"\x8b\x54\x24"),
        (36, b"\x8b\x4c\x24"),
        (40, b"\x8b\x44\x24"),
    ):
        e.raw(opcode + bytes((offset,)))
    e.raw(bytes.fromhex("ff 74 24 2c 9d ff 74 24 38 ff 74 24 38"))
    e.call_absolute(target_va)
    # Preserve EAX, EDX and flags from Draw across restoration, not helper state.
    e.raw(bytes.fromhex("89 44 24 28 89 54 24 20 9c 58 89 44 24 2c"))
    e.raw(bytes.fromhex("8b 14 24 64 89 15 00 00 00 00 83 c4 0c"))
    _restore(e, state_va, font_scope_va=font_scope_va)
    state(b"\xa1", HUD_OWNER)
    state(b"\xa3", HUD_CAPTURED_OWNER)
    state(b"\xc7\x05", HUD_READY, struct.pack("<I", 1))
    state(b"\xff\x05", HUD_COMPLETED)
    e.raw(bytes.fromhex("61 9d c2 08 00"))
    e.label("native")
    e.raw(bytes.fromhex("61 9d"))
    e.jump_absolute(target_va)
    return e.build()


def build_hud_text_unwind(
    *, wrapper_va: int, state_va: int, font_scope_va: int | None = None
) -> bytes:
    """Restore authored TextBox fields on this scope's actual SEH unwind."""
    e = X86Emitter(base_va=wrapper_va)

    def state(opcode: bytes, offset: int, suffix: bytes = b"") -> None:
        e.raw(opcode + struct.pack("<I", state_va + offset) + suffix)

    e.raw(bytes.fromhex("9c 60 8b 44 24 28 f7 40 04 06 00 00 00"))
    e.jump_if(Condition.EQUAL, "return")
    e.raw(bytes.fromhex("8b 54 24 2c"))
    state(b"\x3b\x15", HUD_REGISTRATION)
    e.jump_if(Condition.NOT_EQUAL, "return")
    e.raw(b"\x81\x7a\x08" + struct.pack("<I", state_va))
    e.jump_if(Condition.NOT_EQUAL, "return")
    state(b"\x83\x3d", HUD_BUSY, b"\x01")
    e.jump_if(Condition.NOT_EQUAL, "return")
    _restore(e, state_va, font_scope_va=font_scope_va)
    for offset in (HUD_READY, HUD_CAPTURED_OWNER):
        state(b"\xc7\x05", offset, bytes(4))
    state(b"\xff\x05", HUD_ABORTED)
    e.label("return")
    e.raw(bytes.fromhex("c7 44 24 1c 01 00 00 00 61 9d c3"))
    return e.build()
