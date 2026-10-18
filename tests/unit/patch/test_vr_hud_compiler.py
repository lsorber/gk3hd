"""Execute current-page HUD composition, native draw and lifetime ownership."""

from __future__ import annotations

import functools
import struct
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDX,
    UC_X86_REG_EFLAGS,
    UC_X86_REG_ESP,
)

from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.runtime2d.captions import CaptionFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.menu_tooltip import TooltipFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.room_status import RoomStatusFeatureCompiler
from gk3hd.patch.definitions.vr_hud_compiler import VRHudCompiler
from gk3hd.patch.definitions.vr_menu_compiler import VRMenuCompiler
from gk3hd.patch.definitions.vr_panel import VRPanelCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError
from tests.unit.patch import test_vr_overlays
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine

if TYPE_CHECKING:
    from unicorn import Uc

    from gk3hd.patch.definitions.vr_hud_compiler import VRHudABI

source = test_vr_overlays.source
_FRAME, _ROOM, _CHILDREN, _TEXT, _READABLE = range(_HEAP + 0x10000, _HEAP + 0x15000, 0x1000)


def _compiled(source: bytes, *, menus: bool = False) -> tuple[PEFile, VRHudCompiler]:
    data, compiler = _compiled_bytes(source, menus=menus)
    return PEFile(data), compiler


@functools.cache
def _compiled_bytes(source: bytes, *, menus: bool) -> tuple[bytes, VRHudCompiler]:
    """Reuse compiled bytes, not the mutable image inspected by each test."""
    image = PEFile(source)
    image.write_u32_va(
        GOG_BUILD.address("room_text.vtable"), GOG_BUILD.address("room_text.destructor")
    )
    scene = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40, deferred_frame=True)
    scene.apply(image)
    if menus:
        VRMenuCompiler(profile=GOG_BUILD, world_enabled_va=scene.abi(image).enabled_va).apply(image)
    compiler = VRHudCompiler(profile=GOG_BUILD, world_enabled_va=scene.abi(image).enabled_va)
    compiler.apply(image)
    compiler.postcheck(image)
    return image.to_bytes(), compiler


@pytest.mark.parametrize("menus", [False, True])
def test_verified_dormant_hud_composes_with_native_producers(source: bytes, *, menus: bool) -> None:
    image, compiler = _compiled(source, menus=menus)
    abi = compiler.abi(image)
    assert image.read_u32_va(abi.enabled_va) == 0
    slot = TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va
    panel = VRPanelCompiler(
        profile=GOG_BUILD,
        expected_presenter_va=image.read_u32_va(slot),
        world_enabled_va=abi.world_enabled_va,
        caption=CaptionFeatureCompiler.cache_abi(image),
        tooltip=TooltipFeatureCompiler.cache_abi(image),
        hud=abi,
        menus=VRMenuCompiler(profile=GOG_BUILD, world_enabled_va=abi.world_enabled_va).abi(image)
        if menus
        else None,
    )
    panel.apply(image)
    panel.postcheck(image)
    compiler.postcheck(image)
    with pytest.raises(PatchError, match="already installed"):
        compiler.apply(image)


@pytest.mark.parametrize("fault", ["payload", "draw", "destructor"])
def test_changed_hud_bytes_or_bindings_fail_verification(source: bytes, fault: str) -> None:
    image, compiler = _compiled(source)
    hooks = RoomStatusFeatureCompiler.native_hooks_abi(image, GOG_BUILD)
    address = {
        "payload": compiler.abi(image).query_va,
        "draw": hooks.vtable_va + 0xA0,
        "destructor": hooks.vtable_va,
    }[fault]
    image.write_u32_va(address, 0)
    with pytest.raises(PatchError):
        compiler.postcheck(image)


def _word(cpu: Uc, address: int, *values: int) -> int:
    if values:
        cpu.mem_write(address, struct.pack(f"<{len(values)}I", *values))
    return struct.unpack("<I", cpu.mem_read(address, 4))[0]


def _query_machine(source: bytes) -> tuple[Uc, VRHudCompiler, VRHudABI]:
    image, compiler = _compiled(source)
    abi = compiler.abi(image)
    cpu = _machine(image)
    cpu.mem_map(_HEAP + 0x10000, 0x8000)
    _word(cpu, abi.enabled_va, 1)
    _word(cpu, abi.world_enabled_va, 1)
    _word(cpu, GOG_BUILD.address("win32.IsBadReadPtr"), _READABLE)
    cpu.mem_write(_READABLE, bytes.fromhex("31 c0 c2 08 00"))
    cpu.mem_write(
        GOG_BUILD.address("ui.current_layer"), b"\xb8" + struct.pack("<I", _ROOM) + b"\xc3"
    )
    _word(cpu, _ROOM, GOG_BUILD.address("transition.room_layer_vtable"))
    _word(cpu, _ROOM + 0x4C, _CHILDREN, 1)
    _word(cpu, _CHILDREN, _TEXT)
    _word(cpu, _TEXT, GOG_BUILD.address("room_text.vtable"))
    _word(cpu, _TEXT + 0x18, 1)
    cpu.mem_write(_TEXT + 0x1C, struct.pack("<4i", 5, 5, 392, 22))
    cpu.mem_write(_TEXT + 0x5C, struct.pack("<I4f", 1, 0.25, 0.75, 0, 0))
    cpu.mem_write(_TEXT + 0x88, struct.pack("<f", 0.375))
    for index, part in enumerate((abi.glyph, abi.backing)):
        _word(cpu, part.cache_va, 1, 0x123 + index, 1280, 800, 0x333)
        _word(cpu, part.cache_va + 32, _TEXT)
        _word(cpu, part.cache_va + 0x70, 1)
        cpu.mem_write(part.cache_va + 0x180, bytes(cpu.mem_read(_TEXT + 0x1C, 16)))
        _word(cpu, part.state_va, 1, _TEXT)
        cpu.mem_write(part.state_va + 16, struct.pack("<2f", 0.25, 0.375))
        cpu.mem_write(part.state_va + 24, bytes(cpu.mem_read(_TEXT + 0x5C, 20)))
        _word(cpu, part.state_va + 56, _TEXT, 1)
        # Query tests isolate publication. Separate existing cache validator
        # tests execute native page/owner/dimension qualification.
        cpu.mem_write(part.validate_va, bytes.fromhex("b8 01 00 00 00 c3"))
        cpu.mem_write(part.validate_va - 0xA00, b"\xc3")  # Bounded fake Release.
    _word(cpu, _FRAME, 188)
    return cpu, compiler, abi


def _query(cpu: Uc, abi: VRHudABI) -> int:
    _word(cpu, _STACK, _RETURN, _FRAME)
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.reg_write(UC_X86_REG_EBX, 77)
    cpu.reg_write(UC_X86_REG_EFLAGS, 0x202)
    cpu.emu_start(abi.query_va, _RETURN, count=12000)
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 8
    assert cpu.reg_read(UC_X86_REG_EBX) == 77
    assert cpu.reg_read(UC_X86_REG_EFLAGS) == 0x202
    return cpu.reg_read(UC_X86_REG_EAX)


@pytest.mark.parametrize("alpha", [0.0, 0.075, 0.25, 0.825, 1.0])
@pytest.mark.parametrize("background", [0.0, 0.375, 1.0])
def test_hud_preserves_authored_fades_with_backing_then_glyphs(
    source: bytes, alpha: float, background: float
) -> None:
    cpu, _, abi = _query_machine(source)
    cpu.mem_write(_TEXT + 0x5C, struct.pack("<I4f", 1, alpha, 1 - alpha, 0, 0))
    cpu.mem_write(_TEXT + 0x88, struct.pack("<f", background))
    for part in (abi.glyph, abi.backing):
        cpu.mem_write(part.state_va + 16, struct.pack("<2f", alpha, background))
        cpu.mem_write(part.state_va + 24, bytes(cpu.mem_read(_TEXT + 0x5C, 20)))
    assert _query(cpu, abi) == 1
    count = _word(cpu, _FRAME + 188)
    expected = [(0x124, background)] * bool(background) + [(0x123, alpha)] * bool(alpha)
    assert count == len(expected)
    for index, (surface, opacity) in enumerate(expected):
        words = struct.unpack("<3I6if", cpu.mem_read(_FRAME + 192 + index * 40, 40))
        assert words[:9] == (surface, 1, 1, 5, 5, 409, 23, 5, 5)
        assert words[9] == pytest.approx(opacity)


@pytest.mark.parametrize("position", [0, 1, 2])
def test_toolbar_siblings_do_not_hide_or_reposition_fading_status(
    source: bytes, position: int
) -> None:
    cpu, _, abi = _query_machine(source)
    siblings = [_TEXT + 0x200, _TEXT + 0x300]
    for sibling in siblings:
        _word(cpu, sibling, 0xDEADBEEF)
    siblings.insert(position, _TEXT)
    _word(cpu, _CHILDREN, *siblings)
    _word(cpu, _ROOM + 0x50, len(siblings))
    assert _query(cpu, abi) == 1
    assert _word(cpu, _FRAME + 188) == 2
    assert struct.unpack("<3I6if", cpu.mem_read(_FRAME + 192 + 40, 40)) == (
        0x123,
        1,
        1,
        5,
        5,
        409,
        23,
        5,
        5,
        0.25,
    )


def test_status_at_end_of_bounded_child_vector_is_found(source: bytes) -> None:
    cpu, _, abi = _query_machine(source)
    sibling = _TEXT + 0x200
    _word(cpu, sibling, 0xDEADBEEF)
    _word(cpu, _ROOM + 0x50, 256)
    _word(cpu, _CHILDREN, *([sibling] * 255), _TEXT)
    assert _query(cpu, abi) == 1
    assert _word(cpu, _FRAME + 188) == 2


@pytest.mark.parametrize("fault", ["duplicate", "another_text", "unreadable_sibling", "span"])
def test_ambiguous_or_unreadable_room_children_never_publish_stale_status(
    source: bytes, fault: str
) -> None:
    cpu, _, abi = _query_machine(source)
    sibling = _TEXT + 0x200
    _word(cpu, sibling, GOG_BUILD.address("room_text.vtable"))
    _word(cpu, _ROOM + 0x50, 2)
    _word(cpu, _CHILDREN, _TEXT, _TEXT if fault == "duplicate" else sibling)
    if fault == "unreadable_sibling":
        cpu.mem_write(
            _READABLE,
            bytes.fromhex("31 c0 81 7c 24 04")
            + struct.pack("<I", sibling)
            + bytes.fromhex("0f 94 c0 c2 08 00"),
        )
    if fault == "span":
        # A one-pointer probe would pass, but the actual two-pointer vector
        # is inaccessible. No child read or old-cache replay is authorized.
        cpu.mem_write(
            _READABLE,
            bytes.fromhex("31 c0 83 7c 24 08 08 0f 94 c0 c2 08 00"),
        )
    assert _query(cpu, abi) == 0
    assert _word(cpu, _FRAME + 188) == 0
    assert _word(cpu, abi.glyph.state_va + 4) == 0


@pytest.mark.parametrize(
    "fault",
    [
        "owner",
        "snapshot",
        "rect",
        "glyph",
        "backing",
        "back_owner",
        "back_rect",
        "cache",
        "capacity",
    ],
)
def test_unqualified_hud_rolls_back_without_partial_publication(source: bytes, fault: str) -> None:
    cpu, _, abi = _query_machine(source)
    _word(cpu, _FRAME + 188, 3 if fault != "capacity" else 10)
    address = {
        "owner": abi.glyph.state_va + 4,
        "snapshot": _TEXT + 0x60,
        "rect": _TEXT + 0x1C,
        "glyph": abi.glyph.state_va + 60,
        "backing": abi.backing.state_va + 60,
        "back_owner": abi.backing.cache_va + 32,
        "back_rect": abi.backing.cache_va + 0x180,
        "cache": abi.glyph.cache_va + 32,
    }
    if fault in address:
        _word(cpu, address[fault], 0)
    assert _query(cpu, abi) == 0
    assert _word(cpu, _FRAME + 188) == (10 if fault == "capacity" else 3)


@pytest.mark.parametrize("absent", ["hidden", "expired", "modal", "disabled", "world_disabled"])
def test_absent_hud_withdraws_identity_without_dereferencing_retained_text(
    source: bytes, absent: str
) -> None:
    cpu, _, abi = _query_machine(source)
    addresses = {
        "hidden": _TEXT + 0x18,
        "expired": _ROOM + 0x50,
        "modal": _ROOM,
        "disabled": abi.enabled_va,
        "world_disabled": abi.world_enabled_va,
    }
    _word(cpu, addresses[absent], 0)
    assert _query(cpu, abi) == 1
    assert _word(cpu, _FRAME + 188) == 0
    for part in (abi.glyph, abi.backing):
        assert _word(cpu, part.state_va + 4) == 0
        assert _word(cpu, part.state_va + 56) == 0
        assert _word(cpu, part.state_va + 60) == 0
        assert _word(cpu, part.cache_va + 32) == 0


@pytest.mark.parametrize("backing", [False, True])
@pytest.mark.parametrize("status_first", [False, True])
def test_draw_runs_desktop_once_and_only_the_needed_capture_sources(
    source: bytes, *, backing: bool, status_first: bool
) -> None:
    cpu, compiler, abi = _query_machine(source)
    base = abi.enabled_va - compiler._enabled
    image, _ = _compiled(source)
    hooks = RoomStatusFeatureCompiler.native_hooks_abi(image, GOG_BUILD)
    if not status_first:
        _word(cpu, _ROOM + 0x50, 2)
        _word(cpu, _CHILDREN, _TEXT + 0x200, _TEXT)
        _word(cpu, _TEXT + 0x200, 0xDEADBEEF)
    cpu.mem_write(hooks.draw_va, bytes.fromhex("b8 94 26 00 00 ba 78 56 34 12 f9 c2 08 00"))
    if not backing:
        _word(cpu, _TEXT + 0x88, 0)
    captures = [base + helper for helper in compiler._helpers]
    for address in captures:
        cpu.mem_write(address, bytes.fromhex("b8 ef be ad de c2 08 00"))
    seen: list[int] = []

    def inspect(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address in [hooks.draw_va, *captures]:
            stack = machine.reg_read(UC_X86_REG_ESP)
            assert struct.unpack("<2I", machine.mem_read(stack + 4, 8)) == (1234, 4567)
            assert machine.reg_read(UC_X86_REG_ECX) == _TEXT
            seen.append(address)

    cpu.hook_add(UC_HOOK_CODE, inspect)
    _word(cpu, _STACK, _RETURN, 1234, 4567)
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.reg_write(UC_X86_REG_ECX, _TEXT)
    cpu.emu_start(base + compiler._draw, _RETURN, count=2000)
    assert seen == [hooks.draw_va, *captures[: 2 if backing else 1]]
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 12
    assert cpu.reg_read(UC_X86_REG_EAX) == 0x2694
    assert cpu.reg_read(UC_X86_REG_EDX) == 0x12345678
    assert cpu.reg_read(UC_X86_REG_EFLAGS) & 1


@pytest.mark.parametrize("owner", [_TEXT, _TEXT + 0x100])
def test_native_destruction_withdraws_only_its_owned_text(source: bytes, owner: int) -> None:
    cpu, compiler, abi = _query_machine(source)
    base = abi.enabled_va - compiler._enabled
    target = GOG_BUILD.address("room_text.destructor")
    cpu.mem_write(target, bytes.fromhex("8b c1 c2 04 00"))
    _word(cpu, _STACK, _RETURN, 1)
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.reg_write(UC_X86_REG_ECX, owner)
    cpu.emu_start(base + compiler._destructor, _RETURN, count=1000)
    assert cpu.reg_read(UC_X86_REG_EAX) == owner
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 8
    assert _word(cpu, abi.destroyed_va) == int(owner == _TEXT)
    assert _word(cpu, abi.glyph.state_va + 4) == (0 if owner == _TEXT else _TEXT)


@pytest.mark.parametrize(
    ("size", "rect", "expected"),
    [
        ((1024, 768), (5, 5, 392, 22), (5, 5, 392, 22)),
        ((1280, 800), (-5, -5, 392, 22), (0, 0, 409, 23)),
        ((1920, 1080), (5, 5, 392, 22), (7, 7, 552, 31)),
        ((3840, 2160), (5, 5, 392, 22), (14, 14, 1103, 62)),
        ((1280, 800), (1200, 700, 1300, 800), (1250, 729, 1280, 800)),
    ],
)
def test_hud_crop_uses_reference_height_affine_and_clips_signed_bounds(
    source: bytes,
    size: tuple[int, int],
    rect: tuple[int, int, int, int],
    expected: tuple[int, int, int, int],
) -> None:
    cpu, _, abi = _query_machine(source)
    cpu.mem_write(_TEXT + 0x1C, struct.pack("<4i", *rect))
    for part in (abi.glyph, abi.backing):
        _word(cpu, part.cache_va + 8, *size)
        cpu.mem_write(part.cache_va + 0x180, struct.pack("<4i", *rect))
    assert _query(cpu, abi) == 1
    assert struct.unpack("<4i", cpu.mem_read(_FRAME + 192 + 12, 16)) == expected


@pytest.mark.parametrize("fault", ["room", "children", "text", "count"])
def test_unknown_live_identity_never_dereferences_a_retained_owner(
    source: bytes, fault: str
) -> None:
    cpu, _, abi = _query_machine(source)
    if fault == "count":
        _word(cpu, _ROOM + 0x50, 0xFFFFFFFF)
    else:
        unreadable = {"room": _ROOM, "children": _CHILDREN, "text": _TEXT}[fault]
        # IsBadReadPtr's first argument is preserved for exact fault injection.
        cpu.mem_write(
            _READABLE,
            bytes.fromhex("31 c0 81 7c 24 04")
            + struct.pack("<I", unreadable)
            + bytes.fromhex("0f 94 c0 c2 08 00"),
        )
    assert _query(cpu, abi) == 0
    assert _word(cpu, _FRAME + 188) == 0
    assert _word(cpu, abi.glyph.state_va + 4) == 0


@pytest.mark.parametrize("fault", ["disabled", "world", "foreign", "busy"])
def test_unqualified_native_draw_does_not_capture_or_change_its_result(
    source: bytes, fault: str
) -> None:
    cpu, compiler, abi = _query_machine(source)
    image, _ = _compiled(source)
    hooks = RoomStatusFeatureCompiler.native_hooks_abi(image, GOG_BUILD)
    base = abi.enabled_va - compiler._enabled
    cpu.mem_write(hooks.draw_va, bytes.fromhex("b8 94 26 00 00 ba 78 56 34 12 f9 c2 08 00"))
    address = {
        "disabled": abi.enabled_va,
        "world": abi.world_enabled_va,
        "foreign": _CHILDREN,
        "busy": abi.glyph.cache_va + 20,
    }[fault]
    _word(cpu, address, 1 if fault == "busy" else 0)
    visited: list[int] = []
    targets = [hooks.draw_va, *(base + helper for helper in compiler._helpers)]

    def inspect(_machine: Uc, address: int, _size: int, _data: object) -> None:
        if address in targets:
            visited.append(address)

    cpu.hook_add(UC_HOOK_CODE, inspect)
    _word(cpu, _STACK, _RETURN, 1234, 4567)
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.reg_write(UC_X86_REG_ECX, _TEXT)
    cpu.emu_start(base + compiler._draw, _RETURN, count=2000)
    assert visited == [hooks.draw_va]
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 12
    assert cpu.reg_read(UC_X86_REG_EAX) == 0x2694
    assert cpu.reg_read(UC_X86_REG_EDX) == 0x12345678
