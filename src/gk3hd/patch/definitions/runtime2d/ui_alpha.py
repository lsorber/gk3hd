"""Scale the documented CAIN UIImage/color-opacity pair through native blending."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.inventory_alpha import build_native_alpha_resampler
from gk3hd.patch.definitions.runtime2d.layout import UI_ALPHA_SEGMENT, install_runtime_segment
from gk3hd.patch.definitions.runtime2d.ui_frames import (
    OPACITY_IMAGE_PAIRS,
    build_resource_match,
    build_surface_match,
)

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile

DEST, SOURCE, WIDTH, HEIGHT, VTABLE, TRACE = 0x20, 0x30, 0x40, 0x44, 0x48, 0x60
CONSTRUCTOR, CALLBACK = 0x100, 0x600
NATIVE_SURFACE, DENSE_SURFACE, NATIVE_RESOURCE, DENSE_RESOURCE = 0x800, 0x980, 0xB00, 0xD00


def build_constructor(*, profile: BuildProfile, base: int, fallback_va: int) -> bytes:
    """Map only a live matching color/opacity pair drawn directly onto the screen.

    The original UIImage passes clipped logical rectangles. Source density and
    display scale are independent: scale both source coordinates by its proven
    density, and map destination edges about the screen center. Leave every
    other software effect to its existing owner. Mask dimensions and handle
    generation are checked before using the shared source coordinate mapping.
    """
    code = X86Emitter(base_va=base + CONSTRUCTOR)
    code.raw(b"\x60\x8b\x44\x24\x28")
    code.call_absolute(base + DENSE_SURFACE)
    code.raw(b"\xbd\x02\x00\x00\x00")
    code.jump_if(Condition.BELOW, "matched")
    code.call_absolute(base + NATIVE_SURFACE)
    code.jump_if(Condition.ABOVE_OR_EQUAL, "native")
    code.raw(b"\x31\xed")
    code.label("matched")
    code.raw(b"\x8b\xd8\x8b\x54\x24\x24\x85\xd2")
    code.jump_if(Condition.EQUAL, "native")
    for axis in (0, 4):
        code.raw(b"\xa1" + struct.pack("<I", profile.address("display.dimensions") + axis))
        code.raw(b"\x3b\x42" + bytes([0x38 + axis]))
        code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(b"\x8b\x74\x24\x34\x85\xf6")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x83\x3e\x01")
    code.jump_if(Condition.NOT_EQUAL, "native")
    # Resolve the exact alpha handle, not a filename guessed from the color.
    code.raw(b"\x8b\x56\x0c\x85\xd2")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x8b\x3d" + struct.pack("<I", profile.address("bitmap.manager")))
    code.raw(b"\x85\xff")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x0f\xb7\xc2\x3b\x87\x54\x01\x00\x00")
    code.jump_if(Condition.ABOVE_OR_EQUAL, "native")
    code.raw(b"\x8b\xbf\x50\x01\x00\x00\x85\xff")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x8b\x3c\x87\x85\xff")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\xc1\xea\x10\x66\x3b\x57\x04")
    code.jump_if(Condition.NOT_EQUAL, "native")
    for offset, expected, fold in ((8, b"cain", 0x20202020), (12, b"_alp", 0x20202000)):
        code.raw(b"\x8b\x47" + bytes([offset]) + b"\x0d" + struct.pack("<I", fold))
        code.raw(b"\x3d" + expected)
        code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(b"\x0f\xb7\x47\x10\x0d\x20\x20\x00\x00\x3d\x68\x61\x00\x00")
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(b"\x80\x7f\x12\x00")
    code.jump_if(Condition.NOT_EQUAL, "native")
    # The resource is lazy. Use its own load virtual before checking extents.
    code.raw(b"\x66\x83\x7f\x06\x00")
    code.jump_if(Condition.NOT_EQUAL, "loaded")
    code.raw(b"\x8b\x07\x8b\xcf\xff\x50\x04")
    code.label("loaded")
    for axis in (0, 4):
        code.raw(b"\x8b\x47" + bytes([0x34 + axis]) + b"\x3b\x43" + bytes([0x38 + axis]))
        code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(b"\x8b\x74\x24\x2c\x8b\x7c\x24\x30\x85\xf6")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x85\xff")
    code.jump_if(Condition.EQUAL, "native")
    for axis, extent in ((0, 148), (4, 160)):
        code.raw(b"\x8b\x47" + bytes([axis]) + b"\x85\xc0")
        code.jump_if(Condition.LESS, "native")
        code.raw(b"\x3b\x47" + bytes([axis + 8]))
        code.jump_if(Condition.GREATER_OR_EQUAL, "native")
        code.raw(b"\x81\x7f" + bytes([axis + 8]) + struct.pack("<I", extent))
        code.jump_if(Condition.GREATER, "native")
    for offset in range(0, 16, 4):
        code.raw(b"\x8b\x47" + bytes([offset]) + b"\x8b\xcd\xd3\xe0\xa3")
        code.raw(struct.pack("<I", base + SOURCE + offset))
        code.raw(b"\x8b\x46" + bytes([offset]))
        code.raw(
            b"\x8b\x0d" + struct.pack("<I", profile.address("display.dimensions") + offset % 8)
        )
        code.raw(b"\xd1\xf9\x2b\xc1\x51\x0f\xaf\x05")
        code.raw(struct.pack("<I", profile.address("display.dimensions") + 4))
        code.raw(b"\x99\xb9\x00\x03\x00\x00\xf7\xf9\x59\x03\xc1\xa3")
        code.raw(struct.pack("<I", base + DEST + offset))
    for axis in (0, 4):
        code.raw(b"\xa1" + struct.pack("<I", base + DEST + axis + 8))
        code.raw(b"\x2b\x05" + struct.pack("<I", base + DEST + axis))
        code.raw(b"\xa3" + struct.pack("<I", base + WIDTH + axis))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.LESS_OR_EQUAL, "native")
    code.raw(b"\x61\xff\x74\x24\x14\x68" + struct.pack("<I", base + SOURCE))
    code.raw(b"\x68" + struct.pack("<I", base + DEST))
    code.raw(b"\xff\x74\x24\x14\xff\x74\x24\x14")
    code.call_absolute(profile.address("bitmap.effect_constructor"))
    code.raw(b"\xc7\x00" + struct.pack("<I", base + VTABLE) + b"\xc2\x14\x00")
    code.label("native")
    code.raw(b"\x61")
    code.jump_absolute(fallback_va)
    return code.build()


def install_alpha_adapter(image: PEFile, *, profile: BuildProfile, fallback_va: int) -> int:
    """Chain paired UIImage handling before the existing owner-specific effects."""
    section = install_runtime_segment(image, UI_ALPHA_SEGMENT)
    base = image.rva_to_va(section.virtual_address)
    payload = SegmentPayloadBuilder(
        owner="runtime2d.ui_alpha",
        segment=UI_ALPHA_SEGMENT.logical_name,
        size=UI_ALPHA_SEGMENT.size,
    )
    payload.place(label="identity", offset=0, payload=UI_ALPHA_SEGMENT.magic)
    payload.reserve(label="rectangles and extents", offset=DEST, size=VTABLE - DEST)
    payload.place(
        label="effect vtable",
        offset=VTABLE,
        payload=struct.pack("<II", profile.address("bitmap.effect_executor"), base + CALLBACK),
    )
    payload.reserve(label="blend diagnostics", offset=TRACE, size=40)
    payload.place(
        label="constructor",
        offset=CONSTRUCTOR,
        limit=CALLBACK,
        payload=build_constructor(profile=profile, base=base, fallback_va=fallback_va),
    )
    payload.place(
        label="paired resampler",
        offset=CALLBACK,
        limit=NATIVE_SURFACE,
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
    for density, surface, resource in (
        (1, NATIVE_SURFACE, NATIVE_RESOURCE),
        (4, DENSE_SURFACE, DENSE_RESOURCE),
    ):
        payload.place(
            label=f"{density}x surface",
            offset=surface,
            limit=surface + 0x180,
            payload=build_surface_match(
                wrapper_va=base + surface,
                resource_match_va=base + resource,
                manager_va=profile.address("bitmap.manager"),
                images=OPACITY_IMAGE_PAIRS,
                density=density,
            ),
        )
        payload.place(
            label=f"{density}x resource",
            offset=resource,
            limit=resource + 0x200,
            payload=build_resource_match(
                wrapper_va=base + resource, images=OPACITY_IMAGE_PAIRS, density=density
            ),
        )
    image.write_bytes(section.pointer_to_raw_data, payload.build())
    return base + CONSTRUCTOR
