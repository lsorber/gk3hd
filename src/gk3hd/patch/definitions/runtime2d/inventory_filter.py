"""Adapt dense Inventory alpha tiles to the renderer's area-filter capability."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.layout import (
    INVENTORY_FILTER_SEGMENT,
    install_runtime_segment,
)

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile

WRAPPER_OFFSET = 0x100
NAMES_OFFSET = 0x400
CACHE_OFFSET = 0x20
CALL_COUNT_OFFSET = 0x24
HANDLED_COUNT_OFFSET = 0x28
REQUEST_SIZE = 68


def build_area_adapter(
    *,
    profile: BuildProfile,
    filter_va: int,
    native_va: int,
    dense_source_va: int,
    source_rect_va: int,
    dest_width_va: int,
    dest_height_va: int,
) -> bytes:
    """Pass one stack-local locked-buffer view; decline without changing native input.

    The original thiscall receives destination, pitch, tile size and tile origin.
    Its effect owns RGB565/L8 locked buffers. The versioned renderer request is
    17 x86 words; it exposes neither the effect's layout nor its lifetime to the
    renderer. Native-size images and the separate font virtual never filter.
    """
    code = X86Emitter(base_va=filter_va + WRAPPER_OFFSET)
    code.raw(b"\x83\x3d" + struct.pack("<I", dense_source_va) + b"\x00")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x60\x8b\xec")  # Preserve input registers; EBP anchors PUSHAD.
    code.raw(b"\x8b\x1d" + struct.pack("<I", filter_va + CACHE_OFFSET))
    code.raw(b"\x83\xfb\xff")
    code.jump_if(Condition.EQUAL, "unwind")
    code.raw(b"\x85\xdb")
    code.jump_if(Condition.NOT_EQUAL, "request")
    code.raw(b"\x68" + struct.pack("<I", filter_va + NAMES_OFFSET))
    code.raw(b"\xff\x15" + struct.pack("<I", profile.address("win32.GetModuleHandleA")))
    code.raw(b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "unwind")  # Do not cache an unloaded module.
    code.raw(b"\x68" + struct.pack("<I", filter_va + NAMES_OFFSET + 16) + b"\x50")
    code.raw(b"\xff\x15" + struct.pack("<I", profile.address("win32.GetProcAddress")))
    code.raw(b"\x89\xc3\x85\xdb")
    code.jump_if(Condition.NOT_EQUAL, "resolved")
    code.raw(b"\x83\xcb\xff")
    code.label("resolved")
    code.raw(b"\x89\x1d" + struct.pack("<I", filter_va + CACHE_OFFSET))
    code.raw(b"\x83\xfb\xff")
    code.jump_if(Condition.EQUAL, "unwind")
    code.label("request")
    code.raw(b"\x83\xec" + bytes([REQUEST_SIZE]) + b"\x8b\xfc\x8b\x75\x18")
    code.raw(b"\xc7\x07" + struct.pack("<I", REQUEST_SIZE))
    # Effect source, alpha, pitches, key, and mask-compensated opacity.
    for source, target in (
        (0x30, 4),
        (0x40, 8),
        (0x34, 0x10),
        (0x44, 0x14),
        (0x38, 0x3C),
        (0x48, 0x40),
    ):
        code.raw(b"\x8b\x46" + bytes([source]) + b"\x89\x47" + bytes([target]))
    # Original destination and destination pitch follow the return address.
    for source, target in ((0x24, 0x0C), (0x28, 0x18)):
        code.raw(b"\x8b\x45" + bytes([source]) + b"\x89\x47" + bytes([target]))
    for first, last, target in ((0, 8, 0x1C), (4, 12, 0x20)):
        code.raw(b"\xa1" + struct.pack("<I", source_rect_va + last))
        code.raw(b"\x2b\x05" + struct.pack("<I", source_rect_va + first))
        code.raw(b"\x89\x47" + bytes([target]))
    for address, target in ((dest_width_va, 0x24), (dest_height_va, 0x28)):
        code.raw(b"\xa1" + struct.pack("<I", address) + b"\x89\x47" + bytes([target]))
    for source, target in ((0x30, 0x2C), (0x2C, 0x34)):
        code.raw(b"\x8b\x55" + bytes([source]))
        code.raw(b"\x8b\x02\x89\x47" + bytes([target]))
        code.raw(b"\x8b\x42\x04\x89\x47" + bytes([target + 4]))
    code.raw(b"\xff\x05" + struct.pack("<I", filter_va + CALL_COUNT_OFFSET))
    code.raw(b"\x57\xff\xd3")  # DWORD stdcall(const AreaBlend565Args*).
    code.raw(b"\x01\x05" + struct.pack("<I", filter_va + HANDLED_COUNT_OFFSET))
    code.raw(b"\x83\xc4" + bytes([REQUEST_SIZE]) + b"\x85\xc0\x61")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\xc2\x10\x00")
    code.label("unwind")
    code.raw(b"\x61")
    code.label("native")
    code.jump_absolute(native_va)
    return code.build(maximum_size=NAMES_OFFSET - WRAPPER_OFFSET)


def install_area_adapter(
    image: PEFile,
    *,
    profile: BuildProfile,
    native_va: int,
    dense_source_va: int,
    source_rect_va: int,
    dest_width_va: int,
    dest_height_va: int,
) -> int:
    """Emit a bounded Inventory-owned capability adapter, not another DLL loader."""
    section = install_runtime_segment(image, INVENTORY_FILTER_SEGMENT)
    base = image.rva_to_va(section.virtual_address)
    payload = SegmentPayloadBuilder(
        owner="runtime2d.inventory",
        segment=INVENTORY_FILTER_SEGMENT.logical_name,
        size=INVENTORY_FILTER_SEGMENT.size,
    )
    payload.place(label="magic", offset=0, payload=INVENTORY_FILTER_SEGMENT.magic)
    payload.place(label="version", offset=8, payload=struct.pack("<I", 1))
    payload.reserve(label="capability cache and counters", offset=CACHE_OFFSET, size=12)
    payload.place(
        label="dense item area adapter",
        offset=WRAPPER_OFFSET,
        payload=build_area_adapter(
            profile=profile,
            filter_va=base,
            native_va=native_va,
            dense_source_va=dense_source_va,
            source_rect_va=source_rect_va,
            dest_width_va=dest_width_va,
            dest_height_va=dest_height_va,
        ),
        limit=NAMES_OFFSET,
    )
    payload.place(
        label="renderer capability names",
        offset=NAMES_OFFSET,
        payload=b"ddraw.dll\0".ljust(16, b"\0") + b"Gk3hdAreaBlend565\0",
    )
    image.write_bytes(section.pointer_to_raw_data, payload.build())
    return base + WRAPPER_OFFSET
