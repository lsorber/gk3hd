"""Execute padded-font registration, including rejects and handle reuse."""

from __future__ import annotations

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

from gk3hd.patch.definitions.runtime2d.font_bank import (
    FONT_BANK_CACHE_SIZE,
    FONT_BANK_CACHE_STRIDE,
    FontBankRuntime,
    font_padded_layout_table,
    font_row_layout_table,
)
from gk3hd.textures.upscale.fonts.bank import (
    FONT_BANK_SIGNATURE,
    FONT_PADDED_BANK_LAYOUTS,
    FONT_ROW_BANK_LAYOUTS,
    FONT_ROW_BANK_SIGNATURE,
    FontBankLayout,
    font_bank_layout,
    font_row_bank_layout,
)

_CODE = 0x100000
_GET_PIXEL = 0x101000
_STOP = 0x102000
_FONT = 0x200000
_STACK = 0x308000
_CACHE = 0x400000
_CURSOR = 0x404000
_MANAGER = 0x404004
_HANDLE = 123
_KEY = 0xF800F8
_RUNTIME = FontBankRuntime(_CACHE, _CURSOR, _MANAGER, _GET_PIXEL)
_REGISTERS = {
    UC_X86_REG_EBX: 0x11223344,
    UC_X86_REG_ECX: 0x22334455,
    UC_X86_REG_EDX: 0x33445566,
    UC_X86_REG_ESI: _FONT,
    UC_X86_REG_EDI: 0x44556677,
    UC_X86_REG_EBP: 0x55667788,
    UC_X86_REG_ESP: _STACK,
    UC_X86_REG_EFLAGS: 0x646,  # Including DF, which the staged copy must restore.
}


def _machine(
    name: str, ink: int, fault: str = "", *, key: int = _KEY
) -> tuple[Uc, list[tuple[int, int]]]:
    row_layout = font_row_bank_layout(name)
    row_bank = row_layout is not None
    layout = row_layout if row_layout is not None else font_bank_layout(name)
    assert layout is not None
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    for address, size in ((_CODE, 0x3000), (_FONT, 0x1000), (0x300000, 0x10000), (_CACHE, 0x5000)):
        machine.mem_map(address, size)
    machine.mem_write(_CODE, _RUNTIME.registration(_CODE, row_layouts_va=_STOP + 0x100))
    machine.mem_write(_STOP + 0x100, font_row_layout_table() + font_padded_layout_table())
    machine.mem_write(_GET_PIXEL, bytes.fromhex("c20c00"))
    machine.mem_write(_STACK, struct.pack("<I", _STOP))
    machine.mem_write(_MANAGER, struct.pack("<I", 0x12345678))
    machine.mem_write(_FONT + 4, struct.pack("<I", _HANDLE))
    height = (
        layout.source_size[1] // row_layout.line_count - 1
        if row_layout is not None
        else layout.image_size[1] // 4 - 1
    )
    width = layout.source_size[0] * (2 if row_bank else 1) - 1
    machine.mem_write(_FONT + 0x34, struct.pack("<2I", width, height))
    machine.mem_write(_FONT + 0x4C, struct.pack("<I", row_layout.line_count if row_layout else 1))
    for register, value in {**_REGISTERS, UC_X86_REG_EAX: height}.items():
        machine.reg_write(register, value)
    signature = FONT_ROW_BANK_SIGNATURE if row_bank else FONT_BANK_SIGNATURE
    bits = [bool(byte & (1 << bit)) for byte in signature for bit in range(7, -1, -1)]
    # Row storage stops after the signature; trailing bits must not be read.
    bits.extend(index % 3 == 0 for index in range(layout.glyph_count))
    if fault in {"signature", "second-word"}:
        index = 0 if fault == "signature" else 40
        bits[index] = not bits[index]
    corruptions = {
        "width": (0x34, layout.source_size[0]),
        "height": (0x38, height + 1),
        "rows": (0x4C, 2),
        "handle": (4, 0),
    }
    if fault in corruptions:
        offset, value = corruptions[fault]
        machine.mem_write(_FONT + offset, struct.pack("<I", value))
    calls = []
    nonbinary_at = {
        "nonbinary": (40 if row_bank else 100, 2),
        "last-flag": (64 + layout.glyph_count, 2),
    }.get(fault)

    def pixel(uc: Uc, address: int, _size: int, _user: object) -> None:
        if address != _GET_PIXEL:
            return
        handle, x, y = struct.unpack("<3I", uc.mem_read(uc.reg_read(UC_X86_REG_ESP) + 4, 12))
        assert handle == _HANDLE
        assert uc.reg_read(UC_X86_REG_ECX) == 0x12345678
        calls.append((x, y))
        if row_bank:
            x -= layout.bank_distance
        selected = x == 2 if y == 1 else bits[x - 1]
        value = ink if selected else key
        if fault == "anchors" and y == 1:
            value = key
        if (x, y) == nonbinary_at:
            value = 0x102030
        uc.reg_write(UC_X86_REG_EAX, value)
        # A real native call may destroy volatile registers.
        uc.reg_write(UC_X86_REG_ECX, 0xDEADBEEF)
        uc.reg_write(UC_X86_REG_EDX, 0xBADF00D)

    machine.hook_add(UC_HOOK_CODE, pixel)
    return machine, calls


def _row_banks(name: str) -> None:
    layout = FONT_ROW_BANK_LAYOUTS[name]
    # Include AlphaBlend tooltip recoloring: dark/red text on a white background.
    for key, ink in (
        (_KEY, 0),
        (_KEY, 0xD800B0),
        (_KEY, 0xF8FCF8),
        (0xF8FCF8, 0),
        (0xF8FCF8, 0x600000),
    ):
        for fault in (
            "",
            "signature",
            "second-word",
            "anchors",
            "nonbinary",
            "width",
            "height",
            "rows",
        ):
            machine, calls = _machine(name, ink, fault, key=key)
            # Reusing an entry must clear flags from an unrelated previous font.
            machine.mem_write(_CACHE, struct.pack("<I", _HANDLE) + b"\xff" * 124)
            original = bytes(machine.mem_read(_FONT, 0x300))
            _execute(machine)
            if fault:
                assert machine.mem_read(_CACHE, 4) == bytes(4), fault
                assert machine.mem_read(_FONT, 0x300) == original, fault
                continue
            assert len(calls) == 66
            expected = bytearray(original)
            struct.pack_into("<I", expected, 0x34, layout.source_size[0] - 1)
            assert machine.mem_read(_FONT, 0x300) == expected
            assert struct.unpack("<4I", machine.mem_read(_CACHE, 16)) == (
                _HANDLE,
                layout.source_size[0],
                layout.source_size[1] // layout.line_count,
                layout.glyph_count,
            )
            assert machine.mem_read(_CACHE + 16, 96) == bytes(96)
            assert struct.unpack("<4I", machine.mem_read(_CACHE + 112, 16)) == (
                layout.bank_distance,
                layout.line_count,
                layout.source_size[1],
                1,
            )
            _row_records(machine, layout.glyph_count)


def _row_records(machine: Uc, glyph_count: int) -> None:
    machine.mem_write(_CODE + 0x800, _RUNTIME.glyph_record(_CODE + 0x800))
    original = bytes(machine.mem_read(_FONT, 0x300))
    output = _FONT + 0x400
    for index in (*range(glyph_count), glyph_count, 255, 256, 0xFFFFFFFF):
        for fault in (False, True):
            machine.mem_write(_FONT, original)
            if fault:
                machine.mem_write(_FONT + 0x4C, struct.pack("<I", 2))
            machine.mem_write(output, b"\xff" * 20)
            registers = {
                **_REGISTERS,
                UC_X86_REG_EAX: index,
                UC_X86_REG_EDX: _FONT,
                UC_X86_REG_ECX: output,
            }
            for register, value in registers.items():
                machine.reg_write(register, value)
            machine.emu_start(_CODE + 0x800, _STOP, count=2000)
            accepted = index < glyph_count and not fault
            expected = struct.pack("<5I", 0, 0, 0, 0, _CACHE) if accepted else b"\xff" * 20
            assert machine.mem_read(output, 20) == expected
            for register, value in registers.items():
                wanted = (
                    int(accepted)
                    if register == UC_X86_REG_EAX
                    else value + (4 if register == UC_X86_REG_ESP else 0)
                )
                assert machine.reg_read(register) == wanted


def _execute(machine: Uc) -> None:
    machine.emu_start(_CODE, _STOP, count=20000)
    for register, value in _REGISTERS.items():
        assert machine.reg_read(register) == value + (4 if register == UC_X86_REG_ESP else 0)


def _accepted(name: str, ink: int) -> None:
    layout = font_bank_layout(name)
    assert layout is not None
    machine, calls = _machine(name, ink)
    original_font = bytes(machine.mem_read(_FONT, 0x100))
    _execute(machine)
    assert len(calls) == 66 + layout.glyph_count
    assert machine.reg_read(UC_X86_REG_EAX) == layout.source_size[1] - 1
    expected_font = bytearray(original_font)
    struct.pack_into("<I", expected_font, 0x38, layout.source_size[1] - 1)
    assert machine.mem_read(_FONT, 0x100) == expected_font
    record = bytes(machine.mem_read(_CACHE, FONT_BANK_CACHE_STRIDE))
    assert struct.unpack("<4I", record[:16]) == (_HANDLE, *layout.source_size, layout.max_advance)
    flags = sum(1 << index for index in range(layout.glyph_count) if index % 3 == 0)
    assert record[16:112] == flags.to_bytes(96, "little")
    assert struct.unpack("<I", record[112:116])[0] == layout.bank_distance
    assert struct.unpack("<I", record[116:120])[0] == layout.glyph_count
    remaining = FONT_BANK_CACHE_SIZE - FONT_BANK_CACHE_STRIDE
    assert machine.mem_read(_CACHE + FONT_BANK_CACHE_STRIDE, remaining) == bytes(remaining)


def _rejected(fault: str) -> None:
    machine, calls = _machine("F_ARIAL_T10.BMP", 0xD800B0, fault)
    original_font = bytes(machine.mem_read(_FONT, 0x100))
    original_eax = machine.reg_read(UC_X86_REG_EAX)
    _execute(machine)
    assert machine.reg_read(UC_X86_REG_EAX) == original_eax
    assert machine.mem_read(_FONT, 0x100) == original_font
    assert machine.mem_read(_CACHE, FONT_BANK_CACHE_SIZE) == bytes(FONT_BANK_CACHE_SIZE)
    if fault in {"width", "height", "rows", "handle"}:
        assert calls == []


def _last_flag_rejected(name: str) -> None:
    layout = font_bank_layout(name)
    assert layout is not None
    machine, calls = _machine(name, 0, "last-flag")
    original = bytes(machine.mem_read(_FONT, 0x300))
    _execute(machine)
    assert calls[-1] == (64 + layout.glyph_count, 2)
    assert machine.mem_read(_CACHE, FONT_BANK_CACHE_SIZE) == bytes(FONT_BANK_CACHE_SIZE)
    assert machine.mem_read(_FONT, 0x300) == original


def _reused(fault: str) -> None:
    machine, _calls = _machine("F_ARIAL_T10.BMP", 0, fault)
    slot = _CACHE + 7 * FONT_BANK_CACHE_STRIDE
    machine.mem_write(slot, struct.pack("<I", _HANDLE) + b"\xff" * 124)
    machine.mem_write(_CURSOR, struct.pack("<I", 3))
    _execute(machine)
    assert struct.unpack("<I", machine.mem_read(slot, 4))[0] == (0 if fault else _HANDLE)
    assert machine.mem_read(_CURSOR, 4) == struct.pack("<I", 3)
    if not fault:
        flags = sum(1 << index for index in range(94) if index % 3 == 0)
        assert machine.mem_read(slot + 16, 96) == flags.to_bytes(96, "little")


def _full_cache() -> None:
    machine, _calls = _machine("F_ARIAL_T10.BMP", 0)
    for index in range(64):
        machine.mem_write(_CACHE + index * FONT_BANK_CACHE_STRIDE, struct.pack("<I", 500 + index))
    machine.mem_write(_CURSOR, struct.pack("<I", 63))
    _execute(machine)
    assert machine.mem_read(_CURSOR, 4) == bytes(4)
    assert machine.mem_read(_CACHE + 63 * FONT_BANK_CACHE_STRIDE, 4) == struct.pack("<I", _HANDLE)
    assert machine.mem_read(_CACHE + FONT_BANK_CACHE_SIZE, 64) == bytes(64)


def _glyph_records(name: str) -> None:
    layout = font_bank_layout(name)
    assert layout is not None
    machine, _calls = _machine(name, 0)
    _execute(machine)
    machine.mem_write(_CODE + 0x800, _RUNTIME.glyph_record(_CODE + 0x800))
    boundaries = [1]
    for index in range(layout.glyph_count):
        boundaries.append(boundaries[-1] + 1 + index % 7)
    machine.mem_write(_FONT + 0x50, struct.pack(f"<{len(boundaries)}H", *boundaries))
    output = _FONT + 0x400
    # Selecting every slot exercises storage rows, unequal advances and the
    # final slot independently of which real font glyphs pass outline gates.
    machine.mem_write(_CACHE + 16, ((1 << layout.glyph_count) - 1).to_bytes(96, "little"))
    for index in range(layout.glyph_count):
        registers = {
            **_REGISTERS,
            UC_X86_REG_EAX: index,
            UC_X86_REG_EDX: _FONT,
            UC_X86_REG_ECX: output,
        }
        for register, value in registers.items():
            machine.reg_write(register, value)
        machine.mem_write(output, b"\xff" * 20)
        machine.emu_start(_CODE + 0x800, _STOP, count=2000)
        advance = boundaries[index + 1] - boundaries[index]
        left, top, _right, _bottom = layout.glyph_rect(index, advance)
        expected = (boundaries[index], left + 1 - boundaries[index], top, advance, _CACHE)
        assert struct.unpack("<5i", machine.mem_read(output, 20)) == expected
        for register, value in registers.items():
            wanted = (
                1
                if register == UC_X86_REG_EAX
                else value + (4 if register == UC_X86_REG_ESP else 0)
            )
            assert machine.reg_read(register) == wanted
    _rejected_records(machine, layout.glyph_count)


def _rejected_records(machine: Uc, glyph_count: int) -> None:
    font = bytes(machine.mem_read(_FONT, 0x300))
    cache = bytes(machine.mem_read(_CACHE, FONT_BANK_CACHE_SIZE))
    output = _FONT + 0x400
    mutations = (
        (_FONT + 4, struct.pack("<I", 0), 1),
        (_FONT + 4, struct.pack("<I", _HANDLE + 1), 1),
        (_FONT + 0x34, bytes(4), 1),
        (_FONT + 0x38, bytes(4), 1),
        (_FONT + 0x54, bytes(2), 1),
        (_FONT + 0x54, b"\xff\xff", 1),
        (_FONT + 0x54, struct.pack("<H", 50), 1),
        (_CACHE + 16, b"\xfd", 1),  # Clear only slot 1, leaving its neighbors set.
        (_CACHE + 16, b"\x01", 1),  # Another selected slot must not admit this one.
        (_FONT + 4, struct.pack("<I", _HANDLE), glyph_count),
        (_FONT + 4, struct.pack("<I", _HANDLE), max(glyph_count, 255)),
        (_FONT + 4, struct.pack("<I", _HANDLE), 256),
        (_FONT + 4, struct.pack("<I", _HANDLE), 0xFFFFFFFF),
    )
    for address, data, index in mutations:
        machine.mem_write(_FONT, font)
        machine.mem_write(_CACHE, cache)
        machine.mem_write(address, data)
        machine.mem_write(output, b"\xff" * 20)
        registers = {
            **_REGISTERS,
            UC_X86_REG_EAX: index,
            UC_X86_REG_EDX: _FONT,
            UC_X86_REG_ECX: output,
        }
        for register, value in registers.items():
            machine.reg_write(register, value)
        machine.emu_start(_CODE + 0x800, _STOP, count=2000)
        assert machine.mem_read(output, 20) == b"\xff" * 20
        for register, value in registers.items():
            wanted = (
                0
                if register == UC_X86_REG_EAX
                else value + (4 if register == UC_X86_REG_ESP else 0)
            )
            assert machine.reg_read(register) == wanted


@pytest.mark.slow
def test_native_font_bank_registration() -> None:
    # Unicorn's handled Windows memory probes otherwise trigger pytest's
    # faulthandler. A child process also makes an actual native crash fail here.
    subprocess.run(  # noqa: S603 - fixed interpreter and own test module.
        [sys.executable, str(Path(__file__).resolve())],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )


if __name__ == "__main__":
    # Exercise the format's upper bound, including bit 255, without shipping an
    # unverified font recipe. Existing metadata/cache canaries apply unchanged.
    FONT_PADDED_BANK_LAYOUTS["TEST256.BMP"] = FontBankLayout((1181, 18), 14, 256)
    try:
        _accepted("TEST256.BMP", 0)
        _glyph_records("TEST256.BMP")
        _last_flag_rejected("TEST256.BMP")
    finally:
        del FONT_PADDED_BANK_LAYOUTS["TEST256.BMP"]
    for _name in ("F_ARIAL_T8.BMP", "F_TOOLTIP.BMP"):
        for _ink in (0, 0xD800B0, 0xF8FCF8):
            _accepted(_name, _ink)
        _glyph_records(_name)
        _last_flag_rejected(_name)
    for _fault in (
        "signature",
        "second-word",
        "anchors",
        "nonbinary",
        "width",
        "height",
        "rows",
        "handle",
    ):
        _rejected(_fault)
    for _fault in ("", "width", "nonbinary"):
        _reused(_fault)
    _full_cache()
    for _name in ("F_NUM_TLARGE.BMP", "SID_TEXT_14.BMP", "SID_EMB_28.BMP"):
        _row_banks(_name)
    # Tempus now exercises four-row storage in the production catalog. Bound the
    # actual emitted code/table, not an extra, unused synthetic font entry.
    assert any(layout.line_count == 4 for layout in FONT_ROW_BANK_LAYOUTS.values())
    assert len(_RUNTIME.registration(_CODE, row_layouts_va=_STOP + 0x100)) <= 0x400
    assert len(font_row_layout_table() + font_padded_layout_table()) <= 0x500
