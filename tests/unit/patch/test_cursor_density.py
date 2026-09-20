"""Execute animated-cursor identity, source-density, clipping and ABI contracts."""

from __future__ import annotations

import struct
import subprocess
import sys
from itertools import product
from pathlib import Path
from typing import TYPE_CHECKING

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

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameABI
from gk3hd.patch.definitions.runtime2d.layout import (
    BINOCULAR_SEGMENT,
    CURSOR_DENSITY_PROBE_OFFSET,
    CURSOR_RESOURCE_MATCH_OFFSET,
    RuntimeSymbols,
)
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.system import SystemScreenCompiler
from gk3hd.patch.definitions.runtime2d.system.cursor_density import (
    build_density_probe,
    build_resource_match,
)
from gk3hd.textures.upscale.cursor_art import CURSOR_ART_FRAMES

if TYPE_CHECKING:
    from gk3hd.patch.definitions.runtime2d.system.cursor import CursorFeatureCompiler

_CODE, _STATE, _PROBE = 0x800000, 0x801000, 0x803000
_SOURCE, _DEST, _RECT, _DRAWABLE, _RESOURCE = 0x804000, 0x805000, 0x806000, 0x807000, 0x808000
_STACK, _STOP = 0x900000, 0x810000


def _put(cpu: Uc, address: int, *values: int) -> None:
    cpu.mem_write(address, struct.pack("<" + "i" * len(values), *values))


def _get(cpu: Uc, address: int, count: int) -> tuple[int, ...]:
    return struct.unpack("<" + "i" * count, cpu.mem_read(address, count * 4))


@pytest.mark.slow
def test_dense_frames_keep_logical_geometry_and_original_caller_rect() -> None:
    # Unicorn handles Windows JIT access violations internally; keep those
    # expected exceptions outside pytest's process-wide fatal-error handler.
    subprocess.run(  # noqa: S603 - fixed interpreter and own test module.
        [sys.executable, str(Path(__file__).resolve())],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_shared_cursor_contracts_fit_reserved_runtime_slots() -> None:
    matcher = build_resource_match(wrapper_va=_PROBE + 0x400)
    probe = build_density_probe(
        wrapper_va=_PROBE,
        manager_va=GOG_BUILD.address("resource.manager"),
        resolve_va=GOG_BUILD.address("bitmap.resolve_resource"),
        match_va=_PROBE + 0x400,
    )
    assert len(matcher) <= BINOCULAR_SEGMENT.size - CURSOR_RESOURCE_MATCH_OFFSET
    assert len(probe) <= CURSOR_RESOURCE_MATCH_OFFSET - CURSOR_DENSITY_PROBE_OFFSET


def _machine(feature: CursorFeatureCompiler) -> Uc:
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x600000)
    cpu.mem_write(
        _CODE,
        feature.build_cursor_final_wrapper(
            wrapper_va=_CODE,
            cursor_state_va=_STATE,
            density_probe_va=_PROBE,
            blend_wrapper_va=feature._native_final_stretch_blt_va,
            cursor_transform_count_va=0x802000,
            cursor_presented_source_rect_va=0x801100,
            cursor_display_blt_count_va=0x802004,
            cursor_display_blt_result_va=0x802008,
        ),
    )
    resolver = GOG_BUILD.address("bitmap.resolve_resource")
    manager_va = GOG_BUILD.address("resource.manager")
    cpu.mem_write(
        _PROBE,
        build_density_probe(
            wrapper_va=_PROBE, manager_va=manager_va, resolve_va=resolver, match_va=_PROBE + 0x400
        ),
    )
    cpu.mem_write(_PROBE + 0x400, build_resource_match(wrapper_va=_PROBE + 0x400))
    cpu.mem_write(resolver, b"\xb8" + struct.pack("<I", _RESOURCE) + b"\xc2\x04\x00")
    _put(cpu, manager_va, 0x809000)
    return cpu


def _run_case(name: str, height: int, frame: int, point: tuple[int, int], variant: str) -> None:
    width, frame_height, frames = CURSOR_ART_FRAMES[name]
    point = (point[0], min(point[1], height - 18))
    feature = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=0x790004, height_va=0x790008),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x791000,
            room_presentation_active_va=0x791008,
            pre_flip_presenter_slot_va=0x791004,
            post_flip_presenter_slot_va=0x79100C,
        ),
    ).cursor_feature()
    cpu = _machine(feature)
    cpu.mem_write(
        _RESOURCE + 8,
        name.removesuffix(".BMP").encode() + (b"X" if variant == "other" else b"\0"),
    )
    _put(cpu, _RESOURCE + 0x30, _SOURCE + (0x100 if variant == "surface" else 0))
    _put(cpu, _DRAWABLE + 0x20, 123, width, frame_height, frames - int(variant == "count"))
    _put(cpu, _STATE + 152, _DRAWABLE)
    _put(cpu, feature._physical_width_va, 1024, height)
    origin = frame * width
    _put(cpu, _STATE, *point, origin, 0, origin + width, frame_height)
    _put(cpu, _STATE + 76, int(variant != "unscoped"))
    actual_density = 1 if variant == "native" else 4
    _put(cpu, _SOURCE + 0x38, width * frames * actual_density, frame_height * actual_density)
    _put(cpu, _DEST + 0x38, 1024, height)
    fragment = (origin + 1, 1, origin + width - 1, frame_height - 1)
    _put(cpu, _RECT, *fragment)
    _put(cpu, _STACK, _STOP, _SOURCE, *point, _RECT, 0x809100)
    registers = {
        UC_X86_REG_EBX: 123,
        UC_X86_REG_ESI: 456,
        UC_X86_REG_EDI: 789,
        UC_X86_REG_EBP: 321,
        UC_X86_REG_ECX: _DEST,
    }
    for register, value in registers.items():
        cpu.reg_write(register, value)
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    stretch = variant != "unscoped" and (variant == "dense" or height > 768)
    calls = []

    def inspect_call(machine: Uc, address: int, _size: int, _data: object) -> None:
        if address == feature._native_mid_blt_va:
            calls.append("native")
            machine.emu_stop()
        if address == feature._native_final_stretch_blt_va:
            _return, source, dest_rect, source_rect, options = _get(
                machine, machine.reg_read(UC_X86_REG_ESP), 5
            )
            assert (source, options) == (_SOURCE, 0x809100)
            dest = [
                point[i % 2]
                + ((fragment[i] - (origin if i % 2 == 0 else 0)) * max(height, 768) + 384) // 768
                for i in range(4)
            ]
            sampled = list(fragment)
            for axis, extent in ((0, 1024), (1, height)):
                if dest[axis] < 0:
                    sampled[axis] += (-dest[axis] * 768 + max(height, 768) - 1) // max(height, 768)
                    dest[axis] = 0
                if dest[axis + 2] > extent:
                    sampled[axis + 2] -= (
                        (dest[axis + 2] - extent) * 768 + max(height, 768) - 1
                    ) // max(height, 768)
                    dest[axis + 2] = extent
            density = 4 if variant == "dense" else 1
            assert _get(machine, dest_rect, 4) == tuple(dest)
            assert _get(machine, source_rect, 4) == tuple(value * density for value in sampled)
            calls.append("stretch")

    cpu.mem_write(feature._native_final_stretch_blt_va, b"\xb8\x01\x00\x00\x00\xc2\x10\x00")
    cpu.hook_add(UC_HOOK_CODE, inspect_call)
    cpu.emu_start(_CODE, _STOP, count=3000)
    assert calls == (["stretch"] if stretch else ["native"])
    assert _get(cpu, _RECT, 4) == fragment
    assert all(cpu.reg_read(register) == value for register, value in registers.items())
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + (24 if stretch else 0)
    assert not stretch or cpu.reg_read(UC_X86_REG_EAX) == 1


def _match_case(name: str, variant: str) -> None:
    width, height, frames = CURSOR_ART_FRAMES[name]
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x800000, 0x200000)
    cpu.mem_write(_CODE, build_resource_match(wrapper_va=_CODE))
    stem = name.removesuffix(".BMP").encode()
    identity = stem + b"X" if variant == "prefix" else stem
    if variant == "case":
        identity = identity.lower()
    cpu.mem_write(_RESOURCE + 8, identity + b"\0nonzero bytes after terminator")
    _put(cpu, _SOURCE + 0x38, width * frames * 4 + int(variant == "width"), height * 4)
    if variant == "height":
        _put(cpu, _SOURCE + 0x3C, height * 4 + 1)
    registers = {
        UC_X86_REG_EAX: 0 if variant == "null_surface" else _SOURCE,
        UC_X86_REG_ESI: 0 if variant == "null_resource" else _RESOURCE,
        UC_X86_REG_ECX: 123,
        UC_X86_REG_EDX: 456,
        UC_X86_REG_EBX: 789,
        UC_X86_REG_EDI: 234,
        UC_X86_REG_EBP: 567,
    }
    for register, value in registers.items():
        cpu.reg_write(register, value)
    _put(cpu, _STACK, _STOP)
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.emu_start(_CODE, _STOP, count=3000)
    assert bool(cpu.reg_read(UC_X86_REG_EFLAGS) & 1) == (variant == "match")
    if variant == "match":
        row = cpu.reg_read(UC_X86_REG_ECX)
        assert _get(cpu, row + 20, 4) == (width, height, frames, width * frames)
        registers.pop(UC_X86_REG_ECX)
    assert all(cpu.reg_read(register) == value for register, value in registers.items())
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 4


if __name__ == "__main__":
    # Single-frame and animated cursors, including clipping and first/last frames.
    representatives = {
        next(name for name, (_, _, frames) in CURSOR_ART_FRAMES.items() if frames == 1),
        max(CURSOR_ART_FRAMES, key=lambda name: CURSOR_ART_FRAMES[name][2]),
    }
    for cursor_name in sorted(representatives):
        frame_count = CURSOR_ART_FRAMES[cursor_name][2]
        for case in product(
            (768, 2160),
            sorted({0, frame_count - 1}),
            ((600, 400), (-3, -2)),
            ("dense", "native", "other", "count", "surface", "unscoped"),
        ):
            _run_case(cursor_name, *case)
        for match_variant in (
            "match",
            "prefix",
            "case",
            "width",
            "height",
            "null_surface",
            "null_resource",
        ):
            _match_case(cursor_name, match_variant)
