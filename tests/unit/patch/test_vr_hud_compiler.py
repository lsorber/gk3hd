"""Execute current-page HUD composition, native draw and lifetime ownership."""

from __future__ import annotations

import functools
import struct
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE, UC_PROT_EXEC, UC_PROT_READ
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
from gk3hd.patch.definitions.vr_hud import HUD_CAPTURED_OWNER, HUD_READY, REUSE_HIT
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
_OWNERSHIP = _HEAP + 0x15000
_OWNERSHIP_MODE = _OWNERSHIP + 32
_DEST_RESOURCE, _DEST_WRAPPER, _RESOURCE_MANAGER = _HEAP + 0xD000, _HEAP + 0xE000, _HEAP + 0x8000


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
    assert image.read_u32_va(abi.stereo_only_va) == 0
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


@pytest.mark.parametrize("fault", ["payload", "draw", "destructor", "fill"])
def test_changed_hud_bytes_or_bindings_fail_verification(source: bytes, fault: str) -> None:
    image, compiler = _compiled(source)
    hooks = RoomStatusFeatureCompiler.native_hooks_abi(image, GOG_BUILD)
    address = {
        "payload": compiler.abi(image).query_va,
        "draw": hooks.vtable_va + 0xA0,
        "destructor": hooks.vtable_va,
        "fill": GOG_BUILD.site("room_text.fill_call").va,
    }[fault]
    image.write_u32_va(address, 0)
    with pytest.raises(PatchError):
        compiler.postcheck(image)


def _word(cpu: Uc, address: int, *values: int) -> int:
    if values:
        cpu.mem_write(address, struct.pack(f"<{len(values)}I", *values))
    return struct.unpack("<I", cpu.mem_read(address, 4))[0]


@pytest.mark.parametrize(
    ("stereo_only", "has_export", "result"),
    [(False, True, 0), (True, False, 0), (True, True, 0), (True, True, 0x80004005)],
)
def test_glyph_batch_bridge_preserves_the_native_fallback(
    source: bytes, *, stereo_only: bool, has_export: bool, result: int
) -> None:
    image, compiler = _compiled(source)
    hud = compiler.abi(image)
    cpu = _machine(image)
    base = hud.enabled_va - compiler._enabled
    module, resolve, batch = (_HEAP + 0x8000, _HEAP + 0x8010, _HEAP + 0x8020)
    _word(cpu, hud.stereo_only_va, int(stereo_only))
    _word(cpu, hud.glyph.cache_va + 4, 0x1234)
    _word(cpu, hud.glyph.cache_va + 20, 1)
    _word(cpu, GOG_BUILD.address("win32.GetModuleHandleA"), module)
    _word(cpu, GOG_BUILD.address("win32.GetProcAddress"), resolve)
    cpu.mem_write(module, b"\xb8" + struct.pack("<I", 0x5678) + b"\xc2\x04\x00")
    cpu.mem_write(
        resolve, b"\xb8" + struct.pack("<I", batch if has_export else 0) + b"\xc2\x08\x00"
    )
    cpu.mem_write(batch, b"\xb8" + struct.pack("<I", result) + b"\xc2\x0c\x00")
    calls: list[int] = []

    def observe(machine: Uc, address: int, _size: int, _context: object) -> None:
        if address == batch:
            stack = machine.reg_read(UC_X86_REG_ESP)
            surface, operation, busy = struct.unpack("<3I", machine.mem_read(stack + 4, 12))
            assert (surface, busy) == (0x1234, hud.glyph.cache_va + 20)
            calls.append(operation)

    cpu.hook_add(UC_HOOK_CODE, observe)
    for operation in (0, 1):
        _word(cpu, _STACK, _RETURN)
        cpu.reg_write(UC_X86_REG_ESP, _STACK)
        cpu.reg_write(UC_X86_REG_EAX, operation)
        cpu.emu_start(base + compiler._batch, _RETURN, count=1000)
        assert cpu.reg_read(UC_X86_REG_EAX) == (not stereo_only or not has_export or not result)
        assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 4
    assert calls == ([0, 1] if stereo_only and has_export else [])


def _add_panel(image: PEFile, compiler: VRHudCompiler) -> VRPanelCompiler:
    slot = TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va
    panel = VRPanelCompiler(
        profile=GOG_BUILD,
        expected_presenter_va=image.read_u32_va(slot),
        world_enabled_va=compiler.world_enabled_va,
        caption=CaptionFeatureCompiler.cache_abi(image),
        tooltip=TooltipFeatureCompiler.cache_abi(image),
        hud=compiler.abi(image),
    )
    panel.apply(image)
    panel.postcheck(image)
    return panel


def _query_machine(source: bytes, *, panel: bool = False) -> tuple[Uc, VRHudCompiler, VRHudABI]:
    image, compiler = _compiled(source)
    if panel:
        _add_panel(image, compiler)
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
    # Execute every publication/withdrawal case with immutable instructions.
    cpu.mem_protect(abi.query_va & ~4095, 4096, UC_PROT_READ | UC_PROT_EXEC)
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
        assert words[:9] == (surface, 17, 1, 5, 5, 409, 23, 5, 5)
        assert words[9] == pytest.approx(opacity)


def test_reused_status_pixels_publish_with_the_current_fade(source: bytes) -> None:
    cpu, compiler, abi = _query_machine(source)
    base = abi.enabled_va - compiler._enabled
    capture = base + compiler._helpers[0] + 0x1400
    image, _ = _compiled(source)
    hooks = RoomStatusFeatureCompiler.native_hooks_abi(image, GOG_BUILD)
    cpu.mem_write(hooks.draw_va, b"\xcc")  # A proven hit must not redraw the glyphs.
    _word(cpu, abi.stereo_only_va, 1)
    _word(cpu, _TEXT + 0x88, 0)
    for opacity in (0.5, 0.125):
        _word(cpu, _FRAME + 188, 0)
        cpu.mem_write(_TEXT + 0x5C, struct.pack("<I4f", 1, opacity, 1 - opacity, 0, 0))
        _word(cpu, abi.glyph.cache_va + 20, 1)
        _word(cpu, base + compiler._reuse_state + REUSE_HIT, 1)
        _word(cpu, _STACK, _RETURN, 1234, 4567)
        cpu.reg_write(UC_X86_REG_ESP, _STACK)
        cpu.reg_write(UC_X86_REG_ECX, _TEXT)
        cpu.emu_start(capture, _RETURN, count=2000)
        _word(cpu, abi.glyph.cache_va + 20, 0)

        assert _query(cpu, abi) == 1
        assert _word(cpu, _FRAME + 188) == 1
        assert _word(cpu, _FRAME + 192) == 0x123
        assert struct.unpack("<f", cpu.mem_read(_FRAME + 192 + 36, 4))[0] == opacity


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
        17,
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


def _capture_first_machine(
    source: bytes, *, panel: bool = False
) -> tuple[Uc, VRHudCompiler, VRHudABI, list[str]]:
    cpu, compiler, abi = _query_machine(source, panel=panel)
    image, _ = _compiled(source)
    hooks = RoomStatusFeatureCompiler.native_hooks_abi(image, GOG_BUILD)
    scene = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=1).abi(image)
    base = abi.enabled_va - compiler._enabled
    cpu.mem_write(_OWNERSHIP, b"\xa1" + struct.pack("<I", _OWNERSHIP_MODE) + b"\xc3")
    _word(cpu, _OWNERSHIP_MODE, 1)
    _word(cpu, scene.ownership_query_slot_va, _OWNERSHIP)
    _word(cpu, scene.frame_pending_va, 1)
    _word(cpu, scene.result_va, 0)
    _word(cpu, abi.stereo_only_va, 1)
    _word(cpu, _TEXT + 0x88, 0)
    _word(cpu, abi.glyph.cache_va + 24, _DEST_RESOURCE, _DEST_WRAPPER)
    _word(cpu, GOG_BUILD.address("resource.manager"), _RESOURCE_MANAGER)
    _word(cpu, _RESOURCE_MANAGER + 0x120, 1)
    _word(cpu, _DEST_RESOURCE + 0x30, _DEST_WRAPPER)
    _word(cpu, _DEST_WRAPPER + 0x2C, 0x333)
    _word(cpu, _DEST_WRAPPER + 0x38, 1280, 800)
    _word(cpu, GOG_BUILD.address("transition.back_surface_ptr"), 0x333)
    cpu.mem_write(
        GOG_BUILD.address("bitmap.resolve_resource"),
        b"\xb8" + struct.pack("<I", _DEST_RESOURCE) + bytes.fromhex("c2 04 00"),
    )
    cpu.mem_write(hooks.draw_va, bytes.fromhex("b8 94 26 00 00 ba 78 56 34 12 f9 c2 08 00"))
    for index, part in enumerate((abi.glyph, abi.backing)):
        cpu.mem_write(
            base + compiler._helpers[index],
            b"\xc7\x05"
            + struct.pack("<II", part.state_va + HUD_READY, 1)
            + b"\xc7\x05"
            + struct.pack("<II", part.state_va + HUD_CAPTURED_OWNER, _TEXT)
            + bytes.fromhex("b8 ef be ad de ba 67 45 23 01 f9 c2 08 00"),
        )
    seen: list[str] = []
    targets = {
        hooks.draw_va: "native",
        base + compiler._helpers[0]: "glyph",
        base + compiler._helpers[1]: "backing",
    }

    def inspect(_machine: Uc, address: int, _size: int, _data: object) -> None:
        if address in targets:
            seen.append(targets[address])

    cpu.hook_add(UC_HOOK_CODE, inspect)
    cpu.mem_protect(abi.finish_va & ~4095, 4096, UC_PROT_READ | UC_PROT_EXEC)
    return cpu, compiler, abi, seen


def _draw(cpu: Uc, compiler: VRHudCompiler, abi: VRHudABI) -> int:
    _word(cpu, _STACK, _RETURN, 1234, 4567)
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.reg_write(UC_X86_REG_ECX, _TEXT)
    cpu.reg_write(UC_X86_REG_EBX, 0x87654321)
    cpu.reg_write(UC_X86_REG_EFLAGS, 0x202)
    cpu.emu_start(abi.enabled_va - compiler._enabled + compiler._draw, _RETURN, count=6000)
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 12
    assert cpu.reg_read(UC_X86_REG_EBX) == 0x87654321
    assert cpu.reg_read(UC_X86_REG_ECX) == _TEXT
    assert cpu.reg_read(UC_X86_REG_EFLAGS) & 1
    return cpu.reg_read(UC_X86_REG_EAX)


def _finish(cpu: Uc, abi: VRHudABI, *, native: bool) -> None:
    _word(cpu, _STACK, _RETURN, int(native))
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.reg_write(UC_X86_REG_EAX, 0xABCDEF)
    cpu.reg_write(UC_X86_REG_EDX, 0x7654321)
    cpu.reg_write(UC_X86_REG_EFLAGS, 0x202)
    cpu.emu_start(abi.finish_va, _RETURN, count=6000)
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 8
    assert cpu.reg_read(UC_X86_REG_EAX) == 0xABCDEF
    assert cpu.reg_read(UC_X86_REG_EDX) == 0x7654321
    assert cpu.reg_read(UC_X86_REG_EFLAGS) == 0x202


@pytest.mark.parametrize("native", [False, True])
def test_stereo_only_page_decision_retires_the_current_draw_once(
    source: bytes, *, native: bool
) -> None:
    cpu, compiler, abi, seen = _capture_first_machine(source)
    assert _draw(cpu, compiler, abi) == 0xDEADBEEF
    assert cpu.reg_read(UC_X86_REG_EDX) == 0x1234567
    assert seen == ["glyph"]
    _finish(cpu, abi, native=native)
    assert seen == (["glyph", "native"] if native else ["glyph"])
    _finish(cpu, abi, native=True)
    assert seen == (["glyph", "native"] if native else ["glyph"])


@pytest.mark.parametrize(
    "fault",
    [
        "disabled_contract",
        "bad_contract",
        "pending",
        "failed_world",
        "no_classifier",
        "modal",
        "menu",
        "failed_capture",
        "invalid_cache",
    ],
)
def test_capture_first_failure_keeps_ordinary_drawing(source: bytes, fault: str) -> None:
    cpu, compiler, abi, seen = _capture_first_machine(source)
    image, _ = _compiled(source)
    scene = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=1).abi(image)
    if fault in {"disabled_contract", "bad_contract"}:
        _word(cpu, abi.stereo_only_va, 0 if fault == "disabled_contract" else 2)
    elif fault == "pending":
        _word(cpu, scene.frame_pending_va, 0)
    elif fault == "failed_world":
        _word(cpu, scene.result_va, 0x80004005)
    elif fault == "no_classifier":
        _word(cpu, scene.ownership_query_slot_va, 0)
    elif fault in {"modal", "menu"}:
        _word(cpu, _OWNERSHIP_MODE, 2 if fault == "modal" else 3)
    elif fault == "failed_capture":
        cpu.mem_write(
            abi.enabled_va - compiler._enabled + compiler._helpers[0],
            bytes.fromhex("31 c0 c2 08 00"),
        )
    else:
        cpu.mem_write(abi.glyph.validate_va, bytes.fromhex("31 c0 c3"))
    assert _draw(cpu, compiler, abi) == 0x2694
    assert seen.count("native") == 1
    _finish(cpu, abi, native=True)
    assert seen.count("native") == 1


@pytest.mark.parametrize("fault", ["new_page", "replaced_owner", "hidden", "withdrawn"])
def test_deferred_draw_cannot_replay_on_a_different_page_or_owner(
    source: bytes, fault: str
) -> None:
    cpu, compiler, abi, seen = _capture_first_machine(source)
    assert _draw(cpu, compiler, abi) == 0xDEADBEEF
    if fault == "new_page":
        image, _ = _compiled(source)
        _word(cpu, TransitionFrameCompiler.runtime_abi(image).successful_flip_count_va, 5)
    elif fault == "replaced_owner":
        _word(cpu, _CHILDREN, 0)
    elif fault == "hidden":
        _word(cpu, _TEXT + 0x18, 0)
    else:
        _word(cpu, _ROOM + 0x50, 0)
        _query(cpu, abi)
    _finish(cpu, abi, native=True)
    assert seen == ["glyph"]


def test_native_page_repair_uses_owned_complete_damage_not_a_returned_callers_pointer(
    source: bytes,
) -> None:
    cpu, compiler, abi, seen = _capture_first_machine(source)
    image, _ = _compiled(source)
    target = RoomStatusFeatureCompiler.native_hooks_abi(image, GOG_BUILD).draw_va
    repairs = []

    def inspect(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address != target:
            return
        stack = machine.reg_read(UC_X86_REG_ESP)
        bitmap, damage = struct.unpack("<2I", machine.mem_read(stack + 4, 8))
        assert bitmap == 1234
        assert damage != 4567
        _, begin, end, _ = struct.unpack("<4I", machine.mem_read(damage, 16))
        assert end - begin == 16
        assert struct.unpack("<4I", machine.mem_read(begin, 16)) == (0, 0, 1280, 800)
        assert machine.reg_read(UC_X86_REG_ECX) == _TEXT
        repairs.append(True)

    cpu.hook_add(UC_HOOK_CODE, inspect)
    assert _draw(cpu, compiler, abi) == 0xDEADBEEF
    _finish(cpu, abi, native=True)
    assert repairs == [True]
    assert seen == ["glyph", "native"]


@pytest.mark.parametrize(
    "fault",
    ["resource", "wrapper", "surface", "page_surface", "dimensions", "manager", "unreadable"],
)
def test_deferred_native_repair_does_not_follow_replaced_or_unreadable_bitmap_ownership(
    source: bytes, fault: str
) -> None:
    cpu, compiler, abi, seen = _capture_first_machine(source)
    assert _draw(cpu, compiler, abi) == 0xDEADBEEF
    if fault == "resource":
        cpu.mem_write(GOG_BUILD.address("bitmap.resolve_resource"), bytes.fromhex("31 c0 c2 04 00"))
    elif fault == "wrapper":
        _word(cpu, _DEST_RESOURCE + 0x30, 0)
    elif fault == "surface":
        _word(cpu, _DEST_WRAPPER + 0x2C, 0)
    elif fault == "page_surface":
        _word(cpu, GOG_BUILD.address("transition.back_surface_ptr"), 0)
    elif fault == "dimensions":
        _word(cpu, _DEST_WRAPPER + 0x38, 1024)
    elif fault == "manager":
        _word(cpu, GOG_BUILD.address("resource.manager"), 0)
    else:
        cpu.mem_write(
            _READABLE,
            bytes.fromhex("31 c0 81 7c 24 04")
            + struct.pack("<I", _DEST_RESOURCE)
            + bytes.fromhex("0f 94 c0 c2 08 00"),
        )
        cpu.ctl_remove_cache(_READABLE, _READABLE + 32)
    _finish(cpu, abi, native=True)
    assert seen == ["glyph"]


def test_second_draw_cannot_overwrite_an_unfinished_page_transaction(source: bytes) -> None:
    cpu, compiler, abi, seen = _capture_first_machine(source)
    assert _draw(cpu, compiler, abi) == 0xDEADBEEF
    assert _draw(cpu, compiler, abi) == 0xDEADBEEF
    assert seen == ["glyph", "native", "glyph"]
    _finish(cpu, abi, native=False)
    _finish(cpu, abi, native=True)
    assert seen == ["glyph", "native", "glyph"]


def test_capture_first_restores_this_after_a_volatile_windows_pointer_probe(source: bytes) -> None:
    cpu, compiler, abi, seen = _capture_first_machine(source)
    cpu.mem_write(_READABLE, bytes.fromhex("31 c0 b9 ef be ad de ba 78 56 34 12 c2 08 00"))
    assert _draw(cpu, compiler, abi) == 0xDEADBEEF
    _finish(cpu, abi, native=True)
    assert seen == ["glyph", "native"]


@pytest.mark.parametrize("backing_ready", [False, True])
def test_capture_first_requires_the_current_backing_as_well_as_glyphs(
    source: bytes, *, backing_ready: bool
) -> None:
    cpu, compiler, abi, seen = _capture_first_machine(source)
    cpu.mem_write(_TEXT + 0x88, struct.pack("<f", 0.375))
    if not backing_ready:
        cpu.mem_write(
            abi.enabled_va - compiler._enabled + compiler._helpers[1],
            bytes.fromhex("31 c0 c2 08 00"),
        )
    assert _draw(cpu, compiler, abi) == (0xDEADBEEF if backing_ready else 0x2694)
    assert seen == (["glyph", "backing"] if backing_ready else ["glyph", "backing", "native"])
    _finish(cpu, abi, native=False)
    assert seen.count("native") == (not backing_ready)


@pytest.mark.parametrize(
    "outcome",
    ["world", "late_source_failure", "late_modal", "renderer_failure", "no_device", "no_renderer"],
)
def test_final_page_repairs_before_native_consumption_and_on_failed_completion(
    source: bytes, outcome: str
) -> None:
    cpu, compiler, hud, seen = _capture_first_machine(source, panel=True)
    image, _ = _compiled(source)
    panel = _add_panel(image, compiler)
    abi = panel.abi(image)
    base = abi.enabled_va - panel._enabled
    _word(cpu, abi.enabled_va, 1)
    _word(cpu, abi.ownership_query_slot_va, _OWNERSHIP)
    _word(cpu, base + panel._resolved, 1)
    bridge = _HEAP + 0x16000
    _word(cpu, abi.renderer_bridge_slot_va, 0 if outcome == "no_renderer" else bridge)
    cpu.mem_write(bridge, bytes.fromhex("c2 0c 00"))
    wrapper = _HEAP + 0x5000
    device = _HEAP + 0x6000
    _word(
        cpu,
        GOG_BUILD.address("high_resolution_3d.render_wrapper_ptr"),
        0 if outcome == "no_device" else wrapper,
    )
    _word(cpu, wrapper + 0x4E8, device)
    for name, address, value in (
        ("high_resolution_3d.display_width_ptr", _HEAP + 0xC000, 1280),
        ("high_resolution_3d.display_height_ptr", _HEAP + 0xC004, 800),
    ):
        _word(cpu, GOG_BUILD.address(name), address)
        _word(cpu, address, value)
    cpu.mem_write(panel.expected_presenter_va, b"\xc3")
    assert _draw(cpu, compiler, hud) == 0xDEADBEEF
    assert seen == ["glyph"]
    # Fake capture helpers still have to produce real query snapshot fields.
    cpu.mem_write(hud.glyph.state_va + 16, struct.pack("<2f", 1, 0))
    cpu.mem_write(hud.glyph.state_va + 24, bytes(cpu.mem_read(_TEXT + 0x5C, 20)))
    if outcome == "late_source_failure":
        _word(cpu, hud.glyph.state_va + HUD_READY, 0)
    elif outcome == "late_modal":
        _word(cpu, _OWNERSHIP_MODE, 2)
    events = []
    target = RoomStatusFeatureCompiler.native_hooks_abi(image, GOG_BUILD).draw_va

    def inspect(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address == target:
            events.append("repair")
        elif address == bridge:
            operation = _word(machine, machine.reg_read(UC_X86_REG_ESP) + 8)
            events.append(f"bridge-{operation}")
            machine.reg_write(
                UC_X86_REG_EAX,
                0x80004005 if outcome == "renderer_failure" and operation != 1 else 0,
            )

    cpu.hook_add(UC_HOOK_CODE, inspect)
    _word(cpu, _STACK, _RETURN)
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.mem_protect((base + panel._code) & ~4095, 4096, UC_PROT_READ | UC_PROT_EXEC)
    cpu.emu_start(base + panel._code, _RETURN, count=15000)
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 4
    expected = {
        "world": ["bridge-4"],
        "late_source_failure": ["repair", "bridge-0"],
        "late_modal": ["repair", "bridge-0"],
        "renderer_failure": ["bridge-4", "bridge-1", "repair"],
        "no_device": ["repair"],
        "no_renderer": ["repair"],
    }
    assert events == expected[outcome]
    assert seen.count("native") == (outcome != "world")
    _finish(cpu, hud, native=True)
    assert seen.count("native") == (outcome != "world")


def _configure_glyph_reuse(cpu: Uc, hud: VRHudABI, cache: int) -> tuple[int, int, int, int]:
    module, resolve, reuse, font, text, table, bitmap, surface = range(
        _HEAP + 0x18000, _HEAP + 0x20000, 0x1000
    )
    # Reuse the normal test machine's known live object and resource manager.
    _word(cpu, hud.stereo_only_va, 1)
    _word(cpu, cache + 4, 0x1234)
    _word(cpu, cache + 32, _TEXT)
    _word(cpu, cache + 44, 2, 1)
    _word(cpu, cache + 0x74, 8)
    _word(cpu, _TEXT, GOG_BUILD.address("room_text.vtable"))
    _word(cpu, _TEXT + 0x18, 1)
    _word(cpu, _TEXT + 0x30, text)
    _word(cpu, _TEXT + 0x40, font)
    cpu.mem_write(_TEXT + 0x5C, struct.pack("<Iff", 1, 0.25, 0.75))
    cpu.mem_write(text, b"Room status\0")
    _word(cpu, font + 4, 0xFF000001)
    _word(cpu, _RESOURCE_MANAGER + 0x120, table, 2)
    _word(cpu, table + 4, bitmap)
    _word(cpu, bitmap + 0x30, surface)
    _word(cpu, surface + 0x2C, 0x4567)
    _word(cpu, surface + 0x38, 5864, 72)
    _word(cpu, GOG_BUILD.address("resource.manager"), _RESOURCE_MANAGER)
    _word(cpu, GOG_BUILD.address("win32.IsBadReadPtr"), _READABLE)
    _word(cpu, GOG_BUILD.address("win32.GetModuleHandleA"), module)
    _word(cpu, GOG_BUILD.address("win32.GetProcAddress"), resolve)
    cpu.mem_write(_READABLE, b"\x31\xc0\xc2\x08\x00")
    cpu.mem_write(module, b"\xb8" + struct.pack("<I", 0x5678) + b"\xc2\x04\x00")
    cpu.mem_write(resolve, b"\xc2\x08\x00")
    cpu.mem_write(reuse, b"\xc2\x1c\x00")
    return resolve, reuse, font, text


def test_glyph_reuse_bridge_qualifies_exact_layout_and_legacy_fallback(source: bytes) -> None:
    image, compiler = _compiled(source)
    hud = compiler.abi(image)
    cpu = _machine(image)
    cpu.mem_map(_HEAP + 0x10000, 0x10000)
    base = hud.enabled_va - compiler._enabled
    cache = hud.glyph.cache_va
    resolve, reuse, font, text = _configure_glyph_reuse(cpu, hud, cache)
    layouts: list[int] = []
    has_export = True

    def observe(machine: Uc, address: int, _size: int, _context: object) -> None:
        if address == resolve:
            machine.reg_write(UC_X86_REG_EAX, reuse if has_export else 0)
        if address != reuse:
            return
        stack = machine.reg_read(UC_X86_REG_ESP)
        *arguments, same = struct.unpack("<7I", machine.mem_read(stack + 4, 28))
        assert arguments == [0x1234, 0x4567, cache + 20, 8, 2, 1]
        assert same in (0, 1)
        layouts.append(same)
        machine.reg_write(UC_X86_REG_EAX, 1 - same)

    cpu.hook_add(UC_HOOK_CODE, observe)

    def check(*, hit: bool) -> None:
        _word(cpu, _STACK, _RETURN)
        cpu.reg_write(UC_X86_REG_ESP, _STACK)
        cpu.reg_write(UC_X86_REG_EFLAGS, 0x203)
        cpu.emu_start(base + compiler._helpers[0] + 0x1C00, _RETURN, count=9000)
        assert cpu.reg_read(UC_X86_REG_EAX) == int(hit)
        assert cpu.reg_read(UC_X86_REG_EFLAGS) == 0x203
        assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 4

    check(hit=False)
    cpu.mem_write(_TEXT + 0x60, struct.pack("<ff", 0.5, 0.5))
    check(hit=True)
    cpu.mem_write(text + 5, b"S")
    check(hit=False)
    _word(cpu, font + 0x54, 1)
    check(hit=False)
    check(hit=True)
    _word(cpu, _TEXT + 0x5C, 2)
    check(hit=False)
    _word(cpu, _TEXT + 0x5C, 1)
    _word(cpu, font + 0x4C, 2)
    check(hit=False)
    _word(cpu, font + 0x4C, 1)
    has_export = False
    check(hit=False)
    _word(cpu, hud.stereo_only_va, 0)
    check(hit=False)
    assert layouts == [0, 1, 0, 0, 1]
