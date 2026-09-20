"""Preserve native cursor opacity when source and display densities differ."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.inventory_alpha import build_native_alpha_resampler
from gk3hd.patch.definitions.runtime2d.layout import CURSOR_BLEND_SEGMENT, install_runtime_segment

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile

ENTRY = 0x100
CALLBACK = 0x400
SOURCE = 0x20
WIDTH = 0x30
HEIGHT = 0x34
VTABLE = 0x40
TRACE = 0x60


def build_blend_wrapper(*, profile: BuildProfile, base: int) -> bytes:
    """Draw one already clipped/scaled cursor fragment with its original options.

    Thiscall: destination surface; source surface, destination RECT, source RECT,
    options. The caller proves cursor ownership and supplies physical rectangles.
    Ordinary keyed copies retain the native stretch path. Software effects use
    the native constructor, executor, one-pixel blend callback and destructor;
    only the mapping from destination samples to source samples is replaced.
    """
    code = X86Emitter(base_va=base + ENTRY)
    # The 0x50-byte native effect occupies -0x60..-0x11; locals above it and
    # saved registers below it cannot alias the object's last opacity fields.
    code.raw(b"\x55\x8b\xec\x83\xec\x60\x53\x56\x57")
    code.raw(b"\x89\x4d\xf8\x8b\x45\x14\x85\xc0")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x83\x38\x00")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x89\x45\xfc")
    # Match the stock fast-blit eligibility check before constructing a
    # software effect. Unavailable locks take the same native copy fallback.
    for offset in (8, -8):
        code.raw(b"\x8b\x4d" + bytes([offset & 0xFF]) + b"\x68\xff\xff\x00\x00")
        code.call_absolute(profile.address("bitmap.effect_lockable"))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x8b\x75\x10\xbf" + struct.pack("<I", base + SOURCE))
    code.raw(b"\xb9\x04\x00\x00\x00\xfc\xf3\xa5\x8b\x75\x0c")
    for offset, destination in ((0, WIDTH), (4, HEIGHT)):
        code.raw(b"\x8b\x46" + bytes([offset + 8]) + b"\x2b\x46" + bytes([offset]))
        code.raw(b"\xa3" + struct.pack("<I", base + destination))
    code.raw(b"\xff\x75\xfc\xff\x75\x10\xff\x75\x0c\xff\x75\x08\xff\x75\xf8")
    code.raw(b"\x8d\x4d\xa0")
    code.call_absolute(profile.address("bitmap.effect_constructor"))
    code.raw(b"\xc7\x00" + struct.pack("<I", base + VTABLE) + b"\x8b\xc8")
    code.call_absolute(profile.address("bitmap.effect_executor"))
    code.raw(b"\x8d\x4d\xa0")
    code.call_absolute(profile.address("bitmap.effect_destructor"))
    code.raw(b"\xb8\x01\x00\x00\x00")
    code.jump("done")
    code.label("native")
    code.raw(b"\xff\x75\x10\xff\x75\x0c\xff\x75\x08\x8b\x4d\xf8")
    code.call_absolute(profile.address("runtime2d.final_stretch_blt"))
    code.label("done")
    code.raw(b"\x5f\x5e\x5b\xc9\xc2\x10\x00")
    return code.build()


def install_blend_adapter(image: PEFile, *, profile: BuildProfile) -> None:
    """Install the cursor-owned adapter and its synchronous resampling state."""
    section = install_runtime_segment(image, CURSOR_BLEND_SEGMENT)
    base = image.rva_to_va(section.virtual_address)
    payload = SegmentPayloadBuilder(
        owner="runtime2d.cursor_blend",
        segment=CURSOR_BLEND_SEGMENT.logical_name,
        size=CURSOR_BLEND_SEGMENT.size,
    )
    payload.place(label="magic", offset=0, payload=CURSOR_BLEND_SEGMENT.magic)
    payload.place(label="version", offset=8, payload=struct.pack("<I", 1))
    payload.reserve(label="source rectangle and destination extents", offset=SOURCE, size=24)
    payload.place(
        label="native effect executor and resampling callback",
        offset=VTABLE,
        payload=struct.pack("<II", profile.address("bitmap.effect_executor"), base + CALLBACK),
    )
    payload.reserve(label="resampling diagnostics", offset=TRACE, size=40)
    payload.place(
        label="blend dispatcher",
        offset=ENTRY,
        payload=build_blend_wrapper(profile=profile, base=base),
        limit=CALLBACK,
    )
    payload.place(
        label="native blend resampler",
        offset=CALLBACK,
        payload=build_native_alpha_resampler(
            callback_va=base + CALLBACK,
            native_callback_va=profile.address("bitmap.effect_callback"),
            source_rect_va=base + SOURCE,
            dest_width_va=base + WIDTH,
            dest_height_va=base + HEIGHT,
            trace_va=base + TRACE,
            center_samples=True,
        ),
    )
    image.write_bytes(section.pointer_to_raw_data, payload.build())
