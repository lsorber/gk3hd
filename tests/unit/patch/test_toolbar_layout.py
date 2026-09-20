"""The toolbar layout commit preserves native sizes and fits presented bounds."""

from __future__ import annotations

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

from gk3hd.patch.definitions.runtime2d.system.toolbar_layout import (
    build_toolbar_cursor_warp,
    build_toolbar_layout,
)


def test_toolbar_fit_preserves_native_commit_abi_and_uses_live_display() -> None:
    """The bounded helper shifts both edges then tail-enters native relocation."""
    payload = build_toolbar_layout(
        wrapper_va=0x800000,
        physical_width_va=0x810000,
        input_valid_va=0x810010,
        target_va=0x4ECCD1,
    )
    decoded = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in decoded) == len(payload)
    assert len(payload) <= 0xA0
    instructions = [(i.mnemonic, i.op_str) for i in decoded]
    assert instructions[0] == ("pushal", "")
    assert instructions[-2:] == [("popal", ""), ("jmp", "0x4eccd1")]
    for instruction in (
        ("mov", "edi, dword ptr [esp + 0x24]"),
        ("mov", "ebp, dword ptr [0x810004]"),
        ("sub", "eax, dword ptr [esi + 0x810000]"),
        ("sub", "dword ptr [edi + esi], eax"),
        ("sub", "dword ptr [edi + esi + 8], eax"),
        ("mov", "ecx, dword ptr [esp + 0x18]"),
        ("mov", "dword ptr [0x810010], 0"),
    ):
        assert instruction in instructions


def test_slider_cursor_return_maps_private_point_with_compositor_anchor() -> None:
    payload = build_toolbar_cursor_warp(
        wrapper_va=0x800000,
        physical_width_va=0x810000,
        input_valid_va=0x810010,
        source_rect_va=0x810020,
        target_va=0x56C920,
    )
    decoded = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in decoded) == len(payload)
    assert len(payload) <= 0xB0
    instructions = [(i.mnemonic, i.op_str) for i in decoded]
    assert instructions[-1] == ("jmp", "0x56c920")
    for instruction in (
        ("cmp", "dword ptr [0x810010], 0"),
        ("mov", "ebx, 0x7e"),
        ("mov", "ebx, 0x25"),
        ("imul", "eax, dword ptr [0x810004]"),
        ("mov", "ecx, 0x300"),
        ("mov", "dword ptr [ebp + esi - 8], eax"),
        ("call", "0x56c920"),
    ):
        assert instruction in instructions
