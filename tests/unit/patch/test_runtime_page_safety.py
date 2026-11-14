"""Execute live 2D state updates with their installed instruction pages read-only."""

from __future__ import annotations

import struct
from typing import cast

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, UC_PROT_EXEC, UC_PROT_READ, Uc
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_ECX, UC_X86_REG_ESP

from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.guard_stale_mouse_move_targets import StaleMouseMoveCompiler
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.runtime2d.captions import CaptionFeatureCompiler
from gk3hd.patch.definitions.runtime2d.font_bank import install_font_bank_adapter
from gk3hd.patch.definitions.runtime2d.inventory import InventoryFeatureCompiler
from gk3hd.patch.definitions.runtime2d.layout import (
    CAPTION_ACTIVE_CLIP_OFFSET,
    CAPTION_ACTIVE_OBJECT_OFFSET,
    CAPTION_PRESENTER_OFFSET,
    CAPTION_SEGMENT,
    FINGERPRINT_SEGMENT,
    FONT_BANK_SCOPE_OFFSET,
    FONT_BANK_SEGMENT,
    INVENTORY_ALPHA_HEIGHT_OFFSET,
    INVENTORY_ALPHA_SOURCE_RECT_OFFSET,
    INVENTORY_ALPHA_WIDTH_OFFSET,
    INVENTORY_FONT_ALPHA_VTABLE_OFFSET,
    INVENTORY_SEGMENT,
    LOAD_SAVE_SEGMENT,
    LOAD_SAVE_STATE_OFFSET,
    RESOURCE_SEGMENT,
    RESOURCE_STATE_OFFSET,
    SYSTEM_CONTROL_FULL_DAMAGE_RECT_OFFSET,
    SYSTEM_CONTROL_FULL_DAMAGE_REGION_OFFSET,
    SYSTEM_CONTROL_SEGMENT,
    SYSTEM_CONTROL_STATE_OFFSET,
    SYSTEM_INPUT_ACTIVE_OFFSET,
    SYSTEM_RENDER_DEPTH_OFFSET,
    SYSTEM_ROOT_POINTER_OFFSET,
    SYSTEM_SEGMENT,
    SYSTEM_STATE_OFFSET,
    TIMEBLOCK_SEGMENT,
    RuntimeImage,
    RuntimeLayout,
)
from gk3hd.patch.definitions.runtime2d.resources import ResourceDispatchCompiler
from gk3hd.patch.definitions.runtime2d.system.load_save import LoadSaveFeatureCompiler
from tests.unit.patch.test_complete_compilation import _source
from tests.unit.patch.test_vr_overlays import _source_bytes


def _word(machine: Uc, address: int, value: int) -> None:
    machine.mem_write(address, struct.pack("<I", value))


def _read_word(machine: Uc, address: int) -> int:
    return struct.unpack("<I", machine.mem_read(address, 4))[0]


@pytest.mark.parametrize("active", [False, True])
def test_empty_caption_replay_clears_scope_without_writing_code(*, active: bool) -> None:
    """Even an empty per-frame queue safely retires its active font scope."""
    image = PEFile(_source_bytes())
    section = image.get_section(RuntimeLayout.section_name)
    assert section is not None
    base = image.rva_to_va(section.virtual_address)
    caption = base + CAPTION_SEGMENT.offset
    entry = caption + CAPTION_PRESENTER_OFFSET
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(0x400000, 0x500000)
    machine.mem_write(base, image.read_bytes(section.pointer_to_raw_data, section.virtual_size))
    machine.mem_protect(entry & ~4095, 4096, UC_PROT_READ | UC_PROT_EXEC)
    machine.mem_map(0x300000, 0x20000)
    stack, stop = 0x308000, 0x401000
    _word(machine, stack, stop)
    _word(machine, caption + CAPTION_ACTIVE_OBJECT_OFFSET, 123)
    _word(machine, caption + CAPTION_ACTIVE_CLIP_OFFSET, 456)
    _word(machine, GOG_BUILD.address("transition.back_surface_ptr"), 0x210000)
    _word(
        machine, TransitionFrameCompiler.runtime_abi(image).room_presentation_active_va, int(active)
    )
    _word(machine, GOG_BUILD.address("high_resolution_3d.directdraw_ptr"), 0)
    machine.reg_write(UC_X86_REG_EAX, 0x12345678)
    machine.reg_write(UC_X86_REG_ESP, stack)
    machine.emu_start(entry, stop, count=1000)
    assert _read_word(machine, caption + CaptionFeatureCompiler._off_queue_count) == 0
    assert _read_word(machine, caption + CAPTION_ACTIVE_OBJECT_OFFSET) == 0
    assert _read_word(machine, caption + CAPTION_ACTIVE_CLIP_OFFSET) == 0
    assert machine.reg_read(UC_X86_REG_EAX) == 0x12345678
    assert machine.reg_read(UC_X86_REG_ESP) == stack + 4


@pytest.mark.parametrize("origin", [0, 13])
def test_installed_font_alpha_preserves_each_native_blend_with_rx_code(origin: int) -> None:
    """A real callback maps all four samples without writing its instruction page."""
    image = PEFile(_source_bytes())
    section = image.get_section(RuntimeLayout.section_name)
    assert section is not None
    base = image.rva_to_va(section.virtual_address)
    inventory = base + INVENTORY_SEGMENT.offset
    entry = image.read_u32_va(inventory + INVENTORY_FONT_ALPHA_VTABLE_OFFSET + 4)
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(0x400000, 0x500000)
    machine.mem_write(base, image.read_bytes(section.pointer_to_raw_data, section.virtual_size))
    machine.mem_protect(entry & ~4095, 4096, UC_PROT_READ | UC_PROT_EXEC)
    effect, tile, point = 0x210000, 0x210100, 0x210200
    machine.mem_map(effect, 4096)
    machine.mem_map(0x300000, 0x20000)
    stack, stop = 0x308000, 0x401000
    machine.mem_write(
        inventory + INVENTORY_ALPHA_SOURCE_RECT_OFFSET, struct.pack("<4I", 20, 40, 68, 88)
    )
    _word(machine, inventory + INVENTORY_ALPHA_WIDTH_OFFSET, 60)
    _word(machine, inventory + INVENTORY_ALPHA_HEIGHT_OFFSET, 60)
    machine.mem_write(tile, struct.pack("<2I", 2, 2))
    machine.mem_write(point, struct.pack("<2I", origin, origin))
    native = GOG_BUILD.address("bitmap.effect_callback")
    machine.mem_write(native, bytes.fromhex("c2 10 00"))
    machine.mem_write(stack, struct.pack("<5I", stop, 0x220000, 1024, tile, point))
    samples: list[tuple[int, int]] = []

    def inspect(cpu: Uc, address: int, _size: int, _data: object) -> None:
        if address == native:
            esp = cpu.reg_read(UC_X86_REG_ESP)
            assert cpu.reg_read(UC_X86_REG_ECX) == effect
            assert struct.unpack("<2I", cpu.mem_read(_read_word(cpu, esp + 12), 8)) == (1, 1)
            samples.append(struct.unpack("<2I", cpu.mem_read(_read_word(cpu, esp + 16), 8)))

    machine.hook_add(UC_HOOK_CODE, inspect)
    machine.reg_write(UC_X86_REG_ECX, effect)
    machine.reg_write(UC_X86_REG_ESP, stack)
    machine.emu_start(entry, stop, count=1000)
    step = (48 << 16) // 60
    assert samples == [
        tuple(((origin + offset) * step + step // 2) >> 16 for offset in (x, y))
        for y in range(2)
        for x in range(2)
    ]
    assert _read_word(machine, inventory + InventoryFeatureCompiler._off_font_alpha_trace) == 1
    assert machine.reg_read(UC_X86_REG_ESP) == stack + 20


@pytest.mark.parametrize("slot", [0xB8, 0xBC])
@pytest.mark.parametrize("valid", [False, True])
def test_mouse_hit_callbacks_preserve_point_result_and_traces_with_rx_code(
    slot: int, *, valid: bool
) -> None:
    """Native callbacks and stale-target rejection never write instruction pages."""
    compiler = StaleMouseMoveCompiler(profile=GOG_BUILD)
    base, stack, stop = 0x800000, 0x308000, 0x401000
    owner, table, readable, codecheck, callback, point = range(0x210000, 0x216000, 0x1000)
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    payload = compiler._build_payload(section_va=base)
    machine.mem_map(base, (len(payload) + 4095) & ~4095)
    machine.mem_write(base, payload)
    machine.mem_protect(base, 4096, UC_PROT_READ | UC_PROT_EXEC)
    machine.mem_map(0x200000, 0x20000)
    machine.mem_map(0x300000, 0x20000)
    iats = [GOG_BUILD.address(f"win32.{name}") for name in ("IsBadReadPtr", "IsBadCodePtr")]
    for page in {address & ~4095 for address in iats}:
        machine.mem_map(page, 4096)
    _word(machine, iats[0], readable)
    _word(machine, iats[1], codecheck)
    machine.mem_write(readable, bytes.fromhex("31 c0 c2 08 00"))
    machine.mem_write(codecheck, bytes.fromhex("31 c0 c2 04 00"))
    native_result = 123
    machine.mem_write(callback, b"\xb8" + struct.pack("<I", native_result) + b"\xc2\x04\x00")
    _word(machine, owner, table)
    _word(machine, table + slot, callback)
    machine.mem_write(point, struct.pack("<2i", 17, 29))
    seen = []

    def inspect(cpu: Uc, address: int, _size: int, _data: object) -> None:
        if address == callback:
            seen.append(
                (cpu.reg_read(UC_X86_REG_ECX), _read_word(cpu, cpu.reg_read(UC_X86_REG_ESP) + 4))
            )

    machine.hook_add(UC_HOOK_CODE, inspect)
    machine.mem_write(stack, struct.pack("<2I", stop, point))
    machine.reg_write(UC_X86_REG_EAX, table if valid else 0)
    machine.reg_write(UC_X86_REG_ECX, owner)
    machine.reg_write(UC_X86_REG_ESP, stack)
    offset = compiler._off_tree_b8_wrapper if slot == 0xB8 else compiler._off_tree_bc_wrapper
    trace = compiler._off_tree_b8_trace if slot == 0xB8 else compiler._off_tree_bc_trace
    machine.emu_start(base + offset, stop, count=1000)
    assert seen == ([(owner, point)] if valid else [])
    assert machine.reg_read(UC_X86_REG_EAX) == (native_result if valid else 0)
    assert machine.reg_read(UC_X86_REG_ESP) == stack + 8
    assert _read_word(machine, base + compiler._off_tree_dropped_count) == int(not valid)
    assert _read_word(machine, base + trace) == int(valid)
    if valid:
        assert struct.unpack("<4I", machine.mem_read(base + trace + 4, 16)) == (
            owner,
            17,
            29,
            native_result,
        )


def test_transition_blt_preserves_native_result_with_read_only_instructions() -> None:
    """Blt diagnostics write state without faulting or changing COM cleanup."""
    compiler = TransitionFrameCompiler(profile=GOG_BUILD)
    base, surface, stack, frame = 0x800000, 0x200000, 0x308000, 0x310000
    code = compiler._build_payload(section_va=base)
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(base, (len(code) + 4095) & ~4095)
    machine.mem_write(base, code)
    for offset, _wrapper in compiler._build_wrappers(base):
        machine.mem_protect((base + offset) & ~4095, 4096, UC_PROT_READ | UC_PROT_EXEC)
    machine.mem_map(surface, 4096)
    machine.mem_map(0x300000, 0x20000)
    primary = GOG_BUILD.address("transition.primary_surface_ptr")
    machine.mem_map(primary & ~4095, 4096)
    _word(machine, surface, surface + 0x100)
    _word(machine, surface + 0x114, surface + 0x800)
    native_result = 0x12345678
    machine.mem_write(surface + 0x800, b"\xb8" + struct.pack("<I", native_result) + b"\xc2\x18\x00")
    machine.mem_write(stack, struct.pack("<7I", 0x401000, surface, 0, 0, 0, 0, 0))
    _word(machine, frame + 4, 0x402000)
    _word(machine, frame + 0x10, 99999)
    machine.reg_write(UC_X86_REG_ESP, stack)
    machine.reg_write(UC_X86_REG_EBP, frame)
    machine.reg_write(UC_X86_REG_EAX, surface)
    machine.emu_start(
        base + compiler._off_blt_wrapper,
        GOG_BUILD.address("transition.blt_continue"),
        count=1000,
    )
    assert machine.reg_read(UC_X86_REG_EAX) == native_result
    assert machine.reg_read(UC_X86_REG_ESP) == stack + 28
    assert _read_word(machine, base + compiler._off_blt_count) == 1
    assert _read_word(machine, base + compiler._off_blt_retry_current) == 1
    assert _read_word(machine, base + compiler._off_blt_retry_caller) == 0x402000
    assert struct.unpack("<4I", machine.mem_read(base + compiler._off_last_blt_state, 16)) == (
        native_result,
        surface,
        0,
        0,
    )


def test_installed_font_scope_restores_outer_state_with_read_only_instructions() -> None:
    """Ordinary glyphs retain their native draw and nested scope without code writes."""
    image = _source(GOG_BUILD)
    target, stop, font, stack, frame = 0x100000, 0x101000, 0x210000, 0x308000, 0x310000
    entries = install_font_bank_adapter(
        cast("PEFile", RuntimeImage(image)),
        profile=GOG_BUILD,
        target_va=target,
        active_handle_va=font + 0x100,
    )
    section = image.get_section(RuntimeLayout.section_name)
    assert section is not None
    base = image.rva_to_va(section.virtual_address)
    scope = base + FONT_BANK_SEGMENT.offset + FONT_BANK_SCOPE_OFFSET
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(base, (section.virtual_size + 4095) & ~4095)
    machine.mem_write(base, image.read_bytes(section.pointer_to_raw_data, section.virtual_size))
    for entry in (entries.registration_va, entries.draw_va):
        machine.mem_protect(entry & ~4095, 4096, UC_PROT_READ | UC_PROT_EXEC)
    machine.mem_map(target, 8192)
    machine.mem_map(font, 4096)
    machine.mem_map(0x300000, 0x20000)
    native_result, outer_scope = 0x12345678, 0xABCDEF
    machine.mem_write(target, b"\xb8" + struct.pack("<I", native_result) + b"\xc2\x14\x00")
    machine.mem_write(stack, struct.pack("<6I", stop, 0, 0, 0, 0, 0))
    _word(machine, frame - 0x14, font)
    _word(machine, scope, outer_scope)
    machine.reg_write(UC_X86_REG_ECX, font)
    machine.reg_write(UC_X86_REG_EBP, frame)
    machine.reg_write(UC_X86_REG_ESP, stack)
    machine.emu_start(entries.draw_va, stop, count=10000)
    assert machine.reg_read(UC_X86_REG_EAX) == native_result
    assert machine.reg_read(UC_X86_REG_ESP) == stack + 24
    assert _read_word(machine, scope) == outer_scope


def test_installed_root_publishes_full_damage_without_writing_instruction_pages() -> None:
    """A real root traversal preserves native arguments, result and scope cleanup."""
    image = PEFile(_source_bytes())
    section = image.get_section(RuntimeLayout.section_name)
    assert section is not None
    base = image.rva_to_va(section.virtual_address)
    system = base + SYSTEM_SEGMENT.offset
    control = base + SYSTEM_CONTROL_SEGMENT.offset
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(0x400000, 0x500000)
    machine.mem_write(base, image.read_bytes(section.pointer_to_raw_data, section.virtual_size))
    for start, size in ((system, SYSTEM_STATE_OFFSET), (control, SYSTEM_CONTROL_STATE_OFFSET)):
        machine.mem_protect(start, size, UC_PROT_READ | UC_PROT_EXEC)
    stack, root, stop = 0x308000, 0x210000, 0x101000
    machine.mem_map(0x300000, 0x20000)
    machine.mem_map(root, 4096)
    width = GOG_BUILD.address("display.dimensions")
    _word(machine, width, 3840)
    _word(machine, width + 4, 2160)
    native = GOG_BUILD.address("ui.container_draw")
    result, destination = 0x12345678, 0x55
    machine.mem_write(native, b"\xb8" + struct.pack("<I", result) + b"\xc2\x08\x00")
    machine.mem_write(stack, struct.pack("<3I", stop, destination, 0xDEADBEEF))
    calls: list[tuple[int, int, int, int]] = []

    def inspect(cpu: Uc, address: int, _size: int, _data: object) -> None:
        if address == native:
            esp = cpu.reg_read(UC_X86_REG_ESP)
            calls.append(
                (
                    cpu.reg_read(UC_X86_REG_ECX),
                    _read_word(cpu, esp + 4),
                    _read_word(cpu, esp + 8),
                    _read_word(cpu, system + SYSTEM_RENDER_DEPTH_OFFSET),
                )
            )

    machine.hook_add(UC_HOOK_CODE, inspect)
    machine.reg_write(UC_X86_REG_ECX, root)
    machine.reg_write(UC_X86_REG_ESP, stack)
    entry = image.read_u32_va(GOG_BUILD.address("death.vtable") + 0xA0)
    machine.emu_start(entry, stop, count=1000)
    assert calls == [(root, destination, control + SYSTEM_CONTROL_FULL_DAMAGE_REGION_OFFSET, 1)]
    assert machine.reg_read(UC_X86_REG_EAX) == result
    assert machine.reg_read(UC_X86_REG_ESP) == stack + 12
    assert _read_word(machine, system + SYSTEM_RENDER_DEPTH_OFFSET) == 0
    assert _read_word(machine, system + SYSTEM_INPUT_ACTIVE_OFFSET) == 1
    assert _read_word(machine, system + SYSTEM_ROOT_POINTER_OFFSET) == root
    rect = machine.mem_read(control + SYSTEM_CONTROL_FULL_DAMAGE_RECT_OFFSET, 16)
    assert struct.unpack("<4I", rect) == (0, 0, 3840, 2160)


def test_installed_resource_dispatch_observes_unknown_source_without_code_writes() -> None:
    """Unrecognized artwork keeps native arguments/result while publishing its observation."""
    image = PEFile(_source_bytes())
    section = image.get_section(RuntimeLayout.section_name)
    assert section is not None
    base = image.rva_to_va(section.virtual_address)
    resource = base + RESOURCE_SEGMENT.offset
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(0x400000, 0x500000)
    machine.mem_write(base, image.read_bytes(section.pointer_to_raw_data, section.virtual_size))
    # Adjacent owners have their own behavior tests. Their dormant callbacks do
    # nothing for this ordinary source, isolating the installed resource path.
    machine.mem_write(base + TIMEBLOCK_SEGMENT.offset + 0x100, b"\xc3")
    machine.mem_write(base + FINGERPRINT_SEGMENT.offset + 0x200, b"\xc3")
    machine.mem_protect(resource, RESOURCE_STATE_OFFSET, UC_PROT_READ | UC_PROT_EXEC)
    source, dest, rect, stop, stack = 0x210000, 0x211000, 0x212000, 0x101000, 0x308000
    machine.mem_map(source, 0x3000)
    machine.mem_map(0x300000, 0x20000)
    for surface in (source, dest):
        _word(machine, surface + 0x38, 16)
        _word(machine, surface + 0x3C, 16)
    dimensions = GOG_BUILD.address("display.dimensions")
    _word(machine, dimensions, 16)
    _word(machine, dimensions + 4, 16)
    native = GOG_BUILD.address("runtime2d.final_blt")
    result = 0x12345678
    machine.mem_write(native, b"\xb8" + struct.pack("<I", result) + b"\xc2\x0c\x00")
    machine.mem_write(stack, struct.pack("<4I", stop, source, rect, rect + 16))
    calls: list[tuple[int, int, int, int]] = []

    def inspect(cpu: Uc, address: int, _size: int, _data: object) -> None:
        if address == native:
            esp = cpu.reg_read(UC_X86_REG_ESP)
            calls.append(
                (cpu.reg_read(UC_X86_REG_ECX), *struct.unpack("<3I", cpu.mem_read(esp + 4, 12)))
            )

    machine.hook_add(UC_HOOK_CODE, inspect)
    machine.reg_write(UC_X86_REG_ECX, dest)
    machine.reg_write(UC_X86_REG_ESP, stack)
    machine.emu_start(resource + ResourceDispatchCompiler._off_wrapper, stop, count=3000)
    assert calls == [(dest, source, rect, rect + 16)]
    assert machine.reg_read(UC_X86_REG_EAX) == result
    assert machine.reg_read(UC_X86_REG_ESP) == stack + 16
    assert (
        _read_word(machine, resource + ResourceDispatchCompiler._off_closeup_observed_source)
        == source
    )


def _draw_interface(screen: str) -> tuple[PEFile, Uc]:
    """Traverse the installed root before sending events through its input route."""
    image = PEFile(_source_bytes())
    section = image.get_section(RuntimeLayout.section_name)
    assert section is not None
    base = image.rva_to_va(section.virtual_address)
    system = base + SYSTEM_SEGMENT.offset
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(0x400000, 0x500000)
    machine.mem_write(base, image.read_bytes(section.pointer_to_raw_data, section.virtual_size))
    machine.mem_protect(system, SYSTEM_STATE_OFFSET, UC_PROT_READ | UC_PROT_EXEC)
    root, child, children, stop, stack = 0x210000, 0x210200, 0x210400, 0x101000, 0x308000
    machine.mem_map(root, 4096)
    machine.mem_map(0x300000, 0x20000)
    _word(machine, GOG_BUILD.address("display.dimensions"), 1280)
    _word(machine, GOG_BUILD.address("display.dimensions") + 4, 800)
    root_type = GOG_BUILD.address(f"{screen}.vtable")
    _word(machine, root, root_type)
    _word(machine, root + 0x18, 1)
    _word(machine, root + 0x4C, children)
    _word(machine, root + 0x50, 1)
    _word(machine, children, child)
    _word(machine, child, GOG_BUILD.address("ui.button_vtable"))
    _word(machine, child + 0x18, 1)
    machine.mem_write(child + 0x1C, struct.pack("<4I", 895, 720, 976, 746))
    native_draw = GOG_BUILD.address("title.draw" if screen == "title" else "ui.container_draw")
    machine.mem_write(native_draw, bytes.fromhex("c2 08 00"))
    machine.mem_write(GOG_BUILD.address("bitmap.resolve_resource"), bytes.fromhex("31 c0 c2 04 00"))
    machine.mem_write(stack, struct.pack("<3I", stop, 123, 456))
    machine.reg_write(UC_X86_REG_ECX, root)
    machine.reg_write(UC_X86_REG_ESP, stack)
    machine.emu_start(image.read_u32_va(root_type + 0xA0), stop, count=3000)
    assert _read_word(machine, system + SYSTEM_RENDER_DEPTH_OFFSET) == 0
    return image, machine


@pytest.mark.parametrize("screen", ["title", "inventory"])
def test_drawn_interface_and_installed_input_share_the_same_coordinate_domain(screen: str) -> None:
    """Draw publishes the state actually consumed by the installed input route."""
    image, machine = _draw_interface(screen)
    root, point, stop, stack = 0x210000, 0x210500, 0x101000, 0x308000

    # Enter the actual installed button adapter, not a freshly built wrapper
    # wired to whichever private offsets the test happens to expect.
    site = GOG_BUILD.site("input.left_press_dispatch_call")
    hook = image.read_bytes(image.va_to_offset(site.va), 5)
    entry = site.va + 5 + struct.unpack("<i", hook[1:])[0]
    native_event = site.va + 5 + struct.unpack("<i", site.original[1:5])[0]
    machine.mem_write(native_event, bytes.fromhex("b8 78 56 34 12 c2 04 00"))
    current = GOG_BUILD.address("ui.current_layer")
    machine.mem_write(current, b"\xb8" + struct.pack("<I", root) + b"\xc3")
    presented = (885, 733) if screen == "title" else (640, 400)
    expected = (935, 732) if screen == "title" else (512, 384)
    machine.mem_write(point, struct.pack("<2I", *presented))
    cursor = GOG_BUILD.address("input.cursor_position")
    machine.mem_write(cursor, struct.pack("<2I", *presented))
    seen: list[tuple[int, int]] = []

    def inspect(cpu: Uc, address: int, _size: int, _data: object) -> None:
        if address == native_event:
            esp = cpu.reg_read(UC_X86_REG_ESP)
            argument = _read_word(cpu, esp + 4)
            seen.append(struct.unpack("<2I", cpu.mem_read(argument, 8)))
            assert struct.unpack("<2I", cpu.mem_read(cursor, 8)) == expected

    machine.hook_add(UC_HOOK_CODE, inspect)
    machine.mem_write(stack, struct.pack("<2I", stop, point))
    machine.reg_write(UC_X86_REG_ECX, 0x123456)
    machine.reg_write(UC_X86_REG_ESP, stack)
    machine.emu_start(entry, stop, count=3000)
    assert seen == [expected]
    assert machine.reg_read(UC_X86_REG_EAX) == 0x12345678
    assert machine.reg_read(UC_X86_REG_ESP) == stack + 8
    assert struct.unpack("<2I", machine.mem_read(point, 8)) == presented
    assert struct.unpack("<2I", machine.mem_read(cursor, 8)) == presented


def _loadsave_cache_machine(result: int) -> tuple[Uc, int, int, int]:
    """Provide a real installed cache helper with one synchronous COM surface."""
    image = PEFile(_source_bytes())
    section = image.get_section(RuntimeLayout.section_name)
    assert section is not None
    base = image.rva_to_va(section.virtual_address)
    loadsave = base + LOAD_SAVE_SEGMENT.offset
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(0x400000, 0x500000)
    machine.mem_write(base, image.read_bytes(section.pointer_to_raw_data, section.virtual_size))
    machine.mem_map(0x210000, 0x3000)
    machine.mem_map(0x300000, 0x20000)
    feature = LoadSaveFeatureCompiler
    owner, cache, vtable, native = 0x210000, 0x211000, 0x211100, 0x211800
    for address, value in (
        (GOG_BUILD.address("display.dimensions"), 1280),
        (GOG_BUILD.address("display.dimensions") + 4, 800),
        (GOG_BUILD.address("high_resolution_3d.directdraw_ptr"), owner),
        (GOG_BUILD.address("transition.back_surface_ptr"), 0x212000),
        (loadsave + feature._off_loadsave_cache_surface, cache),
        (loadsave + feature._off_loadsave_cache_owner, owner),
        (loadsave + feature._off_loadsave_cache_descriptor + 8, 800),
        (loadsave + feature._off_loadsave_cache_descriptor + 12, 1280),
        (cache, vtable),
        (vtable + 0x1C, native),
    ):
        _word(machine, address, value)
    control = base + SYSTEM_CONTROL_SEGMENT.offset
    rect = control + SYSTEM_CONTROL_FULL_DAMAGE_RECT_OFFSET
    region = control + SYSTEM_CONTROL_FULL_DAMAGE_REGION_OFFSET
    machine.mem_write(rect, struct.pack("<4I", 0, 0, 1280, 800))
    machine.mem_write(region, struct.pack("<3I", 0, rect, rect + 16))
    machine.mem_write(native, b"\xb8" + struct.pack("<I", result) + bytes.fromhex("c2 18 00"))
    machine.mem_write(loadsave + feature._off_loadsave_post_draw_cursor_presenter, b"\xc3")
    machine.mem_protect(loadsave, LOAD_SAVE_STATE_OFFSET, UC_PROT_READ | UC_PROT_EXEC)
    return machine, loadsave, native, rect


@pytest.mark.parametrize("result", [0, 0x887601AE])
def test_installed_loadsave_capture_keeps_instructions_read_only(result: int) -> None:
    """A successful or failed BltFast cannot fault on the translated code pages."""
    machine, loadsave, native, rect = _loadsave_cache_machine(result)
    feature = LoadSaveFeatureCompiler
    stop, stack, sentinel = 0x101000, 0x308000, 0x12345678
    calls: list[tuple[int, ...]] = []

    def inspect(cpu: Uc, address: int, _size: int, _data: object) -> None:
        if address == native:
            esp = cpu.reg_read(UC_X86_REG_ESP)
            calls.append(struct.unpack("<6I", cpu.mem_read(esp + 4, 24)))

    machine.hook_add(UC_HOOK_CODE, inspect)
    machine.mem_write(stack, struct.pack("<3I", stop, 123, 456))
    machine.reg_write(UC_X86_REG_EAX, sentinel)
    machine.reg_write(UC_X86_REG_ESP, stack)
    machine.emu_start(loadsave + feature._off_loadsave_cache_update_helper, stop, count=3000)
    scratch = loadsave + feature._off_loadsave_cache_scratch_rect
    assert calls == [(0x211000, 0, 0, 0x212000, scratch, 0x10)]
    assert machine.mem_read(scratch, 16) == machine.mem_read(rect, 16)
    assert _read_word(machine, loadsave + feature._off_loadsave_cache_capture_result) == result
    captured = _read_word(machine, loadsave + feature._off_loadsave_cache_capture_count)
    assert captured == int(result == 0)
    assert _read_word(machine, loadsave + feature._off_loadsave_cache_ready) == int(result == 0)
    assert machine.reg_read(UC_X86_REG_EAX) == sentinel
    assert machine.reg_read(UC_X86_REG_ESP) == stack + 12
