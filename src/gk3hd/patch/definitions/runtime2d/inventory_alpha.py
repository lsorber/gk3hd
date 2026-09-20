"""Emit InventoryItem software-alpha scaling at its exact class boundary."""

# These emitters are one physical part of InventoryFeatureCompiler and consume
# its private recovered ABI directly. A copied public configuration would add
# mutable duplication and allow the two ABI views to drift.
# ruff: noqa: SLF001

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from gk3hd.patch.binary.x86 import Condition, X86Emitter

if TYPE_CHECKING:
    from gk3hd.patch.definitions.runtime2d.inventory import InventoryFeatureCompiler


def build_item_draw_wrapper(
    owner: InventoryFeatureCompiler,
    *,
    wrapper_va: int,
    item_draw_count_va: int,
    active_inventory_va: int,
    item_draw_active_va: int,
    item_alpha_handle_va: int,
    item_dense_source_va: int,
) -> bytes:
    """Scope the scaled-alpha virtual to one synchronous item draw."""
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\xa1" + struct.pack("<I", active_inventory_va) + b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\xff\x05" + struct.pack("<I", item_draw_count_va))
    # Retain only the alpha-mask identity needed by the shared constructor
    # call-site. A depth alone would also catch unrelated alpha effects
    # nested in the same root traversal.
    code.raw(b"\x60\x8b\xf1")
    code.raw(b"\x31\xc0\xa3" + struct.pack("<I", item_alpha_handle_va))
    code.raw(b"\xa3" + struct.pack("<I", item_dense_source_va))
    code.raw(b"\x8b\x46\x2c\x85\xc0")
    code.jump_if(Condition.EQUAL, "identity_ready")
    # BitmapDrawable::Draw copies this mask handle into word three of its
    # stack-local options record. Retaining the value gives the shared
    # effect call-site hook an exact identity check; a mere active-depth
    # test also catches unrelated alpha work nested in the same traversal.
    code.raw(b"\x8b\x50\x14\x89\x15" + struct.pack("<I", item_alpha_handle_va))
    code.raw(b"\x85\xd2")
    code.jump_if(Condition.EQUAL, "identity_ready")
    # Inventory owns 94x94 icon cells. A fourfold frame has 376x376 cached
    # drawable extents; make its layout/clip domain logical for this Draw only.
    # The underlying bitmap and opacity surfaces keep their physical sizes.
    for offset in (0x24, 0x28):
        code.raw(b"\x81\x78" + bytes([offset]) + struct.pack("<I", 376))
        code.jump_if(Condition.NOT_EQUAL, "identity_ready")
    code.raw(b"\xff\x05" + struct.pack("<I", item_dense_source_va))
    # The item container also inherited the physical bitmap extent when the
    # replacement was loaded. Keep its persistent bounds logical, not just
    # the drawable's temporary clip extent; damage/hit queries run outside Draw.
    # Left/top are the reference-grid anchor and must remain unchanged.
    code.raw(b"\x8b\x56\x1c\x83\xc2\x5e\x89\x56\x24")
    code.raw(b"\x8b\x56\x20\x83\xc2\x5e\x89\x56\x28")
    code.raw(b"\xc1\x78\x24\x02\xc1\x78\x28\x02")
    code.label("identity_ready")
    code.raw(b"\x61")
    # This depth covers only the synchronous stock item Draw. The effect
    # constructor is shared by unrelated screens, so a broad Inventory
    # lifetime flag would incorrectly enlarge their alpha operations too.
    code.raw(b"\xff\x05" + struct.pack("<I", item_draw_active_va))
    code.raw(b"\x51")
    code.raw(b"\xff\x74\x24\x0c\xff\x74\x24\x0c")
    code.call_absolute(owner._inventory_item_draw_original_va)
    code.raw(b"\xff\x0d" + struct.pack("<I", item_draw_active_va))
    code.raw(b"\x59")
    code.raw(b"\x60\x83\x3d" + struct.pack("<I", item_dense_source_va) + b"\x00")
    code.jump_if(Condition.EQUAL, "dimensions_restored")
    code.raw(b"\x8b\x41\x2c\xc1\x60\x24\x02\xc1\x60\x28\x02")
    code.raw(b"\xc7\x05" + struct.pack("<I", item_dense_source_va) + bytes(4))
    code.label("dimensions_restored")
    code.raw(b"\x61")
    code.raw(b"\xc2\x08\x00")
    code.label("native")
    code.jump_absolute(owner._inventory_item_draw_original_va)
    return code.build()


def build_effect_constructor_wrapper(
    owner: InventoryFeatureCompiler,
    *,
    wrapper_va: int,
    item_draw_active_va: int,
    output_rect_va: int,
    source_rect_va: int,
    dest_width_va: int,
    dest_height_va: int,
    transform_count_va: int,
    item_alpha_handle_va: int,
    item_dense_source_va: int,
    denominator_va: int,
    numerator_va: int,
    x_offset_va: int,
    y_offset_va: int,
    scaled_alpha_vtable_va: int,
    font_scaled_alpha_vtable_va: int,
    selected_vtable_va: int,
    hud_font_active_va: int,
    hud_font_point_va: int,
    hud_font_alpha_transform_count_va: int,
    hd_font_active_va: int,
    hd_font_source_transform_count_va: int,
    physical_height_va: int,
    fallback_constructor_va: int | None = None,
    font_bank_select_va: int | None = None,
) -> bytes:
    """Dispatch the shared alpha constructor to its two exact owners.

    GK3 has one software-alpha constructor call site. Inventory items need a
    fitted-canvas affine; non-opaque font glyphs need the same edge rounding
    as their opaque path (authored HUD edges or a Load/Save-local extent).
    Every unrelated alpha effect must retain the stock helper.
    """
    code = X86Emitter(base_va=wrapper_va)

    # Both font policies are published only for the synchronous high-level
    # glyph call. Generated atlases multiply the source RECT by four; scoped
    # UI owners additionally enlarge the destination about its mapped anchor.
    code.raw(b"\x83\x3d" + struct.pack("<I", hd_font_active_va) + b"\x00")
    code.jump_if(Condition.NOT_EQUAL, "font")
    code.raw(b"\x83\x3d" + struct.pack("<I", hud_font_active_va) + b"\x00")
    code.jump_if(Condition.EQUAL, "inventory")
    code.label("font")
    code.raw(b"\x31\xc0\xa3" + struct.pack("<I", dest_width_va))
    code.raw(
        b"\xc7\x05"
        + struct.pack("<I", selected_vtable_va)
        + struct.pack("<I", font_scaled_alpha_vtable_va)
    )
    code.raw(b"\x60")
    # At this five-argument thiscall boundary, PUSHAD moves arg3 (the
    # destination RECT) to +0x2c and arg4 (the source RECT) to +0x30.
    code.raw(b"\x8b\x74\x24\x2c\x85\xf6")
    code.jump_if(Condition.EQUAL, "restore")
    code.raw(b"\xbf" + struct.pack("<I", output_rect_va))
    code.raw(b"\xfc\xb9\x04\x00\x00\x00\xf3\xa5")
    code.raw(b"\x8b\x74\x24\x30\x85\xf6")
    code.jump_if(Condition.EQUAL, "restore")
    code.raw(b"\xbf" + struct.pack("<I", source_rect_va))
    code.raw(b"\xb9\x04\x00\x00\x00\xf3\xa5")

    code.raw(b"\x83\x3d" + struct.pack("<I", hd_font_active_va) + b"\x00")
    code.jump_short_if(Condition.EQUAL, "font_destination")
    for offset in range(0, 16, 4):
        code.raw(b"\xc1\x25" + struct.pack("<I", source_rect_va + offset) + b"\x02")
    code.raw(b"\xc7\x44\x24\x30" + struct.pack("<I", source_rect_va))
    code.raw(b"\xff\x05" + struct.pack("<I", hd_font_source_transform_count_va))

    code.label("font_destination")
    code.raw(b"\x83\x3d" + struct.pack("<I", hud_font_active_va) + b"\x00")
    code.jump_if(Condition.EQUAL, "font_dimensions")
    code.raw(b"\x8b\x1d" + struct.pack("<I", hud_font_active_va))
    # Match the opaque HUD path: round each authored edge independently.
    # floor(point*s)+floor(extent*s) can be one pixel smaller than
    # floor((point+extent)*s), changing glyph shape at the start of a fade.
    for first, second in ((0, 8), (4, 12)):
        code.raw(b"\xa1" + struct.pack("<I", output_rect_va + second))
        code.raw(b"\x2b\x05" + struct.pack("<I", output_rect_va + first))
        code.raw(b"\x83\xfb\x02")
        code.jump_short_if(Condition.EQUAL, f"font_scale_{first}")
        code.raw(b"\x03\x05" + struct.pack("<I", hud_font_point_va + first))
        code.label(f"font_scale_{first}")
        code.raw(b"\x0f\xaf\x05" + struct.pack("<I", physical_height_va))
        code.raw(b"\x99\xb9\x00\x03\x00\x00\xf7\xf9")
        code.raw(b"\x83\xfb\x02")
        code.jump_short_if(Condition.NOT_EQUAL, f"font_store_{first}")
        code.raw(b"\x03\x05" + struct.pack("<I", output_rect_va + first))
        code.label(f"font_store_{first}")
        code.raw(b"\xa3" + struct.pack("<I", output_rect_va + second))
    code.raw(b"\xff\x05" + struct.pack("<I", hud_font_alpha_transform_count_va))

    code.label("font_dimensions")
    code.raw(b"\xa1" + struct.pack("<I", output_rect_va + 8))
    code.raw(b"\x2b\x05" + struct.pack("<I", output_rect_va))
    code.raw(b"\xa3" + struct.pack("<I", dest_width_va))
    code.raw(b"\xa1" + struct.pack("<I", output_rect_va + 12))
    code.raw(b"\x2b\x05" + struct.pack("<I", output_rect_va + 4))
    code.raw(b"\xa3" + struct.pack("<I", dest_height_va))
    if font_bank_select_va is not None:
        # The constructor's geometry is already physical. Select matching color
        # and opacity artwork now; the final transfer sees only a scratch tile.
        code.raw(b"\xb9" + struct.pack("<I", source_rect_va))
        code.raw(b"\x51\x68" + struct.pack("<I", output_rect_va))
        code.raw(bytes.fromhex("ff742430"))  # Arg2 after PUSHAD and two pushes.
        code.call_absolute(font_bank_select_va)
    code.jump("restore")

    code.label("inventory")
    code.raw(b"\x83\x3d" + struct.pack("<I", item_draw_active_va) + b"\x00")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x31\xc0\xa3" + struct.pack("<I", dest_width_va))
    code.raw(
        b"\xc7\x05"
        + struct.pack("<I", selected_vtable_va)
        + struct.pack("<I", scaled_alpha_vtable_va)
    )
    code.raw(b"\x60")
    # Arg5 is the five-word options record. Only the record whose alpha
    # handle matches the current Inventory item's drawable is owned here.
    # This excludes screenshot fades, controls, and other effects that can
    # run while the item object's synchronous Draw remains on the stack.
    code.raw(b"\x8b\x74\x24\x34\x85\xf6")
    code.jump_if(Condition.EQUAL, "restore")
    code.raw(b"\x8b\x46\x0c")
    code.raw(b"\x3b\x05" + struct.pack("<I", item_alpha_handle_va))
    code.jump_if(Condition.NOT_EQUAL, "restore")
    # Retain both authored rectangles and map only the destination copy.
    code.raw(b"\x8b\x74\x24\x2c\x85\xf6")
    code.jump_if(Condition.EQUAL, "restore")
    code.raw(b"\xbf" + struct.pack("<I", output_rect_va))
    code.raw(b"\xfc\xb9\x04\x00\x00\x00\xf3\xa5")
    code.raw(b"\x8b\x74\x24\x30\x85\xf6")
    code.jump_if(Condition.EQUAL, "restore")
    code.raw(b"\xbf" + struct.pack("<I", source_rect_va))
    code.raw(b"\xb9\x04\x00\x00\x00\xf3\xa5")
    # Item objects, source sampling, and hit geometry remain in authored
    # 1024-space. Convert only the destination through the same fitted
    # affine used by the pointer inverse.
    code.raw(b"\x83\x3d" + struct.pack("<I", item_dense_source_va) + b"\x00")
    code.jump_if(Condition.EQUAL, "inventory_destination")
    for offset in range(0, 16, 4):
        code.raw(b"\xc1\x25" + struct.pack("<I", source_rect_va + offset) + b"\x02")
    code.raw(b"\xc7\x44\x24\x30" + struct.pack("<I", source_rect_va))
    code.label("inventory_destination")
    for displacement, offset_va in (
        (0, x_offset_va),
        (4, y_offset_va),
        (8, x_offset_va),
        (12, y_offset_va),
    ):
        code.raw(b"\xa1" + struct.pack("<I", output_rect_va + displacement))
        code.raw(b"\x0f\xaf\x05" + struct.pack("<I", numerator_va))
        code.raw(b"\x99\xf7\x3d" + struct.pack("<I", denominator_va))
        code.raw(b"\x03\x05" + struct.pack("<I", offset_va))
        code.raw(b"\xa3" + struct.pack("<I", output_rect_va + displacement))
    code.raw(b"\xa1" + struct.pack("<I", output_rect_va + 8))
    code.raw(b"\x2b\x05" + struct.pack("<I", output_rect_va))
    code.raw(b"\xa3" + struct.pack("<I", dest_width_va))
    code.raw(b"\xa1" + struct.pack("<I", output_rect_va + 12))
    code.raw(b"\x2b\x05" + struct.pack("<I", output_rect_va + 4))
    code.raw(b"\xa3" + struct.pack("<I", dest_height_va))
    code.raw(b"\xff\x05" + struct.pack("<I", transform_count_va))
    code.label("restore")
    code.raw(b"\x61")
    code.raw(b"\x83\x3d" + struct.pack("<I", dest_width_va) + b"\x00")
    code.jump_if(Condition.EQUAL, "native")
    # Rebuild the original thiscall explicitly so the stock constructor
    # still owns all surface/resource setup. Arg3 is the fitted destination;
    # dense resources also pass the physical source RECT in arg4.
    code.raw(b"\xff\x74\x24\x14\xff\x74\x24\x14")
    code.raw(b"\x68" + struct.pack("<I", output_rect_va))
    code.raw(b"\xff\x74\x24\x14\xff\x74\x24\x14")
    code.call_absolute(owner._effect_constructor_original_va)
    code.raw(b"\x8b\x15" + struct.pack("<I", selected_vtable_va) + b"\x89\x10")
    code.raw(b"\xc2\x14\x00")
    code.label("native")
    code.jump_absolute(fallback_constructor_va or owner._effect_constructor_original_va)
    return code.build()


def build_scaled_font_alpha_callback(
    owner: InventoryFeatureCompiler,
    *,
    callback_va: int,
    source_rect_va: int,
    dest_width_va: int,
    dest_height_va: int,
    trace_va: int,
) -> bytes:
    """Resample a font effect while delegating each blend to stock GK3 code.

    Font effects can carry colorkey, global opacity, optional masks, and the
    live surface pixel format. Inventory's specialized RGB565 callback cannot
    reproduce all of those semantics. Map each destination pixel to its
    nearest source coordinate, then invoke GK3's native one-pixel callback;
    the native routine remains the sole owner of color and alpha arithmetic.
    This path is used only for the rare non-opaque font generation.
    """
    return build_native_alpha_resampler(
        callback_va=callback_va,
        native_callback_va=owner._effect_callback_original_va,
        source_rect_va=source_rect_va,
        dest_width_va=dest_width_va,
        dest_height_va=dest_height_va,
        trace_va=trace_va,
        # Opaque glyph stretching samples pixel centers too. Switching to
        # opacity must change only the blend, not the glyph's sample phase.
        match_opaque_stretch=True,
    )


def build_native_alpha_resampler(
    *,
    callback_va: int,
    native_callback_va: int,
    source_rect_va: int,
    dest_width_va: int,
    dest_height_va: int,
    trace_va: int,
    center_samples: bool = False,
    match_opaque_stretch: bool = False,
) -> bytes:
    """Map samples without changing native blending.

    Fonts match D7VK's opaque CPU stretch, including its fixed-point ties.
    Other owners retain their existing corner or exact-center sampling rule.
    """
    code = X86Emitter(base_va=callback_va)
    code.raw(b"\x55\x8b\xec\x83\xec\x34\x53\x56\x57")
    code.raw(b"\x89\x4d\xfc")  # effect
    code.raw(b"\x8b\x45\x08\x89\x45\xf8")  # destination base
    code.raw(b"\x8b\x45\x0c\x89\x45\xf4")  # destination pitch
    code.raw(b"\x8b\x45\x10\x89\x45\xf0")  # tile dimensions
    code.raw(b"\x8b\x45\x14\x89\x45\xec")  # tile origin
    code.raw(b"\xff\x05" + struct.pack("<I", trace_va))
    code.raw(b"\x8b\x45\xf0\x8b\x08\x89\x0d" + struct.pack("<I", trace_va + 4))
    code.raw(b"\x8b\x48\x04\x89\x0d" + struct.pack("<I", trace_va + 8))
    code.raw(b"\x8b\x45\xec\x8b\x08\x89\x0d" + struct.pack("<I", trace_va + 12))
    code.raw(b"\x8b\x48\x04\x89\x0d" + struct.pack("<I", trace_va + 16))
    code.raw(b"\x8b\x45\xfc\x8b\x48\x48\x89\x0d" + struct.pack("<I", trace_va + 28))
    code.raw(b"\x8b\x48\x40\x89\x0d" + struct.pack("<I", trace_va + 32))
    code.raw(b"\x8b\x48\x38\x89\x0d" + struct.pack("<I", trace_va + 36))
    code.raw(b"\xa1" + struct.pack("<I", source_rect_va + 8))
    code.raw(b"\x2b\x05" + struct.pack("<I", source_rect_va) + b"\x89\x45\xe8")
    code.raw(b"\xa1" + struct.pack("<I", source_rect_va + 12))
    code.raw(b"\x2b\x05" + struct.pack("<I", source_rect_va + 4) + b"\x89\x45\xe4")
    # Native callback arguments for a single destination pixel.
    code.raw(b"\xc7\x45\xd8\x01\x00\x00\x00")
    code.raw(b"\xc7\x45\xdc\x01\x00\x00\x00")
    code.raw(b"\xc7\x45\xe0\x00\x00\x00\x00")  # row
    code.label("row_loop")
    code.raw(b"\x8b\x45\xf0\x8b\x40\x04\x39\x45\xe0")
    # CMP is encoded as ``row - tile_height``; leave only after the row
    # reaches the exclusive bound. Reversing this condition makes every tile
    # silently transparent because the zero-valued first row exits at once.
    code.jump_if(Condition.GREATER_OR_EQUAL, "done")
    code.raw(b"\xc7\x45\xcc\x00\x00\x00\x00")  # column
    code.label("pixel_loop")
    code.raw(b"\x8b\x45\xf0\x8b\x00\x39\x45\xcc")
    code.jump_if(Condition.GREATER_OR_EQUAL, "next_row")

    # The constructor has already advanced the effect's source base to the
    # clipped source rectangle. Map into that local coordinate domain; adding
    # the original atlas left/top here would advance it twice.
    if match_opaque_stretch:
        _emit_fixed_center_sample(
            code,
            extent_offset=0xE8,
            destination_va=dest_width_va,
            origin_offset=0,
            index_offset=0xCC,
        )
    else:
        code.raw(b"\x8b\x45\xec\x8b\x00\x03\x45\xcc")
        code.raw(b"\x0f\xaf\x45\xe8")
        if center_samples:
            code.raw(b"\x8b\x55\xe8\xd1\xea\x03\xc2")
        code.raw(b"\x99\xf7\x3d" + struct.pack("<I", dest_width_va))
    code.raw(b"\x89\x45\xd0")
    code.raw(b"\xa3" + struct.pack("<I", trace_va + 20))
    # Map the tile's vertical destination coordinate into source space.
    if match_opaque_stretch:
        _emit_fixed_center_sample(
            code,
            extent_offset=0xE4,
            destination_va=dest_height_va,
            origin_offset=4,
            index_offset=0xE0,
        )
    else:
        code.raw(b"\x8b\x45\xec\x8b\x40\x04\x03\x45\xe0")
        code.raw(b"\x0f\xaf\x45\xe4")
        if center_samples:
            code.raw(b"\x8b\x55\xe4\xd1\xea\x03\xc2")
        code.raw(b"\x99\xf7\x3d" + struct.pack("<I", dest_height_va))
    code.raw(b"\x89\x45\xd4")
    code.raw(b"\xa3" + struct.pack("<I", trace_va + 24))

    code.raw(b"\x8b\x45\xe0\x0f\xaf\x45\xf4\x03\x45\xf8")
    code.raw(b"\x8b\x55\xcc\x8d\x04\x50")  # + column * 2
    code.raw(b"\x8d\x55\xd0\x52")  # source POINT
    code.raw(b"\x8d\x55\xd8\x52")  # 1x1 dimensions
    code.raw(b"\xff\x75\xf4\x50")  # destination pitch and pixel
    code.raw(b"\x8b\x4d\xfc")
    code.call_absolute(native_callback_va)
    code.raw(b"\xff\x45\xcc")
    code.jump("pixel_loop")
    code.label("next_row")
    code.raw(b"\xff\x45\xe0")
    code.jump("row_loop")
    code.label("done")
    code.raw(b"\x5f\x5e\x5b\x8b\xe5\x5d\xc2\x10\x00")
    return code.build()


def _emit_fixed_center_sample(
    code: X86Emitter,
    *,
    extent_offset: int,
    destination_va: int,
    origin_offset: int,
    index_offset: int,
) -> None:
    """Match D7VK's 16.16 CPU stretch, including truncated-step tie breaking."""
    code.raw(b"\x8b\x45" + bytes([extent_offset]) + b"\xc1\xe0\x10\x99")
    code.raw(b"\xf7\x3d" + struct.pack("<I", destination_va))
    code.raw(b"\x8b\xc8\xd1\xe9")  # half step
    code.raw(b"\x8b\x55\xec\x8b\x52" + bytes([origin_offset]))
    code.raw(b"\x03\x55" + bytes([index_offset]) + b"\x0f\xaf\xc2\x03\xc1")
    code.raw(b"\xc1\xe8\x10")


def build_scaled_alpha_callback(
    *,
    callback_va: int,
    source_rect_va: int,
    dest_width_va: int,
    dest_height_va: int,
) -> bytes:
    """Blend a scaled Inventory item directly into GK3's locked page.

    The stock effect executor calls this virtual with a locked destination
    tile, its pitch, the tile dimensions, and the tile's origin within the
    complete destination rectangle. Source and alpha pointers at +0x30 and
    +0x40 already point at the clipped source origin. Mapping that global
    destination coordinate back into the original source preserves the
    executor's tiling and cleanup while avoiding any extra surface.
    """
    code = X86Emitter(base_va=callback_va)
    # The deepest local is [EBP-0x68].  Reserve the complete 0x68 bytes
    # before saving EBX/ESI/EDI: the caller is GK3's tiled effect executor
    # and relies on every non-volatile register after each tile callback.
    # Reserving only 0x64 would alias the final blend-weight local with the
    # saved EBX slot and corrupt the next tile's width calculation.
    code.raw(b"\x55\x8b\xec\x83\xec\x68")
    code.raw(b"\x53\x56\x57")
    # Stable inputs and effect metadata.
    code.raw(b"\x89\x4d\xfc")  # effect
    code.raw(b"\x8b\x45\x08\x89\x45\xf8")  # destination row
    code.raw(b"\x8b\x45\x0c\x89\x45\xf4")  # destination pitch
    code.raw(b"\x8b\x45\x10\x89\x45\xf0")  # tile dimensions
    code.raw(b"\x8b\x45\x14\x89\x45\xec")  # tile origin
    code.raw(b"\x8b\x41\x30\x89\x45\xe8")  # source base
    code.raw(b"\x8b\x41\x34\x89\x45\xe4")  # source pitch
    code.raw(b"\x8b\x41\x40\x89\x45\xe0")  # alpha base
    code.raw(b"\x8b\x41\x44\x89\x45\xdc")  # alpha pitch
    # Source dimensions are independent from the physical destination.
    code.raw(b"\xa1" + struct.pack("<I", source_rect_va + 8))
    code.raw(b"\x2b\x05" + struct.pack("<I", source_rect_va) + b"\x89\x45\xd8")
    code.raw(b"\xa1" + struct.pack("<I", source_rect_va + 12))
    code.raw(b"\x2b\x05" + struct.pack("<I", source_rect_va + 4) + b"\x89\x45\xd4")
    # 16.16 nearest-neighbour increments and the tile's global start.
    code.raw(b"\x8b\x45\xd8\xc1\xe0\x10\x99")
    code.raw(b"\xf7\x3d" + struct.pack("<I", dest_width_va) + b"\x89\x45\xd0")
    code.raw(b"\x8b\x45\xd4\xc1\xe0\x10\x99")
    code.raw(b"\xf7\x3d" + struct.pack("<I", dest_height_va) + b"\x89\x45\xc8")
    # A dense 376px item crosses the executor's 128px tile boundary. Its
    # origin*extent*65536 already exceeds signed 32-bit range at tile two;
    # keep the shifted numerator in EDX:EAX until IDIV, not wrapped in EAX.
    code.raw(b"\x8b\x45\xec\x8b\x00\x0f\xaf\x45\xd8\x99\x0f\xa4\xc2\x10\xc1\xe0\x10")
    code.raw(b"\xf7\x3d" + struct.pack("<I", dest_width_va) + b"\x89\x45\xcc")
    code.raw(b"\x8b\x45\xec\x8b\x40\x04\x0f\xaf\x45\xd4\x99\x0f\xa4\xc2\x10\xc1\xe0\x10")
    code.raw(b"\xf7\x3d" + struct.pack("<I", dest_height_va) + b"\x89\x45\xc4")
    code.raw(b"\x8b\x45\xf0\x8b\x40\x04\x89\x45\xc0")  # remaining rows
    code.raw(b"\x83\x7d\xc0\x00")
    code.jump_if(Condition.EQUAL, "done")
    code.label("row_loop")
    # Resolve the current source/alpha rows from the vertical accumulator.
    code.raw(b"\x8b\x45\xc4\xc1\xe8\x10\x0f\xaf\x45\xe4\x03\x45\xe8\x89\x45\xbc")
    code.raw(b"\x8b\x45\xe0\x85\xc0")
    code.jump_short_if(Condition.EQUAL, "no_alpha_row")
    code.raw(b"\x8b\x55\xc4\xc1\xea\x10\x0f\xaf\x55\xdc\x03\xc2")
    code.label("no_alpha_row")
    code.raw(b"\x89\x45\xb8")
    code.raw(b"\x8b\x45\xcc\x89\x45\xb4")  # horizontal accumulator
    code.raw(b"\x8b\x45\xf0\x8b\x00\x89\x45\xb0")  # remaining pixels
    code.raw(b"\x8b\x75\xf8\x89\x75\xac")  # destination pixel
    code.label("pixel_loop")
    code.raw(b"\x8b\x45\xb4\xc1\xe8\x10\x89\x45\xa8")  # source x
    code.raw(b"\x8b\x55\xbc\x0f\xb7\x04\x42\x89\x45\xa4")  # source word
    code.raw(b"\x8b\x55\xfc\x3b\x42\x38")
    code.jump_if(Condition.EQUAL, "next_pixel")
    code.raw(b"\x8b\x7d\xac\x0f\xb7\x0f\x89\x4d\xa0")  # destination word
    # Convert mask opacity into the stock 16.16 source weight. Inventory
    # always has an alpha mask; the fallback retains the global weight for
    # defensive compatibility with malformed resources.
    code.raw(b"\x8b\x45\xb8\x85\xc0")
    code.jump_short_if(Condition.EQUAL, "global_alpha")
    code.raw(b"\x8b\x55\xa8\x0f\xb6\x04\x10\x8b\x55\xfc\x0f\xaf\x42\x48\xc1\xf8\x08")
    code.jump_short("alpha_ready")
    code.label("global_alpha")
    code.raw(b"\x8b\x45\xfc\x8b\x40\x48")
    code.label("alpha_ready")
    code.raw(b"\x89\x45\x9c\xba\x00\x00\x01\x00\x2b\xd0\x89\x55\x98")
    # Red channel (5 bits).
    code.raw(b"\x8b\x45\xa4\xc1\xe8\x0b\x0f\xaf\x45\x9c")
    code.raw(b"\x8b\x55\xa0\xc1\xea\x0b\x0f\xaf\x55\x98\x03\xc2\xc1\xe8\x10\xc1\xe0\x0b\x89\xc3")
    # Green channel (6 bits).
    code.raw(b"\x8b\x45\xa4\xc1\xe8\x05\x83\xe0\x3f\x0f\xaf\x45\x9c")
    code.raw(
        b"\x8b\x55\xa0\xc1\xea\x05\x83\xe2\x3f\x0f\xaf\x55\x98\x03\xc2\xc1\xe8\x10\xc1\xe0\x05\x0b\xd8"
    )
    # Blue channel (5 bits) and final RGB565 store.
    code.raw(b"\x8b\x45\xa4\x83\xe0\x1f\x0f\xaf\x45\x9c")
    code.raw(b"\x8b\x55\xa0\x83\xe2\x1f\x0f\xaf\x55\x98\x03\xc2\xc1\xe8\x10\x0b\xd8")
    code.raw(b"\x66\x89\x1f")
    code.label("next_pixel")
    code.raw(b"\x83\x45\xac\x02")
    code.raw(b"\x8b\x45\xd0\x01\x45\xb4")
    code.raw(b"\xff\x4d\xb0")
    code.jump_if(Condition.NOT_EQUAL, "pixel_loop")
    code.raw(b"\x8b\x45\xf4\x01\x45\xf8")
    code.raw(b"\x8b\x45\xc8\x01\x45\xc4")
    code.raw(b"\xff\x4d\xc0")
    code.jump_if(Condition.NOT_EQUAL, "row_loop")
    code.label("done")
    code.raw(b"\x5f\x5e\x5b\x8b\xe5\x5d\xc2\x10\x00")
    return code.build()
