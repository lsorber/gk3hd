"""Fit verified fullscreen movie content to the VR cinema, not desktop padding."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from gk3hd.patch.binary.x86 import Condition, X86Emitter

if TYPE_CHECKING:
    from gk3hd.patch.builds import BuildProfile


def movie_extent(
    profile: BuildProfile,
    *,
    entry: int,
    frame: int,
    scratch: int,
    width: int,
    height: int,
    operation: int,
) -> bytes:
    """Uniformly fit a live software-movie rectangle into the ordinary cinema.

    Leave native layout, decoder, timing/audio and the source page untouched.
    The UI manager's cached root or last native 16-byte deque entry must be
    readable. Unknown/custom/embedded/overlay movies retain ordinary sizing.
    The two scratch words belong to the private panel, not a game object.
    """
    e = X86Emitter(base_va=entry)
    e.raw(bytes.fromhex("9c 60"))
    e.raw(b"\x83\x3d" + struct.pack("<I", operation) + b"\x00")
    e.jump_if(Condition.EQUAL, "opaque")
    e.raw(b"\x83\x3d" + struct.pack("<I", operation) + b"\x05")
    e.jump_if(Condition.NOT_EQUAL, "done")
    e.label("opaque")

    def readable(size: int) -> None:
        e.raw(bytes.fromhex("85 f6"))
        e.jump_if(Condition.EQUAL, "done")
        e.push_imm32(size)
        e.raw(b"\x56\xff\x15" + struct.pack("<I", profile.address("win32.IsBadReadPtr")))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "done")

    e.raw(b"\x8b\x35" + struct.pack("<I", profile.address("engine.loop")))
    readable(0x448)
    e.raw(bytes.fromhex("8b b6 44 04 00 00"))
    readable(0x48)
    e.raw(bytes.fromhex("8b 76 44"))
    readable(0x5C)
    e.raw(bytes.fromhex("8b 46 58 85 c0"))
    e.jump_if(Condition.NOT_EQUAL, "cached")
    e.raw(bytes.fromhex("8b 4e 44 8b 56 3c 39 d1"))
    e.jump_if(Condition.BELOW, "done")
    e.jump_if(Condition.EQUAL, "previous_block")
    e.raw(bytes.fromhex("89 c8 29 d0 3d 00 10 00 00"))
    e.jump_if(Condition.ABOVE, "done")
    e.raw(bytes.fromhex("a8 0f"))
    e.jump_if(Condition.NOT_EQUAL, "done")
    e.raw(bytes.fromhex("8d 71 f0"))
    e.jump("root_slot")
    e.label("previous_block")
    e.raw(bytes.fromhex("85 d2"))
    e.jump_if(Condition.EQUAL, "done")
    e.raw(bytes.fromhex("8b 76 48 83 fe 04"))
    e.jump_if(Condition.BELOW, "done")
    e.raw(bytes.fromhex("83 ee 04"))
    readable(4)
    e.raw(bytes.fromhex("8b 36"))
    readable(0x1000)
    e.raw(bytes.fromhex("81 c6 f0 0f 00 00"))
    e.label("root_slot")
    readable(4)
    e.raw(bytes.fromhex("8b 06"))
    e.label("cached")
    e.raw(bytes.fromhex("89 c6"))
    readable(0x144)
    e.raw(b"\x81\x3e" + struct.pack("<I", profile.address("movies.layer_vtable")))
    e.jump_if(Condition.NOT_EQUAL, "done")
    for offset in (0x18, 0x19):
        e.raw(bytes((0x80, 0x7E, offset, 0)))
        e.jump_if(Condition.EQUAL, "done")
    e.raw(bytes.fromhex("80 be 40 01 00 00 00"))
    e.jump_if(Condition.EQUAL, "done")
    e.raw(bytes.fromhex("89 f7 8b b6 3c 01 00 00"))
    readable(0x68)
    e.raw(b"\x81\x3e" + struct.pack("<I", profile.address("movies.bink_vtable")))
    e.jump_if(Condition.NOT_EQUAL, "done")
    for instruction in ("80 7e 50 00", "83 7e 64 00"):
        e.raw(bytes.fromhex(instruction))
        e.jump_if(Condition.NOT_EQUAL, "done")
    for address in (frame + 8, frame + 12):
        e.raw(b"\xa1" + struct.pack("<I", address) + bytes.fromhex("85 c0"))
        e.jump_if(Condition.LESS_OR_EQUAL, "done")
        e.raw(bytes.fromhex("3d 00 80 00 00"))
        e.jump_if(Condition.ABOVE, "done")
    # Root and actual decoder destination must agree before excluding borders.
    for offset in range(0, 16, 4):
        e.raw(bytes((0x8B, 0x47, 0x1C + offset, 0x3B, 0x46, 0x40 + offset)))
        e.jump_if(Condition.NOT_EQUAL, "done")
    for offset in (0x1C, 0x20):
        e.raw(bytes((0x83, 0x7F, offset, 0)))
        e.jump_if(Condition.LESS, "done")
    for offset, bound in ((0x24, frame + 8), (0x28, frame + 12)):
        e.raw(bytes((0x8B, 0x47, offset)) + b"\x3b\x05" + struct.pack("<I", bound))
        e.jump_if(Condition.ABOVE, "done")
    e.raw(bytes.fromhex("8b 5f 24 2b 5f 1c 8b 6f 28 2b 6f 20"))
    for instruction in ("85 db", "85 ed"):
        e.raw(bytes.fromhex(instruction))
        e.jump_if(Condition.LESS_OR_EQUAL, "done")
    e.raw(b"\x89\x1d" + struct.pack("<I", scratch))
    e.raw(b"\x89\x2d" + struct.pack("<I", scratch + 4))
    # The cinema is 2.4 x 1.5 metres, independently of mirror aspect/size.
    # Compare movie aspect with its exact 8:5 ratio without integer overflow.
    e.raw(bytes.fromhex("8d 04 ed 00 00 00 00 8d 14 9b 39 d0"))
    e.jump_if(Condition.ABOVE, "height")
    numerator, denominator = frame + 8, scratch
    e.raw(b"\xdb\x05" + struct.pack("<I", numerator))
    e.raw(b"\xda\x35" + struct.pack("<I", denominator))
    e.raw(b"\xd8\x0d" + struct.pack("<I", width))
    e.jump("store")
    e.label("height")
    e.raw(b"\xdb\x05" + struct.pack("<I", frame + 8))
    e.raw(b"\xda\x35" + struct.pack("<I", scratch + 4))
    e.raw(b"\xd8\x0d" + struct.pack("<I", height))
    e.label("store")
    e.raw(b"\xd9\x1d" + struct.pack("<I", frame + 20))
    e.label("done")
    e.raw(bytes.fromhex("61 9d c3"))
    return e.build(maximum_size=0x400)
