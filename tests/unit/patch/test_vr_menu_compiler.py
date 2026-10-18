"""Verify native menu hooks and execute atomic current-frame XR composition."""

from __future__ import annotations

import functools
import struct
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EFLAGS,
    UC_X86_REG_ESP,
)

from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.runtime2d.captions import CaptionFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.menu_tooltip import TooltipFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.menus import MenuFeatureCompiler
from gk3hd.patch.definitions.vr_menu_compiler import VRMenuCompiler
from gk3hd.patch.definitions.vr_panel import VRPanelCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError
from tests.unit.patch import test_vr_overlays
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine

if TYPE_CHECKING:
    from unicorn import Uc

    from gk3hd.patch.definitions.vr_menu_compiler import VRMenuABI

source = test_vr_overlays.source


def _compiled(source: bytes) -> tuple[PEFile, VRMenuCompiler]:
    data, compiler = _compiled_bytes(source)
    return PEFile(data), compiler


@functools.cache
def _compiled_bytes(source: bytes) -> tuple[bytes, VRMenuCompiler]:
    """Compile immutable test input once; never share mutable image/emulator state."""
    image = PEFile(source)
    scene = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40, deferred_frame=True)
    scene.apply(image)
    compiler = VRMenuCompiler(profile=GOG_BUILD, world_enabled_va=scene.abi(image).enabled_va)
    compiler.apply(image)
    compiler.postcheck(image)
    return image.to_bytes(), compiler


def test_menu_compiler_is_dormant_and_keeps_native_runtime_verifiable(source: bytes) -> None:
    image, compiler = _compiled(source)
    abi = compiler.abi(image)
    assert image.read_u32_va(abi.enabled_va) == 0
    assert image.read_u32_va(abi.action.surface_va) == 0
    assert image.read_u32_va(abi.toolbar.surface_va) == 0
    with pytest.raises(PatchError, match="already installed"):
        compiler.apply(image)


@pytest.mark.parametrize("toolbar", [False, True])
@pytest.mark.parametrize("owner", ["room", "sidney", "modal", "absent", "unreadable"])
@pytest.mark.parametrize(("enabled", "world"), [(True, True), (False, True), (True, False)])
def test_isolated_menu_capture_is_owned_only_by_the_current_room(
    source: bytes, owner: str, *, toolbar: bool, enabled: bool, world: bool
) -> None:
    image, compiler = _compiled(source)
    abi = compiler.abi(image)
    hooks = MenuFeatureCompiler.native_hooks_abi(image, GOG_BUILD)
    root = hooks.toolbar if toolbar else hooks.action
    cache = abi.toolbar if toolbar else abi.action
    cpu = _machine(image)
    current = _HEAP + 0x1000
    readable = _HEAP + 0x3000
    cpu.mem_write(
        readable, b"\xb8" + struct.pack("<I", int(owner == "unreadable")) + b"\xc2\x08\x00"
    )
    cpu.mem_write(GOG_BUILD.address("win32.IsBadReadPtr"), struct.pack("<I", readable))
    table = {
        "room": GOG_BUILD.address("vr.room_layer_vtable"),
        "sidney": 0x690540,
        "modal": 0x12345678,
        "absent": 0,
        "unreadable": GOG_BUILD.address("vr.room_layer_vtable"),
    }[owner]
    cpu.mem_write(current, struct.pack("<I", table))
    cpu.mem_write(
        GOG_BUILD.address("ui.current_layer"),
        b"\xb8" + struct.pack("<I", current if table else 0) + b"\xc3",
    )
    _write_words(cpu, ((abi.enabled_va, int(enabled)), (abi.world_enabled_va, int(world))))
    entry = image.read_u32_va(root.vtable_va + 0xA0)
    # Observe the ordinary downstream draw boundary, independent of its cache
    # allocation details. The gate must preserve the complete native thiscall.
    cpu.mem_write(entry + 0x100, bytes.fromhex("b8 7b 00 00 00 c2 08 00"))
    cpu.mem_write(_STACK, struct.pack("<3I", _RETURN, 1234, 5678))
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.reg_write(UC_X86_REG_ECX, _HEAP + 0x2000)
    cpu.reg_write(UC_X86_REG_EBX, 77)
    cpu.reg_write(UC_X86_REG_EFLAGS, 0x202)
    cpu.emu_start(entry, _RETURN, count=500)
    assert _read(cpu, cache.surface_va - 4) == int(enabled and world and owner == "room")
    assert cpu.reg_read(UC_X86_REG_EAX) == 123
    assert cpu.reg_read(UC_X86_REG_ECX) == _HEAP + 0x2000
    assert cpu.reg_read(UC_X86_REG_EBX) == 77
    assert cpu.reg_read(UC_X86_REG_EFLAGS) == 0x202
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 12
    assert bytes(cpu.mem_read(_STACK + 4, 8)) == struct.pack("<2I", 1234, 5678)


@pytest.mark.parametrize("fault", ["draw", "destructor", "helper", "seh", "load_config", "world"])
def test_unverified_native_dependencies_are_rejected_without_writes(
    source: bytes, fault: str
) -> None:
    image = PEFile(source)
    scene = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40, deferred_frame=True)
    scene.apply(image)
    hooks = MenuFeatureCompiler.native_hooks_abi(image, GOG_BUILD)
    world = scene.abi(image).enabled_va
    if fault == "draw":
        image.write_u32_va(hooks.action.vtable_va + 0xA0, hooks.action.draw_va + 1)
    elif fault == "destructor":
        image.write_u32_va(hooks.toolbar.vtable_va, hooks.toolbar.destructor_va + 1)
    elif fault == "helper":
        image.write_bytes(image.va_to_offset(hooks.action.draw_va), b"\xcc")
    elif fault == "seh":
        image.write_bytes(image.optional_offset + 70, struct.pack("<H", 0x400))
    elif fault == "load_config":
        image.write_bytes(image.optional_offset + 96 + 10 * 8, struct.pack("<2I", 0x1000, 72))
    else:
        world += 4
    before = image.to_bytes()
    with pytest.raises(PatchError):
        VRMenuCompiler(profile=GOG_BUILD, world_enabled_va=world).apply(image)
    assert image.to_bytes() == before


@pytest.mark.parametrize("fault", ["state", "helper", "draw", "destructor"])
def test_modified_menu_installation_fails_full_verification(source: bytes, fault: str) -> None:
    image, compiler = _compiled(source)
    abi = compiler.abi(image)
    hooks = MenuFeatureCompiler.native_hooks_abi(image, GOG_BUILD)
    address = {
        "state": abi.enabled_va,
        "helper": abi.query_va,
        "draw": hooks.action.vtable_va + 0xA0,
        "destructor": hooks.toolbar.vtable_va,
    }[fault]
    image.write_u32_va(address, 0)
    if fault == "state":
        image.write_u32_va(address, 1)
    with pytest.raises(PatchError):
        compiler.postcheck(image)


def _query_machine(source: bytes) -> tuple[Uc, VRMenuABI, int]:
    image, compiler = _compiled(source)
    abi = compiler.abi(image)
    hooks = MenuFeatureCompiler.native_hooks_abi(image, GOG_BUILD)
    cpu = _machine(image)
    cpu.mem_map(_HEAP + 0x10000, 0x8000)
    frame, room, children = _HEAP + 0x10000, _HEAP + 0x11000, _HEAP + 0x12000
    current, readable = _HEAP + 0x13000, _HEAP + 0x14000
    action, toolbar = _HEAP + 0x15000, _HEAP + 0x16000

    def word(address: int, *values: int) -> None:
        cpu.mem_write(address, struct.pack(f"<{len(values)}I", *values))

    word(abi.enabled_va, 1)
    word(abi.world_enabled_va, 1)
    word(GOG_BUILD.address("win32.IsBadReadPtr"), readable)
    cpu.mem_write(readable, bytes.fromhex("31 c0 c2 08 00"))
    cpu.mem_write(
        GOG_BUILD.address("ui.current_layer"), b"\xb8" + struct.pack("<I", room) + b"\xc3"
    )
    cpu.mem_write(current, b"\xc3")
    word(room, GOG_BUILD.address("vr.room_layer_vtable"))
    word(room + 0x4C, children, 2)
    word(children, action, toolbar)
    word(action, hooks.action.vtable_va)
    word(toolbar, hooks.toolbar.vtable_va)
    word(action + 0x18, 1)
    word(toolbar + 0x18, 1)
    for index, (cache, root) in enumerate(((abi.action, action), (abi.toolbar, toolbar))):
        cpu.mem_write(cache.validate_va, bytes.fromhex("b8 01 00 00 00 c3"))
        word(cache.surface_va, 0x123 + index)
        word(cache.ready_va, 1)
        word(cache.root_va, root)
        cpu.mem_write(
            cache.rect_va, struct.pack("<4i", 100 + 300 * index, 200, 300 + 300 * index, 250)
        )
        word(cache.surface_va + 4, 1280, 800)
        if cache.coverage is not None:
            cpu.mem_write(cache.coverage.validate_va, bytes.fromhex("b8 01 00 00 00 c3"))
            cpu.mem_write(cache.coverage.body_rect_va, bytes(cpu.mem_read(cache.rect_va, 16)))
            word(cache.coverage.ready_va, 1)
    word(frame, 188)
    # Initial panel dimensions are deliberately zero. Clipping must use the
    # current validator-qualified cache extent, not the previous XR frame.
    return cpu, abi, frame


def _read(cpu: Uc, address: int) -> int:
    return struct.unpack("<I", cpu.mem_read(address, 4))[0]


def _run(cpu: Uc, abi: VRMenuABI, frame: int) -> int:
    cpu.mem_write(_STACK, struct.pack("<2I", _RETURN, frame))
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.reg_write(UC_X86_REG_EBX, 77)
    cpu.reg_write(UC_X86_REG_EFLAGS, 0x202)
    cpu.emu_start(abi.query_va, _RETURN, count=5000)
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 8
    assert cpu.reg_read(UC_X86_REG_EBX) == 77
    assert cpu.reg_read(UC_X86_REG_EFLAGS) == 0x202
    return cpu.reg_read(UC_X86_REG_EAX)


@pytest.mark.parametrize("owner", ["sidney", "modal", "absent"])
def test_non_room_frame_publication_withdraws_isolated_cache_ownership(
    source: bytes, owner: str
) -> None:
    cpu, abi, frame = _query_machine(source)
    room = _HEAP + 0x11000
    table = {"sidney": 0x690540, "modal": 0x12345678, "absent": 0}[owner]
    cpu.mem_write(room, struct.pack("<I", table))
    if not table:
        cpu.mem_write(GOG_BUILD.address("ui.current_layer"), bytes.fromhex("31 c0 c3"))
    assert _run(cpu, abi, frame) == 0
    assert _read(cpu, frame + 188) == 0
    for cache in (abi.action, abi.toolbar):
        assert _read(cpu, cache.surface_va - 4) == 0


@pytest.mark.parametrize("reversed_order", [False, True])
def test_visible_menus_append_in_native_order_with_exact_opaque_coverage(
    source: bytes, *, reversed_order: bool
) -> None:
    cpu, abi, frame = _query_machine(source)
    children = _HEAP + 0x12000
    if reversed_order:
        cpu.mem_write(children, struct.pack("<2I", _HEAP + 0x16000, _HEAP + 0x15000))
    assert _run(cpu, abi, frame) == 1
    assert _read(cpu, frame + 188) == 2
    assert _read(cpu, frame + 4) & 4, "only completed native menu crops enable readable placement"
    parts = [struct.unpack("<3I6i", cpu.mem_read(frame + 192 + i * 40, 36)) for i in range(2)]
    assert [
        struct.unpack("<f", cpu.mem_read(frame + 192 + i * 40 + 36, 4))[0] for i in range(2)
    ] == [1, 1]
    expected = [
        (0x123, 2, 0, 100, 200, 300, 250, 100, 200),
        (0x124, 2, 0, 400, 200, 600, 250, 400, 200),
    ]
    assert parts == (list(reversed(expected)) if reversed_order else expected)


@pytest.mark.parametrize(
    "fault",
    [
        "late_stale",
        "other_root",
        "duplicate",
        "dropdown",
        "pending_dropdown",
        "unreadable_child",
        "unreadable_list",
        "unreadable_room",
        "oversized_list",
        "offscreen",
        "disabled",
        "world_disabled",
        "capacity",
    ],
)
def test_incomplete_menu_coverage_rolls_back_the_entire_batch(source: bytes, fault: str) -> None:
    cpu, abi, frame = _query_machine(source)
    hooks = MenuFeatureCompiler.native_hooks_abi(PEFile(source), GOG_BUILD)
    room, children, toolbar = _HEAP + 0x11000, _HEAP + 0x12000, _HEAP + 0x16000

    def word(address: int, value: int) -> None:
        cpu.mem_write(address, struct.pack("<I", value))

    initial_count = 15 if fault == "capacity" else 1
    word(frame + 188, initial_count)
    sentinel = bytes(range(36))
    cpu.mem_write(frame + 192, sentinel)
    patches = {
        "late_stale": (abi.toolbar.ready_va, 0),
        "other_root": (abi.toolbar.root_va, toolbar + 4),
        "duplicate": (children + 4, _HEAP + 0x15000),
        "dropdown": (toolbar, GOG_BUILD.address("resolution_dropdown.vtable")),
        "pending_dropdown": (hooks.dropdown_pending_va, toolbar),
        "oversized_list": (room + 0x50, 257),
        "disabled": (abi.enabled_va, 0),
        "world_disabled": (abi.world_enabled_va, 0),
    }
    if fault in patches:
        word(*patches[fault])
    elif fault == "offscreen":
        coverage = abi.toolbar.coverage
        assert coverage is not None
        cpu.mem_write(coverage.body_rect_va, struct.pack("<4i", 2000, 200, 2100, 300))
    elif fault.startswith("unreadable"):
        bad = {"unreadable_child": toolbar, "unreadable_list": children, "unreadable_room": room}[
            fault
        ]

        def readable(machine: Uc, address: int, _size: int, _data: object) -> None:
            if address == _HEAP + 0x14000:
                stack = machine.reg_read(UC_X86_REG_ESP)
                machine.reg_write(UC_X86_REG_EAX, int(_read(machine, stack + 4) == bad))

        cpu.mem_write(_HEAP + 0x14000, bytes.fromhex("c2 08 00"))
        cpu.hook_add(UC_HOOK_CODE, readable)
    assert _run(cpu, abi, frame) == 0
    assert _read(cpu, frame + 188) == initial_count
    assert not _read(cpu, frame + 4) & 4, "failed menu batches must not enlarge ordinary labels"
    assert cpu.mem_read(frame + 192, 36) == sentinel


def test_absent_native_menus_do_not_enlarge_ordinary_labels(source: bytes) -> None:
    cpu, abi, frame = _query_machine(source)
    cpu.mem_write(_HEAP + 0x11000 + 0x50, struct.pack("<I", 0))
    cpu.mem_write(frame + 188, struct.pack("<I", 1))
    assert _run(cpu, abi, frame) == 1
    assert _read(cpu, frame + 188) == 1
    assert not _read(cpu, frame + 4) & 4


@pytest.mark.parametrize("rectangle", [(-20, -10, 200, 50), (1200, 760, 1400, 900)])
def test_screen_clipping_keeps_the_same_source_origin_and_hit_coordinates(
    source: bytes, rectangle: tuple[int, int, int, int]
) -> None:
    cpu, abi, frame = _query_machine(source)
    cpu.mem_write(abi.action.rect_va, struct.pack("<4i", *rectangle))
    assert _run(cpu, abi, frame) == 1
    part = struct.unpack("<3I6i", cpu.mem_read(frame + 192, 36))
    left, top, right, bottom = rectangle
    assert part == (
        0x123,
        2,
        0,
        max(left, 0),
        max(top, 0),
        min(right, 1280),
        min(bottom, 800),
        max(left, 0),
        max(top, 0),
    )


@pytest.mark.parametrize("disabled", ["menus", "world"])
def test_disabled_xr_releases_both_caches_without_another_native_draw(
    source: bytes, disabled: str
) -> None:
    image, _ = _compiled(source)
    cpu, abi, frame = _query_machine(source)
    release_entry = _HEAP + 0x17C00
    cpu.mem_write(release_entry, bytes.fromhex("31 c0 c2 04 00"))
    released: list[int] = []

    def observe(machine: Uc, address: int, _size: int, _context: object) -> None:
        if address == release_entry:
            released.append(_read(machine, machine.reg_read(UC_X86_REG_ESP) + 4))

    cpu.hook_add(UC_HOOK_CODE, observe)
    for index, cache in enumerate((abi.action, abi.toolbar)):
        surface, table = _HEAP + 0x17000 + index * 0x100, _HEAP + 0x17600 + index * 0x100
        _write_words(
            cpu, ((cache.surface_va, surface), (surface, table), (table + 8, release_entry))
        )
        cpu.mem_write(
            cache.validate_va, image.read_bytes(image.va_to_offset(cache.validate_va), 0x200)
        )
    _write_words(cpu, (((abi.enabled_va if disabled == "menus" else abi.world_enabled_va), 0),))
    assert _run(cpu, abi, frame) == 0
    assert released == [_HEAP + 0x17000, _HEAP + 0x17100]
    for cache in (abi.action, abi.toolbar):
        assert _read(cpu, cache.surface_va) == 0
        assert _read(cpu, cache.ready_va) == 0
        assert _read(cpu, cache.root_va) == 0


@pytest.mark.parametrize("changed", ["world", "cells", "tooltip"])
def test_panel_rejects_unverified_menu_sources(source: bytes, changed: str) -> None:
    image, compiler = _compiled(source)
    menus = compiler.abi(image)
    if changed == "cells":
        menus = replace(menus, enabled_va=menus.enabled_va + 4)
    if changed == "world":
        menus = replace(menus, world_enabled_va=menus.world_enabled_va + 4)
    hooks = MenuFeatureCompiler.native_hooks_abi(image, GOG_BUILD)
    panel = VRPanelCompiler(
        profile=GOG_BUILD,
        expected_presenter_va=hooks.frame_presenter_va,
        world_enabled_va=compiler.world_enabled_va,
        menus=menus,
        tooltip=None if changed == "tooltip" else TooltipFeatureCompiler.cache_abi(image),
    )
    before = image.to_bytes()
    with pytest.raises(PatchError, match="menus"):
        panel.apply(image)
    assert image.to_bytes() == before


@pytest.mark.parametrize("owner", [0, 1, 2, 3], ids=["closed", "world", "modal", "menus"])
@pytest.mark.parametrize("available", [False, True])
@pytest.mark.parametrize("labels", [False, True])
def test_panel_composes_menus_and_labels_but_retains_atomic_fallback(
    source: bytes, owner: int, *, available: bool, labels: bool
) -> None:
    image, menus = _compiled(source)
    menu = menus.abi(image)
    caption = CaptionFeatureCompiler.cache_abi(image)
    tooltip = TooltipFeatureCompiler.cache_abi(image)
    native = MenuFeatureCompiler.native_hooks_abi(image, GOG_BUILD)
    compiler = VRPanelCompiler(
        profile=GOG_BUILD,
        expected_presenter_va=native.frame_presenter_va,
        world_enabled_va=menus.world_enabled_va,
        caption=caption,
        tooltip=tooltip,
        menus=menu,
    )
    compiler.apply(image)
    compiler.postcheck(image)
    panel = compiler.abi(image)
    cpu = _machine(image)
    module, resolve, bridge, ownership = (
        _HEAP + value for value in (0xA000, 0xA100, 0xA200, 0xA300)
    )
    wrapper, device = _HEAP + 0x5000, _HEAP + 0x6000

    def word(address: int, value: int) -> None:
        cpu.mem_write(address, struct.pack("<I", value))

    _write_words(
        cpu,
        (
            (panel.enabled_va, 1),
            # The preceding frame contained a readable menu. Current ownership
            # must retire that placement when only captions or a modal remain.
            (panel.frame_va + 4, 7),
            (menu.enabled_va, 1),
            (menus.world_enabled_va, 1),
            (GOG_BUILD.address("win32.GetModuleHandleA"), module),
            (GOG_BUILD.address("win32.GetProcAddress"), resolve),
            (GOG_BUILD.address("high_resolution_3d.render_wrapper_ptr"), wrapper),
            (wrapper + 0x4E8, device),
            (panel.ownership_query_slot_va, ownership),
            (caption.ready_va, 1),
            (caption.surface_va, _HEAP + 0x8000),
            (tooltip.visible_va, 1),
            (tooltip.pending_va, 0),
            (tooltip.surface_va, _HEAP + 0x9000),
        ),
    )
    for name, value, pointer in (
        ("high_resolution_3d.display_width_ptr", 1280, _HEAP + 0xC000),
        ("high_resolution_3d.display_height_ptr", 800, _HEAP + 0xC004),
    ):
        word(GOG_BUILD.address(name), pointer)
        word(pointer, value)
    _write_code(
        cpu,
        (
            (native.frame_presenter_va, b"\xc3"),
            (module, bytes.fromhex("c2 04 00")),
            (resolve, bytes.fromhex("c2 08 00")),
            (bridge, bytes.fromhex("c2 0c 00")),
            (ownership, b"\xb8" + struct.pack("<I", owner) + b"\xc3"),
            (menu.query_va, b"\xb8" + struct.pack("<I", available) + b"\xc2\x04\x00"),
        ),
    )
    calls: list[str] = []
    submissions: list[tuple[int, list[int]]] = []
    readable_submissions: list[bool] = []

    def observe(machine: Uc, address: int, _size: int, _context: object) -> None:
        if address == native.frame_presenter_va:
            calls.append("native")
            _refresh_labels(
                machine, (caption.replay_count_va, tooltip.replay_count_va), enabled=labels
            )
        elif address == menu.query_va:
            calls.append("menus")
            assert _read(machine, machine.reg_read(UC_X86_REG_ESP) + 4) == panel.frame_va
            assert _read(machine, panel.frame_va + 188) == 0
            if owner == 3 and available:
                word(panel.frame_va + 188, 1)
                word(panel.frame_va + 4, _read(machine, panel.frame_va + 4) | 4)
                cpu.mem_write(
                    panel.frame_va + 192, struct.pack("<3I6i", 123, 2, 0, 10, 20, 30, 40, 10, 20)
                )
        elif address == module:
            machine.reg_write(UC_X86_REG_EAX, 123)
        elif address == resolve:
            machine.reg_write(UC_X86_REG_EAX, bridge)
        elif address == bridge:
            calls.append("submit")
            submissions.append(_read_submission(machine, panel.frame_va))
            readable_submissions.append(bool(_read(machine, panel.frame_va + 4) & 4))
            machine.reg_write(UC_X86_REG_EAX, 0)

    cpu.hook_add(UC_HOOK_CODE, observe)
    slot = TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va
    entry = image.read_u32_va(slot)
    _invoke_presenter(cpu, entry)
    assert submissions == [_expected_submission(owner, available=available, labels=labels)]
    assert readable_submissions == [owner == 3 and available]
    assert calls.index("native") < calls.index("menus") < calls.index("submit")
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 4


def _refresh_labels(cpu: Uc, counters: tuple[int, int], *, enabled: bool) -> None:
    if enabled:
        for counter in counters:
            cpu.mem_write(counter, struct.pack("<I", _read(cpu, counter) + 1))


def _write_words(cpu: Uc, values: tuple[tuple[int, int], ...]) -> None:
    for address, value in values:
        cpu.mem_write(address, struct.pack("<I", value))


def _write_code(cpu: Uc, instructions: tuple[tuple[int, bytes], ...]) -> None:
    for address, code in instructions:
        cpu.mem_write(address, code)


def _read_submission(cpu: Uc, frame: int) -> tuple[int, list[int]]:
    operation = _read(cpu, cpu.reg_read(UC_X86_REG_ESP) + 8)
    count = _read(cpu, frame + 188) if operation in (4, 5) else 0
    return operation, [_read(cpu, frame + 192 + i * 40) for i in range(count)]


def _invoke_presenter(cpu: Uc, entry: int) -> None:
    cpu.mem_write(_STACK, struct.pack("<I", _RETURN))
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.emu_start(entry, _RETURN, count=5000)


def _expected_submission(owner: int, *, available: bool, labels: bool) -> tuple[int, list[int]]:
    if owner == 2 or (owner == 3 and not available):
        # Keep the atomic native page when menus are not isolated, but retain
        # its fresh readable dialogue. World tooltips must not leak onto it.
        return (5, [_HEAP + 0x8000]) if labels else (0, [])
    surfaces = [123] if owner == 3 and available else []
    if labels and (owner == 1 or (owner == 3 and available)):
        surfaces += [_HEAP + 0x8000, _HEAP + 0x9000]
    expected_operation = 1 if owner == 0 else 4 if surfaces else 2
    return expected_operation, surfaces
