"""Emit the driving map's fitted composition and page-ownership policy.

The map is a retained 2D tree rendered into GK3's rotating DirectDraw pages.
This domain identifies that tree from its exact ``DM_BASE`` resource, applies
one height-derived 4:3 affine to all bitmap and GDI children, and gives the
exact DrivingMapLayer draw a complete physical damage region. Its exact
bitmap-node destructor withdraws ownership; unrelated 2D roots and map
construction before ``DM_BASE`` remain native.
"""

# These emitters are one physical part of ResourceDispatchCompiler and consume
# its private recovered ABI directly; copying that ABI into a second public
# configuration object would add state and permit the two views to drift.
# ruff: noqa: SLF001

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from gk3hd.driving_map import MAP_LOCATIONS
from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.geometry import AUTHORED_FRAME_HEIGHT, AUTHORED_FRAME_WIDTH

if TYPE_CHECKING:
    from gk3hd.patch.binary.mutations import ExecutableMutationPlan
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.runtime2d.resources import ResourceDispatchCompiler

_PUSH_IMM8_OPCODE = 0x6A


def correct_location_origins(mutations: ExecutableMutationPlan, profile: BuildProfile) -> None:
    """Move normal/highlight art and hitboxes at their shared native constructor."""
    for location in ("TR1", "RL1", "TRE"):
        site = profile.site(f"driving_map.{location}.origin")
        x, y, _width, _height = MAP_LOCATIONS[location]
        payload = bytearray(site.original)
        offset = 0
        for coordinate in (y, x):
            short = payload[offset] == _PUSH_IMM8_OPCODE
            struct.pack_into("<b" if short else "<I", payload, offset + 1, coordinate)
            offset += 2 if short else 5
        mutations.replace(
            label=f"driving-map {location} terrain alignment",
            va=site.va,
            expected=site.original,
            payload=bytes(payload),
        )


def emit_fitted_height(code: X86Emitter, *, physical_width_va: int) -> None:
    """Return a contained 4:3 viewport's height in EAX, clobbering EDX."""
    code += b"\xa1" + struct.pack("<I", physical_width_va)
    code += b"\x6b\xc0\x03\xc1\xe8\x02"
    code += b"\x8b\x15" + struct.pack("<I", physical_width_va + 4)
    code += b"\x3b\xc2\x0f\x47\xc2"  # min(width * 3 / 4, height)


def build_source_grid_rect(*, physical_width_va: int) -> bytes:
    """Fit ESI's physical rectangle through the map's native 640x480 pixel grid.

    The draw scope normalizes native hit rectangles to floor-scaled source
    edges. Ceil-divide each edge back to its exact 640x480 coordinate, then
    apply the same H/480 transform as DM_BASE. Neither intermediate physical
    rounding nor a previously rasterized 1024 rectangle changes the geometry.
    The caller owns a private presentation RECT;
    native hit-test rectangles and texture coordinates are never overwritten.
    """
    code = X86Emitter(base_va=0)
    emit_fitted_height(code, physical_width_va=physical_width_va)
    code += b"\x8b\xd8"  # EBX owns the common fitted height.
    for near, far, native, physical in (
        (0, 8, 640, physical_width_va),
        (4, 12, 480, physical_width_va + 4),
    ):
        for edge in (near, far):
            code += b"\x8b\x46" + bytes([edge])
            code += b"\x69\xc0" + struct.pack("<I", native)
            code += b"\x03\x05" + struct.pack("<I", physical) + b"\x48"
            code += b"\x31\xd2\xf7\x35" + struct.pack("<I", physical)
            code += b"\x0f\xaf\xc3"
            code += b"\x31\xd2\xb9\xe0\x01\x00\x00\xf7\xf1"
            code += b"\x89\x46" + bytes([edge])
    # Add the same pillar to both X edges; Y already uses the common scale.
    code += b"\x8b\xc3"
    code += b"\xc1\xe0\x02\x31\xd2\xb9\x03\x00\x00\x00\xf7\xf1"
    code += b"\x8b\x15" + struct.pack("<I", physical_width_va)
    code += b"\x2b\xd0\xd1\xea\x01\x16\x01\x56\x08"
    code += b"\xa1" + struct.pack("<I", physical_width_va + 4)
    code += b"\x2b\xc3\xd1\xe8\x01\x46\x04\x01\x46\x0c\xc3"
    return code.build(maximum_size=0x200)


def build_draw_scope(
    owner: ResourceDispatchCompiler,
    *,
    wrapper_va: int,
    scope_active_va: int,
    input_active_va: int,
    base_child_va: int,
    children_scaled_va: int,
    child_rect_count_va: int,
    child_rects_va: int,
    full_draw_count_va: int,
    full_damage_region_va: int,
    full_damage_rect_va: int,
    system_render_state_vas: tuple[int, int, int],
) -> bytes:
    """Draw the exact live map against one complete physical damage region."""
    code = X86Emitter(base_va=wrapper_va)
    code += b"\x81\x3d" + struct.pack("<I", owner._physical_width_va)
    code += b"\x00\x04\x00\x00"
    code.jump_if(Condition.BELOW, "native")
    code += b"\x83\x3d" + struct.pack("<I", input_active_va) + b"\x00"
    code.jump_if(Condition.EQUAL, "native")
    code += b"\xc7\x05" + struct.pack("<I", child_rect_count_va) + b"\x00\x00\x00\x00"

    # Anchors identify the exact original map crop. Rebuild its model edges
    # from that shared layout on every draw, never from bitmap density or a
    # guessed size threshold. This also handles hover replacing the bitmap.
    code += b"\x60\x8b\x79\x4c\x8b\x59\x50\x85\xff"
    code.jump_if(Condition.EQUAL, "children_done")
    code += b"\x85\xdb"
    code.jump_if(Condition.LESS_OR_EQUAL, "children_done")
    code += b"\x83\xfb\x40"
    code.jump_if(Condition.GREATER, "children_done")
    code.label("child_loop")
    code += b"\x8b\x0f\x83\xc7\x04\x85\xc9"
    code.jump_if(Condition.EQUAL, "next_child")
    code += b"\x3b\x0d" + struct.pack("<I", base_child_va)
    code.jump_if(Condition.EQUAL, "next_child")
    code += b"\x81\x39" + struct.pack("<I", owner._bitmap_node_destructor_slot_va)
    code.jump_if(Condition.NOT_EQUAL, "next_child")
    code += b"\x57"
    for near, native, physical, save_x in (
        (0x1C, 640, owner._physical_width_va, True),
        (0x20, 480, owner._physical_width_va + 4, False),
    ):
        code += b"\x8b\x41" + bytes([near]) + b"\x69\xc0" + struct.pack("<I", native)
        code += b"\x03\x05" + struct.pack("<I", physical) + b"\x48"
        code += b"\x31\xd2\xf7\x35" + struct.pack("<I", physical)
        if save_x:
            code += b"\x8b\xe8"
    code += b"\xc1\xe0\x10\x0b\xe8\xbf"
    code.absolute_label("location_bounds")
    code += b"\xba" + struct.pack("<I", len(MAP_LOCATIONS))
    code.label("find_location")
    code += b"\x3b\x2f"
    code.jump_short_if(Condition.EQUAL, "location_found")
    code += b"\x83\xc7\x08\x4a"
    code.jump_short_if(Condition.NOT_EQUAL, "find_location")
    code.jump_short("location_done")
    code.label("location_found")
    for component, far, native, physical in (
        (0, 0x24, 640, owner._physical_width_va),
        (2, 0x28, 480, owner._physical_width_va + 4),
    ):
        code += b"\x0f\xb7\x47" + bytes([component])
        code += b"\x0f\xb7\x77" + bytes([component + 4]) + b"\x03\xc6"
        code += b"\x0f\xaf\x05" + struct.pack("<I", physical)
        code += b"\x31\xd2\x68" + struct.pack("<I", native)
        code += b"\xf7\x34\x24\x83\xc4\x04\x89\x41" + bytes([far])
    code.label("location_done")
    code += b"\x5f"
    # Publish every location's exact physical model rectangle for the nested
    # final blit. That boundary can then restore a source rectangle clipped by
    # GK3's temporary dense surface without ever mutating hit-test geometry.
    code += b"\xa1" + struct.pack("<I", child_rect_count_va) + b"\x83\xf8\x10"
    code.jump_if(Condition.ABOVE_OR_EQUAL, "next_child")
    code += b"\xc1\xe0\x04\x05" + struct.pack("<I", child_rects_va)
    for source_offset, record_offset in ((0x1C, 0), (0x20, 4), (0x24, 8), (0x28, 12)):
        code += b"\x8b\x51" + bytes([source_offset])
        code += b"\x89\x50" + bytes([record_offset])
    code += b"\xff\x05" + struct.pack("<I", child_rect_count_va)
    code.label("next_child")
    code += b"\x4b"
    code.jump_if(Condition.NOT_EQUAL, "child_loop")
    code.label("children_done")
    code += b"\xc7\x05" + struct.pack("<I", children_scaled_va) + b"\x01\x00\x00\x00"
    code += b"\x61"

    code += b"\x8b\x15" + struct.pack("<I", owner._physical_width_va)
    code += b"\x89\x15" + struct.pack("<I", full_damage_rect_va + 8)
    code += b"\x8b\x15" + struct.pack("<I", owner._physical_width_va + 4)
    code += b"\x89\x15" + struct.pack("<I", full_damage_rect_va + 12)
    code += b"\xc7\x05" + struct.pack("<I", scope_active_va) + b"\x01\x00\x00\x00"
    code += b"\xff\x05" + struct.pack("<I", full_draw_count_va)
    # A modal can request a fresh underlying map before capturing its dimmed
    # backdrop. The map's physical model belongs only to its own resource
    # affine: inheriting the modal's local-root transform sends DM_BASE outside
    # the framebuffer, leaving a black page with only the GDI marker visible.
    for address in system_render_state_vas:
        code += b"\xff\x35" + struct.pack("<I", address)
        code += b"\xc7\x05" + struct.pack("<I", address) + bytes(4)
    code += b"\x51\x68" + struct.pack("<I", full_damage_region_va)
    code += b"\xff\x74\x24\x18"  # three saved state DWORDs precede this/region
    code.call_absolute(owner.profile.address("ui.container_draw"))
    code += b"\xc7\x05" + struct.pack("<I", scope_active_va) + b"\x00\x00\x00\x00"
    code += b"\x59"
    for address in reversed(system_render_state_vas):
        code += b"\x8f\x05" + struct.pack("<I", address)
    code += b"\xc2\x08\x00"
    code.label("native")
    code.jump_absolute(owner.profile.address("ui.container_draw"))
    code.label("location_bounds")
    for bounds in MAP_LOCATIONS.values():
        code += struct.pack("<4H", *bounds)
    return code.build()


def build_destructor(
    owner: ResourceDispatchCompiler,
    *,
    wrapper_va: int,
    child_va: int,
    resource_va: int,
    surface_va: int,
    input_active_va: int,
    children_scaled_va: int,
    child_rect_count_va: int,
    ellipse_count_va: int,
    root_this_va: int,
) -> bytes:
    """Withdraw only the retained map identities owned by this allocation."""
    code = X86Emitter(base_va=wrapper_va)
    code += b"\x3b\x0d" + struct.pack("<I", child_va)
    code.jump_short_if(Condition.NOT_EQUAL, "native")
    for address in (
        input_active_va,
        children_scaled_va,
        child_rect_count_va,
        ellipse_count_va,
        root_this_va,
        resource_va,
        surface_va,
        child_va,
    ):
        code += b"\xc7\x05" + struct.pack("<I", address) + b"\x00\x00\x00\x00"
    code.label("native")
    code.jump_absolute(owner._bitmap_node_destructor_original_va)
    return code.build()


def build_marker_ellipse(
    owner: ResourceDispatchCompiler,
    *,
    scope_active_va: int,
    input_active_va: int,
    ellipse_count_va: int,
) -> bytes:
    """Fit the map's GDI location marker into its 4:3 viewport.

    This class's draw method paints a six-pixel Ellipse directly into the
    destination surface, bypassing the DirectDraw dispatcher that fits the
    map bitmaps. Its position has already received GK3's independent physical
    X/Y scales, but its six-pixel raster footprint has not. Recover the center
    before subtracting the reference radius, then fit the entire box into
    the height-limited map viewport with one height-derived reference scale.

    The method also submits a hidden ``(0,0,6,6)`` sentinel rectangle.  It
    is normally clipped away, but redraw timing can expose it at an absolute
    screen corner.  While map scope is live, report success without issuing
    GDI for that non-location sentinel.

    The visible/native path is a tail call: the original Ellipse arguments
    and return address stay on the stack, and GDI32 performs stdcall cleanup.
    """
    # DM_BASE activates the per-composition scope.  The lifetime flag also
    # covers marker invalidations that arrive just outside that traversal.
    code = X86Emitter(base_va=0)
    code += b"\x83\x3d" + struct.pack("<I", scope_active_va) + b"\x00"
    code.jump_short_if(Condition.NOT_EQUAL, "marker_checks")
    code += b"\x83\x3d" + struct.pack("<I", input_active_va) + b"\x00"
    code.jump_if(Condition.EQUAL, "native")

    code.label("marker_checks")
    # Reject only the exact origin sentinel. A legitimate marker can touch
    # either map edge, so checking only the two zero coordinates is too broad.
    for argument_offset, expected in ((8, 0), (12, 0), (16, 6), (20, 6)):
        code += b"\x83\x7c\x24" + bytes([argument_offset, expected])
        code.jump_if(Condition.NOT_EQUAL, "fit_marker")
    code.jump("suppress_sentinel")

    code.label("fit_marker")
    code += b"\xff\x05" + struct.pack("<I", ellipse_count_va)
    # Keep the native raster dimensions on our stack while the four original
    # Ellipse coordinates remain available eight bytes farther down.
    code += b"\x8b\x44\x24\x10\x2b\x44\x24\x08\x50"  # width
    code += b"\x8b\x44\x24\x18\x2b\x44\x24\x10\x50"  # height
    emit_fitted_height(code, physical_width_va=owner._physical_width_va)
    code += b"\x50"  # fitted height, followed by original height and width

    # Native placement scales the marker CENTER, then subtracts an unscaled
    # three-pixel radius. Scaling that old left/top instead shifts a UHD dot
    # by almost two reference pixels. Recover the rounded reference center,
    # subtract its native radius there, and only then scale the entire box.
    for origin, dimension, reference, physical in (
        (20, 8, AUTHORED_FRAME_WIDTH, owner._physical_width_va),
        (24, 4, AUTHORED_FRAME_HEIGHT, owner._physical_width_va + 4),
    ):
        code += b"\x8b\x4c\x24" + bytes([dimension]) + b"\xd1\xe9"
        code += b"\x8b\x44\x24" + bytes([origin]) + b"\x03\xc1"
        code += b"\x69\xc0" + struct.pack("<I", reference)
        code += b"\x8b\x15" + struct.pack("<I", physical) + b"\xd1\xea\x03\xc2"
        code += b"\x31\xd2\xf7\x35" + struct.pack("<I", physical)
        code += b"\x2b\xc1\x0f\xaf\x04\x24"
        code += b"\x31\xd2\xb9\x00\x03\x00\x00\xf7\xf1"
        code += b"\x89\x44\x24" + bytes([origin])
    code += b"\x8b\x0c\x24"
    code += b"\x6b\xc9\x04\x8b\xc1\x31\xd2\xb9\x03\x00\x00\x00\xf7\xf1"
    code += b"\x8b\x15" + struct.pack("<I", owner._physical_width_va)
    code += b"\x2b\xd0\xd1\xea\x01\x54\x24\x14"
    code += b"\xa1" + struct.pack("<I", owner._physical_width_va + 4)
    code += b"\x2b\x04\x24\xd1\xe8\x01\x44\x24\x18"

    # Round each authored raster dimension by the common vertical scale:
    # round(size * physical_height / 768). A 6x6 marker consequently remains
    # 6x6 at the reference mode, becomes 9x9 at HD, and 17x17 at UHD.
    for size_offset, origin_offset, edge_offset in ((8, 20, 28), (4, 24, 32)):
        code += b"\x8b\x44\x24" + bytes([size_offset])
        code += b"\x0f\xaf\x04\x24"
        code += b"\x05\x80\x01\x00\x00\x31\xd2"
        code += b"\xb9\x00\x03\x00\x00\xf7\xf1"
        code += b"\x03\x44\x24" + bytes([origin_offset])
        code += b"\x89\x44\x24" + bytes([edge_offset])

    code += b"\x83\xc4\x0c"  # discard the three temporary dimensions

    code.label("native")
    code += b"\xff\x25" + struct.pack("<I", owner._ellipse_iat_va)

    code.label("suppress_sentinel")
    # Ellipse returns BOOL and its result is ignored here.  Return TRUE and
    # perform the same five-argument stdcall cleanup as GDI32 would.
    code += b"\xb8\x01\x00\x00\x00\xc2\x14\x00"

    return code.build()
