"""Execute the installed scenery hooks, including original native fallbacks."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE, Uc
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

from gk3hd.patch.builds import GOG_BUILD, SUPPORTED_BUILDS, BuildProfile
from gk3hd.patch.definitions.vr_loading import VRLoadingCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.definitions.vr_scenery import VRSceneryCompiler
from gk3hd.patch.definitions.vr_visibility import VRVisibilityCompiler
from gk3hd.patch.model import PatchError
from tests.unit.patch.test_complete_compilation import _source
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile

_SCOPE = _HEAP + 0x8000
_NATIVE = _HEAP + 0x8100
_DRAW = _HEAP + 0x8200


def _dependencies(profile: BuildProfile) -> tuple[PEFile, VRSceneryCompiler]:
    image = _source(profile)
    scene = VRSceneCompiler(profile=profile, units_per_meter=40)
    scene.apply(image)
    abi = scene.abi(image)
    visibility = VRVisibilityCompiler.for_scene(image, profile, abi)
    visibility.apply(image)
    image.add_section(VRLoadingCompiler.section_name, b"GK3XRL01" + bytes(0xF8), 0xE0000060)
    compiler = VRSceneryCompiler.for_scene(image, profile, abi, VRLoadingCompiler.abi(image))
    return image, compiler


def _prepared(
    profile: BuildProfile = GOG_BUILD,
) -> tuple[PEFile, VRSceneryCompiler, int, dict[str, int]]:
    image, compiler = _dependencies(profile)
    compiler.apply(image)
    compiler.postcheck(image)
    section = image.get_section(compiler.section_name)
    assert section is not None
    base = image.rva_to_va(section.virtual_address)
    _, labels = compiler._payload(base)
    return image, compiler, base, labels


def _return(cpu: Uc, arguments: int, result: int) -> None:
    stack = cpu.reg_read(UC_X86_REG_ESP)
    address = struct.unpack("<I", cpu.mem_read(stack, 4))[0]
    cpu.reg_write(UC_X86_REG_ESP, stack + 4 + arguments * 4)
    cpu.reg_write(UC_X86_REG_EAX, result)
    cpu.reg_write(UC_X86_REG_ECX, 0x22222222)
    cpu.reg_write(UC_X86_REG_EDX, 0x33333333)
    cpu.reg_write(UC_X86_REG_EFLAGS, 0x247)
    cpu.reg_write(UC_X86_REG_EIP, address)


def _cpu(image: PEFile) -> Uc:
    cpu = _machine(image)
    cpu.mem_map(0, 0x1000)
    cpu.mem_write(0, struct.pack("<I", 0xFFFFFFFF))
    return cpu


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda p: str(p.id))
def test_scenery_profile_uses_checked_loading_lifetime_and_starts_dormant(
    profile: BuildProfile,
) -> None:
    image, compiler, base, _ = _prepared(profile)
    assert image.read_bytes(image.va_to_offset(base + compiler._shared), 12) == bytes(12)
    assert image.read_bytes(image.va_to_offset(base + compiler._config), 20) == struct.pack(
        "<5I",
        20,
        1,
        profile.address("high_resolution_3d.render_wrapper_ptr"),
        profile.address("vr.scenery_formats"),
        compiler.loading.calls_va,
    )


@pytest.mark.parametrize(
    "name", [*VRSceneryCompiler._hooks, "vr.scenery_draw", "vr.scenery_footer"]
)
def test_scenery_rejects_changed_native_contract_without_writes(name: str) -> None:
    image, compiler = _dependencies(GOG_BUILD)
    site = compiler.profile.site(name)
    image.write_bytes(image.va_to_offset(site.va), b"\xcc")
    before = image.to_bytes()
    with pytest.raises(PatchError):
        compiler.apply(image)
    assert image.to_bytes() == before


@pytest.mark.parametrize("begin", [None, 0, 1, 2])
@pytest.mark.parametrize("end", [1, 2])
def test_root_preserves_native_result_registers_flags_and_scope_order(
    begin: int | None, end: int
) -> None:
    image, compiler, base, labels = _prepared()
    cpu = _cpu(image)
    cpu.mem_write(base + compiler._shared, struct.pack("<I", int(begin is not None)))
    cpu.mem_write(base + compiler._scope, struct.pack("<I", _SCOPE))
    root = _HEAP + 0x100
    cpu.reg_write(UC_X86_REG_ECX, root)
    cpu.mem_write(_STACK, struct.pack("<I", _RETURN))
    visits = []

    def observe(machine: Uc, address: int, _size: int, _context: object) -> None:
        if address == _SCOPE:
            assert begin is not None
            stack = machine.reg_read(UC_X86_REG_ESP)
            config, actual, phase = struct.unpack("<3I", machine.mem_read(stack + 4, 12))
            assert config == base + compiler._config
            assert actual == root
            visits.append(phase)
            _return(machine, 3, begin if phase == 0 else end)
        elif address == compiler.profile.site("vr.scenery_draw").va:
            assert machine.reg_read(UC_X86_REG_ECX) == root
            visits.append("native")
            _return(machine, 0, 0x87654321)

    cpu.hook_add(UC_HOOK_CODE, observe)
    cpu.emu_start(labels["vr.scenery_call"], _RETURN, count=1000)
    expected = ["native"] if begin is None else [0, "native"] if begin == 0 else [0, "native", 1]
    assert visits == expected
    assert cpu.reg_read(UC_X86_REG_EAX) == 0x87654321
    assert cpu.reg_read(UC_X86_REG_ECX) == 0x22222222
    assert cpu.reg_read(UC_X86_REG_EDX) == 0x33333333
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 4
    assert cpu.reg_read(UC_X86_REG_EFLAGS) & 0x8D5 == 0x247 & 0x8D5
    assert struct.unpack("<I", cpu.mem_read(base + compiler._active, 4))[0] == 0
    failed = begin == 2 or (begin == 1 and end == 2)
    assert struct.unpack("<I", cpu.mem_read(base + compiler._failed, 4))[0] == int(failed)


@pytest.mark.parametrize("name", VRSceneryCompiler._draw_sites)
@pytest.mark.parametrize("action", [None, 0, 1, 2])
def test_indexed_draw_preserves_original_call_or_suppresses_it_once(
    name: str, action: int | None
) -> None:
    image, compiler, base, _labels = _prepared()
    cpu = _cpu(image)
    site = compiler.profile.site(name)
    cpu.mem_write(base + compiler._shared, struct.pack("<I", int(action is not None)))
    cpu.mem_write(base + compiler._active, struct.pack("<I", 1))
    cpu.mem_write(base + compiler._draw, struct.pack("<I", _DRAW))
    table = _HEAP + 0x5000
    cpu.mem_write(table + 0x74, struct.pack("<I", _NATIVE))
    frame = _HEAP + 0x7000
    cpu.mem_write(frame - 0x34, struct.pack("<I", 135))
    arguments = [0x12340000, 4, 0x244, _HEAP + 0x1000, 48, _HEAP + 0x2000, 96, 12]
    cpu.mem_write(_STACK, struct.pack("<8I", *arguments))
    for register, value in (
        (UC_X86_REG_ECX, table),
        (UC_X86_REG_EDX, table),
        (UC_X86_REG_EBP, frame),
    ):
        cpu.reg_write(register, value)
    visits = []

    def observe(machine: Uc, address: int, _size: int, _context: object) -> None:
        stack = machine.reg_read(UC_X86_REG_ESP)
        if address == _DRAW:
            assert action is not None
            pointer, sid = struct.unpack("<2I", machine.mem_read(stack + 4, 8))
            assert pointer == _STACK
            assert sid == 135
            assert list(struct.unpack("<8I", machine.mem_read(pointer, 32))) == arguments
            visits.append("adapter")
            _return(machine, 2, action)
        elif address == _NATIVE:
            assert list(struct.unpack("<8I", machine.mem_read(stack + 4, 32))) == arguments
            visits.append("native")
            _return(machine, 8, 0x87654321)

    cpu.hook_add(UC_HOOK_CODE, observe)
    cpu.emu_start(site.va, site.va + 5, count=500)
    assert visits == (
        ["native"] if action is None else ["adapter", "native"] if action == 0 else ["adapter"]
    )
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 28
    assert bytes(cpu.mem_read(_STACK + 28, 4)) == bytes(4)
    assert cpu.reg_read(UC_X86_REG_EAX) == (0 if action in (1, 2) else 0x87654321)
    assert cpu.reg_read(UC_X86_REG_EBP) == frame
    assert struct.unpack("<I", cpu.mem_read(base + compiler._failed, 4))[0] == int(action == 2)
    assert struct.unpack("<I", cpu.mem_read(base + compiler._captures, 4))[0] == int(action == 1)


@pytest.mark.parametrize("action", [None, 0, 1, 2])
def test_prepared_surface_keeps_original_rejection_and_loop_footer(action: int | None) -> None:
    image, compiler, base, _labels = _prepared()
    cpu = _cpu(image)
    site = compiler.profile.site("vr.scenery_prepared")
    cpu.mem_write(base + compiler._shared, struct.pack("<I", int(action is not None)))
    cpu.mem_write(base + compiler._active, struct.pack("<I", 1))
    cpu.mem_write(base + compiler._prepared, struct.pack("<I", _DRAW))
    native_value = struct.unpack("<I", site.original[1:])[0]
    cpu.mem_write(native_value, struct.pack("<I", 0x12345678))
    frame = _HEAP + 0x7000
    cpu.mem_write(frame - 0x34, struct.pack("<I", 135))
    cpu.mem_write(frame - 0x14, struct.pack("<I", 0x12340000))
    cpu.reg_write(UC_X86_REG_EBP, frame)
    visits = []

    def observe(machine: Uc, address: int, _size: int, _context: object) -> None:
        if address == _DRAW:
            assert action is not None
            stack = machine.reg_read(UC_X86_REG_ESP)
            assert struct.unpack("<2I", machine.mem_read(stack + 4, 8)) == (0x12340000, 135)
            visits.append("adapter")
            _return(machine, 2, action)

    cpu.hook_add(UC_HOOK_CODE, observe)
    destination = compiler.profile.site("vr.scenery_footer").va if action in (1, 2) else site.va + 5
    cpu.emu_start(site.va, destination, count=500)
    assert visits == ([] if action is None else ["adapter"])
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK
    assert cpu.reg_read(UC_X86_REG_EBP) == frame
    if action in (None, 0):
        assert cpu.reg_read(UC_X86_REG_EAX) == 0x12345678
    assert struct.unpack("<I", cpu.mem_read(base + compiler._reused, 4))[0] == int(action == 1)


@pytest.mark.parametrize("mode", ["clean", "failed", "unfinished", "missing"])
def test_shared_callback_cancels_failed_frames_and_restores_its_owner(mode: str) -> None:
    image, compiler, base, labels = _prepared()
    cpu = _cpu(image)
    cpu.mem_write(base + compiler._resolved, struct.pack("<I", 1))
    cpu.mem_write(
        base + compiler._scope, struct.pack("<3I", _SCOPE, _DRAW, 0 if mode == "missing" else _DRAW)
    )
    cpu.mem_write(_STACK, struct.pack("<4I", _RETURN, 11, 22, 33))
    preserved = {UC_X86_REG_EBX: 111, UC_X86_REG_ESI: 222, UC_X86_REG_EDI: 333, UC_X86_REG_EBP: 444}
    for register, value in preserved.items():
        cpu.reg_write(register, value)
    events = []

    def observe(machine: Uc, address: int, _size: int, _context: object) -> None:
        stack = machine.reg_read(UC_X86_REG_ESP)
        if address == compiler.shared_draw_va:
            assert struct.unpack("<3I", machine.mem_read(stack + 4, 12)) == (11, 22, 33)
            assert struct.unpack("<I", machine.mem_read(base + compiler._shared, 4))[0] == int(
                mode != "missing"
            )
            events.append("shared")
            if mode == "failed":
                machine.mem_write(base + compiler._failed, struct.pack("<I", 1))
            if mode == "unfinished":
                machine.mem_write(base + compiler._active, struct.pack("<I", 1))
            _return(machine, 3, 0x12345678)
        elif address == _SCOPE:
            assert struct.unpack("<3I", machine.mem_read(stack + 4, 12)) == (0, 0, 2)
            events.append("cancel")
            _return(machine, 3, 0)

    cpu.hook_add(UC_HOOK_CODE, observe)
    cpu.emu_start(labels["shared"], _RETURN, count=1000)
    failed = mode in {"failed", "unfinished"}
    assert events == (["shared", "cancel"] if failed else ["shared"])
    assert cpu.reg_read(UC_X86_REG_EAX) == (0x80004005 if failed else 0x12345678)
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 16
    assert all(cpu.reg_read(register) == value for register, value in preserved.items())
    assert bytes(cpu.mem_read(base + compiler._shared, 8)) == bytes(8)
    assert struct.unpack("<I", cpu.mem_read(0, 4))[0] == 0xFFFFFFFF


@pytest.mark.parametrize("missing", [None, "module", "Gk3hdWorldDrawV1"])
def test_shared_callback_resolves_real_export_names_once_and_keeps_missing_exports_native(
    missing: str | None,
) -> None:
    image, compiler, base, labels = _prepared()
    cpu = _cpu(image)
    module, lookup = _HEAP + 0x8500, _HEAP + 0x8600
    for name, address in (("GetModuleHandleA", module), ("GetProcAddress", lookup)):
        cpu.mem_write(compiler.profile.address(f"win32.{name}"), struct.pack("<I", address))
    exports = {
        "Gk3hdWorldScopeV1": _SCOPE,
        "Gk3hdWorldDrawV1": _DRAW,
        "Gk3hdWorldPreparedV1": _DRAW,
    }
    visits = []

    def observe(machine: Uc, address: int, _size: int, _context: object) -> None:
        stack = machine.reg_read(UC_X86_REG_ESP)
        if address == module:
            pointer = struct.unpack("<I", machine.mem_read(stack + 4, 4))[0]
            assert bytes(machine.mem_read(pointer, 10)) == b"ddraw.dll\0"
            visits.append("module")
            _return(machine, 1, 0 if missing == "module" else 0x12340000)
        elif address == lookup:
            handle, pointer = struct.unpack("<2I", machine.mem_read(stack + 4, 8))
            assert handle == 0x12340000
            name = bytes(machine.mem_read(pointer, 32)).split(b"\0")[0].decode()
            visits.append(name)
            _return(machine, 2, 0 if name == missing else exports[name])
        elif address == compiler.shared_draw_va:
            enabled = struct.unpack("<I", machine.mem_read(base + compiler._shared, 4))[0]
            assert enabled == int(missing is None)
            visits.append("shared")
            _return(machine, 3, 0x12345678)

    cpu.hook_add(UC_HOOK_CODE, observe)
    for _ in range(2):
        cpu.mem_write(_STACK, struct.pack("<4I", _RETURN, 11, 22, 33))
        cpu.reg_write(UC_X86_REG_ESP, _STACK)
        cpu.emu_start(labels["shared"], _RETURN, count=1000)
        assert cpu.reg_read(UC_X86_REG_EAX) == 0x12345678
        assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 16
        assert struct.unpack("<I", cpu.mem_read(0, 4))[0] == 0xFFFFFFFF
    expected = ["module"] if missing == "module" else ["module", *exports]
    assert visits == [*expected, "shared", "shared"]


@pytest.mark.parametrize("flags", [0, 2, 4])
def test_native_exception_unwind_cancels_scope_without_swallowing_the_exception(flags: int) -> None:
    image, compiler, base, labels = _prepared()
    cpu = _cpu(image)
    cpu.mem_write(base + compiler._resolved, struct.pack("<I", 1))
    cpu.mem_write(base + compiler._scope, struct.pack("<3I", _SCOPE, _DRAW, _DRAW))
    cpu.mem_write(_STACK, struct.pack("<4I", _RETURN, 11, 22, 33))

    def stop_at_native(machine: Uc, address: int, _size: int, _context: object) -> None:
        if address == compiler.shared_draw_va:
            machine.emu_stop()

    hook = cpu.hook_add(UC_HOOK_CODE, stop_at_native)
    cpu.emu_start(labels["shared"], _RETURN, count=1000)
    cpu.hook_del(hook)
    registration = struct.unpack("<I", cpu.mem_read(0, 4))[0]
    assert struct.unpack("<2I", cpu.mem_read(registration, 8)) == (0xFFFFFFFF, labels["unwind"])
    cpu.mem_write(base + compiler._active, struct.pack("<I", 1))
    record, stack = _HEAP + 0x3000, _STACK - 0x1000
    cpu.mem_write(record, struct.pack("<2I", 0xE0000001, flags))
    cpu.mem_write(stack, struct.pack("<5I", _RETURN, record, registration, 0, 0))
    cpu.reg_write(UC_X86_REG_ESP, stack)
    preserved = {UC_X86_REG_EBX: 111, UC_X86_REG_ESI: 222, UC_X86_REG_EDI: 333, UC_X86_REG_EBP: 444}
    for register, value in preserved.items():
        cpu.reg_write(register, value)
    cancels = []

    def cancel(machine: Uc, address: int, _size: int, _context: object) -> None:
        if address == _SCOPE:
            current = machine.reg_read(UC_X86_REG_ESP)
            assert struct.unpack("<3I", machine.mem_read(current + 4, 12)) == (0, 0, 2)
            cancels.append("cancel")
            _return(machine, 3, 0)

    cpu.hook_add(UC_HOOK_CODE, cancel)
    cpu.emu_start(labels["unwind"], _RETURN, count=1000)
    assert cpu.reg_read(UC_X86_REG_EAX) == 1  # ExceptionContinueSearch, not a filter result.
    assert cpu.reg_read(UC_X86_REG_ESP) == stack + 4  # Dispatcher owns the cdecl arguments.
    assert all(cpu.reg_read(register) == value for register, value in preserved.items())
    assert cancels == (["cancel"] if flags else [])
    expected = (0, 0, 1) if flags else (1, 1, 0)
    assert struct.unpack("<3I", cpu.mem_read(base + compiler._shared, 12)) == expected
