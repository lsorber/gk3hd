"""Execute final-rectangle font LOD selection, including unrelated/offscreen draws."""

import itertools
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_EFLAGS,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.font_sampling import build_font_selector as build
from gk3hd.textures.upscale.fonts.bank import font_bank_layout

BASE, TARGET, STOP = 0x100000, 0x101000, 0x102000
SCOPE, ENTRY, MANAGER_PTR, MANAGER, TABLE, RESOURCE = (
    0x200000,
    0x201000,
    0x202000,
    0x203000,
    0x204000,
    0x205000,
)
SURFACE, DEST, DEST_RECT, SOURCE_RECT = 0x206000, 0x207000, 0x208000, 0x209000
STACK = 0x308000
REGS = (
    UC_X86_REG_ECX,
    UC_X86_REG_EDX,
    UC_X86_REG_EBX,
    UC_X86_REG_EBP,
    UC_X86_REG_ESI,
    UC_X86_REG_EDI,
)


def put(cpu: Uc, address: int, *values: int) -> None:
    cpu.mem_write(address, struct.pack("<" + "I" * len(values), *(v & 0xFFFFFFFF for v in values)))


def words(cpu: Uc, address: int, n: int) -> tuple[int, ...]:
    return struct.unpack("<" + "I" * n, cpu.mem_read(address, n * 4))


def run() -> None:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(BASE, 0x4000)
    cpu.mem_map(SCOPE, 0x10000)
    cpu.mem_map(0x300000, 0x10000)
    cpu.mem_write(
        BASE, build(base_va=BASE, native_va=TARGET, scope_va=SCOPE, manager_va=MANAGER_PTR)
    )
    cpu.mem_write(TARGET, bytes.fromhex("b878563412 c20c00"))
    calls: list[dict[str, object]] = []

    def capture(machine: Uc, address: int, _size: int, _user: object) -> None:
        if address == TARGET:
            args = words(machine, machine.reg_read(UC_X86_REG_ESP) + 4, 3)
            calls.append(
                {
                    "source": args[0],
                    "destination": words(machine, args[1], 4) if args[1] else None,
                    "rect": words(machine, args[2], 4) if args[2] else None,
                    "pointer": args[2],
                    "receiver": machine.reg_read(UC_X86_REG_ECX),
                }
            )

    cpu.hook_add(UC_HOOK_CODE, capture)
    check_geometry(cpu, calls)
    check_rejections(cpu, calls)
    check_nested(cpu, calls)
    cpu.mem_write(TARGET, bytes.fromhex("b878563412 c20c00"))
    cpu.ctl_remove_cache(TARGET, TARGET + 512)
    check_row_banks(cpu, calls)
    check_native_cache(cpu, calls)


def check_native_cache(cpu: Uc, calls: list[dict[str, object]]) -> None:
    """A larger atlas cannot recover detail after a native-size cache draw."""
    # Actual pull-down geometry: a 24x40 source region becomes a 6x10 glyph
    # in a 112x13 SpriteButton cache, even with a 4K desktop. Only promoting
    # the cache AND its glyph destinations can select reconstructed artwork.
    put(cpu, SCOPE, ENTRY)
    put(cpu, ENTRY, 7, 512, 12, 181)
    put(cpu, ENTRY + 112, 2048, 3, 36, 1)
    put(cpu, MANAGER_PTR, MANAGER)
    put(cpu, MANAGER + 0x120, TABLE, 16)
    put(cpu, TABLE + 28, RESOURCE)
    put(cpu, RESOURCE + 0x30, SURFACE)
    put(cpu, SURFACE + 0x38, 4096, 144)
    source = (1220, 4, 1244, 44)
    for cache_scale, glyph_scale in ((1, 1), (4, 1), (4, 4)):
        put(cpu, DEST + 0x38, 112 * cache_scale, 13 * cache_scale)
        dest = tuple(value * glyph_scale for value in (54, 1, 60, 11))
        put(cpu, SOURCE_RECT, *source)
        put(cpu, DEST_RECT, *dest)
        put(cpu, STACK, STOP, SURFACE, DEST_RECT, SOURCE_RECT)
        execute_nested(cpu, calls)
        expected = (3268, 4, 3292, 44) if glyph_scale == 4 else source
        assert len(calls) == 1
        assert calls[0]["rect"] == expected
        assert calls[0]["destination"] == dest
        assert words(cpu, SOURCE_RECT, 4) == source


def check_row_banks(cpu: Uc, calls: list[dict[str, object]]) -> None:
    """All atlas rows, clipped glyphs and signed-bank rejection boundaries."""
    for row, factor, cuts, fault in itertools.product(
        range(3),
        (0.5, 1, 1.05, 2.8125, 4),
        (0, 4),
        ("", "identity", "width", "height", "stride", "kind", "negative", "overrun", "second"),
    ):
        put(cpu, SCOPE, ENTRY)
        put(cpu, ENTRY, 7, 517, 16, 181)
        put(cpu, ENTRY + 112, 2068, 3, 48, 1)
        put(cpu, MANAGER_PTR, MANAGER)
        put(cpu, MANAGER + 0x120, TABLE, 16)
        put(cpu, TABLE + 28, RESOURCE)
        put(cpu, RESOURCE + 0x30, SURFACE)
        put(cpu, SURFACE + 0x38, 4136, 192)
        rect = (8 + cuts, row * 64 + 4 + cuts, 48 - cuts, row * 64 + 60 - cuts)
        changes = {
            "identity": (RESOURCE + 0x30, SURFACE + 0x100),
            "width": (SURFACE + 0x38, 4132),
            "height": (SURFACE + 0x3C, 188),
            "stride": (ENTRY + 112, 2064),
            "kind": (ENTRY + 124, 2),
        }
        if fault in changes:
            address, value = changes[fault]
            put(cpu, address, value)
        rect = {
            "negative": (-4, rect[1], rect[2], rect[3]),
            "overrun": (rect[0], rect[1], rect[2], 196),
            "second": (2076, rect[1], 2116, rect[3]),
        }.get(fault, rect)
        sw, sh = rect[2] - rect[0], rect[3] - rect[1]
        dw, dh = max(1, round(sw * factor / 4)), max(1, round(sh * factor / 4))
        dest = (10, 20, 10 + dw, 20 + dh)
        put(cpu, SOURCE_RECT, *rect)
        put(cpu, DEST_RECT, *dest)
        put(cpu, STACK, STOP, SURFACE, DEST_RECT, SOURCE_RECT)
        before = execute_nested(cpu, calls)
        selected = not fault and dw * 4 >= sw and dh * 4 >= sh and (dw * 4 > sw or dh * 4 > sh)
        expected = (rect[0] + 2068, rect[1], rect[2] + 2068, rect[3]) if selected else rect
        expected = tuple(v & 0xFFFFFFFF for v in expected)
        assert len(calls) == 1
        assert calls[0]["rect"] == expected, (row, factor, cuts, fault, calls)
        assert calls[0]["destination"] == dest
        assert words(cpu, SOURCE_RECT, 4) == tuple(v & 0xFFFFFFFF for v in rect)
        assert all(cpu.reg_read(r) == v for r, v in before.items())
        assert cpu.reg_read(UC_X86_REG_ESP) == STACK + 16
        assert cpu.reg_read(UC_X86_REG_EFLAGS) == 0x602


def check_geometry(cpu: Uc, calls: list[dict[str, object]]) -> None:
    for name in ("F_ARIAL_T8.BMP", "F_ARIAL_T10.BMP", "F_ARIAL_T12.BMP"):
        layout = font_bank_layout(name)
        assert layout is not None
        w, h = layout.source_size
        stride = layout.bank_distance
        for index, cuts, factor, flags in itertools.product(
            (0, 37, 93),
            itertools.product((0, 1), repeat=4),
            (0.5, 1, 1.05, 2, 2.8125, 4),
            (0x202, 0x602),
        ):
            glyph = layout.glyph_rect(index, 4)
            rect = tuple(
                v * 4 + (cuts[i] * 4 if i < 2 else -cuts[i] * 4) for i, v in enumerate(glyph)
            )
            sw, sh = rect[2] - rect[0], rect[3] - rect[1]
            dw, dh = max(1, round(sw / 4 * factor)), max(1, round(sh / 4 * factor))
            dest = (50, 60, 50 + dw, 60 + dh)
            put(cpu, SCOPE, ENTRY)
            put(cpu, ENTRY, 7, w, h, layout.max_advance)
            put(cpu, ENTRY + 112, stride)
            put(cpu, MANAGER_PTR, MANAGER)
            put(cpu, MANAGER + 0x120, TABLE, 16)
            put(cpu, TABLE + 7 * 4, RESOURCE)
            put(cpu, RESOURCE + 0x30, SURFACE)
            put(cpu, SURFACE + 0x38, w * 4, h * 4 + stride * 2)
            put(cpu, DEST_RECT, *dest)
            put(cpu, SOURCE_RECT, *rect)
            put(cpu, STACK, STOP, SURFACE, DEST_RECT, SOURCE_RECT)
            for register, value in zip(
                REGS, (DEST, 0x123, 0x456, 0x789, 0xABC, 0xDEF), strict=True
            ):
                cpu.reg_write(register, value)
            before = {r: cpu.reg_read(r) for r in REGS}
            cpu.reg_write(UC_X86_REG_ESP, STACK)
            cpu.reg_write(UC_X86_REG_EFLAGS, flags)
            calls.clear()
            cpu.emu_start(BASE, STOP)
            selected = dw * 4 >= sw and dh * 4 >= sh and (dw * 4 > sw or dh * 4 > sh)
            expected = (rect[0], rect[1] + stride, rect[2], rect[3] + stride) if selected else rect
            assert len(calls) == 1
            assert calls[0]["rect"] == expected, (
                name,
                index,
                cuts,
                factor,
                calls,
                expected,
            )
            assert calls[0]["destination"] == dest
            assert calls[0]["source"] == SURFACE
            assert calls[0]["receiver"] == DEST
            assert words(cpu, SOURCE_RECT, 4) == rect
            assert words(cpu, DEST_RECT, 4) == dest
            assert all(cpu.reg_read(r) == v for r, v in before.items())
            assert cpu.reg_read(UC_X86_REG_EAX) == 0x12345678
            assert cpu.reg_read(UC_X86_REG_ESP) == STACK + 16
            assert cpu.reg_read(UC_X86_REG_EFLAGS) == flags


def check_rejections(cpu: Uc, calls: list[dict[str, object]]) -> None:
    layout = font_bank_layout("F_ARIAL_T12.BMP")
    assert layout is not None
    w, h = layout.source_size
    stride = layout.bank_distance
    put(cpu, ENTRY, 7, w, h, layout.max_advance)
    put(cpu, ENTRY + 112, stride)
    # Deliberately valid-looking source dimensions must not substitute for identity.
    for case in (
        "no_scope",
        "wrong_source",
        "empty_slot",
        "slot_out_of_range",
        "header",
        "second_bank",
        "wrong_width",
        "wrong_height",
        "null_source_rect",
        "null_dest_rect",
        "empty_dest",
        "empty_source",
        "mixed_scale",
        "overflow_dest",
    ):
        put(cpu, SCOPE, ENTRY)
        put(cpu, MANAGER + 0x124, 16)
        put(cpu, TABLE + 28, RESOURCE)
        put(cpu, RESOURCE + 0x30, SURFACE)
        put(cpu, SURFACE + 0x38, w * 4, h * 4 + stride * 2)
        rect = (4, h * 4, 28, h * 4 + 40)
        dest = (0, 0, 24, 40)
        source_pointer = SOURCE_RECT
        dest_pointer = DEST_RECT
        mutations = {
            "no_scope": (SCOPE, 0),
            "wrong_source": (RESOURCE + 0x30, SURFACE + 0x100),
            "empty_slot": (TABLE + 28, 0),
            "slot_out_of_range": (MANAGER + 0x124, 7),
            "wrong_width": (SURFACE + 0x38, w * 4 + 4),
            "wrong_height": (SURFACE + 0x3C, h * 4 + stride * 2 + 4),
        }
        if case in mutations:
            address, value = mutations[case]
            put(cpu, address, value)
        rect = {
            "header": (4, 4, 28, 44),
            "second_bank": (4, h * 4 + stride, 28, h * 4 + stride + 40),
            "empty_source": (4, h * 4, 4, h * 4 + 40),
        }.get(case, rect)
        dest = {
            "empty_dest": (0, 0, 0, 40),
            "mixed_scale": (0, 0, 24, 5),
            "overflow_dest": (0, 0, 0x20000000, 40),
        }.get(case, dest)
        source_pointer = 0 if case == "null_source_rect" else SOURCE_RECT
        dest_pointer = 0 if case == "null_dest_rect" else DEST_RECT
        put(cpu, SOURCE_RECT, *rect)
        put(cpu, DEST_RECT, *dest)
        put(cpu, STACK, STOP, SURFACE, dest_pointer, source_pointer)
        # The dummy native target does not dereference passthrough null pointers.
        calls.clear()
        cpu.reg_write(UC_X86_REG_ESP, STACK)
        cpu.reg_write(UC_X86_REG_ECX, DEST)
        cpu.emu_start(BASE, STOP)
        assert len(calls) == 1, (case, calls)
        assert calls[0]["pointer"] == source_pointer, (case, calls)
        assert calls[0]["rect"] == (rect if source_pointer else None), (case, calls)


def check_nested(cpu: Uc, calls: list[dict[str, object]]) -> None:
    layout = font_bank_layout("F_ARIAL_T12.BMP")
    assert layout is not None
    w, h, stride = *layout.source_size, layout.bank_distance
    # Native code invokes a second text draw before the outer call returns. Its
    # independently owned scope is restored by the high-level caller, not by this
    # final selector. The outer source RECT must survive the entire nested call.
    depth, entry2, resource2, surface2, dest2, dr2, sr2 = (
        0x20A000,
        0x20A100,
        0x20B000,
        0x20B100,
        0x20B200,
        0x20B300,
        0x20B400,
    )
    for kind in ("unscoped-scaled", "other-font-outline", "other-font-native-size"):
        put(cpu, SCOPE, ENTRY)
        put(cpu, ENTRY, 7, w, h, layout.max_advance)
        put(cpu, ENTRY + 112, stride)
        put(cpu, MANAGER + 0x120, TABLE, 16)
        put(cpu, TABLE + 28, RESOURCE)
        put(cpu, RESOURCE + 0x30, SURFACE)
        put(cpu, SURFACE + 0x38, w * 4, h * 4 + stride * 2)
        inner_layout = font_bank_layout("F_ARIAL_T8.BMP")
        assert inner_layout is not None
        iw, ih = inner_layout.source_size
        inner_stride = inner_layout.bank_distance
        put(cpu, entry2, 8, iw, ih, inner_layout.max_advance)
        put(cpu, entry2 + 112, inner_stride)
        put(cpu, TABLE + 32, resource2)
        put(cpu, resource2 + 0x30, surface2)
        put(cpu, surface2 + 0x38, iw * 4, ih * 4 + inner_stride * 2)
        rect = (4, h * 4, 28, h * 4 + 40)
        dest = (30, 40, 54, 80)
        inner_rect = (4, ih * 4, 28, ih * 4 + 40)
        inner_dest = (2, 3, 8, 13) if kind == "other-font-native-size" else (2, 3, 26, 43)
        put(cpu, SOURCE_RECT, *rect)
        put(cpu, DEST_RECT, *dest)
        put(cpu, sr2, *inner_rect)
        put(cpu, dr2, *inner_dest)
        put(cpu, depth, 0)
        stub = nested_stub(kind, (depth, entry2, surface2, dest2, dr2, sr2))
        cpu.mem_write(TARGET, stub)
        cpu.ctl_remove_cache(TARGET, TARGET + 512)
        put(cpu, STACK, STOP, SURFACE, DEST_RECT, SOURCE_RECT)
        before = execute_nested(cpu, calls)
        assert len(calls) == 2, (kind, calls)
        expected = (rect[0], rect[1] + stride, rect[2], rect[3] + stride)
        inner_expected = (
            (
                inner_rect[0],
                inner_rect[1] + inner_stride,
                inner_rect[2],
                inner_rect[3] + inner_stride,
            )
            if kind == "other-font-outline"
            else inner_rect
        )
        assert calls[0]["rect"] == expected, (kind, calls)
        assert calls[1]["rect"] == inner_expected, (kind, calls)
        pointer = calls[0]["pointer"]
        assert isinstance(pointer, int)
        assert words(cpu, pointer, 4) == expected
        assert words(cpu, SOURCE_RECT, 4) == rect
        assert words(cpu, sr2, 4) == inner_rect
        assert words(cpu, SCOPE, 1) == (ENTRY,)
        assert words(cpu, depth, 1) == (0,)
        assert all(cpu.reg_read(r) == v for r, v in before.items())
        assert cpu.reg_read(UC_X86_REG_EFLAGS) == 0x602
        assert cpu.reg_read(UC_X86_REG_ESP) == STACK + 16
        assert cpu.reg_read(UC_X86_REG_EAX) == 0x12345678


def execute_nested(cpu: Uc, calls: list[dict[str, object]]) -> dict[int, int]:
    for register, value in zip(REGS, (DEST, 0x123, 0x456, 0x789, 0xABC, 0xDEF), strict=True):
        cpu.reg_write(register, value)
    before = {r: cpu.reg_read(r) for r in REGS}
    cpu.reg_write(UC_X86_REG_ESP, STACK)
    cpu.reg_write(UC_X86_REG_EFLAGS, 0x602)
    calls.clear()
    cpu.emu_start(BASE, STOP)
    return before


def nested_stub(kind: str, context: tuple[int, ...]) -> bytes:
    depth, entry2, surface2, dest2, dr2, sr2 = context
    stub = X86Emitter(base_va=TARGET)
    stub.raw(bytes.fromhex("833d") + struct.pack("<I", depth) + b"\0")
    stub.jump_if(Condition.NOT_EQUAL, "finish")
    stub.raw(
        bytes.fromhex("ff05")
        + struct.pack("<I", depth)
        + bytes.fromhex("9c60 ff35")
        + struct.pack("<I", SCOPE)
    )
    stub.raw(
        bytes.fromhex("c705")
        + struct.pack("<II", SCOPE, 0 if kind == "unscoped-scaled" else entry2)
    )
    for argument in (sr2, dr2, surface2):
        stub.raw(b"\x68" + struct.pack("<I", argument))
    stub.raw(b"\xb9" + struct.pack("<I", dest2))
    stub.call_absolute(BASE)
    stub.raw(
        bytes.fromhex("8f05")
        + struct.pack("<I", SCOPE)
        + bytes.fromhex("619d ff0d")
        + struct.pack("<I", depth)
    )
    stub.label("finish")
    stub.raw(bytes.fromhex("b878563412 c20c00"))

    return stub.build()


@pytest.mark.slow
def test_executed_font_sampling() -> None:
    subprocess.run(  # noqa: S603 - fixed interpreter and this test module.
        [sys.executable, str(Path(__file__).resolve())],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )


if __name__ == "__main__":
    run()
