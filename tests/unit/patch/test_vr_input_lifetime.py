"""Execute native UI lifetimes without replacing their original operations."""

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
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.vr_input_lifetime import compile_input_lifetime
from gk3hd.patch.definitions.vr_loading import VRLoadingCompiler
from gk3hd.patch.model import PatchError
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine

if TYPE_CHECKING:
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.vr.compiler import VRProgram

pytest_plugins = ("tests.unit.vr.test_compiler",)


class LifetimeHarness:
    def __init__(
        self,
        program: VRProgram,
        profile: BuildProfile,
        *,
        observe: bool = False,
        shortcuts: bool = False,
    ) -> None:
        self.program, self.profile = program, profile
        self.image = program.image.clone()
        self.abi = compile_input_lifetime(
            self.image,
            profile=profile,
            panel=program.panel,
            inputs=program.inputs,
            ownership=program.ownership,
            observe=observe,
            shortcuts=program.game_menu if shortcuts else None,
        )
        self.cpu = _machine(self.image)
        self.cpu.mem_map(0, 0x1000)
        self.engine, self.services, self.manager, self.scene, self.root, self.inventory = (
            _HEAP + i for i in (0x1000, 0x2000, 0x3000, 0x4000, 0x5000, 0x6000)
        )
        self.owner_slot, self.mode_slot = _HEAP + 0x7000, _HEAP + 0x7004
        self.word(0x24, 7)
        self.word(program.inputs.enabled_va, 1)
        self.word(program.panel.enabled_va, 1)
        self.word(profile.address("engine.loop"), self.engine)
        self.word(self.engine + 0x444, self.services)
        self.word(self.services + 0x44, self.manager)
        self.word(profile.address("vr.room_global"), self.scene)
        self.word(self.scene, profile.address("vr.user_scene_vtable"))
        self.word(self.root, profile.address("vr.room_layer_vtable"))
        self.word(self.inventory, profile.address("inventory.vtable"))
        self.word(self.owner_slot, self.root)
        self.word(self.mode_slot, 1)
        self.word(program.panel.pointing_hand_va, 1)
        # Native graph/query recipients are stubs; the owner code under test is
        # the actual emitted x86, including its thread and lifetime guards.
        for target, source in (
            (profile.address("ui.current_layer"), self.owner_slot),
            (program.ownership.query_va, self.mode_slot),
        ):
            self.cpu.mem_write(target, b"\xa1" + struct.pack("<I", source) + b"\xc3")
        assert self.call(self.abi.bind) == 1

    def word(self, address: int, value: int) -> None:
        self.cpu.mem_write(address, struct.pack("<I", value))

    def read(self, address: int) -> int:
        return struct.unpack("<I", self.cpu.mem_read(address, 4))[0]

    def call(self, address: int) -> int:
        self.cpu.mem_write(_STACK, struct.pack("<I", _RETURN))
        self.cpu.reg_write(UC_X86_REG_ESP, _STACK)
        self.cpu.emu_start(address, _RETURN, count=2000)
        assert self.cpu.reg_read(UC_X86_REG_ESP) == _STACK + 4
        return self.cpu.reg_read(UC_X86_REG_EAX)

    def key(self) -> int:
        low = self.call(self.abi.query)
        return low | (self.cpu.reg_read(UC_X86_REG_EDX) << 32)

    def transition(self) -> None:
        site = self.profile.site("vr.input_transition_begin")
        self.cpu.reg_write(UC_X86_REG_ECX, _HEAP + 0x9000)
        self.cpu.reg_write(UC_X86_REG_ESP, _STACK)
        self.cpu.emu_start(site.va, site.va + len(site.original), count=2000)
        assert self.cpu.reg_read(UC_X86_REG_EAX) == _HEAP + 0x9000
        assert self.read(_HEAP + 0x9000) == struct.unpack_from("<I", site.original, 4)[0]
        assert self.cpu.reg_read(UC_X86_REG_ESP) == _STACK

    def recipient(self, previous: int, result: int, *, nested: bool) -> bytes:
        slot = TransitionFrameCompiler.runtime_abi(self.image).pre_flip_presenter_slot_va
        e = X86Emitter(base_va=previous)
        e.raw(b"\xff\x05" + struct.pack("<I", result + 8))
        e.raw(b"\x83\x3d" + struct.pack("<I", result + 8) + b"\x01")
        e.jump_if(Condition.NOT_EQUAL, "return")
        if nested:
            e.call_absolute(self.image.read_u32_va(slot))
        ports = (
            (self.program.inputs.shortcut_filter_slot_va, 14),
            (self.program.game_menu.shortcut_filter_slot_va, 4),
        )
        for index, (filter_slot, fallback) in enumerate(ports):
            e.raw(b"\xba" + struct.pack("<I", fallback))
            e.raw(b"\xff\x15" + struct.pack("<I", filter_slot))
            e.raw(b"\x89\x15" + struct.pack("<I", result + index * 4))
        e.label("return")
        e.raw(b"\xc3")
        return e.build()


def test_native_queries_keep_stable_keys_and_retire_changes(
    program: VRProgram, flat_bytes: tuple[bytes, BuildProfile]
) -> None:
    _, profile = flat_bytes
    h = LifetimeHarness(program, profile)
    first = h.key()
    assert first
    assert h.key() == first
    h.word(h.owner_slot, h.inventory)
    second = h.key()
    assert second > first
    assert h.key() == second
    h.word(program.panel.pointing_hand_va, 0)
    third = h.key()
    assert third > second
    h.word(h.mode_slot, 3)
    assert h.key() > third
    h.word(profile.address("vr.room_global"), h.scene + 0x100)
    h.word(h.scene + 0x100, profile.address("vr.user_scene_vtable"))
    assert h.key() > third + 1


def test_close_reopen_at_same_address_still_invalidates_actions(
    program: VRProgram, flat_bytes: tuple[bytes, BuildProfile]
) -> None:
    _, profile = flat_bytes
    h = LifetimeHarness(program, profile)
    first = h.key()
    # Two real command-constructor hooks, even with no intervening query and
    # the exact same final object graph: pointer identity must not revive input.
    h.transition()
    h.transition()
    assert h.key() == first + 2
    assert h.read(h.abi.transitions) == 2


def test_foreign_thread_and_unsupported_ui_never_borrow_the_key(
    program: VRProgram, flat_bytes: tuple[bytes, BuildProfile]
) -> None:
    _, profile = flat_bytes
    h = LifetimeHarness(program, profile)
    first = h.key()
    h.word(0x24, 8)
    assert h.call(h.abi.bind) == 0
    assert h.key() == 0
    h.word(0x24, 7)
    assert h.key() == first
    h.word(h.root, profile.address("pause.vtable"))
    assert h.key() == 0
    h.word(h.root, profile.address("vr.room_layer_vtable"))
    h.word(profile.address("engine.loop"), 0)
    assert h.key() == 0


def test_dormant_hook_preserves_original_constructor_and_registers(
    program: VRProgram, flat_bytes: tuple[bytes, BuildProfile]
) -> None:
    _, profile = flat_bytes
    h = LifetimeHarness(program, profile)
    first = h.key()
    h.word(program.inputs.enabled_va, 0)
    registers = {UC_X86_REG_EBX: 31, UC_X86_REG_EDI: 41, UC_X86_REG_ESI: 59}
    for register, value in registers.items():
        h.cpu.reg_write(register, value)
    h.cpu.reg_write(UC_X86_REG_EFLAGS, 0x247)
    h.transition()
    assert h.read(h.abi.epoch) == first
    assert h.read(h.abi.transitions) == 0
    assert h.cpu.reg_read(UC_X86_REG_EFLAGS) == 0x247
    assert all(h.cpu.reg_read(register) == value for register, value in registers.items())
    assert h.key() == 0


@pytest.mark.parametrize(("label", "offset"), VRLoadingCompiler.scene_boundaries())
def test_scene_lifetimes_keep_the_original_loading_target(
    program: VRProgram, flat_bytes: tuple[bytes, BuildProfile], label: str, offset: int
) -> None:
    _, profile = flat_bytes
    h = LifetimeHarness(program, profile)
    first = h.key()
    section = program.image.get_section(VRLoadingCompiler.section_name)
    assert section is not None
    target = program.image.rva_to_va(section.virtual_address) + offset
    registers = {UC_X86_REG_EAX: 23, UC_X86_REG_ECX: 13, UC_X86_REG_EDI: 37}
    for register, value in registers.items():
        h.cpu.reg_write(register, value)
    h.cpu.reg_write(UC_X86_REG_EFLAGS, 0x247)
    h.cpu.reg_write(UC_X86_REG_ESP, _STACK)
    h.cpu.emu_start(profile.site(label).va, target, count=1000)
    assert h.read(h.abi.epoch) == first + 1
    assert h.cpu.reg_read(UC_X86_REG_ESP) == _STACK
    assert h.cpu.reg_read(UC_X86_REG_EFLAGS) == 0x247
    assert all(h.cpu.reg_read(register) == value for register, value in registers.items())


def test_counter_exhaustion_withdraws_instead_of_reusing_an_old_key(
    program: VRProgram, flat_bytes: tuple[bytes, BuildProfile]
) -> None:
    _, profile = flat_bytes
    h = LifetimeHarness(program, profile)
    h.key()
    h.word(h.abi.epoch, 0xFFFFFFFF)
    h.word(h.abi.epoch + 4, 0xFFFFFFFF)
    h.transition()
    assert h.read(h.abi.overflow) == 1
    assert h.key() == 0
    h.transition()
    assert h.key() == 0


def test_lifetime_carries_without_publishing_a_reused_low_word(
    program: VRProgram, flat_bytes: tuple[bytes, BuildProfile]
) -> None:
    _, profile = flat_bytes
    h = LifetimeHarness(program, profile)
    h.key()
    h.word(h.abi.epoch, 0xFFFFFFFF)
    h.word(h.abi.epoch + 4, 7)
    assert h.key() == (8 << 32) - 1
    h.transition()
    assert h.key() == 8 << 32
    h.transition()
    assert h.key() == (8 << 32) + 1
    assert h.read(h.abi.overflow) == 0


def test_changed_native_transition_is_rejected_before_mutation(
    program: VRProgram, flat_bytes: tuple[bytes, BuildProfile]
) -> None:
    _, profile = flat_bytes
    image = program.image.clone()
    image.write_bytes(image.va_to_offset(profile.site("vr.input_transition_begin").va), b"\xcc")
    before = image.to_bytes()
    with pytest.raises(PatchError, match="transition anchor"):
        compile_input_lifetime(
            image,
            profile=profile,
            panel=program.panel,
            inputs=program.inputs,
            ownership=program.ownership,
        )
    assert image.to_bytes() == before


def test_observer_preserves_the_presenter_chain_and_records_real_owner_changes(
    program: VRProgram, flat_bytes: tuple[bytes, BuildProfile]
) -> None:
    _, profile = flat_bytes
    slot = TransitionFrameCompiler.runtime_abi(program.image).pre_flip_presenter_slot_va
    previous = program.image.read_u32_va(slot)
    h = LifetimeHarness(program, profile, observe=True)
    observer = h.image.read_u32_va(slot)
    registers = {
        UC_X86_REG_EAX: 17,
        UC_X86_REG_EBX: 23,
        UC_X86_REG_ECX: 31,
        UC_X86_REG_EDX: 41,
        UC_X86_REG_EDI: 59,
        UC_X86_REG_ESI: 67,
    }

    def observe() -> int:
        for register, value in registers.items():
            h.cpu.reg_write(register, value)
        h.cpu.reg_write(UC_X86_REG_ESP, _STACK)
        h.cpu.reg_write(UC_X86_REG_EFLAGS, 0x247)
        h.cpu.emu_start(observer, previous, count=2000)
        assert h.cpu.reg_read(UC_X86_REG_ESP) == _STACK
        assert h.cpu.reg_read(UC_X86_REG_EFLAGS) == 0x247
        assert all(h.cpu.reg_read(register) == value for register, value in registers.items())
        return h.read(h.abi.observed_key) | (h.read(h.abi.observed_key + 4) << 32)

    first = observe()
    assert first == h.key() != 0
    assert observe() == first
    h.transition()
    assert observe() == first + 1
    h.word(h.root, profile.address("pause.vtable"))
    assert observe() == 0
    assert h.read(h.abi.observations) == 4


@pytest.mark.parametrize(
    ("decision", "expected"),
    [(0x80000008, (8, 0)), (0x80000002, (2, 0)), (0x80000000, (0, 0)), (0, (14, 4))],
)
@pytest.mark.parametrize("nested", [False, True])
def test_native_shortcut_transaction_filters_then_acknowledges_with_abi_preservation(
    program: VRProgram,
    flat_bytes: tuple[bytes, BuildProfile],
    decision: int,
    expected: tuple[int, int],
    nested: bool,
) -> None:
    _, profile = flat_bytes
    slot = TransitionFrameCompiler.runtime_abi(program.image).pre_flip_presenter_slot_va
    previous = program.image.read_u32_va(slot)
    h = LifetimeHarness(program, profile, shortcuts=True)
    api, module, resolver, result, exception = (
        _HEAP + offset for offset in (0xE100, 0xE200, 0xE300, 0xE400, 0xE500)
    )
    h.word(profile.address("win32.GetModuleHandleA"), module)
    h.word(profile.address("win32.GetProcAddress"), resolver)
    h.cpu.mem_write(module, bytes.fromhex("b8 01 00 00 00 c2 04 00"))
    h.cpu.mem_write(resolver, b"\xb8" + struct.pack("<I", api) + bytes.fromhex("c2 08 00"))
    h.cpu.mem_write(api, bytes.fromhex("c2 08 00"))
    h.cpu.mem_write(previous, h.recipient(previous, result, nested=nested))
    calls: list[int] = []
    handlers: list[int] = []

    def observe(_cpu: object, address: int, _size: int, _context: object) -> None:
        if address == previous:
            handlers.append(h.read(h.read(0) + 4))
        if address == api:
            stack = h.cpu.reg_read(UC_X86_REG_ESP)
            operation, argument = h.read(stack + 4), h.read(stack + 8)
            calls.append(operation)
            assert argument == (h.abi.query if operation == 1 else 0)
            h.cpu.reg_write(UC_X86_REG_EAX, decision if operation == 2 else 1)

    h.cpu.hook_add(UC_HOOK_CODE, observe)
    registers = {UC_X86_REG_EBX: 23, UC_X86_REG_ECX: 31, UC_X86_REG_EDX: 41}
    for register, value in registers.items():
        h.cpu.reg_write(register, value)
    h.cpu.reg_write(UC_X86_REG_EFLAGS, 0x247)
    h.call(h.image.read_u32_va(slot))
    assert calls == [1, 2, 2, 3]
    assert (h.read(result), h.read(result + 4)) == expected
    assert h.read(result + 8) == (2 if nested else 1)
    assert h.read(0) == 0
    assert all(h.cpu.reg_read(register) == value for register, value in registers.items())
    assert h.cpu.reg_read(UC_X86_REG_EFLAGS) == 0x247
    # Real x86 SEH unwind entry: invalidate ownership without calling the runtime
    # or native UI from an exception handler. A search alone preserves the key.
    first = h.key()
    h.word(_STACK + 4, exception)
    h.word(exception + 4, 0)
    assert h.call(handlers[0]) == 1
    assert h.key() == first
    h.word(exception + 4, 6)
    assert h.call(handlers[0]) == 1
    assert h.key() == first + 1
    assert calls == [1, 2, 2, 3]


@pytest.mark.parametrize("initially_loaded", [False, True])
def test_unloaded_runtime_is_never_called_and_replacement_is_resolved(
    program: VRProgram,
    flat_bytes: tuple[bytes, BuildProfile],
    initially_loaded: bool,
) -> None:
    _, profile = flat_bytes
    h = LifetimeHarness(program, profile, shortcuts=True)
    slot = TransitionFrameCompiler.runtime_abi(program.image).pre_flip_presenter_slot_va
    previous = program.image.read_u32_va(slot)
    first, replacement, module, resolver, result = (
        _HEAP + offset for offset in (0xE100, 0xE200, 0xE300, 0xE400, 0xE500)
    )
    h.word(profile.address("win32.GetModuleHandleA"), module)
    h.word(profile.address("win32.GetProcAddress"), resolver)
    for address, cleanup in ((first, 8), (replacement, 8), (module, 4), (resolver, 8)):
        h.cpu.mem_write(address, bytes((0xC2, cleanup, 0)))
    h.cpu.mem_write(previous, h.recipient(previous, result, nested=False))
    state = {"module": int(initially_loaded), "unload": True}
    calls: list[tuple[int, int]] = []

    def observe(_cpu: object, address: int, _size: int, _context: object) -> None:
        if address == module:
            h.cpu.reg_write(UC_X86_REG_EAX, state["module"])
        if address == resolver:
            h.cpu.reg_write(UC_X86_REG_EAX, first if state["module"] == 1 else replacement)
        if address == previous and state["unload"]:
            state["module"] = 0
        if address in (first, replacement):
            assert state["module"] != 0, "Native consumer called an unloaded runtime"
            operation = h.read(h.cpu.reg_read(UC_X86_REG_ESP) + 4)
            calls.append((address, operation))
            h.cpu.reg_write(UC_X86_REG_EAX, 0x80000008 if operation == 2 else 1)

    h.cpu.hook_add(UC_HOOK_CODE, observe)
    h.call(h.image.read_u32_va(slot))
    assert calls == ([(first, 1)] if initially_loaded else [])
    assert (h.read(result), h.read(result + 4)) == (14, 4)
    state.update(module=2, unload=False)
    h.word(result + 8, 0)
    h.call(h.image.read_u32_va(slot))
    assert calls[-4:] == [(replacement, operation) for operation in (1, 2, 2, 3)]
    assert (h.read(result), h.read(result + 4)) == (8, 0)
