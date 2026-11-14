"""Execute selected-item snapshots without replacing original game decisions."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE, UC_PROT_EXEC, UC_PROT_READ
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.vr_item_hint import VRItemHintCompiler
from gk3hd.patch.model import PatchError
from gk3hd.vr.items import encode_catalog
from tests.unit.patch.test_vr_panel import _linked_panel
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine

if TYPE_CHECKING:
    from unicorn import Uc


class HintHarness:
    """Observe native accessors and the display-only renderer recipient."""

    def __init__(self) -> None:
        image, self.panel, self.previous = _linked_panel(paired=True)
        activation = image.add_section(".hintact", bytes(0x1000), 0xC0000040)
        self.enabled = image.rva_to_va(activation.virtual_address)
        self.world_ready = self.enabled + 4
        self.compiler = VRItemHintCompiler(
            profile=GOG_BUILD,
            panel=self.panel,
            input_enabled_va=self.enabled,
            world_ready_va=self.world_ready,
            expected_presenter_va=self.previous,
        )
        self.compiler.apply(image)
        self.compiler.postcheck(image)
        self.image = image
        self.abi = self.compiler.abi(image)
        self.cpu = _machine(image)
        self.cpu.mem_map(0, 0x1000)
        self.word(0, 0x12345678)
        self.root, self.engine, self.services, self.game_state = (
            _HEAP + offset for offset in (0x1000, 0x2000, 0x3000, 0x4000)
        )
        self.module, self.resolve, self.bridge = (
            _HEAP + offset for offset in (0xA000, 0xA100, 0xA200)
        )
        self.name = _HEAP + 0xB000
        self.item = 104
        self.requests: list[tuple[int, str]] = []
        self.presented = 0
        self.reenter = False
        for address, value in (
            (self.enabled, 1),
            (self.world_ready, 1),
            (self.panel.enabled_va, 1),
            (self.panel.submitted_frames_va, 1),
            (self.panel.frame_va + 64, 1),
            (self.panel.frame_va + 68, 1),
            (self.panel.frame_va + 116, 1),
            (self.panel.pointing_hand_va, 1),
            (self.root, GOG_BUILD.address("inventory.vtable")),
            (GOG_BUILD.address("engine.loop"), self.engine),
            (self.engine + 0x444, self.services),
            (self.services + 0x38, self.game_state),
            (GOG_BUILD.address("win32.GetModuleHandleA"), self.module),
            (GOG_BUILD.address("win32.GetProcAddress"), self.resolve),
            (GOG_BUILD.address("high_resolution_3d.render_wrapper_ptr"), _HEAP + 0xC000),
            (_HEAP + 0xC4E8, _HEAP + 0xC800),
        ):
            self.word(address, value)
        self.cpu.mem_write(self.name, b"NOTEPAD\0")
        for address, cleanup in (
            (self.previous, 0),
            (self.panel.composition_presenter_va, 0),
            (GOG_BUILD.address("ui.current_layer"), 0),
            (GOG_BUILD.site("vr.active_inventory_item").va, 0),
            (GOG_BUILD.site("vr.inventory_item_name").va, 0),
            (self.module, 4),
            (self.resolve, 8),
            (self.bridge, 16),
        ):
            self.cpu.mem_write(
                address, b"\xc3" if not cleanup else b"\xc2" + struct.pack("<H", cleanup)
            )
        self.cpu.hook_add(UC_HOOK_CODE, self.observe)
        self.cpu.mem_protect(self.abi.presenter_va, 0x1000, UC_PROT_READ | UC_PROT_EXEC)

    def word(self, address: int, value: int) -> None:
        self.cpu.mem_write(address, struct.pack("<I", value))

    def read(self, address: int) -> int:
        return struct.unpack("<I", self.cpu.mem_read(address, 4))[0]

    def observe(self, cpu: Uc, address: int, _size: int, _context: object) -> None:
        if address == self.previous:
            self.presented += 1
            if self.reenter:
                self.reenter = False
                stack = cpu.reg_read(UC_X86_REG_ESP)
                self.word(stack - 4, address)
                cpu.reg_write(UC_X86_REG_ESP, stack - 4)
                cpu.reg_write(UC_X86_REG_EAX, 0)
                cpu.reg_write(UC_X86_REG_EIP, self.abi.presenter_va)
        if address == GOG_BUILD.address("ui.current_layer"):
            cpu.reg_write(UC_X86_REG_EAX, self.root)
        if address == GOG_BUILD.site("vr.active_inventory_item").va:
            assert cpu.reg_read(UC_X86_REG_ECX) == self.game_state
            cpu.reg_write(UC_X86_REG_EAX, self.item)
        if address == GOG_BUILD.site("vr.inventory_item_name").va:
            assert self.read(cpu.reg_read(UC_X86_REG_ESP) + 4) == self.item
            cpu.reg_write(UC_X86_REG_EAX, self.name)
        if address in (self.module, self.resolve):
            cpu.reg_write(UC_X86_REG_EAX, 1 if address == self.module else self.bridge)
        if address == self.bridge:
            device, request, catalog, length = struct.unpack(
                "<4I", cpu.mem_read(cpu.reg_read(UC_X86_REG_ESP) + 4, 16)
            )
            assert device == _HEAP + 0xC800
            assert bytes(cpu.mem_read(catalog, length)) == encode_catalog(())
            assert self.read(request) == 104
            name = bytes(cpu.mem_read(request + 8, 96)).split(b"\0", 1)[0].decode()
            self.requests.append((self.read(request + 4), name))
            cpu.reg_write(UC_X86_REG_EAX, 0)

    def invoke(self) -> None:
        self.word(_STACK, _RETURN)
        self.cpu.reg_write(UC_X86_REG_ESP, _STACK)
        self.cpu.emu_start(self.abi.presenter_va, _RETURN, count=5000)
        assert self.cpu.reg_read(UC_X86_REG_ESP) == _STACK + 4
        assert self.read(0) == 0x12345678


@pytest.mark.parametrize("hand", [0, 1])
@pytest.mark.parametrize("owner", ["inventory.vtable", "vr.room_layer_vtable"])
def test_original_item_mapping_is_used_without_changing_game_state(hand: int, owner: str) -> None:
    h = HintHarness()
    h.word(h.panel.pointing_hand_va, hand)
    h.word(h.root, GOG_BUILD.address(owner))
    h.invoke()
    assert h.requests == [(104, "NOTEPAD")]
    h.item = 0
    h.invoke()
    assert h.requests[-1] == (0, "")
    assert h.presented == 2


@pytest.mark.parametrize("reason", ["focus", "tracking", "inactive", "frame", "modal", "oversized"])
def test_current_owner_or_input_loss_withdraws_the_item_hint(reason: str) -> None:
    h = HintHarness()
    h.invoke()
    if reason == "focus":
        h.word(h.panel.frame_va + 64, 0)
    elif reason == "tracking":
        h.word(h.panel.frame_va + 116, 0)
    elif reason == "inactive":
        h.word(h.enabled, 0)
    elif reason == "frame":
        h.word(h.panel.completion_result_va, 1)
    elif reason == "modal":
        h.word(h.root, GOG_BUILD.address("pause.vtable"))
    else:
        h.item = 142
    h.invoke()
    assert h.requests[-1] == (0, "")


@pytest.mark.parametrize(
    "kind",
    ["vr.action_menu_vtable", "vr.toolbar_vtable", "vr.action_skip_vtable", "console.vtable"],
)
def test_visible_native_interaction_owners_have_priority(kind: str) -> None:
    h = HintHarness()
    children, child = _HEAP + 0xD000, _HEAP + 0xD100
    for address, value in (
        (h.root + 0x4C, children),
        (h.root + 0x50, 1),
        (children, child),
        (child, GOG_BUILD.address(kind)),
    ):
        h.word(address, value)
    h.cpu.mem_write(child + 0x18, b"\1\1")
    h.invoke()
    assert h.requests == [(0, "")]
    h.cpu.mem_write(child + 0x18, b"\0\1")
    h.invoke()
    assert h.requests[-1] == (104, "NOTEPAD")


def test_unterminated_name_does_not_escape_the_fixed_request() -> None:
    h = HintHarness()
    h.cpu.mem_write(h.name, b"A" * 120)
    h.invoke()
    assert h.requests == [(0, "")]


def test_catalog_truncation_is_rejected_before_rebuilding_code() -> None:
    h = HintHarness()
    section = h.image.get_section(h.compiler.section_name)
    assert section is not None
    h.image.write_u32_va(h.image.rva_to_va(section.virtual_address) + 8, 2**32 - 1)
    with pytest.raises(PatchError, match="catalog exceeds"):
        h.compiler.catalog_bytes(h.image)


def test_nested_painting_does_not_repeat_item_snapshots() -> None:
    h = HintHarness()
    h.reenter = True
    h.invoke()
    assert h.requests == [(104, "NOTEPAD")]


def test_dormant_player_does_not_resolve_or_call_an_xr_recipient() -> None:
    h = HintHarness()
    h.word(h.enabled, 0)
    h.invoke()
    assert not h.requests
    assert h.presented == 1


@pytest.mark.parametrize("hand", [0, 1])
@pytest.mark.parametrize("ready", [0, 2])
def test_world_hint_yields_to_rayless_teleport_and_fade_ownership(hand: int, ready: int) -> None:
    h = HintHarness()
    h.word(h.panel.pointing_hand_va, hand)
    h.word(h.root, GOG_BUILD.address("vr.room_layer_vtable"))
    h.invoke()
    assert h.requests[-1] == (104, "NOTEPAD")
    h.word(h.world_ready, ready)
    h.invoke()
    assert h.requests[-1] == (0, "")
    assert h.item == 104
    h.word(h.world_ready, 1)
    h.invoke()
    assert h.requests[-1] == (104, "NOTEPAD")


def test_inventory_does_not_require_a_world_ray_to_show_its_selected_item() -> None:
    h = HintHarness()
    h.word(h.world_ready, 0)
    h.invoke()
    assert h.requests == [(104, "NOTEPAD")]
