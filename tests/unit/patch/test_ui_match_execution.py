"""Execute compact resource/size catalogs, including native rejection paths."""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

import pytest
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
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

from gk3hd.patch.definitions.runtime2d.ui_frames import (
    BLIT_ONLY_IMAGES,
    FONT_BUTTON_IMAGES,
    UI_IMAGES,
    build_bitmap_object_dimensions,
    build_blit_match,
    build_dimensions,
    build_resource_match,
    build_source,
    build_surface_match,
)

BASE = 0x800000
SURFACE_MATCH = BASE + 0x8000
STOP = BASE + 0x9000
RESOURCE = 0x900000
SURFACE = RESOURCE + 0x1000
MANAGER_SLOT = RESOURCE + 0x2000
MANAGER = RESOURCE + 0x3000
TABLE = RESOURCE + 0x4000
STACK = RESOURCE + 0xF000
REGISTERS = {
    UC_X86_REG_EAX: SURFACE,
    UC_X86_REG_ESI: RESOURCE,
    UC_X86_REG_EBX: 123,
    UC_X86_REG_ECX: 456,
    UC_X86_REG_EDX: 789,
    UC_X86_REG_EDI: 101,
    UC_X86_REG_EBP: 202,
}


@pytest.mark.parametrize("entry", [BASE, SURFACE_MATCH])
@pytest.mark.slow
def test_compact_ui_catalogs_preserve_exact_identity_and_registers(entry: int) -> None:
    subprocess.run(  # noqa: S603 - fixed interpreter, own test module, integer address.
        [sys.executable, str(Path(__file__).resolve()), str(entry)],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _write(machine: Uc, address: int, *words: int) -> None:
    machine.mem_write(address, struct.pack(f"<{len(words)}I", *words))


def _run(machine: Uc, entry: int, *, matches: bool) -> None:
    for register, value in REGISTERS.items():
        machine.reg_write(register, value)
    machine.reg_write(UC_X86_REG_ESP, STACK)
    machine.reg_write(UC_X86_REG_EFLAGS, 2)
    _write(machine, STACK, STOP)
    machine.emu_start(entry, STOP, count=30000)
    assert machine.reg_read(UC_X86_REG_EIP) == STOP
    assert bool(machine.reg_read(UC_X86_REG_EFLAGS) & 1) == matches, (
        bytes(machine.mem_read(RESOURCE + 8, 24)).split(b"\0", 1)[0],
        struct.unpack("<2I", machine.mem_read(SURFACE + 0x38, 8)),
        matches,
    )
    assert machine.reg_read(UC_X86_REG_ESP) == STACK + 4
    assert all(machine.reg_read(reg) == value for reg, value in REGISTERS.items())


def _exercise(entry: int) -> None:
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(BASE, 0x10000)
    machine.mem_map(RESOURCE, 0x10000)
    resource_match = build_resource_match(wrapper_va=BASE)
    surface_match = build_surface_match(
        wrapper_va=SURFACE_MATCH, resource_match_va=BASE, manager_va=MANAGER_SLOT
    )
    assert BASE + len(resource_match) <= SURFACE_MATCH
    assert SURFACE_MATCH + len(surface_match) < STOP
    machine.mem_write(BASE, resource_match)
    machine.mem_write(SURFACE_MATCH, surface_match)
    _write(machine, MANAGER_SLOT, MANAGER)
    _write(machine, MANAGER + 0x120, TABLE, 2)
    _write(machine, TABLE, 0, RESOURCE)
    _write(machine, RESOURCE + 0x30, SURFACE)
    accepted = {(name.lower(), width * 4, height * 4) for name, width, height in UI_IMAGES}
    for name, width, height in UI_IMAGES:
        for candidate, x, y in (
            (name, width * 4, height * 4),
            (name.upper(), width * 4, height * 4),
            (name + b"x", width * 4, height * 4),
            (name[:-1], width * 4, height * 4),
            (name, width, height),
            (name, width * 4 + 1, height * 4),
            (name, width * 4, height * 4 + 1),
            (name, width * 4 + 65536, height * 4),
        ):
            machine.mem_write(RESOURCE + 8, candidate + bytes(24 - len(candidate)))
            _write(machine, SURFACE + 0x38, x, y)
            # A shortened name can be another complete registered resource:
            # I_LSRPRINTGABE1 -> I_LSRPRINTGABE is a legitimate exact match.
            _run(machine, entry, matches=(candidate.lower(), x, y) in accepted)
    if entry == SURFACE_MATCH:
        # Surface address reuse must not retain a cached dense identity.
        machine.mem_write(RESOURCE + 8, b"unrelated\0")
        _run(machine, entry, matches=False)
        _write(machine, MANAGER_SLOT, 0)
        _run(machine, entry, matches=False)
    else:
        _exercise_logical_clips(machine)
        _exercise_blit_only(machine)


def _exercise_blit_only(machine: Uc) -> None:
    """Dense evidence previews must not change Inventory's shared getter."""
    extra, surface, combined = BASE + 0xB000, BASE + 0xC000, BASE + 0xC800
    dimensions, source_code = BASE + 0xD000, BASE + 0xD100
    bitmap_dimensions, native_dimensions = BASE + 0xD400, BASE + 0xD500
    logical, clip, destination, scratch, display = (
        RESOURCE + 0x5000,
        RESOURCE + 0x5100,
        RESOURCE + 0x5200,
        RESOURCE + 0x5300,
        RESOURCE + 0x5400,
    )
    machine.mem_write(extra, build_resource_match(wrapper_va=extra, images=BLIT_ONLY_IMAGES))
    machine.mem_write(
        surface,
        build_surface_match(
            wrapper_va=surface,
            resource_match_va=extra,
            manager_va=MANAGER_SLOT,
            images=BLIT_ONLY_IMAGES,
        ),
    )
    machine.mem_write(
        combined,
        build_blit_match(wrapper_va=combined, ui_match_va=SURFACE_MATCH, extra_match_va=surface),
    )
    machine.mem_write(
        dimensions, build_dimensions(wrapper_va=dimensions, match_va=BASE, logical_va=logical)
    )
    machine.mem_write(
        bitmap_dimensions,
        build_bitmap_object_dimensions(
            wrapper_va=bitmap_dimensions,
            dimensions_va=native_dimensions,
            surface_match_va=surface,
            logical_va=logical,
        ),
    )
    machine.mem_write(
        native_dimensions, b"\xb8" + struct.pack("<I", SURFACE + 0x38) + b"\xc2\x04\x00"
    )
    caller = 0x54F949
    machine.mem_write(
        source_code,
        build_source(
            wrapper_va=source_code,
            surface_match_va=combined,
            scratch_va=scratch,
            callers=(caller,),
            manager_va=MANAGER_SLOT,
            dimensions_va=display,
        ),
    )
    _write(machine, display, 1024, 768)
    assert not set(BLIT_ONLY_IMAGES).intersection(UI_IMAGES)
    for name, width, height in BLIT_ONLY_IMAGES:
        for candidate, density, matches in (
            (name, 4, True),
            (name.upper(), 4, True),
            (name, 1, False),
            (name + b"_OP", 4, False),
            (name + b"x", 4, False),
        ):
            machine.mem_write(RESOURCE + 8, candidate + bytes(32 - len(candidate)))
            _write(machine, SURFACE + 0x38, width * density, height * density)
            _run(machine, combined, matches=matches)
            _run(machine, BASE, matches=False)
            machine.reg_write(UC_X86_REG_ESP, STACK)
            _write(machine, STACK, STOP)
            machine.emu_start(dimensions, STOP, count=30000)
            assert machine.reg_read(UC_X86_REG_EAX) == SURFACE
            assert struct.unpack("<2I", machine.mem_read(SURFACE + 0x38, 8)) == (
                width * density,
                height * density,
            )
            machine.reg_write(UC_X86_REG_ESP, STACK)
            _write(machine, STACK, STOP, 123)
            machine.emu_start(bitmap_dimensions, STOP, count=30000)
            result = machine.reg_read(UC_X86_REG_EAX)
            assert result == (logical if matches else SURFACE + 0x38)
            expected_size = (width, height) if matches else (width * density, height * density)
            assert struct.unpack("<2I", machine.mem_read(result, 8)) == expected_size
            assert machine.reg_read(UC_X86_REG_ESP) == STACK + 8
            assert struct.unpack("<2I", machine.mem_read(SURFACE + 0x38, 8)) == (
                width * density,
                height * density,
            )
            for actual_caller in (caller, caller + 1):
                _write(machine, clip, 1, 2, width - 1, height - 2)
                _write(machine, destination, 234, 280, 234 + width, 280 + height)
                _write(machine, STACK, STOP, actual_caller, SURFACE, destination, clip)
                machine.reg_write(UC_X86_REG_ESP, STACK)
                machine.emu_start(source_code, STOP, count=30000)
                pointer = struct.unpack("<I", machine.mem_read(STACK + 16, 4))[0]
                dense = matches and actual_caller == caller
                assert pointer == (scratch if dense else clip)
                scale = 4 if dense else 1
                assert struct.unpack("<4I", machine.mem_read(pointer, 16)) == tuple(
                    value * scale for value in (1, 2, width - 1, height - 2)
                )
                assert struct.unpack("<4I", machine.mem_read(clip, 16)) == (
                    1,
                    2,
                    width - 1,
                    height - 2,
                )
                assert struct.unpack("<4I", machine.mem_read(destination, 16)) == (
                    234,
                    280,
                    234 + width,
                    280 + height,
                )
    _exercise_already_logical(machine, bitmap_dimensions, native_dimensions)


def _exercise_already_logical(machine: Uc, bitmap_dimensions: int, native_dimensions: int) -> None:
    """Reject scratch-pair results even when their dimensions resemble dense artwork."""
    # Another getter already returned logical scratch. Even dimensions that
    # resemble a dense preview must not divide again without live ownership.
    already_logical = RESOURCE + 0x5500
    _write(machine, already_logical, 376, 376)
    machine.mem_write(
        native_dimensions, b"\xb8" + struct.pack("<I", already_logical) + b"\xc2\x04\x00"
    )
    machine.ctl_remove_cache(native_dimensions, native_dimensions + 8)
    machine.reg_write(UC_X86_REG_ESP, STACK)
    _write(machine, STACK, STOP, 123)
    machine.emu_start(bitmap_dimensions, STOP, count=30000)
    assert machine.reg_read(UC_X86_REG_EAX) == already_logical
    assert struct.unpack("<2I", machine.mem_read(already_logical, 8)) == (376, 376)


def _exercise_logical_clips(machine: Uc) -> None:
    dimensions, source_code = BASE + 0xA000, BASE + 0xA100
    logical, clip, destination, scratch, display = (
        RESOURCE + 0x5000,
        RESOURCE + 0x5100,
        RESOURCE + 0x5200,
        RESOURCE + 0x5300,
        RESOURCE + 0x5400,
    )
    caller = 0x54F949
    machine.mem_write(
        dimensions, build_dimensions(wrapper_va=dimensions, match_va=BASE, logical_va=logical)
    )
    machine.mem_write(
        source_code,
        build_source(
            wrapper_va=source_code,
            surface_match_va=SURFACE_MATCH,
            scratch_va=scratch,
            callers=(caller,),
            manager_va=MANAGER_SLOT,
            dimensions_va=display,
        ),
    )
    _write(machine, display, 1024, 768)
    images = ((b"s_bkgnd", 640, 480), (b"s_main_scn", 640, 480), *FONT_BUTTON_IMAGES)
    for name, width, height in images:
        for density in (1, 4):
            machine.mem_write(RESOURCE + 8, name + bytes(32 - len(name)))
            _write(machine, SURFACE + 0x38, width * density, height * density)
            machine.reg_write(UC_X86_REG_EAX, SURFACE)
            machine.reg_write(UC_X86_REG_ESI, RESOURCE)
            machine.reg_write(UC_X86_REG_ESP, STACK)
            _write(machine, STACK, STOP)
            machine.emu_start(dimensions, STOP, count=30000)
            assert machine.reg_read(UC_X86_REG_EAX) == (logical if density == 4 else SURFACE)
            if density == 4:
                assert bytes(machine.mem_read(logical, 8)) == struct.pack("<2I", width, height)
            for native_caller in (caller, caller + 1):
                # Clip in the original coordinate domain, then expand only
                # the source. In particular a dense button must not be clipped
                # as a 4x rectangle and shrink the surviving fragment again.
                authored_clip = (1, height - 5, width - 1, height)
                authored_destination = (192, 614, 192 + width - 2, 619)
                _write(machine, clip, *authored_clip)
                _write(machine, destination, *authored_destination)
                _write(machine, STACK, STOP, native_caller, SURFACE, destination, clip)
                machine.reg_write(UC_X86_REG_ESP, STACK)
                machine.emu_start(source_code, STOP, count=30000)
                pointer = struct.unpack("<I", machine.mem_read(STACK + 16, 4))[0]
                dense = density == 4 and native_caller == caller
                assert pointer == (scratch if dense else clip)
                assert struct.unpack("<4I", machine.mem_read(pointer, 16)) == tuple(
                    value * (4 if dense else 1) for value in authored_clip
                )
                assert (
                    struct.unpack("<4I", machine.mem_read(destination, 16)) == authored_destination
                )
                assert struct.unpack("<4I", machine.mem_read(clip, 16)) == authored_clip


if __name__ == "__main__":
    _exercise(int(sys.argv[1]))
