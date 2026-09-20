"""Request area minification for explicitly identified opaque detailed artwork."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.layout import UI_FILTER_SEGMENT, install_runtime_segment
from gk3hd.patch.definitions.runtime2d.ui_frames import (
    DETAILED_ACTION_IMAGES,
    OPAQUE_INVENTORY_IMAGES,
    build_resource_match,
    build_surface_match,
)

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile

WRAPPER_OFFSET = 0x100
SURFACE_MATCH_OFFSET = 0x600
RESOURCE_MATCH_OFFSET = 0x800
NAMES_OFFSET = 0x80
CACHE_OFFSET = 0x20
CALL_COUNT_OFFSET = 0x24
HANDLED_COUNT_OFFSET = 0x28
REQUEST_SIZE = 48
FILTER_IMAGES = DETAILED_ACTION_IMAGES + OPAQUE_INVENTORY_IMAGES


def build_area_adapter(*, profile: BuildProfile, base_va: int, native_va: int) -> bytes:
    """Filter after source/target normalization, preserving unsupported native calls.

    The native thiscall receives source wrapper, destination RECT and source
    RECT. The renderer request contains Surface1 interfaces and copied RECTs;
    it never receives game objects. A handled failure returns false rather than
    drawing again after possible writes. All request storage is stack-local.
    """
    code = X86Emitter(base_va=base_va + WRAPPER_OFFSET)
    code.raw(b"\x9c\x60\x8b\xec\x8b\x45\x28")
    code.call_absolute(base_va + SURFACE_MATCH_OFFSET)
    code.jump_if(Condition.ABOVE_OR_EQUAL, "native")
    # Opaque RGB only. Native source keys and software-alpha/fill paths are not
    # interchangeable with this explicit opaque minification operation.
    code.raw(b"\xf6\x40\x04\x09")
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(b"\x8b\x4d\x18\x85\xc9")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\xf6\x41\x04\x08")
    code.jump_if(Condition.NOT_EQUAL, "native")
    for register, offset in ((b"\x78", 0x2C), (b"\x79", 0x2C), (b"\x7d", 0x2C), (b"\x7d", 0x30)):
        code.raw(b"\x83" + register + bytes([offset]) + b"\x00")
        code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x8b\x1d" + struct.pack("<I", base_va + CACHE_OFFSET))
    code.raw(b"\x83\xfb\xff")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x85\xdb")
    code.jump_if(Condition.NOT_EQUAL, "request")
    code.raw(b"\x68" + struct.pack("<I", base_va + NAMES_OFFSET))
    code.raw(b"\xff\x15" + struct.pack("<I", profile.address("win32.GetModuleHandleA")))
    code.raw(b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x68" + struct.pack("<I", base_va + NAMES_OFFSET + 16) + b"\x50")
    code.raw(b"\xff\x15" + struct.pack("<I", profile.address("win32.GetProcAddress")))
    code.raw(b"\x89\xc3\x85\xdb")
    code.jump_if(Condition.NOT_EQUAL, "resolved")
    code.raw(b"\x83\xcb\xff")
    code.label("resolved")
    code.raw(b"\x89\x1d" + struct.pack("<I", base_va + CACHE_OFFSET))
    code.raw(b"\x83\xfb\xff")
    code.jump_if(Condition.EQUAL, "native")
    code.label("request")
    code.raw(b"\x83\xec" + bytes([REQUEST_SIZE]) + b"\x8b\xfc")
    code.raw(b"\xc7\x07" + struct.pack("<I", REQUEST_SIZE))
    for source, target in ((0x18, 4), (0x28, 8)):
        code.raw(b"\x8b\x45" + bytes([source]) + b"\x8b\x40\x2c\x89\x47" + bytes([target]))
    for source, target in ((0x2C, 12), (0x30, 28)):
        code.raw(b"\x8b\x75" + bytes([source]))
        for offset in range(0, 16, 4):
            code.raw(b"\x8b\x46" + bytes([offset]) + b"\x89\x47" + bytes([target + offset]))
    code.raw(b"\xc7\x47\x2c" + struct.pack("<I", 0x80004005))
    code.raw(b"\xff\x05" + struct.pack("<I", base_va + CALL_COUNT_OFFSET))
    code.raw(b"\x57\xff\xd3\x85\xc0")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\xff\x05" + struct.pack("<I", base_va + HANDLED_COUNT_OFFSET))
    code.raw(b"\x8b\x44\x24\x2c\xc1\xe8\x1f\x83\xf0\x01\x89\x45\x1c")
    code.raw(b"\x8b\xe5\x61\x9d\xc2\x0c\x00")
    code.label("native")
    code.raw(b"\x8b\xe5\x61\x9d")
    code.jump_absolute(native_va)
    return code.build(maximum_size=SURFACE_MATCH_OFFSET - WRAPPER_OFFSET)


def install_area_adapter(image: PEFile, *, profile: BuildProfile, native_va: int) -> int:
    """Install a bounded capability adapter and its small exact-name catalog."""
    section = install_runtime_segment(image, UI_FILTER_SEGMENT)
    base = image.rva_to_va(section.virtual_address)
    payload = SegmentPayloadBuilder(
        owner="runtime2d.ui_filter",
        segment=UI_FILTER_SEGMENT.logical_name,
        size=UI_FILTER_SEGMENT.size,
    )
    payload.place(label="identity", offset=0, payload=UI_FILTER_SEGMENT.magic)
    payload.reserve(label="capability cache and counters", offset=CACHE_OFFSET, size=12)
    payload.place(
        label="area adapter",
        offset=WRAPPER_OFFSET,
        payload=build_area_adapter(profile=profile, base_va=base, native_va=native_va),
        limit=SURFACE_MATCH_OFFSET,
    )
    payload.place(
        label="surface identity",
        offset=SURFACE_MATCH_OFFSET,
        payload=build_surface_match(
            wrapper_va=base + SURFACE_MATCH_OFFSET,
            resource_match_va=base + RESOURCE_MATCH_OFFSET,
            manager_va=profile.address("resource.manager"),
            images=FILTER_IMAGES,
        ),
        limit=RESOURCE_MATCH_OFFSET,
    )
    payload.place(
        label="resource identity",
        offset=RESOURCE_MATCH_OFFSET,
        payload=build_resource_match(wrapper_va=base + RESOURCE_MATCH_OFFSET, images=FILTER_IMAGES),
        limit=UI_FILTER_SEGMENT.size,
    )
    payload.place(
        label="capability names",
        offset=NAMES_OFFSET,
        payload=b"ddraw.dll\0".ljust(16, b"\0") + b"Gk3hdAreaBlt565\0",
    )
    image.write_bytes(section.pointer_to_raw_data, payload.build())
    return base + WRAPPER_OFFSET
