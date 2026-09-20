"""Inventory replacement geometry and tiled-sampler arithmetic contracts."""

from __future__ import annotations

import struct

import pytest
from capstone import CS_ARCH_X86, CS_MODE_32, Cs

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.runtime2d.inventory import InventoryFeatureCompiler
from gk3hd.patch.definitions.runtime2d.inventory_alpha import (
    build_item_draw_wrapper,
    build_scaled_alpha_callback,
)
from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI


def test_inventory_reopen_does_not_clamp_scroll_position_through_a_physical_grid() -> None:
    compiler = InventoryFeatureCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=0x790004, height_va=0x790008),
    )
    payload = compiler._build_layout_wrapper(
        wrapper_va=0x800000,
        active_inventory_va=0x810000,
        system_input_active_va=0x810004,
        system_clear_pending_va=0x810008,
        system_root_ptr_va=0x81000C,
        system_transform_mode_va=0x810010,
        denominator_va=0x810014,
        numerator_va=0x810018,
        x_offset_va=0x81001C,
        y_offset_va=0x810020,
    )
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in instructions) == len(payload)
    calls = [i.op_str for i in instructions if i.mnemonic == "call"]
    assert calls == [
        hex(GOG_BUILD.address("inventory.base_layout")),
        hex(GOG_BUILD.address("inventory.reference_layout")),
    ]
    reference_pair = bytes.fromhex("c7 07 00 04 00 00 c7 47 04 00 03 00 00")
    assert reference_pair in payload
    assert bytes.fromhex("58 89 47 04 58 89 07") in payload  # restore both physical dimensions


def test_dense_item_scope_restores_cached_frame_dimensions() -> None:
    compiler = InventoryFeatureCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=0x790004, height_va=0x790008),
    )
    payload = build_item_draw_wrapper(
        compiler,
        wrapper_va=0x800000,
        item_draw_count_va=0x810000,
        active_inventory_va=0x810004,
        item_draw_active_va=0x810008,
        item_alpha_handle_va=0x81000C,
        item_dense_source_va=0x810010,
    )
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in instructions) == len(payload)
    for offset in (0x24, 0x28):
        assert b"\x81\x78" + bytes([offset]) + struct.pack("<I", 376) in payload
        assert b"\xc1\x78" + bytes([offset, 2]) in payload  # temporary logical extent
        assert b"\xc1\x60" + bytes([offset, 2]) in payload  # restore physical extent
    assert b"\x8b\x41\x2c" in payload  # original item's drawable after native Draw
    assert b"\xc7\x05" + struct.pack("<I", 0x810010) + bytes(4) in payload
    # The owner's persistent right/bottom must use the native 94px cell too.
    # Only the bitmap drawable's cached source dimensions are restored to 376.
    for first, last in ((0x1C, 0x24), (0x20, 0x28)):
        logical_bound = b"\x8b\x56" + bytes([first]) + b"\x83\xc2\x5e\x89\x56" + bytes([last])
        assert logical_bound in payload
        assert payload.index(logical_bound) < payload.index(b"\xc1\x78\x24\x02")


@pytest.mark.parametrize(
    ("origin", "extent", "destination"),
    [(128, 376, 470), (256, 376, 470), (384, 376, 470), (128, 94, 117)],
)
def test_tile_origin_uses_a_64_bit_fixed_point_numerator(
    origin: int, extent: int, destination: int
) -> None:
    payload = build_scaled_alpha_callback(
        callback_va=0x800000,
        source_rect_va=0x810000,
        dest_width_va=0x810010,
        dest_height_va=0x810014,
    )
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in instructions) == len(payload)
    # Both axes must sign-extend BEFORE shifting into EDX:EAX and dividing.
    wide_shift = bytes.fromhex("99 0f a4 c2 10 c1 e0 10 f7 3d")
    assert payload.count(wide_shift) == 2
    product = origin * extent
    high = product >> 16
    low = (product << 16) & 0xFFFFFFFF
    numerator = (high << 32) | low
    assert numerator // destination == (origin * extent * 65536) // destination
    assert (numerator // destination) >> 16 == origin * extent // destination
