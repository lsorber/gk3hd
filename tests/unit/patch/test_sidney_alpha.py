"""Contracts for the software effect path that bypasses SIDNEY's final blit."""

import struct

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_ESP

from gk3hd.patch.binary.x86 import BranchOpcode, decode_rel32_branch
from gk3hd.patch.definitions.runtime2d.layout import (
    SIDNEY_ALPHA_CONSTRUCTOR_OFFSET,
    SIDNEY_PORTRAIT_SOURCE_OFFSET,
)
from gk3hd.patch.definitions.runtime2d.sidney_alpha import (
    build_alpha_wrapper,
    build_caret_wrapper,
    build_solid_fill_wrapper,
)


def test_sidney_alpha_preserves_the_native_constructor_and_owned_partition() -> None:
    """Admission uses draw scope, physical destination and cursor identity."""
    wrapper, target, depth, hud, width, classifier = (
        0x800000,
        0x810000,
        0x820000,
        0x820004,
        0x820008,
        0x830000,
    )
    payload = build_alpha_wrapper(
        wrapper_va=wrapper,
        target_va=target,
        active_depth_va=depth,
        hud_font_active_va=hud,
        physical_width_va=width,
        cursor_classifier_va=classifier,
    )
    assert len(payload) <= SIDNEY_PORTRAIT_SOURCE_OFFSET - SIDNEY_ALPHA_CONSTRUCTOR_OFFSET
    for address in (depth, hud, width, width + 4):
        assert struct.pack("<I", address) in payload
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.JUMP,
            site_va=wrapper + len(payload) - 5,
            instruction=payload[-5:],
        )
        == target
    )
    # The adapted path consumes five original arguments after preserving the
    # native constructor's EAX result; no alternate shader or blend is installed.
    assert b"\x83\xc4\x10\xc2\x14\x00" in payload
    assert b"\x8b\x54\x24\x38\x8b\x74\x24\x3c" in payload
    assert b"\xc7\x05" + struct.pack("<II", hud, 2) in payload
    assert b"\xc7\x05" + struct.pack("<II", hud, 1) not in payload


def test_sidney_caret_retains_its_four_argument_fill_abi() -> None:
    """Caret colors and native GDI rendering remain unchanged by the affine."""
    payload = build_caret_wrapper(
        wrapper_va=0x800000,
        target_va=0x810000,
        resolve_bitmap_va=0x820000,
        active_depth_va=0x830000,
        physical_width_va=0x840000,
    )
    assert len(payload) <= 0x100
    assert b"\x83\xc4\x14\xc2\x10\x00" in payload
    assert b"\xff\x74\x24\x24" * 3 in payload


@pytest.mark.parametrize(("width", "height"), [(1024, 768), (1280, 800), (3840, 2160)])
@pytest.mark.parametrize("scope", ["framebuffer", "inactive", "offscreen", "null_rect"])
def test_sidney_caret_matches_text_affine_and_preserves_native_fill(
    width: int, height: int, scope: str
) -> None:
    wrapper, target, resolve, stop = 0x100000, 0x101000, 0x102000, 0x103000
    state, record, bitmap, rect, stack = 0x200000, 0x201000, 0x202000, 0x203000, 0x308000
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    for address in (wrapper, state, 0x300000):
        machine.mem_map(address, 0x10000)
    machine.mem_write(
        wrapper,
        build_caret_wrapper(
            wrapper_va=wrapper,
            target_va=target,
            resolve_bitmap_va=resolve,
            active_depth_va=state,
            physical_width_va=state + 4,
        ),
    )
    machine.mem_write(target, bytes.fromhex("c2 10 00"))
    machine.mem_write(resolve, bytes.fromhex("c2 04 00"))
    machine.mem_write(state, struct.pack("<3I", int(scope != "inactive"), width, height))
    machine.mem_write(record + 0x30, struct.pack("<I", bitmap))
    machine.mem_write(bitmap + 0x38, struct.pack("<2I", width - int(scope == "offscreen"), height))
    original = (406, 338, 408, 353)  # Native multiline caret after four characters.
    machine.mem_write(rect, struct.pack("<4I", *original))
    rect_arg = 0 if scope == "null_rect" else rect
    machine.mem_write(stack, struct.pack("<5I", stop, 37, 0x2FABC1, 0x2FABC1, rect_arg))
    machine.reg_write(UC_X86_REG_ESP, stack)
    machine.reg_write(UC_X86_REG_ECX, 0x123456)
    observed: list[tuple[int, ...] | None] = []

    def capture(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == resolve:
            current.reg_write(UC_X86_REG_EAX, record)
        if address == target:
            args = struct.unpack("<4I", current.mem_read(current.reg_read(UC_X86_REG_ESP) + 4, 16))
            assert args[:3] == (37, 0x2FABC1, 0x2FABC1)
            assert current.reg_read(UC_X86_REG_ECX) == 0x123456
            observed.append(
                struct.unpack("<4I", current.mem_read(args[3], 16)) if args[3] else None
            )

    machine.hook_add(UC_HOOK_CODE, capture)
    machine.emu_start(wrapper, stop, count=1000)
    offset = (width - 1024 * height // 768) // 2
    expected = (
        tuple(
            value * height // 768 + (offset if index % 2 == 0 else 0)
            for index, value in enumerate(original)
        )
        if scope == "framebuffer"
        else None
        if scope == "null_rect"
        else original
    )
    assert observed == [expected]
    assert machine.mem_read(rect, 16) == struct.pack("<4I", *original)
    assert machine.reg_read(UC_X86_REG_ESP) == stack + 20


def test_sidney_solid_fill_scopes_only_framebuffer_rectangles() -> None:
    payload = build_solid_fill_wrapper(
        wrapper_va=0x800000,
        target_va=0x810000,
        active_depth_va=0x820000,
        physical_width_va=0x830000,
    )
    assert len(payload) <= 0x100
    assert payload.startswith(b"\x83\x3d" + struct.pack("<I", 0x820000) + b"\x00")
    # Verify both destination dimensions before fitting any RECT. Offscreen
    # header/scrollbar construction and complete null-RECT clears stay native.
    for offset, address in ((0x38, 0x830000), (0x3C, 0x830004)):
        assert b"\xa1" + struct.pack("<I", address) + b"\x39\x41" + bytes([offset]) in payload
    assert b"\x83\x7c\x24\x08\x00" in payload
    assert b"\x83\xc4\x10\xc2\x0c\x00" in payload
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.JUMP,
            site_va=0x800000 + len(payload) - 5,
            instruction=payload[-5:],
        )
        == 0x810000
    )
