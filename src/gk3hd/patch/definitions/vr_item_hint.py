"""Read-only selected-item feedback through the original inventory mapping."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.vr_panel import VRPanelCompiler
from gk3hd.patch.model import PatchError
from gk3hd.vr.items import MAX_CATALOG_BYTES, encode_catalog, validate_catalog

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.vr_panel import VRPanelABI


@dataclass(frozen=True, slots=True)
class VRItemHintABI:
    """Display-only diagnostics. Activation belongs to the input consumer."""

    request_va: int
    presenter_va: int
    bridge_result_va: int


@dataclass(frozen=True, slots=True, kw_only=True)
class VRItemHintCompiler:
    """Publish canonical item names without changing picking or puzzle state.

    Query after ordinary input, on the game thread. Only an interactive Room
    or Inventory owner qualifies. Native actions, menus and all other pages
    withdraw the display. The renderer independently checks current tracking.
    Original icons/labels remain private immutable data in the compiled player.
    """

    profile: BuildProfile
    panel: VRPanelABI
    input_enabled_va: int
    world_ready_va: int
    expected_presenter_va: int
    catalog: bytes = b""

    section_name: ClassVar[str] = ".gk3ih"
    _magic: ClassVar[bytes] = b"GK3XRI01"
    _length: ClassVar[int] = 8
    _busy: ClassVar[int] = 0x0C
    _bridge: ClassVar[int] = 0x10
    _result: ClassVar[int] = 0x14
    _request: ClassVar[int] = 0x20  # size, inventory enum, canonical ASCII name[96]
    _code: ClassVar[int] = 0x1000
    _unwind: ClassVar[int] = 0x2000
    _renderer_name: ClassVar[int] = 0x2100
    _export_name: ClassVar[int] = 0x2120
    _catalog: ClassVar[int] = 0x3000

    @classmethod
    def catalog_bytes(cls, image: PEFile) -> bytes:
        """Read bounded data only; executable bytes are independently rebuilt."""
        section = image.get_section(cls.section_name)
        if section is None or image.read_bytes(section.pointer_to_raw_data, 8) != cls._magic:
            msg = "VR item hint section is absent or incompatible"
            raise PatchError(msg)
        length = image.read_u32_va(image.rva_to_va(section.virtual_address) + cls._length)
        if length > MAX_CATALOG_BYTES or cls._catalog + length > section.size_of_raw_data:
            msg = "VR item hint catalog exceeds its section"
            raise PatchError(msg)
        payload = image.read_bytes(section.pointer_to_raw_data + cls._catalog, length)
        try:
            validate_catalog(payload)
        except ValueError as error:
            msg = f"invalid VR item hint catalog: {error}"
            raise PatchError(msg) from error
        return payload

    def abi(self, image: PEFile) -> VRItemHintABI:
        """Read validated section diagnostics without trusting mutable state."""
        self.catalog_bytes(image)
        section = image.get_section(self.section_name)
        if section is None:
            msg = "VR item hint section is absent"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        return VRItemHintABI(base + self._request, base + self._code, base + self._result)

    def _check(self, image: PEFile) -> None:
        if VRPanelCompiler(profile=self.profile).abi(image) != self.panel:
            msg = "VR item hint panel boundary changed"
            raise PatchError(msg)
        for name in ("vr.active_inventory_item", "vr.inventory_item_name"):
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = f"VR item hint native anchor changed: {name}"
                raise PatchError(msg)
        image.va_to_offset(self.input_enabled_va)
        image.va_to_offset(self.world_ready_va)

    def _link(self, image: PEFile, target: int) -> ExecutableMutationPlan:
        plan = ExecutableMutationPlan(owner="vr_item_hint")
        plan.pointer(
            label="selected item presenter",
            slot_va=TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va,
            expected=self.expected_presenter_va,
            target_va=target,
        )
        return plan

    def apply(self, image: PEFile) -> None:
        """Install a consumer dormant with the normal input activation word."""
        if image.get_section(self.section_name) is not None:
            msg = "VR item hint is already installed"
            raise PatchError(msg)
        self._check(image)
        slot = TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va
        if not self.expected_presenter_va or image.read_u32_va(slot) != self.expected_presenter_va:
            msg = "VR item hint presenter changed"
            raise PatchError(msg)
        image.va_to_offset(self.expected_presenter_va)
        catalog = self.catalog or encode_catalog(())
        validate_catalog(catalog)
        size = (self._catalog + len(catalog) + 0xFFF) & ~0xFFF
        section = image.add_section(self.section_name, bytes(size), 0xE0000060)
        base = image.rva_to_va(section.virtual_address)
        image.write_bytes(section.pointer_to_raw_data, self._payload(base, catalog, size))
        self._link(image, base + self._code).apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Rebuild code and catalog, and verify the final presenter link."""
        self._check(image)
        section = image.get_section(self.section_name)
        if section is None:
            msg = "VR item hint section is absent"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        catalog = self.catalog or encode_catalog(())
        expected = self._payload(base, catalog, section.size_of_raw_data)
        if image.read_bytes(section.pointer_to_raw_data, len(expected)) != expected:
            msg = "VR item hint payload failed verification"
            raise PatchError(msg)
        self._link(image, base + self._code).verify(image)

    def _payload(self, base: int, catalog: bytes, size: int) -> bytes:
        e = X86Emitter(base_va=base + self._code)
        c = _HintCode(e, base)
        self._presenter(c)
        self._snapshot(c)
        self._bridge_call(c, len(catalog))
        payload = SegmentPayloadBuilder(owner="vr_item_hint", segment=self.section_name, size=size)
        header = bytearray(0x100)
        header[:8] = self._magic
        struct.pack_into("<I", header, self._length, len(catalog))
        struct.pack_into("<I", header, self._request, 104)
        struct.pack_into("<I", header, self._result, 0x80004001)
        payload.place(label="item hint state", offset=0, payload=bytes(header))
        payload.place(
            label="item snapshot", offset=self._code, payload=e.build(maximum_size=0x1000)
        )
        payload.place(label="item unwind", offset=self._unwind, payload=self._build_unwind(base))
        payload.place(label="item renderer", offset=self._renderer_name, payload=b"ddraw.dll\0")
        payload.place(label="item bridge", offset=self._export_name, payload=b"Gk3hdXrItemHintV1\0")
        payload.place(label="original item visuals", offset=self._catalog, payload=catalog)
        return payload.build()

    def _presenter(self, c: _HintCode) -> None:
        e = c.e
        e.raw(bytes.fromhex("9c 60"))
        c.absolute(b"\x83\x3d", c.base + self._busy)
        e.raw(b"\0")
        e.jump_if(Condition.NOT_EQUAL, "nested")
        e.push_imm32(c.base + self._unwind)
        e.raw(bytes.fromhex("64 ff 35 00 00 00 00 64 89 25 00 00 00 00"))
        c.store(self._busy, 1)
        e.call_absolute(self.expected_presenter_va)
        c.store(self._request + 4, 0)
        c.store(self._request + 8, 0)
        e.call("snapshot")
        e.call("bridge")
        c.store(self._busy, 0)
        e.raw(bytes.fromhex("8b 04 24 64 a3 00 00 00 00 83 c4 08"))
        e.jump("return")
        e.label("nested")
        e.call_absolute(self.panel.composition_presenter_va)
        e.label("return")
        e.raw(bytes.fromhex("61 9d c3"))

    def _snapshot(self, c: _HintCode) -> None:
        e, p = c.e, self.profile
        e.label("snapshot")
        for address, value in (
            (self.input_enabled_va, 1),
            (self.panel.enabled_va, 1),
            (self.panel.result_va, 0),
            (self.panel.completion_result_va, 0),
        ):
            c.absolute(b"\x83\x3d", address)
            e.raw(bytes((value,)))
            e.jump_if(Condition.NOT_EQUAL, "absent")
        c.absolute(b"\x83\x3d", self.panel.submitted_frames_va)
        e.raw(b"\0")
        e.jump_if(Condition.EQUAL, "absent")
        c.absolute(b"\xf7\x05", self.panel.frame_va + 64)
        e.raw(struct.pack("<I", 1))
        e.jump_if(Condition.EQUAL, "absent")
        c.absolute(b"\xa1", self.panel.pointing_hand_va)
        e.raw(bytes.fromhex("83 f8 01"))
        e.jump_if(Condition.ABOVE, "absent")
        e.raw(bytes.fromhex("6b c0 30"))
        c.absolute(b"\xf7\x80", self.panel.frame_va + 68)
        e.raw(struct.pack("<I", 1))
        e.jump_if(Condition.EQUAL, "absent")
        e.call_absolute(p.address("ui.current_layer"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "absent")
        e.raw(b"\x81\x38" + struct.pack("<I", p.address("vr.room_layer_vtable")))
        e.jump_if(Condition.EQUAL, "world_owner")
        e.raw(b"\x81\x38" + struct.pack("<I", p.address("inventory.vtable")))
        e.jump_if(Condition.NOT_EQUAL, "absent")
        e.jump("owner")
        e.label("world_owner")
        # The input consumer's frozen completed world boundary distinguishes
        # selectable rays from navigation-only fades and teleport preview.
        # A physical trigger state is not proof that teleport is actually armed.
        c.absolute(b"\x83\x3d", self.world_ready_va)
        e.raw(b"\x01")
        e.jump_if(Condition.NOT_EQUAL, "absent")
        e.label("owner")
        e.raw(bytes.fromhex("8b 50 4c 8b 48 50 81 f9 00 01 00 00"))
        e.jump_if(Condition.ABOVE, "absent")
        e.raw(bytes.fromhex("85 c9"))
        e.jump_if(Condition.EQUAL, "item")
        e.raw(bytes.fromhex("85 d2"))
        e.jump_if(Condition.EQUAL, "absent")
        e.label("child")
        e.raw(bytes.fromhex("8b 02 85 c0"))
        e.jump_if(Condition.EQUAL, "next_child")
        for offset in (0x18, 0x19):
            e.raw(bytes((0x80, 0x78, offset, 0)))
            e.jump_if(Condition.EQUAL, "next_child")
        for name in (
            "vr.action_menu_vtable",
            "vr.toolbar_vtable",
            "vr.action_skip_vtable",
            "console.vtable",
        ):
            e.raw(b"\x81\x38" + struct.pack("<I", p.address(name)))
            e.jump_if(Condition.EQUAL, "absent")
        e.label("next_child")
        e.raw(bytes.fromhex("83 c2 04 49"))
        e.jump_if(Condition.NOT_EQUAL, "child")
        e.label("item")
        c.absolute(b"\xa1", p.address("engine.loop"))
        for instruction in (bytes.fromhex("8b 80 44 04 00 00"), bytes.fromhex("8b 48 38")):
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.EQUAL, "absent")
            e.raw(instruction)
        e.raw(bytes.fromhex("85 c9"))
        e.jump_if(Condition.EQUAL, "absent")
        e.call_absolute(p.site("vr.active_inventory_item").va)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "absent")
        e.raw(bytes.fromhex("3d 8d 00 00 00"))
        e.jump_if(Condition.ABOVE, "absent")
        c.absolute(b"\xa3", c.base + self._request + 4)
        e.raw(b"\x50")
        e.call_absolute(p.site("vr.inventory_item_name").va)
        e.raw(bytes.fromhex("59 85 c0"))
        e.jump_if(Condition.EQUAL, "clear")
        e.raw(bytes.fromhex("8b f0"))
        e.raw(b"\xbf" + struct.pack("<I", c.base + self._request + 8))
        e.raw(bytes.fromhex("b9 60 00 00 00 fc"))
        e.label("name")
        e.raw(bytes.fromhex("ac aa 84 c0"))
        e.jump_if(Condition.EQUAL, "absent")
        e.raw(b"\x49")
        e.jump_if(Condition.NOT_EQUAL, "name")
        e.label("clear")
        c.store(self._request + 4, 0)
        c.store(self._request + 8, 0)
        e.label("absent")
        e.raw(b"\xc3")

    def _bridge_call(self, c: _HintCode, length: int) -> None:
        e = c.e
        e.label("bridge")
        c.store(self._result, 0x80004001)
        c.absolute(b"\x83\x3d", self.input_enabled_va)
        e.raw(b"\x01")
        e.jump_if(Condition.EQUAL, "resolve")
        c.absolute(b"\x83\x3d", c.base + self._bridge)
        e.raw(b"\0")
        e.jump_if(Condition.EQUAL, "bridge_return")
        e.jump("resolved")
        e.label("resolve")
        c.absolute(b"\x83\x3d", c.base + self._bridge)
        e.raw(b"\0")
        e.jump_if(Condition.NOT_EQUAL, "resolved")
        e.push_imm32(c.base + self._renderer_name)
        c.absolute(b"\xff\x15", self.profile.address("win32.GetModuleHandleA"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "bridge_return")
        e.push_imm32(c.base + self._export_name)
        e.raw(b"\x50")
        c.absolute(b"\xff\x15", self.profile.address("win32.GetProcAddress"))
        c.absolute(b"\xa3", c.base + self._bridge)
        e.label("resolved")
        c.absolute(b"\x83\x3d", c.base + self._bridge)
        e.raw(b"\0")
        e.jump_if(Condition.EQUAL, "bridge_return")
        c.absolute(b"\xa1", self.profile.address("high_resolution_3d.render_wrapper_ptr"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "bridge_return")
        e.raw(bytes.fromhex("8b 80 e8 04 00 00 85 c0"))
        e.jump_if(Condition.EQUAL, "bridge_return")
        for value in (length, c.base + self._catalog, c.base + self._request):
            e.push_imm32(value)
        e.raw(b"\x50")
        c.absolute(b"\xff\x15", c.base + self._bridge)
        c.absolute(b"\xa3", c.base + self._result)
        e.label("bridge_return")
        e.raw(b"\xc3")

    def _build_unwind(self, base: int) -> bytes:
        e = X86Emitter(base_va=base + self._unwind)
        e.raw(bytes.fromhex("8b 44 24 04 f7 40 04 66 00 00 00"))
        e.jump_if(Condition.EQUAL, "return")
        for offset in (self._busy, self._request + 4, self._request + 8):
            e.raw(b"\xc7\x05" + struct.pack("<II", base + offset, 0))
        e.raw(b"\xc7\x05" + struct.pack("<II", base + self._result, 0x80004005))
        e.label("return")
        e.raw(bytes.fromhex("b8 01 00 00 00 c3"))
        return e.build()


@dataclass(frozen=True, slots=True)
class _HintCode:
    e: X86Emitter
    base: int

    def absolute(self, opcode: bytes, address: int) -> None:
        self.e.raw(opcode + struct.pack("<I", address))

    def store(self, offset: int, value: int) -> None:
        self.absolute(b"\xc7\x05", self.base + offset)
        self.e.raw(struct.pack("<I", value))
