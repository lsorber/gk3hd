"""Windowed pages complete VR frames without altering native presentation."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_EFLAGS,
    UC_X86_REG_EIP,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.builds import GOG_BUILD, SUPPORTED_BUILDS
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.vr_panel import VRPanelCompiler
from gk3hd.patch.definitions.vr_presentation import VRPresentationCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError
from tests.unit.patch.test_complete_compilation import _source
from tests.unit.patch.test_vr_scene import _HEAP, _STACK, _machine

if TYPE_CHECKING:
    from unicorn import Uc

    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.vr_panel import VRPanelABI
    from gk3hd.patch.definitions.vr_scene import VRSceneABI


def _prepared(profile: BuildProfile) -> tuple[PEFile, VRPanelABI, VRSceneABI]:
    image = _source(profile)
    TransitionFrameCompiler(profile=profile).apply(image)
    scene = VRSceneCompiler(profile=profile, units_per_meter=40, deferred_frame=True)
    scene.apply(image)
    panel = VRPanelCompiler(profile=profile, world_enabled_va=scene.abi(image).enabled_va)
    panel.apply(image)
    return image, panel.abi(image), scene.abi(image)


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
def test_windowed_boundary_is_verified_and_dormant(profile: BuildProfile) -> None:
    image, panel, scene = _prepared(profile)
    compiler = VRPresentationCompiler(profile=profile, panel=panel, scene=scene)
    compiler.apply(image)
    compiler.postcheck(image)
    assert image.read_u32_va(panel.enabled_va) == 0
    assert image.read_u32_va(panel.world_enabled_va) == 0
    with pytest.raises(PatchError, match="already installed"):
        compiler.apply(image)


@pytest.mark.parametrize("changed", ["entry", "before", "continuation"])
@pytest.mark.parametrize("name", VRPresentationCompiler._sites)
def test_changed_native_boundary_is_rejected_before_mutation(changed: str, name: str) -> None:
    image, panel, scene = _prepared(GOG_BUILD)
    site = GOG_BUILD.site(name)
    address = site.va + {"entry": 0, "before": -1, "continuation": len(site.original)}[changed]
    image.write_bytes(image.va_to_offset(address), b"\xcc")
    before = image.to_bytes()
    with pytest.raises(PatchError, match="native"):
        VRPresentationCompiler(profile=GOG_BUILD, panel=panel, scene=scene).apply(image)
    assert image.to_bytes() == before


@pytest.mark.parametrize("changed", ["payload", "hook", "continuation"])
@pytest.mark.parametrize("name", VRPresentationCompiler._sites)
def test_modified_installation_is_rejected(changed: str, name: str) -> None:
    image, panel, scene = _prepared(GOG_BUILD)
    compiler = VRPresentationCompiler(profile=GOG_BUILD, panel=panel, scene=scene)
    compiler.apply(image)
    section = image.get_section(compiler.section_name)
    assert section is not None
    site = GOG_BUILD.site(name)
    address = {
        "payload": image.rva_to_va(section.virtual_address) + 0x40,
        "hook": site.va,
        "continuation": site.va + len(site.original),
    }[changed]
    image.write_bytes(image.va_to_offset(address), b"\xcc")
    with pytest.raises(PatchError):
        compiler.postcheck(image)


@pytest.mark.parametrize(
    "owner", ["disabled", "panel", "world", "cancelled_world", "missing_callback"]
)
def test_windowed_frame_uses_live_presenter_and_preserves_native_state(owner: str) -> None:
    image, panel, scene = _prepared(GOG_BUILD)
    compiler = VRPresentationCompiler(profile=GOG_BUILD, panel=panel, scene=scene)
    compiler.apply(image)
    machine = _machine(image)
    transition = TransitionFrameCompiler.runtime_abi(image)
    callback = _HEAP + 0xA000
    # Change the live composed callback after compilation. It deliberately
    # clobbers caller and nonvolatile registers plus flags to test isolation.
    machine.mem_write(callback, bytes.fromhex("31 c0 31 db 31 c9 31 d2 31 f6 31 ff c3"))
    for address, value in (
        (transition.pre_flip_presenter_slot_va, 0 if owner == "missing_callback" else callback),
        (panel.enabled_va, int(owner in {"panel", "missing_callback"})),
        (panel.world_enabled_va, int(owner == "world")),
        (scene.frame_pending_va, int(owner == "cancelled_world")),
        (0x00665180, 0x12345678),
        (transition.successful_flip_count_va, 19),
    ):
        machine.mem_write(address, struct.pack("<I", value))
    registers = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI)
    for index, register in enumerate(registers):
        machine.reg_write(register, 100 + index)
    machine.reg_write(UC_X86_REG_EFLAGS, 0x247)
    calls: list[int] = []

    def observe(_current: Uc, address: int, _size: int, _context: object) -> None:
        if address == callback:
            calls.append(address)

    machine.hook_add(UC_HOOK_CODE, observe)
    site = GOG_BUILD.site("vr.windowed_present")
    # This hook is reached only at initial entry, before the native retry setup.
    # Returning to the continuation must still load the real Sleep import.
    machine.emu_start(site.va, site.va + len(site.original), count=1000)
    assert calls == ([callback] if owner in {"panel", "world", "cancelled_world"} else [])
    assert machine.reg_read(UC_X86_REG_EDI) == 0x12345678
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK
    assert machine.reg_read(UC_X86_REG_EFLAGS) == 0x247
    assert [machine.reg_read(register) for register in registers] == list(range(100, 105))
    assert struct.unpack("<I", machine.mem_read(transition.successful_flip_count_va, 4))[0] == 19


@pytest.mark.parametrize(
    ("owner", "inactive", "called"),
    [
        ("disabled", 1, False),
        ("world", 1, True),
        ("panel", 1, True),
        ("cancelled_world", 1, True),
        ("missing_callback", 1, False),
        ("world", 0, False),
        ("panel", -1, False),
    ],
)
def test_inactive_page_finishes_vr_without_changing_native_skip(
    owner: str, inactive: int, *, called: bool
) -> None:
    image, panel, scene = _prepared(GOG_BUILD)
    compiler = VRPresentationCompiler(profile=GOG_BUILD, panel=panel, scene=scene)
    compiler.apply(image)
    machine = _machine(image)
    transition = TransitionFrameCompiler.runtime_abi(image)
    callback, window = _HEAP + 0xA000, _HEAP + 0xB000
    machine.mem_write(callback, bytes.fromhex("31 c0 31 db 31 c9 31 d2 31 f6 31 ff c3"))
    for address, value in (
        (transition.pre_flip_presenter_slot_va, 0 if owner == "missing_callback" else callback),
        (panel.enabled_va, int(owner in {"panel", "missing_callback"})),
        (scene.enabled_va, int(owner == "world")),
        (scene.frame_pending_va, int(owner == "cancelled_world")),
        (window + 0x64, inactive & 0xFFFFFFFF),
        (transition.successful_flip_count_va, 19),
    ):
        machine.mem_write(address, struct.pack("<I", value))
    machine.reg_write(UC_X86_REG_ESI, window)
    machine.reg_write(UC_X86_REG_ECX, 123)
    machine.reg_write(UC_X86_REG_EDX, 456)
    machine.reg_write(UC_X86_REG_EBX, 789)
    machine.reg_write(UC_X86_REG_EDI, 234)
    calls: list[int] = []

    def observe(_current: Uc, address: int, _size: int, _context: object) -> None:
        if address == callback:
            calls.append(address)

    machine.hook_add(UC_HOOK_CODE, observe)
    site = GOG_BUILD.site("vr.inactive_present")
    machine.emu_start(site.va, site.va + len(site.original), count=1000)
    assert bool(calls) == called
    assert len(calls) <= 1
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK
    assert machine.reg_read(UC_X86_REG_ESI) == window
    assert machine.reg_read(UC_X86_REG_EAX) == inactive & 0xFFFFFFFF
    assert machine.reg_read(UC_X86_REG_ECX) == 123
    assert machine.reg_read(UC_X86_REG_EDX) == 456
    assert machine.reg_read(UC_X86_REG_EBX) == 789
    assert machine.reg_read(UC_X86_REG_EDI) == 234
    flags = machine.reg_read(UC_X86_REG_EFLAGS)
    # The native JG immediately following this hook still decides desktop skip.
    assert (not flags & 0x40 and bool(flags & 0x80) == bool(flags & 0x800)) == (inactive > 0)
    assert struct.unpack("<I", machine.mem_read(window + 0x64, 4))[0] == inactive & 0xFFFFFFFF
    assert struct.unpack("<I", machine.mem_read(transition.successful_flip_count_va, 4))[0] == 19


@pytest.mark.parametrize(
    ("owner", "inactive", "device_result", "updates"),
    [
        ("disabled", 1, 0, False),
        ("disabled", 0, 0, True),
        ("disabled", -1, 0, True),
        ("world", 1, 0, True),
        ("panel", 1, 0, True),
        ("cancelled_world", 1, 0, True),
        ("world", 1, 0x80004005, False),
        ("panel", 1, 0x80004005, False),
    ],
)
def test_background_updates_preserve_device_health_and_dormant_wait(
    owner: str, inactive: int, device_result: int, *, updates: bool
) -> None:
    image, panel, scene = _prepared(GOG_BUILD)
    VRPresentationCompiler(profile=GOG_BUILD, panel=panel, scene=scene).apply(image)
    machine = _machine(image)
    window, device, table, health = (_HEAP + offset for offset in (0xA000, 0xB000, 0xB100, 0xB200))
    for address, value in (
        (panel.enabled_va, int(owner == "panel")),
        (scene.enabled_va, int(owner == "world")),
        (scene.frame_pending_va, int(owner == "cancelled_world")),
        (window + 0x64, inactive & 0xFFFFFFFF),
        (0x70D23C, device),
        (device, table),
        (table + 0x68, health),
    ):
        machine.mem_write(address, struct.pack("<I", value))
    machine.mem_write(health, b"\xb8" + struct.pack("<I", device_result) + b"\xc2\x04\x00")
    machine.reg_write(UC_X86_REG_ECX, window)
    machine.reg_write(UC_X86_REG_EBX, 456)
    machine.reg_write(UC_X86_REG_ESI, 789)
    machine.reg_write(UC_X86_REG_EDI, 234)
    calls: list[int] = []

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == health:
            calls.append(address)
        if address in {0x53361E, 0x5335E9}:
            current.emu_stop()

    machine.hook_add(UC_HOOK_CODE, observe)
    machine.emu_start(GOG_BUILD.site("vr.inactive_update").va, 0, count=1000)
    assert machine.reg_read(UC_X86_REG_EIP) == (0x5335E9 if updates else 0x53361E)
    assert bool(calls) == (owner != "disabled" or inactive <= 0)
    assert len(calls) <= 1
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK
    assert machine.reg_read(UC_X86_REG_EDX) == inactive & 0xFFFFFFFF
    assert machine.reg_read(UC_X86_REG_EBX) == 456
    assert machine.reg_read(UC_X86_REG_ESI) == 789
    assert machine.reg_read(UC_X86_REG_EDI) == 234
    assert struct.unpack("<I", machine.mem_read(window + 0x64, 4))[0] == inactive & 0xFFFFFFFF
