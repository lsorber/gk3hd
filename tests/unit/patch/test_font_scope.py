"""Execute bank scope publication/clearing with the real native glyph resolver."""

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
from gk3hd.patch.definitions.runtime2d.font_bank import FontBankRuntime
from gk3hd.patch.definitions.runtime2d.font_sampling import build_font_scope as build_scope
from gk3hd.textures.upscale.fonts.bank import FONT_PADDED_BANK_LAYOUTS, font_bank_layout

BASE, RECORD, TARGET, STOP = 0x100000, 0x100800, 0x101000, 0x102000
CACHE, SCOPE, FONT, EMPTY_FONT, DEPTH = 0x200000, 0x203000, 0x204000, 0x205000, 0x206000
STACK, FRAME, FRAME2 = 0x308000, 0x309000, 0x309100
REGS = (
    UC_X86_REG_ECX,
    UC_X86_REG_EDX,
    UC_X86_REG_EBX,
    UC_X86_REG_EBP,
    UC_X86_REG_ESI,
    UC_X86_REG_EDI,
)


def put(c: Uc, a: int, *v: int) -> None:
    c.mem_write(a, struct.pack("<" + "I" * len(v), *(x & 0xFFFFFFFF for x in v)))


def words(c: Uc, a: int, n: int) -> tuple[int, ...]:
    return struct.unpack("<" + "I" * n, c.mem_read(a, n * 4))


def run() -> None:
    c = Uc(UC_ARCH_X86, UC_MODE_32)
    c.mem_map(BASE, 0x4000)
    c.mem_map(CACHE, 0x10000)
    c.mem_map(0x300000, 0x10000)
    c.mem_write(BASE, build_scope(base_va=BASE, target_va=TARGET, record_va=RECORD, scope_va=SCOPE))
    resolver = FontBankRuntime(CACHE, CACHE + 0x3000, CACHE + 0x3004, STOP).glyph_record(RECORD)
    c.mem_write(RECORD, resolver)
    c.mem_write(TARGET, bytes.fromhex("b878563412 c21400"))
    calls: list[dict[str, object]] = []

    def observe(cpu: Uc, address: int, _size: int, _user: object) -> None:
        if address == TARGET:
            calls.append(
                {
                    "scope": words(cpu, SCOPE, 1)[0],
                    "args": words(cpu, cpu.reg_read(UC_X86_REG_ESP) + 4, 5),
                    "font": cpu.reg_read(UC_X86_REG_EDX),
                }
            )

    c.hook_add(UC_HOOK_CODE, observe)
    check_scopes(c, calls)
    check_nested(c, calls)


def check_scopes(c: Uc, calls: list[dict[str, object]]) -> None:
    for name, entry_index, slot, selected, flags in itertools.product(
        FONT_PADDED_BANK_LAYOUTS,
        (0, 1, 63),
        (0, 37, 93, 95, 96, 127, 128, 179, 180, 255),
        (False, True),
        (0x202, 0x602),
    ):
        layout = font_bank_layout(name)
        assert layout is not None
        entry = CACHE + entry_index * 128
        c.mem_write(CACHE, bytes(8192))
        put(c, entry, 7, *layout.source_size, layout.max_advance)
        selected_bits = (1 << layout.glyph_count) - 1 if selected else 0
        c.mem_write(entry + 16, selected_bits.to_bytes(96, "little"))
        put(c, entry + 116, layout.glyph_count)
        put(c, FONT + 4, 7)
        put(c, FONT + 0x34, layout.source_size[0] - 1, layout.source_size[1] - 1)
        count = layout.glyph_count + 1
        c.mem_write(FONT + 0x50, struct.pack(f"<{count}H", *(1 + 4 * i for i in range(count))))
        put(c, FRAME - 0x14, slot)
        put(c, SCOPE, 0x22334455)
        put(c, STACK, STOP, 11, 22, 33, 44, 55)
        for r, v in zip(REGS, (0x123, FONT, 0x456, FRAME, 0xABC, 0xDEF), strict=True):
            c.reg_write(r, v)
        c.reg_write(UC_X86_REG_EAX, 0x123ABC)
        c.reg_write(UC_X86_REG_ESP, STACK)
        c.reg_write(UC_X86_REG_EFLAGS, flags)
        before = {r: c.reg_read(r) for r in REGS}
        calls.clear()
        c.emu_start(BASE, STOP)
        assert calls == [
            {
                "scope": entry if selected and slot < layout.glyph_count else 0,
                "args": (11, 22, 33, 44, 55),
                "font": FONT,
            }
        ], calls
        assert words(c, SCOPE, 1) == (0x22334455,)
        assert all(c.reg_read(r) == v for r, v in before.items())
        assert c.reg_read(UC_X86_REG_EAX) == 0x12345678
        assert c.reg_read(UC_X86_REG_ESP) == STACK + 24
        assert c.reg_read(UC_X86_REG_EFLAGS) == flags


def check_nested(c: Uc, calls: list[dict[str, object]]) -> None:
    layout = font_bank_layout("F_ARIAL_T12.BMP")
    assert layout is not None
    put(c, FONT + 4, 7)
    put(c, FONT + 0x34, layout.source_size[0] - 1, layout.source_size[1] - 1)
    put(c, FRAME - 0x14, 93)
    # The native downstream recursively draws an unregistered font. It must see
    # zero scope even though the outer bank font is still live on the call stack.
    c.mem_write(CACHE, bytes(8192))
    put(c, CACHE, 7, *layout.source_size, layout.max_advance)
    c.mem_write(CACHE + 16, ((1 << 94) - 1).to_bytes(96, "little"))
    put(c, CACHE + 116, 94)
    put(c, EMPTY_FONT + 4, 0)
    put(c, FRAME2 - 0x14, 0)
    put(c, DEPTH, 0)
    stub = X86Emitter(base_va=TARGET)
    stub.raw(bytes.fromhex("833d") + struct.pack("<I", DEPTH) + b"\0")
    stub.jump_if(Condition.NOT_EQUAL, "finish")
    stub.raw(bytes.fromhex("ff05") + struct.pack("<I", DEPTH) + bytes.fromhex("9c60"))
    for value in (55, 44, 33, 22, 11):
        stub.raw(b"\x68" + struct.pack("<I", value))
    stub.raw(b"\xba" + struct.pack("<I", EMPTY_FONT) + b"\xbd" + struct.pack("<I", FRAME2))
    stub.call_absolute(BASE)
    stub.raw(bytes.fromhex("619d ff0d") + struct.pack("<I", DEPTH))
    stub.label("finish")
    stub.raw(bytes.fromhex("b878563412 c21400"))
    c.mem_write(TARGET, stub.build())
    c.ctl_remove_cache(TARGET, TARGET + 512)
    put(c, SCOPE, 0x22334455)
    put(c, STACK, STOP, 11, 22, 33, 44, 55)
    c.reg_write(UC_X86_REG_EDX, FONT)
    c.reg_write(UC_X86_REG_EBP, FRAME)
    c.reg_write(UC_X86_REG_ESP, STACK)
    calls.clear()
    c.emu_start(BASE, STOP)
    assert [r["scope"] for r in calls] == [CACHE, 0], calls
    assert words(c, SCOPE, 1) == (0x22334455,)
    assert c.reg_read(UC_X86_REG_ESP) == STACK + 24


@pytest.mark.slow
def test_executed_font_scope() -> None:
    subprocess.run(  # noqa: S603 - fixed interpreter and this test module.
        [sys.executable, str(Path(__file__).resolve())],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )


if __name__ == "__main__":
    run()
