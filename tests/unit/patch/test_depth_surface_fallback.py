"""Exercise the installed legacy depth retry with a failing graphics adapter."""

from __future__ import annotations

import struct

import pytest
from unicorn import UC_HOOK_CODE, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.binary.executor import OperationExecutor
from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.catalog import PLANNER
from gk3hd.patch.model import BuildContext, PatchId
from tests.unit.patch.test_complete_compilation import _source
from tests.unit.patch.test_vr_scene import _HEAP, _STACK, _machine

_VIDEO_DEPTH = 0x24000
_SYSTEM_DEPTH = 0x20800
_OUT_OF_VIDEO_MEMORY = 0x8876017C
_INVALID_ARGUMENT = 0x80070057


@pytest.mark.parametrize(
    ("caps", "results", "expected_caps"),
    [
        (_VIDEO_DEPTH, (0,), (_VIDEO_DEPTH,)),
        (_VIDEO_DEPTH, (_OUT_OF_VIDEO_MEMORY, 0), (_VIDEO_DEPTH, _SYSTEM_DEPTH)),
        (_VIDEO_DEPTH, (_OUT_OF_VIDEO_MEMORY, _INVALID_ARGUMENT), (_VIDEO_DEPTH, _SYSTEM_DEPTH)),
        (_VIDEO_DEPTH, (_INVALID_ARGUMENT,), (_VIDEO_DEPTH,)),
        (_SYSTEM_DEPTH, (_OUT_OF_VIDEO_MEMORY,), (_SYSTEM_DEPTH,)),
        (0x840, (_OUT_OF_VIDEO_MEMORY,), (0x840,)),
    ],
)
def test_depth_creation_retries_only_legacy_video_memory_exhaustion(
    caps: int, results: tuple[int, ...], expected_caps: tuple[int, ...]
) -> None:
    plan = PLANNER.plan_explicit(
        (PatchId("enable_modern_resolutions"),), BuildContext(GOG_BUILD.id)
    )
    image = OperationExecutor().execute(_source(GOG_BUILD), plan.compile_operations())
    site = GOG_BUILD.site("resolution.create_depth_surface")
    machine = _machine(image)
    interface, vtable, create, descriptor, output = (_HEAP + i * 0x100 for i in range(5))
    machine.mem_write(interface, struct.pack("<I", vtable))
    machine.mem_write(vtable + 0x18, struct.pack("<I", create))
    machine.mem_write(create, bytes.fromhex("c2 10 00"))  # COM callee pops four arguments.
    machine.mem_write(descriptor, struct.pack("<4I", 0x6C, 0x47, 2880, 5120))
    machine.mem_write(descriptor + 0x68, struct.pack("<I", caps))
    machine.mem_write(_STACK, struct.pack("<3I", output, 0, 1))
    machine.reg_write(UC_X86_REG_EAX, interface)
    machine.reg_write(UC_X86_REG_ECX, vtable)
    machine.reg_write(UC_X86_REG_EDX, descriptor)
    machine.reg_write(UC_X86_REG_ESI, 12)
    machine.reg_write(UC_X86_REG_EDI, 34)
    calls: list[int] = []

    def call(vm: Uc, address: int, _size: int, _data: object) -> None:
        if address != create:
            return
        stack = vm.reg_read(UC_X86_REG_ESP)
        assert struct.unpack("<4I", vm.mem_read(stack + 4, 16)) == (
            interface,
            descriptor,
            output,
            0,
        )
        assert struct.unpack("<4I", vm.mem_read(descriptor, 16)) == (0x6C, 0x47, 2880, 5120)
        result = results[len(calls)]
        calls.append(struct.unpack("<I", vm.mem_read(descriptor + 0x68, 4))[0])
        if result == 0:
            vm.mem_write(output, struct.pack("<I", 0x1234))
        vm.reg_write(UC_X86_REG_EAX, result)
        vm.reg_write(UC_X86_REG_ECX, 0)
        vm.reg_write(UC_X86_REG_EDX, 0)

    machine.hook_add(UC_HOOK_CODE, call)
    machine.emu_start(site.va, site.va + len(site.original), count=80)
    assert tuple(calls) == expected_caps
    assert machine.reg_read(UC_X86_REG_EAX) == results[-1]
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 8
    assert machine.reg_read(UC_X86_REG_ESI) == 12
    assert machine.reg_read(UC_X86_REG_EDI) == 34
    assert machine.mem_read(descriptor + 0x68, 4) == struct.pack("<I", caps)
    assert machine.mem_read(output, 4) == struct.pack("<I", 0x1234 if results[-1] == 0 else 0)
