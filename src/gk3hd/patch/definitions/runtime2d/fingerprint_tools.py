"""Keep fingerprint tools and drag input in reference-scale units."""

from __future__ import annotations

import struct

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.ui_frames import (
    FINGERPRINT_TOOL_IMAGES,
    build_resource_match,
)


def build_dust_input(
    *, wrapper_va: int, native_va: int, hd_set_active_va: int, dimensions_va: int
) -> bytes:
    """Inverse-map the fingerprint-only drag callback's first POINT argument.

    Drag events use vtable +0x80, independently of ordinary pointer motion and
    clicks. Dense workstation presentation scales around the screen center;
    native dust hit tests still use the centered logical model. Pass a private
    point to the original thiscall callback, preserving its other arguments,
    return value, nonvolatile registers and the caller's physical point.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x83\x3d" + struct.pack("<I", hd_set_active_va) + b"\x00")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x81\x3d" + struct.pack("<I", dimensions_va + 4) + struct.pack("<I", 768))
    code.jump_if(Condition.BELOW_OR_EQUAL, "native")
    code.raw(b"\x83\x7c\x24\x04\x00")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x55\x8b\xec\x83\xec\x0c\x89\x4d\xf4")
    for axis, local in ((0, 0xF8), (4, 0xFC)):
        code.raw(b"\x8b\x55\x08\x8b\x42" + bytes([axis]))
        code.raw(b"\x8b\x0d" + struct.pack("<I", dimensions_va + axis) + b"\xd1\xf9")
        code.raw(b"\x2b\xc1\x69\xc0\x00\x03\x00\x00\x99")
        code.raw(b"\xf7\x3d" + struct.pack("<I", dimensions_va + 4))
        code.raw(b"\x03\xc1\x89\x45" + bytes([local]))
    code.raw(b"\xff\x75\x10\xff\x75\x0c\x8d\x45\xf8\x50\x8b\x4d\xf4")
    code.call_absolute(native_va)
    code.raw(b"\xc9\xc2\x0c\x00")
    code.label("native")
    code.jump_absolute(native_va)
    return code.build()


def build_damage_selector(
    *, wrapper_va: int, hd_set_active_va: int, dimensions_va: int, full_region_va: int
) -> bytes:
    """Choose complete damage for dense art even at the reference resolution.

    EAX otherwise retains the native region. A dense workstation rebuilds its
    complete source rectangle; native partial damage cannot erase moving tools
    correctly. Unmodified reference artwork keeps its original damage policy.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x83\x3d" + struct.pack("<I", hd_set_active_va) + b"\x00")
    code.jump_short_if(Condition.NOT_EQUAL, "full")
    for offset, extent in ((0, 1024), (4, 768)):
        code.raw(
            b"\x81\x3d" + struct.pack("<I", dimensions_va + offset) + struct.pack("<I", extent)
        )
        code.jump_short_if(Condition.ABOVE, "full")
    code.ret()
    code.label("full")
    code.raw(b"\xb8" + struct.pack("<I", full_region_va))
    code.ret()
    return code.build()


def build_tool_match(*, wrapper_va: int, manager_va: int) -> bytes:
    """Identify EAX through the live resource table, without retaining pointers.

    These are UI images, despite their C_ names. Match the complete brush/tape
    state family at native or fourfold density; preserve registers and return CF.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x60\x85\xc0")
    code.jump_if(Condition.EQUAL, "no")
    code.raw(b"\x8b\x3d" + struct.pack("<I", manager_va) + b"\x85\xff")
    code.jump_if(Condition.EQUAL, "no")
    code.raw(b"\x8b\x8f\x24\x01\x00\x00\x8b\xbf\x20\x01\x00\x00\x85\xff")
    code.jump_if(Condition.EQUAL, "no")
    code.label("scan")
    code.raw(b"\x85\xc9")
    code.jump_if(Condition.EQUAL, "no")
    code.raw(b"\x8b\x37\x83\xc7\x04\x49\x85\xf6")
    code.jump_short_if(Condition.EQUAL, "scan")
    code.raw(b"\x39\x46\x30")
    code.jump_short_if(Condition.NOT_EQUAL, "scan")
    code.call_absolute(wrapper_va + 0x60)
    code.raw(b"\x61\xc3")
    code.label("no")
    code.raw(b"\x61\xf8\xc3")
    lookup = code.build(maximum_size=0x60)
    catalog = tuple(
        (name, width * density, height * density)
        for density in (1, 4)
        for name, width, height in FINGERPRINT_TOOL_IMAGES
    )
    return lookup.ljust(0x60, b"\x90") + build_resource_match(
        wrapper_va=wrapper_va + 0x60, images=catalog, density=1
    )


def _logical_extent(code: X86Emitter, *, axis: int, label: str) -> None:
    """Load ECX after exact identity matching, never infer ownership from size."""
    code.raw(b"\x8b\x4b" + bytes([0x38 + axis]) + b"\x83\x7b\x38\x21")
    code.jump_short_if(Condition.BELOW_OR_EQUAL, label)
    code.raw(b"\xc1\xe9\x02")
    code.label(label)


def build_tool_transform(
    *,
    wrapper_va: int,
    match_va: int,
    layout_active_va: int,
    dimensions_va: int,
    dest_rect_va: int,
    source_rect_va: int,
) -> bytes:
    """Emit a prefix for the fingerprint blitter's existing PUSHAD-frame ABI.

    Only an active dense-workstation traversal to a physical display surface
    qualifies. Restore the complete image about its existing physical pointer
    anchor, then clip in presentation space. Native clipping happened before
    scaling and must not discard pixels which become visible after enlargement.
    The root supplies full damage at these resolutions. Source/destination
    caller rectangles, hit boxes and pointer positions are never modified.

    A handled call returns from the enclosing blitter; other calls fall through.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x83\x3d" + struct.pack("<I", layout_active_va) + b"\x01")
    code.jump_if(Condition.NOT_EQUAL, "done")
    code.raw(b"\x8b\x44\x24\x28")
    code.call_absolute(match_va)
    code.jump_if(Condition.ABOVE_OR_EQUAL, "done")
    code.raw(b"\x89\xc3\x8b\x54\x24\x1c\x85\xd2")
    code.jump_if(Condition.EQUAL, "done")
    for offset in (0, 4):
        code.raw(b"\xa1" + struct.pack("<I", dimensions_va + offset))
        code.raw(b"\x39\x42" + bytes([0x38 + offset]))
        code.jump_if(Condition.NOT_EQUAL, "done")
    code.raw(b"\x8b\x74\x24\x2c\x8b\x7c\x24\x30\x85\xf6")
    code.jump_if(Condition.EQUAL, "done")
    code.raw(b"\x85\xff")
    code.jump_if(Condition.EQUAL, "done")
    # Validate the recovered high-blitter contract before touching either arg.
    for offset in (0, 4):
        code.raw(b"\x8b\x47" + bytes([offset]) + b"\x85\xc0")
        code.jump_if(Condition.SIGN, "done")
        code.raw(b"\x8b\x57" + bytes([offset + 8]) + b"\x3b\x53" + bytes([0x38 + offset]))
        code.jump_if(Condition.ABOVE, "done")
        code.raw(b"\x83\x7b\x38\x21")
        code.jump_short_if(Condition.BELOW_OR_EQUAL, f"aligned_{offset}")
        code.raw(b"\x89\xc1\x09\xd1\xf6\xc1\x03")
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.label(f"aligned_{offset}")
        code.raw(b"\x29\xc2")
        code.jump_if(Condition.LESS_OR_EQUAL, "done")
        code.raw(b"\x89\xd0")
        _logical_extent(code, axis=offset, label=f"validate_extent_{offset}")
        code.raw(b"\x0f\xaf\xc1\x31\xd2\xf7\x73" + bytes([0x38 + offset]))
        code.raw(b"\x85\xd2")
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\x8b\x56" + bytes([offset + 8]) + b"\x2b\x56" + bytes([offset]) + b"\x39\xd0")
        code.jump_if(Condition.NOT_EQUAL, "done")
    for offset in (0, 4):
        near = dest_rect_va + offset
        far = near + 8
        src_near = source_rect_va + offset
        src_far = src_near + 8
        # Recover the unclipped physical anchor from logical source displacement.
        code.raw(b"\x8b\x47" + bytes([offset]))
        _logical_extent(code, axis=offset, label=f"anchor_extent_{offset}")
        code.raw(b"\x0f\xaf\xc1")
        code.raw(b"\x31\xd2\xf7\x73" + bytes([0x38 + offset]))
        code.raw(b"\x8b\x56" + bytes([offset]) + b"\x29\xc2\x89\x15" + struct.pack("<I", near))
        code.raw(b"\xa1" + struct.pack("<I", dimensions_va + 4))
        _logical_extent(code, axis=offset, label=f"display_extent_{offset}")
        code.raw(
            b"\x0f\xaf\xc1" + b"\x05\x80\x01\x00\x00\x31\xd2\xb9\x00\x03\x00\x00\xf7\xf1\x89\xc5"
        )
        code.raw(b"\x03\x05" + struct.pack("<I", near) + b"\xa3" + struct.pack("<I", far))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.LESS_OR_EQUAL, "done")
        code.raw(
            b"\xa1"
            + struct.pack("<I", near)
            + b"\x3b\x05"
            + struct.pack("<I", dimensions_va + offset)
        )
        code.jump_if(Condition.GREATER_OR_EQUAL, "done")
        code.raw(b"\xc7\x05" + struct.pack("<I", src_near) + b"\x00\x00\x00\x00")
        code.raw(b"\x85\xc0")
        code.jump_short_if(Condition.NOT_SIGN, f"near_{offset}")
        code.raw(
            b"\xf7\xd8\xf7\x63"
            + bytes([0x38 + offset])
            + b"\xf7\xf5\xa3"
            + struct.pack("<I", src_near)
        )
        code.raw(b"\xc7\x05" + struct.pack("<I", near) + b"\x00\x00\x00\x00")
        code.label(f"near_{offset}")
        code.raw(b"\x8b\x43" + bytes([0x38 + offset]) + b"\xa3" + struct.pack("<I", src_far))
        code.raw(
            b"\xa1"
            + struct.pack("<I", far)
            + b"\x2b\x05"
            + struct.pack("<I", dimensions_va + offset)
        )
        code.jump_short_if(Condition.LESS_OR_EQUAL, f"far_{offset}")
        code.raw(
            b"\xf7\x63" + bytes([0x38 + offset]) + b"\xf7\xf5\x29\x05" + struct.pack("<I", src_far)
        )
        code.raw(
            b"\xa1" + struct.pack("<I", dimensions_va + offset) + b"\xa3" + struct.pack("<I", far)
        )
        code.label(f"far_{offset}")
    code.raw(b"\xc7\x44\x24\x2c" + struct.pack("<I", dest_rect_va))
    code.raw(b"\xc7\x44\x24\x30" + struct.pack("<I", source_rect_va))
    code.ret()
    code.label("done")
    return code.build()
