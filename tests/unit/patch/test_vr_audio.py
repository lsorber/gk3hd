"""Native VR audio follows completed head poses without adding audio commits."""

from __future__ import annotations

import struct
from typing import cast

import pytest
from unicorn import UC_HOOK_CODE, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EIP,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.binary.x86 import BranchOpcode, decode_rel32_branch
from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.vr_audio import VRListenerCompiler
from gk3hd.patch.definitions.vr_ownership import VROwnershipABI
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError
from tests.unit.patch.test_complete_compilation import _source
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine


def _install_stubs(
    machine: Uc, stubs: dict[int, str], condition: str, pose: tuple[float, ...]
) -> list[tuple[str, int, tuple[int, ...]]]:
    calls: list[tuple[str, int, tuple[int, ...]]] = []

    def call_stub(uc: Uc, address: int, _size: int, _data: object) -> None:
        name = stubs.get(address)
        if name is None:
            return
        sizes = {
            "ownership": 0,
            "module": 1,
            "resolve": 2,
            "head": 2,
            "position": 5,
            "orientation": 8,
            "commit": 1,
            "sources": 0,
            "rollback": 3,
        }
        count = sizes[name]
        stack = uc.reg_read(UC_X86_REG_ESP)
        values = struct.unpack(f"<{count + 1}I", uc.mem_read(stack, (count + 1) * 4))
        args = values[1:]
        calls.append((name, uc.reg_read(UC_X86_REG_ECX), args))
        result = 0
        if name == "ownership":
            result = int(condition != "scripted")
        elif name == "module":
            result = 0 if condition == "no_module" else 0x24680
        elif name == "resolve":
            result = 0 if condition == "no_export" else _HEAP + 0xB300
        elif name == "head":
            assert args[0] == 0x13579
            assert struct.unpack("<I", uc.mem_read(args[1], 4))[0] == 48
            supplied = (float("nan"), *pose[1:]) if condition == "bad_pose" else pose
            uc.mem_write(args[1], struct.pack("<I11f", 48, *supplied))
            result = {"missing": 0x80004001, "hidden": 1}.get(condition, 0)
        elif (name == "position" and condition == "position_failure") or (
            name == "orientation" and condition == "orientation_failure"
        ):
            result = 0x80004005
        uc.reg_write(UC_X86_REG_EAX, result)
        uc.reg_write(UC_X86_REG_ESP, stack + 4 * (count + 1))
        uc.reg_write(UC_X86_REG_EIP, values[0])

    machine.hook_add(UC_HOOK_CODE, call_stub)
    return calls


@pytest.mark.parametrize(
    "condition",
    [
        "ready",
        "disabled",
        "scripted",
        "missing",
        "hidden",
        "bad_pose",
        "no_device",
        "no_interface",
        "no_module",
        "no_export",
        "position_failure",
        "orientation_failure",
    ],
)
def test_listener_keeps_native_cadence_and_fallback(condition: str) -> None:
    profile = GOG_BUILD
    image = _source(profile)
    scene = VRSceneCompiler(profile=profile, units_per_meter=40)
    scene.apply(image)
    owner = VROwnershipABI(_HEAP + 0x8000, _HEAP + 0x8004, _HEAP + 0xB000)
    compiler = VRListenerCompiler(profile=profile, scene=scene.abi(image), ownership=owner)
    compiler.apply(image)
    compiler.postcheck(image)
    abi = compiler.abi(image)
    machine = _machine(image)
    manager, wrapper, interface, table = (_HEAP + n for n in (0x4000, 0x5000, 0x6000, 0x7000))

    def word(address: int, value: int) -> None:
        machine.mem_write(address, struct.pack("<I", value))

    word(scene.abi(image).enabled_va, int(condition != "disabled"))
    word(profile.address("high_resolution_3d.render_wrapper_ptr"), wrapper)
    word(wrapper + 0x4E8, 0 if condition == "no_device" else 0x13579)
    word(manager + 0x48, _HEAP + 0x7800)
    machine.mem_write(manager + 0x14, struct.pack("<5f", 7, 8, 9, 0.25, 0.5))
    word(manager + 0x54, 0 if condition == "no_interface" else interface)
    word(interface, table)
    stubs = {
        owner.query_va: "ownership",
        _HEAP + 0xB100: "module",
        _HEAP + 0xB200: "resolve",
        _HEAP + 0xB300: "head",
        _HEAP + 0xB400: "position",
        _HEAP + 0xB500: "orientation",
        _HEAP + 0xB600: "commit",
        profile.site("vr.audio_listener_set").va: "rollback",
        cast(
            "int",
            decode_rel32_branch(
                opcode=BranchOpcode.CALL,
                site_va=profile.site("vr.audio_tick").va + 6,
                instruction=profile.site("vr.audio_tick").context_after[:5],
            ),
        ): "sources",
    }
    word(profile.address("win32.GetModuleHandleA"), _HEAP + 0xB100)
    word(profile.address("win32.GetProcAddress"), _HEAP + 0xB200)
    for offset, stub in ((0x38, 0xB400), (0x34, 0xB500), (0x44, 0xB600)):
        word(table + offset, _HEAP + stub)
    original_args = (manager + 0x14, 0x3E800000, 0x3F000000)
    machine.mem_write(_STACK, struct.pack("<I", _RETURN))
    saved = {UC_X86_REG_EBX: 17, UC_X86_REG_ESI: 18, UC_X86_REG_EDI: 19, UC_X86_REG_EBP: 20}
    for register, value in saved.items():
        machine.reg_write(register, value)
    machine.reg_write(UC_X86_REG_ECX, manager)
    pose = (100.0, 69.5, 35.0, 0.0, 0.0, 1.0, -0.5, 0.8660254, 0.0, 0.0, 0.0)

    calls = _install_stubs(machine, stubs, condition, pose)
    site = profile.site("vr.audio_tick")
    entry = decode_rel32_branch(
        opcode=BranchOpcode.JUMP,
        site_va=site.va,
        instruction=image.read_bytes(image.va_to_offset(site.va), 5),
    )
    assert entry is not None
    machine.emu_start(entry, _RETURN, count=5000)
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 4
    assert all(machine.reg_read(register) == value for register, value in saved.items())
    assert sum(name == "sources" for name, _, _ in calls) == 1
    assert sum(name == "commit" for name, _, _ in calls) == int(condition != "no_interface")
    success = condition in {"ready", "no_interface"}
    assert struct.unpack("<I", machine.mem_read(abi.applied_va, 4))[0] == int(success)
    fallback = [call for call in calls if call[0] == "rollback"]
    assert fallback == (
        [("rollback", manager, original_args)]
        if condition in {"position_failure", "orientation_failure"}
        else []
    )
    cached = struct.unpack("<5f", machine.mem_read(manager + 0x14, 20))
    assert cached == ((100, 69.5, 35, 0, 0) if success else (7, 8, 9, 0.25, 0.5))
    if condition == "ready":
        position = next(call[2] for call in calls if call[0] == "position")
        orientation = next(call[2] for call in calls if call[0] == "orientation")
        assert position == (interface, *struct.unpack("<3I", struct.pack("<3f", *pose[:3])), 1)
        assert orientation == (interface, *struct.unpack("<6I", struct.pack("<6f", *pose[3:9])), 1)


@pytest.mark.parametrize("anchor", VRListenerCompiler._anchors)
def test_listener_rejects_changed_native_audio_without_writing(anchor: str) -> None:
    profile = GOG_BUILD
    image = _source(profile)
    scene = VRSceneCompiler(profile=profile, units_per_meter=40)
    scene.apply(image)
    compiler = VRListenerCompiler(
        profile=profile, scene=scene.abi(image), ownership=VROwnershipABI(1, 2, 3)
    )
    image.write_bytes(image.va_to_offset(profile.site(anchor).va), b"\xcc")
    before = image.to_bytes()
    with pytest.raises(PatchError, match="dependency changed"):
        compiler.apply(image)
    assert image.to_bytes() == before
