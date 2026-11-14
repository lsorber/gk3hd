"""Emit the game-side status cache key for the renderer's exact atlas check."""

from __future__ import annotations

import struct

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.vr_hud import REUSE_HIT, emit_hud_opacities

_RECORDED = 16
_PREVIOUS = 0x40
_CURRENT = 0x480
_FONT = 0x60
_FONT_BYTES = 0x360
_TEXT = _FONT + _FONT_BYTES
_TEXT_BYTES = 128
_KEY_BYTES = _TEXT + _TEXT_BYTES
REUSE_STATE_SIZE = _CURRENT + _KEY_BYTES

REUSE_EXPORT = b"Gk3hdXrGlyphReuseV1\0"


def build_hud_reuse_probe(
    *,
    wrapper_va: int,
    state_va: int,
    cache_va: int,
    stereo_only_va: int,
    class_vtable: int,
    display_va: int,
    manager_va: int,
    readable_iat_va: int,
    module_iat_va: int,
    proc_iat_va: int,
    renderer_name_va: int,
    export_name_va: int,
) -> bytes:
    """Require the supported native atlas and compare the original draw inputs.

    Called after cache descriptor and key preparation, before clearing or
    binding the private destination. The renderer owns the atlas pixel
    comparison. The native key excludes opacity, which is checked live and
    applied later. Every exit preserves flags, registers and FP state except
    EAX, which is one only when the renderer can reuse the earlier draw.
    """
    e = X86Emitter(base_va=wrapper_va)

    def absolute(opcode: bytes, address: int, suffix: bytes = b"") -> None:
        e.raw(opcode + struct.pack("<I", address) + suffix)

    def word(opcode: bytes, offset: int, suffix: bytes = b"") -> None:
        absolute(opcode, state_va + offset, suffix)

    def readable(register: int, count: int) -> None:
        e.push_imm32(count)
        e.raw(bytes((0x50 + register,)))
        absolute(b"\xff\x15", readable_iat_va)
        e.raw(b"\x85\xc0")
        e.jump_if(Condition.NOT_EQUAL, "reject")

    e.raw(b"\x9c")
    absolute(b"\x83\x3d", stereo_only_va, b"\x01")
    e.jump_if(Condition.NOT_EQUAL, "inactive")
    e.raw(bytes.fromhex("60 8b ec 81 ec 10 02 00 00 83 e4 f0 0f ae 04 24 fc"))
    word(b"\xc7\x05", REUSE_HIT, bytes(4))
    absolute(b"\x8b\x1d", cache_va + 32)
    readable(3, 0x8C)  # EBX: the live TextBox selected by the caller.
    e.raw(b"\x81\x3b" + struct.pack("<I", class_vtable))
    e.jump_if(Condition.NOT_EQUAL, "reject")
    e.raw(bytes.fromhex("80 7b 18 00"))
    e.jump_if(Condition.EQUAL, "reject")
    e.raw(b"\x8b\xcb")
    emit_hud_opacities(e, reject="reject")

    word(b"\xbf", _CURRENT)
    e.raw(b"\x31\xc0\xb9" + struct.pack("<I", _FONT // 4) + b"\xf3\xab")
    word(b"\x89\x1d", _CURRENT)
    # Original rectangle, horizontal offset, font object and options which
    # survive the scope's normalization of opacity and blend mode.
    for index, field in enumerate((0x1C, 0x20, 0x24, 0x28, 0x3C, 0x40, 0x68, 0x6C, 0x84), 1):
        e.raw(b"\x8b\x83" + struct.pack("<I", field))
        word(b"\xa3", _CURRENT + index * 4)
    for index, address in enumerate(
        (display_va, display_va + 4, cache_va + 16, cache_va + 24, cache_va + 28, manager_va), 10
    ):
        absolute(b"\xa1", address)
        word(b"\xa3", _CURRENT + index * 4)

    e.raw(bytes.fromhex("8b 73 40"))
    readable(6, _FONT_BYTES)  # ESI: the native font object.
    e.raw(bytes.fromhex("83 7e 4c 01"))
    e.jump_if(Condition.GREATER, "reject")  # Multirow fonts dereference additional tables.
    word(b"\xbf", _CURRENT + _FONT)
    e.raw(b"\xb9" + struct.pack("<I", _FONT_BYTES // 4) + b"\xf3\xa5")
    e.raw(bytes.fromhex("8b 73 30"))
    readable(6, _TEXT_BYTES)
    e.raw(bytes.fromhex("80 3e 00"))
    e.jump_if(Condition.EQUAL, "reject")
    word(b"\xbf", _CURRENT + _TEXT)
    e.raw(b"\x31\xc0\xb9" + struct.pack("<I", _TEXT_BYTES // 4) + b"\xf3\xab")
    word(b"\xbf", _CURRENT + _TEXT)
    e.raw(b"\xb9" + struct.pack("<I", _TEXT_BYTES))
    e.label("copy_text")
    e.raw(bytes.fromhex("ac aa 84 c0"))
    e.jump_if(Condition.EQUAL, "compare")
    e.raw(b"\x49")
    e.jump_if(Condition.NOT_EQUAL, "copy_text")
    e.jump("reject")

    e.label("compare")
    e.raw(b"\x31\xdb")
    word(b"\x83\x3d", _RECORDED, b"\x01")
    e.jump_if(Condition.NOT_EQUAL, "record")
    word(b"\xbe", _CURRENT)
    word(b"\xbf", _PREVIOUS)
    e.raw(b"\xb9" + struct.pack("<I", _KEY_BYTES // 4) + bytes.fromhex("f3 a7 0f 94 c3"))
    e.label("record")
    word(b"\xbe", _CURRENT)
    word(b"\xbf", _PREVIOUS)
    e.raw(b"\xb9" + struct.pack("<I", _KEY_BYTES // 4) + b"\xf3\xa5")

    # Resolve the same live bitmap as the native font draw. The supported
    # 5864x72 atlas cannot match any current padded or paired-bank layout.
    word(b"\x0f\xb7\x3d", _CURRENT + _FONT + 4)
    absolute(b"\x8b\x35", manager_va)
    readable(6, 0x128)
    e.raw(bytes.fromhex("3b be 24 01 00 00"))
    e.jump_if(Condition.ABOVE_OR_EQUAL, "reject")
    e.raw(bytes.fromhex("8b b6 20 01 00 00 85 f6"))
    e.jump_if(Condition.EQUAL, "reject")
    e.raw(bytes.fromhex("8d 34 be"))
    readable(6, 4)
    e.raw(bytes.fromhex("8b 36"))
    readable(6, 0x34)
    e.raw(bytes.fromhex("8b 76 30"))
    readable(6, 0x50)
    e.raw(bytes.fromhex("81 7e 38 e8 16 00 00"))
    e.jump_if(Condition.NOT_EQUAL, "reject")
    e.raw(bytes.fromhex("83 7e 3c 48"))
    e.jump_if(Condition.NOT_EQUAL, "reject")
    e.raw(bytes.fromhex("8b 76 2c 85 f6"))
    e.jump_if(Condition.EQUAL, "reject")

    e.push_imm32(renderer_name_va)
    absolute(b"\xff\x15", module_iat_va)
    e.raw(b"\x85\xc0")
    e.jump_if(Condition.EQUAL, "reject")
    e.push_imm32(export_name_va)
    e.raw(b"\x50")
    absolute(b"\xff\x15", proc_iat_va)
    e.raw(b"\x85\xc0")
    e.jump_if(Condition.EQUAL, "reject")
    word(b"\xc7\x05", _RECORDED, struct.pack("<I", 1))
    e.raw(b"\x53")
    for offset in (48, 44, 0x74):
        absolute(b"\xff\x35", cache_va + offset)
    e.push_imm32(cache_va + 20)
    e.raw(b"\x56")
    absolute(b"\xff\x35", cache_va + 4)
    e.raw(bytes.fromhex("ff d0 85 c0 0f 94 c0 0f b6 c0"))
    word(b"\xa3", REUSE_HIT)
    e.jump("return")

    e.label("reject")
    word(b"\xc7\x05", _RECORDED, bytes(4))
    e.raw(b"\x31\xc0")
    e.label("return")
    e.raw(bytes.fromhex("0f ae 0c 24 8b e5 89 44 24 1c 61 9d c3"))
    e.label("inactive")
    for offset in (REUSE_HIT, _RECORDED):
        word(b"\xc7\x05", offset, bytes(4))
    e.raw(bytes.fromhex("9d b8 00 00 00 00 c3"))
    return e.build()
