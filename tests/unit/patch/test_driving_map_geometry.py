"""Execute map geometry helpers, including the native unscaled marker radius."""

import struct

import pytest
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_ESI, UC_X86_REG_ESP

from gk3hd.patch.definitions.runtime2d.resource_driving_map import (
    build_draw_scope,
    build_marker_ellipse,
    build_source_grid_rect,
)
from tests.unit.patch.test_runtime2d_timeblock import _compiler


@pytest.mark.parametrize(
    "size", [(1024, 768), (1280, 800), (1280, 1024), (1920, 1080), (3840, 2160)]
)
def test_marker_scales_reference_origin_and_radius_together(size: tuple[int, int]) -> None:
    compiler = _compiler()
    base, state, stack, stop = 0x800000, 0x801000, 0x808000, 0x809000
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x400000)
    cpu.mem_map(base, 0x10000)
    cpu.mem_write(
        base,
        build_marker_ellipse(
            compiler,
            scope_active_va=state,
            input_active_va=state + 4,
            ellipse_count_va=state + 8,
        ),
    )
    cpu.mem_write(state, struct.pack("<I", 1))
    cpu.mem_write(compiler._physical_width_va, struct.pack("<2I", *size))
    cpu.mem_write(compiler._ellipse_iat_va, struct.pack("<I", stop))
    width, height = size
    # Observed native current-location center is (223.2, 136.2) in 640x480.
    left, top = round(223.2 * width / 640) - 3, round(136.2 * height / 480) - 3
    cpu.mem_write(stack, struct.pack("<6I", stop, 123, left, top, left + 6, top + 6))
    cpu.reg_write(UC_X86_REG_ESP, stack)
    cpu.emu_start(base, stop, count=500)
    assert cpu.reg_read(UC_X86_REG_ESP) == stack
    actual = struct.unpack("<4I", cpu.mem_read(stack + 8, 16))
    fitted_height = min(height, width * 3 // 4)
    scale = fitted_height / 768
    x = (width - fitted_height * 4 // 3) // 2 + int(354 * scale)
    y = (height - fitted_height) // 2 + int(215 * scale)
    diameter = int(6 * scale + 0.5)
    assert actual == (x, y, x + diameter, y + diameter)


# Observed native model pairs include every location, not just the three hovers.
_RECTANGLES = (
    ((70, 348, 226, 468), (264, 981, 852, 1318)),
    ((619, 412, 750, 484), (2322, 1161, 2814, 1363)),
    ((732, 360, 820, 422), (2748, 1012, 3078, 1187)),
    ((633, 299, 719, 363), (2376, 841, 2700, 1021)),
    ((707, 248, 766, 299), (2652, 697, 2874, 841)),
    ((798, 219, 868, 281), (2994, 616, 3258, 791)),
    ((150, 640, 239, 720), (564, 1800, 900, 2025)),
    ((888, 115, 964, 193), (3330, 324, 3618, 544)),
    ((924, 35, 1008, 113), (3468, 99, 3786, 319)),
    ((832, 6, 924, 92), (3120, 18, 3468, 261)),
    ((308, 190, 391, 265), (1158, 535, 1470, 746)),
    ((726, 104, 785, 142), (2724, 292, 2946, 400)),
    ((715, 145, 774, 193), (2682, 409, 2904, 544)),
    ((779, 272, 873, 348), (2922, 765, 3276, 981)),
    ((86, 214, 164, 274), (324, 603, 618, 774)),
    ((809, 145, 879, 205), (3036, 409, 3300, 580)),
    ((0, 0, 1024, 768), (0, 0, 3840, 2160)),
)


def test_all_location_rectangles_share_the_background_source_grid() -> None:
    base, dimensions, rectangle, stack, stop = 0x800000, 0x801000, 0x802000, 0x808000, 0x809000
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(base, 0x10000)
    cpu.mem_write(base, build_source_grid_rect(physical_width_va=dimensions))
    for reference, current in _RECTANGLES:
        native_x = round(current[0] * 640 / 3840)
        native_y = round(current[1] * 480 / 2160)
        native_w = round((current[2] - current[0]) * 640 / 3840)
        native_h = round((current[3] - current[1]) * 480 / 2160)
        edges = (native_x, native_y, native_x + native_w, native_y + native_h)
        for size in ((3840, 2160), (1024, 768)):
            # The map draw scope publishes canonical source-grid model edges.
            source = tuple(
                value * size[i % 2] // (640 if i % 2 == 0 else 480) for i, value in enumerate(edges)
            )
            cpu.mem_write(dimensions, struct.pack("<2I", *size))
            cpu.mem_write(rectangle, struct.pack("<4I", *source))
            cpu.mem_write(stack, struct.pack("<I", stop))
            cpu.reg_write(UC_X86_REG_ESP, stack)
            cpu.reg_write(UC_X86_REG_ESI, rectangle)
            cpu.emu_start(base, stop, count=500)
            # Native anchors and extents are independent integers. All edges
            # must use one global background transform, not separately rounded
            # 1024 edges or a stretch of a rounded physical-width cache.
            expected = tuple(
                int(v * size[1] / 480) + ((size[0] - size[1] * 4 // 3) // 2 if i % 2 == 0 else 0)
                for i, v in enumerate(edges)
            )
            assert struct.unpack("<4I", cpu.mem_read(rectangle, 16)) == expected, reference


@pytest.mark.parametrize(
    "size", [(1024, 768), (1280, 800), (1280, 1024), (1920, 1080), (3840, 2160)]
)
def test_background_and_adjacent_tiles_meet_without_gaps(size: tuple[int, int]) -> None:
    base, dimensions, rectangle, stack, stop = 0x800000, 0x801000, 0x802000, 0x808000, 0x809000
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(base, 0x10000)
    cpu.mem_write(base, build_source_grid_rect(physical_width_va=dimensions))
    cpu.mem_write(dimensions, struct.pack("<2I", *size))

    def present(rect: tuple[int, int, int, int]) -> tuple[int, ...]:
        cpu.mem_write(rectangle, struct.pack("<4I", *rect))
        cpu.mem_write(stack, struct.pack("<I", stop))
        cpu.reg_write(UC_X86_REG_ESP, stack)
        cpu.reg_write(UC_X86_REG_ESI, rectangle)
        cpu.emu_start(base, stop, count=500)
        return struct.unpack("<4I", cpu.mem_read(rectangle, 16))

    width, height = size
    background = present((0, 0, width, height))
    # Adjacent original-map tiles have to share their boundary with each
    # other and the background, including 5:4 displays with top/bottom bars.
    first = present((0, 0, width // 2, height))
    second = present((width // 2, 0, width, height))
    assert first[2] == second[0]
    assert first[:2] == background[:2]
    assert second[2:] == background[2:]
    left, top, right, bottom = background
    assert 0 <= left < right <= width
    assert 0 <= top < bottom <= height
    assert abs((right - left) / (bottom - top) - 4 / 3) < 0.002
    assert abs(left - (width - right)) <= 1
    assert abs(top - (height - bottom)) <= 1


@pytest.mark.parametrize("size", [(1024, 768), (1280, 800), (1280, 1024), (3840, 2160)])
@pytest.mark.parametrize("bounds", [(57, 131, 49, 38), (44, 218, 98, 75), (578, 22, 53, 49)])
def test_location_keeps_hitbox_across_texture_densities_and_redraws(
    size: tuple[int, int], bounds: tuple[int, int, int, int]
) -> None:
    compiler = _compiler()
    base, state, root, child, children, stack, stop = (
        0x800000,
        0x801000,
        0x802000,
        0x803000,
        0x804000,
        0x808000,
        0x809000,
    )
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x400000)
    cpu.mem_map(base, 0x10000)
    cpu.mem_write(
        base,
        build_draw_scope(
            compiler,
            wrapper_va=base,
            scope_active_va=state,
            input_active_va=state + 4,
            base_child_va=state + 8,
            children_scaled_va=state + 12,
            child_rect_count_va=state + 16,
            child_rects_va=state + 256,
            full_draw_count_va=state + 20,
            full_damage_region_va=state + 32,
            full_damage_rect_va=state + 64,
            system_render_state_vas=(state + 80, state + 84, state + 88),
        ),
    )
    cpu.mem_write(compiler.profile.address("ui.container_draw"), b"\xc2\x08\x00")
    cpu.mem_write(compiler._physical_width_va, struct.pack("<2I", *size))
    cpu.mem_write(state + 4, struct.pack("<I", 1))
    cpu.mem_write(root + 0x4C, struct.pack("<2I", children, 1))
    cpu.mem_write(children, struct.pack("<I", child))
    cpu.mem_write(child, struct.pack("<I", compiler._bitmap_node_destructor_slot_va))
    width, height = size
    source_x, source_y, source_width, source_height = bounds
    x, y = source_x * width // 640, source_y * height // 480
    extent = (source_width * width // 640, source_height * height // 480)
    for density in (1, 4, 1, 4, 1):  # hover replaces either original or dense art
        cpu.mem_write(
            child + 0x1C,
            struct.pack("<4I", x, y, x + extent[0] * density, y + extent[1] * density),
        )
        cpu.mem_write(stack, struct.pack("<3I", stop, 123, 456))
        cpu.reg_write(UC_X86_REG_ESP, stack)
        cpu.reg_write(UC_X86_REG_ECX, root)
        cpu.emu_start(base, stop, count=1500)
        assert struct.unpack("<4I", cpu.mem_read(child + 0x1C, 16)) == (
            x,
            y,
            (source_x + source_width) * width // 640,
            (source_y + source_height) * height // 480,
        )
        assert struct.unpack("<I", cpu.mem_read(state, 4)) == (0,)
        assert cpu.reg_read(UC_X86_REG_ESP) == stack + 12


def test_hidden_marker_does_not_draw_or_leak_stack() -> None:
    compiler = _compiler()
    base, state, stack, stop = 0x800000, 0x801000, 0x808000, 0x809000
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x400000)
    cpu.mem_map(base, 0x10000)
    cpu.mem_write(
        base,
        build_marker_ellipse(
            compiler,
            scope_active_va=state,
            input_active_va=state + 4,
            ellipse_count_va=state + 8,
        ),
    )
    cpu.mem_write(state, struct.pack("<I", 1))
    # An unmapped GDI target proves this exact sentinel never reaches drawing.
    cpu.mem_write(compiler._ellipse_iat_va, struct.pack("<I", 0xDEADBEEF))
    cpu.mem_write(stack, struct.pack("<6I", stop, 123, 0, 0, 6, 6))
    cpu.reg_write(UC_X86_REG_ESP, stack)
    cpu.emu_start(base, stop, count=500)
    assert cpu.reg_read(UC_X86_REG_EAX) == 1
    assert cpu.reg_read(UC_X86_REG_ESP) == stack + 24
