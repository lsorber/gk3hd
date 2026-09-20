"""Contracts for the software effect path that bypasses SIDNEY's final blit."""

import struct

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
