"""Exact animated-cursor identity and logical/dense source contracts."""

from __future__ import annotations

import struct

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.textures.upscale.cursor_art import CURSOR_ART_FRAMES

_NAME_BYTES = 16


def build_resource_match(*, wrapper_va: int) -> bytes:
    """Match ESI's complete name and EAX's exact dense surface against one table.

    Return carry and ECX's immutable layout row on a match. Other registers
    survive; ECX also survives a miss. Both geometry and drawing use this same
    contract, without duplicating a growing chain of machine-code comparisons.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x60\xbb")  # PUSHAD; EBX = table.
    code.absolute_label("table")
    code.raw(b"\xbd" + struct.pack("<I", len(CURSOR_ART_FRAMES)))
    code.raw(b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "no")
    code.raw(b"\x85\xf6")
    code.jump_if(Condition.EQUAL, "no")
    code.label("next")
    code.raw(b"\x8b\x0b\x8d\x7b\x04\x56\x83\xc6\x08\xfc\xf3\xa6\x5e")
    code.jump_if(Condition.NOT_EQUAL, "miss")
    for source, surface in ((32, 0x38), (24, 0x3C)):
        code.raw(b"\x8b\x53" + bytes([source]) + b"\xc1\xe2\x02\x39\x50" + bytes([surface]))
        code.jump_if(Condition.NOT_EQUAL, "miss")
    code.raw(b"\x89\x5c\x24\x18\x61\xf9\xc3")
    code.label("miss")
    code.raw(b"\x83\xc3\x24\x4d")  # 36-byte row; next entry.
    code.jump_if(Condition.NOT_EQUAL, "next")
    code.label("no")
    code.raw(b"\x61\xf8\xc3")
    code.label("table")
    for name, (width, height, frames) in CURSOR_ART_FRAMES.items():
        stem = name.removesuffix(".BMP").encode("ascii") + b"\0"
        if len(stem) > _NAME_BYTES:
            msg = f"cursor resource name exceeds the native matcher slot: {name}"
            raise ValueError(msg)
        code.raw(struct.pack("<I16s4I", len(stem), stem, width, height, frames, width * frames))
    return code.build()


def emit_logical_dimensions(code: X86Emitter, *, logical_va: int, match_va: int) -> None:
    """Return original strip metrics only for exact supported dense resources."""
    code.call_absolute(match_va)
    code.jump_if(Condition.ABOVE_OR_EQUAL, "cursor_dimensions_miss")
    for source, destination in ((32, logical_va), (24, logical_va + 4)):
        code.raw(b"\x8b\x51" + bytes([source]) + b"\x89\x15" + struct.pack("<I", destination))
    code.raw(b"\xb8" + struct.pack("<I", logical_va))
    code.jump("done")
    code.label("cursor_dimensions_miss")


def build_density_probe(
    *, wrapper_va: int, manager_va: int, resolve_va: int, match_va: int
) -> bytes:
    """Return CF for EAX's live drawable using EDX's exact resolved dense source.

    No surface pointer survives this synchronous call. Validate native frame
    dimensions/count as well as resource identity: a dense strip is not a large
    static cursor. Preserve all registers; only carry is the result.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x60\x85\xc0")
    code.jump_if(Condition.EQUAL, "no")
    code.raw(b"\x89\xc3\x89\xd7")  # EBX drawable, EDI final source wrapper.
    code.raw(b"\x8b\x0d" + struct.pack("<I", manager_va) + b"\x85\xc9")
    code.jump_if(Condition.EQUAL, "no")
    code.raw(b"\xff\x73\x20")
    code.call_absolute(resolve_va)
    code.raw(b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "no")
    code.raw(b"\x89\xc6\x8b\x46\x30\x85\xc0")
    code.jump_if(Condition.EQUAL, "no")
    code.raw(b"\x39\xf8")
    code.jump_if(Condition.NOT_EQUAL, "no")
    code.call_absolute(match_va)
    code.jump_if(Condition.ABOVE_OR_EQUAL, "no")
    for offset, layout in ((0x24, 20), (0x28, 24), (0x2C, 28)):
        code.raw(b"\x8b\x51" + bytes([layout]) + b"\x39\x53" + bytes([offset]))
        code.jump_if(Condition.NOT_EQUAL, "no")
    code.raw(b"\x61\xf9\xc3")
    code.label("no")
    code.raw(b"\x61\xf8\xc3")
    return code.build()
