"""Keep revealed fingerprint overlays aligned through native software blending."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.inventory_alpha import build_native_alpha_resampler
from gk3hd.patch.definitions.runtime2d.layout import (
    FINGERPRINT_ALPHA_NORMALIZE_OFFSET,
    FINGERPRINT_ALPHA_SEGMENT,
    install_runtime_segment,
)
from gk3hd.patch.definitions.runtime2d.ui_frames import build_resource_match, build_surface_match
from gk3hd.textures.upscale.fingerprint import WORKSTATION_PRINT_SIZES

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile

# Exact original workstation print extents; A-suffixed opacity resources are
# not color sources. Native and fourfold sources share the same model units.
PRINT_IMAGES = tuple(
    (name.removesuffix(".BMP").lower().encode("ascii"), *size)
    for name, size in WORKSTATION_PRINT_SIZES.items()
)
CONSTRUCTOR = 0x100
CALLBACK = 0x400
NATIVE_SURFACE = 0x600
DENSE_SURFACE = 0x780
NATIVE_RESOURCE = 0x900
DENSE_RESOURCE = 0xC00
DEST = 0x20
SOURCE = 0x30
WIDTH = 0x40
HEIGHT = 0x44
VTABLE = 0x48
TRACE = 0x60


def build_constructor(
    *, profile: BuildProfile, base: int, root_va: int, hd_set_active_va: int
) -> bytes:
    """Adapt only live print resources going to the fingerprint screen itself."""
    code = X86Emitter(base_va=base + CONSTRUCTOR)
    code.raw(b"\x83\x3d" + struct.pack("<I", hd_set_active_va) + b"\x00")
    code.jump_if(Condition.NOT_EQUAL, "scope")
    code.jump_absolute(profile.address("bitmap.effect_constructor"))
    code.label("scope")
    code.raw(b"\x60\xa1" + struct.pack("<I", root_va) + b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x81\x38" + struct.pack("<I", profile.address("fingerprint.vtable")))
    code.jump_if(Condition.NOT_EQUAL, "native")
    # PUSHAD: arg1 destination surface +24, arg2 source surface +28.
    code.raw(b"\x8b\x54\x24\x24\x85\xd2")
    code.jump_if(Condition.EQUAL, "native")
    for axis in (0, 4):
        code.raw(b"\xa1" + struct.pack("<I", profile.address("display.dimensions") + axis))
        code.raw(b"\x3b\x42" + bytes([0x38 + axis]))
        code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(b"\x8b\x44\x24\x28")
    code.call_absolute(base + DENSE_SURFACE)
    code.raw(b"\xbd\x02\x00\x00\x00")
    code.jump_if(Condition.BELOW, "matched")
    code.call_absolute(base + NATIVE_SURFACE)
    code.jump_if(Condition.ABOVE_OR_EQUAL, "native")
    code.raw(b"\x31\xed")
    code.label("matched")
    code.raw(b"\x8b\xd8\x8b\x74\x24\x2c\x8b\x7c\x24\x30")
    code.raw(b"\x85\xf6")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x85\xff")
    code.jump_if(Condition.EQUAL, "native")
    # The high-level caller has already clipped source and destination in
    # raster units. Recover the complete anchor, then map its logical extent.
    for axis in (0, 4):
        code.raw(b"\x8b\x46" + bytes([axis]) + b"\x2b\x47" + bytes([axis]))
        code.raw(b"\x8b\x0d" + struct.pack("<I", profile.address("display.dimensions") + axis))
        code.raw(b"\xd1\xf9\x2b\xc1\x51")
        code.raw(b"\x0f\xaf\x05" + struct.pack("<I", profile.address("display.dimensions") + 4))
        code.raw(b"\x99\xb9\x00\x03\x00\x00\xf7\xf9\x59\x03\xc1")
        code.raw(b"\xa3" + struct.pack("<I", base + DEST + axis))
        code.raw(b"\x8b\x43" + bytes([0x38 + axis]) + b"\x8b\xcd\xd3\xe8")
        code.raw(b"\x0f\xaf\x05" + struct.pack("<I", profile.address("display.dimensions") + 4))
        code.raw(b"\x99\xb9\x00\x03\x00\x00\xf7\xf9")
        code.raw(b"\xa3" + struct.pack("<I", base + WIDTH + axis))
        code.raw(b"\x03\x05" + struct.pack("<I", base + DEST + axis))
        code.raw(b"\xa3" + struct.pack("<I", base + DEST + axis + 8))
        code.raw(b"\xc7\x05" + struct.pack("<I", base + SOURCE + axis) + bytes(4))
        code.raw(
            b"\x8b\x43"
            + bytes([0x38 + axis])
            + b"\xa3"
            + struct.pack("<I", base + SOURCE + axis + 8)
        )
    code.raw(b"\x61\xff\x74\x24\x14")
    code.raw(b"\x68" + struct.pack("<I", base + SOURCE))
    code.raw(b"\x68" + struct.pack("<I", base + DEST))
    code.raw(b"\xff\x74\x24\x14\xff\x74\x24\x14")
    code.call_absolute(profile.address("bitmap.effect_constructor"))
    code.raw(b"\xc7\x00" + struct.pack("<I", base + VTABLE) + b"\xc2\x14\x00")
    code.label("native")
    code.raw(b"\x61")
    code.jump_absolute(profile.address("bitmap.effect_constructor"))
    return code.build()


def build_normalize(*, base: int) -> bytes:
    """Normalize a live print node's hit bounds; retain all source pixels.

    EAX is the resolved resource, ECX the UI bitmap node. Preserve registers.
    """
    code = X86Emitter(base_va=base + FINGERPRINT_ALPHA_NORMALIZE_OFFSET)
    code.raw(b"\x60\x8b\xf0\x8b\xf9\x8b\x40\x30\x85\xc0")
    code.jump_if(Condition.EQUAL, "done")
    code.call_absolute(base + DENSE_RESOURCE)
    code.jump_if(Condition.ABOVE_OR_EQUAL, "done")
    for axis in (0, 4):
        code.raw(b"\x8b\x50" + bytes([0x38 + axis]) + b"\xc1\xea\x02")
        code.raw(b"\x03\x57" + bytes([0x1C + axis]) + b"\x89\x57" + bytes([0x24 + axis]))
    code.label("done")
    code.raw(b"\x61\xc3")
    return code.build()


def install_alpha_adapter(
    image: PEFile, *, profile: BuildProfile, root_va: int, hd_set_active_va: int
) -> int:
    """Install one exact-owner fallback behind the existing alpha dispatcher."""
    section = install_runtime_segment(image, FINGERPRINT_ALPHA_SEGMENT)
    base = image.rva_to_va(section.virtual_address)
    payload = SegmentPayloadBuilder(
        owner="runtime2d.fingerprint_alpha",
        segment=FINGERPRINT_ALPHA_SEGMENT.logical_name,
        size=FINGERPRINT_ALPHA_SEGMENT.size,
    )
    payload.place(label="magic", offset=0, payload=FINGERPRINT_ALPHA_SEGMENT.magic)
    payload.place(label="version", offset=8, payload=struct.pack("<I", 1))
    payload.reserve(label="effect rectangles and dimensions", offset=DEST, size=VTABLE - DEST)
    payload.place(
        label="effect vtable",
        offset=VTABLE,
        payload=struct.pack("<II", profile.address("bitmap.effect_executor"), base + CALLBACK),
    )
    payload.reserve(label="native blend trace", offset=TRACE, size=40)
    payload.place(
        label="constructor",
        offset=CONSTRUCTOR,
        payload=build_constructor(
            profile=profile, base=base, root_va=root_va, hd_set_active_va=hd_set_active_va
        ),
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
        limit=NATIVE_SURFACE,
    )
    for density, surface, resource, limit in (
        (1, NATIVE_SURFACE, NATIVE_RESOURCE, DENSE_RESOURCE),
        (4, DENSE_SURFACE, DENSE_RESOURCE, FINGERPRINT_ALPHA_NORMALIZE_OFFSET),
    ):
        payload.place(
            label=f"{density}x surface",
            offset=surface,
            payload=build_surface_match(
                wrapper_va=base + surface,
                resource_match_va=base + resource,
                manager_va=profile.address("bitmap.manager"),
                images=PRINT_IMAGES,
                density=density,
            ),
            limit=surface + 0x180,
        )
        payload.place(
            label=f"{density}x resources",
            offset=resource,
            payload=build_resource_match(
                wrapper_va=base + resource, images=PRINT_IMAGES, density=density
            ),
            limit=limit,
        )
    payload.place(
        label="print hit bounds",
        offset=FINGERPRINT_ALPHA_NORMALIZE_OFFSET,
        payload=build_normalize(base=base),
    )
    image.write_bytes(section.pointer_to_raw_data, payload.build())
    return base + CONSTRUCTOR
