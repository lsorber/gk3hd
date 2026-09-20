"""Console layout and rectangle paths share one explicit ownership boundary."""

from __future__ import annotations

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.runtime2d.console import (
    BOUNDS_OFFSET,
    FILL_OFFSET,
    FILL_STRIDE,
    FILL_TRAMPOLINE_OFFSET,
    INPUT_OFFSET,
    INPUT_SLOTS,
    INPUT_STUB_OFFSET,
    SITES,
    WIDTH_OFFSET,
    ConsoleFeatureCompiler,
    build_damage,
    build_fill,
    build_input,
    build_transfer,
)
from gk3hd.patch.definitions.runtime2d.layout import CONSOLE_SEGMENT


def _ops(data: bytes) -> list[tuple[str, str]]:
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(data, 0x800000))
    assert sum(item.size for item in instructions) == len(data)
    return [(item.mnemonic, item.op_str) for item in instructions]


def test_console_payload_owns_layout_and_fill_not_the_shared_blitter() -> None:
    payload, _ = ConsoleFeatureCompiler(profile=GOG_BUILD).build(0x800000)
    assert len(payload) == CONSOLE_SEGMENT.size
    assert payload[:8] == CONSOLE_SEGMENT.magic
    assert GOG_BUILD.site(SITES[0]).original in payload[WIDTH_OFFSET:BOUNDS_OFFSET]
    assert GOG_BUILD.site(SITES[1]).original in payload[BOUNDS_OFFSET:0x300]
    assert [GOG_BUILD.site(name).va for name in SITES] == [
        0x463946,
        0x463B76,
        0x499656,
        0x55C0F0,
    ]
    for index, name in enumerate(SITES[2:]):
        start = FILL_OFFSET + index * FILL_STRIDE + FILL_TRAMPOLINE_OFFSET
        assert payload[start : start + 5] == GOG_BUILD.site(name).original


def test_console_transfer_handles_both_alpha_capture_and_final_destination() -> None:
    ops = _ops(
        build_transfer(
            wrapper_va=0x800000,
            owner_va=0x810010,
            dimensions_va=0x820000,
            rect_va=0x810020,
            capture_return_va=0x5773E3,
        )
    )
    assert ("cmp", "dword ptr [edi + 0x20], 0x5773e3") in ops
    assert ("mov", "ebp, 0x28") in ops
    assert ("mov", "ebp, 0x2c") in ops
    assert ("mov", "dword ptr [edi + ebp], 0x810020") in ops
    assert ops.count(("imul", "dword ptr [0x820004]")) == 4
    assert ops.count(("adc", "edx, 0")) == 4
    assert not any(mnemonic in {"call", "retf"} for mnemonic, _ in ops)


def test_console_fill_preserves_native_callee_cleanup_and_nullable_rectangles() -> None:
    for caret, cleanup, argument in ((True, "0x10", "0x14"), (False, "0xc", "0xc")):
        ops = _ops(
            build_fill(
                wrapper_va=0x800000,
                trampoline_va=0x810000,
                owner_va=0x820000,
                profile=GOG_BUILD,
                caret=caret,
            )
        )
        assert ("mov", f"esi, dword ptr [ebp + {argument}]") in ops
        assert ("test", "esi, esi") in ops
        assert ("ret", cleanup) in ops
        assert ("call", "0x534560") in ops
        assert ops[-3:] == [("popal", ""), ("leave", ""), ("jmp", "0x810000")]


def test_console_pointer_slots_share_a_private_point_inverse() -> None:
    payload, _ = ConsoleFeatureCompiler(profile=GOG_BUILD).build(0x800000)
    for index, name in enumerate(INPUT_SLOTS):
        site = GOG_BUILD.site(name)
        assert site.va == GOG_BUILD.address("console.vtable") + 0x44 + index * 4
        start = INPUT_STUB_OFFSET + index * 16
        assert payload[start : start + 5] == b"\xb8" + site.original
    body = build_input(wrapper_va=0x800000 + INPUT_OFFSET, profile=GOG_BUILD)
    assert payload[INPUT_OFFSET : INPUT_OFFSET + len(body)] == body
    ops = _ops(body)
    assert ("cmp", "dword ptr [esp + 4], 0") in ops
    assert ("lea", "eax, [ebp - 0x10]") in ops
    assert ("call", "edi") in ops
    assert ops[-2:] == [("ret", "4"), ("jmp", "eax")]
    # The caller's POINT is read through ESI, never written through it.
    assert not any(m == "mov" and operands.startswith("dword ptr [esi") for m, operands in ops)


def test_console_damage_uses_own_bounded_collection_and_reference_fallback() -> None:
    ops = _ops(
        build_damage(
            wrapper_va=0x800000,
            profile=GOG_BUILD,
            region_va=0x810040,
            rect_va=0x810050,
        )
    )
    assert ("cmp", "dword ptr [0x6f7b50], 0x400") in ops
    assert ("cmp", "dword ptr [0x6f7b54], 0x300") in ops
    for offset in range(0, 16, 4):
        assert ("mov", f"edx, dword ptr [ecx + {0x1C + offset:#x}]") in ops
        assert ("mov", f"dword ptr [{0x810050 + offset:#x}], edx") in ops
    assert ops[-3:] == [("pop", "edx"), ("mov", "eax, 0x810040"), ("ret", "")]
