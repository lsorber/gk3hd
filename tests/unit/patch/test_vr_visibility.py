"""Execute native shared visibility scopes without a game or headset."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_PROT_EXEC, UC_PROT_READ, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.binary.x86 import BranchOpcode, encode_rel32_branch
from gk3hd.patch.builds import GOG_BUILD, SUPPORTED_BUILDS, BuildProfile
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.definitions.vr_visibility import VRVisibilityCompiler
from gk3hd.patch.model import PatchError
from tests.unit.patch.test_complete_compilation import _source
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile


def _prepared(
    profile: BuildProfile = GOG_BUILD,
) -> tuple[PEFile, VRVisibilityCompiler, int, dict[str, int]]:
    image = _source(profile)
    scene = VRSceneCompiler(profile=profile, units_per_meter=40)
    scene.apply(image)
    compiler = VRVisibilityCompiler.for_scene(image, profile, scene.abi(image))
    compiler.apply(image)
    compiler.postcheck(image)
    section = image.get_section(compiler.section_name)
    assert section is not None
    base = image.rva_to_va(section.virtual_address)
    _, labels = compiler._payload(base)
    return image, compiler, base, labels


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda p: str(p.id))
def test_visibility_is_dormant_and_verifies_native_dependencies(profile: BuildProfile) -> None:
    image, compiler, base, _ = _prepared(profile)
    assert image.read_u32_va(base + compiler._active) == 0
    assert image.read_u32_va(base + compiler._point_active) == 0
    site = profile.site("vr.visibility_collect")
    image.write_bytes(image.va_to_offset(site.va), b"\xcc")
    with pytest.raises(PatchError, match="collector dependency"):
        compiler.postcheck(image)


@pytest.mark.parametrize("name", ["vr.visibility_collect", "vr.visibility_collect_call"])
def test_changed_visibility_dependency_is_rejected_before_writes(name: str) -> None:
    image = _source(GOG_BUILD)
    scene = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40)
    scene.apply(image)
    compiler = VRVisibilityCompiler.for_scene(image, GOG_BUILD, scene.abi(image))
    image.write_bytes(image.va_to_offset(GOG_BUILD.site(name).va), b"\xcc")
    before = image.to_bytes()
    with pytest.raises(PatchError):
        compiler.apply(image)
    assert image.to_bytes() == before


def _execution() -> tuple[
    Uc, VRVisibilityCompiler, int, dict[str, int], int, bytes, dict[int, int]
]:
    image, compiler, base, labels = _prepared()
    machine = _machine(image)
    machine.mem_map(0, 0x1000)
    machine.mem_write(0, struct.pack("<I", 0xFFFFFFFF))
    origin = GOG_BUILD.address("vr.visibility_origin")
    authored = struct.pack("<3f", 100, 200, 300)
    machine.mem_write(origin, authored)
    machine.mem_write(GOG_BUILD.site("vr.visibility_collect").va, b"\xc2\x08\x00")
    # Substitute only the native draw in this emulator. It reaches the actual
    # installed top-level collector hook with thiscall arguments unchanged.
    body = bytes.fromhex("55 8b ec 68 3f 00 00 00 68 4d 00 00 00 b9 00 40 90 00")
    body += encode_rel32_branch(
        opcode=BranchOpcode.CALL,
        site_va=compiler.draw_va + len(body),
        target_va=labels["collect"],
        size=5,
    )
    body += bytes.fromhex("b8 78 56 34 12 c9 c2 0c 00")
    machine.mem_write(compiler.draw_va, body)
    pair = _HEAP + 0x2000
    machine.mem_write(pair, bytes(464))
    machine.mem_write(pair + 28, struct.pack("<3f", 1, 2, 3))
    machine.mem_write(pair + 232 + 28, struct.pack("<3f", 4, 5, 6))
    machine.mem_write(
        _STACK, struct.pack("<4I", _RETURN, compiler.context_va, _HEAP + 0x3000, pair)
    )
    registers = {UC_X86_REG_EBX: 11, UC_X86_REG_ESI: 22, UC_X86_REG_EDI: 33, UC_X86_REG_EBP: 44}
    for register, value in registers.items():
        machine.reg_write(register, value)
    machine.mem_protect(base + compiler._code, 0x1000, UC_PROT_READ | UC_PROT_EXEC)
    return machine, compiler, base, labels, origin, authored, registers


def test_shared_collection_visits_both_eyes_and_restores_origin_stack_and_registers() -> None:
    machine, compiler, base, labels, origin, authored, registers = _execution()
    native = GOG_BUILD.site("vr.visibility_collect").va
    # The eye offsets are measured in the shared camera's sheared coordinates.
    machine.mem_write(_HEAP + 0x3000 + 0x28, struct.pack("<9f", 2, 1, 0, 0, 3, 0, 0, -2, 4))
    visits = []
    writes = []

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == native:
            stack = current.reg_read(UC_X86_REG_ESP)
            visits.append(
                (
                    bytes(current.mem_read(origin, 12)),
                    current.reg_read(UC_X86_REG_ECX),
                    struct.unpack("<2I", current.mem_read(stack + 4, 8)),
                )
            )

    def written(
        _current: Uc, _access: int, address: int, _size: int, _value: int, _context: object
    ) -> None:
        writes.append(address)

    machine.hook_add(UC_HOOK_CODE, observe)
    machine.hook_add(UC_HOOK_MEM_WRITE, written)
    machine.emu_start(labels["shared_draw"], _RETURN, timeout=1_000_000, count=1000)
    assert visits == [
        (struct.pack("<3f", *point), _HEAP + 0x4000, (77, 63)) for point in ((1, 2, 3), (4, 5, 6))
    ]
    assert bytes(machine.mem_read(origin, 12)) == authored
    assert machine.reg_read(UC_X86_REG_EAX) == 0x12345678
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 16
    assert all(machine.reg_read(register) == value for register, value in registers.items())
    assert struct.unpack("<I", machine.mem_read(0, 4))[0] == 0xFFFFFFFF
    assert bytes(machine.mem_read(base + compiler._active, 8)) == bytes(8)
    (back_limit,) = struct.unpack("<f", machine.mem_read(base + compiler._model_back_limit, 4))
    assert back_limit == pytest.approx(-((6**2 + 6**2 + 12**2) ** 0.5 / 2 + 0.001))
    assert not any(
        base + compiler._code <= address < base + compiler.section_size for address in writes
    )


def test_dormant_collection_is_one_native_call_with_no_origin_change() -> None:
    machine, _compiler, _base, labels, origin, authored, _registers = _execution()
    visits = []

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == GOG_BUILD.site("vr.visibility_collect").va:
            visits.append(bytes(current.mem_read(origin, 12)))

    machine.hook_add(UC_HOOK_CODE, observe)
    machine.mem_write(_STACK, struct.pack("<3I", _RETURN, 77, 63))
    machine.emu_start(labels["collect"], _RETURN, timeout=1_000_000, count=100)
    assert visits == [authored]
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 12


@pytest.mark.parametrize(
    ("shared", "plane_distance", "current_cull", "rescued"),
    [
        (False, -0.2, 1, False),
        (True, -1.5, 1, False),
        (True, -0.2, 1, True),
        (True, -0.2, 2, False),
    ],
)
def test_clipped_model_preserves_triangles_one_eye_can_see(
    shared: bool,
    plane_distance: float,
    current_cull: int,
    rescued: bool,
) -> None:
    machine, compiler, base, labels, *_ = _execution()
    frame, engine, device, vtable = (
        _HEAP + address for address in (0x1800, 0x3000, 0x4000, 0x5000)
    )
    get, set_ = vtable + 0x200, vtable + 0x210
    machine.mem_write(base + compiler._active, struct.pack("<I", shared))
    machine.mem_write(base + compiler._model_back_limit, struct.pack("<f", -1))
    machine.mem_write(frame - 0x18, struct.pack("<I", engine))
    machine.mem_write(frame - 0x20, struct.pack("<f", plane_distance))
    machine.mem_write(engine + 0x4E8, struct.pack("<I", device))
    machine.mem_write(device, struct.pack("<I", vtable))
    machine.mem_write(vtable + 0x54, struct.pack("<2I", get, set_))
    machine.mem_write(get, bytes.fromhex("33 c0 c2 0c 00"))
    machine.mem_write(set_, bytes.fromhex("33 c0 c2 0c 00"))
    machine.reg_write(UC_X86_REG_EBP, frame)
    changes: list[int] = []
    continuation: list[int] = []
    facing = GOG_BUILD.site("vr.model_clip_facing")
    front = facing.va + len(facing.original)
    back = front + 0x75

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address in {front, back}:
            continuation.append(address)
            current.emu_stop()
        if address in {get, set_}:
            stack = current.reg_read(UC_X86_REG_ESP)
            owner, state, value = struct.unpack("<3I", current.mem_read(stack + 4, 12))
            assert (owner, state) == (device, 22)  # D3DRENDERSTATE_CULLMODE.
            if address == get:
                current.mem_write(value, struct.pack("<I", current_cull))
            else:
                changes.append(value)

    machine.hook_add(UC_HOOK_CODE, observe)
    # Compare 0 < 1 on the x87 stack, then enter the real patched instruction.
    trampoline = vtable + 0x300
    body = bytes.fromhex("d9 e8 d9 ee de d9")
    machine.mem_write(
        trampoline,
        body
        + encode_rel32_branch(
            opcode=BranchOpcode.JUMP,
            site_va=trampoline + len(body),
            target_va=facing.va,
            size=5,
        ),
    )
    machine.emu_start(trampoline, _RETURN, count=180)
    assert continuation == [front if rescued else back]
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK
    assert changes == ([3] if rescued else [])

    # The exit hook restores the exact original state before the next pass.
    machine.emu_start(labels["vr.model_clip_end"], _RETURN, count=120)
    assert changes == ([3, 1] if rescued else [])
    assert bytes(machine.mem_read(base + compiler._model_device, 4)) == bytes(4)


@pytest.mark.parametrize("invalid", ["context", "source", "eyes", "recursive"])
def test_unavailable_shared_draw_rejects_before_touching_visibility(invalid: str) -> None:
    machine, compiler, base, labels, origin, authored, registers = _execution()
    arguments = [compiler.context_va, _HEAP + 0x3000, _HEAP + 0x2000]
    if invalid == "recursive":
        machine.mem_write(base + compiler._active, struct.pack("<I", 1))
    else:
        arguments[{"context": 0, "source": 1, "eyes": 2}[invalid]] = 0
    before = bytes(machine.mem_read(base, compiler._code))
    machine.mem_write(_STACK, struct.pack("<4I", _RETURN, *arguments))
    machine.emu_start(labels["shared_draw"], _RETURN, timeout=1_000_000, count=100)
    assert machine.reg_read(UC_X86_REG_EAX) == 0x80004005
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 16
    assert bytes(machine.mem_read(base, compiler._code)) == before
    assert bytes(machine.mem_read(origin, 12)) == authored
    assert all(machine.reg_read(register) == value for register, value in registers.items())
    assert struct.unpack("<I", machine.mem_read(0, 4))[0] == 0xFFFFFFFF


@pytest.mark.parametrize("flags", [0, 2, 4, 6])
def test_visibility_exception_search_is_read_only_and_unwind_restores_owned_origin(
    flags: int,
) -> None:
    machine, compiler, base, labels, origin, authored, _registers = _execution()

    class CollectionInterruptedError(Exception):
        pass

    def interrupt(_current: Uc, address: int, _size: int, _context: object) -> None:
        if address == GOG_BUILD.site("vr.visibility_collect").va:
            raise CollectionInterruptedError

    hook = machine.hook_add(UC_HOOK_CODE, interrupt)
    with pytest.raises(CollectionInterruptedError):
        machine.emu_start(labels["shared_draw"], _RETURN, timeout=1_000_000, count=1000)
    machine.hook_del(hook)
    registration = bytes(machine.mem_read(0, 4))
    assert bytes(machine.mem_read(origin, 12)) == struct.pack("<3f", 1, 2, 3)
    record = _HEAP + 0x7000
    machine.mem_write(record, struct.pack("<2I", 0xC0000005, flags))
    machine.mem_write(_STACK + 0x800, struct.pack("<5I", _RETURN, record, 0, 0, 0))
    machine.reg_write(UC_X86_REG_ESP, _STACK + 0x800)
    machine.emu_start(labels["unwind"], _RETURN, timeout=1_000_000, count=200)
    assert machine.reg_read(UC_X86_REG_EAX) == 0  # Continue native exception search.
    assert bytes(machine.mem_read(0, 4)) == registration  # OS owns the chain.
    if flags:
        assert bytes(machine.mem_read(origin, 12)) == authored
        assert bytes(machine.mem_read(base + compiler._active, 8)) == bytes(8)
    else:
        assert bytes(machine.mem_read(origin, 12)) == struct.pack("<3f", 1, 2, 3)
        assert struct.unpack("<I", machine.mem_read(base + compiler._active, 4))[0] == 1
