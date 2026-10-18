"""Execute native text ownership, at-most-once editing and cancellation."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.vr_text import VRTextCompiler
from gk3hd.patch.model import PatchError
from tests.unit.patch.test_vr_panel import _linked_panel
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine

if TYPE_CHECKING:
    from unicorn import Uc


class TextHarness:
    """Observe engine callbacks without implementing a competing text editor."""

    def __init__(self) -> None:
        image, self.panel, previous = _linked_panel()
        self.previous = previous
        self.profile = GOG_BUILD
        table = self.profile.address("savegame_edit.vtable")
        for off, target in ((0x64, "vr.text_key"), (0x6C, "vr.save_character")):
            image.write_u32_va(table + off, self.profile.site(target).va)
        image.write_u32_va(
            self.profile.address("savegame.vtable") + 0x6C,
            self.profile.site("vr.container_text_route").va,
        )
        self.compiler = VRTextCompiler(
            profile=self.profile, panel=self.panel, expected_presenter_va=previous
        )
        self.compiler.apply(image)
        self.compiler.postcheck(image)
        self.image = image
        self.abi = self.compiler.abi(image)
        self.machine = _machine(image)
        self.machine.mem_map(0, 0x1000)
        self.word(0, 0x12345678)
        self.engine, self.system, self.manager, _editor, self.layer = (
            _HEAP + off for off in (0x1000, 0x2000, 0x3000, 0x4000, 0x5000)
        )
        self.editor = self.layer + 0x340
        self.word(self.profile.address("engine.loop"), self.engine)
        self.word(self.engine + 0x444, self.system)
        self.word(self.system + 0x44, self.manager)
        self.word(self.manager + 0x64, self.editor)
        self.word(self.editor, table)
        self.word(self.editor + 0x78, self.layer)
        self.word(self.layer, self.profile.address("savegame.vtable"))
        self.word(self.layer + 0x4C, self.manager + 0x100)
        self.word(self.layer + 0x50, 1)
        self.word(self.manager + 0x100, self.editor)
        self.machine.mem_write(self.editor + 0x18, b"\x01\x01")
        self.word(self.abi.enabled_va, 1)
        self.word(self.panel.enabled_va, 1)
        self.word(self.panel.frame_va + 64, 1)
        self.word(self.panel.frame_va + 168, 1)
        self.word(self.panel.frame_va + 68 + 48, 1)
        self.unreadable = 0
        self.callbacks: list[tuple[str, int, int]] = []
        self.presented = 0
        self.composed = 0
        self.machine.mem_write(previous, b"\xc3")
        self.machine.mem_write(self.panel.composition_presenter_va, b"\xc3")
        self.machine.mem_write(self.profile.address("ui.current_layer"), b"\xc3")
        readable = _HEAP + 0xA000
        self.word(self.profile.address("win32.IsBadReadPtr"), readable)
        self.machine.mem_write(readable, bytes.fromhex("c2 08 00"))
        for name in (
            "vr.save_character",
            "vr.text_character",
            "vr.text_key",
            "vr.multiline_text_key",
        ):
            self.machine.mem_write(self.profile.site(name).va, bytes.fromhex("c2 08 00"))
        self.machine.hook_add(UC_HOOK_CODE, self.observe)

    def observe(self, current: Uc, address: int, _size: int, _context: object) -> None:
        if address == self.previous:
            self.presented += 1
        if address == self.panel.composition_presenter_va:
            self.composed += 1
        if address == self.profile.address("ui.current_layer"):
            current.reg_write(UC_X86_REG_EAX, self.layer)
        if address == _HEAP + 0xA000:
            pointer = self.read(current.reg_read(UC_X86_REG_ESP) + 4)
            current.reg_write(UC_X86_REG_EAX, int(pointer in (self.unreadable, 0)))
        for name in (
            "vr.save_character",
            "vr.text_character",
            "vr.text_key",
            "vr.multiline_text_key",
        ):
            if address == self.profile.site(name).va:
                assert current.reg_read(UC_X86_REG_ECX) == self.editor
                value, flags = struct.unpack(
                    "<2I", current.mem_read(current.reg_read(UC_X86_REG_ESP) + 4, 8)
                )
                assert self.read(self.abi.request_va) == 0
                self.callbacks.append((name, value, flags))

    def word(self, address: int, value: int) -> None:
        self.machine.mem_write(address, struct.pack("<I", value))

    def read(self, address: int) -> int:
        return struct.unpack("<I", self.machine.mem_read(address, 4))[0]

    def invoke(self) -> None:
        self.machine.mem_write(_STACK, struct.pack("<I", _RETURN))
        self.machine.reg_write(UC_X86_REG_ESP, _STACK)
        self.machine.emu_start(self.abi.presenter_va, _RETURN, count=3000)
        assert self.machine.reg_read(UC_X86_REG_ESP) == _STACK + 4
        assert self.read(0) == 0x12345678

    def request(self, value: int, *, kind: int = 1, epoch: int | None = None) -> None:
        self.word(
            self.abi.request_epoch_va, self.read(self.abi.epoch_va) if epoch is None else epoch
        )
        self.word(self.abi.kind_va, kind)
        self.word(self.abi.value_va, value)
        self.word(self.abi.request_va, 1)


def test_save_editor_uses_native_printable_character_once() -> None:
    h = TextHarness()
    h.invoke()
    assert h.read(h.abi.focus_va) == h.editor
    assert h.read(h.abi.layer_va) == h.layer
    h.request(ord("V"))
    h.invoke()
    h.invoke()
    assert h.callbacks == [("vr.save_character", ord("V"), 1)]
    assert h.read(h.abi.accepted_va) == 1
    assert h.read(h.abi.result_va) == 1
    assert h.presented == 3


class KeyboardHarness(TextHarness):
    """Exercise the emitted DLL/epoch bridge, including hostile/stale output."""

    module = _HEAP + 0xB000
    resolver = _HEAP + 0xB100
    bridge = _HEAP + 0xB200
    wrapper = _HEAP + 0xC000

    def __init__(self) -> None:
        super().__init__()
        self.output = (0, 0, 0)
        self.calls: list[tuple[int, int]] = []
        self.module_present = self.export_present = True
        self.error = 0
        self.word(self.abi.keyboard_enabled_va, 1)
        self.word(self.profile.address("win32.GetModuleHandleA"), self.module)
        self.word(self.profile.address("win32.GetProcAddress"), self.resolver)
        self.word(self.profile.address("high_resolution_3d.render_wrapper_ptr"), self.wrapper)
        self.word(self.wrapper + 0x4E8, 0x12340000)
        self.machine.mem_write(self.module, bytes.fromhex("c2 04 00"))
        self.machine.mem_write(self.resolver, bytes.fromhex("c2 08 00"))
        self.machine.mem_write(self.bridge, bytes.fromhex("c2 08 00"))

    def observe(self, current: Uc, address: int, _size: int, _context: object) -> None:
        super().observe(current, address, _size, _context)
        if address == self.module:
            current.reg_write(UC_X86_REG_EAX, int(self.module_present))
        if address == self.resolver:
            current.reg_write(UC_X86_REG_EAX, self.bridge if self.export_present else 0)
        if address == self.bridge:
            device, frame = struct.unpack(
                "<2I", current.mem_read(current.reg_read(UC_X86_REG_ESP) + 4, 8)
            )
            assert device == 0x12340000
            assert frame == self.abi.keyboard_frame_va
            size, epoch, available = struct.unpack("<3I", current.mem_read(frame, 12))
            assert size == 24
            self.calls.append((epoch, available))
            current.mem_write(frame + 12, struct.pack("<3I", *self.output))
            current.reg_write(UC_X86_REG_EAX, self.error)


class ContainerTextHarness(TextHarness):
    """An ordinary editor reached through native nested child dispatch."""

    container_table = _HEAP + 0xD000
    editor_table = _HEAP + 0xD100
    inert_table = _HEAP + 0xD200
    children = _HEAP + 0xD300
    font = _HEAP + 0xD400
    page = _HEAP + 0xE000
    inert = _HEAP + 0xE100
    page_children = _HEAP + 0xE200

    def __init__(self) -> None:
        super().__init__()
        self.word(self.container_table + 0x6C, self.profile.site("vr.container_text_route").va)
        self.word(self.editor_table + 0x64, self.profile.site("vr.text_key").va)
        self.word(self.editor_table + 0x6C, self.profile.site("vr.text_character").va)
        self.word(self.inert_table + 0x6C, self.profile.site("vr.no_text").va)
        self.word(self.editor, self.editor_table)
        self.word(self.editor + 0x2C, self.font)
        # Generic text widgets do not use SaveEditBox's parent field.
        self.word(self.editor + 0x78, 0)
        for node, table in (
            (self.layer, self.container_table),
            (self.page, self.container_table),
            (self.inert, self.inert_table),
        ):
            self.word(node, table)
            self.machine.mem_write(node + 0x18, b"\x01\x01")
        self.word(self.layer + 0x4C, self.children)
        self.word(self.layer + 0x50, 2)
        self.word(self.children, self.inert)
        self.word(self.children + 4, self.page)
        self.word(self.page + 0x4C, self.page_children)
        self.word(self.page + 0x50, 1)
        self.word(self.page_children, self.editor)
        self.word(self.manager + 0x60, 0)
        self.word(self.manager + 0x64, 0)


class MultilineTextHarness(ContainerTextHarness):
    """Original multiline editor preserves its separate native key handler."""

    def __init__(self) -> None:
        super().__init__()
        self.word(self.editor_table + 0x64, self.profile.site("vr.multiline_text_key").va)


@pytest.mark.parametrize(
    ("kind", "value"), [(1, ord("n")), (2, 8), (2, 46), (2, 37), (2, 39), (2, 36), (2, 35), (3, 13)]
)
def test_multiline_editor_preserves_native_character_and_key_semantics(
    kind: int, value: int
) -> None:
    h = MultilineTextHarness()
    h.invoke()
    assert h.read(h.abi.focus_va) == h.editor
    h.request(value, kind=kind)
    h.invoke()
    h.invoke()
    handler = "vr.text_character" if kind == 1 else "vr.multiline_text_key"
    assert h.callbacks == [(handler, value, 1)]
    assert h.read(h.abi.accepted_va) == 1


def test_multiline_editor_with_unreadable_line_state_cannot_receive_input() -> None:
    h = MultilineTextHarness()

    def truncated(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == _HEAP + 0xA000:
            pointer, size = struct.unpack(
                "<2I", current.mem_read(current.reg_read(UC_X86_REG_ESP) + 4, 8)
            )
            if pointer == h.editor and size > 0x78:
                current.reg_write(UC_X86_REG_EAX, 1)

    h.machine.hook_add(UC_HOOK_CODE, truncated)
    h.invoke()
    h.request(36, kind=2)
    h.invoke()
    assert h.read(h.abi.focus_va) == 0
    assert not h.callbacks


@pytest.mark.parametrize(("kind", "value"), [(1, ord("v")), (2, 8), (2, 36), (2, 35), (3, 13)])
def test_nested_native_editor_uses_its_original_callbacks_without_manager_focus(
    kind: int, value: int
) -> None:
    h = ContainerTextHarness()
    h.invoke()
    assert h.read(h.abi.focus_va) == h.editor
    assert h.read(h.abi.layer_va) == h.layer
    h.request(value, kind=kind)
    h.invoke()
    handler = "vr.text_character" if kind == 1 else "vr.text_key"
    assert h.callbacks == [(handler, value, 1)]
    assert h.read(h.abi.accepted_va) == 1


@pytest.mark.parametrize(
    "loss",
    [
        "hidden_page",
        "hidden_root",
        "disabled_editor",
        "custom_handler",
        "wrong_key",
        "font",
        "removed",
        "unreadable",
        "cycle",
        "count",
        "null_array",
    ],
)
@pytest.mark.parametrize("harness", [ContainerTextHarness, MultilineTextHarness])
def test_native_container_changes_cannot_deliver_pending_text(
    loss: str, harness: type[ContainerTextHarness]
) -> None:
    h = harness()
    h.invoke()
    h.request(ord("X"))
    epoch = h.read(h.abi.epoch_va)
    writes = {
        "custom_handler": (h.inert_table + 0x6C, h.profile.site("vr.save_character").va),
        "wrong_key": (h.editor_table + 0x64, h.profile.site("vr.no_text").va),
        "font": (h.editor + 0x2C, 0),
        "removed": (h.page_children, h.inert),
        "cycle": (h.page_children, h.page),
        "count": (h.page + 0x50, 257),
        "null_array": (h.page + 0x4C, 0),
    }
    if loss in writes:
        h.word(*writes[loss])
    elif loss == "unreadable":
        h.unreadable = h.page_children
    else:
        flags = {
            "hidden_page": h.page + 0x18,
            "hidden_root": h.layer + 0x18,
            "disabled_editor": h.editor + 0x19,
        }
        h.machine.mem_write(flags[loss], b"\x00")
    h.invoke()
    assert not h.callbacks
    assert h.read(h.abi.focus_va) == h.read(h.abi.layer_va) == 0
    assert h.read(h.abi.epoch_va) != epoch


def test_native_editor_order_change_invalidates_old_recipient() -> None:
    h = ContainerTextHarness()
    h.invoke()
    h.request(ord("X"))
    second = _HEAP + 0xE400
    h.word(second, h.editor_table)
    h.word(second + 0x2C, h.font)
    h.machine.mem_write(second + 0x18, b"\x01\x01")
    h.word(h.children, second)
    h.invoke()
    assert not h.callbacks
    assert h.read(h.abi.focus_va) == second
    assert h.read(h.abi.result_va) == 2
    h.editor = second  # Observe the newly qualified native recipient.
    h.request(ord("Y"))
    h.invoke()
    assert h.callbacks == [("vr.text_character", ord("Y"), 1)]


def test_native_editor_does_not_reinterpret_its_fields_as_children() -> None:
    h = ContainerTextHarness()
    h.word(h.editor + 0x4C, 0)
    h.word(h.editor + 0x50, 0xFFFFFFFF)
    h.invoke()
    h.request(ord("A"))
    h.invoke()
    assert h.callbacks == [("vr.text_character", ord("A"), 1)]


def test_hidden_native_recipient_is_not_skipped_in_favor_of_a_later_editor() -> None:
    h = ContainerTextHarness()
    second = _HEAP + 0xE400
    h.word(second, h.editor_table)
    h.word(second + 0x2C, h.font)
    h.machine.mem_write(second + 0x18, b"\x01\x01")
    h.machine.mem_write(h.editor + 0x18, b"\x00")
    h.word(h.page + 0x50, 2)
    h.word(h.page_children + 4, second)
    h.invoke()
    assert h.read(h.abi.focus_va) == 0
    h.request(ord("X"))
    h.invoke()
    assert not h.callbacks


def test_hidden_custom_text_handler_is_not_bypassed_to_reach_an_editor() -> None:
    h = ContainerTextHarness()
    h.machine.mem_write(h.inert + 0x18, b"\x00")
    h.word(h.inert_table + 0x6C, h.profile.site("vr.save_character").va)
    h.invoke()
    assert h.read(h.abi.focus_va) == 0


def test_renderer_keyboard_action_uses_requalified_native_editor_once() -> None:
    h = KeyboardHarness()
    h.invoke()
    epoch = h.read(h.abi.epoch_va)
    assert h.calls == [(epoch, 1)]
    h.output = (epoch, 1, ord("K"))
    h.invoke()
    assert h.callbacks == [("vr.save_character", ord("K"), 1)]
    h.output = (0, 0, 0)
    h.invoke()
    assert h.read(h.abi.accepted_va) == 1


@pytest.mark.parametrize(("kind", "value"), [(1, 31), (1, 127), (2, 13), (2, 27), (3, 65)])
def test_renderer_keyboard_rejects_invalid_text_edit_and_confirmation_actions(
    kind: int, value: int
) -> None:
    h = KeyboardHarness()
    h.invoke()
    h.output = (h.read(h.abi.epoch_va), kind, value)
    h.invoke()
    assert not h.callbacks
    assert h.read(h.abi.rejected_va) == 1


@pytest.mark.parametrize("change", ["layer", "focus", "hand", "disable"])
def test_renderer_keyboard_event_cannot_cross_native_ownership_change(change: str) -> None:
    h = KeyboardHarness()
    h.invoke()
    h.output = (h.read(h.abi.epoch_va), 1, ord("K"))
    if change == "layer":
        h.word(h.layer, 0)
    elif change == "focus":
        h.word(h.panel.frame_va + 64, 0)
    elif change == "hand":
        h.word(h.panel.frame_va + 168, 0)
        h.word(h.panel.frame_va + 68, 1)
    else:
        h.word(h.abi.keyboard_enabled_va, 0)
    h.invoke()
    assert not h.callbacks
    if change != "hand":
        assert h.calls[-1] == (0, 0)


def test_renderer_keyboard_never_overwrites_an_occupied_text_mailbox() -> None:
    h = KeyboardHarness()
    h.invoke()
    h.request(ord("A"))
    h.output = (h.read(h.abi.epoch_va), 1, ord("B"))
    h.invoke()
    assert h.calls[-1][1] == 0
    assert h.callbacks == [("vr.save_character", ord("A"), 1)]


@pytest.mark.parametrize("failure", ["module", "export", "device", "result"])
def test_unavailable_keyboard_does_not_break_native_text_sink(failure: str) -> None:
    h = KeyboardHarness()
    if failure == "module":
        h.module_present = False
    elif failure == "export":
        h.export_present = False
    elif failure == "device":
        h.word(h.wrapper + 0x4E8, 0)
    else:
        h.error = 0x80004005
    h.invoke()
    h.output = (h.read(h.abi.epoch_va), 1, ord("B"))
    h.request(ord("A"))
    h.invoke()
    assert h.callbacks == [("vr.save_character", ord("A"), 1)]
    assert h.read(h.abi.request_va) == 0


@pytest.mark.parametrize("key", [8, 46, 37, 39, 36, 35])
def test_edit_keys_use_native_handler_without_host_events(key: int) -> None:
    h = TextHarness()
    h.invoke()
    h.request(key, kind=2)
    h.invoke()
    assert h.callbacks == [("vr.text_key", key, 1)]


@pytest.mark.parametrize(
    ("kind", "value"),
    [(1, 0), (1, 13), (1, 31), (1, 127), (1, 256), (2, 13), (2, 27), (2, 65), (3, 65)],
)
def test_invalid_text_and_shortcuts_cannot_escape_the_editor(kind: int, value: int) -> None:
    h = TextHarness()
    h.invoke()
    h.request(value, kind=kind)
    h.invoke()
    assert h.callbacks == []
    assert h.read(h.abi.result_va) == 2
    assert h.read(h.abi.rejected_va) == 1


@pytest.mark.parametrize(
    "harness", [TextHarness, ContainerTextHarness, KeyboardHarness, MultilineTextHarness]
)
def test_explicit_confirmation_uses_native_return_handler_once(
    harness: type[TextHarness],
) -> None:
    h = harness()
    h.invoke()
    if isinstance(h, KeyboardHarness):
        h.output = (h.read(h.abi.epoch_va), 3, 13)
    else:
        h.request(13, kind=3)
    h.invoke()
    if isinstance(h, KeyboardHarness):
        h.output = (0, 0, 0)
    h.invoke()
    handler = "vr.multiline_text_key" if isinstance(h, MultilineTextHarness) else "vr.text_key"
    assert h.callbacks == [(handler, 13, 1)]
    assert h.read(h.abi.accepted_va) == 1


@pytest.mark.parametrize("modifier", [0x08, 0x10, 0x20, 0x38])
def test_host_modifiers_cannot_change_confirmation_semantics(modifier: int) -> None:
    h = ContainerTextHarness()
    h.invoke()
    h.word(h.engine + 0x518, modifier)
    h.request(13, kind=3)
    h.invoke()
    assert not h.callbacks
    assert h.read(h.abi.result_va) == 2


def test_confirmation_that_retires_native_editor_does_not_repeat_or_revisit_it() -> None:
    h = ContainerTextHarness()
    h.invoke()
    h.request(13, kind=3)

    def retire(_current: Uc, address: int, _size: int, _context: object) -> None:
        if address == h.profile.site("vr.text_key").va:
            h.word(h.page + 0x50, 0)
            h.unreadable = h.editor

    h.machine.hook_add(UC_HOOK_CODE, retire)
    h.invoke()
    h.invoke()
    assert h.callbacks == [("vr.text_key", 13, 1)]
    assert h.read(h.abi.focus_va) == 0
    assert h.read(h.abi.request_va) == 0


@pytest.mark.parametrize(
    "loss",
    [
        "focus",
        "tracking",
        "hand",
        "hidden",
        "disabled",
        "parent",
        "class",
        "layer",
        "xr",
        "completion",
        "switch",
        "null",
        "unreadable",
    ],
)
@pytest.mark.parametrize(("kind", "value"), [(1, ord("A")), (3, 13)])
def test_lost_ownership_rejects_pending_text_and_retires_target(
    loss: str, kind: int, value: int
) -> None:
    h = TextHarness()
    h.invoke()
    old = h.read(h.abi.epoch_va)
    h.request(value, kind=kind)
    writes = {
        "focus": (h.panel.frame_va + 64, 0),
        "tracking": (h.panel.frame_va + 68 + 48, 0),
        "hand": (h.panel.frame_va + 168, 2),
        "parent": (h.editor + 0x78, h.layer + 0x100),
        "class": (h.editor, h.profile.address("room_text.vtable")),
        "xr": (h.panel.result_va, 1),
        "completion": (h.panel.completion_result_va, 1),
        "switch": (h.abi.enabled_va, 0),
        "null": (h.layer + 0x4C, 0),
    }
    if loss in writes:
        h.word(*writes[loss])
    elif loss in {"hidden", "disabled"}:
        h.machine.mem_write(h.editor + (0x18 if loss == "hidden" else 0x19), b"\x00")
    elif loss == "layer":
        h.layer += 0x100
    else:
        h.unreadable = h.editor
    h.invoke()
    assert h.callbacks == []
    assert h.read(h.abi.focus_va) == h.read(h.abi.layer_va) == 0
    assert h.read(h.abi.epoch_va) != old
    assert h.read(h.abi.result_va) == 2


@pytest.mark.parametrize(("kind", "value"), [(1, ord("A")), (3, 13)])
def test_old_epoch_cannot_type_into_or_confirm_a_reactivated_field(kind: int, value: int) -> None:
    h = TextHarness()
    h.invoke()
    old = h.read(h.abi.epoch_va)
    h.word(h.panel.frame_va + 64, 0)
    h.invoke()
    h.word(h.panel.frame_va + 64, 1)
    h.invoke()
    h.request(value, kind=kind, epoch=old)
    h.invoke()
    assert h.callbacks == []
    assert h.read(h.abi.result_va) == 2


@pytest.mark.parametrize(("kind", "value"), [(1, ord("A")), (3, 13)])
def test_nested_native_paint_does_not_repeat_input_or_xr_presentation(
    kind: int, value: int
) -> None:
    h = TextHarness()
    h.invoke()
    h.request(value, kind=kind)
    handler = "vr.save_character" if kind == 1 else "vr.text_key"
    address = h.profile.site(handler).va
    h.machine.mem_write(
        address,
        b"\xe8" + struct.pack("<i", h.abi.presenter_va - address - 5) + bytes.fromhex("c2 08 00"),
    )
    h.invoke()
    assert h.callbacks == [(handler, value, 1)]
    assert h.presented == 2
    assert h.composed == 1


def test_host_modifiers_cannot_turn_edit_keys_into_clipboard_shortcuts() -> None:
    h = TextHarness()
    h.invoke()
    h.word(h.engine + 0x518, 0x10)
    h.request(37, kind=2)
    h.invoke()
    assert h.callbacks == []


def test_hand_handoff_invalidates_a_request_from_the_previous_controller() -> None:
    h = TextHarness()
    h.invoke()
    h.request(ord("A"))
    h.word(h.panel.frame_va + 68, 1)
    h.word(h.panel.frame_va + 168, 0)
    h.invoke()
    assert h.read(h.abi.focus_va) == h.editor
    assert h.callbacks == []
    h.request(ord("B"))
    h.invoke()
    assert h.callbacks == [("vr.save_character", ord("B"), 1)]


@pytest.mark.parametrize("bad", [0, 2, 0xFFFFFFFF])
def test_invalid_epochs_and_mailbox_publication_are_rejected(bad: int) -> None:
    h = TextHarness()
    h.invoke()
    h.request(ord("A"), epoch=0)
    if bad:
        h.word(h.abi.request_epoch_va, h.read(h.abi.epoch_va))
        h.word(h.abi.request_va, bad)
    h.invoke()
    assert h.callbacks == []
    assert h.read(h.abi.request_va) == 0
    assert h.read(h.abi.result_va) == 2


@pytest.mark.parametrize("bad_count", [0, 257, 0xFFFFFFFF])
def test_unbounded_or_empty_child_graph_is_not_a_text_target(bad_count: int) -> None:
    h = TextHarness()
    h.word(h.layer + 0x50, bad_count)
    h.invoke()
    assert h.read(h.abi.focus_va) == 0


def test_mouse_capture_is_not_required_for_the_native_save_editor() -> None:
    h = TextHarness()
    h.word(h.manager + 0x60, 0)
    h.word(h.manager + 0x64, 0)
    h.invoke()
    h.request(ord("A"))
    h.invoke()
    assert h.callbacks == [("vr.save_character", ord("A"), 1)]


@pytest.mark.parametrize("flags", [0, 1, 2, 4, 0x20, 0x40])
def test_only_exception_unwind_retires_text_ownership(flags: int) -> None:
    h = TextHarness()
    h.invoke()
    h.request(ord("A"))
    epoch = h.read(h.abi.epoch_va)
    record = _HEAP + 0xB000
    h.word(record + 4, flags)
    h.machine.mem_write(_STACK, struct.pack("<2I", _RETURN, record))
    h.machine.reg_write(UC_X86_REG_ESP, _STACK)
    h.machine.emu_start(
        h.abi.enabled_va - h.compiler._enabled + h.compiler._unwind, _RETURN, count=200
    )
    assert h.machine.reg_read(UC_X86_REG_EAX) == 1  # ExceptionContinueSearch
    if flags & 0x66:
        assert h.read(h.abi.focus_va) == h.read(h.abi.layer_va) == 0
        assert h.read(h.abi.request_va) == 0
        assert h.read(h.abi.epoch_va) != epoch
        assert h.read(h.abi.result_va) == 3
    else:
        assert h.read(h.abi.focus_va) == h.editor
        assert h.read(h.abi.request_va) == 1
        assert h.read(h.abi.epoch_va) == epoch


@pytest.mark.parametrize("anchor", VRTextCompiler._anchors)
def test_changed_native_dispatch_is_rejected_before_any_mutation(anchor: str) -> None:
    image, panel, previous = _linked_panel()
    image.write_bytes(image.va_to_offset(GOG_BUILD.site(anchor).va), b"\xcc")
    before = image.to_bytes()
    compiler = VRTextCompiler(profile=GOG_BUILD, panel=panel, expected_presenter_va=previous)
    with pytest.raises(PatchError, match="anchor changed"):
        compiler.apply(image)
    assert image.to_bytes() == before


def test_installation_is_dormant_and_native_tampering_is_rejected() -> None:
    h = TextHarness()
    assert h.image.read_u32_va(h.abi.enabled_va) == 0
    h.image.write_bytes(h.image.va_to_offset(h.profile.site("vr.save_character").va), b"\xcc")
    with pytest.raises(PatchError, match="anchor changed"):
        h.compiler.postcheck(h.image)
