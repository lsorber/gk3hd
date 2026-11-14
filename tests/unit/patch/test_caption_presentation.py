"""Run final-page caption composition with observable graphics boundaries."""

from __future__ import annotations

import inspect
import struct

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_EFLAGS,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from tests.unit.patch.test_registry import _caption_compiler

_CODE, _STOP, _STACK, _OBJECT, _SURFACE, _BACK, _VTABLE, _CALL = range(0x820000, 0x828000, 0x1000)


def _stage_caption_queue(
    cpu: Uc, state: dict[str, int], *, count: int, ready: bool, scope: str
) -> None:
    compiler = _caption_compiler()

    def write(address: int, *values: int) -> None:
        cpu.mem_write(address, struct.pack(f"<{len(values)}I", *values))

    write(state["queue_count_va"], count)
    write(state["destination_handle_va"], 99 if scope == "movie" else 17)
    write(state["room_presentation_active_va"], int(scope in {"room", "movie"}))
    write(state["modal_scope_va"], int(scope == "movie"))
    write(state["cache_ready_va"], int(ready))
    write(state["cache_object_count_va"], max(1, count))
    bounds = (20, 30, 80, 90)
    write(state["cache_generation_rect_va"], *bounds)
    write(state["cache_rect_va"], *bounds)
    for index in range(count):
        pointer = _OBJECT + index * 0x200
        write(pointer, compiler.profile.address("caption.vtable"))
        write(state["entries_va"] + index * compiler._entry_stride, pointer)
        write(
            state["entries_va"] + index * compiler._entry_stride + compiler._entry_destination,
            17,
        )
        write(
            state["entries_va"] + index * compiler._entry_stride + compiler._entry_scaled_rect,
            *bounds,
        )
        write(state["cache_objects_va"] + index * 4, pointer)


def _compose(
    *, count: int, ready: bool, allocation_failure: bool = False, scope: str = "room"
) -> tuple[list[str], dict[str, int]]:
    compiler = _caption_compiler()
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x500000)
    state = {
        name: 0x800000 + index * 0x200
        for index, name in enumerate(inspect.signature(compiler._build_presenter).parameters)
    }
    state["wrapper_va"] = _CODE

    def write(address: int, *values: int) -> None:
        cpu.mem_write(address, struct.pack(f"<{len(values)}I", *values))

    def read(address: int) -> int:
        return struct.unpack("<I", cpu.mem_read(address, 4))[0]

    cpu.mem_write(_CODE, compiler._build_presenter(**state))
    _stage_caption_queue(cpu, state, count=count, ready=ready, scope=scope)
    write(state["cache_surface_va"], _SURFACE)
    write(_SURFACE, _VTABLE)
    write(_BACK, _VTABLE)
    write(compiler.profile.address("transition.back_surface_ptr"), _BACK)
    write(compiler.profile.address("win32.IsBadReadPtr"), _CALL)
    write(_VTABLE + 0x1C, _CALL + 0x40)
    cpu.mem_write(_CALL, b"\x31\xc0\xc2\x08\x00")
    cpu.mem_write(_CALL + 0x40, b"\x31\xc0\xc2\x18\x00")
    cpu.mem_write(state["cache_ensure_helper_va"], b"\x31\xc0\xc3")
    draw = compiler.profile.address("caption.draw")
    cpu.mem_write(draw, b"\x31\xc0\xc2\x08\x00")

    # Nonzero prior borrowed pointers must be withdrawn even for an empty queue.
    write(state["active_object_va"], _OBJECT)
    write(state["active_clip_va"], _OBJECT + 0x40)
    events: list[str] = []
    preserved = {
        UC_X86_REG_EAX: 11,
        UC_X86_REG_EBX: 13,
        UC_X86_REG_ECX: 17,
        UC_X86_REG_EDX: 19,
        UC_X86_REG_ESI: 23,
        UC_X86_REG_EDI: 29,
        UC_X86_REG_EFLAGS: 0x246,
    }
    for register, value in preserved.items():
        cpu.reg_write(register, value)
    cpu.reg_write(UC_X86_REG_ESP, _STACK + 0x800)
    write(_STACK + 0x800, _STOP)

    def observe(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address == _STOP:
            machine.emu_stop()
        elif address == state["cache_ensure_helper_va"]:
            events.append("allocate")
            assert allocation_failure, "Caption composition unexpectedly rebuilt its cache"
        elif address == _CALL + 0x40:
            events.append("replay")
            esp = machine.reg_read(UC_X86_REG_ESP)
            assert read(esp + 4) == _BACK
            assert read(esp + 16) == _SURFACE
            assert read(esp + 20) == state["cache_rect_va"]
        elif address == draw:
            events.append("native")
            assert read(state["active_object_va"]) == machine.reg_read(UC_X86_REG_ECX)

    cpu.hook_add(UC_HOOK_CODE, observe)
    cpu.emu_start(_CODE, _STOP + 1, count=10000)
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 0x804
    for register, value in preserved.items():
        assert cpu.reg_read(register) == value
    outputs = {
        name: read(state[name])
        for name in (
            "queue_count_va",
            "active_object_va",
            "active_clip_va",
            "cache_ready_va",
            "cache_build_count_va",
            "cache_replay_count_va",
            "present_count_va",
        )
    }
    return events, outputs


@pytest.mark.parametrize("ready", [False, True])
@pytest.mark.parametrize("scope", ["room", "movie", "none"])
def test_empty_caption_queue_does_no_graphics_work(ready: bool, scope: str) -> None:
    """Expired/absent captions neither allocate nor clear or replay old pixels."""
    events, state = _compose(count=0, ready=ready, scope=scope)
    assert events == []
    assert state["queue_count_va"] == state["active_object_va"] == state["active_clip_va"] == 0
    assert state["cache_ready_va"] == int(ready)
    assert state["cache_build_count_va"] == state["cache_replay_count_va"] == 0


@pytest.mark.parametrize("count", [1, 2, 3])
@pytest.mark.parametrize("scope", ["room", "movie"])
def test_live_caption_cache_replays_once_on_the_current_page(count: int, scope: str) -> None:
    """A live immutable generation remains visible and consumes its queue."""
    events, state = _compose(count=count, ready=True, scope=scope)
    assert events == ["replay"]
    assert state["cache_replay_count_va"] == 1
    assert state["present_count_va"] == count
    assert state["queue_count_va"] == state["active_object_va"] == state["active_clip_va"] == 0


@pytest.mark.parametrize("count", [1, 2, 3])
@pytest.mark.parametrize("scope", ["room", "movie"])
def test_caption_cache_failure_keeps_same_frame_native_drawing(count: int, scope: str) -> None:
    """Failure to create an isolated cache never drops nonempty captions."""
    events, state = _compose(count=count, ready=False, allocation_failure=True, scope=scope)
    assert events == ["allocate", *(["native"] * count)]
    assert state["present_count_va"] == count
    assert state["cache_replay_count_va"] == 0
    assert state["queue_count_va"] == state["active_object_va"] == state["active_clip_va"] == 0
