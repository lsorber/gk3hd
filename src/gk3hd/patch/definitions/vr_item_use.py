"""Use a selected item through an actually offered native action."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile


@dataclass(frozen=True, slots=True)
class VRItemUseABI:
    """Synchronous before/after hooks for a genuine Select release."""

    prepare_va: int
    dispatch_va: int
    attempts_va: int


@dataclass(frozen=True, slots=True, kw_only=True)
class VRItemUseCompiler:
    """Choose the original selected-item button without another trigger click.

    Called only inside the input consumer's qualified, non-reentrant native
    left-up transaction. Prepare takes no action. Dispatch consumes that
    snapshot once, requires the same layer, protagonist and selected item,
    and accepts only a newly opened original menu belonging to that layer.
    Its unique visible enabled button must bind the canonical item verb to
    that exact menu receiver. The original handler owns puzzle conditions,
    actor approach, fallback responses, item consumption and menu destruction.

    Nothing is deferred to another frame. Failure leaves the native menu usable.
    The enclosing input transaction owns activation, tracking and exception
    cleanup. There is no new runtime switch or renderer protocol.
    """

    profile: BuildProfile

    section_name: ClassVar[str] = ".gk3iu"
    section_size: ClassVar[int] = 0x2000
    _magic: ClassVar[bytes] = b"GK3XRU01"
    _owner: ClassVar[int] = 0x10
    _item: ClassVar[int] = 0x14
    _verb: ClassVar[int] = 0x18
    _ego: ClassVar[int] = 0x1C
    _game_state: ClassVar[int] = 0x20
    _button: ClassVar[int] = 0x24
    _attempts: ClassVar[int] = 0x28
    _prepare: ClassVar[int] = 0x1000
    _dispatch: ClassVar[int] = 0x1200
    _anchors: ClassVar[tuple[str, ...]] = (
        "vr.active_inventory_item",
        "vr.inventory_item_verb",
        "vr.action_menu_receiver",
        "vr.action_menu_item_button",
        "vr.action_menu_handle",
        "vr.action_button_binding",
        "vr.button_enabled",
    )

    def abi(self, image: PEFile) -> VRItemUseABI:
        """Resolve only the current helper's fixed callable boundary."""
        section = image.get_section(self.section_name)
        if section is None or image.read_bytes(section.pointer_to_raw_data, 8) != self._magic:
            msg = "VR item use section is absent or incompatible"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        return VRItemUseABI(base + self._prepare, base + self._dispatch, base + self._attempts)

    def _check(self, image: PEFile) -> None:
        for name in self._anchors:
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = f"VR item use native anchor changed: {name}"
                raise PatchError(msg)

    def apply(self, image: PEFile) -> None:
        """Add inert helper code; the native input consumer supplies its calls."""
        if image.get_section(self.section_name) is not None:
            msg = "VR item use is already installed"
            raise PatchError(msg)
        self._check(image)
        section = image.add_section(self.section_name, bytes(self.section_size), 0xE0000060)
        base = image.rva_to_va(section.virtual_address)
        image.write_bytes(section.pointer_to_raw_data, self._payload(base))

    def postcheck(self, image: PEFile) -> None:
        """Verify original callees and every emitted byte independently."""
        self._check(image)
        base = self.abi(image).prepare_va - self._prepare
        if image.read_bytes(image.va_to_offset(base), self.section_size) != self._payload(base):
            msg = "VR item use payload failed verification"
            raise PatchError(msg)

    def _payload(self, base: int) -> bytes:
        payload = SegmentPayloadBuilder(
            owner="vr_item_use", segment=self.section_name, size=self.section_size
        )
        payload.place(label="item use identity", offset=0, payload=self._magic)
        payload.place(
            label="before native release", offset=self._prepare, payload=self._prepare_code(base)
        )
        payload.place(
            label="after native release", offset=self._dispatch, payload=self._dispatch_code(base)
        )
        return payload.build()

    def _prepare_code(self, base: int) -> bytes:
        e = X86Emitter(base_va=base + self._prepare)
        c = _UseCode(e, base, self.profile)
        e.raw(bytes.fromhex("9c 60"))
        c.store(self._owner, 0)
        c.absolute(b"\x83\x3d", self.profile.address("vr.action_menu_global"))
        e.raw(b"\0")
        e.jump_if(Condition.NOT_EQUAL, "return")
        e.call_absolute(self.profile.address("ui.current_layer"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "return")
        e.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("vr.room_layer_vtable")))
        e.jump_if(Condition.EQUAL, "owner")
        e.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("inventory.vtable")))
        e.jump_if(Condition.NOT_EQUAL, "return")
        e.label("owner")
        e.raw(bytes.fromhex("8b f0"))  # retain current layer across native accessors
        c.game_state()
        c.absolute(b"\x89\x0d", base + self._game_state)
        c.absolute(b"\x89\x15", base + self._ego)
        e.call_absolute(self.profile.site("vr.active_inventory_item").va)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "return")
        e.raw(bytes.fromhex("3d 8d 00 00 00"))
        e.jump_if(Condition.ABOVE, "return")
        c.absolute(b"\xa3", base + self._item)
        e.push_imm32(base + self._verb)
        e.raw(b"\x50")
        e.call_absolute(self.profile.site("vr.inventory_item_verb").va)
        e.raw(bytes.fromhex("83 c4 08"))
        c.absolute(b"\xa1", base + self._verb)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.LESS_OR_EQUAL, "return")
        e.raw(bytes.fromhex("3d 59 01 00 00"))
        e.jump_if(Condition.ABOVE, "return")
        c.absolute(b"\x89\x35", base + self._owner)
        e.label("return")
        e.raw(bytes.fromhex("61 9d c3"))
        return e.build(maximum_size=self._dispatch - self._prepare)

    def _dispatch_code(self, base: int) -> bytes:
        e = X86Emitter(base_va=base + self._dispatch)
        c = _UseCode(e, base, self.profile)
        e.raw(bytes.fromhex("9c 60"))
        c.absolute(b"\x8b\x35", base + self._owner)
        c.store(self._owner, 0)  # consume even if validation or the callback fails
        c.store(self._button, 0)
        e.raw(bytes.fromhex("85 f6"))
        e.jump_if(Condition.EQUAL, "return")
        e.call_absolute(self.profile.address("ui.current_layer"))
        e.raw(bytes.fromhex("3b c6"))
        e.jump_if(Condition.NOT_EQUAL, "return")
        c.game_state()
        c.absolute(b"\x3b\x0d", base + self._game_state)
        e.jump_if(Condition.NOT_EQUAL, "return")
        c.absolute(b"\x3b\x15", base + self._ego)
        e.jump_if(Condition.NOT_EQUAL, "return")
        e.call_absolute(self.profile.site("vr.active_inventory_item").va)
        c.absolute(b"\x3b\x05", base + self._item)
        e.jump_if(Condition.NOT_EQUAL, "return")
        c.absolute(b"\x8b\x1d", self.profile.address("vr.action_menu_global"))
        e.raw(bytes.fromhex("85 db"))
        e.jump_if(Condition.EQUAL, "return")
        e.raw(b"\x81\x3b" + struct.pack("<I", self.profile.address("vr.action_menu_vtable")))
        e.jump_if(Condition.NOT_EQUAL, "return")
        for offset in (0x18, 0x19):
            e.raw(bytes((0x80, 0x7B, offset, 0)))
            e.jump_if(Condition.EQUAL, "return")
        e.raw(bytes.fromhex("83 bb e0 00 00 00 00"))  # original target/NVC context
        e.jump_if(Condition.EQUAL, "return")
        e.raw(bytes.fromhex("80 bb 00 01 00 00 00"))  # native item-use mode
        e.jump_if(Condition.NOT_EQUAL, "return")
        c.children("root", owner="esi")
        e.label("root_child")
        e.raw(bytes.fromhex("3b 1a"))
        e.jump_if(Condition.EQUAL, "menu_owned")
        e.raw(bytes.fromhex("83 c2 04 49"))
        e.jump_if(Condition.NOT_EQUAL, "root_child")
        e.jump("return")
        e.label("menu_owned")
        c.children("menu", owner="ebx")
        e.label("menu_child")
        e.raw(bytes.fromhex("8b 02 85 c0"))
        e.jump_if(Condition.EQUAL, "next")
        e.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("ui.button_vtable")))
        e.jump_if(Condition.NOT_EQUAL, "next")
        for offset in (0x18, 0x19):
            e.raw(bytes((0x80, 0x78, offset, 0)))
            e.jump_if(Condition.EQUAL, "next")
        e.raw(bytes.fromhex("83 b8 98 00 00 00 03"))  # state 4 is disabled
        e.jump_if(Condition.ABOVE, "next")
        e.raw(bytes.fromhex("8b bb cc 00 00 00 85 ff"))
        e.jump_if(Condition.EQUAL, "return")
        e.raw(bytes.fromhex("3b b8 88 00 00 00"))
        e.jump_if(Condition.NOT_EQUAL, "next")
        c.absolute(b"\x8b\x3d", base + self._verb)
        e.raw(bytes.fromhex("3b b8 8c 00 00 00"))
        e.jump_if(Condition.NOT_EQUAL, "next")
        c.absolute(b"\x83\x3d", base + self._button)
        e.raw(b"\0")
        e.jump_if(Condition.NOT_EQUAL, "return")  # ambiguous delegate: leave normal menu
        c.absolute(b"\xa3", base + self._button)
        e.label("next")
        e.raw(bytes.fromhex("83 c2 04 49"))
        e.jump_if(Condition.NOT_EQUAL, "menu_child")
        c.absolute(b"\x83\x3d", base + self._button)
        e.raw(b"\0")
        e.jump_if(Condition.EQUAL, "return")
        c.absolute(b"\xff\x05", base + self._attempts)
        c.absolute(b"\xff\x35", base + self._verb)
        e.raw(bytes.fromhex("8d 8b c4 00 00 00"))
        e.call_absolute(self.profile.site("vr.action_menu_handle").va)
        # The callback destroys its menu. Do not inspect it or its button again.
        e.label("return")
        e.raw(bytes.fromhex("61 9d c3"))
        return e.build(maximum_size=self.section_size - self._dispatch)


@dataclass(frozen=True, slots=True)
class _UseCode:
    e: X86Emitter
    base: int
    profile: BuildProfile

    def absolute(self, opcode: bytes, address: int) -> None:
        self.e.raw(opcode + struct.pack("<I", address))

    def store(self, offset: int, value: int) -> None:
        self.absolute(b"\xc7\x05", self.base + offset)
        self.e.raw(struct.pack("<I", value))

    def game_state(self) -> None:
        """Resolve the native state and current protagonist without copied enums."""
        self.absolute(b"\xa1", self.profile.address("engine.loop"))
        for code in ("8b 80 44 04 00 00", "8b 48 38", "8b 50 60"):
            self.e.raw(bytes.fromhex("85 c0"))
            self.e.jump_if(Condition.EQUAL, "return")
            self.e.raw(bytes.fromhex(code))
        self.e.raw(bytes.fromhex("85 c9"))
        self.e.jump_if(Condition.EQUAL, "return")
        self.e.raw(bytes.fromhex("85 d2"))
        self.e.jump_if(Condition.EQUAL, "return")
        self.e.raw(bytes.fromhex("8b 52 20"))

    def children(self, label: str, *, owner: str) -> None:
        """Read one original, bounded, nonempty UI child vector."""
        self.e.label(label + "_children")
        self.e.raw(bytes.fromhex("8b 56 4c 8b 4e 50" if owner == "esi" else "8b 53 4c 8b 4b 50"))
        self.e.raw(bytes.fromhex("85 d2"))
        self.e.jump_if(Condition.EQUAL, "return")
        self.e.raw(bytes.fromhex("85 c9"))
        self.e.jump_if(Condition.EQUAL, "return")
        self.e.raw(bytes.fromhex("81 f9 00 01 00 00"))
        self.e.jump_if(Condition.ABOVE, "return")
