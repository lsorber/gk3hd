"""Execute real footprint capture/validation and atomic dropdown composition."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_EFLAGS, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.runtime2d.system.menus import MenuFeatureCompiler
from tests.unit.patch import test_vr_menu_compiler as menus
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK

if TYPE_CHECKING:
    from unicorn import Uc

    from gk3hd.patch.definitions.vr_menu_compiler import VRMenuABI

source = menus.source
_TOOLBAR = _HEAP + 0x16000
_POPUP = _HEAP + 0x17000
_CHILDREN = _HEAP + 0x12000

# Original native geometry and physical output from independent live captures.
_CASES = {
    (1024, 768): (
        (386, 347, 638, 768),
        634,
        (493, 440, 630, 768),
        (386, 347, 638, 634),
        (493, 440, 630, 768),
    ),
    (1280, 800): (
        (514, 363, 766, 784),
        650,
        (621, 456, 758, 784),
        (509, 362, 771, 660),
        (621, 458, 762, 800),
    ),
    (3840, 2160): (
        (1794, 1043, 2046, 1464),
        1330,
        (1901, 1136, 2038, 1464),
        (1566, 976, 2274, 1783),
        (1867, 1237, 2251, 2160),
    ),
}


def _coverage_machine(
    source: bytes, size: tuple[int, int] = (1280, 800), *, popup: bool = True
) -> tuple[Uc, VRMenuABI, int]:
    image, _ = menus._compiled(source)
    cpu, abi, frame = menus._query_machine(source)
    coverage = abi.toolbar.coverage
    assert coverage is not None
    hooks = MenuFeatureCompiler.native_hooks_abi(image, GOG_BUILD)
    cpu.mem_write(
        coverage.validate_va, image.read_bytes(image.va_to_offset(coverage.validate_va), 0x600)
    )
    root, bottom, rectangle, body, physical_popup = _CASES[size]
    if not popup:
        root = (*root[:3], bottom)
    cpu.mem_write(_TOOLBAR + 0x1C, struct.pack("<4i", *root))
    union = (*body[:3], physical_popup[3] if popup else body[3])
    cpu.mem_write(abi.toolbar.rect_va, struct.pack("<4i", *union))
    cpu.mem_write(abi.toolbar.surface_va + 4, struct.pack("<2I", *size))
    menus._write_words(
        cpu,
        (
            (hooks.dropdown_pending_va, _POPUP if popup else 0),
            (hooks.dropdown_saved_bottom_va, bottom),
            (hooks.dropdown_bottom_valid_va, int(popup)),
            (_POPUP, GOG_BUILD.address("resolution_dropdown.vtable")),
            (_POPUP + 0x18, int(popup)),
            (_HEAP + 0x11000 + 0x50, 3),
        ),
    )
    cpu.mem_write(_POPUP + 0x1C, struct.pack("<4i", *rectangle))
    cpu.mem_write(_CHILDREN, struct.pack("<3I", _HEAP + 0x15000, _POPUP, _TOOLBAR))
    return cpu, abi, frame


def _invoke(cpu: Uc, entry: int) -> int:
    cpu.mem_write(_STACK, struct.pack("<I", _RETURN))
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.reg_write(UC_X86_REG_EBX, 77)
    cpu.reg_write(UC_X86_REG_EFLAGS, 0x202)
    cpu.emu_start(entry, _RETURN, count=5000)
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 4
    assert cpu.reg_read(UC_X86_REG_EBX) == 77
    assert cpu.reg_read(UC_X86_REG_EFLAGS) == 0x202
    return cpu.reg_read(UC_X86_REG_EAX)


def _rect(cpu: Uc, address: int) -> tuple[int, ...]:
    return struct.unpack("<4i", cpu.mem_read(address, 16))


@pytest.mark.parametrize("size", _CASES)
@pytest.mark.parametrize("popup", [False, True])
def test_capture_matches_original_toolbar_and_list_geometry(
    source: bytes, size: tuple[int, int], *, popup: bool
) -> None:
    cpu, abi, _ = _coverage_machine(source, size, popup=popup)
    coverage = abi.toolbar.coverage
    assert coverage is not None
    assert _invoke(cpu, coverage.capture_va) == 1
    assert _invoke(cpu, coverage.validate_va) == 1
    assert menus._read(cpu, coverage.ready_va) == 1
    assert _rect(cpu, coverage.body_rect_va) == _CASES[size][3]
    assert menus._read(cpu, coverage.popup_root_va) == (_POPUP if popup else 0)
    if popup:
        assert _rect(cpu, coverage.popup_rect_va) == _CASES[size][4]


@pytest.mark.parametrize("size", _CASES)
@pytest.mark.parametrize("toolbar_first", [False, True])
def test_dropdown_is_appended_after_body_without_claiming_bounding_box_gaps(
    source: bytes, size: tuple[int, int], *, toolbar_first: bool
) -> None:
    cpu, abi, frame = _coverage_machine(source, size)
    coverage = abi.toolbar.coverage
    assert coverage is not None
    if toolbar_first:
        cpu.mem_write(_CHILDREN, struct.pack("<3I", _TOOLBAR, _POPUP, _HEAP + 0x15000))
    assert _invoke(cpu, coverage.capture_va) == 1
    assert menus._run(cpu, abi, frame) == 1
    assert menus._read(cpu, frame + 188) == 3
    parts = [struct.unpack("<3I6i", cpu.mem_read(frame + 192 + i * 40, 36)) for i in range(3)]
    assert all(
        struct.unpack("<f", cpu.mem_read(frame + 192 + i * 40 + 36, 4))[0] == 1 for i in range(3)
    )
    body, popup = _CASES[size][3:]
    expected = [
        (0x123, 2, 0, 100, 200, 300, 250, 100, 200),
        (0x124, 2, 0, *body, *body[:2]),
        (0x124, 2, 0, *popup, *popup[:2]),
    ]
    assert parts == (expected[1:] + expected[:1] if toolbar_first else expected)
    # The blank area below the body and to the left of the list remains world.
    gap = (body[0] + 1, body[3] + 1)
    assert not any(part[3] <= gap[0] < part[5] and part[4] <= gap[1] < part[6] for part in parts)


def _make_unreadable(cpu: Uc, bad: int) -> None:
    readable = _HEAP + 0x14000
    cpu.mem_write(readable, bytes.fromhex("c2 08 00"))
    # Capture may already have translated the original readable stub. Make
    # the emulator execute its replacement rather than a cached XOR EAX.
    cpu.ctl_remove_cache(readable, readable + 5)

    def observe(machine: Uc, address: int, _size: int, _context: object) -> None:
        if address == readable:
            pointer = menus._read(machine, machine.reg_read(UC_X86_REG_ESP) + 4)
            machine.reg_write(UC_X86_REG_EAX, int(pointer == bad))

    cpu.hook_add(UC_HOOK_CODE, observe)


def _fault(cpu: Uc, source: bytes, fault: str) -> None:
    image, _ = menus._compiled(source)
    hooks = MenuFeatureCompiler.native_hooks_abi(image, GOG_BUILD)
    writes = {
        "hidden": (_POPUP + 0x18, 0),
        "foreign": (_POPUP, hooks.toolbar.vtable_va),
        "withdrawn": (hooks.dropdown_pending_va, 0),
        "changed_owner": (hooks.dropdown_pending_va, _POPUP + 0x200),
        "no_saved_bottom": (hooks.dropdown_bottom_valid_va, 0),
        "saved_bottom_changed": (hooks.dropdown_saved_bottom_va, 649),
        "body_changed": (_TOOLBAR + 0x1C, 515),
        "popup_changed": (_POPUP + 0x1C, 622),
        "empty_popup": (_POPUP + 0x24, 621),
        "oversized_popup": (_POPUP + 0x24, 32769),
        "negative_popup": (_POPUP + 0x1C, -32769),
        "bottom_below_body": (hooks.dropdown_saved_bottom_va, 362),
        "bottom_above_union": (hooks.dropdown_saved_bottom_va, 785),
        "hidden_body": (_TOOLBAR + 0x18, 0),
        "foreign_body": (_TOOLBAR, hooks.action.vtable_va),
    }
    if fault in writes:
        address, value = writes[fault]
        menus._write_words(cpu, ((address, value & 0xFFFFFFFF),))
    else:
        _make_unreadable(cpu, _TOOLBAR if fault == "unreadable_body" else _POPUP)


@pytest.mark.parametrize(
    "fault",
    [
        "hidden",
        "foreign",
        "no_saved_bottom",
        "empty_popup",
        "oversized_popup",
        "negative_popup",
        "bottom_below_body",
        "bottom_above_union",
        "hidden_body",
        "foreign_body",
        "unreadable_body",
        "unreadable_popup",
    ],
)
def test_invalid_capture_cannot_publish_coverage(source: bytes, fault: str) -> None:
    cpu, abi, frame = _coverage_machine(source)
    coverage = abi.toolbar.coverage
    assert coverage is not None
    _fault(cpu, source, fault)
    assert _invoke(cpu, coverage.capture_va) == 0
    assert menus._read(cpu, coverage.ready_va) == 0
    assert menus._run(cpu, abi, frame) == 0
    assert menus._read(cpu, frame + 188) == 0


@pytest.mark.parametrize(
    "fault",
    [
        "hidden",
        "foreign",
        "withdrawn",
        "changed_owner",
        "no_saved_bottom",
        "saved_bottom_changed",
        "body_changed",
        "popup_changed",
        "unreadable_body",
        "unreadable_popup",
    ],
)
def test_changed_footprint_withdraws_coverage_and_rolls_back_partial_batch(
    source: bytes, fault: str
) -> None:
    cpu, abi, frame = _coverage_machine(source)
    coverage = abi.toolbar.coverage
    assert coverage is not None
    assert _invoke(cpu, coverage.capture_va) == 1
    sentinel = bytes(range(36))
    cpu.mem_write(frame + 192, sentinel)
    menus._write_words(cpu, ((frame + 188, 1),))
    _fault(cpu, source, fault)
    # A malformed earlier room child can reject the batch before reaching
    # the toolbar. Exercise footprint withdrawal independently of ordering.
    assert _invoke(cpu, coverage.validate_va) == 0
    assert menus._run(cpu, abi, frame) == 0
    assert menus._read(cpu, coverage.ready_va) == 0
    assert menus._read(cpu, frame + 188) == 1
    assert cpu.mem_read(frame + 192, 36) == sentinel


@pytest.mark.parametrize("fault", ["duplicate_popup", "missing_popup", "missing_body", "capacity"])
def test_incomplete_native_graph_never_submits_partial_popup(source: bytes, fault: str) -> None:
    cpu, abi, frame = _coverage_machine(source)
    coverage = abi.toolbar.coverage
    assert coverage is not None
    assert _invoke(cpu, coverage.capture_va) == 1
    changes = {
        "duplicate_popup": (_CHILDREN + 4, _POPUP),
        "missing_popup": (_POPUP + 0x18, 0),
        "missing_body": (_TOOLBAR + 0x18, 0),
        "capacity": (frame + 188, 12),
    }
    if fault == "duplicate_popup":
        menus._write_words(cpu, ((_CHILDREN, _POPUP),))
    menus._write_words(cpu, (changes[fault],))
    before = menus._read(cpu, frame + 188)
    assert menus._run(cpu, abi, frame) == 0
    assert menus._read(cpu, frame + 188) == before


@pytest.mark.parametrize("fault", ["unreadable_body", "unreadable_popup", "foreign", "withdrawn"])
def test_query_rejects_stale_sources_without_a_separate_validation_call(
    source: bytes, fault: str
) -> None:
    cpu, abi, frame = _coverage_machine(source)
    coverage = abi.toolbar.coverage
    assert coverage is not None
    assert _invoke(cpu, coverage.capture_va) == 1
    _fault(cpu, source, fault)
    assert menus._run(cpu, abi, frame) == 0
    assert menus._read(cpu, frame + 188) == 0


def test_hidden_popup_requires_fresh_capture_before_republication(source: bytes) -> None:
    cpu, abi, frame = _coverage_machine(source)
    coverage = abi.toolbar.coverage
    assert coverage is not None
    assert _invoke(cpu, coverage.capture_va) == 1
    _fault(cpu, source, "hidden")
    assert _invoke(cpu, coverage.validate_va) == 0
    menus._write_words(cpu, ((_POPUP + 0x18, 1),))
    assert menus._run(cpu, abi, frame) == 0
    assert _invoke(cpu, coverage.capture_va) == 1
    assert menus._run(cpu, abi, frame) == 1
    assert menus._read(cpu, frame + 188) == 3
