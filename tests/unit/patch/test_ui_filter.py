"""Exercise the explicit opaque-art filtering adapter and native fallbacks."""

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
    UC_X86_REG_EIP,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.runtime2d.ui_filter import (
    CACHE_OFFSET,
    CALL_COUNT_OFFSET,
    FILTER_IMAGES,
    HANDLED_COUNT_OFFSET,
    NAMES_OFFSET,
    RESOURCE_MATCH_OFFSET,
    SURFACE_MATCH_OFFSET,
    WRAPPER_OFFSET,
    build_area_adapter,
)
from gk3hd.patch.definitions.runtime2d.ui_frames import build_resource_match, build_surface_match

BASE = 0x800000
DATA = 0x900000
SOURCE = DATA + 0x200
DESTINATION = DATA + 0x400
DEST_RECT = DATA + 0x600
SOURCE_RECT = DATA + 0x700
STACK = 0xA00F00
STOP = 0x830000
MODULE = 0x820000
RESOLVE = 0x820100
EXPORT = 0x820200
NATIVE = 0x820300
# One resource in this fixture, with a bounded scan of the complete catalog.
# Allow the dimension/entry instructions and at most 16 instructions per name
# byte; a fixed 10,000 cap cut off valid late matches as the catalog grew.
INSTRUCTION_BUDGET = 2000 + sum(16 * (len(name) + 1) + 16 for name, _, _ in FILTER_IMAGES)
REGISTERS = {
    UC_X86_REG_EAX: 0x12345678,
    UC_X86_REG_ECX: DESTINATION,
    UC_X86_REG_EDX: 0x23456789,
    UC_X86_REG_EBX: 0x3456789A,
    UC_X86_REG_ESI: 0x456789AB,
    UC_X86_REG_EDI: 0x56789ABC,
    UC_X86_REG_EBP: 0x6789ABCD,
    UC_X86_REG_EFLAGS: 0x246,
}
CASES = (
    "std",
    "hov",
    "dwn",
    "unmarked-std",
    "unmarked-hov",
    "unmarked-dwn",
    "tape-std",
    "tape-hov",
    "tape-dwn",
    "notepad-std",
    "notepad-hov",
    "notepad-dwn",
    # Sample the framed-document and menu-art paths, not every catalog alias.
    "document-I_CAPNSTASH_HOV",
    "lowercase",
    "opaque-fallback",
    "opaque-native-size",
    "opaque-wrong-size",
    "opaque-other",
    "wrong-name",
    "name-suffix",
    "native-size",
    "no-manager",
    "no-table",
    "empty-table",
    "different-surface",
    "keyed",
    "source-alpha",
    "dest-alpha",
    "no-source",
    "no-dest",
    "no-source-surface",
    "no-dest-surface",
    "no-source-rect",
    "no-dest-rect",
    "module-absent",
    "export-absent",
    "declined",
    "failed",
)


def _write(machine: Uc, address: int, *words: int) -> None:
    machine.mem_write(address, struct.pack(f"<{len(words)}I", *words))


def _words(machine: Uc, address: int, count: int) -> tuple[int, ...]:
    return struct.unpack(f"<{count}I", machine.mem_read(address, count * 4))


@pytest.mark.slow
def test_scoped_area_filter_preserves_native_contract() -> None:
    result = subprocess.run(  # noqa: S603 - fixed interpreter, own test module and enumerated case.
        [sys.executable, str(Path(__file__).resolve())],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _resource_name(case: str) -> str:
    state = case if case in ("std", "hov", "dwn") else "std"
    name = f"I_PASSPORTMOSDIS_{state.upper()}"
    for prefix, family in (
        ("unmarked-", "I_PASSPORTMOS_"),
        ("tape-", "I_ABBETAPE_"),
        ("notepad-", "I_NOTEBOOKGAB_"),
    ):
        if case.startswith(prefix):
            name = family + case.removeprefix(prefix).upper()
    if case.startswith("document-"):
        name = case.removeprefix("document-")
    if case == "wrong-name":
        name = "I_UNREGISTERED_STD"
        assert name.lower().encode() not in {entry[0] for entry in FILTER_IMAGES}
    if case == "name-suffix":
        name += "_EXTRA"
    if case == "lowercase":
        name = name.lower()
    if case.startswith("opaque-"):
        name = "OTHER9" if case == "opaque-other" else "UNDEFINED9"
    return name


def _machine(case: str) -> Uc:
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    for start, size in ((BASE, 0x40000), (DATA, 0x10000), (0xA00000, 0x10000), (0x660000, 0xB0000)):
        machine.mem_map(start, size)
    machine.mem_write(
        BASE + WRAPPER_OFFSET, build_area_adapter(profile=GOG_BUILD, base_va=BASE, native_va=NATIVE)
    )
    machine.mem_write(
        BASE + SURFACE_MATCH_OFFSET,
        build_surface_match(
            wrapper_va=BASE + SURFACE_MATCH_OFFSET,
            resource_match_va=BASE + RESOURCE_MATCH_OFFSET,
            manager_va=GOG_BUILD.address("resource.manager"),
            images=FILTER_IMAGES,
        ),
    )
    machine.mem_write(
        BASE + RESOURCE_MATCH_OFFSET,
        build_resource_match(wrapper_va=BASE + RESOURCE_MATCH_OFFSET, images=FILTER_IMAGES),
    )
    machine.mem_write(BASE + NAMES_OFFSET, b"ddraw.dll\0".ljust(16, b"\0") + b"Gk3hdAreaBlt565\0")
    for address, size in ((MODULE, 4), (RESOLVE, 8), (EXPORT, 4), (NATIVE, 12)):
        machine.mem_write(address, b"\xc2" + struct.pack("<H", size))
    _write(machine, GOG_BUILD.address("win32.GetModuleHandleA"), MODULE)
    _write(machine, GOG_BUILD.address("win32.GetProcAddress"), RESOLVE)
    _write(machine, GOG_BUILD.address("resource.manager"), 0 if case == "no-manager" else DATA)
    _write(
        machine,
        DATA + 0x120,
        0 if case == "no-table" else DATA + 0x1000,
        int(case != "empty-table"),
    )
    _write(machine, DATA + 0x1000, DATA + 0x1100)
    _write(machine, DATA + 0x1130, SOURCE + (0x80 if case == "different-surface" else 0))
    machine.mem_write(DATA + 0x1108, _resource_name(case).encode() + b"\0")
    extent = 376 if case.startswith("opaque-") else 128
    actual_extent = {"native-size": 32, "opaque-native-size": 94, "opaque-wrong-size": 128}.get(
        case, extent
    )
    _write(machine, SOURCE + 0x38, actual_extent, actual_extent)
    _write(machine, SOURCE + 4, {"keyed": 1, "source-alpha": 8}.get(case, 0))
    _write(machine, DESTINATION + 4, 8 if case == "dest-alpha" else 0)
    _write(machine, SOURCE + 0x2C, 0 if case == "no-source-surface" else 0x920000)
    _write(machine, DESTINATION + 0x2C, 0 if case == "no-dest-surface" else 0x920100)
    _write(machine, DEST_RECT, 657, 390, 690, 423)
    _write(machine, SOURCE_RECT, 0, 0, extent, extent)
    return machine


def _exercise(case: str) -> None:
    machine = _machine(case)
    extent = 376 if case.startswith("opaque-") else 128
    calls = {MODULE: 0, RESOLVE: 0, EXPORT: 0, NATIVE: 0}
    registers = REGISTERS | ({UC_X86_REG_ECX: 0} if case == "no-dest" else {})
    args = (
        0 if case == "no-source" else SOURCE,
        0 if case == "no-dest-rect" else DEST_RECT,
        0 if case == "no-source-rect" else SOURCE_RECT,
    )

    def observe(uc: Uc, address: int, _size: int, _data: object) -> None:
        if address not in calls:
            return
        calls[address] += 1
        stack = uc.reg_read(UC_X86_REG_ESP)
        if address == MODULE:
            assert _words(uc, stack + 4, 1) == (BASE + NAMES_OFFSET,)
            uc.reg_write(UC_X86_REG_EAX, 0 if case == "module-absent" else 0x710000)
        elif address == RESOLVE:
            assert _words(uc, stack + 4, 2) == (0x710000, BASE + NAMES_OFFSET + 16)
            uc.reg_write(UC_X86_REG_EAX, 0 if case == "export-absent" else EXPORT)
        elif address == EXPORT:
            request = _words(uc, stack + 4, 1)[0]
            assert _words(uc, request, 12) == (
                48,
                0x920100,
                0x920000,
                657,
                390,
                690,
                423,
                0,
                0,
                extent,
                extent,
                0x80004005,
            )
            _write(uc, request + 44, 0x887601C2 if case == "failed" else 0)
            uc.reg_write(UC_X86_REG_EAX, int(case != "declined"))
        else:
            assert stack == STACK
            assert _words(uc, stack + 4, 3) == args
            assert all(uc.reg_read(reg) == value for reg, value in registers.items())

    machine.hook_add(UC_HOOK_CODE, observe)
    for _ in range(2):
        _write(machine, STACK, STOP, *args)
        for register, value in registers.items():
            machine.reg_write(register, value)
        machine.reg_write(UC_X86_REG_ESP, STACK)
        machine.emu_start(BASE + WRAPPER_OFFSET, STOP, count=INSTRUCTION_BUDGET)
        assert machine.reg_read(UC_X86_REG_EIP) == STOP
        assert machine.reg_read(UC_X86_REG_ESP) == STACK + 16
        handled = case.startswith(("unmarked-", "tape-", "document-", "notepad-")) or case in (
            "std",
            "hov",
            "dwn",
            "lowercase",
            "opaque-fallback",
            "failed",
        )
        expected = registers | ({UC_X86_REG_EAX: int(case != "failed")} if handled else {})
        assert all(machine.reg_read(reg) == value for reg, value in expected.items())
        assert _words(machine, DEST_RECT, 4) == (657, 390, 690, 423)
        assert _words(machine, SOURCE_RECT, 4) == (0, 0, extent, extent)
    export = case.startswith(("unmarked-", "tape-", "document-", "notepad-")) or case in (
        "std",
        "hov",
        "dwn",
        "lowercase",
        "opaque-fallback",
        "declined",
        "failed",
    )
    assert calls[EXPORT] == (2 if export else 0)
    assert calls[NATIVE] == (0 if handled else 2)
    assert _words(machine, BASE + CALL_COUNT_OFFSET, 1) == (calls[EXPORT],)
    assert _words(machine, BASE + HANDLED_COUNT_OFFSET, 1) == (2 if handled else 0,)
    assert _words(machine, BASE + CACHE_OFFSET, 1) == (
        EXPORT if export else 0xFFFFFFFF if case == "export-absent" else 0,
    )
    assert calls[RESOLVE] == int(export or case == "export-absent")
    assert calls[MODULE] == (
        2 if case == "module-absent" else int(export or case == "export-absent")
    )


if __name__ == "__main__":
    for case in CASES:
        try:
            _exercise(case)
        except AssertionError as error:
            error.add_note(f"filter case: {case}")
            raise
