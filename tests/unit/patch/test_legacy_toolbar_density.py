"""Execute exact native UI identity and dimension contracts for legacy buttons."""

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
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.definitions.runtime2d.ui_frames import build_resource_match
from gk3hd.textures.upscale.thumbnail_recipes import FRAMED_THUMBNAIL_SIZES
from gk3hd.textures.upscale.ui_art import (
    LEGACY_DOCUMENT_SIZES,
    LEGACY_TOOLBAR_ART_SIZES,
    QUIT_BUTTON_SIZES,
)


@pytest.mark.slow
def test_legacy_buttons_require_exact_names_and_fourfold_dimensions() -> None:
    subprocess.run(  # noqa: S603 - fixed interpreter and own test module.
        [sys.executable, str(Path(__file__).resolve())],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _case(name: str, size: tuple[int, int], variant: str) -> None:
    code, resource, surface, stack, stop = 0x800000, 0x810000, 0x820000, 0x830000, 0x840000
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x800000, 0x50000)
    cpu.mem_write(code, build_resource_match(wrapper_va=code))
    identity = name.removesuffix(".BMP")
    if variant == "case":
        identity = identity.lower()
    elif variant == "suffix":
        identity += "X"
    cpu.mem_write(resource + 8, identity.encode() + b"\0nonzero trailing bytes")
    width, height = (value * 4 for value in size)
    if variant == "width":
        width += 1
    elif variant == "height":
        height += 1
    elif variant == "native":
        width, height = size
    cpu.mem_write(surface + 0x38, struct.pack("<II", width, height))
    cpu.mem_write(stack, struct.pack("<I", stop))
    registers = {
        UC_X86_REG_EAX: surface,
        UC_X86_REG_ESI: resource,
        UC_X86_REG_EBX: 123,
        UC_X86_REG_ECX: 456,
        UC_X86_REG_EDX: 789,
        UC_X86_REG_EDI: 321,
        UC_X86_REG_EBP: 654,
    }
    for register, value in registers.items():
        cpu.reg_write(register, value)
    cpu.reg_write(UC_X86_REG_ESP, stack)
    cpu.emu_start(code, stop, count=20000)
    assert bool(cpu.reg_read(UC_X86_REG_EFLAGS) & 1) == (variant in {"match", "case"})
    assert all(cpu.reg_read(register) == value for register, value in registers.items())
    assert cpu.reg_read(UC_X86_REG_ESP) == stack + 4


if __name__ == "__main__":
    _note_sizes = {
        name: FRAMED_THUMBNAIL_SIZES[name] for name in ("SNOTE.BMP", "SNOTE_HOV.BMP", "SNOTED.BMP")
    }
    for _name, _size in (
        LEGACY_TOOLBAR_ART_SIZES | QUIT_BUTTON_SIZES | _note_sizes | LEGACY_DOCUMENT_SIZES
    ).items():
        for _variant in ("match", "case", "suffix", "width", "height", "native"):
            _case(_name, _size, _variant)
