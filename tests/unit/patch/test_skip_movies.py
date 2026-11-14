"""Movie testing shortcuts preserve the caller ABI without waiting on decoders."""

from __future__ import annotations

import struct

import pytest
from unicorn import UC_HOOK_CODE, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.binary.operations import ReplaceBytes
from gk3hd.patch.builds import SUPPORTED_BUILDS, BuildProfile
from gk3hd.patch.definitions.engine import _skip_all_movies
from gk3hd.patch.model import BuildContext, CompilationContext, PatchId
from tests.unit.patch.test_complete_compilation import _source
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda value: str(value.id))
@pytest.mark.parametrize("codec", ["movies.update", "movies.avi_open"])
def test_each_codec_finishes_without_entering_its_blocking_decoder(
    profile: BuildProfile, codec: str
) -> None:
    image = _source(profile)
    context = CompilationContext(BuildContext(profile.id), frozenset({PatchId("skip_all_movies")}))
    for operation in _skip_all_movies(context):
        if isinstance(operation, ReplaceBytes):
            image.write_bytes(image.va_to_offset(operation.va), operation.replacement)
    machine = _machine(image)
    complete = profile.address("movies.complete")
    machine.mem_write(complete, b"\xc2\x04\x00")
    movie = _HEAP + 0x400
    machine.mem_write(movie, b"\x7f" * 96)
    machine.reg_write(UC_X86_REG_ECX, movie)
    machine.reg_write(UC_X86_REG_EAX, 0x123456FF)
    saved = {UC_X86_REG_EBX: 12, UC_X86_REG_ESI: 34, UC_X86_REG_EDI: 56, UC_X86_REG_EBP: 78}
    for register, value in saved.items():
        machine.reg_write(register, value)
    calls: list[tuple[int, int]] = []

    def observe(vm: Uc, address: int, _size: int, _data: object) -> None:
        if address == complete:
            flag = struct.unpack("<I", vm.mem_read(vm.reg_read(UC_X86_REG_ESP) + 4, 4))[0]
            calls.append((vm.reg_read(UC_X86_REG_ECX), flag))

    machine.hook_add(UC_HOOK_CODE, observe)
    machine.emu_start(profile.site(codec).va, _RETURN, count=50)
    assert calls == ([(movie, 1)] if codec == "movies.update" else [])
    assert machine.reg_read(UC_X86_REG_EAX) & 0xFF == 0
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + (4 if codec == "movies.update" else 8)
    assert {register: machine.reg_read(register) for register in saved} == saved
    if codec == "movies.avi_open":
        assert machine.mem_read(movie, 96) == b"\x7f" * 96
