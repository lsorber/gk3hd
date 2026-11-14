"""VR mirror settings never overwrite flat resolution and fullscreen choices."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.builds import GOG_BUILD, SUPPORTED_BUILDS
from gk3hd.patch.definitions.vr_mirror import VRMirrorCompiler
from gk3hd.patch.model import PatchError
from tests.unit.patch.test_complete_compilation import _source
from tests.unit.patch.test_vr_scene import _HEAP, _STACK, _machine

if TYPE_CHECKING:
    from unicorn import Uc

    from gk3hd.patch.builds import BuildProfile


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
def test_guard_verifies_dormant_for_every_supported_build(profile: BuildProfile) -> None:
    image = _source(profile)
    compiler = VRMirrorCompiler(profile=profile)
    compiler.apply(image)
    compiler.postcheck(image)
    assert image.read_u32_va(compiler.abi(image).enabled_va) == 0
    with pytest.raises(PatchError, match="already installed"):
        compiler.apply(image)


@pytest.mark.parametrize("changed", ["entry", "before", "after"])
@pytest.mark.parametrize("name", ["vr.mirror_preferences", "vr.windowed_gamma_query"])
def test_unrecognized_context_is_rejected_without_mutation(changed: str, name: str) -> None:
    image = _source(GOG_BUILD)
    site = GOG_BUILD.site(name)
    address = {
        "entry": site.va,
        "before": site.va - 1,
        "after": site.va + len(site.original),
    }[changed]
    image.write_bytes(image.va_to_offset(address), b"\x01")
    before = image.to_bytes()
    with pytest.raises(PatchError):
        VRMirrorCompiler(profile=GOG_BUILD).apply(image)
    assert image.to_bytes() == before


@pytest.mark.parametrize("changed", ["payload", "hook", "continuation", "active"])
@pytest.mark.parametrize("name", ["vr.mirror_preferences", "vr.windowed_gamma_query"])
def test_changed_guard_is_rejected(changed: str, name: str) -> None:
    image = _source(GOG_BUILD)
    compiler = VRMirrorCompiler(profile=GOG_BUILD)
    compiler.apply(image)
    section = image.get_section(compiler.section_name)
    assert section is not None
    site = GOG_BUILD.site(name)
    address = {
        "payload": image.rva_to_va(section.virtual_address) + 0x40,
        "hook": site.va,
        "continuation": site.va + len(site.original),
        "active": compiler.abi(image).enabled_va,
    }[changed]
    image.write_bytes(image.va_to_offset(address), b"\xcc")
    with pytest.raises(PatchError):
        compiler.postcheck(image)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize(
    "name",
    [
        b"Screen Width",
        b"Screen Height",
        b"Full Screen",
        b"Game Width",
        b"Game Height",
        b"sCrEeN wIdTh",
        b"GAME HEIGHT",
        b"Screen",
        b"Screen Width Extra",
        b"Screen Width\0Extra",
        b"",
        b"Gamma",
        b"Monitor",
        None,
    ],
)
def test_only_exact_display_values_are_suppressed(enabled: bool, name: bytes | None) -> None:
    blocked = (
        enabled
        and name is not None
        and name.split(b"\0")[0].lower()
        in {
            b"screen width",
            b"screen height",
            b"full screen",
            b"game width",
            b"game height",
        }
    )
    _assert_write(name=name, enabled=enabled, kind=4, length=4, blocked=blocked)


@pytest.mark.parametrize(("kind", "length"), [(1, 4), (4, 8), (3, 4), (4, 0)])
def test_other_value_types_and_sizes_preserve_native_errors(kind: int, length: int) -> None:
    _assert_write(name=b"Screen Width", enabled=True, kind=kind, length=length, blocked=False)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("fullscreen", [False, True])
def test_vr_gamma_query_retains_dormant_fullscreen_policy_and_native_capability_checks(
    *,
    enabled: bool,
    fullscreen: bool,
) -> None:
    image = _source(GOG_BUILD)
    compiler = VRMirrorCompiler(profile=GOG_BUILD)
    compiler.apply(image)
    machine = _machine(image)
    machine.mem_write(compiler.abi(image).enabled_va, struct.pack("<I", enabled))
    native_mode = _HEAP + 0x1000
    machine.mem_write(native_mode, bytes((fullscreen,)))
    machine.reg_write(UC_X86_REG_EDX, native_mode)
    registers = (
        UC_X86_REG_EAX,
        UC_X86_REG_EBX,
        UC_X86_REG_ECX,
        UC_X86_REG_ESI,
        UC_X86_REG_EDI,
        UC_X86_REG_EBP,
    )
    for index, register in enumerate(registers):
        machine.reg_write(register, 100 + index)
    site = GOG_BUILD.site("vr.windowed_gamma_query")
    native_checks = site.va + len(site.original)
    rejected = native_checks + 0x3B
    destinations = []

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address in (native_checks, rejected):
            destinations.append(address)
            current.emu_stop()

    machine.hook_add(UC_HOOK_CODE, observe)
    machine.emu_start(site.va, _HEAP + 0xE000, count=1000)
    assert destinations == [native_checks if enabled or fullscreen else rejected]
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK
    assert machine.reg_read(UC_X86_REG_EDX) == native_mode
    assert [machine.reg_read(register) for register in registers] == list(range(100, 106))
    assert bytes(machine.mem_read(native_mode, 1)) == bytes((fullscreen,))
    # Neither the capability test nor its original reject branch is bypassed.
    assert bytes(machine.mem_read(native_checks, len(site.context_after))) == site.context_after


def _assert_write(
    *,
    name: bytes | None,
    enabled: bool,
    kind: int,
    length: int,
    blocked: bool,
) -> None:
    image = _source(GOG_BUILD)
    compiler = VRMirrorCompiler(profile=GOG_BUILD)
    compiler.apply(image)
    machine = _machine(image)
    machine.mem_write(compiler.abi(image).enabled_va, struct.pack("<I", enabled))
    callback = _HEAP + 0xB000
    value = _HEAP + 0x2000
    machine.mem_write(0x0066500C, struct.pack("<I", callback))
    machine.mem_write(callback, bytes.fromhex("b8 05 00 00 00 c2 18 00"))
    machine.mem_write(value, struct.pack("<I", 1280))
    pointer = _HEAP + 0x1000 if name is not None else 0
    if name is not None:
        machine.mem_write(pointer, name + b"\0")
    args = (0x12345678, pointer, 0, kind, value, length)
    machine.mem_write(_STACK, struct.pack("<6I", *args))
    registers = (
        UC_X86_REG_EBX,
        UC_X86_REG_ECX,
        UC_X86_REG_EDX,
        UC_X86_REG_ESI,
        UC_X86_REG_EDI,
        UC_X86_REG_EBP,
    )
    for index, register in enumerate(registers):
        machine.reg_write(register, 100 + index)
    calls = []

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == callback:
            calls.append(
                struct.unpack("<6I", current.mem_read(current.reg_read(UC_X86_REG_ESP) + 4, 24))
            )

    machine.hook_add(UC_HOOK_CODE, observe)
    site = GOG_BUILD.site("vr.mirror_preferences")
    machine.emu_start(site.va, site.va + len(site.original), count=3000)
    assert calls == ([] if blocked else [args])
    assert machine.reg_read(UC_X86_REG_EAX) == (0 if blocked else 5)
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 24
    assert [machine.reg_read(register) for register in registers] == list(range(100, 106))
    assert bytes(machine.mem_read(value, 4)) == struct.pack("<I", 1280)
