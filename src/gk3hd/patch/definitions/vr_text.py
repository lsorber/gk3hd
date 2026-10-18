"""Private render-thread text entry through qualified live native editors."""

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

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.vr_panel import VRPanelABI


@dataclass(frozen=True, slots=True)
class VRTextABI:
    """Single-slot, game-thread mailbox for the renderer's controller keyboard.

    Producer writes epoch, kind and value, then publishes request=1 last.
    Consumer clears request before dispatch. Kind 1 inserts printable ASCII;
    kind 2 is Backspace/Delete/Left/Right/Home/End. Kind 3 explicitly confirms
    the current editor through its native Return handler. Confirmation is a
    distinct deliberate action, not printable typing or an editing key.
    No Escape, clipboard or host events cross this boundary.
    A new focus/layer or tracking loss invalidates the published epoch.
    """

    enabled_va: int
    focus_va: int
    layer_va: int
    epoch_va: int
    request_va: int
    request_epoch_va: int
    kind_va: int
    value_va: int
    result_va: int
    accepted_va: int
    rejected_va: int
    keyboard_enabled_va: int
    keyboard_frame_va: int
    keyboard_result_va: int
    presenter_va: int


@dataclass(frozen=True, slots=True, kw_only=True)
class VRTextCompiler:
    """Qualify live native editors without changing their text or caret fields.

    The first child receiving native SaveGame character events, its class,
    visibility, enabled state and parent must agree with the current layer.
    SaveGame routes text to this child without registering manager keyboard
    focus, unlike generic editors. Input also requires a successful
    focused XR frame with a tracked selected hand. The private switch defaults
    off. A separate switch connects the renderer-owned keyboard through a
    fixed-width epoch/action bridge. Ordinary editors must be the first live
    recipient in the original ordered container dispatch, with the verified
    character/key handlers. Unknown handlers, damaged graphs and excessive
    traversal retire ownership, rather than guessing from buffer fields.
    """

    profile: BuildProfile
    panel: VRPanelABI
    expected_presenter_va: int

    section_name: ClassVar[str] = ".gk3vt"
    section_size: ClassVar[int] = 0x1000
    _magic: ClassVar[bytes] = b"GK3XRT01"
    _enabled: ClassVar[int] = 0x0C
    _focus: ClassVar[int] = 0x10
    _layer: ClassVar[int] = 0x14
    _epoch: ClassVar[int] = 0x18
    _request: ClassVar[int] = 0x1C
    _request_epoch: ClassVar[int] = 0x20
    _kind: ClassVar[int] = 0x24
    _value: ClassVar[int] = 0x28
    _result: ClassVar[int] = 0x2C
    _accepted: ClassVar[int] = 0x30
    _rejected: ClassVar[int] = 0x34
    _busy: ClassVar[int] = 0x38
    _hand: ClassVar[int] = 0x3C
    _keyboard_enabled: ClassVar[int] = 0x40
    _bridge: ClassVar[int] = 0x44
    _resolved: ClassVar[int] = 0x48
    _keyboard_result: ClassVar[int] = 0x4C
    _keyboard_frame: ClassVar[int] = 0x50
    _walk_budget: ClassVar[int] = 0x80
    _code: ClassVar[int] = 0x100
    _probe: ClassVar[int] = 0x600
    _unwind: ClassVar[int] = 0xA00
    _configure: ClassVar[int] = 0xB00
    _renderer_name: ClassVar[int] = 0xD00
    _export_name: ClassVar[int] = 0xD20
    _walk: ClassVar[int] = 0xE00
    _anchors: ClassVar[tuple[str, ...]] = (
        "vr.text_key",
        "vr.multiline_text_key",
        "vr.text_character",
        "vr.save_character",
        "vr.container_text_route",
        "vr.container_text_dispatch",
        "vr.no_text",
    )

    def abi(self, image: PEFile) -> VRTextABI:
        """Return the fixed-width private mailbox, never a native string pointer."""
        section = image.get_section(self.section_name)
        if section is None or image.read_bytes(section.pointer_to_raw_data, 8) != self._magic:
            msg = "VR text section is absent or incompatible"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        return VRTextABI(
            *(
                base + off
                for off in (
                    self._enabled,
                    self._focus,
                    self._layer,
                    self._epoch,
                    self._request,
                    self._request_epoch,
                    self._kind,
                    self._value,
                    self._result,
                    self._accepted,
                    self._rejected,
                    self._keyboard_enabled,
                    self._keyboard_frame,
                    self._keyboard_result,
                    self._code,
                )
            )
        )

    def _check(self, image: PEFile) -> None:
        if VRPanelCompiler(profile=self.profile).abi(image) != self.panel:
            msg = "VR text panel boundary changed"
            raise PatchError(msg)
        for name in self._anchors:
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = f"VR text native anchor changed: {name}"
                raise PatchError(msg)
        table = self.profile.address("savegame_edit.vtable")
        for off, target in ((0x64, "vr.text_key"), (0x6C, "vr.save_character")):
            if image.read_u32_va(table + off) != self.profile.site(target).va:
                msg = "VR text native editor dispatch changed"
                raise PatchError(msg)

        if (
            image.read_u32_va(self.profile.address("savegame.vtable") + 0x6C)
            != self.profile.site("vr.container_text_route").va
        ):
            msg = "VR text native save routing changed"
            raise PatchError(msg)

    def _link(self, image: PEFile, target: int) -> ExecutableMutationPlan:
        plan = ExecutableMutationPlan(owner="vr_text")
        plan.pointer(
            label="text presenter",
            slot_va=TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va,
            expected=self.expected_presenter_va,
            target_va=target,
        )
        return plan

    def apply(self, image: PEFile) -> None:
        """Install dormant text routing after the caller's verified presenter."""
        if image.get_section(self.section_name) is not None:
            msg = "VR text hooks are already installed"
            raise PatchError(msg)
        self._check(image)
        slot = TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va
        if image.read_u32_va(slot) != self.expected_presenter_va or not self.expected_presenter_va:
            msg = "VR text presenter changed"
            raise PatchError(msg)
        image.va_to_offset(self.expected_presenter_va)
        section = image.add_section(self.section_name, bytes(self.section_size), 0xE0000060)
        base = image.rva_to_va(section.virtual_address)
        image.write_bytes(section.pointer_to_raw_data, self._payload(base))
        self._link(image, base + self._code).apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Verify native anchors, mailbox code and its presentation link."""
        self._check(image)
        abi = self.abi(image)
        base = abi.enabled_va - self._enabled
        if image.read_bytes(image.va_to_offset(base), self.section_size) != self._payload(base):
            msg = "VR text payload failed verification"
            raise PatchError(msg)
        self._link(image, abi.presenter_va).verify(image)

    def _payload(self, base: int) -> bytes:
        e = X86Emitter(base_va=base + self._code)

        def state(op: bytes, offset: int) -> None:
            e.raw(op + struct.pack("<I", base + offset))

        def store(offset: int, value: int) -> None:
            state(b"\xc7\x05", offset)
            e.raw(struct.pack("<I", value))

        e.raw(bytes.fromhex("9c 60"))
        state(b"\x83\x3d", self._busy)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "nested")
        e.raw(b"\x68" + struct.pack("<I", base + self._unwind))
        e.raw(bytes.fromhex("64 ff 35 00 00 00 00 64 89 25 00 00 00 00"))
        store(self._busy, 1)
        e.call_absolute(self.expected_presenter_va)
        e.call_absolute(base + self._probe)  # EAX focus, EDX current layer
        state(b"\x3b\x05", self._focus)
        e.jump_if(Condition.NOT_EQUAL, "changed")
        state(b"\x3b\x15", self._layer)
        e.jump_if(Condition.NOT_EQUAL, "changed")
        e.raw(b"\x8b\x0d" + struct.pack("<I", self.panel.frame_va + 168))
        state(b"\x3b\x0d", self._hand)
        e.jump_if(Condition.EQUAL, "same")
        e.label("changed")
        state(b"\xff\x05", self._epoch)
        # Epoch zero is never a publishable target, including after wrap.
        state(b"\x83\x3d", self._epoch)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "same")
        state(b"\xff\x05", self._epoch)
        e.label("same")
        state(b"\xa3", self._focus)
        state(b"\x89\x15", self._layer)
        e.raw(b"\x8b\x0d" + struct.pack("<I", self.panel.frame_va + 168))
        state(b"\x89\x0d", self._hand)
        # Retrieve one renderer-produced action after current native ownership
        # is qualified. The renderer receives only epoch/availability values,
        # never a widget pointer. Manual diagnostic requests keep priority.
        e.call_absolute(base + self._configure)
        state(b"\x83\x3d", self._request)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "done")
        state(b"\x8b\x1d", self._request)
        # At-most-once, even if the callback nests painting or unwinds.
        store(self._request, 0)
        e.raw(bytes.fromhex("83 fb 01"))
        e.jump_if(Condition.NOT_EQUAL, "reject")
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "reject")
        state(b"\x8b\x0d", self._request_epoch)
        e.raw(bytes.fromhex("85 c9"))
        e.jump_if(Condition.EQUAL, "reject")
        state(b"\x3b\x0d", self._epoch)
        e.jump_if(Condition.NOT_EQUAL, "reject")
        e.raw(bytes.fromhex("8b f0"))
        state(b"\xa1", self._value)
        state(b"\x83\x3d", self._kind)
        e.raw(b"\x01")
        e.jump_if(Condition.NOT_EQUAL, "key")
        e.raw(bytes.fromhex("83 f8 20"))
        e.jump_if(Condition.BELOW, "reject")
        e.raw(bytes.fromhex("83 f8 7e"))
        e.jump_if(Condition.ABOVE, "reject")
        e.raw(bytes.fromhex("6a 01 50 8b ce"))
        e.raw(
            bytes.fromhex("81 3e") + struct.pack("<I", self.profile.address("savegame_edit.vtable"))
        )
        e.jump_if(Condition.EQUAL, "save_character")
        e.call_absolute(self.profile.site("vr.text_character").va)
        e.jump("accepted")
        e.label("save_character")
        e.call_absolute(self.profile.site("vr.save_character").va)
        e.jump("accepted")
        e.label("key")
        state(b"\x83\x3d", self._kind)
        e.raw(b"\x02")
        e.jump_if(Condition.NOT_EQUAL, "confirm")
        for value in (8, 46, 37, 39, 36, 35):
            e.raw(b"\x83\xf8" + bytes((value,)))
            e.jump_if(Condition.EQUAL, "edit_key")
        e.jump("reject")
        e.label("confirm")
        state(b"\x83\x3d", self._kind)
        e.raw(b"\x03")
        e.jump_if(Condition.NOT_EQUAL, "reject")
        e.raw(bytes.fromhex("83 f8 0d"))
        e.jump_if(Condition.NOT_EQUAL, "reject")
        e.label("edit_key")
        e.raw(b"\x8b\x0d" + struct.pack("<I", self.profile.address("engine.loop")))
        e.raw(bytes.fromhex("f7 81 18 05 00 00 38 00 00 00"))
        e.jump_if(Condition.NOT_EQUAL, "reject")
        e.raw(bytes.fromhex("6a 01 50 8b ce"))
        # Preserve the qualified editor's native Home/End and Return behavior.
        # Both handlers are byte-anchored; arbitrary virtual targets are never called.
        e.raw(
            bytes.fromhex("8b 16 81 7a 64")
            + struct.pack("<I", self.profile.site("vr.multiline_text_key").va)
        )
        e.jump_if(Condition.EQUAL, "multiline_key")
        e.call_absolute(self.profile.site("vr.text_key").va)
        e.jump("accepted")
        e.label("multiline_key")
        e.call_absolute(self.profile.site("vr.multiline_text_key").va)
        e.label("accepted")
        state(b"\xff\x05", self._accepted)
        store(self._result, 1)
        e.jump("done")
        e.label("reject")
        state(b"\xff\x05", self._rejected)
        store(self._result, 2)
        e.label("done")
        store(self._busy, 0)
        e.raw(bytes.fromhex("8b 04 24 64 a3 00 00 00 00 83 c4 08"))
        e.jump("return")
        e.label("nested")
        # Native edit callbacks can paint synchronously. Preserve the flat
        # composition, but do not sample XR or consume the mailbox again.
        if self.panel.composition_presenter_va:
            e.call_absolute(self.panel.composition_presenter_va)
        e.label("return")
        e.raw(bytes.fromhex("61 9d c3"))

        payload = SegmentPayloadBuilder(
            owner="vr_text", segment=self.section_name, size=self.section_size
        )
        header = bytearray(self._code)
        header[:8] = self._magic
        struct.pack_into("<I", header, self._keyboard_frame, 24)
        payload.place(label="text state", offset=0, payload=bytes(header))
        payload.place(
            label="text consumer", offset=self._code, payload=e.build(), limit=self._probe
        )
        payload.place(
            label="focus probe",
            offset=self._probe,
            payload=self._build_probe(base),
            limit=self._unwind,
        )
        payload.place(
            label="text unwind",
            offset=self._unwind,
            payload=self._build_unwind(base),
            limit=self._configure,
        )
        payload.place(
            label="keyboard configuration",
            offset=self._configure,
            payload=self._build_keyboard(base),
            limit=self._renderer_name,
        )
        payload.place(label="keyboard renderer", offset=self._renderer_name, payload=b"ddraw.dll\0")
        payload.place(label="keyboard export", offset=self._export_name, payload=b"Gk3hdXrTextV1\0")
        payload.place(
            label="native text recipient",
            offset=self._walk,
            payload=self._build_walk(base),
            limit=self.section_size,
        )
        return payload.build()

    def _build_keyboard(self, base: int) -> bytes:
        e = X86Emitter(base_va=base + self._configure)

        def state(op: bytes, offset: int) -> None:
            e.raw(op + struct.pack("<I", base + offset))

        def store(offset: int, value: int) -> None:
            state(b"\xc7\x05", offset)
            e.raw(struct.pack("<I", value))

        e.raw(b"\x60")  # Preserve the consumer's native focus and parent.
        state(b"\x83\x3d", self._keyboard_enabled)
        e.raw(b"\x01")
        e.jump_if(Condition.EQUAL, "resolve")
        # Disabling an already-connected keyboard must publish retirement.
        state(b"\x83\x3d", self._bridge)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "done")
        e.label("resolve")
        state(b"\x83\x3d", self._resolved)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "resolved")
        store(self._resolved, 1)
        state(b"\x68", self._renderer_name)
        e.raw(b"\xff\x15" + struct.pack("<I", self.profile.address("win32.GetModuleHandleA")))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "done")
        state(b"\x68", self._export_name)
        e.raw(b"\x50\xff\x15" + struct.pack("<I", self.profile.address("win32.GetProcAddress")))
        state(b"\xa3", self._bridge)
        e.label("resolved")
        state(b"\x83\x3d", self._bridge)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "done")
        store(self._keyboard_frame + 4, 0)
        store(self._keyboard_frame + 8, 0)
        for off in (12, 16, 20):
            store(self._keyboard_frame + off, 0)
        state(b"\x83\x3d", self._keyboard_enabled)
        e.raw(b"\x01")
        e.jump_if(Condition.NOT_EQUAL, "configured")
        state(b"\x83\x3d", self._focus)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "configured")
        state(b"\xa1", self._epoch)
        state(b"\xa3", self._keyboard_frame + 4)
        e.raw(bytes.fromhex("31 c0"))
        state(b"\x83\x3d", self._request)
        e.raw(bytes.fromhex("00 0f 94 c0"))
        state(b"\xa3", self._keyboard_frame + 8)
        e.label("configured")
        e.raw(
            b"\xa1"
            + struct.pack("<I", self.profile.address("high_resolution_3d.render_wrapper_ptr"))
        )
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "done")
        e.raw(bytes.fromhex("8b 80 e8 04 00 00 85 c0"))
        e.jump_if(Condition.EQUAL, "done")
        state(b"\x68", self._keyboard_frame)
        e.raw(b"\x50")
        state(b"\xff\x15", self._bridge)
        state(b"\xa3", self._keyboard_result)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "done")
        for offset, value in ((self._keyboard_enabled, 1), (self._request, 0)):
            state(b"\x83\x3d", offset)
            e.raw(bytes((value,)))
            e.jump_if(Condition.NOT_EQUAL, "done")
        state(b"\xa1", self._keyboard_frame + 16)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "done")
        state(b"\xa3", self._kind)
        state(b"\xa1", self._keyboard_frame + 20)
        state(b"\xa3", self._value)
        state(b"\xa1", self._keyboard_frame + 12)
        state(b"\xa3", self._request_epoch)
        store(self._request, 1)  # Publish last, after all event fields.
        e.label("done")
        e.raw(bytes.fromhex("61 c3"))
        return e.build()

    def _build_probe(self, base: int) -> bytes:
        e = X86Emitter(base_va=base + self._probe)
        e.raw(bytes.fromhex("53 56 57"))
        for address in (base + self._enabled, self.panel.enabled_va):
            e.raw(b"\x83\x3d" + struct.pack("<I", address) + b"\x01")
            e.jump_if(Condition.NOT_EQUAL, "absent")
        for address in (self.panel.result_va, self.panel.completion_result_va):
            e.raw(b"\x83\x3d" + struct.pack("<I", address) + b"\x00")
            e.jump_if(Condition.NOT_EQUAL, "absent")
        frame = self.panel.frame_va
        e.raw(b"\xf7\x05" + struct.pack("<II", frame + 64, 1))
        e.jump_if(Condition.EQUAL, "absent")
        e.raw(b"\xa1" + struct.pack("<I", frame + 168) + bytes.fromhex("83 f8 01"))
        e.jump_if(Condition.ABOVE, "absent")
        e.raw(bytes.fromhex("6b c0 30 83 b8") + struct.pack("<I", frame + 68) + b"\x01")
        e.jump_if(Condition.NOT_EQUAL, "absent")

        def readable(size: int) -> None:
            e.raw(
                b"\x68"
                + struct.pack("<I", size)
                + b"\x56\xff\x15"
                + struct.pack("<I", self.profile.address("win32.IsBadReadPtr"))
            )
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.NOT_EQUAL, "absent")

        e.raw(b"\x8b\x35" + struct.pack("<I", self.profile.address("engine.loop")))
        readable(0x51C)  # Native edit keys inspect the current modifier flags.
        e.call_absolute(self.profile.address("ui.current_layer"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "absent")
        e.raw(bytes.fromhex("8b f0 8b d8"))  # ESI/EBX current native root
        readable(0x54)
        e.raw(b"\x81\x3e" + struct.pack("<I", self.profile.address("savegame.vtable")))
        e.jump_if(Condition.NOT_EQUAL, "container")
        e.raw(bytes.fromhex("8b 46 50 48 3d ff 00 00 00"))
        e.jump_if(Condition.ABOVE, "absent")
        e.raw(bytes.fromhex("8b 76 4c"))
        readable(4)
        e.raw(bytes.fromhex("8b 36 8d 83 40 03 00 00 3b f0"))
        e.jump_if(Condition.NOT_EQUAL, "absent")
        readable(0x7C)
        e.raw(b"\x81\x3e" + struct.pack("<I", self.profile.address("savegame_edit.vtable")))
        e.jump_if(Condition.NOT_EQUAL, "absent")
        for off in (0x18, 0x19):
            e.raw(bytes((0x80, 0x7E, off, 0)))
            e.jump_if(Condition.EQUAL, "absent")
        e.raw(bytes.fromhex("3b 5e 78"))
        e.jump_if(Condition.NOT_EQUAL, "absent")
        e.jump("present")
        e.label("container")
        e.raw(b"\xc7\x05" + struct.pack("<II", base + self._walk_budget, 256))
        e.raw(bytes.fromhex("31 c9"))
        e.call_absolute(base + self._walk)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.LESS_OR_EQUAL, "absent")
        e.raw(bytes.fromhex("8b f0"))
        e.label("present")
        e.raw(bytes.fromhex("8b d3 8b c6 5f 5e 5b c3"))
        e.label("absent")
        e.raw(bytes.fromhex("31 c0 31 d2 5f 5e 5b c3"))
        return e.build()

    def _build_walk(self, base: int) -> bytes:
        """Resolve original ordered container dispatch, bounded and read-only.

        ESI is a node, ECX depth. EAX is zero for no recipient, -1 for an
        unqualified route, or the exact first editor. Preserve all other
        registers, including the probe's current root. Do not treat an editor
        as a container just because its unrelated fields resemble a child list.
        """
        e = X86Emitter(base_va=base + self._walk)
        e.raw(bytes.fromhex("60 8b e9 85 f6"))
        e.jump_if(Condition.EQUAL, "none")
        e.raw(b"\xff\x0d" + struct.pack("<I", base + self._walk_budget))
        e.jump_if(Condition.LESS, "invalid")
        e.raw(bytes.fromhex("83 fd 08"))
        e.jump_if(Condition.ABOVE, "invalid")

        def readable(size: int, push: bytes = b"\x56") -> None:
            e.push_imm32(size)
            e.raw(
                push + b"\xff\x15" + struct.pack("<I", self.profile.address("win32.IsBadReadPtr"))
            )
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.NOT_EQUAL, "invalid")

        readable(0x1A)
        e.raw(bytes.fromhex("8b 3e"))
        readable(0x70, b"\x57")
        e.raw(bytes.fromhex("8b 47 6c 3d") + struct.pack("<I", self.profile.site("vr.no_text").va))
        e.jump_if(Condition.EQUAL, "none")
        e.raw(b"\x3d" + struct.pack("<I", self.profile.site("vr.text_character").va))
        e.jump_if(Condition.NOT_EQUAL, "container")
        e.raw(bytes.fromhex("81 7f 64") + struct.pack("<I", self.profile.site("vr.text_key").va))
        e.jump_if(Condition.EQUAL, "single_line")
        e.raw(
            bytes.fromhex("81 7f 64")
            + struct.pack("<I", self.profile.site("vr.multiline_text_key").va)
        )
        e.jump_if(Condition.NOT_EQUAL, "invalid")
        readable(0x98)  # Multiline Home/End inspect the original line-list fields.
        e.jump("editor_font")
        e.label("single_line")
        readable(0x78)
        e.label("editor_font")
        e.raw(bytes.fromhex("8b 7e 2c"))
        readable(0x360, b"\x57")  # Original character handler's font map.
        e.raw(bytes.fromhex("8b c6"))
        e.jump("qualified")
        e.label("container")
        e.raw(b"\x3d" + struct.pack("<I", self.profile.site("vr.container_text_route").va))
        e.jump_if(Condition.NOT_EQUAL, "invalid")
        readable(0x54)
        e.raw(bytes.fromhex("8b 7e 50 81 ff 00 01 00 00"))
        e.jump_if(Condition.ABOVE, "invalid")
        e.raw(bytes.fromhex("85 ff"))
        e.jump_if(Condition.EQUAL, "none")
        e.raw(
            bytes.fromhex("8b 5e 4c 8d 04 bd 00 00 00 00 50 53 ff 15")
            + struct.pack("<I", self.profile.address("win32.IsBadReadPtr"))
        )
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "invalid")
        e.label("children")
        e.raw(bytes.fromhex("56 8b 33 8b cd 41"))
        e.call_absolute(base + self._walk)
        e.raw(bytes.fromhex("5e 85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "qualified")
        e.raw(bytes.fromhex("83 c3 04 4f"))
        e.jump_if(Condition.NOT_EQUAL, "children")
        e.label("none")
        e.raw(bytes.fromhex("31 c0"))
        e.jump("done")
        e.label("invalid")
        e.raw(bytes.fromhex("b8 ff ff ff ff"))
        e.jump("done")
        e.label("qualified")
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.LESS, "done")
        # Original container character dispatch walks hidden children too.
        # Verify the first recipient's whole visible/enabled ancestor path,
        # rather than skipping a hidden recipient and typing into a later one.
        for off in (0x18, 0x19):
            e.raw(bytes((0x80, 0x7E, off, 0)))
            e.jump_if(Condition.EQUAL, "invalid")
        e.label("done")
        e.raw(bytes.fromhex("89 44 24 1c 61 c3"))
        return e.build()

    def _build_unwind(self, base: int) -> bytes:
        e = X86Emitter(base_va=base + self._unwind)
        e.raw(bytes.fromhex("8b 44 24 04 f7 40 04 66 00 00 00"))
        e.jump_if(Condition.EQUAL, "return")
        for off in (self._focus, self._layer, self._request, self._busy):
            e.raw(b"\xc7\x05" + struct.pack("<I", base + off) + bytes(4))
        e.raw(b"\xff\x05" + struct.pack("<I", base + self._epoch))
        e.raw(b"\xc7\x05" + struct.pack("<II", base + self._result, 3))
        e.label("return")
        e.raw(bytes.fromhex("b8 01 00 00 00 c3"))  # ExceptionContinueSearch
        return e.build()
