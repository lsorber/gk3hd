"""Run the emitted use-on gesture against observable native menu callbacks."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE, UC_PROT_EXEC, UC_PROT_READ
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.vr_item_use import VRItemUseCompiler
from gk3hd.patch.model import PatchError
from tests.unit.patch.test_complete_compilation import _source
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine

if TYPE_CHECKING:
    from unicorn import Uc


class UseHarness:
    """The game supplies the selected item, current layer and offered actions."""

    def __init__(self) -> None:
        self.image = _source(GOG_BUILD)
        self.compiler = VRItemUseCompiler(profile=GOG_BUILD)
        self.compiler.apply(self.image)
        self.compiler.postcheck(self.image)
        self.abi = self.compiler.abi(self.image)
        self.cpu = _machine(self.image)
        self.root, self.engine, self.services, self.state, self.story, self.menu = (
            _HEAP + offset for offset in (0x1000, 0x2000, 0x3000, 0x4000, 0x8000, 0x9000)
        )
        self.children, self.button = _HEAP + 0xA000, _HEAP + 0xB000
        self.owner, self.item, self.verb = self.root, 104, 163
        self.calls: list[tuple[int, int]] = []
        for address, value in (
            (GOG_BUILD.address("engine.loop"), self.engine),
            (self.engine + 0x444, self.services),
            (self.services + 0x38, self.state),
            (self.services + 0x60, self.story),
            (self.story + 0x20, 0x211),
            (self.root, GOG_BUILD.address("inventory.vtable")),
            (self.root + 0x4C, self.children),
            (self.root + 0x50, 1),
            (self.children, self.menu),
            (self.menu, GOG_BUILD.address("vr.action_menu_vtable")),
            (self.menu + 0xCC, 0x1234),
            (self.menu + 0xE0, _HEAP + 0xC000),
            (self.menu + 0x4C, self.children + 0x100),
            (self.menu + 0x50, 1),
            (self.children + 0x100, self.button),
            (self.button, GOG_BUILD.address("ui.button_vtable")),
            (self.button + 0x88, 0x1234),
            (self.button + 0x8C, self.verb),
        ):
            self.word(address, value)
        for obj in (self.root, self.menu, self.button):
            self.cpu.mem_write(obj + 0x18, b"\1\1")
        for address, code in (
            (GOG_BUILD.address("ui.current_layer"), b"\xc3"),
            (GOG_BUILD.site("vr.active_inventory_item").va, b"\xc3"),
            (GOG_BUILD.site("vr.inventory_item_verb").va, b"\xc3"),
            (GOG_BUILD.site("vr.action_menu_handle").va, b"\xc2\x04\0"),
        ):
            self.cpu.mem_write(address, code)
        self.cpu.hook_add(UC_HOOK_CODE, self.observe)
        self.cpu.mem_protect(self.abi.prepare_va, 0x1000, UC_PROT_READ | UC_PROT_EXEC)

    def word(self, address: int, value: int) -> None:
        self.cpu.mem_write(address, struct.pack("<I", value))

    def read(self, address: int) -> int:
        return struct.unpack("<I", self.cpu.mem_read(address, 4))[0]

    def observe(self, cpu: Uc, address: int, _size: int, _context: object) -> None:
        if address == GOG_BUILD.address("ui.current_layer"):
            cpu.reg_write(UC_X86_REG_EAX, self.owner)
        elif address == GOG_BUILD.site("vr.active_inventory_item").va:
            assert cpu.reg_read(UC_X86_REG_ECX) == self.state
            cpu.reg_write(UC_X86_REG_EAX, self.item)
        elif address == GOG_BUILD.site("vr.inventory_item_verb").va:
            stack = cpu.reg_read(UC_X86_REG_ESP)
            assert self.read(stack + 4) == self.item
            self.word(self.read(stack + 8), self.verb)
        elif address == GOG_BUILD.site("vr.action_menu_handle").va:
            receiver = cpu.reg_read(UC_X86_REG_ECX)
            self.calls.append((receiver, self.read(cpu.reg_read(UC_X86_REG_ESP) + 4)))
            # Original HandleAction destroys the menu. Any subsequent access to
            # it or its buttons must fault rather than pass accidentally.
            self.word(GOG_BUILD.address("vr.action_menu_global"), 0)
            self.cpu.mem_unmap(self.menu, 0x1000)
            self.cpu.mem_unmap(self.button, 0x1000)

    def invoke(self, address: int) -> None:
        self.word(_STACK, _RETURN)
        self.cpu.reg_write(UC_X86_REG_ESP, _STACK)
        self.cpu.emu_start(address, _RETURN, count=3000)
        assert self.cpu.reg_read(UC_X86_REG_ESP) == _STACK + 4

    def open_menu(self) -> None:
        self.word(GOG_BUILD.address("vr.action_menu_global"), self.menu)


@pytest.mark.parametrize("layer", ["vr.room_layer_vtable", "inventory.vtable"])
def test_use_follows_original_item_mapping_and_offered_callback_once(layer: str) -> None:
    h = UseHarness()
    h.word(h.root, GOG_BUILD.address(layer))
    h.invoke(h.abi.prepare_va)
    assert h.calls == []
    h.open_menu()
    h.invoke(h.abi.dispatch_va)
    assert h.calls == [(h.menu + 0xC4, 163)]
    assert h.read(h.abi.attempts_va) == 1
    h.invoke(h.abi.dispatch_va)
    assert len(h.calls) == 1


@pytest.mark.parametrize("changed", ["item", "protagonist", "layer", "state"])
def test_changed_native_selection_or_owner_never_reuses_the_attempt(changed: str) -> None:
    h = UseHarness()
    h.invoke(h.abi.prepare_va)
    h.open_menu()
    if changed == "item":
        h.item = 105
    elif changed == "protagonist":
        h.word(h.story + 0x20, 0x212)
    elif changed == "layer":
        h.owner = h.menu
    else:
        h.word(h.services + 0x38, 0)
    h.invoke(h.abi.dispatch_va)
    assert h.calls == []


@pytest.mark.parametrize(
    "reason",
    [
        "absent",
        "hidden",
        "disabled",
        "wrong_verb",
        "wrong_receiver",
        "duplicate",
        "not_owned",
        "oversized",
        "no_target",
        "other_mode",
    ],
)
def test_only_one_offered_enabled_action_may_be_selected(reason: str) -> None:
    h = UseHarness()
    h.invoke(h.abi.prepare_va)
    h.open_menu()
    if reason == "absent":
        h.word(h.menu + 0x50, 0)
    elif reason == "hidden":
        h.cpu.mem_write(h.button + 0x18, b"\0")
    elif reason == "disabled":
        h.word(h.button + 0x98, 4)
    elif reason == "wrong_verb":
        h.word(h.button + 0x8C, 164)
    elif reason == "wrong_receiver":
        h.word(h.button + 0x88, 0x5678)
    elif reason == "duplicate":
        h.word(h.menu + 0x50, 2)
        h.word(h.children + 0x104, h.button)
    elif reason == "not_owned":
        h.word(h.children, h.button)
    elif reason == "oversized":
        h.word(h.menu + 0x50, 257)
    elif reason == "no_target":
        h.word(h.menu + 0xE0, 0)
    else:
        h.cpu.mem_write(h.menu + 0x100, b"\1")
    h.invoke(h.abi.dispatch_va)
    assert h.calls == []
    assert h.read(GOG_BUILD.address("vr.action_menu_global")) == h.menu


@pytest.mark.parametrize("blocked", ["existing_menu", "no_item", "unsupported_owner"])
def test_ordinary_menu_clicks_and_unselected_items_keep_native_behaviour(blocked: str) -> None:
    h = UseHarness()
    if blocked == "existing_menu":
        h.open_menu()
    elif blocked == "no_item":
        h.item = 0
    else:
        h.word(h.root, GOG_BUILD.address("pause.vtable"))
    h.invoke(h.abi.prepare_va)
    h.open_menu()
    h.invoke(h.abi.dispatch_va)
    assert h.calls == []


def test_modified_native_callback_is_rejected_before_mutation() -> None:
    image = _source(GOG_BUILD)
    image.write_bytes(image.va_to_offset(GOG_BUILD.site("vr.action_menu_handle").va), b"\xcc")
    original = image.to_bytes()
    with pytest.raises(PatchError, match="native anchor changed"):
        VRItemUseCompiler(profile=GOG_BUILD).apply(image)
    assert image.to_bytes() == original
